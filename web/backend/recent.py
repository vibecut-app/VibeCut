"""Your recent videos: what Home shows under the drop box.

A return visit should open on what was made, not on the same empty box as
the first: each video as its own picture, its length, and two ways on,
Open and Share. The picture is the video at its clearest: the sharpest,
steadiest, best-exposed frame among the edit's opening shots (the
indexer's best frame, `pick_still`), read from the original clip at full
size and toned for an SDR screen as the phone showed it. A card upright on
the page needs about 540 x 960 pixels on a sharp screen; the index's
thumbnails are 216 px tall and looked smudged there (sarah, 2026-11-09:
"so blurry ... I don't want to click into them"). When the creator chose a
cover to post with, the card is that frame of the export instead (as
covers.py), and a frame of the export stands in when the clip has moved.

Share hands on the file that was exported, so it needs one that is still
where it was saved. Export jobs live in memory, so an export from an
earlier run of the app is taken up again from its record (`revive`): the
file, its frame and length, whether it has music. The Share box then
works on it as it does straight after an export.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np

from cutgrammar import bestframe, media

from .indexer import CACHE, clip_dir

DIR = CACHE / "posters"
CARD = (540, 960)   # an upright card at twice its size on a sharp screen [prior]
CAP = 1280          # a wide picture covers the card from its middle; no need for more
INTO_S = 3.0        # without a hook noted: at most this far in, past a fade up [prior]
OPENING = 3         # the card's picture is the clearest of the edit's first shots [prior]
# Big enough to cover a card, never past the file's own size.
FIT = (f"scale=w='trunc(iw*min(min(max({CARD[0]}/iw,{CARD[1]}/ih),{CAP}/max(iw,ih)),1)/2)*2'"
       f":h='trunc(ih*min(min(max({CARD[0]}/iw,{CARD[1]}/ih),{CAP}/max(iw,ih)),1)/2)*2':flags=lanczos")
TURN = {90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}   # as export._shot


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
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin", "-ss", f"{t:.3f}", "-i", rec["path"],
                        "-frames:v", "1", "-vf", FIT, "-q:v", "3", str(out)], capture_output=True, text=True, timeout=60)
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
            "at": e.get("at"), "alt": bool(e.get("alt")), "poster": f"/api/projects/{pid}/poster?v={stamp}",
            # the creator picked this frame to post with: the card shows it
            "chosen": bool((e.get("cover") or {}).get("t") is not None)}


def pick_still(entries: list[dict], clips: dict[str, dict]) -> dict | None:
    """Which frame the card shows: of the edit's first OPENING shots, the one
    whose best frame the indexer scored clearest (sharp, steady, well
    exposed), at that frame when the edit keeps it, else the middle of what
    it keeps. A held frame shows its one frame. Turned or mirrored by hand
    stays so."""
    best = None
    seen = 0
    for e in entries:
        if e.get("gap") or not e.get("id"):
            continue
        cid, _, idx = e["id"].partition(":")
        s = next((s for s in (clips.get(cid) or {}).get("shots", []) if str(s.get("index")) == idx), None)
        if s is None:
            continue
        seen += 1
        lo, hi = float(e["start"]), float(e["end"])
        t = lo if e.get("freeze") else float(s["best_t"]) if s.get("best_t") is not None and lo <= s["best_t"] <= hi \
            else (lo + hi) / 2
        q = float(s.get("quality") or 0)
        if best is None or q > best[0]:
            best = (q, {"clip": cid, "t": round(t, 3), "rotate": int(e.get("rotate") or 0) % 360,
                        "mirror": bool(e.get("mirror"))})
        if seen >= OPENING:
            break
    return best[1] if best else None


def still_key(st: dict) -> str:
    return f"{st['clip']}-{int(round(st['t'] * 1000))}-{st.get('rotate', 0)}{'m' if st.get('mirror') else ''}"


def clip_still(st: dict) -> Path:
    """That frame of the original clip as a JPEG sized for a card, as the
    phone showed it (HDR toned for an SDR screen, as the thumbnails are).
    Cached; the clip is read once."""
    try:
        path = json.loads((clip_dir(st["clip"]) / "index.json").read_text())["path"]
    except (OSError, ValueError, KeyError) as e:
        raise FileNotFoundError("this clip was never read") from e
    if not os.path.isfile(path):
        raise FileNotFoundError("the clip isn't where it was any more")
    out = DIR / f"{still_key(st)}.jpg"
    if out.exists() and out.stat().st_mtime >= os.path.getmtime(path):
        return out
    info = media.probe(path)
    v = next((x for x in info.get("streams", []) if x.get("codec_type") == "video"), {})
    meta = {"transfer": v.get("color_transfer"), "primaries": v.get("color_primaries")}
    chain = [TURN[st["rotate"]]] if st.get("rotate") in TURN else []
    if st.get("mirror"):
        chain.append("hflip")
    chain.append(FIT)
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-ss", f"{max(0.0, st['t']):.3f}", "-i", path,
                        "-frames:v", "1", "-vf", ",".join(chain), "-pix_fmt", "rgb24",  # an iPhone's 10 bits too
                        "-f", "image2pipe", "-vcodec", "ppm", "-"],
                       capture_output=True, timeout=60)
    img = _ppm(p.stdout) if p.returncode == 0 else None
    if img is None:
        raise ValueError("Couldn't read a frame of the clip: " + (p.stderr.decode(errors="ignore").strip()[-160:] or "unknown error"))
    out.parent.mkdir(parents=True, exist_ok=True)
    bestframe.write_jpegs([media.to_sdr(img[None], meta)[0]], [str(out)], quality=3)
    return out


def _ppm(b: bytes) -> np.ndarray | None:
    """One binary PPM (what ffmpeg's ppm encoder writes) as (H, W, 3) uint8."""
    m = re.match(rb"P6\s+(\d+)\s+(\d+)\s+(\d+)\s", b)
    if not m or int(m.group(3)) != 255:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    data = b[m.end():m.end() + w * h * 3]
    return np.frombuffer(data, np.uint8).reshape(h, w, 3) if len(data) == w * h * 3 else None


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
