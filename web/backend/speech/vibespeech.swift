import Foundation
import Speech
import AVFoundation
import NaturalLanguage

// On-device speech-to-text for VibeCut's talking-head mode (web/backend/speech.py).
// Apple's SpeechAnalyzer / SpeechTranscriber (macOS 26+): the audio never
// leaves the Mac. The locale's model is downloaded by the OS on first use.
//
// usage: vibespeech <audio file> <locale e.g. zh-CN>
// stdout: one JSON object per finalized result:
//   {"text", "start", "end", "words": [{"t": text, "s": start, "e": end, "c": confidence}], "segs": [word...]}
// Chinese comes back one character per timed run; English one word. "segs"
// is the text split into words by NLTokenizer (on-device), so subtitles can
// break between words even in Chinese, which has no spaces. "c" is the
// recogniser's own confidence in that run (0..1), null where it gives none:
// subtitles.py marks the words it wasn't sure of, so the creator can fix
// them instead of reading a guess as fact.
@main struct VibeSpeech {
  static func main() async {
    let args = CommandLine.arguments
    guard args.count >= 3 else { FileHandle.standardError.write("usage: vibespeech <audio> <locale>\n".data(using: .utf8)!); exit(2) }
    do {
      let transcriber = SpeechTranscriber(locale: Locale(identifier: args[2]), transcriptionOptions: [],
                                          reportingOptions: [], attributeOptions: [.audioTimeRange, .transcriptionConfidence])
      if let req = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
        FileHandle.standardError.write("downloading speech model for \(args[2])\n".data(using: .utf8)!)
        try await req.downloadAndInstall()
      }
      let analyzer = SpeechAnalyzer(modules: [transcriber])
      let file = try AVAudioFile(forReading: URL(fileURLWithPath: args[1]))
      let collect = Task {
        for try await r in transcriber.results {
          var words: [[String: Any]] = []
          for run in r.text.runs {
            guard let tr = run.audioTimeRange else { continue }
            let t = String(r.text[run.range].characters)
            var w: [String: Any] = ["t": t, "s": tr.start.seconds, "e": tr.end.seconds]
            if let c = run.transcriptionConfidence { w["c"] = c } else { w["c"] = NSNull() }
            words.append(w)
          }
          let text = String(r.text.characters)
          let tok = NLTokenizer(unit: .word)
          tok.string = text
          var segs: [String] = []
          tok.enumerateTokens(in: text.startIndex..<text.endIndex) { range, _ in
            segs.append(String(text[range])); return true
          }
          let obj: [String: Any] = ["text": text, "start": r.range.start.seconds,
                                    "end": r.range.end.seconds, "words": words, "segs": segs]
          let data = try JSONSerialization.data(withJSONObject: obj)
          FileHandle.standardOutput.write(data); FileHandle.standardOutput.write("\n".data(using: .utf8)!)
        }
      }
      if let last = try await analyzer.analyzeSequence(from: file) {
        try await analyzer.finalizeAndFinish(through: last)
      } else {
        await analyzer.cancelAndFinishNow()
      }
      try await collect.value
    } catch {
      FileHandle.standardError.write("error: \(error)\n".data(using: .utf8)!)
      exit(1)
    }
  }
}
