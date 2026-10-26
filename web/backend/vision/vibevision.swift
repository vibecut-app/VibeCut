// On-device Vision pass over shot thumbnails. Nothing leaves the machine.
//
//   vibevision img1.jpg img2.jpg ...   -> one JSON object per line on stdout
//   vibevision --faces | --text | --text2 a.jpg ...   (see below)
//
// Gives the index what numpy can't: what is in the frame (labels, faces),
// an embedding to cluster by subject, and Apple's aesthetics score as the
// per-shot quality number the tech plan calls for.

import Foundation
import Vision

struct Out: Encodable {
    let path: String
    let labels: [[String: Double]]   // [{label: confidence}], top few
    let faces: Int
    let faceArea: Double             // largest face as fraction of frame -- shot-size proxy
    let aesthetic: Double?           // -1...1
    let utility: Bool?               // screenshots, documents, receipts
    let embedding: [Float]
    let error: String?
}

func analyse(_ path: String) async -> Out {
    let url = URL(fileURLWithPath: path)
    do {
        let labels = try await ClassifyImageRequest().perform(on: url)
            .filter { $0.confidence > 0.15 }
            .sorted { $0.confidence > $1.confidence }
            .prefix(8)
            .map { [$0.identifier: Double($0.confidence)] }
        let faces = try await DetectFaceRectanglesRequest().perform(on: url)
        let area = faces.map { Double($0.boundingBox.width * $0.boundingBox.height) }.max() ?? 0
        var aesthetic: Double? = nil
        var utility: Bool? = nil
        if let a = try? await CalculateImageAestheticsScoresRequest().perform(on: url) {
            aesthetic = Double(a.overallScore)
            utility = a.isUtility
        }
        let fp = try await GenerateImageFeaturePrintRequest().perform(on: url)
        var emb = [Float]()
        fp.data.withUnsafeBytes { raw in
            if fp.elementType == .float {
                emb = Array(raw.bindMemory(to: Float.self))
            } else {
                emb = raw.bindMemory(to: Double.self).map { Float($0) }
            }
        }
        return Out(path: path, labels: Array(labels), faces: faces.count, faceArea: area,
                   aesthetic: aesthetic, utility: utility, embedding: emb, error: nil)
    } catch {
        return Out(path: path, labels: [], faces: 0, faceArea: 0, aesthetic: nil,
                   utility: nil, embedding: [], error: "\(error)")
    }
}

// `vibevision --faces a.jpg b.jpg ...`: face boxes only, for every sampled
// second of a clip (trim needs to know when a person is in or leaving frame).
struct FaceOut: Encodable {
    let path: String
    let faces: [[Double]]   // [x, y, w, h, yaw?], normalised, origin bottom-left; yaw in degrees
}

// Which way a face is turned: 0 is straight at the lens. Talking to the
// audience is done looking into the phone; chatting with a friend is done
// turned towards them -- the one thing that tells the two apart.
func degrees(_ m: Measurement<UnitAngle>?) -> Double? {
    guard let m else { return nil }
    return m.converted(to: .degrees).value
}

func faces(_ path: String) async -> FaceOut {
    let url = URL(fileURLWithPath: path)
    let found = (try? await DetectFaceRectanglesRequest().perform(on: url)) ?? []
    return FaceOut(path: path, faces: found.map {
        let box = [Double($0.boundingBox.origin.x), Double($0.boundingBox.origin.y),
                   Double($0.boundingBox.width), Double($0.boundingBox.height)]
        if let yaw = degrees($0.yaw) { return box + [yaw] }
        return box
    })
}

// `vibevision --text a.jpg b.jpg ...`: the words on screen in each frame and
// where they sit, so a reference reel can teach when its text appears, how
// long it holds and where (research 06 / spec P16). Fast recognition is
// enough: the words themselves matter less than their timing and place.
struct TextItem: Encodable {
    let text: String
    let box: [Double]        // x, y, w, h, normalised, origin bottom-left
    let conf: Double
}
struct TextOut: Encodable {
    let path: String
    let items: [TextItem]
}

// `vibevision --text2 a.jpg ...`: the same, read by the accurate recogniser
// with language detection. Fast reads Latin script only; a Korean,
// Japanese or Chinese caption needs accurate. Slower, so only the taste
// collector asks for it.
func words(_ path: String, accurate: Bool = false) async -> TextOut {
    let url = URL(fileURLWithPath: path)
    var req = RecognizeTextRequest()
    if accurate {
        let langs = ["en-US", "ko-KR", "ja-JP", "zh-Hans", "zh-Hant", "fr-FR", "es-ES"]
        req.recognitionLevel = .accurate
        req.automaticallyDetectsLanguage = true
        req.recognitionLanguages = langs.map { Locale.Language(identifier: $0) }
    } else {
        req.recognitionLevel = .fast
    }
    req.usesLanguageCorrection = false
    let found = (try? await req.perform(on: url)) ?? []
    return TextOut(path: path, items: found.compactMap { obs in
        guard let top = obs.topCandidates(1).first else { return nil }
        let b = obs.boundingBox
        return TextItem(text: top.string,
                        box: [Double(b.origin.x), Double(b.origin.y), Double(b.width), Double(b.height)],
                        conf: Double(top.confidence))
    })
}

var args = Array(CommandLine.arguments.dropFirst())
let enc = JSONEncoder()
if args.first == "--text" || args.first == "--text2" {
    let accurate = args.first == "--text2"
    args.removeFirst()
    // One frame at a time: text recognition deadlocked when a task group
    // ran 18 requests at once (2026-10-18, 0% CPU, never returned); the
    // Python side chunks and parallelises across processes instead.
    for p in args {
        let r = await words(p, accurate: accurate)
        if let d = try? enc.encode(r), let s = String(data: d, encoding: .utf8) { print(s) }
        fflush(stdout)
    }
    exit(0)
}
if args.first == "--faces" {
    args.removeFirst()
    let found = await withTaskGroup(of: (Int, FaceOut).self) { group in
        for (i, p) in args.enumerated() { group.addTask { (i, await faces(p)) } }
        var acc = [(Int, FaceOut)]()
        for await r in group { acc.append(r) }
        return acc.sorted { $0.0 < $1.0 }.map { $0.1 }
    }
    for r in found {
        if let d = try? enc.encode(r), let s = String(data: d, encoding: .utf8) { print(s) }
    }
    exit(0)
}
let paths = args
let results = await withTaskGroup(of: (Int, Out).self) { group in
    for (i, p) in paths.enumerated() {
        group.addTask { (i, await analyse(p)) }
    }
    var acc = [(Int, Out)]()
    for await r in group { acc.append(r) }
    return acc.sorted { $0.0 < $1.0 }.map { $0.1 }
}
for r in results {
    if let d = try? enc.encode(r), let s = String(data: d, encoding: .utf8) { print(s) }
}
