"""Local Codex App Server and Claude Code transports."""
import json
import os
import queue
import re
import time
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from i18n import t
from relay_mcp import FINISH, PREFIX, SEND
from relay_platform import WINDOWS, app_support, claude_rule_path, process_group, terminate_tree

BUNDLED = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
def claude_desktop_home():
    if WINDOWS:
        override = os.environ.get("SESSION_RELAY_CLAUDE_DESKTOP_DIR")
        if override:
            return Path(override)
        packaged = Path(os.environ["LOCALAPPDATA"]) / "Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude"
        if packaged.is_dir():
            return packaged
    return app_support() / "Claude"


CLAUDE_HOME = claude_desktop_home()
CLAUDE_CACHE = CLAUDE_HOME / "claude-code"
DESKTOP = CLAUDE_HOME / "claude-code-sessions"
RELAY_ENTRY = "sdk-cli"


def cli_path():
    home = str(Path.home() / ".local/bin")
    extra = [home] if WINDOWS else [home, "/opt/homebrew/bin", "/usr/local/bin"]
    return os.pathsep.join([os.environ.get("PATH", ""), *extra])


def executable(agent):
    override = os.environ.get(f"SESSION_RELAY_{agent.upper()}_BIN")  # Custom installs and test doubles.
    if override:
        return override
    found = shutil.which(agent, path=cli_path())
    if sys.platform == "darwin" and agent == "codex" and BUNDLED.is_file():
        return str(BUNDLED)
    if found:
        return found
    if agent == "claude":
        pattern = "*/*/claude.exe" if WINDOWS else "*/*/claude.app/Contents/MacOS/claude"
        builds = list(CLAUDE_CACHE.glob(pattern))
        if builds:
            return str(max(builds, key=lambda p: p.stat().st_mtime))
    raise RuntimeError(t(f"没有找到 {agent} 本地程序。", f"Could not find the local {agent} program."))


def cli_command(agent, program):
    if WINDOWS:
        path = Path(program)
        if path.suffix.lower() == ".py" and not getattr(sys, "frozen", False):
            return [sys.executable, str(path)]
        if path.suffix.lower() == ".cmd":
            # Use the published npm entry point directly so cmd.exe cannot reparse JSON or prompts.
            package = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code"}[agent]
            folder = path.parent / "node_modules" / package
            manifest = folder / "package.json"
            if manifest.is_file():
                entry = json.loads(manifest.read_text(encoding="utf-8"))["bin"][agent]
                script = folder / entry
                if script.suffix.lower() == ".exe":
                    return [str(script)]
                node = shutil.which("node.exe", path=os.pathsep.join((str(path.parent), cli_path())))
                if node is None:
                    raise RuntimeError(t("没有找到 node.exe。", "Could not find node.exe."))
                return [node, str(script)]
    return [program]


def agent_command(agent, *args):
    return [*cli_command(agent, executable(agent)), *args]


def cli_subprocess():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}


def session_id(value):
    return str(uuid.UUID(value.strip().rstrip("/").split("/")[-1]))


def claude_env():
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["PATH"] = cli_path()
    return env


def claude_auth():
    p = subprocess.run(agent_command("claude", "auth", "status"), env=claude_env(), capture_output=True,
                       encoding="utf-8", timeout=20, **cli_subprocess())
    try:
        return bool(json.loads(p.stdout)["loggedIn"])
    except (ValueError, KeyError):
        raise RuntimeError(t("无法读取 Claude Code 登录状态。请在本地 Claude Code 中检查 /status。",
                           "Could not read the Claude Code sign-in state. Check /status in Claude Code."))


def transcript(sid):
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home()/".claude")) / "projects"
    return next(base.glob("*/" + session_id(sid) + ".jsonl"), None)


def project_sessions(root, desktop=None):
    """Join local CLI transcripts with Desktop's display titles and IDs."""
    root = Path(root).expanduser().resolve()
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home()/".claude")) / "projects"
    desktop = desktop or DESKTOP
    found = {}

    def add(path, title="", alias=""):
        try:
            sid = str(uuid.UUID(path.stem))
            found[sid] = dict(id=sid, title=title or t("终端会话", "Terminal session"), alias=alias,
                              modified=path.stat().st_mtime)
        except (ValueError, OSError):
            return

    key = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    pattern = (key if len(key) < 200 else key[:200] + "*") + "/*.jsonl"
    for path in base.glob(pattern):
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    cwd = json.loads(line).get("cwd")
                    if cwd:
                        if Path(cwd).resolve() == root:
                            add(path)
                        break
        except (ValueError, OSError):
            continue
    for path in desktop.glob("*/*/local_*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if not row.get("cwd") or Path(row["cwd"]).resolve() != root:
                continue
            sid = session_id(row["cliSessionId"])
            if row.get("isArchived"):
                found.pop(sid, None)
                continue
            local = transcript(sid)
            if local:
                add(local, row.get("title"), row.get("sessionId") or path.stem)
        except (KeyError, TypeError, ValueError, OSError):
            continue
    return sorted(found.values(), key=lambda s: s["modified"], reverse=True)


def resolve_claude_id(value, root):
    raw = value.strip().rstrip("/").split("/")[-1]
    try:
        sid = session_id(raw.removeprefix("local_"))
    except ValueError:
        raise ValueError(t("请选择一个本地 Claude Code 会话，或粘贴它的 UUID。",
                           "Choose a local Claude Code session or paste its UUID.")) from None
    if not raw.startswith("local_") and transcript(sid):
        return sid
    return next((s["id"] for s in project_sessions(root)
                 if s["alias"].removeprefix("local_") == sid), sid)


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def claude_blocks(content):
    if isinstance(content, str):
        return [content]
    return [b["text"] if b.get("type") == "text" else compact(b) for b in content
            if b.get("type") not in ("thinking", "redacted_thinking")]


def short(value, limit=160):
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit-1] + "…"


def tool_line(name, args):
    """One readable line per tool call for the conversation view."""
    args = args if isinstance(args, dict) else {}
    if name == PREFIX + SEND:
        return t("▸ 提交给 Codex 的指令（见下方）", "▸ Prompt for Codex (below)")
    if name == PREFIX + FINISH:
        return t("▸ 结束审查：", "▸ Review finished: ") + f"{args.get('status', '')} · {short(args.get('reason', ''))}"
    for key in ("file_path", "path", "command", "pattern", "url", "description", "prompt"):
        if args.get(key):
            return f"▸ {name} {short(args[key])}"
    return f"▸ {name}"


def claude_view(row):
    """Readable pieces of one top-level stream-json row: text and tool calls, no tool output."""
    if row.get("parent_tool_use_id") or row.get("type") not in ("assistant", "user"):
        return []
    content = row.get("message", {}).get("content", [])
    if isinstance(content, str):
        return []
    pieces = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if row["type"] == "assistant" and block.get("type") == "text" and block.get("text", "").strip():
            pieces.append(block["text"].strip())
        elif row["type"] == "assistant" and block.get("type") == "tool_use":
            pieces.append(tool_line(block.get("name", ""), block.get("input")))
        elif row["type"] == "user" and block.get("type") == "tool_result" and block.get("is_error"):
            pieces.append(t("  ✗ 工具返回错误", "  ✗ Tool error"))
    return pieces


def codex_view(item):
    kind = item.get("type")
    if kind == "agentMessage":
        return [item["text"].strip()] if item.get("text", "").strip() else []
    if kind in ("reasoning", "userMessage", "hookPrompt"):
        return []
    if kind == "commandExecution":
        return [t("▸ 命令 ", "▸ Command ") + short(item.get("command", ""))]
    if kind == "fileChange":
        names = [c.get("path", "") for c in item.get("changes", []) if isinstance(c, dict)]
        return [t("▸ 修改文件 ", "▸ Edited ") + short(", ".join(names) or "")]
    return ["▸ " + str(kind)]


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def desktop_notes(sid, limit=8000):
    """Exchanges typed in another client (the desktop window) after the relay's last review.

    The desktop window keeps its own branch of the transcript, so a relay resume may
    not contain them. Returns oldest-first [(user text, assistant reply)] within limit chars.
    """
    path = transcript(sid)
    if not path:
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    last_relay = None
    for i, row in enumerate(rows):
        if (row.get("type") == "user" and row.get("entrypoint") == RELAY_ENTRY and not row.get("isMeta")
                and _text(row.get("message", {}).get("content", [])).strip()):
            last_relay = i
    if last_relay is None:
        return []
    exchanges = []
    for row in rows[last_relay+1:]:
        if row.get("isSidechain") or row.get("isMeta") or row.get("entrypoint") in (None, RELAY_ENTRY):
            continue
        text = _text(row.get("message", {}).get("content", [])).strip()
        if not text:
            continue
        if row.get("type") == "user":
            exchanges.append([text, ""])
        elif row.get("type") == "assistant" and exchanges:
            exchanges[-1][1] = text
    kept, size = [], 0
    for user, reply in reversed(exchanges):
        user, reply = user[:1500], reply[-1500:]
        if kept and size + len(user) + len(reply) > limit:
            break
        kept.append((user, reply))
        size += len(user) + len(reply)
    return list(reversed(kept))


def desktop_activity(sid, desktop=None):
    """Last time (epoch seconds) the desktop app touched this CLI session, or None."""
    for path in (desktop or DESKTOP).glob("*/*/local_*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("isArchived") or session_id(row.get("cliSessionId", "")) != sid:
                continue
            stamps = [row.get(k) for k in ("lastActivityAt", "latestUserFrameAt", "lastTurnEdgeAt")]
            stamps = [s / 1000 for s in stamps if isinstance(s, (int, float))]
            if stamps:
                return dict(title=row.get("title") or row.get("sessionId", ""), at=max(stamps))
        except (KeyError, TypeError, ValueError, OSError):
            continue
    return None


def latest_claude(sid):
    path = transcript(sid)
    if not path:
        raise RuntimeError(t("未找到这个本地 Claude Code 会话。请核对 /status 中的 ID，或在 App 里新建会话。",
                           "This local Claude Code session was not found. Check the ID in /status or create one in the app."))
    blocks, final, finished = [], "", False
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("isSidechain"):
                continue
            role = row.get("type")
            if role not in ("user", "assistant"):
                continue
            msg = row.get("message", {})
            content = msg.get("content", [])
            if role == "user" and not row.get("isMeta") and (isinstance(content, str) or any(b.get("type") == "text" for b in content)):
                blocks, final, finished = [], "", False
                continue
            blocks.extend(claude_blocks(content))
            if role == "assistant":
                final = "\n".join(b["text"] for b in content if b.get("type") == "text")
                finished = msg.get("stop_reason") in ("end_turn", "stop_sequence")
    if not finished or not final:
        raise RuntimeError(t("Claude Code 最新一轮还没有完整的执行回执。可选择「从目标开始」。",
                           "Claude Code's latest turn has no complete receipt yet. Try \"Start from goal\"."))
    return "\n\n".join(blocks)


class Claude:
    def __init__(self, sid, root, document, desktop=None):
        self.sid, self.root, self.document = sid, root, document
        self.desktop = desktop
        self.listener = None  # Called with each readable piece while a run streams.

    def desktop_activity(self):
        return desktop_activity(self.sid, self.desktop)

    def desktop_notes(self):
        return desktop_notes(self.sid)

    def run(self, prompt, manager, handoff=None):
        args = agent_command("claude", "-p", "--resume", self.sid, "--verbose", "--output-format", "stream-json")
        if manager:
            # Claude's // prefix anchors a permission at the filesystem root,
            # including after a review command changes the working directory.
            rule_path = claude_rule_path(self.document.absolute())
            allowed = [f"Edit({rule_path})", f"Write({rule_path})", "Read"]
            if handoff is not None:
                args.extend(["--mcp-config", handoff.config()])
                allowed.extend([PREFIX + SEND, PREFIX + FINISH])
            args.extend(["--allowedTools", *allowed])
        else:
            args.extend(["--permission-mode", "acceptEdits"])
        p = subprocess.Popen(args, cwd=self.root, env=claude_env(), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", **process_group())
        errors = []

        def feed():
            try:
                p.stdin.write(prompt)
                p.stdin.close()
            except OSError:
                pass

        threads = [threading.Thread(target=feed, daemon=True),
                   threading.Thread(target=lambda: errors.append(p.stderr.read()), daemon=True)]
        for t in threads:
            t.start()
        blocks, result = [], {}
        try:
            # Read rows as they arrive so the app can show the review while it runs.
            for line in p.stdout:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("type") in ("assistant", "user"):
                    blocks.extend(claude_blocks(row.get("message", {}).get("content", [])))
                    if handoff is not None:
                        handoff.observe(row, self.sid)
                    if self.listener:
                        for piece in claude_view(row):
                            self.listener(piece)
                elif row.get("type") == "result":
                    result = row
            p.wait()
            for t in threads:
                t.join()
        except BaseException:
            if WINDOWS:
                terminate_tree(p.pid)
            else:
                p.terminate()
            p.wait()
            raise
        finally:
            p.stdout.close()
            p.stderr.close()
        err = "".join(errors)
        if p.returncode or result.get("is_error") or result.get("subtype") != "success":
            raise RuntimeError(str(result.get("result") or result.get("errors") or err or t("Claude Code 没有返回成功回执。", "Claude Code did not report success."))[-1800:])
        if result.get("session_id") != self.sid:
            raise RuntimeError(t("Claude 返回的会话 ID 和绑定的会话不一致。", "Claude answered from a different session than the bound one."))
        final = result.get("result", "")
        if not final and handoff is None:
            raise RuntimeError(t("Claude 没有返回最终文本。", "Claude returned no final text."))
        return final, "\n\n".join(blocks + ([] if blocks and blocks[-1] == final else [final]))


def codex_output(items):
    texts, final = [], ""
    for item in items:
        kind = item.get("type")
        if kind in ("reasoning", "userMessage", "hookPrompt"):
            continue
        if kind == "agentMessage":
            text = item.get("text", "")
            if text:
                final = text
                texts.append(text)
        else:
            texts.append(compact(item))
    return final, "\n\n".join(texts)


class Codex:
    def __init__(self, sid, root):
        self.sid, self.root = sid, root
        self.sequence, self.turn = 0, None
        self.attached = False
        self.listener = None
        self.started = None  # Called with the turn ID (or queue ID) once Codex accepts a prompt.
        self.events = queue.Queue()
        self.proc = subprocess.Popen(agent_command("codex", "app-server", "--listen", "stdio://"),
                                     cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, encoding="utf-8", **process_group())
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            self.rpc("initialize", {"clientInfo":{"name":"session_relay","version":"1.0"}})
            self.send({"method":"initialized"})
            if sid is None:  # Only listing chats.
                return
            thread = self.rpc("thread/read", {"threadId":sid})["thread"]
            if thread["id"] != sid or Path(thread["cwd"]).resolve() != root:
                raise RuntimeError(t(f"Codex 会话的项目是 {thread.get('cwd')}。请选择同一项目目录。",
                                     f"The Codex chat belongs to {thread.get('cwd')}. Choose the same project folder."))
            self.name = thread.get("name") or sid
            self.thread_status = thread.get("status", {}).get("type")
            self.rollout = Path(thread["path"]) if thread.get("path") else None
            self.log_position = 0
            self.log_inode = None
            self.aborted_turns = set()
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self.events.put(json.loads(line))
        finally:
            self.events.put(None)

    def close(self):
        if self.proc.poll() is None:
            if WINDOWS:
                terminate_tree(self.proc.pid)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdin.close()
        self.proc.stdout.close()

    def send(self, obj):
        self.proc.stdin.write(compact(obj) + "\n")
        self.proc.stdin.flush()

    def receive(self, timeout=None):
        try:
            msg = self.events.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError(t("Codex App Server 响应超时。", "The Codex App Server timed out."))
        if msg is None:
            raise RuntimeError(t("Codex App Server 已断开。", "The Codex App Server disconnected."))
        if "method" in msg and "id" in msg:
            self.send({"id":msg["id"],"error":{"code":-32603,"message":"This turn requires interactive input in Codex."}})
            raise RuntimeError(t("Codex 请求人工输入或工具授权。请在执行会话中处理后重新接入。",
                               "Codex is asking for input or tool approval. Handle it in the Codex chat, then reconnect."))
        return msg

    def rpc(self, method, params):
        self.sequence += 1
        self.send({"id":self.sequence, "method":method, "params":params})
        early = []
        try:
            while True:
                msg = self.receive(90)
                if msg.get("id") == self.sequence:
                    if "error" in msg:
                        raise RuntimeError(f"{method} · {msg['error'].get('message')}")
                    return msg.get("result", {})
                early.append(msg)
        finally:
            # Notifications may precede the reply to turn/start.
            self.pending = getattr(self, "pending", []) + early

    def get_turn(self, turn_id=None):
        cursor = None
        while True:
            try:
                page = self.rpc("thread/turns/list", {"threadId":self.sid, "sortDirection":"desc",
                                "itemsView":"notLoaded", "limit":16 if turn_id else 1, "cursor":cursor})
            except RuntimeError as exc:
                if not self.legacy_history_error(exc):
                    raise
                thread = self.rpc("thread/read", {"threadId":self.sid, "includeTurns":True})["thread"]
                page = {"data":reversed(thread["turns"])}
            for turn in page["data"]:
                if turn_id is None or turn["id"] == turn_id:
                    return turn
            cursor = page.get("nextCursor")
            if not cursor:
                if turn_id:
                    raise RuntimeError(t("已锁定的 Codex 回合无法读取，请检查原会话。", "The pinned Codex turn cannot be read. Check the Codex chat."))
                return None

    @staticmethod
    def legacy_history_error(exc):
        return any(x in str(exc).lower() for x in ("unknown method", "method not found",
                   "unsupported", "pagination", "paginated"))

    def explicitly_aborted(self, turn_id):
        # A second App Server may label a live turn interrupted without a completion time.
        # Its owning process writes an explicit turn_aborted event on cancellation.
        if self.rollout:
            try:
                with self.rollout.open("rb") as f:
                    stat = os.fstat(f.fileno())
                    if self.log_inode != stat.st_ino or stat.st_size < self.log_position:
                        self.log_position = 0
                        self.aborted_turns.clear()
                    self.log_inode = stat.st_ino
                    f.seek(self.log_position)
                    for line in f:
                        if not line.endswith(b"\n"):
                            break
                        self.log_position += len(line)
                        if b'"turn_aborted"' in line:
                            event = json.loads(line)
                            payload = event.get("payload", {})
                            if event.get("type") == "event_msg" and payload.get("type") == "turn_aborted":
                                self.aborted_turns.add(payload.get("turn_id"))
            except OSError:
                pass
        return turn_id in self.aborted_turns

    def turn_state(self, turn):
        status = turn["status"]
        if status in ("completed", "failed"):
            return status
        if status == "interrupted" and (turn.get("completedAt") is not None or self.explicitly_aborted(turn["id"])):
            return "interrupted"
        if status not in ("inProgress", "interrupted"):
            raise RuntimeError(t("无法识别 Codex 回合状态 ", "Unknown Codex turn status ") + str(status))
        return "pending"

    def turn_output(self, turn_id):
        items, cursor = [], None
        while True:
            try:
                page = self.rpc("thread/items/list", {"threadId":self.sid, "turnId":turn_id,
                                                     "limit":100, "cursor":cursor})
            except RuntimeError as exc:
                if not self.legacy_history_error(exc):
                    raise
                thread = self.rpc("thread/read", {"threadId":self.sid, "includeTurns":True})["thread"]
                turn = next((t for t in thread["turns"] if t["id"] == turn_id), None)
                if turn is None:
                    raise RuntimeError(t("原 Codex 回合已不可读。", "The Codex turn is no longer readable."))
                items = turn["items"]
                break
            items.extend(r["item"] for r in page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return codex_output(items)

    def latest(self):
        turn = self.get_turn()
        if not turn or self.turn_state(turn) != "completed":
            raise RuntimeError(t("Codex 的最新一轮尚未完成。", "Codex's latest turn has not finished."))
        return self.turn_output(turn["id"])[1]

    def wait_for_receipt(self, turn_id, pause):
        while not pause():
            turn = self.get_turn(turn_id)
            state = self.turn_state(turn)
            if state == "completed":
                final, receipt = self.turn_output(turn_id)
                if not final:
                    raise RuntimeError(t("Codex 回合已结束，但没有可审查的最终答复。", "The Codex turn ended without a final answer to review."))
                return receipt
            if state in ("failed", "interrupted"):
                raise RuntimeError(t("锁定的 Codex 回合已失败或中断。请在原会话处理，再选择新的执行回合。",
                                   "The pinned Codex turn failed or was interrupted. Handle it in the Codex chat, then pick a new turn."))
            time.sleep(2)
        return None

    def attach(self):
        if self.attached:
            return
        try:
            self.rpc("thread/resume", {"threadId":self.sid, "excludeTurns":True})
        except RuntimeError as exc:
            if "active writer" in str(exc):
                return  # The owning client consumes messages from the shared queue.
            raise
        self.attached = True

    def queued_run(self, prompt):
        def turns():
            return self.rpc("thread/turns/list", {"threadId":self.sid,"sortDirection":"desc",
                                                "itemsView":"notLoaded","limit":16})["data"]

        baseline = {t["id"] for t in turns()}
        cmd = agent_command("codex", "queue", "--thread", self.sid, "--message", prompt, "--resume")
        result = subprocess.run(cmd, cwd=self.root, capture_output=True, encoding="utf-8", timeout=30,
                                **cli_subprocess())
        match = re.search(r"Queued message ([0-9a-f-]{36})", result.stdout, re.I)
        if result.returncode or not match:
            raise RuntimeError(t("Codex 队列未确认接收。请核对原会话。 ", "The Codex queue did not confirm the message. Check the Codex chat. ")
                               + (result.stderr or result.stdout)[-800:])
        queue_id = match.group(1)
        if self.started:
            self.started("queued:" + queue_id)
        seen, target = set(), None
        deadline = time.monotonic() + 180
        while True:
            for t in turns():
                tid = t["id"]
                if tid in baseline or tid in seen or (target and target != tid):
                    continue
                if not target:
                    head = self.rpc("thread/items/list", {"threadId":self.sid,"turnId":tid,"limit":8})["data"]
                    messages = [r["item"] for r in head if r["item"]["type"] == "userMessage"]
                    if not any(m.get("clientId") == queue_id or
                               any(b.get("text") == prompt for b in m.get("content", [])) for m in messages):
                        if messages:
                            seen.add(tid)
                        continue
                    target = tid
                    if self.started:
                        self.started(tid)
                if t["status"] == "completed":
                    final, receipt = self.turn_output(tid)
                    if not final:
                        raise RuntimeError(t("Codex 队列任务完成，但缺少最终答复。", "The queued Codex turn finished without a final answer."))
                    return final, receipt
                if self.turn_state(t) in ("failed", "interrupted"):
                    raise RuntimeError(t("Codex 队列任务已中断。请核对原会话。", "The queued Codex turn was interrupted. Check the Codex chat."))
            if not target and time.monotonic() > deadline:
                raise RuntimeError(t("指令已排队但尚未观察到对应回合。请打开原 Codex 会话检查队列；不要重复发送。",
                                   "The prompt is queued but no turn has started. Check the queue in the Codex chat; do not send it again."))
            time.sleep(2)

    def run(self, prompt, manager):
        if self.rpc("thread/read", {"threadId":self.sid})["thread"].get("status", {}).get("type") == "active":
            raise RuntimeError(t("Codex 正在运行另一项任务。请等待原任务结束后再派单。",
                               "Codex is busy with another task. Wait for it to finish before dispatching."))
        self.attach()
        if not self.attached:
            return self.queued_run(prompt)
        self.pending = []
        turn = self.rpc("turn/start", {"threadId":self.sid,"input":[{"type":"text","text":prompt,"text_elements":[]}]})["turn"]["id"]
        self.turn = turn
        if self.started:
            self.started(turn)
        items = {}
        while True:
            msg = self.pending.pop(0) if self.pending else self.receive()
            event, p = msg.get("method"), msg.get("params", {})
            if p.get("threadId") != self.sid:
                continue
            if event == "item/completed" and p.get("turnId") == turn:
                item = p["item"]
                items[item["id"]] = item
                if self.listener:
                    for piece in codex_view(item):
                        self.listener(piece)
            if event == "turn/completed" and p["turn"]["id"] == turn:
                self.turn = None
                if p["turn"]["status"] != "completed":
                    raise RuntimeError(t("Codex 本轮没有成功结束。 ", "The Codex turn did not succeed. ")
                                       + str(p["turn"].get("error") or p["turn"]["status"]))
                for item in p["turn"].get("items", []):
                    items[item["id"]] = item
                final, receipt = codex_output(items.values())
                if not final:
                    raise RuntimeError(t("Codex 本轮缺少最终答复。", "The Codex turn has no final answer."))
                return final, receipt


def codex_threads(root, limit=40):
    """The project's top-level Codex chats, newest first, for the chat picker."""
    root = Path(root).expanduser().resolve()
    codex = Codex(None, root)
    try:
        rows = codex.rpc("thread/list", {"cwd":str(root), "limit":limit, "sortKey":"updated_at"}).get("data", [])
    finally:
        codex.close()
    chats = []
    for row in rows:
        if row.get("parentThreadId") or row.get("attachedToThreadId") or row.get("ephemeral"):
            continue  # Sub-agents and scratch threads are not chats you can bind.
        if Path(row.get("cwd") or "/").resolve() != root:
            continue
        title = row.get("name") or short(row.get("preview") or "", 60) or row["id"]
        chats.append(dict(id=row["id"], title=title, modified=float(row.get("updatedAt") or 0)))
    return chats
