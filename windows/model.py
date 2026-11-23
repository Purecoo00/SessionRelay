"""Pair persistence and the Qt client for relay.py's JSON lines protocol."""
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QIODevice, QObject, QProcess, QProcessEnvironment, QSaveFile, Signal

from relay_platform import WINDOWS, relay_support, script_command, terminate_tree

ROOT = Path(__file__).resolve().parents[1]
STRINGS = re.compile(r'("(?:[^"\\]|\\.)*")\s*=\s*("(?:[^"\\]|\\.)*")\s*;')


class Language:
    def __init__(self, code):
        self.code = code
        path = ROOT / f"{'en' if code == 'en' else 'zh-Hans'}.lproj" / "Localizable.strings"
        self.strings = {json.loads(key): json.loads(value)
                        for key, value in STRINGS.findall(path.read_text(encoding="utf-8"))}

    def __call__(self, key, *args):
        text = self.strings.get(key, key)
        for arg in args:
            text = re.sub(r"%lld|%@", lambda _: str(arg), text, count=1)
        if WINDOWS:
            text = text.replace("this Mac", "this PC").replace("in Finder", "in File Explorer")
            text = text.replace("在 Finder 中", "在文件资源管理器中")
        return text


@dataclass
class Pair:
    id: str
    name: str = ""
    project: str = ""
    document: str = ""
    codex: str = ""
    claude: str = ""
    manager: str = "claude"
    mode: str = "latest"
    goal: str = ""
    relayMode: str = "live"
    limit: int = 3

    @classmethod
    def fresh(cls, other):
        return cls("p-" + uuid4().hex[:8], project=other.project, document=other.document,
                   relayMode=other.relayMode, limit=other.limit)

    @property
    def configured(self):
        return bool(self.project and self.document)

    @property
    def ready(self):
        return bool(self.configured and self.codex and self.claude and (self.mode != "goal" or self.goal))

    @property
    def live_base(self):
        return Path(self.project) / ".session-relay" / "live" / self.id

    @property
    def checked_key(self):
        return "|".join((self.project, self.codex, self.claude))

    def config(self, command, force=False):
        config = asdict(self)
        config["pair"] = config.pop("id")
        del config["name"], config["relayMode"]
        config["command"] = command
        if force:
            config.update(mode="resume", force=True)
        return config


def last_path_part(value):
    return value.strip().rstrip("/").rsplit("/", 1)[-1]


def atomic_write(path, data=b""):
    file = QSaveFile(str(path))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(file.errorString())
    if file.write(data) != len(data) or not file.commit():
        raise OSError(file.errorString())


class Request(QProcess):
    """One backend process. Parse complete stdout lines even across read boundaries."""
    def __init__(self, store, config, receive, finish):
        super().__init__(store)
        self.config, self.receive, self.finish = config, receive, finish
        self.buffer = b""
        self.errors = b""
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SESSION_RELAY_LANG", store.language.code)
        self.setProcessEnvironment(env)
        if getattr(sys, "frozen", False):
            suffix = ".exe" if WINDOWS else ""
            worker = Path(sys.executable).with_name("relay-worker" + suffix)
            command = [str(worker), "relay.py"]
        else:
            command = script_command(ROOT / "relay.py")
            command.insert(1, "-u")
        self.setProgram(command[0])
        self.setArguments(command[1:])
        self.started.connect(self.send_config)
        self.readyReadStandardOutput.connect(self.read_output)
        self.readyReadStandardError.connect(self.read_errors)
        self.finished.connect(self.completed)
        self.errorOccurred.connect(self.start_failed)
        store.requests.add(self)

    def send_config(self):
        self.write((json.dumps(self.config, ensure_ascii=False) + "\n").encode("utf-8"))
        self.closeWriteChannel()

    def read_output(self):
        self.buffer += bytes(self.readAllStandardOutput())
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        for line in lines:
            self.parse(line)

    def parse(self, line):
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            return
        if isinstance(event, dict):
            self.receive(event)

    def read_errors(self):
        self.errors = (self.errors + bytes(self.readAllStandardError()))[-1800:]

    def completed(self, code, _status):
        self.read_output()
        self.parse(self.buffer)
        self.read_errors()
        self.finish(code, self.errors.decode("utf-8", "replace"), "")
        self.dispose()

    def start_failed(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.finish(-1, "", self.errorString())
            self.dispose()

    def dispose(self):
        self.parent().requests.discard(self)
        self.deleteLater()

    def stop(self):
        if self.state() == QProcess.ProcessState.Running and WINDOWS:
            terminate_tree(self.processId())
        else:
            self.terminate()
        if not self.waitForFinished(1000) and self.state() != QProcess.ProcessState.NotRunning:
            self.kill()
            self.waitForFinished(1000)


class Store(QObject):
    changed = Signal(str, str)
    storage_error = Signal(str)

    def __init__(self, language, demo=False, settings=None):
        super().__init__()
        self.language, self.demo = language, demo
        self.settings = settings if settings is not None else relay_support() / "settings.json"
        self.data = {} if demo else self.read()
        keys = {f.name for f in fields(Pair)}
        saved = self.data.get("pairs")
        if isinstance(saved, list) and saved and all(isinstance(row, dict) and isinstance(row.get("id"), str)
                                                      for row in saved):
            self.pairs = [Pair(**{k: v for k, v in row.items() if k in keys}) for row in saved]
        else:
            # The original binding and lastRunFolder use the first pair's empty ID.
            self.pairs = [Pair("", **{k: self.data[k] for k in keys - {"id", "name"} if k in self.data})]
        last = self.data.get("selectedPair")
        self.selected = last if any(p.id == last for p in self.pairs) else self.pairs[0].id
        self.tab = "setup"
        self.discovery, self.discovery_error, self.runs = {}, {}, {}
        self.probing, self.requests = set(), set()

    def read(self):
        try:
            data = json.loads(self.settings.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self):
        if self.demo:
            return
        self.data.update(pairs=[asdict(pair) for pair in self.pairs], selectedPair=self.selected)
        try:
            self.settings.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.settings, json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError as exc:
            self.storage_error.emit(str(exc))

    @property
    def current(self):
        return next(p for p in self.pairs if p.id == self.selected)

    def run(self, id):
        if id not in self.runs:
            self.runs[id] = Run(self, id)
        return self.runs[id]

    def title(self, pair):
        if pair.name:
            return pair.name
        for chat in self.discovery.get(pair.project, {}).get("codex", []):
            if chat["id"] == pair.codex:
                return chat["title"]
        return Path(pair.project).name if pair.project else self.language("新配对")

    def siblings(self, pair):
        return bool(pair.project and any(p.id != pair.id and p.project == pair.project for p in self.pairs))

    def add(self, source=None):
        pair = Pair.fresh(source or self.current)
        if source is not None:
            pair.name = source.name + " 2" if source.name else ""
            pair.manager, pair.mode, pair.goal = source.manager, source.mode, source.goal
        self.pairs.append(pair)
        self.tab = "setup"
        self.select(pair.id)

    def select(self, id):
        self.selected = id
        self.save()
        self.changed.emit(id, "selected")

    def delete(self, pair):
        if len(self.pairs) < 2 or self.run(pair.id).busy:
            return
        if pair.project and not self.demo:
            (pair.live_base / "binding.json").unlink(missing_ok=True)
        self.pairs.remove(pair)
        self.runs.pop(pair.id, None)
        self.select(self.pairs[0].id if self.selected == pair.id else self.selected)

    def discover(self, project):
        if self.demo or not project or project in self.probing:
            return
        self.probing.add(project)
        events = []

        def finish(code, errors, failure):
            self.probing.discard(project)
            result = next((e for e in events if e.get("kind") == "discovery"), None)
            if code == 0 and result is not None:
                previous = self.discovery.get(project)
                self.discovery[project] = result
                self.discovery_error.pop(project, None)
                if result == previous:
                    return
            else:
                self.discovery.pop(project, None)
                message = next((e.get("message") for e in events if e.get("kind") == "error"), "")
                self.discovery_error[project] = message or failure or self.language("会话检查失败")
            self.changed.emit(project, "discovery")

        Request(self, {"command": "discover", "project": project}, events.append, finish).start()

    def stop(self):
        for request in list(self.requests):
            request.stop()


class Run:
    def __init__(self, store, id):
        self.store, self.id = store, id
        self.L = store.language
        self.busy = self.paused_requested = self.desktop_blocked = self.live_enabled = self.live_paused = False
        self.status = "等待选择会话"
        self.checked_pair = self.note = self.pause_file = self.stage = self.live_role = self.live_text = ""
        self.round = 0
        self.entries, self.chat, self.expanded = [], [], set()
        self.folder_key = "lastRunFolder" + ("." + id if id else "")
        self.folder = store.data.get(self.folder_key, "")
        self.history_version = 0
        self.history_pending = None

    def changed(self, part="run"):
        self.store.changed.emit(self.id, part)

    @property
    def tone(self):
        if self.busy:
            return "active"
        if self.status in ("需要处理", "已中断", "启动失败"):
            return "bad"
        if self.status in ("等待处理", "桌面窗口正在使用", "已暂停", "等待登录", "正在暂停", "等待本轮结束"):
            return "warn"
        if self.status in ("已连接", "已完成", "原会话接力已启用"):
            return "good"
        return "neutral"

    @property
    def digest(self):
        return Path(self.folder).parent.parent / "LATEST.md" if self.folder else None

    def remember(self, folder):
        if self.folder != folder:
            self.chat = []
            self.folder = folder
        if not self.store.demo:
            self.store.data[self.folder_key] = folder
            self.store.save()

    def refresh_flags(self, pair):
        if self.store.demo or not pair.project:
            return
        flags = ((pair.live_base / "binding.json").exists(), (pair.live_base / "pause").exists())
        if flags != (self.live_enabled, self.live_paused):
            self.live_enabled, self.live_paused = flags
            self.changed("flags")

    def refresh_live(self, pair):
        if self.store.demo or not pair.project:
            return
        self.refresh_flags(pair)
        base = pair.live_base
        if self.folder and Path(self.folder).is_relative_to(base):
            try:
                name = (base / "current").read_text(encoding="utf-8").strip()
            except OSError:
                name = ""
            if name and str(base / name) != self.folder:
                self.remember(str(base / name))
                self.changed()
                self.changed("chat")
        self.load_history()

    def load_history(self):
        folder, version = self.folder, self.history_version
        target = (folder, version)
        if not folder or self.busy or self.history_pending == target:
            return
        events = []
        self.history_pending = target

        def finish(code, _errors, _failure):
            if self.history_pending == target:
                self.history_pending = None
            if code or folder != self.folder or version != self.history_version or self.busy:
                return
            rows = next((e["messages"] for e in events if e.get("kind") == "history"), None)
            if rows is not None and self.chat != rows:
                self.chat = rows
                self.changed("chat")

        Request(self.store, {"command": "history", "folder": folder}, events.append, finish).start()

    def set_live_pause(self, pair):
        if self.store.demo:
            self.note = self.L("演示模式不会启动接力。")
        else:
            paused = not self.live_paused
            file = pair.live_base / "pause"
            try:
                if paused:
                    atomic_write(file)
                else:
                    file.unlink(missing_ok=True)
                self.live_paused = paused
                self.note = self.L("已暂停派单。Codex 正在执行的回合会照常完成，Claude 收到回执后不会再派单。"
                                   if paused else "已恢复派单。")
            except OSError as exc:
                self.note = str(exc)
        self.changed("flags")

    def pause(self):
        if not self.pause_file:
            return
        try:
            atomic_write(self.pause_file)
            self.paused_requested = True
            self.status = "正在暂停" if self.stage == "waiting" else "等待本轮结束"
        except OSError as exc:
            self.note = str(exc)
        self.changed()

    def launch(self, config):
        if self.busy:
            return
        if self.store.demo:
            self.note = self.L("演示模式不会启动接力。")
            self.changed()
            return
        self.history_version += 1
        self.status = "准备 Code 会话" if config["command"] == "create" else "正在连接"
        self.paused_requested = self.desktop_blocked = False
        self.busy = True
        self.pause_file = self.note = self.stage = self.live_role = self.live_text = ""
        self.round = 0
        self.log(self.L(self.status))
        self.changed()

        def finish(code, errors, failure):
            if errors:
                self.log(errors)
            if failure:
                self.status, self.note = "启动失败", failure
            elif code and self.status != "需要处理":
                self.status, self.note = "已中断", self.L("请查看记录，并核对最后一次交接。")
            self.busy = False
            self.pause_file = self.live_text = self.live_role = ""
            self.changed()
            self.changed("chat")

        Request(self.store, config, self.receive, finish).start()

    def log(self, message):
        self.entries.append((datetime.now(), message))
        self.changed("log")

    def receive(self, event):
        kind, message = event.get("kind"), event.get("message", "")
        if kind == "turn" and "id" in event and "role" in event:
            row = {key: event.get(key, default) for key, default in
                   (("id", ""), ("role", ""), ("round", 0), ("title", ""), ("text", ""), ("path", ""))}
            index = next((i for i, old in enumerate(self.chat) if old["id"] == row["id"]), len(self.chat))
            self.chat[index:index + 1] = [row]
            if row["role"] in ("review", "receipt"):
                self.live_text = self.live_role = ""
            self.changed("chat")
            return
        if kind == "stream":
            role, piece = event.get("role", ""), event.get("text", "")
            if role != self.live_role:
                self.live_role, self.live_text = role, ""
            self.live_text = self.live_text + "\n\n" + piece if self.live_text else piece
            if len(self.live_text) > 20000:
                self.live_text = "…\n" + self.live_text[-20000:]
            self.changed("chat")
            return
        self.round = event.get("round", self.round)
        self.stage = event.get("stage", self.stage)
        if kind == "control":
            self.pause_file = message
        elif kind == "folder":
            self.remember(message)
            self.changed("chat")
        else:
            statuses = {"login": "等待登录", "created": "等待 Code 会话", "error": "需要处理", "checked": "已连接",
                        "bound": "原会话接力已启用", "done": "已完成", "paused": "已暂停", "blocked": "等待处理",
                        "desktop": "桌面窗口正在使用"}
            phases = {"waiting": "等待 Codex 回执", "review": "指挥者审查中", "execute": "执行者工作中"}
            self.status = statuses.get(kind, "正在暂停" if self.paused_requested else phases.get(self.stage, "运行中"))
            self.note = message
            if kind == "created":
                self.note = self.L("已打开终端。完成登录，等 Claude 读完文档后，在终端输入 /exit，再回到这里开始。")
                pair = next(p for p in self.store.pairs if p.id == self.id)
                pair.claude = message
                self.store.save()
                self.changed("created")
            elif kind == "bound":
                self.live_enabled = True
            elif kind == "paused":
                self.note = self.L("下次选择「继续上次」即可接着运行。")
            elif kind == "desktop":
                self.desktop_blocked = True
            self.log(self.note if kind == "created" else message)
        self.changed()
