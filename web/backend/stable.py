"""A span of a clip held steady, as a file of its own (Stabilise, the Edit tab).

Handheld phone footage shakes, and a shake is the first thing that reads
as amateur: the picture jitters while the eye wants it still. The fix
every editor has is the same two passes (iMovie's "Stabilize shaky video",
CapCut's Stabilize): find how the camera moved frame to frame
(vidstabdetect), smooth that path, and move each frame against the
difference (vidstabtransform), zoomed in just enough that the moved edges
never show. Only frames the creator filmed are shown, moved and cropped.
An ffmpeg built without vid.stab (Homebrew's is slim) gets the same idea
in numpy: the picture's shift frame to frame by phase correlation, the
path smoothed, each frame's window moved against the difference; it
follows sideways and up-down moves only, not a tilt.

The strength (0..1 on the shot) is how long a stretch of the camera's path
is smoothed: a little irons out a trembling hand and keeps a walk's sway; all
the way holds the frame almost still and crops a little more.

The span is made with `PAD` seconds either side, so a dissolve still has
footage past the cut. The preview gets a small copy (`PREVIEW_H`), export
one at its own size, both from this one function. Cached by file, span,
strength and height. Backwards is the steady file reversed (reverse.py).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np

from . import indexer

FPS = 30
PREVIEW_H = 540
PAD = 1.5           # seconds of steady footage past each end of the span: a dissolve's handles
SMOOTH_S = (0.25, 1.5)   # seconds of the camera's path smoothed each side, at the slider's ends [prior]
SHAKINESS = 8       # vidstabdetect: phone footage walks and turns
ANALYSE = 320       # numpy path: the long side the camera's path is read at
MAX_ZOOM = 1.2      # numpy path: never crop in more than this to hide the edges [prior]
DIR = indexer.CACHE / "steady"
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def clamp(v) -> float:
    return round(max(0.0, min(1.0, float(v))), 2)


def base(a: float) -> float:
    """Source time at the steady file's 0 (the player computes the same)."""
    return max(0.0, round(a - PAD, 3))


def smoothing(strength: float) -> int:
    """vidstabtransform's smoothing: frames each side of the moment."""
    s = clamp(strength)
    return max(1, round((SMOOTH_S[0] + (SMOOTH_S[1] - SMOOTH_S[0]) * s) * FPS))


def _encoder(rate: str) -> list[str]:
    from . import export
    return [x.replace("{rate}", rate).replace("{crf}", "16") for x in export._encoder()]


def path_for(src: str, a: float, b: float, strength: float, height: int) -> Path:
    st = Path(src).stat()
    how = "vidstab" if has_vidstab() else "numpy"   # a newer ffmpeg makes them anew, the better way
    k = hashlib.sha1(f"{src}|{st.st_size}|{st.st_mtime_ns}|{a:.3f}|{b:.3f}|{clamp(strength):.2f}|{height}|{how}"
                     .encode()).hexdigest()[:20]
    return DIR / f"{k}.mp4"


def _duration(src: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _ff(args: list[str]) -> None:
    """ffmpeg, decoding on the Mac's hardware when it will (4K HEVC twice over)."""
    head = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin"]
    if sys.platform == "darwin":
        try:
            subprocess.run([*head, "-hwaccel", "videotoolbox", *args], check=True, capture_output=True)
            return
        except subprocess.CalledProcessError:
            pass   # a codec the hardware decoder won't take
    subprocess.run([*head, *args], check=True, capture_output=True)


_vidstab: bool | None = None


def has_vidstab() -> bool:
    global _vidstab
    if _vidstab is None:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
        _vidstab = "vidstabtransform" in r.stdout
    return _vidstab


def steady_span(src: str, a: float, b: float, strength: float, height: int = PREVIEW_H) -> tuple[float, Path]:
    """Source seconds [a, b) of `src`, held steady, with up to PAD seconds
    either side, at `height` pixels tall (never taller than filmed), 30 fps,
    no sound (the mixer plays the clip's own). Returns (source time at the
    file's 0, the file)."""
    if b - a < 1 / FPS:
        raise ValueError("nothing to hold steady")
    f0 = base(a)
    end = b + PAD
    dur = _duration(src)
    if dur:
        end = min(end, dur)
    out = path_for(src, a, b, strength, height)
    if out.exists():
        return f0, out
    with _guard:
        lock = _locks.setdefault(str(out), threading.Lock())
    with lock:
        if out.exists():
            return f0, out
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=DIR))
        try:
            frames = max(1, round((end - f0) * FPS))
            inp = ["-ss", f"{f0:.4f}", "-t", f"{end - f0 + 0.2:.4f}", "-i", src, "-an"]
            made = tmp / "steady.mp4"
            enc = [*_encoder("16M" if height > 720 else "6M"), "-movflags", "+faststart", str(made)]
            if has_vidstab():
                # both passes see exactly the same frames at the same size, so the
                # moves found in the first are the moves undone in the second
                pre = (f"fps={FPS},trim=end_frame={frames},setpts=PTS-STARTPTS,"
                       f"scale=-2:'min(ih,{height})'")
                trf = tmp / "moves.trf"
                _ff([*inp, "-vf", f"{pre},vidstabdetect=shakiness={SHAKINESS}:accuracy=15"
                     f":result='{trf}'", "-f", "null", "-"])
                _ff([*inp, "-vf", f"{pre},vidstabtransform=input='{trf}':smoothing={smoothing(strength)}"
                     ":optzoom=1:interpol=bicubic,unsharp=5:5:0.6:3:3:0.3,format=yuv420p", *enc])
            else:
                _numpy_steady(src, inp, frames, strength, height, enc)
            made.replace(out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return f0, out


# --------------------------------------------------------------------------
# without vid.stab: the same two passes in numpy

def _size(src: str, height: int) -> tuple[int, int]:
    """The picture as decoded (turned upright) at `height` tall, never taller than filmed."""
    from . import export
    d = export._display(src)
    h = min(d["h"], height)
    return max(2, round(d["w"] * h / d["h"] / 2) * 2), max(2, h // 2 * 2)


def _decode(inp: list[str], vf: str, w: int, h: int, ch: int):
    """Frames of the span as uint8 arrays (h, w, ch), one at a time, decoded
    on the Mac's hardware when it will."""
    fmt = "gray" if ch == 1 else "rgb24"
    heads = [["-hwaccel", "videotoolbox"], []] if sys.platform == "darwin" else [[]]
    n = w * h * ch
    for k, hw in enumerate(heads):
        p = subprocess.Popen(["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", *hw, *inp, "-vf", vf,
                              "-f", "rawvideo", "-pix_fmt", fmt, "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        got = 0
        try:
            while True:
                buf = p.stdout.read(n)
                if len(buf) < n:
                    break
                got += 1
                yield np.frombuffer(buf, np.uint8).reshape(h, w, ch)
        finally:
            p.stdout.close()
            p.wait()
        if got or k == len(heads) - 1:
            if not got:
                raise ValueError("couldn't read that shot")
            return


def _shift(a: np.ndarray, b: np.ndarray, win: np.ndarray) -> tuple[float, float]:
    """How far the picture in `a` is moved against `b` (x, y), to a tenth of
    a pixel: phase correlation, its peak refined on a parabola."""
    A, B = np.fft.rfft2((a - a.mean()) * win), np.fft.rfft2((b - b.mean()) * win)
    r = A * np.conj(B)
    r = np.fft.irfft2(r / (np.abs(r) + 1e-9), s=a.shape)
    y, x = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = r.shape

    def peak(c0: float, cm: float, cp: float) -> float:
        d = cm - 2 * c0 + cp
        return 0.0 if abs(d) < 1e-12 else max(-0.5, min(0.5, 0.5 * (cm - cp) / d))

    dx = x + peak(r[y, x], r[y, (x - 1) % w], r[y, (x + 1) % w])
    dy = y + peak(r[y, x], r[(y - 1) % h, x], r[(y + 1) % h, x])
    return (dx if dx < w / 2 else dx - w), (dy if dy < h / 2 else dy - h)


def _smooth(path: np.ndarray, frames_each_side: int) -> np.ndarray:
    """The camera's path as it was meant: a Gaussian over the moment's neighbours."""
    sd = max(1.0, frames_each_side / 2)
    k = np.exp(-0.5 * (np.arange(-3 * int(sd), 3 * int(sd) + 1) / sd) ** 2)
    k /= k.sum()
    pad = len(k) // 2
    out = np.empty_like(path)
    for j in range(path.shape[1]):
        out[:, j] = np.convolve(np.pad(path[:, j], pad, mode="edge"), k, mode="valid")
    return out


def _numpy_steady(src: str, inp: list[str], frames: int, strength: float, height: int, enc: list[str]) -> None:
    pre = f"fps={FPS},trim=end_frame={frames},setpts=PTS-STARTPTS"
    W, H = _size(src, height)
    s = ANALYSE / max(W, H)
    aw, ah = max(16, round(W * s / 2) * 2), max(16, round(H * s / 2) * 2)
    win = np.outer(np.hanning(ah), np.hanning(aw))
    # where the picture sits, frame by frame, as a share of the frame
    pos, prev = [np.zeros(2)], None
    for g in _decode(inp, f"{pre},scale={aw}:{ah}", aw, ah, 1):
        g = g[..., 0].astype(np.float32)
        if prev is not None:
            dx, dy = _shift(g, prev, win)
            pos.append(pos[-1] + (dx / aw, dy / ah))
        prev = g
    path = np.array(pos)
    off = path - _smooth(path, smoothing(strength))     # where each frame's window goes
    margin = (1 - 1 / MAX_ZOOM) / 2
    need = float(np.abs(off).max()) if len(off) else 0.0
    zoom = 1 / (1 - 2 * min(need, margin)) if need else 1.0
    room = (1 - 1 / zoom) / 2
    off = np.clip(off, -room, room)
    cw, chh = max(2, round(W / zoom / 2) * 2), max(2, round(H / zoom / 2) * 2)
    out = subprocess.Popen(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin", "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-s", f"{cw}x{chh}", "-r", str(FPS), "-i", "-",
                            "-vf", f"scale={W}:{H}:flags=bicubic,unsharp=5:5:0.6:3:3:0.3,format=yuv420p", *enc],
                           stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i, f in enumerate(_decode(inp, f"{pre},scale={W}:{H}", W, H, 3)):
            ox, oy = off[min(i, len(off) - 1)]
            x = int(round((W - cw) / 2 + ox * W))
            y = int(round((H - chh) / 2 + oy * H))
            x, y = max(0, min(W - cw, x)), max(0, min(H - chh, y))
            out.stdin.write(np.ascontiguousarray(f[y:y + chh, x:x + cw]).tobytes())
        out.stdin.close()
    except BrokenPipeError:
        pass
    err = out.stderr.read().decode(errors="replace")
    if out.wait() != 0:
        raise ValueError(f"couldn't steady that shot: {err.strip()[-200:]}")


def steady_reversed(src: str, a: float, b: float, strength: float, height: int = PREVIEW_H) -> Path:
    """The span held steady, then played backwards: exactly [a, b), like reverse.py's."""
    from . import reverse
    f0, steady = steady_span(src, a, b, strength, height)
    return reverse.reversed_span(str(steady), a - f0, b - f0, height)
