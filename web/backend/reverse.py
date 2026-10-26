"""A span of a clip, played backwards, as a file of its own.

Browsers can't play video backwards and ffmpeg's `reverse` filter holds
every frame of what it reverses in memory (a 10 s span of 4K is gigabytes).
So the span is reversed in short pieces, each piece small enough to hold,
and the pieces are joined last-first. The preview gets a small copy
(`PREVIEW_H`), export one at its own size; both come from this one function,
so they show the same frames. Cached by file, span and height.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from . import indexer

FPS = 30
PIECE_S = 2.0       # seconds reversed at a time: bounded memory whatever the span
PREVIEW_H = 540
DIR = indexer.CACHE / "reversed"
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _encoder(rate: str) -> list[str]:
    from . import export
    return [x.replace("{rate}", rate).replace("{crf}", "16") for x in export._encoder()]


def path_for(src: str, a: float, b: float, height: int) -> Path:
    st = Path(src).stat()
    k = hashlib.sha1(f"{src}|{st.st_size}|{st.st_mtime_ns}|{a:.3f}|{b:.3f}|{height}".encode()).hexdigest()[:20]
    return DIR / f"{k}.mp4"


def reversed_span(src: str, a: float, b: float, height: int = PREVIEW_H) -> Path:
    """Source seconds [a, b) of `src`, backwards, at `height` pixels tall
    (never taller than filmed), 30 fps, no sound (the mixer reverses that)."""
    if b - a < 1 / FPS:
        raise ValueError("nothing to reverse")
    out = path_for(src, a, b, height)
    if out.exists():
        return out
    with _guard:
        lock = _locks.setdefault(str(out), threading.Lock())
    with lock:
        if out.exists():
            return out
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=DIR))
        try:
            pieces, t = [], a
            while t < b - 1e-6:
                pieces.append((t, min(b, t + PIECE_S)))
                t += PIECE_S
            names = []
            for n, (p0, p1) in enumerate(reversed(pieces)):
                f = tmp / f"{n:04d}.mp4"
                # frames counted, not timed, so the joined file is exactly the span
                frames = max(1, round((p1 - p0) * FPS))
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin",
                     "-ss", f"{p0:.4f}", "-t", f"{p1 - p0 + 0.2:.4f}", "-i", src,
                     "-an", "-vf", f"fps={FPS},trim=end_frame={frames},setpts=PTS-STARTPTS,"
                     f"scale=-2:'min(ih,{height})',reverse,format=yuv420p",
                     *_encoder("16M" if height > 720 else "6M"), str(f)],
                    check=True, capture_output=True)
                names.append(f)
            (tmp / "list.txt").write_text("".join(f"file '{f.name}'\n" for f in names))
            joined = tmp / "joined.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin", "-f", "concat",
                            "-safe", "0", "-i", str(tmp / "list.txt"), "-c", "copy", "-movflags", "+faststart",
                            str(joined)], check=True, capture_output=True)
            joined.replace(out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return out
