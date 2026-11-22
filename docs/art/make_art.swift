// Draws the README banner and the GitHub social preview in the app icon's style.
// Usage: swift make_art.swift <banner|social> <output.png>
// Run from the repository root so it can find icon/AppIcon.icns.
import AppKit

let kind = CommandLine.arguments[1]
let out = CommandLine.arguments[2]
let size = kind == "banner" ? NSSize(width: 1280, height: 400) : NSSize(width: 1280, height: 640)
let scale: CGFloat = 2

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: r, green: g, blue: b, alpha: a)
}
let claude = rgb(0.85, 0.47, 0.34)
let codex = rgb(0.97, 0.97, 0.96)

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale), pixelsHigh: Int(size.height * scale),
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current!.cgContext.scaleBy(x: scale, y: scale)

// Card: rounded so it sits well on both light and dark pages.
let card = NSRect(origin: .zero, size: size)
let shape = NSBezierPath(roundedRect: card, xRadius: kind == "banner" ? 28 : 0, yRadius: kind == "banner" ? 28 : 0)
shape.addClip()
NSGradient(colors: [rgb(0.20, 0.20, 0.22), rgb(0.11, 0.11, 0.12), rgb(0.07, 0.07, 0.08)],
           atLocations: [0, 0.55, 1], colorSpace: .sRGB)!.draw(in: card, angle: -70)

let icon = NSImage(contentsOfFile: "icon/AppIcon.icns")!
let iconSide: CGFloat = kind == "banner" ? 230 : 230
let iconCenter = kind == "banner" ? NSPoint(x: 205, y: size.height / 2) : NSPoint(x: size.width / 2, y: 430)
NSGradient(colors: [claude.withAlphaComponent(0.22), claude.withAlphaComponent(0)])!
    .draw(fromCenter: iconCenter, radius: 0, toCenter: iconCenter, radius: kind == "banner" ? 330 : 380, options: [])
icon.draw(in: NSRect(x: iconCenter.x - iconSide / 2, y: iconCenter.y - iconSide / 2, width: iconSide, height: iconSide))

func text(_ s: String, _ font: NSFont, _ color: NSColor) -> NSAttributedString {
    NSAttributedString(string: s, attributes: [.font: font, .foregroundColor: color, .kern: font.pointSize * -0.01])
}
func draw(_ a: NSAttributedString, x: CGFloat? = nil, y: CGFloat) {
    let w = a.size().width
    a.draw(at: NSPoint(x: x ?? (size.width - w) / 2, y: y))
}

let title = text("Session Relay", .systemFont(ofSize: kind == "banner" ? 76 : 80, weight: .bold), .white)
let tagline = text("Claude reviews. Codex builds. The loop runs itself.",
                   .systemFont(ofSize: kind == "banner" ? 27 : 30, weight: .regular), rgb(1, 1, 1, 0.72))

// The relay as three pills: who acts, in order.
func pills(x: CGFloat?, y: CGFloat) {
    let items: [(String, NSColor, Bool)] = [("Claude reviews", claude, false), ("Codex runs", codex, false), ("Receipt returns", claude, true)]
    let font = NSFont.systemFont(ofSize: 19, weight: .medium)
    let arrow = text("→", .systemFont(ofSize: 20, weight: .semibold), rgb(1, 1, 1, 0.45))
    let widths = items.map { text($0.0, font, .white).size().width + 52 }
    let total = widths.reduce(0, +) + CGFloat(items.count - 1) * 44
    var cursor = x ?? (size.width - total) / 2
    for (index, item) in items.enumerated() {
        let rect = NSRect(x: cursor, y: y, width: widths[index], height: 42)
        let pill = NSBezierPath(roundedRect: rect, xRadius: 21, yRadius: 21)
        rgb(1, 1, 1, 0.07).setFill(); pill.fill()
        rgb(1, 1, 1, 0.14).setStroke(); pill.lineWidth = 1; pill.stroke()
        let dot = NSBezierPath(ovalIn: NSRect(x: rect.minX + 18, y: rect.midY - 6, width: 12, height: 12))
        item.1.setFill(); dot.fill()
        if item.2 {  // The receipt goes back to Claude: hollow dot.
            rgb(0.12, 0.12, 0.13).setFill()
            NSBezierPath(ovalIn: NSRect(x: rect.minX + 21, y: rect.midY - 3, width: 6, height: 6)).fill()
        }
        text(item.0, font, .white).draw(at: NSPoint(x: rect.minX + 38, y: rect.midY - 12))
        cursor += widths[index]
        if index < items.count - 1 {
            arrow.draw(at: NSPoint(x: cursor + 12, y: rect.midY - 13))
            cursor += 44
        }
    }
}

if kind == "banner" {
    let left: CGFloat = 380
    draw(title, x: left, y: 222)
    draw(tagline, x: left + 3, y: 172)
    pills(x: left, y: 92)
} else {
    draw(title, y: 218)
    draw(tagline, y: 168)
    pills(x: nil, y: 88)
}

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
