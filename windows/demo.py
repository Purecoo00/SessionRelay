"""The parser-kit demo and screenshot sequence from Demo.swift."""
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap

from windows.model import Pair

PROJECT = "/path/to/parser-kit"
RUN = PROJECT + "/.session-relay/live/20260101-090000-demo"
CHAT = [('0-receipt',
  0,
  'receipt',
  ('起点 · 目标', 'Start · Goal'),
  ('为 `parser` 模块补齐边界测试，并修复空输入时的崩溃。',
   'Add edge-case tests for the `parser` module and fix the crash on empty input.'),
  '000-receipt.txt'),
 ('0-review',
  0,
  'review',
  ('Claude 审查', 'Claude review'),
  ('读完了任务文档和现有测试。\n'
   '\n'
   '**结论**：空输入崩溃来自 `tokenize()` 没有处理 EOF。先让 Codex 写出失败用例，再做最小修复。\n'
   '\n'
   '▸ Read src/parser.py\n'
   '\n'
   '▸ Edit docs/task.md\n'
   '\n'
   '▸ 提交给 Codex 的指令（见下方）',
   'Read the task document and the existing tests.\n'
   '\n'
   '**Finding**: the empty-input crash comes from `tokenize()` not handling EOF. Have Codex write failing '
   'tests first, then make the smallest fix.\n'
   '\n'
   '▸ Read src/parser.py\n'
   '\n'
   '▸ Edit docs/task.md\n'
   '\n'
   '▸ Prompt for Codex (below)'),
  '000-decision.txt'),
 ('0-prompt',
  0,
  'prompt',
  ('发给 Codex 的指令', 'Prompt for Codex'),
  ('请先阅读任务文档第 2 节。\n'
   '1. 在 `tests/test_parser.py` 增加空输入、仅空白、超长行三个用例。\n'
   '2. 修复 `tokenize()` 的 EOF 处理，改动保持最小。\n'
   '3. 运行 `pytest -q` 并贴出结果。\n'
   '验收：三个新用例全部通过，原有测试不回退。',
   'Read section 2 of the task document first.\n'
   '1. Add three cases to `tests/test_parser.py`: empty input, whitespace only, a very long line.\n'
   '2. Fix EOF handling in `tokenize()` with the smallest change.\n'
   '3. Run `pytest -q` and paste the result.\n'
   'Done when: all three new cases pass and no existing test regresses.'),
  '001-prompt.txt'),
 ('1-receipt',
  1,
  'receipt',
  ('Codex 执行与回执', 'Codex run and receipt'),
  ('▸ 命令 pytest -q tests/test_parser.py\n'
   '\n'
   '▸ 修改文件 src/parser.py, tests/test_parser.py\n'
   '\n'
   '▸ 命令 pytest -q\n'
   '\n'
   '已完成。新增 3 个用例，修复了 `tokenize()` 在 EOF 时越界读取的问题。\n'
   '`pytest -q`：**48 passed** in 2.31s。',
   '▸ Command pytest -q tests/test_parser.py\n'
   '\n'
   '▸ Edited src/parser.py, tests/test_parser.py\n'
   '\n'
   '▸ Command pytest -q\n'
   '\n'
   'Done. Added 3 cases and fixed the out-of-bounds read in `tokenize()` at EOF.\n'
   '`pytest -q`: **48 passed** in 2.31s.'),
  '001-receipt.txt'),
 ('1-review',
  1,
  'review',
  ('Claude 审查', 'Claude review'),
  ('核对了回执和改动：三个用例都覆盖到了，EOF 分支只改了两行。结论已写入任务文档。\n'
   '\n'
   '▸ Read src/parser.py\n'
   '\n'
   '▸ Edit docs/task.md\n'
   '\n'
   '▸ 结束审查：done · 等待用户确认',
   'Checked the receipt and the diff: all three cases are covered and the EOF branch changed by two lines. '
   'The finding is in the task document.\n'
   '\n'
   '▸ Read src/parser.py\n'
   '\n'
   '▸ Edit docs/task.md\n'
   '\n'
   '▸ Review finished: done · waiting for the user'),
  '001-decision.txt'),
 ('1-decision',
  1,
  'decision',
  ('接力完成，等待你确认', 'Relay done, waiting for you'),
  ('边界测试与 EOF 修复已完成，任务文档已更新。请审阅后再开始下一项。',
   'Edge-case tests and the EOF fix are done and the task document is updated. Review before the next '
   'item.'),
  '001-mcp.json')]

def seed(store):
    def pick(zh, en):
        return en if store.language.code == "en" else zh

    main = Pair("", name=pick("parser-kit · 边界测试", "parser-kit · edge cases"),
                project=PROJECT, document=PROJECT + "/docs/task.md",
                codex="019a3f2e-7c41-7d20-9b6e-2f5a8c1d4e77", claude="5c8e2b14-3a9d-4f61-8e27-b0d9c6a1f3e2", limit=5)
    perf = Pair("p-perf", name=pick("parser-kit · 性能", "parser-kit · performance"),
                project=PROJECT, document=PROJECT + "/docs/perf.md",
                codex="019a4410-2b7e-7f13-a6c4-5d0e9b8f2a61", claude="8f1d3c27-6b4e-4a90-9d52-c7e1a0b6f384")
    docs = Pair("p-docs", name=pick("文档站点", "Docs site"), project="/path/to/docs-site",
                document="/path/to/docs-site/TODO.md", relayMode="app")
    store.pairs = [main, perf, docs]
    store.selected = main.id
    store.discovery[PROJECT] = dict(
        loggedIn=True, codexError="",
        sessions=[dict(id=main.claude, title=pick("审查：边界测试", "Review: edge cases"), alias="", modified=1767250800),
                  dict(id=perf.claude, title=pick("审查：性能", "Review: performance"), alias="", modified=1767247200)],
        codex=[dict(id=main.codex, title=pick("parser 边界测试", "parser edge cases"), modified=1767250800),
               dict(id=perf.codex, title=pick("parser 性能调优", "parser performance"), modified=1767247200)])
    other = store.run(perf.id)
    other.live_enabled = other.live_paused = True
    other.status = "原会话接力已启用"
    store.run(docs.id).status = "已完成"

    run = store.run(main.id)
    run.chat = [dict(id=id, round=round_, role=role, title=pick(*title), text=pick(*text), path=RUN + "/" + file)
                for id, round_, role, title, text, file in CHAT]
    run.live_enabled = True
    run.status = "原会话接力已启用"
    run.folder = RUN
    lines = [
        pick("已绑定 Codex 会话「parser-kit」，本次最多派出 5 轮。",
             'Bound the Codex chat "parser-kit" with up to 5 rounds.'),
        pick("第 1 轮指令已开始执行（Codex 回合 019a3f40）。",
             "Round 1 prompt is running (Codex turn 019a3f40)."),
        pick("Codex 第 1 轮已完成，回执已交给审查会话。",
             "Codex round 1 is done; the receipt went to the reviewer session."),
        pick("审查会话结束本轮：等待用户确认。", "The reviewer session ended the round: waiting for the user."),
    ]
    now = datetime.now()
    run.entries = [(now + timedelta(seconds=(index - 4) * 140), message) for index, message in enumerate(lines)]


class Snapshot:
    def __init__(self, app, window, folder):
        self.app, self.window, self.folder = app, window, Path(folder)
        self.steps = iter((theme, page) for theme in ("light", "dark")
                          for page in ("setup", "chat", "log", "chat-live", "note"))
        self.suffix = "" if window.store.language.code == "en" else "-zh"

    def start(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.window.resize(1120, 720)
        QTimer.singleShot(100, self.advance)

    def advance(self):
        step = next(self.steps, None)
        if step is None:
            self.app.quit()
            return
        theme, page = step
        english = self.window.store.language.code == "en"
        run = self.window.run
        run.status = "原会话接力已启用"
        run.busy = False
        run.live_role = run.live_text = run.note = ""
        run.stage, run.round = "", 0
        if page == "chat-live":
            run.busy, run.stage, run.round = True, "review", 2
            run.status, run.live_role = "指挥者审查中", "claude"
            run.live_text = ("Checking the test output in the round 2 receipt…" if english else "正在核对第 2 轮回执里的测试输出…")
            run.live_text += "\n\n▸ Read tests/test_parser.py\n\n▸ Read src/parser.py"
        elif page == "note":
            run.status = "桌面窗口正在使用"
            run.note = ("The desktop window used this Claude session within the last 2 min. To keep both sides from "
                        "editing the task document at once, the relay paused before calling Claude." if english else
                        "桌面窗口约 2 分钟内还在使用这个 Claude 会话。为避免两边同时修改任务文档，接力在调用 Claude 之前暂停。")
        self.window.apply_theme(theme)
        self.window.set_page({"chat-live": "chat", "note": "setup"}.get(page, page), force=True)
        path = self.folder / f"{page}-{theme}{self.suffix}.png"
        QTimer.singleShot(125, lambda: self.capture(path, live=page == "chat-live"))

    def capture(self, path, live):
        if live:
            scrollbar = self.window.views["chat"].verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        focus = self.app.focusWidget()
        if focus is not None:
            focus.clearFocus()
        shot = self.window.grab()
        if not framed(shot).save(str(path), "PNG"):
            self.app.exit(1)
            return
        QTimer.singleShot(0, self.advance)


def framed(shot):
    """Use the Swift demo's transparent margin, rounded corners and soft shadow."""
    dpr = shot.devicePixelRatio()
    width, height = shot.width() / dpr, shot.height() / dpr
    margin, radius = 48, 14
    canvas = QPixmap(round((width + 2 * margin) * dpr), round((height + 2 * margin) * dpr))
    canvas.setDevicePixelRatio(dpr)
    canvas.fill(Qt.GlobalColor.transparent)
    rect = QRectF(margin, margin - 6, width, height)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for size in range(27, 0, -1):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, max(1, (28 - size) // 4)))
        painter.drawRoundedRect(rect.translated(0, 9).adjusted(-size, -size, size, size), radius + size, radius + size)
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(rect.topLeft(), shot)
    painter.end()
    return canvas
