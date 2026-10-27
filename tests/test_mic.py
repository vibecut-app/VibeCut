"""Voiceover: the creator's voice recorded over the edit (mic.py, board.add_voice).

The edit is two pure-tone clips (440 Hz / 880 Hz) with a 220 Hz "music"
bed under them; the "voice" is a 660 Hz tone that talks for 1.5 s, pauses
for 1 s and talks for 1 s, sent the way Chrome's recorder sends it (Opus in
WebM). Each tone can be measured on its own, so each check moves one thing:

- the take is saved as WAV with its true length; empty or too short is refused;
- the voice sounds where it was recorded and nowhere before it, and the
  shots' own sound is untouched;
- the music ducks to VOICE_DUCK of its level under the voice and comes back
  up in the pause between the two sentences (the magnitude built in);
- volume 50% is half the voice; muted: no voice and no duck; deleted: gone,
  and undo brings it back;
- the timeline lists it as a voice strip; a made-up file name is refused.

    python tests/test_mic.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = Path(tempfile.mkdtemp(prefix="vibecut-mic-"))
os.environ["VIBECUT_CACHE"] = str(TMP / "cache")

from web.backend import audiomix as am  # noqa: E402
from web.backend import board as bd  # noqa: E402
from web.backend import mic  # noqa: E402
from web.backend import timeline  # noqa: E402

SR = am.SR
failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def tone_clip(path: Path, freq: int, dur: float = 6.0) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=160x90:r=30:d={dur}",
                    "-f", "lavfi", "-i", f"sine=f={freq}:d={dur}:sample_rate=48000", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", str(path)], check=True)


def energy(x: np.ndarray, freq: float, a: float, b: float) -> float:
    s = x[int(a * SR):int(b * SR), 0]
    if len(s) == 0:
        return 0.0
    t = np.arange(len(s)) / SR
    return float(2 * np.hypot((s * np.cos(2 * np.pi * freq * t)).mean(), (s * np.sin(2 * np.pi * freq * t)).mean()))


def shot(cid: str) -> dict:
    return {"id": cid, "name": f"{cid}.MOV", "capture_time": None, "gps": None, "path": "", "duration": 6.0,
            "shots": [{"index": 0, "start": 0.0, "end": 6.0, "thumb": "shot000.jpg", "best_t": 3.0,
                       "quality": 0.6, "aesthetic": None, "utility": False, "labels": [["x", 0.8]],
                       "faces": 0, "face_area": 0.0, "embedding": [1.0] + [0.0] * 7}]}


def voice_webm() -> bytes:
    """1.5 s of "talking", 1 s of quiet, 1 s of talking: Opus in WebM, as Chrome records."""
    out = TMP / "take.webm"
    talk = "sin(2*PI*660*t)*0.5*(lt(t\\,1.5)+gte(t\\,2.5))"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc={talk}:s=48000:d=3.5",
                    "-c:a", "libopus", "-b:a", "96k", str(out)], check=True)
    return out.read_bytes()


def main() -> int:
    A, B, M = TMP / "a.mov", TMP / "b.mov", TMP / "music.wav"
    tone_clip(A, 440)
    tone_clip(B, 880)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=20:sample_rate=48000",
                    "-ac", "2", str(M)], check=True)
    clips = {"A": {"id": "A", "path": str(A), "duration": 6.0}, "B": {"id": "B", "path": str(B), "duration": 6.0}}
    cat = bd.Catalog.from_clips([shot("A"), shot("B")])
    option = {"key": "o", "name": "Two", "summary": "", "beats": [{"title": "All", "detail": "", "shots": [
        {"id": "A:0", "start": 0.0, "end": 4.0}, {"id": "B:0", "start": 0.0, "end": 4.0}]}]}
    mk = lambda d: {"options": [option]}  # noqa: E731
    s = bd.Session()
    s.add({"kind": "chat", "text": "go", "ops": [], "direction": {"text": "go"}}, cat, mk)
    s.add({"kind": "direct", "text": "pick", "ops": [{"op": "choose_option", "option": "o"}]}, cat, mk)
    music = {"path": str(M), "in": 0.0, "gain": am.MUSIC_GAIN, "fade_out": 0.0}

    def mix():
        items = timeline.layout(s.board)
        buf, _ = am.render(items, clips, music=music, sound=am.strips_of(s.board))
        return buf

    before = mix()

    print("saving a take")
    vid, dur = mic.save(voice_webm(), ".webm")
    check("saved as WAV with its true length", mic.path_of(vid).exists() and abs(dur - 3.5) < 0.05, f"{dur}")
    for bad, why in ((b"", "empty"), (b"not audio at all", "unreadable")):
        try:
            mic.save(bad, ".webm")
            check(f"{why} is refused", False)
        except mic.MicError as e:
            check(f"{why} is refused", True, str(e))
    short = TMP / "short.webm"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=660:d=0.1:sample_rate=48000",
                    "-c:a", "libopus", str(short)], check=True)
    try:
        mic.save(short.read_bytes(), ".webm")
        check("a click on and straight off is refused", False)
    except mic.MicError as e:
        check("a click on and straight off is refused", True, str(e))

    print("recorded at 2 s")
    t = s.add({"kind": "direct", "text": "rec", "ops": [{"op": "add_voice", "voice": vid, "at": 2.0, "dur": dur}]}, cat, mk)
    take = s.board["sound"]["voice"][0]
    check("one take, where recording started", (take["at"], take["dur"], take["gain"]) == (2.0, dur, 1.0), str(take))
    check("the turn says what happened", any("Recorded" in x["text"] for x in t.lines), str(t.lines))
    x = mix()
    loud = energy(x, 660, 2.2, 3.3)
    check("the voice sounds where it was recorded", loud > 0.3, f"{loud:.3f}")
    check("…and nowhere before it", energy(x, 660, 0.2, 1.8) < 0.01, f"{energy(x, 660, 0.2, 1.8):.3f}")
    check("the shots' own sound is untouched",
          abs(energy(x, 440, 0.5, 3.5) - energy(before, 440, 0.5, 3.5)) < 0.01
          and abs(energy(x, 880, 4.5, 7.5) - energy(before, 880, 4.5, 7.5)) < 0.01)
    full = energy(before, 220, 2.4, 3.3)
    under = energy(x, 220, 2.4, 3.3) / full
    check("the music ducks under the voice to VOICE_DUCK (the magnitude built in)",
          abs(under - mic.VOICE_DUCK) < 0.03, f"{under:.3f}")
    check("…and is untouched before the voice", abs(energy(x, 220, 0.2, 1.6) / energy(before, 220, 0.2, 1.6) - 1) < 0.02)
    gap = energy(x, 220, 3.9, 4.2) / energy(before, 220, 3.9, 4.2)
    check("…comes back up in the pause between sentences", gap > 0.9, f"{gap:.3f}")
    check("…and goes down again for the second", energy(x, 220, 4.75, 5.3) / energy(before, 220, 4.75, 5.3) < 0.4)
    lane = timeline.audio_lane(s.board, timeline.layout(s.board))
    check("the timeline draws it as voice strip 1", [(v["id"], v["n"], v["voice"]) for v in lane["voice"]] == [(take["id"], 1, True)],
          str(lane["voice"]))

    sid = take["id"]
    print("volume, mute, move, delete")
    v = s.add({"kind": "direct", "text": "vol", "ops": [{"op": "edit_audio", "audio": sid, "gain": 0.5}]}, cat, mk)
    half = energy(mix(), 660, 2.2, 3.3) / loud
    check("50% is half the voice", abs(half - 0.5) < 0.02, f"{half:.3f}")
    check("…said in the voice's words", any("Your voice's volume" in x["text"] for x in v.lines), str(v.lines))
    s.toggle(v.id, cat, mk)
    m = s.add({"kind": "direct", "text": "mute", "ops": [{"op": "edit_audio", "audio": sid, "mute": True}]}, cat, mk)
    x = mix()
    check("muted: no voice", energy(x, 660, 2.2, 3.3) < 0.01)
    check("…and no duck", abs(energy(x, 220, 2.4, 3.3) / full - 1) < 0.02, f"{energy(x, 220, 2.4, 3.3) / full:.3f}")
    s.toggle(m.id, cat, mk)
    mv = s.add({"kind": "direct", "text": "move", "ops": [{"op": "edit_audio", "audio": sid, "at": 0.5}]}, cat, mk)
    x = mix()
    check("moved 1.5 s earlier: sounds from 0.5 s", energy(x, 660, 0.7, 1.8) > 0.9 * loud and energy(x, 660, 0.0, 0.4) < 0.01)
    s.toggle(mv.id, cat, mk)
    d = s.add({"kind": "direct", "text": "del", "ops": [{"op": "drop_audio", "audio": sid}]}, cat, mk)
    check("deleted: gone", not s.board["sound"]["voice"] and energy(mix(), 660, 2.2, 3.3) < 0.01)
    s.toggle(d.id, cat, mk)
    check("undo brings it back", len(s.board["sound"]["voice"]) == 1 and energy(mix(), 660, 2.2, 3.3) > 0.9 * loud)

    print("refused")
    bad = s.add({"kind": "direct", "text": "bad", "ops": [{"op": "add_voice", "voice": "../../etc", "at": 0, "dur": 1}]}, cat, mk)
    check("a made-up file name is refused", bool(bad.skipped) and len(s.board["sound"]["voice"]) == 1, str(bad.skipped))
    try:
        mic.path_of("../x")
        check("path_of never leaves the voice folder", False)
    except mic.MicError:
        check("path_of never leaves the voice folder", True)

    print("through the API (what the Record button sends)")
    from fastapi.testclient import TestClient
    from web.backend import app as A
    from web.backend import projects as pj
    A.SESSION = s
    A.CATALOG["cat"] = cat
    A._make_proposals = mk
    A._session = lambda: {"turns": len(A.SESSION.turns)}
    A._save = lambda: None
    A.PROJECT["p"] = pj.Project(id="mic", name="Voice")
    c = TestClient(A.app)   # no lifespan: nothing opened from disk
    turns = len(s.turns)
    r = c.post("/api/voice?at=4.5", content=voice_webm(), headers={"content-type": "audio/webm;codecs=opus"})
    takes = s.board["sound"]["voice"]
    check("a take is one turn, on its own strip at 4.5 s", r.status_code == 200 and len(s.turns) == turns + 1
          and len(takes) == 2 and takes[-1]["at"] == 4.5 and abs(takes[-1]["dur"] - 3.5) < 0.05, r.text)
    check("…said in plain words", s.turns[-1].text == "You recorded your voice at 0:04", s.turns[-1].text)
    r = c.post("/api/voice?at=1", content=b"", headers={"content-type": "audio/webm"})
    check("nothing recorded: refused with the reason, no turn", r.status_code == 400 and "microphone" in r.json()["detail"]
          and len(s.turns) == turns + 1, r.text)

    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
