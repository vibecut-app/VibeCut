"""Colour adjust (Brightness / Contrast / Saturation) and Stabilise on a shot.

Each is built into one shot of an otherwise identical edit, and the
measurement must move by the amount that was built in:

- the three sliders, rendered by export's ffmpeg filters, give the same
  colours as the browser's CSS sums (tone.apply, tone.ts) on known colours;
- an exported shot at brightness +50 is 1.2x as light, at saturation -100
  has no colour left, and the same shot as filmed is untouched;
- a clip with a hand's shake on a slow pan, held steady: the shake drops to
  under a third, the pan the camera meant is kept, a stronger setting holds
  it stiller, and the export of a steadied shot shakes less than the plain one;
- the board: values clamp, a value back at 0 leaves the entry plain, a cut
  keeps them, a held frame keeps the colour but can't be steadied, undo
  takes them off, and the turn says what changed.

    python tests/test_adjust.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = Path(tempfile.mkdtemp(prefix="vibecut-adjust-"))
os.environ["VIBECUT_CACHE"] = str(TMP / "cache")
os.environ["VIBECUT_EXPORTS"] = str(TMP / "out")

from web.backend import board as bd  # noqa: E402
from web.backend import export  # noqa: E402
from web.backend import stable  # noqa: E402
from web.backend import timeline  # noqa: E402
from web.backend import tone  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def ff(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-y", *args], input=data, check=True, capture_output=True).stdout


def frames(path: Path, w: int, h: int, fmt: str = "gray") -> np.ndarray:
    raw = ff("-i", str(path), "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", fmt, "-")
    ch = 3 if fmt == "rgb24" else 1
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, ch).astype(float)


def shot(cid: str, dur: float) -> dict:
    return {"id": cid, "name": f"{cid}.MOV", "capture_time": None, "gps": None, "duration": dur,
            "shots": [{"index": 0, "start": 0.0, "end": dur, "thumb": "shot000.jpg", "best_t": dur / 2,
                       "quality": 0.6, "aesthetic": None, "utility": False, "labels": [["x", 0.8]],
                       "faces": 0, "face_area": 0.0, "embedding": [1.0] + [0.0] * 7}]}


# --------------------------------------------------------------------------
# shake: where the picture sits, frame by frame

def shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    """How far `a` is moved against `b`, in whole pixels (phase correlation)."""
    A, B = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = A * np.conj(B)
    r = np.fft.ifft2(r / (np.abs(r) + 1e-9)).real
    y, x = np.unravel_index(np.argmax(r), r.shape)
    h, w = r.shape
    return (x if x < w // 2 else x - w), (y if y < h // 2 else y - h)


def shake(path: Path, w: int, h: int) -> tuple[float, float]:
    """(shake, travel): how far the picture strays, frame to frame, from a
    smooth path through where it sits, and how far that path goes across."""
    g = frames(path, w, h)[..., 0]
    g = g[:, h // 9:-h // 9, w // 10:-w // 10]   # the middle: a steadied frame is zoomed in
    ref = g[len(g) // 2]
    pos = np.array([shift(f, ref) for f in g], float)
    t = np.arange(len(g))
    resid = [np.abs(pos[:, k] - np.polyval(np.polyfit(t, pos[:, k], 2), t)).mean() for k in range(2)]
    return float(np.mean(resid)), float(abs(pos[-1, 0] - pos[0, 0]))


def shaky_clip(path: Path, w: int = 640, h: int = 360, n: int = 150) -> None:
    """A textured wall filmed on a slow pan (44 px across) by a shaking hand (6 px)."""
    rng = np.random.default_rng(3)
    tex = np.kron(rng.random((h // 8 + 20, w // 8 + 20)), np.ones((8, 8)))
    tex = (tex * 200 + 30).astype(np.uint8)
    jx, jy, pan = rng.normal(0, 6, n), rng.normal(0, 6, n), np.linspace(0, 40, n)
    out = []
    for i in range(n):
        x, y = int(round(60 + pan[i] + jx[i])), int(round(60 + jy[i]))
        f = tex[y:y + h, x:x + w]
        out.append(np.stack([f, f, f], -1))
    ff("-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
       "-f", "lavfi", "-i", f"sine=f=440:d={n / 30}:sample_rate=48000",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", "-c:a", "pcm_s16le", "-shortest", str(path),
       data=np.stack(out).tobytes())


def main() -> int:
    print("the three sliders: export's filters are the browser's sums")
    cols = np.array([[[40, 90, 200], [200, 120, 60], [128, 128, 128], [250, 250, 250]]], np.uint8)
    img = np.kron(cols, np.ones((16, 16, 1), np.uint8))
    H, W = img.shape[:2]
    for e in ({"brightness": 0.5}, {"contrast": 0.6}, {"saturation": -1},
              {"saturation": 0.8, "brightness": -0.4, "contrast": -0.5}):
        raw = ff("-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-i", "-",
                 "-vf", tone.chain(e) + "format=rgb24", "-f", "rawvideo", "-pix_fmt", "rgb24", "-", data=img.tobytes())
        got = np.frombuffer(raw, np.uint8).reshape(H, W, 3)[8, 8::16].astype(int)
        want = tone.apply(cols[0], e).round().astype(int)
        check(f"{e}", int(np.abs(got - want).max()) <= 1, f"ffmpeg {got.tolist()} vs sums {want.tolist()}")
    check("as filmed: no filters at all", tone.chain({}) == "" and tone.chain({"brightness": 0}) == "")

    print("the board")
    A, S = TMP / "a.mov", TMP / "shaky.mp4"
    # A: a colourful still (orange left, blue right), 8 s, with sound
    ff("-f", "lavfi", "-i", "color=c=0xd2783c:s=160x180:r=30:d=8", "-f", "lavfi", "-i", "color=c=0x3c5ad2:s=160x180:r=30:d=8",
       "-f", "lavfi", "-i", "sine=f=440:d=8:sample_rate=48000", "-filter_complex", "[0][1]hstack,format=yuv420p[v]",
       "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-crf", "12", "-c:a", "pcm_s16le", "-shortest", str(A))
    shaky_clip(S)
    clips = {"A": {"id": "A", "path": str(A), "duration": 8.0, "width": 320, "height": 180},
             "S": {"id": "S", "path": str(S), "duration": 5.0, "width": 640, "height": 360}}
    cat = bd.Catalog.from_clips([shot("A", 8.0), shot("S", 5.0)])
    option = {"key": "o", "name": "Two", "summary": "", "beats": [{"title": "All", "detail": "", "shots": [
        {"id": "A:0", "start": 1.0, "end": 5.0}, {"id": "S:0", "start": 1.0, "end": 4.0}]}]}
    mk = lambda d: {"options": [option]}  # noqa: E731
    s = bd.Session()
    s.add({"kind": "chat", "text": "go", "ops": [], "direction": {"text": "go"}}, cat, mk)
    s.add({"kind": "direct", "text": "pick", "ops": [{"op": "choose_option", "option": "o"}]}, cat, mk)

    def entry(k: str = "A:0") -> dict:
        return next(e for bt in s.board["beats"] for e in bt["shots"] if bd.key(e) == k)

    def fix(k: str = "A:0", **kw):
        return s.add({"kind": "direct", "text": "fix", "ops": [{"op": "set_shot", "shot": k, **kw}]}, cat, mk)

    t = fix(brightness=3, contrast=-0.25, saturation=0.5)
    e = entry()
    check("values clamp to -1..1", e["brightness"] == 1.0 and e["contrast"] == -0.25 and e["saturation"] == 0.5, str(e))
    check("the turn says what changed", any("brightness +100" in ln["text"] for ln in t.lines)
          and any("colour +50" in ln["text"] for ln in t.lines), str([ln["text"] for ln in t.lines]))
    check("…and the timeline carries them to the player and export",
          timeline.layout(s.board)[0].get("contrast") == -0.25)
    fix(brightness=0)
    check("a slider back at 0 leaves the field off the entry", "brightness" not in entry() and "contrast" in entry())
    s.add({"kind": "direct", "text": "cut", "ops": [{"op": "split", "shot": "A:0", "at": 3.0}]}, cat, mk)
    second = timeline.layout(s.board)[1]
    check("a cut keeps the colour on both pieces", second.get("saturation") == 0.5 and entry().get("saturation") == 0.5)
    s.toggle(s.turns[-1].id, cat, mk)
    s.add({"kind": "direct", "text": "hold", "ops": [{"op": "freeze_frame", "shot": "A:0", "at": 2.0}]}, cat, mk)
    held = next(it for it in timeline.layout(s.board) if it.get("freeze"))
    check("a held frame keeps the shot's colour", held.get("saturation") == 0.5 and held.get("contrast") == -0.25)
    tf = fix(held["key"], stabilize=0.5)
    check("a held frame can't be steadied (the turn says why)", any("steady" in x for x in tf.skipped)
          and "stabilize" not in entry(held["key"]), str(tf.skipped))
    for turn in reversed(s.turns[2:]):
        if not turn.undone:
            s.toggle(turn.id, cat, mk)
    check("undo takes them all off", not any(f in entry() for f in tone.FIELDS))
    tst = fix("S:0", stabilize=1.7)
    check("stabilise clamps to 0..1 and says so", entry("S:0")["stabilize"] == 1.0
          and any("steady" in ln["text"] for ln in tst.lines), str([ln["text"] for ln in tst.lines]))
    s.toggle(tst.id, cat, mk)

    print("export: brightness and saturation, measured on the file")
    def render(k: int, **kw) -> Path:
        t = fix(bd.key(timeline.layout(s.board)[k]), **kw) if kw else None
        job = export.create(timeline.layout(s.board), clips, "t", None, want="wide")
        job.size = {"w": 320, "h": 180}
        out = TMP / f"shot{len(list(TMP.glob('shot*.mov')))}.mov"
        export._shot(job, job.items[k], out)
        if t:
            s.toggle(t.id, cat, mk)
        return out
    plain = frames(render(0), 32, 18, "rgb24")[15]
    bright = frames(render(0, brightness=0.5), 32, 18, "rgb24")[15]
    grey = frames(render(0, saturation=-1), 32, 18, "rgb24")[15]
    ratio = bright[4:14, 2:14].mean() / plain[4:14, 2:14].mean()
    check("brightness +50: 1.2x as light", abs(ratio - 1.2) < 0.04, f"x{ratio:.3f}")
    chroma = lambda f: float((f.max(-1) - f.min(-1))[4:14].mean())  # noqa: E731
    check("saturation -100: black and white", chroma(grey) < 6 < 60 < chroma(plain),
          f"colour {chroma(plain):.0f} -> {chroma(grey):.0f}")
    check("…as filmed, the export is the clip's own colour", abs(plain[9, 4] - [210, 120, 60]).max() < 12, str(plain[9, 4]))

    print("stabilise: a shaky clip held steady")
    raw_shake, raw_pan = shake(S, 640, 360)
    f0, strong = stable.steady_span(str(S), 1.0, 4.0, 1.0, 360)
    _, light = stable.steady_span(str(S), 1.0, 4.0, 0.3, 360)
    (s_shake, s_pan), (l_shake, l_pan) = shake(strong, 640, 360), shake(light, 640, 360)
    check("the steady file runs 1.5 s either side of the span (to the clip's ends)", f0 == 0.0
          and abs(len(frames(strong, 16, 9)) - 150) <= 1, f"starts at {f0}, {len(frames(strong, 16, 9))} frames")
    check("the shake drops to under a third", s_shake < raw_shake / 3 and l_shake < raw_shake / 3,
          f"{raw_shake:.2f} px -> {l_shake:.2f} (30%), {s_shake:.2f} (100%)")
    check("stronger holds it stiller", s_shake <= l_shake, f"{l_shake:.2f} -> {s_shake:.2f}")
    check("the pan the camera meant is kept", abs(s_pan - raw_pan) < 0.25 * raw_pan and abs(l_pan - raw_pan) < 0.25 * raw_pan,
          f"{raw_pan:.0f} px -> {l_pan:.0f}, {s_pan:.0f}")
    check("made once, then cached", stable.steady_span(str(S), 1.0, 4.0, 1.0, 360) == (f0, strong))
    back = stable.steady_reversed(str(S), 1.0, 4.0, 1.0, 360)
    fwd, rev = frames(strong, 64, 36)[..., 0], frames(back, 64, 36)[..., 0]
    check("backwards: the steady span's frames, last first", len(rev) == 90
          and np.abs(rev[10] - fwd[30 + 89 - 10]).mean() < 6, f"{len(rev)} frames")
    plain_s = TMP / "plain_s.mov"
    job = export.create(timeline.layout(s.board), clips, "t", None, want="wide")
    job.size = {"w": 640, "h": 360}
    export._shot(job, job.items[1], plain_s)
    t = fix("S:0", stabilize=0.7)
    job = export.create(timeline.layout(s.board), clips, "t", None, want="wide")
    job.size = {"w": 640, "h": 360}
    steady_s = TMP / "steady_s.mov"
    export._shot(job, job.items[1], steady_s)
    s.toggle(t.id, cat, mk)
    e_plain, e_steady = shake(plain_s, 640, 360)[0], shake(steady_s, 640, 360)[0]
    n = len(frames(steady_s, 16, 9))
    check("export: the steadied shot shakes less, same length", e_steady < e_plain / 3 and n == len(frames(plain_s, 16, 9)),
          f"{e_plain:.2f} -> {e_steady:.2f} px, {n} frames")

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
