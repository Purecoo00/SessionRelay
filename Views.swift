import SwiftUI
import AppKit
import UniformTypeIdentifiers

// MARK: - Status

enum Tone {
    case neutral, active, good, warn, bad
    var color: Color {
        switch self {
        case .neutral: .secondary
        case .active, .good: .green
        case .warn: .orange
        case .bad: .red
        }
    }
    var symbol: String {
        switch self {
        case .neutral, .active: "info.circle.fill"
        case .good: "checkmark.circle.fill"
        case .warn: "exclamationmark.triangle.fill"
        case .bad: "xmark.octagon.fill"
        }
    }
}

extension Controller {
    /// Status strings are Chinese keys (see Localizable.strings); the tone follows the key.
    var tone: Tone {
        if busy { return .active }
        switch status {
        case "需要处理", "已中断", "启动失败": return .bad
        case "等待处理", "桌面窗口正在使用", "已暂停", "等待登录", "正在暂停", "等待本轮结束": return .warn
        case "已连接", "已完成", "原会话接力已启用": return .good
        default: return .neutral
        }
    }
}

struct StatusPill: View {
    let text: String
    let tone: Tone
    var body: some View {
        HStack(spacing: 6) {
            if tone == .active {
                ProgressView().controlSize(.mini)
            } else {
                Circle().fill(tone.color).frame(width: 7, height: 7)
            }
            Text(text).font(.callout.weight(.medium))
        }
        .padding(.horizontal, 10).padding(.vertical, 4)
        .background(tone.color.opacity(0.13), in: Capsule())
        .fixedSize()
    }
}

// MARK: - Chat

struct Avatar: View {
    let symbol: String
    let tint: Color
    var codex = false
    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(codex ? Color(nsColor: .windowBackgroundColor) : .white)
            .frame(width: 30, height: 30)
            .background(codex ? Color.primary : tint, in: Circle())
    }
}

struct RoundDivider: View {
    let round: Int
    var body: some View {
        HStack(spacing: 10) {
            line
            Group {
                if round == 0 { Text("起点") } else { Text("第 \(round) 轮") }
            }
            .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            line
        }.padding(.top, 6)
    }
    var line: some View { Rectangle().fill(.separator).frame(height: 1) }
}

struct MessageCard: View {
    let role: String
    let title: String
    let text: String
    let path: String
    var live = false
    var expanded = false
    var toggle: () -> Void = {}

    /// Prose keeps inline Markdown; "▸ tool" lines become one compact, muted block.
    private var rich: AttributedString {
        var out = AttributedString()
        var previousWasTool = false
        for (index, block) in text.components(separatedBy: "\n\n").enumerated() {
            let isTool = block.hasPrefix("▸") || block.hasPrefix("  ✗")
            if index > 0 { out += AttributedString(isTool && previousWasTool ? "\n" : "\n\n") }
            if isTool {
                var line = AttributedString(block)
                line.font = .system(size: 12, design: .monospaced)
                line.foregroundColor = .secondary
                out += line
            } else {
                out += (try? AttributedString(markdown: block, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
                    ?? AttributedString(block)
            }
            previousWasTool = isTool
        }
        return out
    }
    private var long: Bool { text.count > 1400 || text.split(separator: "\n", omittingEmptySubsequences: false).count > 18 }

    /// Claude speaks in the accent color, Codex in black / white, outcomes in green / orange.
    private var look: (symbol: String, tint: Color, codex: Bool) {
        switch role {
        case "review": ("text.magnifyingglass", accent, false)
        case "prompt": ("paperplane.fill", accent, false)
        case "live-claude": ("ellipsis", accent, false)
        case "live-codex": ("ellipsis", .primary, true)
        case "decision": path.hasSuffix("mcp.json") && !title.contains(L("接力受阻"))
            ? ("checkmark", .green, false) : ("exclamationmark", .orange, false)
        case "status": ("hourglass", .secondary, false)
        default: path.hasSuffix("000-receipt.txt") && !title.contains("Codex") && !title.contains("Claude")
            ? ("scope", .secondary, false) : ("terminal.fill", .primary, true)
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Avatar(symbol: look.symbol, tint: look.tint, codex: look.codex)
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Text(title).font(.system(size: 13, weight: .semibold))
                    if live { ProgressView().controlSize(.small) }
                    Spacer()
                    if !path.isEmpty {
                        Button { NSWorkspace.shared.open(URL(fileURLWithPath: path)) } label: {
                            Image(systemName: "arrow.up.forward.square")
                        }
                        .buttonStyle(.borderless).foregroundStyle(.secondary).help("打开原始文件")
                    }
                }
                Text(rich)
                    .font(.system(size: 13)).lineSpacing(3)
                    .textSelection(.enabled)
                    .lineLimit(expanded || live ? nil : 16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if long && !live {
                    Button(expanded ? L("收起") : L("展开全文")) { withAnimation(.snappy) { toggle() } }
                        .buttonStyle(.link).font(.caption)
                }
            }
            .padding(14)
            .background(role == "prompt" ? accent.opacity(0.08) : Color(nsColor: .controlBackgroundColor),
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(role == "prompt" ? accent.opacity(0.25) : Color.primary.opacity(0.07)))
        }
    }
}

// MARK: - Workspace

struct Workspace: View {
    @ObservedObject var ctl = Controller.shared
    @AppStorage("project") var project = ""
    @AppStorage("document") var document = ""
    @AppStorage("codex") var codex = ""
    @AppStorage("claude") var claude = ""
    @AppStorage("manager") var manager = "claude"
    @AppStorage("mode") var mode = "latest"
    @AppStorage("limit") var limit = 3
    @AppStorage("goal") var goal = ""
    @AppStorage("relayMode") var relayMode = "live"
    var root: URL { URL(fileURLWithPath: project) }
    var config: [String: Any] {
        ["project": project, "document": document, "codex": codex, "claude": claude,
         "manager": manager, "mode": mode, "limit": limit, "goal": goal]
    }
    var configured: Bool { !project.isEmpty && !document.isEmpty }
    var ready: Bool { configured && !codex.isEmpty && !claude.isEmpty && (mode != "goal" || !goal.isEmpty) }

    /// The task document as shown: relative inside the project, absolute elsewhere.
    var documentLabel: String {
        guard !document.isEmpty else { return L("未选择") }
        let prefix = root.path + "/"
        return !project.isEmpty && document.hasPrefix(prefix) ? String(document.dropFirst(prefix.count)) : document
    }

    func action(_ name: String, force: Bool = false) {
        var args = config; args["command"] = name
        if force { args["mode"] = "resume"; args["force"] = true }
        if name == "start" { ctl.tab = "chat" }
        ctl.launch(args)
    }

    var accountText: String {
        if !ctl.discoveryError.isEmpty { return ctl.discoveryError }
        guard let d = ctl.discovery else { return project.isEmpty ? L("先选择项目目录") : L("正在读取登录状态…") }
        return d.loggedIn ? L("已登录") : L("尚未登录")
    }

    func selectSession(_ discovery: CodeDiscovery) {
        let value = claude.trimmingCharacters(in: .whitespacesAndNewlines)
        let last = value.split(separator: "/").last.map(String.init) ?? value
        var sid = value
        if value.isEmpty, discovery.sessions.count == 1 {
            sid = discovery.sessions[0].id
        } else if !last.isEmpty, let match = discovery.sessions.first(where: {
            !$0.alias.isEmpty && ($0.alias == last || $0.alias == "local_" + last)
        }) {
            sid = match.id
        }
        if claude != sid { claude = sid }
        guard !ctl.busy, configured else { return }
        if discovery.loggedIn && !codex.isEmpty && !sid.isEmpty {
            let key = [project, codex, sid].joined(separator: "|")
            if ctl.checkedPair != key {
                ctl.checkedPair = key
                var args = config; args["command"] = "check"; args["claude"] = sid
                ctl.launch(args)
            }
        } else if ["等待选择会话", "等待登录", "已连接", "等待 Code 会话", "等待检查"].contains(ctl.status) {
            ctl.checkedPair = ""
            ctl.status = discovery.loggedIn ? "等待选择会话" : "等待登录"
        }
    }

    func choose() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.prompt = L("选择项目")
        panel.message = L("选择项目根目录")
        if !project.isEmpty { panel.directoryURL = root }
        if panel.runModal() == .OK, let url = panel.url, project != url.path {
            if ctl.discovery?.sessions.contains(where: { $0.id == claude }) == true { claude = "" }
            ctl.discovery = nil; project = url.path
        }
    }

    func chooseDocument() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true; panel.canChooseDirectories = false
        panel.allowedContentTypes = [UTType(filenameExtension: "md") ?? .plainText, .plainText]
        panel.prompt = L("选择任务文档")
        panel.message = L("选择指挥者每轮要阅读和更新的任务文档")
        panel.directoryURL = document.isEmpty ? (project.isEmpty ? nil : root)
                                              : URL(fileURLWithPath: document).deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url { document = url.path }
    }

    // MARK: Sidebar

    func navRow(_ key: String, _ label: LocalizedStringKey, _ symbol: String, badge: Int = 0) -> some View {
        let selected = ctl.tab == key
        return Button { ctl.tab = key } label: {
            HStack(spacing: 10) {
                Image(systemName: symbol).frame(width: 18)
                    .foregroundStyle(selected ? accent : .secondary)
                Text(label)
                Spacer()
                if badge > 0 {
                    Text(verbatim: "\(badge)").font(.caption.weight(.medium)).monospacedDigit()
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 7).padding(.vertical, 1)
                        .background(.quaternary, in: Capsule())
                }
            }
            .font(.system(size: 13, weight: selected ? .semibold : .regular))
            .padding(.horizontal, 10).frame(height: 32)
            .background(selected ? accent.opacity(0.14) : .clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    var sidebar: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("接力").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                .padding(.horizontal, 10).padding(.bottom, 4)
            navRow("setup", "设置", "slider.horizontal.3")
            navRow("chat", "对话", "bubble.left.and.bubble.right", badge: ctl.chat.count)
            navRow("log", "运行记录", "list.bullet.rectangle")
            Spacer()
        }
        .padding(.horizontal, 10).padding(.top, 8)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .safeAreaInset(edge: .top, spacing: 0) {
            HStack(spacing: 10) {
                Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(verbatim: "Session Relay").font(.headline)
                    Text(verbatim: "Claude ⇄ Codex").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.horizontal, 16).padding(.top, 6).padding(.bottom, 10)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            Button(action: choose) {
                HStack(spacing: 10) {
                    Image(systemName: "folder.fill").foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("当前项目").font(.caption).foregroundStyle(.secondary)
                        Text(project.isEmpty ? L("选择项目…") : root.lastPathComponent)
                            .font(.callout.weight(.medium)).lineLimit(1).truncationMode(.middle)
                    }
                    Spacer()
                    Image(systemName: "chevron.up.chevron.down").font(.caption).foregroundStyle(.tertiary)
                }
                .padding(10)
                .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain).disabled(ctl.busy)
            .help(project.isEmpty ? L("选择项目目录") : project)
            .padding(10)
        }
        .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 280)
    }

    // MARK: Setup

    var setupPage: some View {
        Form {
            Section {
                LabeledContent("项目目录") {
                    HStack {
                        Text(project.isEmpty ? L("未选择") : project)
                            .lineLimit(1).truncationMode(.middle)
                            .foregroundStyle(project.isEmpty ? .secondary : .primary)
                            .textSelection(.enabled)
                        Button(project.isEmpty ? L("选择…") : L("更改…"), action: choose)
                    }
                }
                LabeledContent("任务文档") {
                    HStack {
                        Text(documentLabel)
                            .font(.system(.callout, design: .monospaced))
                            .lineLimit(1).truncationMode(.middle)
                            .foregroundStyle(document.isEmpty ? .secondary : .primary)
                            .textSelection(.enabled)
                            .help(document)
                        Button(document.isEmpty ? L("选择…") : L("更改…"), action: chooseDocument)
                    }
                }
            } header: {
                Text("项目")
            } footer: {
                Text("任务文档是指挥者每轮阅读和更新的 Markdown 文件，可以放在项目里的任何位置。")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section {
                LabeledContent("Codex 会话") {
                    TextField("Codex 会话", text: $codex, prompt: Text("粘贴会话 ID 或链接"))
                        .labelsHidden().font(.system(.body, design: .monospaced))
                }
                LabeledContent("Claude Code 会话") {
                    HStack {
                        TextField("Claude Code 会话", text: $claude, prompt: Text("UUID 或 local_ 标识"))
                            .labelsHidden().font(.system(.body, design: .monospaced))
                        if let list = ctl.discovery?.sessions, !list.isEmpty {
                            Menu {
                                ForEach(list) { s in
                                    Button(s.label + " · " + String(s.id.prefix(8))) {
                                        claude = s.id
                                        ctl.checkedPair = ""
                                        if let d = ctl.discovery { selectSession(d) }
                                    }
                                }
                            } label: {
                                Text(list.first(where: { $0.id == claude })?.title ?? L("本项目会话"))
                            }
                            .fixedSize()
                        }
                    }
                }
                LabeledContent(LocalizedStringKey("Claude Code")) {
                    HStack(spacing: 8) {
                        Label(accountText, systemImage: ctl.discovery?.loggedIn == true ? "checkmark.circle.fill" : "person.crop.circle")
                            .foregroundStyle(ctl.discovery?.loggedIn == true ? .green : .secondary)
                            .fixedSize()
                        Button("刷新") { ctl.discover(project) }.disabled(project.isEmpty)
                        if ctl.discovery?.loggedIn == false { Button("登录…") { action("login") } }
                        Button("新建会话…") { ctl.showCreate = true }.disabled(!configured)
                    }
                }
            } header: {
                Text("会话")
            } footer: {
                Text("从 Codex 会话菜单复制 ID 或链接。Claude Code 会话可以从本项目的会话里选，也可以粘贴桌面 Code 的 local_ 标识。")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section {
                Picker("接力方式", selection: $relayMode) {
                    Text("原会话接力").tag("live")
                    Text("App 驱动").tag("app")
                }
                .pickerStyle(.segmented)
            } footer: {
                Text(relayMode == "live"
                     ? L("推荐。审查会话在 Claude 桌面窗口里调用 send_to_codex 派单，并在后台收取回执，全程都在同一个对话里。")
                     : L("由本 App 通过命令行续接 Claude 会话完成审查。审查轮次不会显示在桌面窗口里，可在「对话」页查看。"))
                    .font(.caption).foregroundStyle(.secondary)
            }

            if relayMode == "live" {
                Section {
                    Stepper("单次接力上限：\(limit) 轮", value: $limit, in: 1...100)
                    LabeledContent("状态") {
                        if ctl.liveEnabled {
                            Label(ctl.livePaused ? L("派单已暂停") : L("已启用，等待审查会话派单"),
                                  systemImage: ctl.livePaused ? "pause.circle.fill" : "checkmark.circle.fill")
                                .foregroundStyle(ctl.livePaused ? .orange : .green)
                        } else {
                            Text("未启用").foregroundStyle(.secondary)
                        }
                    }
                } header: {
                    Text("原会话接力")
                } footer: {
                    Text("启用时会在本机为这个项目注册 codex_relay 工具，不需要 .mcp.json。注册后在审查会话里开一轮新对话，工具就会出现。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Section {
                    Picker("指挥者", selection: $manager) {
                        Text(verbatim: "Claude").tag("claude")
                        Text(verbatim: "Codex").tag("codex")
                    }
                    .pickerStyle(.segmented)
                    LabeledContent("执行者", value: manager == "claude" ? L("Codex · MCP 派单") : "Claude Code")
                    Stepper("单次执行上限：\(limit) 轮", value: $limit, in: 1...100)
                    Picker("本次起点", selection: $mode) {
                        Text("最新执行回执").tag("latest")
                        Text("从目标开始").tag("goal")
                        Text("继续上次").tag("resume")
                    }
                    .pickerStyle(.segmented)
                    if mode != "resume" {
                        TextField(mode == "goal" ? L("目标") : L("补充说明"), text: $goal,
                                  prompt: Text(mode == "goal" ? L("交给指挥者的目标") : L("可选")), axis: .vertical)
                            .lineLimit(2...6)
                    }
                } header: {
                    Text("App 驱动")
                }
            }
        }
        .formStyle(.grouped)
        .disabled(ctl.busy)
    }

    // MARK: Chat

    var liveTitle: String {
        let who = ctl.liveRole == "claude" ? "Claude" : "Codex"
        return String(format: ctl.stage == "review" ? L("%@ 正在审查…") : L("%@ 正在执行…"), who)
    }

    var chatPage: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(ctl.chat.enumerated()), id: \.element.id) { index, m in
                        if index == 0 || ctl.chat[index - 1].round != m.round {
                            RoundDivider(round: m.round)
                        }
                        MessageCard(role: m.role, title: m.title, text: m.text, path: m.path,
                                    expanded: ctl.expanded.contains(m.id)) {
                            if ctl.expanded.contains(m.id) { ctl.expanded.remove(m.id) } else { ctl.expanded.insert(m.id) }
                        }
                    }
                    if ctl.busy && !ctl.liveText.isEmpty {
                        MessageCard(role: "live-" + ctl.liveRole, title: liveTitle, text: ctl.liveText, path: "", live: true)
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding(.horizontal, 24).padding(.vertical, 18)
                .frame(maxWidth: 880)
                .frame(maxWidth: .infinity)
            }
            .overlay {
                if ctl.chat.isEmpty && ctl.liveText.isEmpty {
                    ContentUnavailableView {
                        Label("还没有对话", systemImage: "bubble.left.and.bubble.right")
                    } description: {
                        Text("接力开始后，每一轮的审查、发给 Codex 的指令和回执会按顺序显示在这里。")
                    }
                }
            }
            // Demo screenshots start at the top: a window snapshot cannot show the toolbar's blur.
            .onChange(of: ctl.chat.count) { _, _ in if !demoMode { proxy.scrollTo("bottom", anchor: .bottom) } }
            .onChange(of: ctl.liveText) { _, _ in proxy.scrollTo("bottom", anchor: .bottom) }
            .onAppear { if !demoMode { proxy.scrollTo("bottom", anchor: .bottom) } }
        }
    }

    // MARK: Log

    var logPage: some View {
        List(ctl.entries.reversed()) { e in
            HStack(alignment: .firstTextBaseline, spacing: 14) {
                Text(e.time, format: .dateTime.hour().minute().second())
                    .font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
                    .frame(width: 70, alignment: .leading)
                Text(e.message).textSelection(.enabled)
            }
            .padding(.vertical, 3)
        }
        .listStyle(.inset)
        .overlay {
            if ctl.entries.isEmpty {
                ContentUnavailableView("暂无记录", systemImage: "list.bullet.rectangle",
                                       description: Text("本次打开 App 以来的连接、交接和错误会记录在这里。"))
            }
        }
    }

    // MARK: Bottom bar

    var noteBanner: some View {
        let tone = ctl.tone == .active ? Tone.neutral : ctl.tone
        return HStack(alignment: .top, spacing: 10) {
            Image(systemName: tone.symbol).foregroundStyle(tone == .neutral ? accent : tone.color)
            Text(ctl.note).font(.callout).textSelection(.enabled)
                .lineLimit(4).frame(maxWidth: .infinity, alignment: .leading)
            Button { ctl.note = "" } label: { Image(systemName: "xmark") }
                .buttonStyle(.borderless).foregroundStyle(.secondary).help("关闭")
        }
        .padding(12)
        .background((tone == .neutral ? accent : tone.color).opacity(0.10),
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .padding(.horizontal, 16).padding(.bottom, 10)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    var cycleText: String {
        if ctl.busy && ctl.round > 0 { return String(format: L("第 %lld 轮"), ctl.round) }
        return relayMode == "live" ? L("审查会话派单 → Codex 执行 → 回执唤醒审查会话") : L("审查 → 执行 → 回执")
    }

    var actionBar: some View {
        HStack(spacing: 10) {
            Label(cycleText, systemImage: "arrow.triangle.2.circlepath")
                .font(.callout).foregroundStyle(.secondary).lineLimit(1)
            Spacer()
            if ctl.busy {
                Button(ctl.pausedRequested ? L("正在暂停") : (ctl.stage == "waiting" ? L("暂停等待") : L("本轮后暂停")),
                       systemImage: "pause.fill") { ctl.pause() }
                    .disabled(ctl.pausedRequested || ctl.pauseFile.isEmpty)
            } else if relayMode == "live" {
                if ctl.liveEnabled {
                    Button(ctl.livePaused ? L("恢复派单") : L("暂停派单"),
                           systemImage: ctl.livePaused ? "play.fill" : "pause.fill") { ctl.setLivePause(project, !ctl.livePaused) }
                    if ctl.tab != "chat" {
                        Button("查看对话", systemImage: "bubble.left.and.bubble.right") { ctl.tab = "chat"; ctl.refreshLive(project) }
                    }
                }
                Button(ctl.liveEnabled ? L("更新绑定") : L("启用原会话接力"), systemImage: "link") { action("bind") }
                    .buttonStyle(.borderedProminent)
                    .disabled(codex.isEmpty || !configured)
            } else {
                if ctl.desktopBlocked {
                    Button("仍然继续") { action("start", force: true) }
                        .help("忽略桌面窗口刚才的活动，从保存的交接点继续")
                }
                Button("检查连接") { action("check") }.disabled(codex.isEmpty || claude.isEmpty || !configured)
                Button("开始接力", systemImage: "play.fill") { action("start") }
                    .buttonStyle(.borderedProminent).disabled(!ready)
            }
        }
        .controlSize(.large)
        .padding(.horizontal, 20).padding(.vertical, 12)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }

    // MARK: Body

    var title: String { L(["setup": "设置", "chat": "对话"][ctl.tab] ?? "运行记录") }

    var detail: some View {
        VStack(spacing: 0) {
            Group {
                switch ctl.tab {
                case "chat": chatPage
                case "log": logPage
                default: setupPage
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            if !ctl.note.isEmpty { noteBanner }
            actionBar
        }
        .animation(.snappy, value: ctl.note.isEmpty)
        .navigationTitle(title)
        .navigationSubtitle(project.isEmpty ? L("未选择项目") : root.lastPathComponent)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if ctl.tab == "chat" {
                    Button("最新摘要", systemImage: "doc.text") { NSWorkspace.shared.open(URL(fileURLWithPath: ctl.digestPath)) }
                        .help("打开 LATEST.md")
                        .disabled(ctl.digestPath.isEmpty || !FileManager.default.fileExists(atPath: ctl.digestPath))
                }
                if ctl.tab != "setup" {
                    Button("运行目录", systemImage: "folder") { NSWorkspace.shared.open(URL(fileURLWithPath: ctl.folder)) }
                        .help("在 Finder 中打开本次运行的完整记录")
                        .disabled(ctl.folder.isEmpty)
                }
            }
            ToolbarItem(placement: .status) {
                StatusPill(text: L(ctl.status), tone: ctl.tone)
            }
        }
    }

    var body: some View {
        NavigationSplitView {
            sidebar
        } detail: {
            detail
        }
        .tint(accent)
        .frame(minWidth: 900, minHeight: 640)
        .onAppear {
            if demoMode { Demo.seed(self) }
            ctl.discover(project); ctl.refreshLive(project)
        }
        .onReceive(Timer.publish(every: 4, on: .main, in: .common).autoconnect()) { _ in
            if ctl.tab == "chat" && !ctl.busy { ctl.refreshLive(project) }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in ctl.discover(project) }
        .onChange(of: project) { _, _ in ctl.checkedPair = ""; ctl.discover(project); ctl.refreshLive(project) }
        .onChange(of: [codex, claude, project, document]) { _, _ in
            if !ctl.busy && !demoMode && ctl.checkedPair != [project, codex, claude].joined(separator: "|") {
                ctl.checkedPair = ""; ctl.status = ready ? "等待检查" : "等待选择会话"; ctl.note = ""
            }
        }
        .onReceive(ctl.$discovery.compactMap { $0 }) { d in selectSession(d) }
        .onChange(of: ctl.createdID) { _, value in if !value.isEmpty { claude = value } }
        .alert("新建本地 Claude Code 会话？", isPresented: $ctl.showCreate) {
            Button("取消", role: .cancel) {}
            Button("打开终端") { action("create") }
        } message: {
            Text("将在项目目录打开 Claude Code 并自动填入新 ID。首次使用时请完成登录。它会先阅读任务文档，你可以补充旧 Chat 中尚未记录的决定。")
        }
    }
}

@main struct SessionRelayApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        Window("Session Relay", id: "main") { Workspace() }
            .defaultSize(width: 1080, height: 760)
            .windowToolbarStyle(.unified)
    }
}
