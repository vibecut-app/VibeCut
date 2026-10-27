"""Where to aim a crop: at the people in the shot, not at its middle.

A version in the other frame (share.py's "vertical version too") crops
every shot filmed the other way up: a wide shot keeps about a third of its
width in a vertical frame. Kept to the middle, someone standing left of
centre -- the rule-of-thirds framing most people film by -- loses half
their face, the clearest amateur tell a reframe can make. An editor
reframing by hand moves the window onto the person; this does the same,
once per shot (a window that follows every frame reads as a robot
camera), from the face boxes Vision already finds on the index's samples.

- **Who**: the faces in the shot that aren't background (`COMPANION` of the
  largest, as vision.face_track counts people). Two people who fit in the
  window together are kept together; when they don't, the larger one --
  the person nearest the camera -- is kept whole.
- **When**: only the samples inside the seconds the shot uses. A shot
  where faces are seen on fewer than `MIN_SEEN` of them keeps the middle
  (a passer-by is no subject).
- **Where**: the median of those samples, so a turn of the head doesn't
  swing the window. Across the frame the face is centred; up and down
  (a wide version of a vertical shot) it sits at `HEAD_AT` of the height,
  leaving headroom above it as a framed shot would.

Boxes are read from the index's sample JPEGs (never the original file) and
cached beside them as `faceboxes.json`; on a machine without Vision there
are none and every crop keeps the middle, which the export says.
"""

from __future__ import annotations

import json
from statistics import median

from . import vision
from .indexer import clip_dir

MIN_SEEN = 0.3     # share of a shot's samples with a face before it has a subject [prior]
HEAD_AT = 0.4      # a face's centre this far down a cropped frame [prior: upper third + headroom]
COMPANION = vision.COMPANION


def _cache(cid: str):
    return clip_dir(cid) / "faceboxes.json"


def boxes(clips: list[dict]) -> dict[str, list[list[list[float]]]]:
    """{clip id: face boxes per sample}, read once per clip and cached.
    Clips Vision can't read here (or with no samples) are left out."""
    out, need = {}, []
    for c in clips:
        cid, files = c.get("id"), (c.get("samples") or {}).get("files")
        if not cid or not files:
            continue
        try:
            got = json.loads(_cache(cid).read_text())
            if len(got) == len(files):
                out[cid] = got
                continue
        except (OSError, ValueError):
            pass
        need.append(c)
    if need:
        paths = {c["id"]: [str(clip_dir(c["id"]) / f) for f in c["samples"]["files"]] for c in need}
        found = vision.faces([p for ps in paths.values() for p in ps])
        if found:
            for cid, ps in paths.items():
                out[cid] = [found.get(p, []) for p in ps]
                try:
                    _cache(cid).write_text(json.dumps(out[cid]))
                except OSError:
                    pass
    return out


def subject(faces: list[list[float]], window: tuple[float, float]) -> tuple[float, float] | None:
    """The point to keep on one sample, top-left origin (Vision's boxes are
    bottom-left): the people together if they fit in `window` (the crop's
    width and height as a share of the picture), else the largest face."""
    if not faces:
        return None
    big = max(faces, key=lambda b: b[2] * b[3])
    keep = [b for b in faces if b[2] * b[3] >= COMPANION * big[2] * big[3]]
    left, right = min(b[0] for b in keep), max(b[0] + b[2] for b in keep)
    top, bottom = min(1 - (b[1] + b[3]) for b in keep), max(1 - b[1] for b in keep)
    if right - left > window[0] or bottom - top > window[1]:
        keep = [big]
        left, right, top, bottom = big[0], big[0] + big[2], 1 - (big[1] + big[3]), 1 - big[1]
    return (left + right) / 2, (top + bottom) / 2


# A crop that keeps a face's centre can still cut the face: a close selfie in
# a wide frame is taller than the third of the picture a wide window shows,
# and its hair and chin go (the side-by-side of 2026-10-26: foreheads cut at
# 1:07, a face sliced at the edge at 56.7 s). So the whole face is checked,
# with room for the hair above and the chin below. [priors]
HAIR = 0.4           # above a face box, this much of its height is still the head
CHIN = 0.15          # ...and below it
CUT_TOL = 0.04       # a head may lose this much of its height to the crop before it reads as cut
CUT_SHARE = 0.34     # cut on this share of the samples with a face in them = the crop cuts the face


def cuts_face(it: dict, clip: dict, faces: list[list[list[float]]] | None, window: tuple[float, float],
              at: tuple[float, float] | None) -> bool:
    """Whether the crop -- `window` (width, height shares of the picture) put
    where export._fit puts it for `at` (else the middle) -- cuts off a head:
    the main faces' boxes (a companion as big as COMPANION of the largest
    counts), grown by HAIR and CHIN, must sit inside it on most samples."""
    if not faces:
        return False
    times = (clip.get("samples") or {}).get("times") or []
    a, b = float(it.get("src_start", 0)), float(it.get("src_end", 0))
    inside = [i for i, t in enumerate(times) if a <= t <= b and i < len(faces) and faces[i]]
    if not inside:
        return False
    wx, wy = window
    px, py = at or (0.5, 0.5)
    left = min(max(px - wx / 2, 0.0), max(0.0, 1 - wx))
    top = min(max(py - HEAD_AT * wy, 0.0), max(0.0, 1 - wy))
    cut = 0
    for i in inside:
        big = max(faces[i], key=lambda f: f[2] * f[3])
        for f in (f for f in faces[i] if f[2] * f[3] >= COMPANION * big[2] * big[3]):
            x0, x1 = f[0], f[0] + f[2]
            y0, y1 = 1 - (f[1] + f[3]) - HAIR * f[3], 1 - f[1] + CHIN * f[3]
            lost = (max(0.0, top - y0) + max(0.0, y1 - (top + wy))) / max(f[3], 1e-6)
            lost_x = (max(0.0, left - x0) + max(0.0, x1 - (left + wx))) / max(f[2], 1e-6)
            if lost > CUT_TOL or lost_x > CUT_TOL:
                cut += 1
                break
    return cut >= CUT_SHARE * len(inside)


def turned(p: tuple[float, float], rotate: int, mirror: bool) -> tuple[float, float]:
    """A point in the filmed picture, after the shot's mirror and quarter
    turns as export._shot applies them (hflip, then transpose)."""
    x, y = p
    if mirror:
        x = 1 - x
    r = int(rotate or 0) % 360
    if r == 90:          # transpose=1: a quarter turn clockwise
        x, y = 1 - y, x
    elif r == 180:
        x, y = 1 - x, 1 - y
    elif r == 270:       # transpose=2: counter-clockwise
        x, y = y, 1 - x
    return x, y


def aim(it: dict, clip: dict, faces: list[list[list[float]]], window: tuple[float, float]) -> tuple[float, float] | None:
    """Where the crop of this shot centres, as a share of its (turned)
    picture, or None to keep the middle. `window` is in the turned picture;
    faces are found before the turn, so it's turned back for `subject`."""
    times = (clip.get("samples") or {}).get("times") or []
    a, b = float(it.get("src_start", 0)), float(it.get("src_end", 0))
    inside = [i for i, t in enumerate(times) if a <= t <= b and i < len(faces)]
    if not inside:   # a shot shorter than the sample spacing: its nearest sample
        if not times or not faces:
            return None
        mid = (a + b) / 2
        inside = [min(range(min(len(times), len(faces))), key=lambda i: abs(times[i] - mid))]
    quarter = int(it.get("rotate") or 0) % 180 == 90
    win = (window[1], window[0]) if quarter else window
    seen = [p for p in (subject(faces[i], win) for i in inside) if p]
    if not seen or len(seen) < MIN_SEEN * len(inside):
        return None
    x, y = turned((median(p[0] for p in seen), median(p[1] for p in seen)), int(it.get("rotate") or 0), bool(it.get("mirror")))
    return round(x, 4), round(y, 4)
