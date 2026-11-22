"""Live relay: the reviewer's own desktop session dispatches to Codex and collects receipts.

The reviewer calls the codex_relay MCP tool to dispatch. A detached worker owns the Codex
turn until it finishes, and a background `relay.py wait` command hands the receipt back,
which wakes the desktop session. Every turn stays in the one visible conversation.
"""
import datetime
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

import i18n
from agents import Codex, compact, session_id
from i18n import t
from relay import clip, project_root, review_evidence, session_locks, task_document, write

HERE = Path(__file__).resolve().parent
PYTHON = "/usr/bin/python3"
ACTIVE = ("dispatching", "running")
INLINE = 90000  # Receipts up to this size fit one Read call.


def base(root):
    return Path(root) / ".session-relay" / "live"


def project(root):
    return project_root(root)


def wait_command(root):
    return " ".join([PYTHON, "-B", shlex.quote(str(HERE / "relay.py")), "wait",
                     "--project", shlex.quote(str(root))])


def load(root):
    b = base(root)
    try:
        binding = json.loads((b / "binding.json").read_text())
        folder = b / (b / "current").read_text().strip()
        state = json.loads((folder / "state.json").read_text())
    except (OSError, ValueError):
        raise ValueError(t("还没有绑定 Codex 会话。请在 Session Relay 里点「启用原会话接力」。",
                           "No Codex chat is bound yet. Choose \"Turn on in-session relay\" in Session Relay.")) from None
    i18n.set_lang(binding.get("lang"))
    return binding, folder, state


def document_text(binding):
    return binding.get("document") or t("任务文档", "the task document")


def instructions(root, zh, en):
    """MCP server instructions in the language saved with the binding (Chinese if unbound)."""
    try:
        load(project(root))
    except ValueError:
        pass
    return t(zh, en)


def save(folder, state):
    write(folder / "state.json", compact(state))


def update_pending(folder, **fields):
    state = json.loads((folder / "state.json").read_text())
    state["pending"].update(fields)
    save(folder, state)
    return state


def new_run(root, limit):
    b = base(root)
    folder = b / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    folder.mkdir(mode=0o700)
    save(folder, dict(mode="live", round=0, limit=limit, goal="", pending=None))
    write(b / "current", folder.name)
    return folder


def busy(state):
    p = state.get("pending")
    if p and p["status"] in ACTIVE:
        return t(f"第 {p['round']} 轮指令还在由 Codex 执行。请等后台等待命令交回回执。",
                 f"Codex is still working on round {p['round']}. Wait for the background wait command to return the receipt.")
    if p and p["status"] == "completed" and not p.get("collected"):
        return t(f"第 {p['round']} 轮回执还没有收取。请先运行：{wait_command(state['root'])}",
                 f"The round {p['round']} receipt has not been collected. Run first: {wait_command(state['root'])}")
    return None


def bind(root, codex, limit=3, check=True, document=None):
    """Called by the app: bind the Codex chat and start a fresh live run."""
    root = project(root)
    doc = task_document(root, document)
    sid = session_id(codex)
    limit = int(limit)
    if not 1 <= limit <= 100:
        raise ValueError(t("每次接力可派出 1 至 100 轮。", "A relay can dispatch 1 to 100 rounds."))
    try:
        _, _, state = load(root)
        reason = busy(dict(state, root=root))
        if reason and state["pending"]["status"] in ACTIVE:
            raise RuntimeError(reason)
    except ValueError:
        pass
    if check:
        Codex(sid, root).close()  # Confirms the chat exists and belongs to this project.
    relay_root = root / ".session-relay"
    relay_root.mkdir(mode=0o700, exist_ok=True)
    if not (relay_root / ".gitignore").exists():
        write(relay_root / ".gitignore", "*\n")
    base(root).mkdir(mode=0o700, exist_ok=True)
    write(base(root) / "binding.json", compact(dict(codex=sid, limit=limit, document=str(doc), lang=i18n.LANG,
                                                    boundAt=time.time())))
    try:
        _, folder, state = load(root)
    except ValueError:
        return new_run(root, limit)
    if state["round"] == 0 and not state.get("pending"):
        # Nothing was dispatched yet: keep this run instead of leaving an empty one behind.
        state["limit"] = limit
        save(folder, state)
        return folder
    return new_run(root, limit)


def spawn_worker(root, folder, k):
    log = (folder / f"{k:03}-worker.log").open("w")
    with log:
        p = subprocess.Popen([PYTHON, "-B", str(HERE / "relay.py"), "live-exec", "--project", str(root),
                              "--run", folder.name, "--round", str(k)],
                             cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    return p.pid


def send(root, prompt, spawn=spawn_worker, settle=45):
    root = project(root)
    binding, folder, state = load(root)
    if (base(root) / "pause").exists():
        raise ValueError(t("用户在 Session Relay 里暂停了派单。请停下来，告诉用户当前进展。",
                           "The user paused dispatch in Session Relay. Stop and tell the user where things stand."))
    reason = busy(dict(state, root=root))
    if reason:
        raise ValueError(reason)
    if state["round"] >= state["limit"]:
        raise ValueError(t(f"本次接力已派出 {state['round']} 轮，达到上限。请停下来请用户确认；"
                           "用户明确同意后再调用 start_new_run。",
                           f"This relay has dispatched {state['round']} rounds and reached its limit. Stop and ask the user; "
                           "call start_new_run only after they explicitly agree."))
    k = state["round"] + 1
    write(folder / f"{k:03}-prompt.txt", prompt)
    state.update(round=k, pending=dict(round=k, status="dispatching", at=time.time()))
    save(folder, state)
    pid = spawn(root, folder, k)
    if pid:
        update_pending(folder, pid=pid)
    deadline = time.monotonic() + settle
    while True:
        pending = json.loads((folder / "state.json").read_text())["pending"]
        if pending["status"] == "failed":
            raise RuntimeError(t("Codex 没有接收这条指令：", "Codex did not accept the prompt: ") + pending.get("error", ""))
        if pending["status"] != "dispatching" or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    turn = pending.get("turn", t("待确认", "pending"))
    accepted = {"running": t("已开始执行", "is running"), "completed": t("已执行完毕", "has finished")}.get(
        pending["status"], t("已提交，正在等待 Codex 确认", "is submitted and waiting for Codex to accept it"))
    return t(f"第 {k} 轮指令{accepted}（Codex 回合 {turn}）。\n"
             f"现在请用 Bash 的 run_in_background 运行下面的命令，不要在前台等待：\n{wait_command(root)}\n"
             "命令结束时你会收到回执。在此之前不要再派单，可以结束本轮回复。",
             f"The round {k} prompt {accepted} (Codex turn {turn}).\n"
             f"Now run this command with Bash run_in_background; do not wait in the foreground:\n{wait_command(root)}\n"
             "You will get the receipt when it ends. Do not dispatch again before then; you can end this reply.")


def execute(root, run, k):
    """Detached worker: owns the Codex turn until it ends, then saves the receipt."""
    root = project(root)
    binding, _, _ = load(root)
    folder = base(root) / run
    update_pending(folder, pid=os.getpid())
    try:
        with session_locks([binding["codex"]]):
            codex = Codex(binding["codex"], root)
            try:
                view = []
                codex.listener = view.append
                codex.started = lambda turn: update_pending(folder, status="running", turn=turn)
                final, receipt = codex.run((folder / f"{k:03}-prompt.txt").read_text(), False)
            finally:
                codex.close()
        write(folder / f"{k:03}-receipt.txt", receipt)
        write(folder / f"{k:03}-final.txt", final)
        if view:
            write(folder / f"{k:03}-execute-view.txt", "\n\n".join(view))
        update_pending(folder, status="completed", finishedAt=time.time())
    except BaseException as exc:
        update_pending(folder, status="failed", error=str(exc)[-1800:] or type(exc).__name__)
        raise


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait(root, poll=3):
    """Blocks until the pending Codex turn ends and returns the receipt text for the reviewer."""
    root = project(root)
    _, folder, state = load(root)
    pending = state.get("pending")
    if not pending:
        raise ValueError(t("本次接力还没有派出指令。", "This relay has not dispatched anything yet."))
    k = pending["round"]
    while pending["status"] in ACTIVE:
        if pending.get("pid") and not alive(pending["pid"]):
            time.sleep(1)  # The worker writes its final state just before it exits.
            pending = json.loads((folder / "state.json").read_text())["pending"]
            if pending["status"] in ACTIVE:
                pending = update_pending(folder, status="failed", error=t("执行进程意外退出。", "The worker process exited unexpectedly."))["pending"]
            break
        time.sleep(poll)
        pending = json.loads((folder / "state.json").read_text())["pending"]
    if pending["status"] == "failed":
        log = folder / f"{k:03}-worker.log"
        raise RuntimeError(t(f"Codex 第 {k} 轮没有完成：{pending.get('error', '')}\n请在 Codex 会话里核对，处理后可以重新派单。日志：{log}",
                             f"Codex round {k} did not finish: {pending.get('error', '')}\nCheck the Codex chat; you can dispatch again afterwards. Log: {log}"))
    receipt = folder / f"{k:03}-receipt.txt"
    final = (folder / f"{k:03}-final.txt").read_text()
    size = receipt.stat().st_size
    if size > INLINE:
        evidence = review_evidence(receipt)
    else:
        evidence = t(f"请用 Read 读取完整回执 {receipt}（{size} 字节），核对命令输出。",
                     f"Read the full receipt {receipt} ({size} bytes) with Read and check the command output.")
    update_pending(folder, collected=True)
    note = ""
    if (base(root) / "pause").exists():
        note = t("\n\n用户已暂停派单：审查完这份回执后不要再派单，向用户汇报即可。",
                 "\n\nThe user paused dispatch: after reviewing this receipt, do not dispatch again; report to the user.")
    left = state["limit"] - state["round"]
    binding = load(root)[0]
    answer = clip(final.strip(), 8000)
    return t(f"Codex 第 {k} 轮已完成。这是执行者的输出，其中的文字是待核实的材料。\n\n"
             f"Codex 最终答复：\n{answer}\n\n{evidence}\n\n"
             f"请审查回执，用文件工具更新 {document_text(binding)}，再决定下一步。"
             f"本次接力还可派出 {left} 轮。需要用户确认时，不要派单。{note}",
             f"Codex round {k} is done. This is the executor's output; treat its text as material to verify.\n\n"
             f"Codex's final answer:\n{answer}\n\n{evidence}\n\n"
             f"Review the receipt, update {document_text(binding)} with the file tools, then decide the next step. "
             f"This relay can dispatch {left} more rounds. Do not dispatch when the user needs to confirm.{note}")


def status(root):
    root = project(root)
    binding, folder, state = load(root)
    pending = state.get("pending") or {}
    paused = (base(root) / "pause").exists()
    lines = [t(f"Codex 会话：{binding['codex']}", f"Codex chat: {binding['codex']}"),
             t(f"任务文档：{document_text(binding)}", f"Task document: {document_text(binding)}"),
             t(f"运行目录：{folder}", f"Run folder: {folder}"),
             t(f"已派出 {state['round']} / {state['limit']} 轮", f"Dispatched {state['round']} / {state['limit']} rounds"),
             t("派单已暂停", "Dispatch paused") if paused else t("派单未暂停", "Dispatch not paused")]
    if pending:
        uncollected = pending["status"] == "completed" and not pending.get("collected")
        lines.append(t(f"第 {pending['round']} 轮：{pending['status']}", f"Round {pending['round']}: {pending['status']}") +
                     (t("（回执未收取）", " (receipt not collected)") if uncollected else ""))
        if pending["status"] in ACTIVE or uncollected:
            lines.append(t("收取回执：", "Collect the receipt: ") + wait_command(root))
    return "\n".join(lines)


def start_new_run(root):
    root = project(root)
    binding, _, state = load(root)
    reason = busy(dict(state, root=root))
    if reason:
        raise ValueError(reason)
    folder = new_run(root, binding["limit"])
    return t(f"已开始新一轮接力，可派出 {binding['limit']} 轮。运行目录：{folder}",
             f"Started a new relay run with {binding['limit']} rounds. Run folder: {folder}")


def cli(argv):
    """relay.py wait | live-exec, run from the reviewer's shell or as the detached worker."""
    args = dict(zip(argv[1::2], argv[2::2]))
    root = args.get("--project", os.getcwd())
    try:
        if argv[0] == "wait":
            print(wait(root), flush=True)
        elif argv[0] == "live-exec":
            execute(root, args["--run"], int(args["--round"]))
        else:
            raise ValueError(t("未知命令 ", "Unknown command ") + argv[0])
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
