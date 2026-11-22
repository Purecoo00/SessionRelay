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

struct CodeSession: Identifiable, Decodable {
    let id: String
    let title: String
    let alias: String
    let modified: Double
    var label: String {
        let date = Date(timeIntervalSince1970: modified).formatted(date: .abbreviated, time: .shortened)
        return "\(title) · \(date)"
    }
}

struct CodeDiscovery: Decodable {
    let loggedIn: Bool
    let sessions: [CodeSession]
}

final class Controller: ObservableObject {
    @Published var tab = "setup"
    @Published var showCreate = false
    @Published var busy = false
    @Published var status = "等待选择会话"
    @Published var discovery: CodeDiscovery?
    @Published var discoveryError = ""
    private var discoveryVersion = 0
    private var probingProject: String?
    var checkedPair = ""
    @Published var entries: [Entry] = []
    @Published var note = ""
    @Published var folder = UserDefaults.standard.string(forKey: "lastRunFolder") ?? ""
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
    static let shared = Controller()

    func discover(_ project: String) {
        guard !demoMode, !project.isEmpty, probingProject != project else { return }
        guard let worker = Bundle.main.url(forResource: "relay", withExtension: "py") else { return }
        probingProject = project
        discoveryVersion += 1
        let version = discoveryVersion
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
                    guard version == self.discoveryVersion else { return }
                    self.probingProject = nil; self.discoveryError = ""; self.discovery = result
                }
            } catch {
                DispatchQueue.main.async {
                    guard version == self.discoveryVersion else { return }
                    self.probingProject = nil; self.discovery = nil; self.discoveryError = error.localizedDescription
                }
            }
        }
    }

    var digestPath: String {
        guard !folder.isEmpty else { return "" }
        return URL(fileURLWithPath: folder).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("LATEST.md").path
    }

    func liveBase(_ project: String) -> URL {
        URL(fileURLWithPath: project).appendingPathComponent(".session-relay/live")
    }

    /// Follows the live run the reviewer session is using, then reloads the chat from disk.
    func refreshLive(_ project: String) {
        guard !demoMode, !project.isEmpty else { return }
        let base = liveBase(project)
        let fm = FileManager.default
        liveEnabled = fm.fileExists(atPath: base.appendingPathComponent("binding.json").path)
        livePaused = fm.fileExists(atPath: base.appendingPathComponent("pause").path)
        if folder.hasPrefix(base.path + "/"),
           let name = try? String(contentsOf: base.appendingPathComponent("current"), encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty {
            let next = base.appendingPathComponent(name).path
            if next != folder {
                folder = next; chat = []
                UserDefaults.standard.set(next, forKey: "lastRunFolder")
            }
        }
        loadHistory()
    }

    func setLivePause(_ project: String, _ paused: Bool) {
        let file = liveBase(project).appendingPathComponent("pause")
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
            UserDefaults.standard.set(m, forKey: "lastRunFolder")
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
        if Controller.shared.busy {
            let alert = NSAlert()
            alert.messageText = L("交接正在进行")
            alert.informativeText = L("现在退出会中断接力。也可以保留窗口，点「本轮后暂停」保存交接点。")
            alert.addButton(withTitle: L("保留窗口"))
            alert.addButton(withTitle: L("退出"))
            if alert.runModal() == .alertFirstButtonReturn { return .terminateCancel }
            Controller.shared.terminate()
        }
        return .terminateNow
    }
}

