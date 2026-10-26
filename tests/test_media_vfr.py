"""A variable-frame-rate file must decode on the clock it was filmed on.

Phones write VFR: 60 fps while the camera moves, fewer when it doesn't.
load() once let ffmpeg pad such a file to its top rate while every stage
read time as index / average fps, so a 10 s clip measured as 16 s and its
cuts landed after the video had ended (taste reference S007). The fixture
has a hard cut every second, 60 fps for the first five and 15 fps after,
so a stretched clock shows up as cuts at the wrong seconds.

    python tests/test_media_vfr.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cutgrammar import media, shots  # noqa: E402

COLOURS = ["crimson", "navy", "gold", "seagreen", "white",
           "black", "orange", "purple", "gray", "cyan"]


def _ff(args: list[str]) -> None:
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[:400])


def build_vfr(d: str) -> str:
    """Ten 1 s colour shots at 60 fps, then every 4th frame dropped after 5 s."""
    inputs = []
    for c in COLOURS:
        inputs += ["-f", "lavfi", "-i", f"color=c={c}:size=320x180:rate=60:d=1"]
    labels = "".join(f"[{i}:v]" for i in range(len(COLOURS)))
    cfr = os.path.join(d, "cfr60.mp4")
    _ff([*inputs, "-filter_complex", f"{labels}concat=n={len(COLOURS)}:v=1:a=0[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", cfr])
    out = os.path.join(d, "vfr.mp4")
    _ff(["-i", cfr, "-vf", "select='lt(t,5)+not(mod(n,4))'", "-fps_mode", "vfr",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out])
    return out


def build_stall(d: str) -> str:
    """A steady 10 s 30 fps pan with 8 frames missing near the end: a phone's
    low-light stall, which pulls the average rate under the nominal one."""
    cfr = os.path.join(d, "pan.mp4")
    _ff(["-f", "lavfi", "-i",
         "nullsrc=s=320x180:r=30:d=10,geq=lum='128+90*sin((X+N*8)/40)*cos(Y/30)':cb=128:cr=128",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-crf", "12", cfr])
    out = os.path.join(d, "stall.mp4")
    _ff(["-i", cfr, "-vf", "select='not(between(n\\,270\\,277))'", "-fps_mode", "vfr",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-crf", "12", out])
    return out


def main() -> int:
    failures = []

    def check(name: str, cond: bool, got: str) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}: {got}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as d:
        print("building a variable-frame-rate fixture...")
        path = build_vfr(d)
        v = [s for s in media.probe(path)["streams"] if s.get("codec_type") == "video"][0]
        check("the fixture really is VFR",
              v.get("r_frame_rate") != v.get("avg_frame_rate"),
              f"r={v.get('r_frame_rate')} avg={v.get('avg_frame_rate')}")

        m = media.load(path)
        check("frames / fps covers the file's duration",
              abs(m.n_frames / m.fps - m.duration) < 2 / m.fps,
              f"{m.n_frames} frames / {m.fps:.2f} fps = {m.n_frames / m.fps:.2f} s "
              f"vs {m.duration:.2f} s")

        sh = shots.detect(m)
        check("every shot starts inside the video",
              all(s.start_t < m.duration for s in sh),
              f"last start {sh[-1].start_t:.2f} s of {m.duration:.2f} s")
        check("one shot per colour", len(sh) == len(COLOURS), f"{len(sh)} shots")
        cuts = [s.start_t for s in sh[1:]]
        # After 5 s the source only has a frame every 1/15 s, so a cut can
        # only be seen to that precision.
        worst = max((abs(t - round(t)) for t in cuts), default=99.0)
        check("cuts land on the whole seconds they were made at",
              len(cuts) == len(COLOURS) - 1 and worst < 0.1,
              ", ".join(f"{t:.2f}" for t in cuts))

        print("building a stalled 30 fps pan...")
        path = build_stall(d)
        m = media.load(path)
        check("a stall keeps the nominal rate",
              abs(m.fps - 30.0) < 0.01 and abs(m.n_frames / m.fps - 10.0) < 0.1,
              f"{m.n_frames} frames at {m.fps:.2f} fps")
        jumps = getattr(shots, "jump_cuts", lambda *a: [])(m, shots.detect(m))
        check("no frame dropped through the file reads as a jump cut",
              not jumps, f"jumps at {[round(m.t(i), 2) for i in jumps]}")

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
