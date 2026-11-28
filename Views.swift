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

extension Run {
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

// MARK: - Sidebar

struct PairRow: View {
    @ObservedObject var store: Store
    @ObservedObject var run: Run
    let pair: Pair

    var dot: Color {
        if run.busy { return .green }
        if pair.relayMode == "live" && run.liveEnabled { return run.livePaused ? .orange : .green }
        return run.tone == .neutral ? Color.secondary.opacity(0.45) : run.tone.color
    }

    var subtitle: String {
        let folder = pair.project.isEmpty ? L("未选择项目") : URL(fileURLWithPath: pair.project).lastPathComponent
        return folder + " · " + (pair.relayMode == "live" ? L("原会话接力") : L("App 驱动"))
    }

    var body: some View {
        let selected = store.selected == pair.id
        Button { store.selected = pair.id } label: {
            HStack(spacing: 10) {
                Image(systemName: pair.relayMode == "live" ? "link" : "arrow.triangle.2.circlepath")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(selected ? .white : accent)
                    .frame(width: 26, height: 26)
                    .background(selected ? accent : accent.opacity(0.14), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
                VStack(alignment: .leading, spacing: 1) {
                    Text(store.title(pair)).font(.system(size: 13, weight: selected ? .semibold : .regular)).lineLimit(1)
                    Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 4)
                Circle().fill(dot).frame(width: 7, height: 7)
            }
            .padding(.horizontal, 8).frame(height: 44)
            .background(selected ? accent.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button("复制配对") { store.duplicate(pair) }
            Divider()
            Button("删除配对…", role: .destructive) { store.deleting = pair }
                .disabled(store.pairs.count < 2 || run.busy)
        }
    }
}

struct PageRows: View {
    @ObservedObject var store: Store
    @ObservedObject var run: Run

    func row(_ key: String, _ label: LocalizedStringKey, _ symbol: String, badge: Int = 0) -> some View {
        let selected = store.tab == key
        return Button { store.tab = key } label: {
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

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            row("setup", "设置", "slider.horizontal.3")
            row("chat", "对话", "bubble.left.and.bubble.right", badge: run.chat.count)
            row("log", "运行记录", "list.bullet.rectangle")
        }
    }
}

struct Sidebar: View {
    @ObservedObject var store: Store

    func heading(_ text: LocalizedStringKey) -> some View {
        Text(text).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
                HStack {
                    heading("配对")
                    Spacer()
                    Button { store.add() } label: { Image(systemName: "plus") }
                        .buttonStyle(.borderless).help("新建配对")
                }
                .padding(.horizontal, 10).padding(.bottom, 4)
                ForEach(store.pairs) { p in
                    PairRow(store: store, run: store.run(p.id), pair: p)
                }
                heading("当前配对").padding(.horizontal, 10).padding(.top, 16).padding(.bottom, 4)
                PageRows(store: store, run: store.run(store.selected))
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
        .navigationSplitViewColumnWidth(min: 230, ideal: 270, max: 340)
    }
}

// MARK: - Pair

struct PairPage: View {
    @ObservedObject var store: Store
    @ObservedObject var run: Run
    @Binding var p: Pair

    var root: URL { URL(fileURLWithPath: p.project) }
    var discovery: CodeDiscovery? { store.discovery[p.project] }
    var config: [String: Any] {
        ["pair": p.id, "project": p.project, "document": p.document, "codex": p.codex, "claude": p.claude,
         "manager": p.manager, "mode": p.mode, "limit": p.limit, "goal": p.goal]
    }
    var configured: Bool { !p.project.isEmpty && !p.document.isEmpty }
    var ready: Bool { configured && !p.codex.isEmpty && !p.claude.isEmpty && (p.mode != "goal" || !p.goal.isEmpty) }
    /// Other pairs in the same project; with any, each in-session pair needs its own reviewer.
    var siblings: Int { store.pairs.filter { $0.id != p.id && $0.project == p.project && !p.project.isEmpty }.count }

    /// The task document as shown: relative inside the project, absolute elsewhere.
    var documentLabel: String {
        guard !p.document.isEmpty else { return L("未选择") }
        let prefix = root.path + "/"
        return !p.project.isEmpty && p.document.hasPrefix(prefix) ? String(p.document.dropFirst(prefix.count)) : p.document
    }

    /// A pasted link or ID, reduced to the ID the picker lists.
    var codexID: String { p.codex.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "/").last.map(String.init) ?? "" }

    func action(_ name: String, force: Bool = false) {
        var args = config; args["command"] = name
        if force { args["mode"] = "resume"; args["force"] = true }
        if name == "start" { store.tab = "chat" }
        run.launch(args)
    }

    var accountText: String {
        if let error = store.discoveryError[p.project] { return error }
        guard let d = discovery else { return p.project.isEmpty ? L("先选择项目目录") : L("正在读取登录状态…") }
        return d.loggedIn ? L("已登录") : L("尚未登录")
    }

    func selectSession(_ discovery: CodeDiscovery) {
        let value = p.claude.trimmingCharacters(in: .whitespacesAndNewlines)
        let last = value.split(separator: "/").last.map(String.init) ?? value
        var sid = value
        if value.isEmpty, discovery.sessions.count == 1, siblings == 0 {
            sid = discovery.sessions[0].id
        } else if !last.isEmpty, let match = discovery.sessions.first(where: {
            !$0.alias.isEmpty && ($0.alias == last || $0.alias == "local_" + last)
        }) {
            sid = match.id
        }
        if p.claude != sid { p.claude = sid }
        guard !run.busy, configured, p.relayMode == "app" else { return }
        if discovery.loggedIn && !p.codex.isEmpty && !sid.isEmpty {
            let key = [p.project, p.codex, sid].joined(separator: "|")
            if run.checkedPair != key {
                run.checkedPair = key
                var args = config; args["command"] = "check"; args["claude"] = sid
                run.launch(args)
            }
        } else if ["等待选择会话", "等待登录", "已连接", "等待 Code 会话", "等待检查"].contains(run.status) {
            run.checkedPair = ""
            run.status = discovery.loggedIn ? "等待选择会话" : "等待登录"
        }
    }

    func choose() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.prompt = L("选择项目")
        panel.message = L("选择项目根目录")
        if !p.project.isEmpty { panel.directoryURL = root }
        if panel.runModal() == .OK, let url = panel.url, p.project != url.path {
            if discovery?.sessions.contains(where: { $0.id == p.claude }) == true { p.claude = "" }
            if discovery?.codex.contains(where: { $0.id == codexID }) == true { p.codex = "" }
            p.project = url.path
        }
    }

    func chooseDocument() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true; panel.canChooseDirectories = false
        panel.allowedContentTypes = [UTType(filenameExtension: "md") ?? .plainText, .plainText]
        panel.prompt = L("选择任务文档")
        panel.message = L("选择指挥者每轮要阅读和更新的任务文档")
        panel.directoryURL = p.document.isEmpty ? (p.project.isEmpty ? nil : root)
                                                : URL(fileURLWithPath: p.document).deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url { p.document = url.path }
    }

    // MARK: Setup

    var setupPage: some View {
        Form {
            Section {
                LabeledContent("名称") {
                    TextField("名称", text: $p.name, prompt: Text(store.title(Pair(id: p.id, project: p.project, codex: p.codex))))
                        .labelsHidden()
                }
                LabeledContent("项目目录") {
                    HStack {
                        Text(p.project.isEmpty ? L("未选择") : p.project)
                            .lineLimit(1).truncationMode(.middle)
                            .foregroundStyle(p.project.isEmpty ? .secondary : .primary)
                            .textSelection(.enabled)
                        Button(p.project.isEmpty ? L("选择…") : L("更改…"), action: choose)
                    }
                }
                LabeledContent("任务文档") {
                    HStack {
                        Text(documentLabel)
                            .font(.system(.callout, design: .monospaced))
                            .lineLimit(1).truncationMode(.middle)
                            .foregroundStyle(p.document.isEmpty ? .secondary : .primary)
                            .textSelection(.enabled)
                            .help(p.document)
                        Button(p.document.isEmpty ? L("选择…") : L("更改…"), action: chooseDocument)
                    }
                }
            } header: {
                Text("配对信息")
            } footer: {
                Text("任务文档是指挥者每轮阅读和更新的 Markdown 文件，可以放在项目里的任何位置。名称留空时使用 Codex 会话的标题。")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section {
                LabeledContent("Codex 会话") {
                    HStack {
                        TextField("Codex 会话", text: $p.codex, prompt: Text("粘贴会话 ID 或链接"))
                            .labelsHidden().font(.system(.body, design: .monospaced))
                        if let list = discovery?.codex, !list.isEmpty {
                            Menu {
                                ForEach(list) { c in
                                    Button(c.label) { p.codex = c.id }
                                }
                            } label: {
                                Text(list.first(where: { $0.id == codexID })?.title ?? L("本项目会话"))
                            }
                            .frame(maxWidth: 190)
                        }
                    }
                }
                LabeledContent("Claude Code 会话") {
                    HStack {
                        TextField("Claude Code 会话", text: $p.claude, prompt: Text("UUID 或 local_ 标识"))
                            .labelsHidden().font(.system(.body, design: .monospaced))
                        if let list = discovery?.sessions, !list.isEmpty {
                            Menu {
                                ForEach(list) { s in
                                    Button(s.label + " · " + String(s.id.prefix(8))) {
                                        p.claude = s.id
                                        run.checkedPair = ""
                                        if let d = discovery { selectSession(d) }
                                    }
                                }
                            } label: {
                                Text(list.first(where: { $0.id == p.claude })?.title ?? L("本项目会话"))
                            }
                            .frame(maxWidth: 190)
                        }
                    }
                }
                LabeledContent(LocalizedStringKey("Claude Code")) {
                    HStack(spacing: 8) {
                        Label(accountText, systemImage: discovery?.loggedIn == true ? "checkmark.circle.fill" : "person.crop.circle")
                            .foregroundStyle(discovery?.loggedIn == true ? .green : .secondary)
                            .fixedSize()
                        Button("刷新") { store.discover(p.project) }.disabled(p.project.isEmpty)
                        if discovery?.loggedIn == false { Button("登录…") { action("login") } }
                        Button("新建会话…") { store.showCreate = true }.disabled(!configured)
                    }
                }
            } header: {
                Text("会话")
            } footer: {
                Text(discovery?.codexError.isEmpty == false
                     ? L("读不到本项目的 Codex 会话列表，可以直接粘贴 ID 或链接：") + (discovery?.codexError ?? "")
                     : L("两边都可以从本项目的会话里选，也可以粘贴 Codex 会话的 ID 或链接、Claude Code 会话的 UUID 或桌面 Code 的 local_ 标识。"))
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section {
                Picker("接力方式", selection: $p.relayMode) {
                    Text("原会话接力").tag("live")
                    Text("App 驱动").tag("app")
                }
                .pickerStyle(.segmented)
            } footer: {
                Text(p.relayMode == "live"
                     ? L("推荐。审查会话在 Claude 桌面窗口里调用 send_to_codex 派单，并在后台收取回执，全程都在同一个对话里。")
                     : L("由本 App 通过命令行续接 Claude 会话完成审查。审查轮次不会显示在桌面窗口里，可在「对话」页查看。"))
                    .font(.caption).foregroundStyle(.secondary)
            }

            if p.relayMode == "live" {
                Section {
                    limitPicker
                    if p.limit > 0 {
                        Stepper("单次接力上限：\(p.limit) 轮", value: $p.limit, in: 1...100)
                    }
                    LabeledContent("状态") {
                        if run.liveEnabled {
                            Label(run.livePaused ? L("派单已暂停") : L("已启用，等待审查会话派单"),
                                  systemImage: run.livePaused ? "pause.circle.fill" : "checkmark.circle.fill")
                                .foregroundStyle(run.livePaused ? .orange : .green)
                        } else {
                            Text("未启用").foregroundStyle(.secondary)
                        }
                    }
                } header: {
                    Text("原会话接力")
                } footer: {
                    Text(unlimitedNote + (siblings > 0
                         ? L("这个项目里还有其他配对。codex_relay 按调用它的 Claude Code 会话找到对应的配对，所以每个配对都要选定自己的 Claude Code 会话。")
                         : L("启用时会在本机为这个项目注册 codex_relay 工具，不需要 .mcp.json。注册后在审查会话里开一轮新对话，工具就会出现。")))
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Section {
                    Picker("指挥者", selection: $p.manager) {
                        Text(verbatim: "Claude").tag("claude")
                        Text(verbatim: "Codex").tag("codex")
                    }
                    .pickerStyle(.segmented)
                    LabeledContent("执行者", value: p.manager == "claude" ? L("Codex · MCP 派单") : "Claude Code")
                    limitPicker
                    if p.limit > 0 {
                        Stepper("单次执行上限：\(p.limit) 轮", value: $p.limit, in: 1...100)
                    }
                    Picker("本次起点", selection: $p.mode) {
                        Text("最新执行回执").tag("latest")
                        Text("从目标开始").tag("goal")
                        Text("继续上次").tag("resume")
                    }
                    .pickerStyle(.segmented)
                    if p.mode != "resume" {
                        TextField(p.mode == "goal" ? L("目标") : L("补充说明"), text: $p.goal,
                                  prompt: Text(p.mode == "goal" ? L("交给指挥者的目标") : L("可选")), axis: .vertical)
                            .lineLimit(2...6)
                    }
                } header: {
                    Text("App 驱动")
                } footer: {
                    if p.limit == 0 {
                        Text(unlimitedNote.trimmingCharacters(in: .whitespacesAndNewlines))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .disabled(run.busy)
    }

    /// 0 rounds means no limit: the relay stops only when the work is done, needs the user, or is paused.
    var limitPicker: some View {
        Picker("轮数上限", selection: Binding(get: { p.limit == 0 }, set: { p.limit = $0 ? 0 : 10 })) {
            Text("设上限").tag(false)
            Text("不设上限").tag(true)
        }
        .pickerStyle(.segmented)
    }

    var unlimitedNote: String {
        p.limit == 0 ? L("不设上限时，接力只会在任务完成、需要你确认或你暂停派单时停下。") + "\n" : ""
    }

    // MARK: Chat

    var liveTitle: String {
        let who = run.liveRole == "claude" ? "Claude" : "Codex"
        return String(format: run.stage == "review" ? L("%@ 正在审查…") : L("%@ 正在执行…"), who)
    }

    var chatPage: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(run.chat.enumerated()), id: \.element.id) { index, m in
                        if index == 0 || run.chat[index - 1].round != m.round {
                            RoundDivider(round: m.round)
                        }
                        MessageCard(role: m.role, title: m.title, text: m.text, path: m.path,
                                    expanded: run.expanded.contains(m.id)) {
                            if run.expanded.contains(m.id) { run.expanded.remove(m.id) } else { run.expanded.insert(m.id) }
                        }
                    }
                    if run.busy && !run.liveText.isEmpty {
                        MessageCard(role: "live-" + run.liveRole, title: liveTitle, text: run.liveText, path: "", live: true)
                    }
                    Color.clear.frame(height: 1).id("bottom")
                }
                .padding(.horizontal, 24).padding(.vertical, 18)
                .frame(maxWidth: 880)
                .frame(maxWidth: .infinity)
            }
            .overlay {
                if run.chat.isEmpty && run.liveText.isEmpty {
                    ContentUnavailableView {
                        Label("还没有对话", systemImage: "bubble.left.and.bubble.right")
                    } description: {
                        Text("接力开始后，每一轮的审查、发给 Codex 的指令和回执会按顺序显示在这里。")
                    }
                }
            }
            // Demo screenshots start at the top: a window snapshot cannot show the toolbar's blur.
            .onChange(of: run.chat.count) { _, _ in if !demoMode { proxy.scrollTo("bottom", anchor: .bottom) } }
            .onChange(of: run.liveText) { _, _ in proxy.scrollTo("bottom", anchor: .bottom) }
            .onAppear { if !demoMode { proxy.scrollTo("bottom", anchor: .bottom) } }
        }
    }

    // MARK: Log

    var logPage: some View {
        List(run.entries.reversed()) { e in
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
            if run.entries.isEmpty {
                ContentUnavailableView("暂无记录", systemImage: "list.bullet.rectangle",
                                       description: Text("本次打开 App 以来这个配对的连接、交接和错误会记录在这里。"))
            }
        }
    }

    // MARK: Bottom bar

    var noteBanner: some View {
        let tone = run.tone == .active ? Tone.neutral : run.tone
        return HStack(alignment: .top, spacing: 10) {
            Image(systemName: tone.symbol).foregroundStyle(tone == .neutral ? accent : tone.color)
            Text(run.note).font(.callout).textSelection(.enabled)
                .lineLimit(4).frame(maxWidth: .infinity, alignment: .leading)
            Button { run.note = "" } label: { Image(systemName: "xmark") }
                .buttonStyle(.borderless).foregroundStyle(.secondary).help("关闭")
        }
        .padding(12)
        .background((tone == .neutral ? accent : tone.color).opacity(0.10),
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .padding(.horizontal, 16).padding(.bottom, 10)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    var cycleText: String {
        if run.busy && run.round > 0 { return String(format: L("第 %lld 轮"), run.round) }
        return p.relayMode == "live" ? L("审查会话派单 → Codex 执行 → 回执唤醒审查会话") : L("审查 → 执行 → 回执")
    }

    var actionBar: some View {
        HStack(spacing: 10) {
            Label(cycleText, systemImage: "arrow.triangle.2.circlepath")
                .font(.callout).foregroundStyle(.secondary).lineLimit(1)
            Spacer()
            if run.busy {
                Button(run.pausedRequested ? L("正在暂停") : (run.stage == "waiting" ? L("暂停等待") : L("本轮后暂停")),
                       systemImage: "pause.fill") { run.pause() }
                    .disabled(run.pausedRequested || run.pauseFile.isEmpty)
            } else if p.relayMode == "live" {
                if run.liveEnabled {
                    Button(run.livePaused ? L("恢复派单") : L("暂停派单"),
                           systemImage: run.livePaused ? "play.fill" : "pause.fill") { run.setLivePause(p, !run.livePaused) }
                    if store.tab != "chat" {
                        Button("查看对话", systemImage: "bubble.left.and.bubble.right") { store.tab = "chat"; run.refreshLive(p) }
                    }
                }
                Button(run.liveEnabled ? L("更新绑定") : L("启用原会话接力"), systemImage: "link") { action("bind") }
                    .buttonStyle(.borderedProminent)
                    .disabled(p.codex.isEmpty || !configured)
            } else {
                if run.desktopBlocked {
                    Button("仍然继续") { action("start", force: true) }
                        .help("忽略桌面窗口刚才的活动，从保存的交接点继续")
                }
                Button("检查连接") { action("check") }.disabled(p.codex.isEmpty || p.claude.isEmpty || !configured)
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

    var title: String { L(["setup": "设置", "chat": "对话"][store.tab] ?? "运行记录") }

    var body: some View {
        VStack(spacing: 0) {
            Group {
                switch store.tab {
                case "chat": chatPage
                case "log": logPage
                default: setupPage
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            if !run.note.isEmpty { noteBanner }
            actionBar
        }
        .animation(.snappy, value: run.note.isEmpty)
        .navigationTitle(title)
        .navigationSubtitle(store.title(p))
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if store.tab == "chat" {
                    Button("最新摘要", systemImage: "doc.text") { NSWorkspace.shared.open(URL(fileURLWithPath: run.digestPath)) }
                        .help("打开 LATEST.md")
                        .disabled(run.digestPath.isEmpty || !FileManager.default.fileExists(atPath: run.digestPath))
                }
                if store.tab != "setup" {
                    Button("运行目录", systemImage: "folder") { NSWorkspace.shared.open(URL(fileURLWithPath: run.folder)) }
                        .help("在 Finder 中打开本次运行的完整记录")
                        .disabled(run.folder.isEmpty)
                }
            }
            ToolbarItem(placement: .status) {
                StatusPill(text: L(run.status), tone: run.tone)
            }
        }
        .onAppear {
            store.discover(p.project); run.refreshLive(p)
            if let d = discovery { selectSession(d) }
        }
        .onChange(of: p.project) { _, _ in run.checkedPair = ""; store.discover(p.project); run.refreshLive(p) }
        .onChange(of: [p.codex, p.claude, p.project, p.document]) { _, _ in
            if !run.busy && !demoMode && run.checkedPair != [p.project, p.codex, p.claude].joined(separator: "|") {
                run.checkedPair = ""; run.status = ready ? "等待检查" : "等待选择会话"; run.note = ""
            }
        }
        .onChange(of: discovery) { _, d in if let d { selectSession(d) } }
        .onChange(of: run.createdID) { _, value in if !value.isEmpty { p.claude = value } }
        .alert("新建本地 Claude Code 会话？", isPresented: $store.showCreate) {
            Button("取消", role: .cancel) {}
            Button("打开终端") { action("create") }
        } message: {
            Text("将在项目目录打开 Claude Code 并自动填入新 ID。首次使用时请完成登录。它会先阅读任务文档，你可以补充旧 Chat 中尚未记录的决定。")
        }
    }
}

// MARK: - Workspace

struct Workspace: View {
    @ObservedObject var store = Store.shared

    var body: some View {
        NavigationSplitView {
            Sidebar(store: store)
        } detail: {
            PairPage(store: store, run: store.run(store.selected), p: store.binding(store.selected))
                .id(store.selected)
        }
        .tint(accent)
        .frame(minWidth: 940, minHeight: 640)
        .onAppear {
            if demoMode { Demo.seed(store) }
            for p in store.pairs { store.run(p.id).refreshFlags(p) }
        }
        .onReceive(Timer.publish(every: 4, on: .main, in: .common).autoconnect()) { _ in
            for p in store.pairs {
                let run = store.run(p.id)
                if p.id == store.selected && store.tab == "chat" && !run.busy { run.refreshLive(p) } else { run.refreshFlags(p) }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            store.discover(store.current.project)
        }
        .alert(Text(String(format: L("删除配对「%@」？"), store.deleting.map(store.title) ?? "")),
               isPresented: Binding(get: { store.deleting != nil }, set: { if !$0 { store.deleting = nil } }),
               presenting: store.deleting) { pair in
            Button("删除", role: .destructive) { store.delete(pair) }
            Button("取消", role: .cancel) {}
        } message: { _ in
            Text("会关闭它的原会话接力绑定。运行记录保留在项目的 .session-relay 文件夹里。")
        }
    }
}

@main struct SessionRelayApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene {
        Window("Session Relay", id: "main") { Workspace() }
            .defaultSize(width: 1120, height: 760)
            .windowToolbarStyle(.unified)
    }
}
