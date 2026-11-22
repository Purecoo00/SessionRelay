// Renders the Session Relay app icon: two sessions joined by a relay loop.
// Usage: swift make_icon.swift <output.png> [size]
import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.png"
let size = CommandLine.arguments.count > 2 ? Double(CommandLine.arguments[2])! : 1024
let s = size / 1024  // All geometry is designed on a 1024 canvas.

func rgb(_ r: Double, _ g: Double, _ b: Double, _ a: Double = 1) -> NSColor {
    NSColor(srgbRed: r, green: g, blue: b, alpha: a)
}
let claude = rgb(0.85, 0.47, 0.34)   // Warm terracotta for the Claude session.
let codex = rgb(0.97, 0.97, 0.96)    // White for the Codex session.
let deep = rgb(0.07, 0.07, 0.08)

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size),
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext
ctx.scaleBy(x: s, y: s)

// Tile: macOS grid places the body at 824 pt inside the 1024 canvas.
let body = NSRect(x: 100, y: 100, width: 824, height: 824)
let tile = NSBezierPath(roundedRect: body, xRadius: 185, yRadius: 185)
NSGraphicsContext.saveGraphicsState()
let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
shadow.shadowOffset = NSSize(width: 0, height: -10)
shadow.shadowBlurRadius = 28
shadow.set()
deep.setFill()
tile.fill()
NSGraphicsContext.restoreGraphicsState()

NSGraphicsContext.saveGraphicsState()
tile.addClip()
NSGradient(colors: [rgb(0.24, 0.24, 0.26), rgb(0.14, 0.14, 0.15), rgb(0.07, 0.07, 0.08)],
           atLocations: [0, 0.55, 1], colorSpace: .sRGB)!.draw(in: body, angle: -90)
// Soft glow behind the loop.
NSGradient(colors: [rgb(1.0, 0.72, 0.58, 0.16), rgb(1.0, 0.72, 0.58, 0)])!
    .draw(fromCenter: NSPoint(x: 512, y: 540), radius: 0, toCenter: NSPoint(x: 512, y: 540), radius: 420, options: [])
NSGraphicsContext.restoreGraphicsState()
rgb(1, 1, 1, 0.10).setStroke()
let rim = NSBezierPath(roundedRect: body.insetBy(dx: 1.5, dy: 1.5), xRadius: 184, yRadius: 184)
rim.lineWidth = 3
rim.stroke()

// Relay loop: two arcs, each carrying work from one session to the other.
let c = NSPoint(x: 512, y: 512)
let R = 250.0, width = 64.0
func point(_ deg: Double, _ r: Double) -> NSPoint {
    let a = deg * .pi / 180
    return NSPoint(x: c.x + r * cos(a), y: c.y + r * sin(a))
}
func arrow(from start: Double, to end: Double, tip: Double, color: NSColor) {
    let arc = NSBezierPath()
    arc.appendArc(withCenter: c, radius: R, startAngle: start, endAngle: end, clockwise: true)
    arc.lineWidth = width
    arc.lineCapStyle = .round
    color.setStroke()
    arc.stroke()
    let head = NSBezierPath()
    head.move(to: point(tip, R))
    head.line(to: point(end + 4, R + 58))
    head.line(to: point(end + 4, R - 58))
    head.close()
    head.lineJoinStyle = .round
    head.lineWidth = 14
    color.setFill(); color.setStroke()
    head.fill(); head.stroke()
}
NSGraphicsContext.saveGraphicsState()
let glow = NSShadow()
glow.shadowColor = NSColor.black.withAlphaComponent(0.28)
glow.shadowOffset = NSSize(width: 0, height: -8)
glow.shadowBlurRadius = 18
glow.set()
ctx.beginTransparencyLayer(auxiliaryInfo: nil)  // One shadow for the whole loop, not per stroke.
arrow(from: 150, to: 52, tip: 26, color: claude)     // Claude → Codex, over the top.
arrow(from: -30, to: -128, tip: -154, color: codex)  // Codex → Claude, underneath.

// The two sessions.
func node(_ deg: Double, _ fill: NSColor) {
    let p = point(deg, R)
    let outer = NSBezierPath(ovalIn: NSRect(x: p.x - 92, y: p.y - 92, width: 184, height: 184))
    fill.setFill()
    outer.fill()
}
node(180, claude)
node(0, codex)
ctx.endTransparencyLayer()
NSGraphicsContext.restoreGraphicsState()
for (deg, color) in [(180.0, rgb(0.16, 0.16, 0.17)), (0.0, rgb(0.13, 0.13, 0.14))] {
    let p = point(deg, R)
    color.setFill()
    NSBezierPath(ovalIn: NSRect(x: p.x - 38, y: p.y - 38, width: 76, height: 76)).fill()
}

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
