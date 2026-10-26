"""The talking-head cut through the real on-device recogniser.

A known script is spoken by macOS's Chinese voice (Tingting) with long
pauses and one sentence said twice, put into a video, transcribed by the
Swift helper, and cut. What must come out: the earlier take gone, the
pauses down to a breath, the video shorter by about what was removed, and
subtitles that say the script.

Needs macOS 26+ (SpeechTranscriber; the Chinese model downloads once).
Skips elsewhere. ~20 s.

    python tests/test_talk_speech.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = Path(tempfile.mkdtemp(prefix="vibecut-talk-"))
os.environ["VIBECUT_CACHE"] = str(TMP / "cache")

from web.backend import speech, talk  # noqa: E402

SCRIPT = ("大家好，今天我们聊聊怎么剪口播视频。[[slnc 1600]]"
          "第一步是把气口剪掉。[[slnc 1400]]"
          "第二步是删掉重复的句子。[[slnc 500]]第二步是删掉重复的句子。[[slnc 1300]]"
          "最后配上字幕就完成了。")


def main() -> int:
    failures = []

    def check(name: str, cond: bool, got: str) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}: {got}")
        if not cond:
            failures.append(name)

    try:
        speech.ensure_built()
    except speech.SpeechError as e:
        print(f"  SKIP  {e}")
        return 0
    aiff, mov = TMP / "vo.aiff", TMP / "talk.mov"
    subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), SCRIPT], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30", "-i", str(aiff),
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(mov)], check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mov)],
                               capture_output=True, text=True).stdout)
    clip = {"id": "talk00000001", "name": "talk.mov", "path": str(mov), "duration": dur,
            "shots": [{"index": 0, "start": 0.0, "end": dur}]}
    res = speech.transcribe(clip, "zh-CN")
    heard = "".join(r["text"] for r in res)
    check("the recogniser hears the script", talk.containment("第一步是把气口剪掉", heard) > 0.8, heard[:40])
    confs = [w.get("c") for r in res for w in r["words"]]
    check("and says how sure it is of each word (0..1)", confs and all(c is None or 0.0 <= c <= 1.0 for c in confs)
          and any(c is not None for c in confs), f"{sum(c is not None for c in confs)}/{len(confs)} words with a confidence")

    p = talk.build({clip["id"]: res}, {clip["id"]: clip}, "zh-CN", {clip["id"]: talk.active(speech.audio(clip))})
    pub = talk.public(p)
    takes = [it for it in pub["items"] if it["kind"] == "sentence" and "重复" in it["text"]]
    check("of the two takes, the first goes and the second stays",
          len(takes) == 2 and takes[0]["removed"] and not takes[1]["removed"],
          " | ".join(f"{'✗' if t['removed'] else '✓'} {t['text']}" for t in takes))
    cut_pauses = [it for it in pub["items"] if it["kind"] == "pause" and it["cut"]]
    check("the three long pauses are cut", len(cut_pauses) >= 3, str([it["len"] for it in cut_pauses]))
    kept = sum(x["end"] - x["start"] for x in talk.spans(p))
    check("the cut is shorter by the pauses and the retake", dur - kept > 4.5, f"{dur:.1f}s -> {kept:.1f}s")
    caps = talk.board(p)["overlays"]
    said = "".join(c["text"] for c in caps)
    # (the recogniser may mishear a character -- 第二部 -- which the creator fixes in Words on screen)
    check("subtitles say the repeated sentence once", said.count("删掉重复") == 1 and "最后配上字幕" in said,
          " / ".join(c["text"] for c in caps))
    print(f"\n  {pub['summary']['line_en']}")

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
