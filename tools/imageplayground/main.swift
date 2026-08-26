// CLI nhỏ gọi ImagePlayground.ImageCreator của Apple Intelligence.
//
// Dùng để thử xem Image Playground có thay được đường sinh keyframe cho content
// profile hay không. Chưa nối vào pipeline: đây là công cụ đo, không phải
// provider. Nếu đạt thì mới bọc thành ImageProvider trong providers/image/.
//
//   swiftc -O -o ipgen main.swift -framework ImagePlayground
//   ./ipgen --style illustration --limit 2 --out /tmp/out "mô tả cảnh"

import Foundation
import ImagePlayground
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

struct Options {
    var style = "illustration"
    var limit = 1
    var out = FileManager.default.currentDirectoryPath
    var sourceImage: URL?
    var prompt = ""
    var listStyles = false
}

func parse() -> Options {
    var options = Options()
    var rest: [String] = []
    var index = 1
    let argv = CommandLine.arguments
    while index < argv.count {
        switch argv[index] {
        case "--style": index += 1; options.style = argv[index]
        case "--limit": index += 1; options.limit = Int(argv[index]) ?? 1
        case "--out": index += 1; options.out = argv[index]
        case "--source": index += 1; options.sourceImage = URL(fileURLWithPath: argv[index])
        case "--list-styles": options.listStyles = true
        default: rest.append(argv[index])
        }
        index += 1
    }
    options.prompt = rest.joined(separator: " ")
    return options
}

func style(named name: String, from available: [ImagePlaygroundStyle]) -> ImagePlaygroundStyle? {
    available.first { $0.id.lowercased() == name.lowercased() }
}

func write(_ image: CGImage, to url: URL) throws {
    guard let destination = CGImageDestinationCreateWithURL(
        url as CFURL, UTType.png.identifier as CFString, 1, nil
    ) else { throw NSError(domain: "ipgen", code: 1) }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw NSError(domain: "ipgen", code: 2)
    }
}

let options = parse()
guard options.listStyles || !options.prompt.isEmpty else {
    FileHandle.standardError.write("cần một mô tả cảnh\n".data(using: .utf8)!)
    exit(2)
}

let semaphore = DispatchSemaphore(value: 0)
var exitCode: Int32 = 0

Task {
    defer { semaphore.signal() }
    do {
        let creator = try await ImageCreator()
        if options.listStyles {
            print(creator.availableStyles.map { $0.id }.joined(separator: ", "))
            return
        }
        guard let chosen = style(named: options.style, from: creator.availableStyles) else {
            let names = creator.availableStyles.map { $0.id }.joined(separator: ", ")
            FileHandle.standardError.write("style không có; chỉ có: \(names)\n".data(using: .utf8)!)
            exitCode = 3
            return
        }
        var concepts: [ImagePlaygroundConcept] = [.text(options.prompt)]
        if let source = options.sourceImage, let concept = ImagePlaygroundConcept.image(source) {
            concepts.append(concept)
        }
        try FileManager.default.createDirectory(
            atPath: options.out, withIntermediateDirectories: true
        )
        var count = 0
        for try await created in creator.images(
            for: concepts, style: chosen, limit: options.limit
        ) {
            let url = URL(fileURLWithPath: options.out)
                .appendingPathComponent(String(format: "ipgen-%02d.png", count))
            try write(created.cgImage, to: url)
            print(url.path)
            count += 1
        }
        if count == 0 {
            FileHandle.standardError.write("không sinh được ảnh nào\n".data(using: .utf8)!)
            exitCode = 4
        }
    } catch {
        let log = FileHandle(forWritingAtPath: "/tmp/ipgen.log") ?? {
            FileManager.default.createFile(atPath: "/tmp/ipgen.log", contents: nil)
            return FileHandle(forWritingAtPath: "/tmp/ipgen.log")!
        }()
        log.seekToEndOfFile()
        log.write("lỗi: \(error)\n".data(using: .utf8)!)
        FileHandle.standardError.write("lỗi: \(error)\n".data(using: .utf8)!)
        exitCode = 5
    }
}

semaphore.wait()
exit(exitCode)
