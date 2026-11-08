"""Describe a finished edit shot by shot, as numbers and labels.

The taste model learns what good editors do from what they did, so it
needs every edit -- someone's vlog, or a board VibeCut is about to make --
written down the same way: each shot's length and what's in it (a face
looking in, someone talking, how much moves), how each shot becomes the
next (a hard cut, a jump cut, a dissolve, a dip, a flash -- in the words a
reel can be read in, so a board's swipe is a cut), where the words sit
and for how long, whether music runs under it. One schema (v1) from two
places:

- `from_video`: a reference video, read once into the small arrays
  (media.load), plus the Mac's Vision and sound classifier where they are.
  The words on screen are counted, placed and dropped; frames live in a
  work folder the caller deletes. Nothing of the video stays but numbers.
- `from_board`: a VibeCut board, without rendering or decoding anything:
  the timeline, the export's own transition plan, the captions, and the
  clips' per-second readings from the index.

A reading that couldn't be taken is None and left out of `have`, never
guessed: the model works from what both sides of a comparison have.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np

DESC_VERSION = 1
ROLES = ("hook", "setup", "step", "payoff", "talk", "reaction", "transit", "detail", "title", "outro", "other")
JOIN_KINDS = ("cut", "jump", "dissolve", "dip_black", "flash", "swipe", "other")
READINGS = ("motion", "faces", "sound", "words", "labels", "roles", "music")
BANDS = ("bottom", "middle", "top")
GROUP_OF_FORMAT = {"short": "short", "tall": "long", "wide": "long"}
SHOT_KEYS = ("t", "d", "motion", "motion_in", "motion_out", "face", "facing", "people", "voice", "music",
             "laugh", "labels", "aesthetic", "same", "speed", "role", "chapter")

EDGE_S = 0.5           # how a shot enters and leaves: motion over its first / last half second
JUMP_NEAR_S = 0.2      # a jump cut this close to a join already found is that join
FRAME_FPS = 2          # frames a second the Mac reads, as reference.text_events (a caption holds longer)
FRAME_HEIGHT = 540
TEXT_MIN_CONF = 0.3    # as style.TEXT_MIN_CONF: below this the recogniser is guessing
MUSIC_ON = 0.5         # a second counts as having music under it at this confidence [prior]
MISSING_WORDS = 0.5    # more than this share of frames unread: the words are not known, not absent
TOP_LABELS = 3
FPS = 30               # the edit's frame rate (timeline.FPS)

# How big each kind of words is drawn, as a share of the frame's short side
# (overlayDraw.ts baseLines / TEMPLATES / HEADINGS, main line). A board's
# word size is put on the same scale as OCR's box height (a share of the
# frame's height), so a reel's captions and VibeCut's compare; approximate.
SIZE = {"S": 0.78, "M": 1.0, "L": 1.4}
KIND_SIZE = {"title": 0.09, "end": 0.07, "part": 0.058, "name": 0.05, "date": 0.03, "chapters": 0.024}
SOFT_SIZE = 0.05       # a caption with no template (Soft)
TEMPLATE_SIZE = {"outlined": 0.064, "bold": 0.066, "label": 0.048, "highlight": 0.052, "handwritten": 0.07,
                 "tape": 0.044, "pop": 0.066, "quiet": 0.03, "neon": 0.07, "glow": 0.06, "gradient": 0.064,
                 "extrude": 0.068, "retro": 0.085}
HEADING_SIZE = {"script": 0.088, "spaced": 0.07, "bold": 0.1, "serif": 0.08}
# Lettering that is always capitals, or never (overlayDraw case rules).
TEMPLATE_CASE = {"bold": 1.0, "quiet": 1.0, "handwritten": 0.0}
HEADING_CASE = {"spaced": 1.0, "bold": 1.0}
FRAME_PX = {"short": (1080, 1920), "tall": (1080, 1920), "wide": (1920, 1080)}   # export.frame_size


# --------------------------------------------------------------------------
# small pure helpers (shared by both sides, tested on their own)
# --------------------------------------------------------------------------

def _r(x, nd: int = 3):
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def span_mean(track, a: float, b: float) -> float | None:
    """The mean of a per-second reading over [a, b) seconds, each second
    weighted by how much of it the span covers. None when there's nothing
    to read there (no track, or the span starts past its end)."""
    if not track:
        return None
    n = len(track)
    if b <= a:
        k = min(n - 1, max(0, int(a)))
        return _r(track[k]) if track[k] is not None else None
    lo, hi = max(0, int(math.floor(a))), min(n, int(math.ceil(b)))
    num = den = 0.0
    for k in range(lo, hi):
        w = min(b, k + 1) - max(a, k)
        if w > 0 and track[k] is not None:
            num += w * float(track[k])
            den += w
    return _r(num / den) if den > 0 else None


def face_reading(rows, a: float, b: float) -> tuple[float | None, float | None, int | None]:
    """(face, facing, people) of a span from per-second face rows
    [presence, edge, people, facing] (vision.face_track; older rows have
    only the first two). Facing is the share of the face's seconds looking
    into the lens; None with no face, or when the OS gave no direction."""
    if not rows:
        return None, None, None
    face = span_mean([r[0] for r in rows], a, b)
    if face is None:
        return None, None, None
    lo, hi = max(0, int(math.floor(a))), min(len(rows), max(int(math.ceil(b)), int(math.floor(a)) + 1))
    inside = rows[lo:hi]
    people = int(max(r[2] for r in inside)) if inside and all(len(r) >= 3 for r in inside) else None
    seen = [(min(b, k + 1) - max(a, k) if b > a else 1.0, r[3]) for k, r in zip(range(lo, hi), inside)
            if len(r) >= 4 and r[0] > 0]
    if not seen or any(f < 0 for _, f in seen) or sum(w for w, _ in seen) <= 0:
        return face, None, people
    return face, _r(sum(w * f for w, f in seen) / sum(w for w, _ in seen)), people


def band_of(box) -> str:
    """Where a recognised line sits, from its box [x, y, w, h] (origin
    bottom, style.TEXT_BANDS)."""
    from cutgrammar.style import TEXT_BANDS
    cy = box[1] + box[3] / 2
    for lo, hi, name in TEXT_BANDS:
        if lo <= cy < hi:
            return name
    return "top" if cy >= 1 else "bottom"


def _upper(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    return sum(ch.isupper() for ch in letters) / len(letters) if letters else 0.0


def word_events(samples: list[dict], step: float = 1 / FRAME_FPS) -> list[dict]:
    """Words on screen read from frames at a steady rate -> one event per
    caption: the samples in a row with words in the same band are one card
    (two bands at once are two cards, a title over a subtitle). `samples` =
    [{t, items: [{text, box, conf}] | None}]; None = that frame wasn't read,
    which neither starts nor ends a card. A one-frame hole inside a card is
    the recogniser missing it, not two cards (as style.text_style). The
    words themselves go no further than this function."""
    samples = sorted(samples, key=lambda s: s["t"])
    events = []
    for band in BANDS:
        state = []          # per sample: list of items in this band, [] none, None unread
        for s in samples:
            items = s.get("items")
            if items is None:
                state.append(None)
                continue
            state.append([i for i in items if i.get("conf", 1) >= TEXT_MIN_CONF and str(i.get("text", "")).strip()
                          and band_of(i["box"]) == band])
        on = [bool(x) for x in state]
        for k in range(1, len(state) - 1):
            if not on[k] and on[k - 1] and on[k + 1]:
                on[k] = True
        k = 0
        while k < len(state):
            if not on[k]:
                k += 1
                continue
            j = k
            while j + 1 < len(state) and (on[j + 1] or (state[j + 1] is None and j + 2 < len(state) and on[j + 2])):
                j += 1
            run = [x for x in state[k:j + 1] if x]
            items = [i for x in run for i in x]
            text = " ".join(i["text"] for i in items)
            events.append({"t": _r(samples[k]["t"]), "d": _r((j - k + 1) * step), "band": band,
                           "size": _r(float(np.median([i["box"][3] for i in items]))),
                           "upper": _r(_upper(text), 2),
                           "n": int(round(float(np.median([sum(len(i["text"].split()) for i in x) for x in run])))),
                           "kind": None})
            k = j + 1
    return sorted(events, key=lambda e: (e["t"], BANDS.index(e["band"])))


def _have(*pairs) -> list[str]:
    got = {name for name, ok in pairs if ok}
    return [x for x in READINGS if x in got]


def _shot(t: float, d: float, **kw) -> dict:
    out = {k: None for k in SHOT_KEYS}
    out.update(t=_r(t), d=_r(d), same=False, speed=1.0)
    out.update(kw)
    return out


# --------------------------------------------------------------------------
# a finished video
# --------------------------------------------------------------------------

def _jumps(m, sh, log) -> list[float]:
    """Jump cuts inside the hard-cut shots (shots.jump_cuts, when the
    detector is there): the same camera and background, the subject skips
    ahead -- the talking vlog's cut. As seconds."""
    from cutgrammar import shots as shots_mod
    find = getattr(shots_mod, "jump_cuts", None)
    if find is None:
        return []
    try:
        found = find(m, sh) or []
    except Exception as e:   # a reading that fails is left out, never fatal to the description
        log(f"  jump cuts not read: {e}")
        return []
    out = []
    for j in found:
        if isinstance(j, dict):
            out.append(float(j["t"]))
        elif isinstance(j, (int, np.integer)):
            out.append(float(m.t(int(j))))
        else:
            out.append(float(j))
    return out


def _motion(m, joins: list[dict], fades: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Per-frame motion, and which frames to leave out of it: the cut
    itself (a frame either side) and every frame of a dissolve, dip or fade
    -- those measure the join, not what the camera saw."""
    from cutgrammar import features
    mo = features.motion(m).astype(np.float64)
    fps = m.fps or 30.0
    skip = np.zeros(len(mo), dtype=bool)
    if len(skip):
        skip[0] = True
    for x in joins:
        half = max(x["dur"] / 2, 1 / fps)
        a, z = int(math.floor((x["t"] - half) * fps)), int(math.ceil((x["t"] + half) * fps)) + 1
        skip[max(0, a):max(0, z)] = True
    for x in fades:
        if x["kind"] == "fade_in":
            skip[: int(math.ceil(x["dur"] * fps)) + 1] = True
        else:
            skip[max(0, int((x["t"] - x["dur"]) * fps) - 1):] = True
    return mo, skip


def _mean(mo: np.ndarray, skip: np.ndarray, a: float, b: float, fps: float) -> float | None:
    i, j = max(0, int(round(a * fps))), min(len(mo), int(round(b * fps)))
    sel = mo[i:j][~skip[i:j]]
    return _r(float(sel.mean())) if len(sel) else None


def _frames(path: str, out: Path, limit_s: float | None) -> list[str]:
    head = ["-t", f"{limit_s:.3f}"] if limit_s else []
    out.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", *head, "-i", path,
                        "-vf", f"fps={FRAME_FPS},scale=-2:{FRAME_HEIGHT}", "-q:v", "4", str(out / "%05d.jpg")],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return []
    return sorted(str(x) for x in out.glob("*.jpg"))


def _read_words(vision, paths: list[str], log) -> list[dict] | None:
    try:
        got = vision.text(paths, accurate=True)
    except TypeError:            # a bridge without the accurate reader
        got = vision.text(paths)
    failed: set = set()
    if isinstance(got, tuple):   # (found, paths that timed out)
        got, failed = got[0], set(got[1] or ())
    got = got or {}
    samples = [{"t": i / FRAME_FPS, "items": None if (p in failed or p not in got) else got[p]}
               for i, p in enumerate(paths)]
    unread = sum(s["items"] is None for s in samples)
    if not samples or unread > MISSING_WORDS * len(samples):
        log(f"  words not read ({unread} of {len(samples)} frames unread)")
        return None
    return word_events(samples)


def _read_sound(sound, binary, path: str, limit_s: float | None, n: int) -> dict | None:
    """Per-second voice / music / laughter of the video's own sound
    (vibesound), over the part that was measured."""
    with tempfile.TemporaryDirectory() as d:
        wav = str(Path(d) / "a.wav")
        head = ["-t", f"{limit_s:.3f}"] if limit_s else []
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", *head, "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav],
                           capture_output=True)
        if p.returncode:
            return None
        ws = sound._classify(binary, wav)
    if ws is None:
        return None
    return {k: sound.per_second(ws, n, k) for k in ("voice", "music", "laughter")}


def from_video(path: str, *, id: str | None = None, group: str | None = None, limit_s: float | None = None,
               workdir: str | Path | None = None, mac: bool = True, log=print,
               loaded=None) -> tuple[dict, dict]:
    """One reference video -> (description, extras). Read once at 48x27
    (media.load); joins from style.transitions (+ jump cuts), so shot
    lengths come from the same reading as the measurements. With the Mac's
    readers (`mac`), frames at 2 fps go to Vision (words, faces, labels)
    and the sound to the classifier. `extras` = {"stills": a mid-frame jpg
    per shot, "frames_dir", "times"} while the frames exist (Vision there,
    or a `workdir` given); the caller deletes `frames_dir`. `loaded`: the
    same file already read by media.load with the same `limit_s` (the
    collector measures it first), so its pixels are decoded once."""
    from cutgrammar import media, shots as shots_mod, style

    m = loaded if loaded is not None else media.load(path, limit_s=limit_s)
    dur = float(m.duration)
    fps = m.fps or 30.0
    cutoff = bool(limit_s and m.duration >= limit_s - 1)
    sh = shots_mod.detect(m)
    trans = style.transitions(m, sh)
    fades = [x for x in trans if x["kind"] in ("fade_in", "fade_out")]
    joins = [{"t": float(x["t"]), "kind": x["kind"] if x["kind"] in JOIN_KINDS else "other", "dur": float(x["dur"])}
             for x in trans if x["kind"] not in ("fade_in", "fade_out") and 0 < x["t"] < dur]
    for t in _jumps(m, sh, log):
        if 0 < t < dur and all(abs(t - x["t"]) > JUMP_NEAR_S for x in joins):
            joins.append({"t": t, "kind": "jump", "dur": 0.0})
    joins.sort(key=lambda x: x["t"])
    kept = []
    for x in joins:          # two readings of one boundary: the first stands
        if (x["t"] - (kept[-1]["t"] if kept else 0.0)) * fps >= 1:
            kept.append(x)
    joins = [x for x in kept if (dur - x["t"]) * fps >= 1]

    mo, skip = _motion(m, joins, fades)
    edges = [0.0, *[x["t"] for x in joins], dur]
    shots = []
    for k, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        shots.append(_shot(a, b - a, motion=_mean(mo, skip, a, b, fps),
                           motion_in=_mean(mo, skip, a, min(b, a + EDGE_S), fps),
                           motion_out=_mean(mo, skip, max(a, b - EDGE_S), b, fps),
                           same=bool(k and joins[k - 1]["kind"] == "jump")))

    music = None
    if m.has_audio:
        beat = style.beat_sync(m, [x["t"] for x in joins]) or {}
        music = {"bpm": _r(beat.get("bpm"), 1), "on": None, "beat": _r(beat.get("on_grid"))}

    # --- the Mac's readings ------------------------------------------------
    vision = sound = vbin = sbin = None
    if mac:
        from web.backend import sound, vision
        vbin, sbin = vision.ensure_built(), sound.ensure_built()
    frames_dir, paths = None, []
    if vbin is not None or workdir is not None:
        frames_dir = Path(workdir) if workdir is not None else Path(tempfile.mkdtemp(prefix="vibecut-describe-"))
        paths = _frames(path, frames_dir, limit_s)
    times = [round(i / FRAME_FPS, 3) for i in range(len(paths))]
    mids = [min(len(paths) - 1, max(0, int(round((s["t"] + s["d"] / 2) * FRAME_FPS)))) for s in shots] if paths else []
    stills = [paths[i] for i in mids] if paths else [None] * len(shots)

    words = None
    got_faces = got_labels = got_sound = False
    if vbin is not None and paths:
        words = _read_words(vision, paths, log)
        boxes = vision.faces(paths)
        if boxes:
            track = vision.face_track([boxes.get(p, []) for p in paths], times, int(math.ceil(dur)))
            for s in shots:
                s["face"], s["facing"], s["people"] = face_reading(track, s["t"], s["t"] + s["d"])
            got_faces = True
        recs, backend = vision.analyse(sorted(set(stills)))
        if backend == "vision":
            by = {r["path"]: r for r in recs if not r.get("error")}
            for s, p in zip(shots, stills):
                r = by.get(p)
                if r:
                    s["labels"] = [lb for lb, _ in r.get("labels", [])[:TOP_LABELS]]
                    s["aesthetic"] = _r(r.get("aesthetic"))
            got_labels = any(s["labels"] is not None for s in shots)
    if sbin is not None and m.has_audio:
        per = _read_sound(sound, sbin, path, limit_s, int(math.ceil(dur)))
        if per is not None:
            for s in shots:
                a, b = s["t"], s["t"] + s["d"]
                s["voice"], s["music"], s["laugh"] = (span_mean(per["voice"], a, b), span_mean(per["music"], a, b),
                                                      span_mean(per["laughter"], a, b))
            mus = per["music"]
            music = {**(music or {"bpm": None, "beat": None}),
                     "on": _r(sum(x >= MUSIC_ON for x in mus) / len(mus)) if mus else 0.0}
            got_sound = True

    desc = {
        "v": DESC_VERSION, "id": id, "source": "reference", "group": group,
        "vertical": bool(style.frame_style(m, (0, 0))["vertical"]),
        "duration": _r(sum(s["d"] for s in shots)), "cutoff": cutoff,
        "have": _have(("motion", m.n_frames > 1), ("faces", got_faces), ("sound", got_sound),
                      ("words", words is not None), ("labels", got_labels),
                      ("music", music is not None and music.get("on") is not None)),
        "shots": shots,
        "joins": [{"t": _r(x["t"]), "kind": x["kind"], "dur": _r(x["dur"])} for x in joins],
        "open": any(x["kind"] == "fade_in" for x in fades),
        "close": bool(not cutoff and any(x["kind"] == "fade_out" for x in fades)),
        "words": words,
        "music": music,
        "lufs": _r(media.loudness_lufs(path), 1),
    }
    log(f"  {len(shots)} shots over {desc['duration']:.0f} s, read: {', '.join(desc['have']) or 'nothing'}")
    return desc, {"stills": stills, "frames_dir": str(frames_dir) if frames_dir else None, "times": times}


# --------------------------------------------------------------------------
# a VibeCut board
# --------------------------------------------------------------------------

def _labels_of(sid: str, clip: dict | None, cat) -> tuple[list[str] | None, float | None]:
    """Top labels and Apple's aesthetics score of a shot: the catalogue's
    if there is one, else the clip's own index."""
    s = cat.shots.get(sid) if cat is not None else None
    if s is not None:
        labels = [k for k, _ in sorted((s.labels or {}).items(), key=lambda kv: -kv[1])[:TOP_LABELS]]
        return labels or None, _r(s.aesthetic)
    idx = int(sid.split(":")[1]) if ":" in sid else -1
    rec = next((x for x in (clip or {}).get("shots", []) if x.get("index") == idx), None)
    if rec is None:
        return None, None
    raw = rec.get("labels") or []
    pairs = sorted(raw.items() if isinstance(raw, dict) else [tuple(x) for x in raw], key=lambda kv: -kv[1])
    return [k for k, _ in pairs[:TOP_LABELS]] or None, _r(rec.get("aesthetic"))


# The blends a reference's reader (style.transitions) can see. A board is
# described the way a reel is read, so the model compares like with like: a
# swipe, slide or zoom through reads as a plain cut there (a 0.3 s slideleft
# came back as one "cut"), so it is a "cut" here too, the blend kept aside as
# `drawn`. Otherwise every board's swipes would count against it for
# something no real edit could ever be seen to have.
READ_BLENDS = ("dissolve",)


def _join_kind(plan: list[dict], k: int) -> tuple[str, float, str | None]:
    """How shot k becomes k+1 in the export's own plan (app._picture_at), in
    the reference reader's words, and the blend actually drawn when that
    reader would call it something else."""
    a, b = plan[k], plan[k + 1]
    if a.get("blend"):
        if a["blend"] in READ_BLENDS:
            return a["blend"], (a["tail"] + b["head"]) / FPS, None
        return "cut", 0.0, str(a["blend"])
    if a.get("fade_out") and b.get("fade_in"):
        kind = "flash" if a["fade_out"][1] == "white" else "dip_black"
        return kind, (a["fade_out"][0] + b["fade_in"][0]) / FPS, None
    return "cut", 0.0, None


def _words_of_board(board: dict, fmt: str) -> list[dict]:
    """The captions as word events: when, where, how big, how capitalised,
    how many words -- the same shape a reel's OCR gives."""
    from web.backend import overlays
    st = overlays.style_of(board)
    tpl = st.get("template")
    case = (st.get("motion") or {}).get("case")
    w, h = FRAME_PX.get(fmt, FRAME_PX["short"])
    u = min(w, h) / h       # the short side as a share of the height
    out = []
    for o in overlays.resolve(board):
        d = float(o["shown_end"]) - float(o["start"])
        if d <= 0:
            continue
        kind = o["kind"]
        text = " ".join(x for x in (o.get("text") or "", o.get("sub") or "") if x)
        if kind == "chapters":
            text = " ".join(b.get("title", "") for b in board.get("beats", []))
        if o.get("place"):
            y = float(o["place"]["y"])
            band = "top" if y < 0.33 else "bottom" if y > 0.67 else "middle"
        elif kind == "caption":
            band = "middle" if st.get("captions") == "center" else "bottom"
        else:
            pos = o.get("pos") or "center"
            band = "top" if pos.startswith("top") else "bottom" if pos.startswith("bottom") else "middle"
        if kind == "caption":
            factor = TEMPLATE_SIZE.get(tpl, SOFT_SIZE) if tpl else SOFT_SIZE
            upper = TEMPLATE_CASE.get(tpl, _upper(text)) if tpl else 0.0
        elif kind == "heading":
            factor = HEADING_SIZE.get(o.get("look") or "bold", HEADING_SIZE["bold"])
            upper = HEADING_CASE.get(o.get("look") or "bold", _upper(text))
        else:
            factor = KIND_SIZE.get(kind, SOFT_SIZE)
            upper = 1.0 if kind == "date" or case == "upper" else 0.0 if case == "lower" else _upper(text)
        scale = float((o.get("place") or {}).get("scale") or 1.0)
        out.append({"t": _r(o["start"]), "d": _r(d), "band": band,
                    "size": _r(factor * SIZE.get(o.get("size") or "M", 1.0) * scale * u),
                    "upper": _r(upper, 2), "n": len(text.split()), "kind": kind})
    return out


def from_board(board: dict, clips, cat=None, fmt: str = "short", *, roles: dict | None = None,
               track=None) -> dict:
    """A board as the same description, with no rendering and no decode:
    timeline.layout -> export.spans -> the look's joins with the creator's
    picks (looks.picture) -> export.plan_transitions, as the export would
    draw them; overlays.resolve for the words; each shot's face, voice and
    motion from its clip's per-second index readings over the source
    seconds it uses. `clips` = {clip id: index record}; `roles` = {entry
    key or shot id: role} from the plan; `track` = the music.Track in hand
    (else only one already loaded is looked up: nothing is analysed)."""
    from web.backend import export, looks, timeline

    if isinstance(clips, list):
        clips = {c["id"]: c for c in clips}
    board = board or {}
    sp = export.spans(timeline.layout(board))
    plan, _ = export.plan_transitions(sp, clips, looks.picture(board, None))
    order = {b["id"]: i for i, b in enumerate(board.get("beats", []))}
    idx = [k for k, it in enumerate(sp) if it["kind"] == "shot"]

    shots, joins, seen = [], [], {"motion": 0, "faces": 0, "sound": 0, "labels": 0}
    for j, k in enumerate(idx):
        it = sp[k]
        c = clips.get(it["clip_id"]) or {}
        a, b = float(it["src_start"]), float(it["src_end"])
        sig = (c.get("signals") or {}).get("motion")
        face, facing, people = face_reading(c.get("faces"), a, b)
        snd = c.get("sound") or {}
        labels, aesthetic = _labels_of(it["shot_id"], c, cat)
        role = (roles or {}).get(it["key"]) or (roles or {}).get(it["shot_id"])
        s = _shot(it["seq_start"], it["frames"] / FPS,
                  motion=span_mean(sig, a, b), motion_in=span_mean(sig, a, min(b, a + EDGE_S)),
                  motion_out=span_mean(sig, max(a, b - EDGE_S), b),
                  face=face, facing=facing, people=people,
                  voice=span_mean(snd.get("voice"), a, b), music=span_mean(snd.get("music"), a, b),
                  laugh=span_mean(snd.get("laughter"), a, b),
                  labels=labels, aesthetic=aesthetic, speed=float(it.get("speed") or 1.0),
                  role=role if role in ROLES else None, chapter=order.get(it["beat_id"]))
        seen["motion"] += s["motion"] is not None
        seen["faces"] += s["face"] is not None
        seen["sound"] += s["voice"] is not None
        seen["labels"] += s["labels"] is not None
        if j:
            p = idx[j - 1]
            prev = sp[p]
            drawn = None
            if k != p + 1:
                # a gap between them is black: a dip as long as the gap
                kind, jd = "dip_black", (it["seq_start"] - prev["seq_end"])
            else:
                kind, jd, drawn = _join_kind(plan, p)
                # the same clip again, further on: the talking vlog's jump cut
                if (kind == "cut" and not drawn and prev["clip_id"] == it["clip_id"]
                        and a > float(prev["src_end"]) + 1 / FPS):
                    kind = "jump"
            s["same"] = kind == "jump"
            joins.append({"t": _r(it["seq_start"]), "kind": kind, "dur": _r(jd)})
            if drawn:
                joins[-1]["drawn"] = drawn
        shots.append(s)

    mus = board.get("music") or {}
    on = bool(mus.get("track"))
    if on and track is None:
        from web.backend import musiclib
        track = next((t for t in musiclib.STATE.get("tracks", []) if getattr(t, "id", None) == mus["track"]), None)
    bpm = beat = None
    if on and track is not None:
        bpm = _r(getattr(track, "bpm", None), 1)
        grid = timeline.grid_of(track, float(mus.get("in") or 0.0))
        cuts = [x["t"] for x in joins]
        if grid and cuts:
            from cutgrammar.style import BEAT_TOL_S
            period = 60.0 / grid["bpm"]
            ph = (np.asarray(cuts) - grid["phase"]) / period
            beat = _r(float(np.mean(np.abs(ph - np.round(ph)) * period < BEAT_TOL_S)))

    first = plan[idx[0]] if idx else {}
    last = plan[idx[-1]] if idx else {}
    total = sp[-1]["seq_end"] if sp else 0.0
    half = len(shots) / 2
    roles_set = any(s["role"] for s in shots)
    return {
        "v": DESC_VERSION, "id": None, "source": "board", "group": GROUP_OF_FORMAT.get(fmt),
        "vertical": fmt != "wide", "duration": _r(total), "cutoff": False,
        # a reading most of the edit has counts; a shot without it stays None
        "have": _have(("motion", shots and seen["motion"] >= half), ("faces", shots and seen["faces"] >= half),
                      ("sound", shots and seen["sound"] >= half), ("words", True),
                      ("labels", shots and seen["labels"] >= half), ("roles", roles_set), ("music", True)),
        "shots": shots,
        "joins": joins,
        "open": bool(first.get("fade_in") and first["fade_in"][1] == "black"),
        "close": bool(last.get("fade_out") and last["fade_out"][1] == "black"),
        "words": _words_of_board(board, fmt),
        "music": {"bpm": bpm, "on": heard_share(shots, mus if on else None, total), "beat": beat},
        "lufs": None,
    }


HEARD = 0.2            # the bed ducked below this share of its gain isn't heard as music [prior]


def heard_share(shots: list[dict], mus: dict | None, total: float, step: float = 0.25) -> float:
    """Share of the edit's time with music heard, as from_video reads a real
    vlog (the classifier hears music in the final mix): the bed where it
    isn't ducked out, or music in the footage's own sound. Before
    2026-10-24 a board with a track read 1.0 however much of it was ducked
    out, so the taste model couldn't see music stepping out under talk."""
    if total <= 0:
        return 0.0
    ducks = [d for d in ((mus or {}).get("duck") or []) if len(d) >= 3]
    n = max(1, int(math.ceil(total / step)))
    heard = 0
    k = 0
    for i in range(n):
        t = (i + 0.5) * step
        while k < len(shots) - 1 and t >= shots[k]["t"] + shots[k]["d"]:
            k += 1
        own = shots[k].get("music") if shots else None
        if own is not None and own >= MUSIC_ON:
            heard += 1
            continue
        if mus is None:
            continue
        level = min([float(g) for a, b, g in ducks if float(a) <= t < float(b)], default=1.0)
        heard += level >= HEARD
    return _r(heard / n)


# --------------------------------------------------------------------------
# checking, saving
# --------------------------------------------------------------------------

def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate(desc: dict) -> list[str]:
    """What's wrong with a description, in plain words; empty when fine."""
    if not isinstance(desc, dict):
        return ["not a description"]
    bad = []
    if desc.get("v") != DESC_VERSION:
        bad.append(f"version {desc.get('v')!r}, not {DESC_VERSION}")
    for k in ("id", "source", "group", "vertical", "duration", "cutoff", "have", "shots", "joins", "open",
              "close", "words", "music", "lufs"):
        if k not in desc:
            bad.append(f"no {k}")
    if bad:
        return bad
    if desc["source"] not in ("reference", "board"):
        bad.append(f"source {desc['source']!r}")
    if desc["group"] not in ("long", "short", None):
        bad.append(f"group {desc['group']!r}")
    for k in ("vertical", "cutoff", "open", "close"):
        if not isinstance(desc[k], bool):
            bad.append(f"{k} is not true/false")
    if not _num(desc["duration"]) or desc["duration"] < 0:
        bad.append("duration is not a length")
    if not isinstance(desc["have"], list) or any(x not in READINGS for x in desc["have"]):
        bad.append(f"have {desc['have']!r} names an unknown reading")
    shots = desc["shots"]
    if not isinstance(shots, list) or not shots:
        return bad + ["no shots"]
    end = 0.0
    for n, s in enumerate(shots, 1):
        miss = [k for k in SHOT_KEYS if k not in s]
        if miss:
            bad.append(f"shot {n} lacks {', '.join(miss)}")
            continue
        if not (_num(s["t"]) and _num(s["d"])) or s["d"] <= 0:
            bad.append(f"shot {n} has no length")
            continue
        if s["t"] < end - 0.05:
            bad.append(f"shot {n} starts before shot {n - 1} ends")
        end = s["t"] + s["d"]
        for k in ("face", "facing", "voice", "music", "laugh"):
            if s[k] is not None and not (_num(s[k]) and -1e-6 <= s[k] <= 1 + 1e-6):
                bad.append(f"shot {n} {k} {s[k]!r} is not 0..1")
        for k in ("motion", "motion_in", "motion_out"):
            if s[k] is not None and not (_num(s[k]) and s[k] >= 0):
                bad.append(f"shot {n} {k} {s[k]!r}")
        if s["aesthetic"] is not None and not (_num(s["aesthetic"]) and -1.001 <= s["aesthetic"] <= 1.001):
            bad.append(f"shot {n} aesthetic {s['aesthetic']!r}")
        if s["people"] is not None and not (isinstance(s["people"], int) and s["people"] >= 0):
            bad.append(f"shot {n} people {s['people']!r}")
        if s["labels"] is not None and not (isinstance(s["labels"], list) and all(isinstance(x, str) for x in s["labels"])):
            bad.append(f"shot {n} labels are not words")
        if s["role"] is not None and s["role"] not in ROLES:
            bad.append(f"shot {n} role {s['role']!r}")
        if not isinstance(s["same"], bool):
            bad.append(f"shot {n} same is not true/false")
        if not (_num(s["speed"]) and s["speed"] > 0):
            bad.append(f"shot {n} speed {s['speed']!r}")
        if s["chapter"] is not None and not isinstance(s["chapter"], int):
            bad.append(f"shot {n} chapter {s['chapter']!r}")
    if _num(desc["duration"]) and sum(s["d"] for s in shots if _num(s.get("d"))) > desc["duration"] + 0.05:
        bad.append("the shots run longer than the video")
    joins = desc["joins"]
    if not isinstance(joins, list) or len(joins) != len(shots) - 1:
        bad.append(f"{len(joins) if isinstance(joins, list) else '?'} joins for {len(shots)} shots")
    else:
        for n, j in enumerate(joins, 1):
            if j.get("kind") not in JOIN_KINDS:
                bad.append(f"join {n} kind {j.get('kind')!r}")
            if not (_num(j.get("t")) and _num(j.get("dur")) and j["dur"] >= 0):
                bad.append(f"join {n} has no time or length")
    if desc["words"] is not None:
        if not isinstance(desc["words"], list):
            bad.append("words is not a list")
        else:
            for n, w in enumerate(desc["words"], 1):
                if w.get("band") not in BANDS:
                    bad.append(f"words {n} band {w.get('band')!r}")
                if not (_num(w.get("t")) and _num(w.get("d")) and w["d"] >= 0):
                    bad.append(f"words {n} have no time")
                if not (isinstance(w.get("n"), int) and w["n"] >= 0):
                    bad.append(f"words {n} count {w.get('n')!r}")
                for k in ("size", "upper"):
                    if w.get(k) is not None and not _num(w[k]):
                        bad.append(f"words {n} {k} {w.get(k)!r}")
                if "text" in w:
                    bad.append(f"words {n} keep their text")
    mus = desc["music"]
    if mus is not None and (not isinstance(mus, dict) or any(k not in mus for k in ("bpm", "on", "beat"))):
        bad.append("music lacks bpm / on / beat")
    if desc["lufs"] is not None and not _num(desc["lufs"]):
        bad.append(f"lufs {desc['lufs']!r}")
    return bad


def save(desc: dict, path) -> None:
    """Write a description; a broken one is refused, not kept for training."""
    bad = validate(desc)
    if bad:
        raise ValueError("not a valid description: " + "; ".join(bad[:5]))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(desc, indent=1, default=float))
    tmp.replace(p)


def load(path) -> dict:
    return json.loads(Path(path).read_text())
