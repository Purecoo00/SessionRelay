import SwiftUI
import AppKit

/// Claude's warm terracotta, shared with the app icon. Codex uses the label color (black / white).
let accent = Color(red: 0.85, green: 0.47, blue: 0.34)
let demoMode = ProcessInfo.processInfo.environment["SESSION_RELAY_DEMO"] != nil

/// Chinese strings are the localization keys; en.lproj/Localizable.strings holds the English text.
func L(_ key: String) -> String { NSLocalizedString(key, comment: "") }
let english = Bundle.main.preferredLocalizations.first?.hasPrefix("en") == true

/// A python3 process for relay.py that speaks the app's language.
func relayProcess(_ worker: URL, unbuffered: Bool = false) -> Process {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    p.arguments = unbuffered ? ["-B", "-u", worker.path] : ["-B", worker.path]
    var env = ProcessInfo.processInfo.environment
    env["SESSION_RELAY_LANG"] = english ? "en" : "zh"
    p.environment = env
    return p
}

struct Entry: Identifiable {
    let id = UUID()
    var time = Date()
    let message: String
}

struct ChatMessage: Identifiable {
    let id: String
    let round: Int
    let role: String
    let title: String
    let text: String
    let path: String
    init?(_ e: [String: Any]) {
        guard let id = e["id"] as? String, let role = e["role"] as? String else { return nil }
        self.id = id; self.role = role
        round = e["round"] as? Int ?? 0
        title = e["title"] as? String ?? ""
        text = e["text"] as? String ?? ""
        path = e["path"] as? String ?? ""
    }
}

struct CodeSession: Identifiable, Decodable, Equatable {
    let id: String
    let title: String
    let alias: String
    let modified: Double
    var label: String {
        let date = Date(timeIntervalSince1970: modified).formatted(date: .abbreviated, time: .shortened)
        return "\(title) · \(date)"
    }
}

struct CodexChat: Identifiable, Decodable, Equatable {
    let id: String
    let title: String
    let modified: Double
    var label: String {
        let date = Date(timeIntervalSince1970: modified).formatted(date: .abbreviated, time: .shortened)
        return "\(title) · \(date)"
    }
}

struct CodeDiscovery: Decodable, Equatable {
    let loggedIn: Bool
    let sessions: [CodeSession]
    let codex: [CodexChat]
    let codexError: String
}

/// One Claude Code reviewer and one Codex chat, with their project and relay settings.
struct Pair: Codable, Identifiable, Equatable {
    /// "" is the first pair, whose in-session binding lives in .session-relay/live/ itself.
    var id: String
    var name = ""
    var project = ""
    var document = ""
    var codex = ""
    var claude = ""
    var manager = "claude"
    var mode = "latest"
    var goal = ""
    var relayMode = "live"
    var limit = 3

    static func fresh(like other: Pair?) -> Pair {
        var p = Pair(id: "p-" + UUID().uuidString.prefix(8).lowercased())
        if let other { p.project = other.project; p.document = other.document; p.relayMode = other.relayMode; p.limit = other.limit }
        return p
    }
}

/// The list of pairs, which one is shown, and what each project's sessions look like.
final class Store: ObservableObject {
    @Published var pairs: [Pair] { didSet { save() } }
    @Published var selected: String { didSet { if !demoMode { UserDefaults.standard.set(selected, forKey: "selectedPair") } } }
    @Published var tab = "setup"
    @Published var showCreate = false
    @Published var deleting: Pair?
    @Published var discovery: [String: CodeDiscovery] = [:]
    @Published var discoveryError: [String: String] = [:]
    private var probing: Set<String> = []
    private var runs: [String: Run] = [:]
    static let shared = Store()

    init() {
        let d = UserDefaults.standard
        var list: [Pair]
        if !demoMode, let data = d.data(forKey: "pairs"), let saved = try? JSONDecoder().decode([Pair].self, from: data), !saved.isEmpty {
            list = saved
        } else {
            // Before pairs existed the app kept one set of settings; it becomes the first pair.
            var p = Pair(id: "")
            if !demoMode {
                p.project = d.string(forKey: "project") ?? ""; p.document = d.string(forKey: "document") ?? ""
                p.codex = d.string(forKey: "codex") ?? ""; p.claude = d.string(forKey: "claude") ?? ""
                p.manager = d.string(forKey: "manager") ?? "claude"; p.mode = d.string(forKey: "mode") ?? "latest"
                p.goal = d.string(forKey: "goal") ?? ""; p.relayMode = d.string(forKey: "relayMode") ?? "live"
                p.limit = d.object(forKey: "limit") as? Int ?? 3
            }
            list = [p]
        }
        let last = demoMode ? nil : d.string(forKey: "selectedPair")
        pairs = list
        selected = last.flatMap { id in list.contains { $0.id == id } ? id : nil } ?? list[0].id
    }

    private func save() {
        guard !demoMode, let data = try? JSONEncoder().encode(pairs) else { return }
        UserDefaults.standard.set(data, forKey: "pairs")
    }

    var current: Pair { pairs.first { $0.id == selected } ?? pairs[0] }

    func binding(_ id: String) -> Binding<Pair> {
        Binding(get: { self.pairs.first { $0.id == id } ?? Pair(id: id) },
                set: { value in if let i = self.pairs.firstIndex(where: { $0.id == id }) { self.pairs[i] = value } })
    }

    func run(_ id: String) -> Run {
        if let r = runs[id] { return r }
        let r = Run(id: id)
        runs[id] = r
        return r
    }

    var anyBusy: Bool { runs.values.contains { $0.busy } }
    func terminateAll() { runs.values.forEach { $0.terminate() } }

    /// The name shown in the sidebar: yours, else the Codex chat's title, else the folder.
    func title(_ p: Pair) -> String {
        if !p.name.isEmpty { return p.name }
        if let chat = discovery[p.project]?.codex.first(where: { $0.id == p.codex }) { return chat.title }
        if !p.project.isEmpty { return URL(fileURLWithPath: p.project).lastPathComponent }
        return L("新配对")
    }

    func add() {
        let p = Pair.fresh(like: current)
        pairs.append(p)
        selected = p.id; tab = "setup"
    }

    func duplicate(_ p: Pair) {
        var copy = Pair.fresh(like: p)
        copy.name = p.name.isEmpty ? "" : p.name + " 2"
        copy.manager = p.manager; copy.mode = p.mode; copy.goal = p.goal
        pairs.append(copy)
        selected = copy.id; tab = "setup"
    }

    /// Forgets the pair and turns off its in-session binding. Run records stay in the project.
    func delete(_ p: Pair) {
        guard pairs.count > 1, !run(p.id).busy else { return }
        if !p.project.isEmpty {
            try? FileManager.default.removeItem(at: Run.liveBase(p).appendingPathComponent("binding.json"))
        }
        if selected == p.id { selected = pairs.first { $0.id != p.id }!.id }
        pairs.removeAll { $0.id == p.id }
        runs[p.id]?.terminate(); runs[p.id] = nil
    }

    func discover(_ project: String) {
        guard !demoMode, !project.isEmpty, !probing.contains(project) else { return }
        guard let worker = Bundle.main.url(forResource: "relay", withExtension: "py") else { return }
        probing.insert(project)
        DispatchQueue.global().async {
            let p = relayProcess(worker), input = Pipe(), output = Pipe()
            p.standardInput = input; p.standardOutput = output; p.standardError = FileHandle.nullDevice
            do {
                let data = try JSONSerialization.data(withJSONObject: ["command":"discover","project":project])
                try p.run()
                input.fileHandleForWriting.write(data + Data([10]))
                try input.fileHandleForWriting.close()
                let reply = output.fileHandleForReading.readDataToEndOfFile()
                p.waitUntilExit()
                if p.terminationStatus != 0 {
                    let err = try? JSONSerialization.jsonObject(with: reply) as? [String: Any]
                    throw NSError(domain:"Discovery",code:1,userInfo:[NSLocalizedDescriptionKey: err?["message"] as? String ?? L("会话检查失败")])
                }
                let result = try JSONDecoder().decode(CodeDiscovery.self, from: reply)
                DispatchQueue.main.async {
                    self.probing.remove(project); self.discoveryError[project] = nil
                    if self.discovery[project] != result { self.discovery[project] = result }
                }
            } catch {
                DispatchQueue.main.async {
                    self.probing.remove(project); self.discovery[project] = nil
                    self.discoveryError[project] = error.localizedDescription
                }
            }
        }
    }
}

/// What one pair is doing right now: its relay process, status, conversation and log.
final class Run: ObservableObject {
    let id: String
    @Published var busy = false
    @Published var status = "等待选择会话"
    var checkedPair = ""
    @Published var entries: [Entry] = []
    @Published var note = ""
    @Published var folder: String
    @Published var pauseFile = ""
    @Published var pausedRequested = false
    @Published var stage = ""
    @Published var round = 0
    @Published var createdID = ""
    @Published var chat: [ChatMessage] = []
    @Published var liveRole = ""
    @Published var liveText = ""
    @Published var desktopBlocked = false
    @Published var livePaused = false
    @Published var liveEnabled = false
    @Published var expanded: Set<String> = []  // Chat cards showing their full text.
    private var historyVersion = 0
    private var proc: Process?

    init(id: String) {
        self.id = id
        folder = UserDefaults.standard.string(forKey: Run.folderKey(id)) ?? ""
    }

    /// The first pair keeps the key used before pairs existed.
    static func folderKey(_ id: String) -> String { id.isEmpty ? "lastRunFolder" : "lastRunFolder." + id }

    func remember(_ folder: String) {
        if !demoMode { UserDefaults.standard.set(folder, forKey: Run.folderKey(id)) }
    }

    var digestPath: String {
        guard !folder.isEmpty else { return "" }
        return URL(fileURLWithPath: folder).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("LATEST.md").path
    }

    /// Mirrors live.base(): the first pair uses live/ itself, the others live/<id>/.
    static func liveBase(_ p: Pair) -> URL {
        let live = URL(fileURLWithPath: p.project).appendingPathComponent(".session-relay/live")
        return p.id.isEmpty ? live : live.appendingPathComponent(p.id)
    }

    /// Reads whether the pair is bound or paused; cheap enough for every pair on each tick.
    func refreshFlags(_ p: Pair) {
        guard !demoMode, !p.project.isEmpty else { return }
        let base = Run.liveBase(p), fm = FileManager.default
        let enabled = fm.fileExists(atPath: base.appendingPathComponent("binding.json").path)
        let paused = fm.fileExists(atPath: base.appendingPathComponent("pause").path)
        if enabled != liveEnabled { liveEnabled = enabled }
        if paused != livePaused { livePaused = paused }
    }

    /// Follows the live run the reviewer session is using, then reloads the chat from disk.
    func refreshLive(_ p: Pair) {
        guard !demoMode, !p.project.isEmpty else { return }
        refreshFlags(p)
        let base = Run.liveBase(p)
        if folder.hasPrefix(base.path + "/"),
           let name = try? String(contentsOf: base.appendingPathComponent("current"), encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty {
            let next = base.appendingPathComponent(name).path
            if next != folder {
                folder = next; chat = []
                remember(next)
            }
        }
        loadHistory()
    }

    func setLivePause(_ p: Pair, _ paused: Bool) {
        let file = Run.liveBase(p).appendingPathComponent("pause")
        do {
            if paused { try Data().write(to: file, options: .atomic) }
            else if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
            livePaused = paused
            note = paused ? L("已暂停派单。Codex 正在执行的回合会照常完成，Claude 收到回执后不会再派单。") : L("已恢复派单。")
        } catch { note = error.localizedDescription }
    }

    func loadHistory() {
        guard !folder.isEmpty, !busy,
              let worker = Bundle.main.url(forResource: "relay", withExtension: "py") else { return }
        historyVersion += 1
        let version = historyVersion, target = folder
        DispatchQueue.global().async {
            let p = relayProcess(worker), input = Pipe(), output = Pipe()
            p.standardInput = input; p.standardOutput = output; p.standardError = FileHandle.nullDevice
            guard let data = try? JSONSerialization.data(withJSONObject: ["command":"history","folder":target]),
                  (try? p.run()) != nil else { return }
            input.fileHandleForWriting.write(data + Data([10]))
            try? input.fileHandleForWriting.close()
            let reply = output.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit()
            guard let e = try? JSONSerialization.jsonObject(with: reply) as? [String: Any],
                  let rows = e["messages"] as? [[String: Any]] else { return }
            let messages = rows.compactMap(ChatMessage.init)
            DispatchQueue.main.async {
                guard version == self.historyVersion, target == self.folder, !self.busy else { return }
                self.chat = messages
            }
        }
    }

    func receive(_ line: Data) {
        guard let e = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
              let k = e["kind"] as? String else { return }
        let m = e["message"] as? String ?? ""
        switch k {
        case "turn":
            guard let message = ChatMessage(e) else { return }
            if let i = chat.firstIndex(where: { $0.id == message.id }) { chat[i] = message } else { chat.append(message) }
            if ["review", "receipt"].contains(message.role) { liveText = ""; liveRole = "" }
            return
        case "stream":
            let piece = e["text"] as? String ?? ""
            let role = e["role"] as? String ?? ""
            if role != liveRole { liveText = "" ; liveRole = role }
            liveText = liveText.isEmpty ? piece : liveText + "\n\n" + piece
            if liveText.count > 20000 { liveText = "…\n" + String(liveText.suffix(20000)) }
            return
        default: break
        }
        if let n = e["round"] as? Int { round = n }
        if let s = e["stage"] as? String { stage = s }
        switch k {
        case "control": pauseFile = m; return
        case "folder":
            if folder != m { chat = [] }
            folder = m
            remember(m)
            return
        case "login": status = "等待登录"; note = m
        case "created":
            createdID = m
            status = "等待 Code 会话"
            note = L("已打开终端。完成登录，等 Claude 读完文档后，在终端输入 /exit，再回到这里开始。")
        case "error": status = "需要处理"; note = m
        case "checked": status = "已连接"; note = m
        case "bound": status = "原会话接力已启用"; note = m; liveEnabled = true
        case "done": status = "已完成"; note = m
        case "paused": status = "已暂停"; note = L("下次选择「继续上次」即可接着运行。")
        case "blocked": status = "等待处理"; note = m
        case "desktop": status = "桌面窗口正在使用"; note = m; desktopBlocked = true
        default:
            let phases = ["waiting":"等待 Codex 回执", "review":"指挥者审查中", "execute":"执行者工作中"]
            status = pausedRequested ? "正在暂停" : phases[stage] ?? "运行中"
            note = m
        }
        entries.append(Entry(message: k == "created" ? note : m))
    }

    func launch(_ config: [String: Any]) {
        guard !busy else { return }
        if demoMode { note = L("演示模式不会启动接力。"); return }
        guard let worker = Bundle.main.url(forResource: "relay", withExtension: "py") else {
            note = L("App 缺少运行组件 relay.py"); return
        }
        let p = relayProcess(worker, unbuffered: true), input = Pipe(), output = Pipe(), errors = Pipe()
        p.standardInput = input
        p.standardOutput = output
        p.standardError = errors
        let command = config["command"] as? String ?? "start"
        status = command == "create" ? "准备 Code 会话" : "正在连接"
        pausedRequested = false; pauseFile = ""; note = ""; busy = true; stage = ""; round = 0
        desktopBlocked = false; liveText = ""; liveRole = ""
        entries.append(Entry(message: L(status)))
        do {
            let data = try JSONSerialization.data(withJSONObject: config)
            try p.run()
            proc = p
            input.fileHandleForWriting.write(data + Data([10]))
            try? input.fileHandleForWriting.close()
        } catch {
            busy = false; status = "启动失败"; note = error.localizedDescription
            return
        }
        DispatchQueue.global().async {
            let data = errors.fileHandleForReading.readDataToEndOfFile()
            if !data.isEmpty {
                let message = String(decoding: data.suffix(1800), as: UTF8.self)
                DispatchQueue.main.async { self.entries.append(Entry(message: message)) }
            }
        }
        DispatchQueue.global().async {
            var buffer = Data()
            while true {
                let part = output.fileHandleForReading.availableData
                if part.isEmpty { break }
                buffer.append(part)
                while let i = buffer.firstIndex(of: 10) {
                    let line = Data(buffer[..<i])
                    buffer.removeSubrange(...i)
                    DispatchQueue.main.async { self.receive(line) }
                }
            }
            p.waitUntilExit()
            DispatchQueue.main.async {
                if p.terminationStatus != 0 && self.status != "需要处理" {
                    self.status = "已中断"
                    self.note = L("请查看记录，并核对最后一次交接。")
                }
                self.busy = false; self.proc = nil; self.pauseFile = ""
                self.liveText = ""; self.liveRole = ""
            }
        }
    }

    func pause() {
        guard !pauseFile.isEmpty else { return }
        do {
            try Data().write(to: URL(fileURLWithPath: pauseFile), options: .atomic)
            pausedRequested = true
            status = stage == "waiting" ? "正在暂停" : "等待本轮结束"
        } catch { note = error.localizedDescription }
    }

    func terminate() {
        if let p = proc, p.isRunning { p.terminate() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if Store.shared.anyBusy {
            let alert = NSAlert()
            alert.messageText = L("交接正在进行")
            alert.informativeText = L("现在退出会中断接力。也可以保留窗口，点「本轮后暂停」保存交接点。")
            alert.addButton(withTitle: L("保留窗口"))
            alert.addButton(withTitle: L("退出"))
            if alert.runModal() == .alertFirstButtonReturn { return .terminateCancel }
            Store.shared.terminateAll()
        }
        return .terminateNow
    }
}

