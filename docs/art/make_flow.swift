// Draws the "How it works" loop for the README in the app's colors.
// Usage: swift make_flow.swift <light|dark> <en|zh> <output.png>
import AppKit

let dark = CommandLine.arguments[1] == "dark"
let zh = CommandLine.arguments[2] == "zh"
let out = CommandLine.arguments[3]
let size = NSSize(width: 1200, height: 440)
let scale: CGFloat = 2

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: r, green: g, blue: b, alpha: a)
}
func tr(_ en: String, _ cn: String) -> String { zh ? cn : en }

let claude = rgb(0.85, 0.47, 0.34)
let background = dark ? rgb(0.10, 0.10, 0.11) : rgb(0.985, 0.978, 0.968)
let border = dark ? rgb(1, 1, 1, 0.08) : rgb(0, 0, 0, 0.07)
let nodeFill = dark ? rgb(0.155, 0.155, 0.165) : .white
let nodeStroke = dark ? rgb(1, 1, 1, 0.10) : rgb(0, 0, 0, 0.09)
let primary = dark ? rgb(1, 1, 1, 0.94) : rgb(0.11, 0.11, 0.12)
let secondary = dark ? rgb(1, 1, 1, 0.58) : rgb(0, 0, 0, 0.52)
let chipFill = dark ? rgb(1, 1, 1, 0.06) : rgb(0, 0, 0, 0.04)
// Codex is black on light pages and white on dark ones, as in the app.
let codex = dark ? rgb(0.96, 0.96, 0.95) : rgb(0.11, 0.11, 0.12)
let codexGlyph = dark ? rgb(0.10, 0.10, 0.11) : .white

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale), pixelsHigh: Int(size.height * scale),
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current!.cgContext.scaleBy(x: scale, y: scale)

let canvas = NSBezierPath(roundedRect: NSRect(origin: .zero, size: size).insetBy(dx: 1, dy: 1), xRadius: 26, yRadius: 26)
background.setFill(); canvas.fill()
border.setStroke(); canvas.lineWidth = 1; canvas.stroke()

func text(_ s: String, _ font: NSFont, _ color: NSColor) -> NSAttributedString {
    NSAttributedString(string: s, attributes: [.font: font, .foregroundColor: color])
}
func symbol(_ name: String, _ pt: CGFloat, _ color: NSColor) -> NSImage {
    let config = NSImage.SymbolConfiguration(pointSize: pt, weight: .semibold)
        .applying(NSImage.SymbolConfiguration(paletteColors: [color]))
    return NSImage(systemSymbolName: name, accessibilityDescription: nil)!.withSymbolConfiguration(config)!
}
func drawSymbol(_ image: NSImage, center: NSPoint) {
    let s = image.size
    image.draw(in: NSRect(x: center.x - s.width / 2, y: center.y - s.height / 2, width: s.width, height: s.height))
}
func badge(_ n: Int, center: NSPoint, fill: NSColor, ink: NSColor) {
    fill.setFill()
    NSBezierPath(ovalIn: NSRect(x: center.x - 13, y: center.y - 13, width: 26, height: 26)).fill()
    let label = text("\(n)", .systemFont(ofSize: 14, weight: .bold), ink)
    let w = label.size()
    label.draw(at: NSPoint(x: center.x - w.width / 2, y: center.y - w.height / 2))
}

struct Node {
    let rect: NSRect, title: String, detail: String, chipSymbol: String, chip: String
    let avatarSymbol: String, avatarFill: NSColor, avatarInk: NSColor, step: Int
}

func draw(_ node: Node) {
    let r = node.rect
    let shape = NSBezierPath(roundedRect: r, xRadius: 20, yRadius: 20)
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = rgb(0, 0, 0, dark ? 0.35 : 0.07)
    shadow.shadowBlurRadius = 18
    shadow.shadowOffset = NSSize(width: 0, height: -4)
    shadow.set()
    nodeFill.setFill(); shape.fill()
    NSGraphicsContext.restoreGraphicsState()
    nodeStroke.setStroke(); shape.lineWidth = 1; shape.stroke()

    let avatar = NSPoint(x: r.minX + 52, y: r.maxY - 52)
    node.avatarFill.setFill()
    NSBezierPath(ovalIn: NSRect(x: avatar.x - 24, y: avatar.y - 24, width: 48, height: 48)).fill()
    drawSymbol(symbol(node.avatarSymbol, 19, node.avatarInk), center: avatar)

    text(node.title, .systemFont(ofSize: 25, weight: .semibold), primary)
        .draw(at: NSPoint(x: r.minX + 92, y: avatar.y - 15))
    badge(node.step, center: NSPoint(x: r.maxX - 38, y: avatar.y), fill: chipFill, ink: secondary)

    let detail = text(node.detail, .systemFont(ofSize: 18, weight: .regular), secondary)
    detail.draw(with: NSRect(x: r.minX + 28, y: r.minY + 78, width: r.width - 56, height: 52),
                options: [.usesLineFragmentOrigin])

    let chipText = text(node.chip, .systemFont(ofSize: 15, weight: .medium), primary.withAlphaComponent(0.8))
    let chipRect = NSRect(x: r.minX + 28, y: r.minY + 26, width: chipText.size().width + 52, height: 34)
    chipFill.setFill(); NSBezierPath(roundedRect: chipRect, xRadius: 10, yRadius: 10).fill()
    drawSymbol(symbol(node.chipSymbol, 13, secondary), center: NSPoint(x: chipRect.minX + 18, y: chipRect.midY))
    chipText.draw(at: NSPoint(x: chipRect.minX + 34, y: chipRect.midY - chipText.size().height / 2))
}

let left = NSRect(x: 56, y: 112, width: 400, height: 236)
let right = NSRect(x: 744, y: 112, width: 400, height: 236)

draw(Node(rect: left, title: "Claude Code",
          detail: tr("Reviews the receipt, checks the evidence, writes the next instruction", "审查回执、核对证据，写出下一条指令"),
          chipSymbol: "doc.text", chip: tr("updates task.md", "更新 task.md"),
          avatarSymbol: "text.magnifyingglass", avatarFill: claude, avatarInk: .white, step: 1))
draw(Node(rect: right, title: "Codex",
          detail: tr("Runs the instruction in the bound chat, start to finish", "在绑定的 Codex 会话里完整执行指令"),
          chipSymbol: "terminal", chip: tr("commands · edits · output", "命令 · 改动 · 输出"),
          avatarSymbol: "terminal.fill", avatarFill: codex, avatarInk: codexGlyph, step: 2))

// Arrows: dispatch arcs over the top, the receipt comes back underneath.
func arrow(from a: NSPoint, to b: NSPoint, c1: NSPoint, c2: NSPoint, color: NSColor, dashed: Bool) {
    let path = NSBezierPath()
    path.move(to: a); path.curve(to: b, controlPoint1: c1, controlPoint2: c2)
    path.lineWidth = 3; path.lineCapStyle = .round
    if dashed { path.setLineDash([2, 9], count: 2, phase: 0) }
    color.setStroke(); path.stroke()
    let angle = atan2(b.y - c2.y, b.x - c2.x)
    let head = NSBezierPath()
    let len: CGFloat = 15, spread: CGFloat = 0.5
    head.move(to: NSPoint(x: b.x - len * cos(angle - spread), y: b.y - len * sin(angle - spread)))
    head.line(to: b)
    head.line(to: NSPoint(x: b.x - len * cos(angle + spread), y: b.y - len * sin(angle + spread)))
    head.lineWidth = 3; head.lineCapStyle = .round; head.lineJoinStyle = .round
    head.stroke()
}
func pill(_ label: NSAttributedString, center: NSPoint, stroke: NSColor, step: Int?) {
    let extra: CGFloat = step == nil ? 0 : 30
    let w = label.size().width + 32 + extra
    let rect = NSRect(x: center.x - w / 2, y: center.y - 19, width: w, height: 38)
    let shape = NSBezierPath(roundedRect: rect, xRadius: 19, yRadius: 19)
    background.setFill(); shape.fill()
    stroke.setStroke(); shape.lineWidth = 1.5; shape.stroke()
    if let step {
        badge(step, center: NSPoint(x: rect.minX + 24, y: rect.midY), fill: chipFill, ink: secondary)
    }
    label.draw(at: NSPoint(x: rect.minX + 16 + extra, y: rect.midY - label.size().height / 2))
}

let receiptColor = dark ? rgb(1, 1, 1, 0.55) : rgb(0, 0, 0, 0.42)
arrow(from: NSPoint(x: left.maxX + 14, y: 286), to: NSPoint(x: right.minX - 16, y: 286),
      c1: NSPoint(x: 540, y: 372), c2: NSPoint(x: 660, y: 372), color: claude, dashed: false)
arrow(from: NSPoint(x: right.minX - 14, y: 174), to: NSPoint(x: left.maxX + 16, y: 174),
      c1: NSPoint(x: 660, y: 88), c2: NSPoint(x: 540, y: 88), color: receiptColor, dashed: true)

pill(text("send_to_codex", .monospacedSystemFont(ofSize: 16, weight: .semibold), claude),
     center: NSPoint(x: 600, y: 350), stroke: claude.withAlphaComponent(0.5), step: nil)
pill(text(tr("receipt", "回执"), .systemFont(ofSize: 16, weight: .semibold), primary),
     center: NSPoint(x: 600, y: 110), stroke: receiptColor.withAlphaComponent(0.6), step: 3)

let footer = text(tr("Repeats until the round limit, or until Claude stops to ask you.",
                     "如此往复，直到达到轮数上限，或 Claude 停下来问你。"),
                  .systemFont(ofSize: 15, weight: .regular), secondary)
footer.draw(at: NSPoint(x: (size.width - footer.size().width) / 2, y: 32))

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
