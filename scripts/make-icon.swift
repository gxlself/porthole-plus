// 舷窗Plus app icon，沿用 Window Seat 图标的舷窗、星空和云海。Renders the app icon (1024×1024, opaque) with SwiftUI.
// Usage: swift scripts/make-icon.swift <out.png> [variant]
import AppKit
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255, opacity: opacity)
    }
}

struct Icon: View {
    let s: CGFloat = 1024

    var body: some View {
        ZStack {
            // cabin wall
            LinearGradient(colors: [Color(hex: 0x1A2440), Color(hex: 0x0A0F1D)], startPoint: .top, endPoint: .bottom)
            RadialGradient(colors: [Color(hex: 0xFFB54A, opacity: 0.20), .clear], center: UnitPoint(x: 0.5, y: 0.08), startRadius: 0, endRadius: 620)

            // window frame (outer bezel)
            let w: CGFloat = 572, h: CGFloat = 800, r: CGFloat = 286
            RoundedRectangle(cornerRadius: r, style: .continuous)
                .fill(LinearGradient(colors: [Color(hex: 0xE9ECF4), Color(hex: 0xA9B1C6)], startPoint: .top, endPoint: .bottom))
                .frame(width: w + 92, height: h + 92)
                .shadow(color: .black.opacity(0.55), radius: 40, y: 26)
            RoundedRectangle(cornerRadius: r - 10, style: .continuous)
                .fill(LinearGradient(colors: [Color(hex: 0x8C95AC), Color(hex: 0xD9DEEA)], startPoint: .top, endPoint: .bottom))
                .frame(width: w + 40, height: h + 40)

            // the view outside
            ZStack {
                LinearGradient(
                    stops: [
                        .init(color: Color(hex: 0x0E1838), location: 0),
                        .init(color: Color(hex: 0x2B2F6B), location: 0.42),
                        .init(color: Color(hex: 0x8A4E86), location: 0.66),
                        .init(color: Color(hex: 0xFFAE5E), location: 0.86),
                        .init(color: Color(hex: 0xFFD98F), location: 1),
                    ],
                    startPoint: .top, endPoint: .bottom
                )
                // stars
                ForEach(0..<14, id: \.self) { i in
                    let xs: [CGFloat] = [-190, -120, 150, 210, -40, 90, -210, 30, 180, -150, 120, -80, 60, 230]
                    let ys: [CGFloat] = [-300, -230, -290, -190, -330, -250, -120, -170, -60, -40, -130, -280, -350, -300]
                    let sz: [CGFloat] = [7, 5, 6, 4, 5, 8, 4, 4, 5, 3, 4, 3, 4, 3]
                    Circle().fill(.white.opacity(0.85)).frame(width: sz[i], height: sz[i]).offset(x: xs[i], y: ys[i])
                }
                // moon
                Circle()
                    .fill(Color(hex: 0xFFF3D6))
                    .frame(width: 96, height: 96)
                    .mask(
                        ZStack {
                            Rectangle()
                            Circle().frame(width: 84, height: 84).offset(x: 29, y: -19).blendMode(.destinationOut)
                        }
                        .compositingGroup()
                    )
                    .shadow(color: Color(hex: 0xFFE7B0).opacity(0.7), radius: 30)
                    .offset(x: -170, y: -250)

                // 五块发光方块拼成「+」：中间是品牌黄，四臂是四种玩法色
                let tile: CGFloat = 112, gap: CGFloat = 10, step = tile + gap
                let cells: [(CGFloat, CGFloat, UInt32)] = [(0, -1, 0x5BD8C1), (-1, 0, 0xF47C92), (0, 0, 0xFFC83D), (1, 0, 0x68B7FF), (0, 1, 0xB18CFF)]
                ZStack {
                    ForEach(0..<5, id: \.self) { i in
                        let c = cells[i]
                        RoundedRectangle(cornerRadius: 28, style: .continuous)
                            .fill(LinearGradient(colors: [Color(hex: c.2), Color(hex: c.2).opacity(0.8)], startPoint: .top, endPoint: .bottom))
                            .overlay(
                                RoundedRectangle(cornerRadius: 28, style: .continuous)
                                    .strokeBorder(.white.opacity(0.45), lineWidth: 3)
                            )
                            .overlay(alignment: .top) {
                                RoundedRectangle(cornerRadius: 18, style: .continuous)
                                    .fill(.white.opacity(0.3))
                                    .frame(height: 24)
                                    .padding(.horizontal, 15)
                                    .padding(.top, 11)
                            }
                            .frame(width: tile, height: tile)
                            .shadow(color: Color(hex: c.2).opacity(0.8), radius: i == 2 ? 34 : 24)
                            .offset(x: c.0 * step, y: c.1 * step)
                    }
                }
                .rotationEffect(.degrees(-5))
                .offset(x: 10, y: 10)

                // cloud sea
                ZStack {
                    ForEach(0..<9, id: \.self) { i in
                        let xs: [CGFloat] = [-300, -200, -90, 20, 130, 240, -250, -30, 190]
                        let ys: [CGFloat] = [330, 300, 320, 296, 318, 300, 380, 372, 380]
                        let ds: [CGFloat] = [190, 170, 210, 180, 200, 170, 220, 240, 220]
                        Circle()
                            .fill(LinearGradient(colors: [.white, Color(hex: 0xF4E3D7)], startPoint: .top, endPoint: .bottom))
                            .frame(width: ds[i], height: ds[i])
                            .offset(x: xs[i], y: ys[i])
                    }
                }
                .opacity(0.96)
            }
            .frame(width: w, height: h)
            .clipShape(RoundedRectangle(cornerRadius: r - 30, style: .continuous))
            .overlay(
                // inner shadow & glass glare
                RoundedRectangle(cornerRadius: r - 30, style: .continuous)
                    .strokeBorder(Color.black.opacity(0.35), lineWidth: 10)
                    .blur(radius: 8)
                    .clipShape(RoundedRectangle(cornerRadius: r - 30, style: .continuous))
            )
            .overlay(
                LinearGradient(colors: [.white.opacity(0.22), .white.opacity(0)], startPoint: .topLeading, endPoint: UnitPoint(x: 0.55, y: 0.45))
                    .clipShape(RoundedRectangle(cornerRadius: r - 30, style: .continuous))
                    .allowsHitTesting(false)
            )
        }
        .frame(width: s, height: s)
    }
}

@MainActor
func render(to path: String) throws {
    let renderer = ImageRenderer(content: Icon())
    renderer.scale = 1
    guard let image = renderer.cgImage else { throw NSError(domain: "icon", code: 1) }
    let size = 1024
    let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                        space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: size, height: size))
    let opaque = ctx.makeImage()!
    let url = URL(fileURLWithPath: path) as CFURL
    let dest = CGImageDestinationCreateWithURL(url, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, opaque, nil)
    CGImageDestinationFinalize(dest)
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon-1024.png"
try MainActor.assumeIsolated { try render(to: out) }
print("wrote \(out)")
