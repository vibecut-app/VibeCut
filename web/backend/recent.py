"""Your recent videos: what Home shows under the drop box.

A return visit should open on what was made, not on the same empty box as
the first: each video as its own picture, its length, and two ways on,
Open and Share. The picture of an exported video is a frame of the
export itself (captions and look included, the chosen cover's moment when
there is one, as covers.py), so the card looks like what was posted;
before it's exported, the edit's first shot (projects.snapshot_of).

Share hands on the file that was exported, so it needs one that is still
where it was saved. Export jobs live in memory, so an export from an
earlier run of the app is taken up again from its record (`revive`): the
file, its frame and length, whether it has music. The Share box then
works on it as it does straight after an export.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .indexer import CACHE

DIR = CACHE / "posters"
LONG_SIDE = 640     # a card's picture at twice its size on a sharp screen [prior]
INTO_S = 3.0        # without a hook noted: at most this far in, past a fade up [prior]


def video_of(exports: list[dict]) -> tuple[int, dict] | None:
    """The export that is this video: the last one in the edit's own frame
    whose file is still there, else the last version in the other frame
    that is. None when nothing exported is left to share."""
    there = [(n, e) for n, e in enumerate(exports or []) if e.get("path") and os.path.isfile(e["path"])]
    own = [x for x in there if not x[1].get("alt")]
    pick = own or there
    return pick[-1] if pick else None


def poster_t(rec: dict) -> float:
    """The moment the card shows: the chosen cover's, else the hook's
    middle as noted at export, else a little way in (a made video may fade
    up from black, and its title arrives in the first second)."""
    c = rec.get("cover") or {}
    if c.get("t") is not None:
        return round(float(c["t"]), 3)
    if rec.get("poster_t") is not None:
        return round(float(rec["poster_t"]), 3)
    s = float(rec.get("seconds") or 0)
    return round(max(0.0, min(s * 0.15, INTO_S, s - 0.1)), 3)


def poster(rec: dict) -> Path:
    """That frame of the exported file as a small JPEG (cached; the export
    is the only file read)."""
    t = poster_t(rec)
    key = re.sub(r"[^\w-]", "", str(rec.get("job") or "")) or "export"
    out = DIR / f"{key}-{int(round(t * 1000))}.jpg"
    if out.exists() and out.stat().st_mtime >= os.path.getmtime(rec["path"]):
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    fit = f"scale=w='if(gte(iw,ih),{LONG_SIDE},-2)':h='if(gte(iw,ih),-2,{LONG_SIDE})'"
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin", "-ss", f"{t:.3f}", "-i", rec["path"],
                        "-frames:v", "1", "-vf", fit, "-q:v", "4", str(out)], capture_output=True, text=True, timeout=60)
    if p.returncode != 0 or not out.exists():
        raise ValueError("Couldn't read a frame of the video: " + (p.stderr.strip()[-160:] or "unknown error"))
    return out


def public(pid: str, exports: list[dict]) -> dict | None:
    """What a Home card needs to show the video and offer Share."""
    v = video_of(exports)
    if v is None:
        return None
    n, e = v
    stamp = f"{int(poster_t(e) * 1000)}-{int(e.get('at') or 0)}"
    return {"n": n, "file": Path(e["path"]).name, "seconds": e.get("seconds"), "size": e.get("size"),
            "at": e.get("at"), "alt": bool(e.get("alt")), "poster": f"/api/projects/{pid}/poster?v={stamp}"}


def revive(rec: dict, items: list[dict], clips: dict[str, dict]):
    """A finished export of an earlier run, back as a job the Share box can
    use. `items` are the edit's as it stands now (for the cover stills and
    the words to post with); the file itself is the one on the record."""
    from . import export
    job = export.Job(id=rec["job"], items=items, clips=clips, size=dict(rec.get("size") or {}),
                     total=float(rec.get("seconds") or 0), name=Path(rec["path"]).stem,
                     # only whether it has music is read from a finished job (the credit)
                     music="yes" if rec.get("music") else None,
                     overlays=int(rec.get("overlays") or 0), stage="done", progress=1.0,
                     path=rec["path"], elapsed=float(rec.get("elapsed") or 0), alt=bool(rec.get("alt")))
    export.JOBS[job.id] = job
    return job
