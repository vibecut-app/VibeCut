"""A span of a clip held steady, as a file of its own (Stabilise, the Edit tab).

Handheld phone footage shakes, and a shake is the first thing that reads
as amateur: the picture jitters while the eye wants it still. The fix
every editor has is the same two passes (iMovie's "Stabilize shaky video",
CapCut's Stabilize): find how the camera moved frame to frame
(vidstabdetect), smooth that path, and move each frame against the
difference (vidstabtransform), zoomed in just enough that the moved edges
never show. Only frames the creator filmed are shown, moved and cropped.

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

from . import indexer

FPS = 30
PREVIEW_H = 540
PAD = 1.5           # seconds of steady footage past each end of the span: a dissolve's handles
SMOOTH_S = (0.25, 1.5)   # seconds of the camera's path smoothed each side, at the slider's ends [prior]
SHAKINESS = 8       # vidstabdetect: phone footage walks and turns
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
    k = hashlib.sha1(f"{src}|{st.st_size}|{st.st_mtime_ns}|{a:.3f}|{b:.3f}|{clamp(strength):.2f}|{height}"
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
            # both passes see exactly the same frames at the same size, so the
            # moves found in the first are the moves undone in the second
            pre = (f"fps={FPS},trim=end_frame={frames},setpts=PTS-STARTPTS,"
                   f"scale=-2:'min(ih,{height})'")
            inp = ["-ss", f"{f0:.4f}", "-t", f"{end - f0 + 0.2:.4f}", "-i", src, "-an"]
            trf = tmp / "moves.trf"
            _ff([*inp, "-vf", f"{pre},vidstabdetect=shakiness={SHAKINESS}:accuracy=15"
                 f":result='{trf}'", "-f", "null", "-"])
            made = tmp / "steady.mp4"
            _ff([*inp, "-vf", f"{pre},vidstabtransform=input='{trf}':smoothing={smoothing(strength)}"
                 ":optzoom=1:interpol=bicubic,unsharp=5:5:0.6:3:3:0.3,format=yuv420p",
                 *_encoder("16M" if height > 720 else "6M"), "-movflags", "+faststart", str(made)])
            made.replace(out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return f0, out


def steady_reversed(src: str, a: float, b: float, strength: float, height: int = PREVIEW_H) -> Path:
    """The span held steady, then played backwards: exactly [a, b), like reverse.py's."""
    from . import reverse
    f0, steady = steady_span(src, a, b, strength, height)
    return reverse.reversed_span(str(steady), a - f0, b - f0, height)
