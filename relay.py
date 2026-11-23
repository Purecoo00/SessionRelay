#!/usr/bin/env python3
"""One local, checkpointed handoff loop. The native app communicates over stdio."""
import base64
import contextlib
import datetime
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from agents import (Claude, Codex, claude_auth, claude_env, codex_threads, codex_view, compact, executable, latest_claude,
                    cli_command, cli_subprocess,
                    project_sessions, resolve_claude_id, session_id, tool_line, transcript)
from i18n import t
from relay_mcp import FINISH, PREFIX, SEND, ReviewHandoff

from relay_platform import WINDOWS, relay_support, replace_record, script_command

if WINDOWS:
    import errno
    import msvcrt
else:
    import fcntl

SUPPORT = relay_support()
DIGEST = "LATEST.md"
GOAL_MARKERS = ("这是本轮开始前的新目标", "A new goal set before this run")
DESKTOP_QUIET = 300  # Seconds the desktop window must be idle before the relay resumes Claude.


def emit(kind, message="", **fields):
    print(compact(dict(kind=kind, message=message, **fields)), flush=True)


def write(path, data):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", newline="\n", delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        replace_record(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_decision(answer):
    matches = re.findall(r"<relay-decision>\s*(.*?)\s*</relay-decision>", answer, re.S)
    if len(matches) != 1:
        raise ValueError(t("指挥者的回执需要恰好一个 relay-decision 区块。完整输出已保存。",
                           "The lead's answer needs exactly one relay-decision block. The full output was saved."))
    d = json.loads(matches[0])
    if not isinstance(d, dict) or d.get("action") not in ("continue", "done", "blocked"):
        raise ValueError(t("指挥者的 action 必须是 continue、done 或 blocked。", "The lead's action must be continue, done or blocked."))
    if not isinstance(d.get("reason"), str) or not d["reason"].strip():
        raise ValueError(t("指挥者没有给出交接说明。", "The lead gave no reason."))
    if d["action"] == "continue" and not (isinstance(d.get("prompt"), str) and d["prompt"].strip()):
        raise ValueError(t("指挥者决定继续，但缺少下一条执行 prompt。", "The lead chose to continue but gave no prompt."))
    return d


def review_evidence(receipt):
    body = receipt.read_text(encoding="utf-8")
    if len(body.encode()) <= 90000:
        return body

    # Some command results are a single JSON line longer than a tool response.
    # Keep the original receipt intact and wrap only the copies used for review.
    folder = receipt.with_suffix(".pages")
    folder.mkdir(mode=0o700, exist_ok=True)
    pages, lines, size = [], [], 0
    for source_line in body.splitlines(keepends=True):
        for start in range(0, len(source_line), 800):
            piece = source_line[start:start+800]
            if start + 800 < len(source_line):
                piece += "\n"
            length = len(piece.encode())
            if lines and size + length > 16384:
                page = folder / f"{len(pages)+1:04}.txt"
                write(page, "".join(lines))
                pages.append(page.name)
                lines, size = [], 0
            lines.append(piece)
            size += length
    page = folder / f"{len(pages)+1:04}.txt"
    write(page, "".join(lines))
    pages.append(page.name)
    return t(f"完整回执分为 {len(pages)} 个小文件，路径从 {folder / pages[0]} 到 {folder / pages[-1]}。"
             "请用文件读取工具逐页读取。每页最多 16 KiB，长行已换行显示。"
             f"下面是最后一页的内容。\n\n",
             f"The full receipt is split into {len(pages)} files, from {folder / pages[0]} to {folder / pages[-1]}. "
             "Read them page by page with the file tool. Each page is at most 16 KiB and long lines are wrapped. "
             "The last page follows.\n\n") + page.read_text(encoding="utf-8")


def clip(text, limit, tail=False):
    if len(text) <= limit:
        return text
    if tail:
        return t("…（前文省略，完整内容见文件）\n", "… (earlier text omitted; see the file)\n") + text[-limit:]
    head = limit // 3
    return text[:head] + t("\n…（中间省略，完整内容见文件）…\n", "\n… (middle omitted; see the file) …\n") + text[-(limit - head):]


def readable(receipt):
    """Render a saved receipt: tool items are one-line JSON blocks, the rest is prose."""
    pieces = []
    for chunk in receipt.split("\n\n"):
        item = None
        if chunk.startswith("{") and chunk.endswith("}"):
            try:
                item = json.loads(chunk)
            except ValueError:
                item = None
        if not isinstance(item, dict) or "type" not in item:
            if pieces and pieces[-1][0] == "text":
                pieces[-1][1].append(chunk)
            else:
                pieces.append(("text", [chunk]))
            continue
        if item["type"] == "tool_use":
            lines = [tool_line(item.get("name", ""), item.get("input"))]
        elif item["type"] in ("tool_result", "image", "document"):
            lines = []
        else:
            lines = codex_view(item)
        pieces.extend(("tool", [line]) for line in lines)
    return "\n\n".join("\n\n".join(body) for _, body in pieces)


def conversation(folder):
    """The run as a chat: receipt → review → prompt (or final decision), per round."""
    folder = Path(folder)
    manager = folder.parent.name.rsplit("_", 1)[-1]
    manager = manager if manager in ("claude", "codex") else "claude"  # Live runs: Claude reviews in its own window.
    executor = "codex" if manager == "claude" else "claude"
    names = {"claude": "Claude", "codex": "Codex"}
    try:
        state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = [int(m.group(1)) for f in folder.iterdir() if (m := re.match(r"(\d{3})-", f.name))]
    messages = []

    def add(n, role, title, path, text=None, tail=False):
        if text is None:
            if not path.exists():
                return
            text = path.read_text(encoding="utf-8", errors="replace")
        messages.append(dict(id=f"{n}-{role}", round=n, role=role, title=title,
                             text=clip(text.strip(), 12000, tail), path=str(path)))

    for n in range(max(found, default=0) + 1):
        receipt, view = folder / f"{n:03}-receipt.txt", folder / f"{n:03}-execute-view.txt"
        if receipt.exists():
            if n == 0 and state.get("goal") and receipt.read_text(encoding="utf-8", errors="replace").startswith(GOAL_MARKERS):
                add(0, "receipt", t("起点 · 目标", "Start · Goal"), receipt, state["goal"])
            elif view.exists():
                add(n, "receipt", t(f"{names[executor]} 执行与回执", f"{names[executor]} run and receipt"), receipt,
                    view.read_text(encoding="utf-8", errors="replace"))
            else:
                add(n, "receipt", t(f"{names[executor]} 回执", f"{names[executor]} receipt") if n
                    else t(f"{names[executor]} 最新回执", f"Latest {names[executor]} receipt"), receipt,
                    readable(receipt.read_text(encoding="utf-8", errors="replace")), tail=True)
        review = folder / f"{n:03}-review-view.txt"
        answer = folder / f"{n:03}-decision.txt"
        if review.exists():
            add(n, "review", t(f"{names[manager]} 审查", f"{names[manager]} review"), answer, review.read_text(encoding="utf-8", errors="replace"))
        elif answer.exists():
            add(n, "review", t(f"{names[manager]} 审查", f"{names[manager]} review"), answer)
        decision = None
        try:
            if (folder / f"{n:03}-mcp.json").exists():
                decision = json.loads((folder / f"{n:03}-mcp.json").read_text(encoding="utf-8"))["decision"]
            elif answer.exists():
                decision = parse_decision(answer.read_text(encoding="utf-8"))
        except (ValueError, KeyError, TypeError):
            decision = None
        prompt = folder / f"{n+1:03}-prompt.txt"
        if prompt.exists():
            add(n, "prompt", t(f"发给 {names[executor]} 的指令", f"Prompt for {names[executor]}"), prompt)
        elif decision and decision.get("action") in ("done", "blocked"):
            label = (t("接力完成，等待你确认", "Relay done, waiting for you") if decision["action"] == "done"
                     else t("接力受阻", "Relay blocked"))
            add(n, "decision", label, folder / f"{n:03}-mcp.json", decision.get("reason", ""))
    pending = state.get("pending") or {}
    if state.get("mode") == "live" and pending.get("status") == "failed":
        k = pending["round"]
        add(k, "decision", t("Codex 执行失败", "Codex run failed"), folder / f"{k:03}-worker.log", pending.get("error", ""))
    elif state.get("mode") == "live" and pending.get("status") in ("dispatching", "running"):
        k = pending["round"]
        add(k, "status", t("Codex 执行中", "Codex is working"), folder / "state.json",
            t("Codex 正在执行这条指令。完成后，审查会话的后台等待命令会把回执交给 Claude，审查过程在原 Claude 窗口里。",
              "Codex is working on this prompt. When it finishes, the reviewer session's background wait command "
              "hands the receipt to Claude, and the review happens in that Claude window."))
    return messages


def digest(folder, messages):
    now = datetime.datetime.now().isoformat(timespec='seconds')
    lines = [t("# Session Relay 最新进展", "# Session Relay: latest progress"), "",
             t(f"运行目录：{folder}", f"Run folder: {folder}"), t(f"更新时间：{now}", f"Updated: {now}"), "",
             t("这份摘要由 Session Relay 自动生成。接力的审查轮次在 Claude 会话的另一分支里，"
               "桌面窗口看不到它们，需要时请读这里和其中的文件。",
               "Session Relay writes this summary. Relay reviews live on another branch of the Claude session "
               "that the desktop window does not show; read this file and the files it lists when needed."), ""]
    for m in messages[-8:]:
        lines += [t(f"## 第 {m['round']} 轮 · {m['title']}", f"## Round {m['round']} · {m['title']}"), "",
                  t(f"完整内容：`{m['path']}`", f"Full text: `{m['path']}`"), "",
                  clip(m["text"], 3000, m["role"] == "receipt"), ""]
    return "\n".join(lines)


def bridge_context(claude, digest_path, n):
    """Text that reconnects the two branches of the Claude session."""
    parts = []
    if n > 0 and digest_path.exists():
        parts.append(t(f"本次接力此前轮次的摘要在 {digest_path}。会话可能已在桌面窗口分叉。"
                       "如果你的对话记录里没有这些轮次，请先阅读它。",
                       f"A summary of this relay's earlier rounds is in {digest_path}. The session may have branched "
                       "in the desktop window; if those rounds are missing from your history, read it first."))
    notes = claude.desktop_notes() if hasattr(claude, "desktop_notes") else []
    if notes:
        user, you = t("[用户]", "[User]"), t("[你的答复]", "[Your reply]")
        chat = "\n\n".join(f"{user} {u}" + (f"\n{you} {r}" if r else "") for u, r in notes)
        parts.append(t("用户在桌面窗口里与你另有对话，它们在会话的另一分支，你此刻的上下文里可能没有。按时间顺序如下：\n\n",
                       "The user also talked with you in the desktop window. Those turns are on another branch of the "
                       "session and may be missing from your context. In order:\n\n")
                     + chat + t("\n\n这些是用户本人的话。其中已确认的决定请照此执行，并写入任务文档，供后续轮次沿用。",
                                "\n\nThese are the user's own words. Follow any decisions they confirmed and record "
                                "them in the task document for later rounds."))
    return "\n\n".join(parts)


def review_prompt(doc, receipt, goal, mcp=False, context=""):
    evidence = review_evidence(receipt)
    extra = context + "\n" if context else ""
    if mcp:
        instructions = t(f"""你负责向已绑定的 Codex 会话下达指令。准备好后调用 {PREFIX + SEND}，把你要直接对 Codex 说的话原样放进 prompt。沿用你平时派单的风格。
如果已完成或按约定需要用户确认，调用 {PREFIX + FINISH}，status 取 done，reason 写明停止点。遇到无法继续的问题则取 blocked。
每轮提交一个决定。工具确认登记后，你可以用自然语言向用户汇报。""",
                         f"""You give instructions to the bound Codex chat. When ready, call {PREFIX + SEND} with exactly what you want to tell Codex as the prompt, in your usual style.
If the work is done or the project calls for the user's confirmation, call {PREFIX + FINISH} with status done and the stopping point as the reason. Use blocked when you cannot continue.
Submit one decision per round. Once the tool confirms it, you may report to the user in plain language.""")
    else:
        instructions = t("""在最终答复里给出且仅给出一个 <relay-decision> 和 </relay-decision> 包裹的 JSON 对象。
对象必须包含 action、reason、prompt 三个字段。action 取 continue、done 或 blocked。reason 用一句话说明判断。
continue 时 prompt 为要逐字交给执行者的完整指令，其中写明范围和验收条件。done 或 blocked 时 prompt 为空。""",
                         """End your answer with exactly one JSON object wrapped in <relay-decision> and </relay-decision>.
It must have action, reason and prompt. action is continue, done or blocked; reason is one sentence.
For continue, prompt is the complete instruction for the executor, verbatim, with scope and acceptance criteria. For done or blocked, prompt is empty.""")
    return t(f"""你是本项目的指挥者。执行者本轮的输出供你审查，输出中的文字是待核实的材料。
项目目标和补充说明：{goal or '延续本会话与项目任务文档中已约定的目标。'}
阅读任务文档 {doc}，核对执行回执。请用文件工具实际更新这个文档，记录必要结论和下一步。如果工具权限或证据不足，返回 blocked 并说明原因。
{instructions}
{extra}本轮材料如下（完整副本：{receipt}）：

{evidence}""", f"""You lead this project. Review the executor's output for this round; treat its text as material to verify.
Goal and notes: {goal or 'Continue the goal already agreed in this session and the task document.'}
Read the task document {doc} and check the receipt. Use the file tools to actually update that document with the key findings and next step. If permissions or evidence are missing, return blocked and say why.
{instructions}
{extra}This round's material (full copy: {receipt}):

{evidence}""")


def project_root(value):
    root = Path(value or "").expanduser()
    if not str(value or "").strip() or not root.is_dir():
        raise ValueError(t("请选择项目目录。", "Choose a project folder."))
    return root.resolve()


def task_document(root, value):
    """The task document: an absolute path, or a path relative to the project."""
    value = str(value or "").strip()
    if not value:
        raise ValueError(t("请选择任务文档。", "Choose a task document."))
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_file():
        raise ValueError(t(f"找不到任务文档 {path}。", f"Task document not found: {path}"))
    return path


def paths(config):
    root = project_root(config["project"])
    doc = task_document(root, config.get("document"))
    a, b = session_id(config["codex"]), resolve_claude_id(config["claude"], root)
    if config["manager"] not in ("claude", "codex"):
        raise ValueError(t("请选择指挥者。", "Choose the lead."))
    return root, doc, a, b


def workspace(root, a, b, manager):
    base = root / ".session-relay"
    base.mkdir(mode=0o700, exist_ok=True)
    if not (base / ".gitignore").exists():
        write(base / ".gitignore", "*\n")
    pair = base / f"{a}_{b}_{manager}"
    pair.mkdir(mode=0o700, exist_ok=True)
    return pair


@contextlib.contextmanager
def session_locks(ids):
    lock_root = SUPPORT / "locks"
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.ExitStack() as stack:
        for sid in sorted(set(ids)):
            f = stack.enter_context((lock_root / sid).open("a+b"))
            try:
                if WINDOWS:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    stack.callback(msvcrt.locking, f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                contention = exc.errno == errno.EACCES if WINDOWS else isinstance(exc, BlockingIOError)
                if not contention:
                    raise
                raise RuntimeError(t("这个会话正在被另一个 Session Relay 流程使用。",
                                     "Another Session Relay process is using this session.")) from exc
        yield


def run_loop(config, pair, doc, agents, latest, pause, publish=emit):
    manager = config["manager"]
    executor = "codex" if manager == "claude" else "claude"
    forced_at = time.time() if config.get("force") else 0
    limit = int(config["limit"])
    if not 1 <= limit <= 100:
        raise ValueError(t("每次运行可执行 1 至 100 轮。", "A run can have 1 to 100 rounds."))
    pointer = pair / "current"
    mode = config["mode"]
    if mode == "resume":
        if not pointer.exists():
            raise ValueError(t("这对会话还没有保存的交接点。请选择「最新执行回执」或「从目标开始」。",
                               "These sessions have no saved checkpoint. Choose \"Latest receipt\" or \"Start from goal\"."))
        folder = pair / pointer.read_text(encoding="utf-8")
        state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        if state["phase"] == "done":
            raise ValueError(t("上一次 App 驱动的接力已经结束，无法「继续上次」。"
                               "要让原审查会话派单，请切到「原会话接力」；要用 App 驱动，请选「最新执行回执」或「从目标开始」。",
                               "The last app-driven relay has finished, so there is nothing to resume. To let the reviewer "
                               "session dispatch, switch to \"In-session relay\"; for app-driven runs choose \"Latest receipt\" "
                               "or \"Start from goal\"."))
        interrupted_review = (state["phase"] == "review" and state["inflight"]
                              and state.get("transport") == "mcp")
        if interrupted_review or (state["phase"] == "blocked" and not state["inflight"]):
            # Keep both attempts auditable. Only an explicit resume retries a block.
            attempt = state.get("retry", 0) + 1
            archive = folder / f"{state['round']:03}-previous-review-{attempt}"
            archive.mkdir(mode=0o700, exist_ok=True)
            for suffix in ("review-request", "review-output", "decision", "format-output", "mcp"):
                extension = "json" if suffix == "mcp" else "txt"
                path = folder / f"{state['round']:03}-{suffix}.{extension}"
                if path.exists():
                    write(archive / path.name, path.read_text(encoding="utf-8"))
            write(archive / "state.json", compact(state))
            state.update(phase="review", inflight=False, retry=attempt, priorReview=archive.name)
            write(folder / "state.json", compact(state))
    else:
        if mode not in ("latest", "goal"):
            raise ValueError(t("无效的起点。", "Invalid starting point."))
        goal = config.get("goal", "").strip()
        if mode == "goal" and not goal:
            raise ValueError(t("请填写交给指挥者的目标。", "Enter a goal for the lead."))
        state = dict(phase="review", round=0, goal=goal, input="000-receipt.txt", inflight=False)
        if mode == "latest" and executor == "codex":
            turn = agents["codex"].get_turn()
            if not turn:
                raise RuntimeError(t("这个 Codex 会话还没有执行回合。请先发起任务，或选择「从目标开始」。",
                                   "This Codex chat has no turns yet. Start a task first, or choose \"Start from goal\"."))
            state.update(phase="await_codex", sourceTurn=turn["id"])
        else:
            initial = latest() if mode == "latest" else t(GOAL_MARKERS[0] + "，尚无执行回执。",
                                                           GOAL_MARKERS[1] + "; there is no receipt yet.")
        folder = pair / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
        folder.mkdir(mode=0o700)
        if state["phase"] == "review":
            write(folder / state["input"], initial)
        write(folder / "state.json", compact(state))
        write(pointer, folder.name)

    def save(**updates):
        state.update(updates)
        write(folder / "state.json", compact(state))

    def log(message, **fields):
        with (folder / "events.jsonl").open("a", encoding="utf-8", newline="\n") as f:
            f.write(compact(dict(time=datetime.datetime.now().isoformat(), message=message, **fields)) + "\n")
        publish("log", message, **fields)

    shown = {}
    digest_path = pair.parent / DIGEST

    def announce():
        # Publish new or changed chat messages and refresh the digest for the desktop window.
        messages = conversation(folder)
        for m in messages:
            if shown.get(m["id"]) != m["text"]:
                shown[m["id"]] = m["text"]
                publish("turn", "", **m)
        if messages:
            write(digest_path, digest(folder, messages))

    def streaming(agent, role, n, view):
        def listen(piece):
            view.append(piece)
            publish("stream", "", text=piece, role=role, round=n)
        agents[agent].listener = listen

    def desktop_conflict():
        claude = agents["claude"]
        seen = claude.desktop_activity() if hasattr(claude, "desktop_activity") else None
        if not seen:
            return None
        at, now = seen["at"], time.time()
        if at < now - DESKTOP_QUIET or at <= forced_at or at <= state.get("claudeDoneAt", 0) + 10:
            return None
        minutes = max(1, round((now - at) / 60))
        return t(f"桌面窗口「{seen['title']}」约 {minutes} 分钟内还在使用这个 Claude 会话。"
                 "为避免两边同时修改任务文档，接力在调用 Claude 之前暂停。"
                 "请先结束桌面窗口里的对话再点「继续上次」，或确认没有冲突后点「仍然继续」。",
                 f"The desktop window \"{seen['title']}\" used this Claude session within the last {minutes} min. "
                 "To keep both sides from editing the task document at once, the relay paused before calling Claude. "
                 "Finish the desktop conversation and choose \"Resume\", or choose \"Continue anyway\" if there is no conflict.")

    def guard():
        reason = desktop_conflict()
        if reason:
            log(reason, round=state["round"])
            publish("desktop", reason, round=state["round"])
        return reason

    publish("folder", str(folder))
    announce()
    if state["inflight"]:
        raise RuntimeError(t("上次发送后没有保存完整回执。请核对两端会话，再从「最新执行回执」或「从目标开始」接入。",
                           "No complete receipt was saved after the last dispatch. Check both sessions, then start from "
                           "\"Latest receipt\" or \"Start from goal\"."))
    count = 0
    while True:
        if pause() or (state["phase"] == "execute" and count >= limit):
            log(t("交接点已保存。选择「继续上次」可从此处接着运行。", "Checkpoint saved. Choose \"Resume\" to continue from here."))
            publish("paused", t("已暂停", "Paused"), round=state["round"])
            return
        n = state["round"]
        if state["phase"] == "await_codex":
            tid = state["sourceTurn"]
            log(t(f"等待 Codex 回合 {tid} 的完成回执，随后交给 {manager.title()} 审查。",
                  f"Waiting for Codex turn {tid} to finish, then {manager.title()} reviews it."), stage="waiting")
            receipt = agents["codex"].wait_for_receipt(tid, pause)
            if receipt is not None:
                write(folder / state["input"], receipt)
                save(phase="review")
                log(t("已收到锁定回合的完整回执", "Received the full receipt of the pinned turn"), round=n)
                announce()
            continue
        if state["phase"] == "review":
            handoff = ReviewHandoff() if manager == "claude" else None
            detail = (t("Claude 审查回执并准备 MCP 交接", "Claude reviews the receipt and prepares the MCP handoff") if handoff
                      else t("Codex 审查并更新任务文档", "Codex reviews and updates the task document"))
            log(t(f"第 {n} 轮 · {detail}", f"Round {n} · {detail}"), round=n, stage="review")
            if manager == "claude" and guard():
                return
            context = bridge_context(agents["claude"], digest_path, n) if manager == "claude" else ""
            request = review_prompt(doc, folder / state["input"], state["goal"], mcp=handoff is not None,
                                    context=context)
            if state.get("priorReview"):
                previous = folder / state["priorReview"] / f"{n:03}-decision.txt"
                request += (t("\n\n正在恢复同一回合的审查。", "\n\nResuming the review of the same round. ")
                            + (t(f"上次结论保存在 {previous}。", f"The previous conclusion is in {previous}. ") if previous.exists() else "")
                            + t("请沿用已经核实的结论，核对文档现状并完成待办写入。继续遵守项目中已有的人工确认条件。",
                                "Keep the verified conclusions, check the document and finish the pending edits. "
                                "Keep following the project's confirmation rules."))
            write(folder / f"{n:03}-review-request.txt", request)
            current_hash = fingerprint(doc)
            before = state["before"] if state.get("priorReview") and state.get("reviewedHash") == current_hash else current_hash
            save(inflight=True, before=before, transport="mcp" if handoff else "text")
            view = []
            streaming(manager, manager, n, view)
            if handoff:
                try:
                    final, output = agents[manager].run(request, True, handoff=handoff)
                except Exception as exc:
                    # A review tool stages work. Only the execute phase can deliver it.
                    final = output = t(f"Claude 审查未完成：{exc}", f"Claude review did not finish: {exc}")
                    record = dict(toolUseIds=[], decision=dict(action="blocked", reason=final, prompt=""))
                else:
                    record = handoff.record()
                write(folder / f"{n:03}-mcp.json", compact(record))
            else:
                final, output = agents[manager].run(request, True)
            agents[manager].listener = None
            write(folder / f"{n:03}-review-output.txt", output)
            write(folder / f"{n:03}-decision.txt", final)
            if view:
                write(folder / f"{n:03}-review-view.txt", "\n\n".join(view))
            else:
                (folder / f"{n:03}-review-view.txt").unlink(missing_ok=True)
            save(phase="parse", inflight=False, repaired=False, priorReview=None,
                 **({"claudeDoneAt": time.time()} if manager == "claude" else {}))
        if state["phase"] == "parse":
            answer_path = folder / f"{n:03}-decision.txt"
            try:
                if state.get("transport") == "mcp":
                    d = json.loads((folder / f"{n:03}-mcp.json").read_text(encoding="utf-8"))["decision"]
                else:
                    d = parse_decision(answer_path.read_text(encoding="utf-8"))
            except (ValueError, TypeError) as exc:
                if state.get("transport") == "mcp":
                    raise RuntimeError(t("MCP 交接记录损坏，请核对运行记录。", "The MCP handoff record is damaged. Check the run folder.")) from exc
                if state.get("repaired"):
                    raise ValueError(t("指挥者仍未给出有效决策。请在原会话核对，随后从最新回执重新审查。",
                                       "The lead still gave no valid decision. Check the session, then review the latest receipt again.")) from exc
                log(t("正在请指挥者修正回执格式", "Asking the lead to fix the answer format"), round=n)
                save(inflight=True, repaired=True)
                correction = t("请只重新格式化上一条审查结论，保留同一决定和下一条 prompt。"
                               "若上一条答复没有明确的下一步指令，且不能判定任务已经完成，请返回 blocked 并说明需澄清之处。"
                               "用一对 <relay-decision> 与 </relay-decision> 包裹一个 JSON 对象。"
                               "action 为 continue、done 或 blocked，reason 为说明，prompt 为完整执行指令或空字符串。",
                               "Only reformat your previous review, keeping the same decision and next prompt. "
                               "If it had no clear next instruction and the task is not clearly done, return blocked and say what needs clarifying. "
                               "Wrap one JSON object in <relay-decision> and </relay-decision>. "
                               "action is continue, done or blocked; reason explains it; prompt is the full instruction or an empty string.")
                final, output = agents[manager].run(correction, True)
                write(folder / f"{n:03}-format-output.txt", output)
                write(answer_path, final)
                save(inflight=False)
                continue
            if d["action"] != "blocked" and fingerprint(doc) == state["before"]:
                if state.get("transport") == "mcp":
                    reason = t("任务文档内容没有更新。MCP 决定已保存，可以核对后重试审查。",
                               "The task document was not updated. The MCP decision is saved; check it and retry the review.")
                    save(phase="blocked", reviewedHash=fingerprint(doc))
                    announce()
                    log(reason, round=n)
                    publish("blocked", reason, round=n)
                    return
                raise RuntimeError(t("任务文档内容没有更新。已保留指挥者的答复并暂停派单。请核对文档后继续。",
                                   "The task document was not updated. The lead's answer is kept and dispatch is paused. Check the document, then continue."))
            log(d["reason"], round=n)
            if d["action"] != "continue":
                save(phase=d["action"], reviewedHash=fingerprint(doc))
                announce()
                publish(d["action"], d["reason"], round=n)
                return
            filename = f"{n+1:03}-prompt.txt"
            write(folder / filename, d["prompt"])
            save(phase="execute", input=filename)
            announce()
            continue
        if state["phase"] == "execute":
            if executor == "claude" and guard():
                return
            log(t(f"第 {n+1} 轮 · {executor.title()} 执行指挥者的 prompt", f"Round {n+1} · {executor.title()} runs the lead's prompt"),
                round=n+1, stage="execute")
            save(inflight=True)
            view = []
            streaming(executor, executor, n+1, view)
            try:
                _, output = agents[executor].run((folder / state["input"]).read_bytes().decode("utf-8"), False)
            finally:
                agents[executor].listener = None
            if not output.strip():
                raise RuntimeError(t("执行者没有返回可供审查的输出。", "The executor returned nothing to review."))
            filename = f"{n+1:03}-receipt.txt"
            write(folder / filename, output)
            if view:
                write(folder / f"{n+1:03}-execute-view.txt", "\n\n".join(view))
            save(phase="review", round=n+1, input=filename, inflight=False,
                 **({"claudeDoneAt": time.time()} if executor == "claude" else {}))
            count += 1
            log(t("已保存本轮完整回执", "Saved this round's full receipt"), round=n+1)
            announce()


MCP_NAME = "codex_relay"


def register_mcp(root, run=subprocess.run):
    """Register codex_relay for this project (Claude Code local scope).

    Local scope lives in Claude Code's own settings, not in the project, so nothing
    machine-specific is committed and no approval prompt is needed. The server runs
    from this copy of Session Relay, so rebuilding the app keeps it working.
    """
    cli = cli_command("claude", executable("claude"))
    server = script_command(Path(__file__).with_name("relay_mcp.py").resolve(), "--live", "--project", str(root))
    opts = dict(cwd=root, env=claude_env(), capture_output=True, encoding="utf-8", timeout=30, **cli_subprocess())
    run([*cli, "mcp", "remove", "-s", "local", MCP_NAME], **opts)
    done = run([*cli, "mcp", "add", "-s", "local", MCP_NAME, "--", *server], **opts)
    if done.returncode:
        raise RuntimeError(t("无法在本机注册 codex_relay：", "Could not register codex_relay on this PC: " if WINDOWS
                             else "Could not register codex_relay on this Mac: ")
                           + (done.stderr or done.stdout)[-800:])


def bootstrap(project, login_only=False, document=None):
    root = project_root(project)
    doc = None if login_only else task_document(root, document)
    sid = str(uuid.uuid4())
    cli = executable("claude")
    greeting = t(f"请阅读任务文档 {doc}，了解现状，等我通过 Session Relay 交给你回执或指令。此步骤只阅读。",
                 f"Read the task document {doc} to learn the current state, then wait for receipts or instructions from Session Relay. Only read for now.")
    if WINDOWS:
        def quote(value):
            return "'" + value.replace("'", "''") + "'"

        invoke = "& " + " ".join(map(quote, cli_command("claude", cli)))
        command = invoke + " auth status *> $null\n"
        command += "if ($LASTEXITCODE -ne 0) { " + invoke + " auth login; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }\n"
        if not login_only:
            command += invoke + " --session-id " + quote(sid) + " " + quote(greeting)
        script = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        subprocess.Popen(["powershell.exe", "-NoProfile", "-EncodedCommand", script], cwd=root,
                         env=claude_env(), creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        folder = SUPPORT / "launchers"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        cmd = folder / f"{sid}.command"
        cli = shlex.quote(cli)
        command = "#!/bin/zsh\nset -e\ncd -- " + shlex.quote(str(root)) + "\n"
        command += cli + " auth status >/dev/null 2>&1 || " + cli + " auth login\n"
        if not login_only:
            command += "exec " + cli + " --session-id " + sid + " " + shlex.quote(greeting) + "\n"
        cmd.write_text(command, encoding="utf-8")
        cmd.chmod(0o700)
        subprocess.run(["/usr/bin/open","-a","Terminal",str(cmd)], check=True)
    if login_only:
        emit("login", t("已打开本地 Code 登录终端。完成后回到 App 检查连接。", "Opened a Terminal to sign in to Claude Code. Come back and check the connection when done."))
    else:
        emit("created", sid)


def main():
    os.umask(0o077)
    config = json.loads(sys.stdin.readline())
    if config.get("command") == "discover":
        try:
            chats, problem = codex_threads(config["project"]), ""
        except Exception as exc:  # The Claude list is still useful without Codex.
            chats, problem = [], str(exc)
        emit("discovery", loggedIn=claude_auth(), sessions=project_sessions(config["project"]),
             codex=chats, codexError=problem)
        return
    if config.get("command") in ("create", "login"):
        return bootstrap(config["project"], config["command"] == "login", config.get("document"))
    if config.get("command") == "bind":
        from live import bind
        limit = config.get("limit", 3)
        folder = bind(config["project"], config["codex"], limit, document=config.get("document"),
                      pair=config.get("pair", ""), claude=config.get("claude", ""))
        register_mcp(project_root(config["project"]))
        emit("folder", str(folder))
        emit("bound", t(f"已启用原会话接力，本次最多派出 {limit} 轮，并已在本机为这个项目注册 codex_relay。"
                        "在审查会话里开一轮新对话加载工具，再让 Claude 用 send_to_codex 派单。",
                        f"In-session relay is on with up to {limit} rounds, and codex_relay is registered for this project "
                        + ("on this PC. " if WINDOWS else "on this Mac. ")
                        + "Start a new conversation in the reviewer session to load the tools, then have Claude "
                          "dispatch with send_to_codex."))
        return
    if config.get("command") == "history":
        folder = Path(config.get("folder", "")).expanduser()
        ok = folder.is_dir() and ".session-relay" in folder.parts
        emit("history", folder=str(folder), messages=conversation(folder) if ok else [])
        return
    root, doc, a, b = paths(config)
    with session_locks([a,b]):
        if not claude_auth():
            raise RuntimeError(t("本地 Claude Code 尚未登录。点「登录…」完成本地登录，再检查连接。",
                               "Claude Code is not signed in. Choose \"Sign in…\", then check the connection again."))
        if not transcript(b):
            raise ValueError(t("找不到这个本地 Claude Code 会话。请使用本地 Code 的会话 UUID，或点「新建会话…」。",
                             "This local Claude Code session was not found. Use its session UUID, or choose \"New session…\"."))
        codex = Codex(a, root)
        try:
            if config.get("command") == "check":
                turn = codex.get_turn()
                state = codex.turn_state(turn) if turn else "empty"
                detail = {"completed": t("最新回合已完成", "latest turn finished"),
                          "pending": t("最新回合尚未结束", "latest turn still running"),
                          "failed": t("最新回合执行失败", "latest turn failed"),
                          "interrupted": t("最新回合已中断", "latest turn interrupted"),
                          "empty": t("还没有执行回合", "no turns yet")}[state]
                note = t(f"Codex「{codex.name}」{detail}。", f"Codex \"{codex.name}\": {detail}. ")
                if config["manager"] == "claude" and config.get("mode", "latest") == "latest":
                    if state == "pending":
                        note += t("点「开始接力」即可等待回执并自动交给 Claude。", "Choose \"Start relay\" to wait for the receipt and hand it to Claude.")
                    elif state == "completed":
                        note += t("点「开始接力」即可将最新回执交给 Claude。", "Choose \"Start relay\" to hand the latest receipt to Claude.")
                emit("checked", note)
                return
            pair = workspace(root, a, b, config["manager"])
            stop = pair / "pause"
            stop.unlink(missing_ok=True)
            emit("control", str(stop))
            agents = dict(claude=Claude(b, root, doc), codex=codex)
            latest = codex.latest if config["manager"] == "claude" else lambda: latest_claude(b)
            run_loop(config, pair, doc, agents, latest, stop.exists)
        finally:
            codex.close()


def entrypoint():
    def terminate(sig, frame):
        raise KeyboardInterrupt()
    if WINDOWS:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            stream.reconfigure(encoding="utf-8")
        signal.signal(signal.SIGBREAK, terminate)
    else:
        signal.signal(signal.SIGTERM, terminate)
    if len(sys.argv) > 1:
        from live import cli
        cli(sys.argv[1:])
        sys.exit(0)
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        emit("error", str(exc))
        sys.exit(1)


if __name__ == "__main__":
    entrypoint()
