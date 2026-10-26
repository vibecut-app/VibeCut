"""The clip tools next to Split: Duplicate, Freeze frame, Reverse, and the
music's Volume slider.

Each is built into one shot of an otherwise identical edit, and the
measurement must move the way it was built, and nowhere else:

- duplicate: the same span twice in a row, with its fixes, the edit longer
  by exactly the shot; a cut through either copy leaves the other alone;
- freeze frame: the frame under the playhead held for its length, cut in
  where it plays; the picture doesn't change over it and it is silent;
  dragging its end makes it longer without changing the frame;
- reverse: the picture runs backwards through the same span (export), the
  sound too (the mixer), the length unchanged; a cut and a trim on a
  reversed shot act on what plays first / last, not on source order;
- music volume: 50% halves the bed, 100% is as placed; undo restores it.

    python tests/test_clip_tools.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = Path(tempfile.mkdtemp(prefix="vibecut-cliptools-"))
os.environ["VIBECUT_CACHE"] = str(TMP / "cache")
os.environ["VIBECUT_EXPORTS"] = str(TMP / "out")

from web.backend import audiomix as am  # noqa: E402
from web.backend import board as bd  # noqa: E402
from web.backend import export  # noqa: E402
from web.backend import reverse  # noqa: E402
from web.backend import timeline  # noqa: E402

SR = am.SR
failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def level(x: np.ndarray, a: float, b: float) -> float:
    s = x[int(a * SR):int(b * SR), 0]
    return float(np.sqrt((s ** 2).mean())) if len(s) else 0.0


def shot(cid: str) -> dict:
    return {"id": cid, "name": f"{cid}.MOV", "capture_time": None, "gps": None, "duration": 8.0,
            "shots": [{"index": 0, "start": 0.0, "end": 8.0, "thumb": "shot000.jpg", "best_t": 4.0,
                       "quality": 0.6, "aesthetic": None, "utility": False, "labels": [["x", 0.8]],
                       "faces": 0, "face_area": 0.0, "embedding": [1.0] + [0.0] * 7}]}


def frame(path: Path, t: float) -> float:
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=32:18", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True, check=True)
    return float(np.frombuffer(p.stdout, np.uint8).mean())


def main() -> int:
    A, B = TMP / "a.mov", TMP / "b.mov"
    # A: brightness = 25 * source seconds, its sound gets louder through the clip
    ff("-f", "lavfi", "-i", "nullsrc=s=320x180:r=30:d=8,geq=lum='min(255,T*25+10)':cb=128:cr=128",
       "-f", "lavfi", "-i", "sine=f=440:d=8:sample_rate=48000,volume='t/8':eval=frame",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", str(A))
    ff("-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30:d=8", "-f", "lavfi",
       "-i", "sine=f=880:d=8:sample_rate=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       "-c:a", "pcm_s16le", "-shortest", str(B))
    clips = {"A": {"id": "A", "path": str(A), "duration": 8.0, "width": 320, "height": 180},
             "B": {"id": "B", "path": str(B), "duration": 8.0, "width": 320, "height": 180}}
    cat = bd.Catalog.from_clips([shot("A"), shot("B")])
    option = {"key": "o", "name": "Two", "summary": "", "beats": [{"title": "All", "detail": "", "shots": [
        {"id": "A:0", "start": 1.0, "end": 5.0}, {"id": "B:0", "start": 1.0, "end": 3.0}]}]}
    mk = lambda d: {"options": [option]}  # noqa: E731
    s = bd.Session()
    s.add({"kind": "chat", "text": "go", "ops": [], "direction": {"text": "go"}}, cat, mk)
    s.add({"kind": "direct", "text": "pick", "ops": [{"op": "choose_option", "option": "o"}]}, cat, mk)

    def items():
        return timeline.layout(s.board)

    def do(*ops):
        return s.add({"kind": "direct", "text": "t", "ops": list(ops)}, cat, mk)

    def undo(t):
        s.toggle(t.id, cat, mk)

    def render(i: int) -> Path:
        job = export.create(items(), clips, "t", None, want="wide")
        job.size = {"w": 320, "h": 180}
        out = TMP / f"shot{len(list(TMP.glob('shot*.mov')))}.mov"
        export._shot(job, job.items[i], out)
        return out

    print("duplicate")
    tg = do({"op": "set_shot", "shot": "A:0", "speed": 2})
    td = do({"op": "duplicate_shot", "shot": "A:0"})
    it = items()
    check("the copy plays right after the shot", [x["shot_id"] for x in it] == ["A:0", "A:0", "B:0"],
          str([x["key"] for x in it]))
    check("…same span, same fixes", (it[1]["src_start"], it[1]["src_end"], it[1].get("speed")) == (1.0, 5.0, 2))
    check("…its own key", it[0]["key"] != it[1]["key"], f"{it[0]['key']} / {it[1]['key']}")
    check("the edit is longer by the shot", abs(it[-1]["seq_end"] - 6.0) < 1e-3, f"{it[-1]['seq_end']:.3f}")
    check("the turn says it copied", any("Copied" in ln["text"] for ln in td.lines), str(td.lines))
    tc = do({"op": "split", "shot": it[1]["key"], "at": 3.0})
    it2 = items()
    check("a cut through the copy leaves the original whole",
          (it2[0]["src_start"], it2[0]["src_end"]) == (1.0, 5.0) and len(it2) == 4)
    undo(tc)
    undo(td)
    undo(tg)
    check("undo: one shot again", [x["shot_id"] for x in items()] == ["A:0", "B:0"])

    print("freeze frame")
    tf = do({"op": "freeze_frame", "shot": "A:0", "at": 3.0, "dur": 2.0})
    it = items()
    check("cut in where it plays: shot, held frame, rest of the shot",
          [(x["src_start"], x["src_end"], bool(x.get("freeze"))) for x in it[:3]]
          == [(1.0, 3.0, False), (3.0, 5.0, True), (3.0, 5.0, False)],
          str([(x["src_start"], x["src_end"], x.get("freeze")) for x in it[:3]]))
    check("the edit is longer by the hold", abs(it[-1]["seq_end"] - 8.0) < 1e-3, f"{it[-1]['seq_end']:.3f}")
    check("the turn says it held a frame", any("Held a frame" in ln["text"] for ln in tf.lines), str(tf.lines))
    held = render(1)
    f0, f1 = frame(held, 0.1), frame(held, 1.8)
    check("the picture doesn't change over it", abs(f0 - f1) < 2, f"{f0:.0f} -> {f1:.0f}")
    check("…and it is the frame at 3 s", abs(f0 - (3 * 25 + 10)) < 8, f"{f0:.0f}, expected ~85")
    x = am.render(items(), clips)[0]
    check("it is silent", level(x, 2.1, 3.9) < 0.002 and level(x, 4.2, 5.8) > 0.01,
          f"held {level(x, 2.1, 3.9):.4f}, after {level(x, 4.2, 5.8):.3f}")
    tt = do({"op": "trim", "shot": it[1]["key"], "edge": "out", "to": 6.0})
    it3 = items()
    check("dragging its end makes it longer, same frame",
          abs((it3[1]["seq_end"] - it3[1]["seq_start"]) - 3.0) < 1e-3 and it3[1]["src_start"] == 3.0,
          f"{it3[1]['seq_end'] - it3[1]['seq_start']:.3f}s from {it3[1]['src_start']}")
    undo(tt)
    tb = do({"op": "freeze_frame", "shot": it[2]["key"], "at": 3.0})
    check("at the moment a shot starts, the hold goes before it", items()[2].get("freeze")
          and abs(items()[2]["seq_end"] - items()[2]["seq_start"] - bd.FREEZE_S) < 1e-3)
    undo(tb)
    undo(tf)

    print("reverse")
    fwd = render(0)
    tr = do({"op": "set_shot", "shot": "A:0", "reverse": True})
    it = items()
    check("same length in the edit", abs(it[0]["seq_end"] - 4.0) < 1e-3 and it[0].get("reverse") is True)
    check("the turn says backwards", any("backwards" in ln["text"] for ln in tr.lines), str(tr.lines))
    back = render(0)
    pairs = [(frame(back, t), frame(fwd, 4.0 - 1 / 30 - t)) for t in (0.2, 1.5, 2.5, 3.7)]
    check("export: frame t of the reversed shot is frame (end - t) of the plain one",
          all(abs(a - b) < 3 for a, b in pairs) and pairs[0][0] - pairs[-1][0] > 60,
          ", ".join(f"{a:.0f}/{b:.0f}" for a, b in pairs))
    x = am.render(items(), clips)[0]
    check("the sound runs backwards too: loud first, quiet last", level(x, 0.1, 0.6) > 1.5 * level(x, 3.3, 3.8),
          f"{level(x, 0.1, 0.6):.3f} -> {level(x, 3.3, 3.8):.3f}")
    p = reverse.reversed_span(str(A), 1.0, 5.0, 180)
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", str(p)], capture_output=True,
                           text=True).stdout.strip())
    check("the reversed copy is exactly the span's frames", n == 120, f"{n} frames")
    check("…the preview's copy and export's come from one function, cached", reverse.reversed_span(str(A), 1.0, 5.0, 180) == p)
    ts = do({"op": "split", "shot": "A:0", "at": 4.0})
    it = items()
    check("a cut at 4 s of source: the first piece is what plays first (4–5 s)",
          (it[0]["src_start"], it[0]["src_end"], it[1]["src_start"], it[1]["src_end"]) == (4.0, 5.0, 1.0, 4.0),
          str([(x["src_start"], x["src_end"]) for x in it[:2]]))
    undo(ts)
    tin = do({"op": "trim", "shot": "A:0", "edge": "in", "to": 4.5})
    check("trimming its start (what plays first) moves the source end",
          (items()[0]["src_start"], items()[0]["src_end"]) == (1.0, 4.5), str((items()[0]["src_start"], items()[0]["src_end"])))
    undo(tin)
    tdr = do({"op": "drop_range", "from_shot": "A:0", "from_at": 4.0, "to_shot": "A:0", "to_at": 3.0})
    it = items()
    check("removing 1 s inside it (played 1–2 s) leaves 3 s, the right pieces",
          abs(it[-1]["seq_end"] - 5.0) < 1e-3 and [(x["src_start"], x["src_end"]) for x in it[:2]] == [(4.0, 5.0), (1.0, 3.0)],
          str([(x["src_start"], x["src_end"]) for x in it[:2]]))
    undo(tdr)
    undo(tr)

    print("music volume")
    tm = do({"op": "set_music", "track": "t1", "in": 0.0, "gain": 0.4, "original": 1.0})
    spec = export.music_spec("x.wav", s.board.get("music"))
    tv = do({"op": "set_music", **s.board["music"], "volume": 0.5})
    spec2 = export.music_spec("x.wav", s.board.get("music"))
    check("50% halves the bed", abs(spec2["gain"] - spec["gain"] / 2) < 1e-6, f"{spec['gain']} -> {spec2['gain']}")
    check("the turn names the volume", any("Music volume 100% → 50%" in ln["text"] for ln in tv.lines), str(tv.lines))
    tv1 = do({"op": "set_music", **s.board["music"], "volume": 1.0})
    check("100% is as placed (nothing stored)", "volume" not in s.board["music"])
    undo(tv1)
    undo(tv)
    check("undo restores it", export.music_spec("x.wav", s.board.get("music"))["gain"] == spec["gain"])
    undo(tm)

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
