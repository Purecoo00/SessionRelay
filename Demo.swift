import SwiftUI
import AppKit

/// Sample data for screenshots and UI work. Launch with SESSION_RELAY_DEMO=1;
/// add SESSION_RELAY_SNAPSHOT=<folder> to export every page in light and dark mode, then quit.
/// Demo mode never starts a relay or reads local sessions. It follows the app language
/// (for example `-AppleLanguages "(en)"`).
enum Demo {
    static let run = "/path/to/parser-kit/.session-relay/live/20260101-090000-demo"

    static func message(_ id: String, _ round: Int, _ role: String, _ title: (String, String),
                        _ text: (String, String), _ file: String) -> ChatMessage {
        ChatMessage(["id": id, "round": round, "role": role, "title": english ? title.1 : title.0,
                     "text": english ? text.1 : text.0, "path": run + "/" + file])!
    }

    static var chat: [ChatMessage] { [
        message("0-receipt", 0, "receipt", ("起点 · 目标", "Start · Goal"),
                ("为 `parser` 模块补齐边界测试，并修复空输入时的崩溃。",
                 "Add edge-case tests for the `parser` module and fix the crash on empty input."), "000-receipt.txt"),
        message("0-review", 0, "review", ("Claude 审查", "Claude review"), ("""
            读完了任务文档和现有测试。

            **结论**：空输入崩溃来自 `tokenize()` 没有处理 EOF。先让 Codex 写出失败用例，再做最小修复。

            ▸ Read src/parser.py

            ▸ Edit docs/task.md

            ▸ 提交给 Codex 的指令（见下方）
            """, """
            Read the task document and the existing tests.

            **Finding**: the empty-input crash comes from `tokenize()` not handling EOF. Have Codex write failing tests first, then make the smallest fix.

            ▸ Read src/parser.py

            ▸ Edit docs/task.md

            ▸ Prompt for Codex (below)
            """), "000-decision.txt"),
        message("0-prompt", 0, "prompt", ("发给 Codex 的指令", "Prompt for Codex"), ("""
            请先阅读任务文档第 2 节。
            1. 在 `tests/test_parser.py` 增加空输入、仅空白、超长行三个用例。
            2. 修复 `tokenize()` 的 EOF 处理，改动保持最小。
            3. 运行 `pytest -q` 并贴出结果。
            验收：三个新用例全部通过，原有测试不回退。
            """, """
            Read section 2 of the task document first.
            1. Add three cases to `tests/test_parser.py`: empty input, whitespace only, a very long line.
            2. Fix EOF handling in `tokenize()` with the smallest change.
            3. Run `pytest -q` and paste the result.
            Done when: all three new cases pass and no existing test regresses.
            """), "001-prompt.txt"),
        message("1-receipt", 1, "receipt", ("Codex 执行与回执", "Codex run and receipt"), ("""
            ▸ 命令 pytest -q tests/test_parser.py

            ▸ 修改文件 src/parser.py, tests/test_parser.py

            ▸ 命令 pytest -q

            已完成。新增 3 个用例，修复了 `tokenize()` 在 EOF 时越界读取的问题。
            `pytest -q`：**48 passed** in 2.31s。
            """, """
            ▸ Command pytest -q tests/test_parser.py

            ▸ Edited src/parser.py, tests/test_parser.py

            ▸ Command pytest -q

            Done. Added 3 cases and fixed the out-of-bounds read in `tokenize()` at EOF.
            `pytest -q`: **48 passed** in 2.31s.
            """), "001-receipt.txt"),
        message("1-review", 1, "review", ("Claude 审查", "Claude review"), ("""
            核对了回执和改动：三个用例都覆盖到了，EOF 分支只改了两行。结论已写入任务文档。

            ▸ Read src/parser.py

            ▸ Edit docs/task.md

            ▸ 结束审查：done · 等待用户确认
            """, """
            Checked the receipt and the diff: all three cases are covered and the EOF branch changed by two lines. The finding is in the task document.

            ▸ Read src/parser.py

            ▸ Edit docs/task.md

            ▸ Review finished: done · waiting for the user
            """), "001-decision.txt"),
        message("1-decision", 1, "decision", ("接力完成，等待你确认", "Relay done, waiting for you"),
                ("边界测试与 EOF 修复已完成，任务文档已更新。请审阅后再开始下一项。",
                 "Edge-case tests and the EOF fix are done and the task document is updated. Review before the next item."),
                "001-mcp.json"),
    ] }

    static func seed(_ store: Store) {
        func name(_ zh: String, _ en: String) -> String { english ? en : zh }
        let project = "/path/to/parser-kit"
        var main = Pair(id: "")
        main.name = name("parser-kit · 边界测试", "parser-kit · edge cases")
        main.project = project; main.document = project + "/docs/task.md"
        main.codex = "019a3f2e-7c41-7d20-9b6e-2f5a8c1d4e77"; main.claude = "5c8e2b14-3a9d-4f61-8e27-b0d9c6a1f3e2"
        main.limit = 5
        var perf = Pair(id: "p-perf")
        perf.name = name("parser-kit · 性能", "parser-kit · performance")
        perf.project = project; perf.document = project + "/docs/perf.md"
        perf.codex = "019a4410-2b7e-7f13-a6c4-5d0e9b8f2a61"; perf.claude = "8f1d3c27-6b4e-4a90-9d52-c7e1a0b6f384"
        var docs = Pair(id: "p-docs")
        docs.name = name("文档站点", "Docs site")
        docs.project = "/path/to/docs-site"; docs.document = "/path/to/docs-site/TODO.md"
        docs.relayMode = "app"
        store.pairs = [main, perf, docs]
        store.selected = main.id
        store.discovery[project] = CodeDiscovery(
            loggedIn: true,
            sessions: [CodeSession(id: main.claude, title: name("审查：边界测试", "Review: edge cases"), alias: "", modified: 1767250800),
                       CodeSession(id: perf.claude, title: name("审查：性能", "Review: performance"), alias: "", modified: 1767247200)],
            codex: [CodexChat(id: main.codex, title: name("parser 边界测试", "parser edge cases"), modified: 1767250800),
                    CodexChat(id: perf.codex, title: name("parser 性能调优", "parser performance"), modified: 1767247200)],
            codexError: "")

        store.run(perf.id).liveEnabled = true
        store.run(perf.id).livePaused = true
        store.run(perf.id).status = "原会话接力已启用"
        store.run(docs.id).status = "已完成"

        let ctl = store.run(main.id)
        ctl.chat = chat
        ctl.liveEnabled = true
        ctl.status = "原会话接力已启用"
        ctl.folder = run
        let now = Date()
        let lines = english ? [
            "Bound the Codex chat \"parser-kit\" with up to 5 rounds.",
            "Round 1 prompt is running (Codex turn 019a3f40).",
            "Codex round 1 is done; the receipt went to the reviewer session.",
            "The reviewer session ended the round: waiting for the user.",
        ] : [
            "已绑定 Codex 会话「parser-kit」，本次最多派出 5 轮。",
            "第 1 轮指令已开始执行（Codex 回合 019a3f40）。",
            "Codex 第 1 轮已完成，回执已交给审查会话。",
            "审查会话结束本轮：等待用户确认。",
        ]
        ctl.entries = lines.enumerated().map { Entry(time: now.addingTimeInterval(Double($0.offset - 4) * 140), message: $0.element) }
        if let folder = ProcessInfo.processInfo.environment["SESSION_RELAY_SNAPSHOT"] {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { snapshot(folder, store, ctl) }
        }
    }

    static func snapshot(_ folder: String, _ store: Store, _ ctl: Run) {
        guard let window = NSApp.windows.first(where: { $0.isVisible }) else { NSApp.terminate(nil); return }
        window.setContentSize(NSSize(width: 1120, height: 720))
        window.center()
        var steps: [(String, () -> Void)] = []
        for (name, look) in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
            for tab in ["setup", "chat", "log"] {
                steps.append(("\(tab)-\(name)", { NSApp.appearance = NSAppearance(named: look); store.tab = tab }))
            }
            steps.append(("chat-live-\(name)", {
                store.tab = "chat"; ctl.busy = true; ctl.stage = "review"; ctl.round = 2; ctl.status = "指挥者审查中"
                ctl.liveRole = "claude"
                ctl.liveText = english
                    ? "Checking the test output in the round 2 receipt…\n\n▸ Read tests/test_parser.py\n\n▸ Read src/parser.py"
                    : "正在核对第 2 轮回执里的测试输出…\n\n▸ Read tests/test_parser.py\n\n▸ Read src/parser.py"
            }))
            steps.append(("note-\(name)", {
                ctl.busy = false; ctl.liveText = ""; ctl.status = "桌面窗口正在使用"; store.tab = "setup"
                ctl.note = english
                    ? "The desktop window used this Claude session within the last 2 min. To keep both sides from editing the task document at once, the relay paused before calling Claude."
                    : "桌面窗口约 2 分钟内还在使用这个 Claude 会话。为避免两边同时修改任务文档，接力在调用 Claude 之前暂停。"
            }))
            steps.append(("reset-\(name)", { ctl.note = ""; ctl.status = "原会话接力已启用" }))
        }
        func run(_ index: Int) {
            guard index < steps.count else { NSApp.terminate(nil); return }
            let (name, apply) = steps[index]
            apply()
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                if !name.hasPrefix("reset") { capture(window, "\(folder)/\(name).png") }
                run(index + 1)
            }
        }
        run(0)
    }

    static func capture(_ window: NSWindow, _ path: String) {
        window.makeFirstResponder(nil)
        guard let view = window.contentView?.superview ?? window.contentView,
              let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
        try? framed(rep)?.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    }

    /// The window with rounded corners and a soft shadow on a transparent canvas, like a product shot.
    static func framed(_ shot: NSBitmapImageRep) -> NSBitmapImageRep? {
        let scale = CGFloat(shot.pixelsWide) / shot.size.width
        let margin: CGFloat = 48, radius: CGFloat = 14
        let size = NSSize(width: shot.size.width + margin * 2, height: shot.size.height + margin * 2)
        guard let out = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale), pixelsHigh: Int(size.height * scale),
                                         bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                         colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
        out.size = size
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: out)
        let window = NSRect(x: margin, y: margin + 6, width: shot.size.width, height: shot.size.height)
        let shape = NSBezierPath(roundedRect: window, xRadius: radius, yRadius: radius)
        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.28)
        shadow.shadowOffset = NSSize(width: 0, height: -10)
        shadow.shadowBlurRadius = 28
        NSGraphicsContext.saveGraphicsState()
        shadow.set()
        NSColor.black.setFill()
        shape.fill()
        NSGraphicsContext.restoreGraphicsState()
        shape.addClip()
        shot.draw(in: window)
        NSColor.black.withAlphaComponent(0.12).setStroke()
        shape.lineWidth = 1
        shape.stroke()
        NSGraphicsContext.restoreGraphicsState()
        return out
    }
}
