"""A cover for the finished video: one of its own frames, chosen by the creator.

Every platform shows a still before anyone presses play, and a platform's
own pick is often a blink or a blur. The cover is taken from the exported
file itself -- what the viewer will see, captions and look included, never
a generated image (CLAUDE.md non-goal) -- at a moment the edit gives
weight to: the hook, then the shots held longest (an editor holds what
matters). The creator picks one; it is saved as a JPEG beside the video,
ready for TikTok's or Instagram's "choose cover", and YouTube gets it with
the post (youtube.set_thumbnail).

Stills are read from the export with one ffmpeg seek each and cached; the
export is the only file touched.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .indexer import CACHE

CHOICES = 6             # stills offered [prior]
MIN_SHOT_S = 0.8        # a flash of a shot is no cover
THUMB_W = 270           # the picker's width; the saved cover is full size
MAX_BYTES = 2 * 1024 * 1024   # YouTube's custom thumbnail limit


def candidates(items: list[dict], n: int = CHOICES) -> list[float]:
    """Times (edit seconds) worth offering: the hook's middle, then the
    middles of the longest-held shots, in edit order."""
    shots = [it for it in items if it.get("kind") == "shot" and it["seq_end"] - it["seq_start"] >= MIN_SHOT_S]
    if not shots:
        shots = [it for it in items if it.get("kind") == "shot"]
    if not shots:
        return []
    mid = lambda it: round((it["seq_start"] + it["seq_end"]) / 2, 2)  # noqa: E731
    keep = [shots[0]] + sorted(shots[1:], key=lambda it: it["seq_end"] - it["seq_start"], reverse=True)[: n - 1]
    return sorted({mid(it) for it in keep})


def _dir(jid: str) -> Path:
    return CACHE / "covers" / jid


def still(video: str, jid: str, t: float, full: bool = False) -> Path:
    """The frame at t seconds of the export, as a JPEG (cached)."""
    ms = int(round(t * 1000))
    out = _dir(jid) / f"{ms}{'-full' if full else ''}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = [] if full else ["-vf", f"scale={THUMB_W}:-2"]
    qs = (2, 4, 8) if full else (4,)
    for q in qs:      # coarser until it fits YouTube's limit
        p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin", "-ss", f"{t:.3f}", "-i", video,
                            "-frames:v", "1", *vf, "-q:v", str(q), str(out)], capture_output=True, text=True, timeout=60)
        if p.returncode != 0 or not out.exists():
            raise ValueError("Couldn't read a frame there: " + (p.stderr.strip()[-160:] or "unknown error"))
        if out.stat().st_size <= MAX_BYTES or q == qs[-1]:
            break
    return out


def save(video: str, jid: str, t: float) -> Path:
    """The chosen cover, full size, beside the video: '<name> cover.jpg'."""
    src = still(video, jid, t, full=True)
    dest = Path(video).with_name(Path(video).stem + " cover.jpg")
    dest.write_bytes(src.read_bytes())
    return dest
