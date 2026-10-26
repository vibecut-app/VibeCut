"""Looks (the "vibe" in the UI): one dated record per look, applied as a turn.

Surface dates and structure lasts (research 06 §4), so a look is data, not
code: `looks/*.json`, one file each, with the date it was written and the
date it must be reviewed by. The values come from the design spec
(redesign-v2 §4.3–4.4); most are priors, and each record says which were
measured. This first cut carries what words on screen need -- font, case,
tracking, palette, backing, and motion (curve, entrance time, stepping,
stagger, beat lock) -- and, since 2026-10-10, the picture: a **grade** and
a **join** family, so picking "Cozy" grades the shots and softens the
part boundaries, not only the words. The spec's camera, texture, sounds
and music per look are still listed in each record's `not_yet`.

The grade is *relative to the footage*, not a reference's absolute colour:
"warm, lifted blacks, a little less saturated" is applied on top of what
was filmed (a black floor or ceiling, never an absolute level: footage
already past it is left alone) (`grade_target` turns the footage's own stats into the target
stats grade.Look fits a LUT to). Colour shifts stay capped by grade.py's
MAX_SHIFT, so a sunset isn't un-warmed and a face isn't tinted. The LUT is
rendered in export only (the only place pixels are re-encoded); joins are
honoured by preview and export alike through export.plan_transitions.
Every number in a record's `grade` and `joins` is a prior.

`set_look` sets the look for the whole video. What the creator already set
by hand (overlay_style after or before) is kept -- the look fills in only
what they left alone -- and the difference is shown, one click from being
reset. Changing look never silently throws a choice away.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from cutgrammar import grade

from .indexer import CACHE

DIR = Path(__file__).resolve().parent / "looks"
GRADE_SHOTS = 24     # how many of the story's shots the grade is fitted on
STYLE_KEYS = ("font", "color", "accent", "backing")
BEAT_SNAP_S = 0.25   # a word lands on the beat if it was this close already [prior]

_LOOKS: dict[str, dict] | None = None


def all_looks() -> dict[str, dict]:
    global _LOOKS
    if _LOOKS is None:
        _LOOKS = {}
        for p in sorted(DIR.glob("*.json")):
            rec = json.loads(p.read_text())
            _LOOKS[rec["id"]] = rec
    return _LOOKS


def get(look_id: str | None) -> dict | None:
    return all_looks().get(look_id or "")


def overlay_defaults(look: dict) -> dict:
    """The overlay_style fields a look sets when the creator hasn't."""
    t = look["type"]
    return {"font": t["font"], "color": t["palette"][0], "accent": t["palette"][1], "backing": t["backing"]}


def motion_of(look: dict | None) -> dict | None:
    """What overlayDraw needs to move words the look's way."""
    if not look:
        return None
    m, t = look["motion"], look["type"]
    return {"curve": m["curve"], "in_s": m["in_s"], "step_fps": m["step_fps"], "stagger_s": m["stagger_s"],
            "enter": m["enter"], "case": t["case"], "track": t["track"], "beat_lock": m["beat_lock"]}


def public() -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "line": r["line"], "font": r["type"]["font"],
             "palette": r["type"]["palette"], "status": r["status"], "review_by": r["review_by"]}
            for r in all_looks().values()]


# --------------------------------------------------------------------------
# on the board
# --------------------------------------------------------------------------

def apply(b: dict, op: dict) -> None:
    """set_look {look, reset?}. look None = no look (the plain defaults)."""
    lid = op.get("look")
    if lid is not None and lid not in all_looks():
        raise ValueError(f"no look {lid!r} — one of {', '.join(all_looks())}")
    if lid is None:
        b.pop("look", None)
    else:
        b["look"] = lid
    if op.get("reset"):
        # "use the look's": forget what was set by hand, so the look shows through
        b["style_set"] = []
        b["overlay_style"] = {k: v for k, v in (b.get("overlay_style") or {}).items() if k not in STYLE_KEYS}


def style(b: dict | None, base: dict) -> dict:
    """The overlay style the video uses: defaults, then the look, then what
    the creator set by hand. `base` is overlays.DEFAULT_STYLE."""
    b = b or {}
    set_by_hand = b.get("overlay_style") or {}
    look = get(b.get("look"))
    if not look:
        return {**base, **set_by_hand}
    kept = set(b.get("style_set") or [])
    mine = {k: v for k, v in set_by_hand.items() if k in kept or k not in STYLE_KEYS}
    return {**base, **overlay_defaults(look), **mine, "look": look["id"], "motion": motion_of(look)}


def overrides(b: dict | None) -> list[str]:
    """Fields the creator set by hand that differ from the look."""
    b = b or {}
    look = get(b.get("look"))
    if not look:
        return []
    d = overlay_defaults(look)
    mine = b.get("overlay_style") or {}
    return [k for k in b.get("style_set") or [] if k in d and mine.get(k) != d[k]]


def describe(a: dict | None, b: dict | None) -> list[dict]:
    la, lb = (a or {}).get("look"), (b or {}).get("look")
    # A field set by hand (style_set grew) is said by the overlay lines; only
    # fields handed back to the look mean the words follow it again.
    if la == lb and not set((a or {}).get("style_set") or []) - set((b or {}).get("style_set") or []):
        return []
    if lb and la != lb:
        kept = overrides(b)
        extra = f" (kept your {', '.join(kept)})" if kept else ""
        return [{"kind": "style", "text": f"Look: {get(lb)['name']} — {get(lb)['line'].rstrip('.')}{extra}"}]
    if la and not lb:
        return [{"kind": "style", "text": "Look removed: back to the plain words"}]
    if lb:
        return [{"kind": "style", "text": f"Words now follow the {get(lb)['name']} look throughout"}]
    return []


def beat_lock(items: list[dict], grid: dict | None, total: float) -> list[dict]:
    """Words that enter on the music's beat. Each overlay that starts within
    BEAT_SNAP_S of a beat moves (whole, keeping its length) onto it; others
    stay where they are. The same resolved times feed preview and export."""
    if not grid or not grid.get("bpm"):
        return items
    period = 60.0 / float(grid["bpm"])
    phase = float(grid.get("phase") or 0.0)
    out = []
    for o in items:
        if o.get("kind") == "chapters":
            out.append(o)
            continue
        k = round((o["start"] - phase) / period)
        beat = phase + k * period
        d = beat - o["start"]
        if abs(d) <= BEAT_SNAP_S and beat >= 0 and o["shown_end"] + d <= total + 1e-6:
            o = {**o, "start": round(beat, 4), "end": round(o["end"] + d, 4),
                 "shown_end": round(o["shown_end"] + d, 4), "on_beat": True}
        out.append(o)
    return out


# --------------------------------------------------------------------------
# the picture: a grade fitted to the footage, and the join family
# --------------------------------------------------------------------------

def grade_target(src: dict, g: dict) -> dict:
    """The footage's own stats, moved the look's way: the target grade.Look
    fits to. Tone: contrast scaled about the median, then the 1st percentile
    lifted or sunk to `black` with the top pinned; cast warmed or cooled;
    shadow / highlight offsets added; saturation scaled."""
    tone = np.asarray(src["tone"], dtype=np.float64)
    med = float(np.median(tone))
    tone = med + (tone - med) * float(g.get("contrast", 1.0))
    tone = np.maximum.accumulate(np.clip(tone, 0, 255))
    # tone[1] is the 1st percentile (grade.TONE_Q[1] == 1). A lifted look
    # sets a floor under it, a deep look a ceiling over it; footage already
    # past that is left alone -- "lifted" must never pull a dark frame down.
    lo, top = float(tone[1]), float(tone[-1])
    black = None
    if g.get("black_floor") is not None and lo < float(g["black_floor"]):
        black = float(g["black_floor"])
    elif g.get("black_ceiling") is not None and lo > float(g["black_ceiling"]):
        black = float(g["black_ceiling"])
    if black is not None and top > lo + 1:
        tone = np.where(tone <= lo, black * tone / max(lo, 1e-3), black + (tone - lo) * (top - black) / (top - lo))
        tone = np.maximum.accumulate(np.clip(tone, 0, 255))
    w = float(g.get("warmth", 0.0))
    cast = np.asarray(src["cast"], dtype=np.float64) + np.array([w / 2, 0.0, -w / 2])
    split = g.get("split") or {}
    shadow = np.asarray(src["shadow"], dtype=np.float64) + np.asarray(split.get("shadow") or [0, 0, 0], dtype=np.float64)
    high = np.asarray(src["high"], dtype=np.float64) + np.asarray(split.get("high") or [0, 0, 0], dtype=np.float64)
    return {"tone": [round(float(v), 2) for v in tone], "cast": [round(float(v), 2) for v in cast],
            "mid": [round(float(v), 2) for v in cast], "shadow": [round(float(v), 2) for v in shadow],
            "high": [round(float(v), 2) for v in high], "sat": round(float(src["sat"]) * float(g.get("sat", 1.0)), 4)}


def fit_grade(look: dict, px: np.ndarray, strength: float = 1.0) -> dict | None:
    """The look's grade on these pixels: a .cube in the cache (keyed on the
    look and the pixels, so the same story fits once) and what it did.
    None for a look without a grade (Clean)."""
    g = look.get("grade")
    if not g or len(px) == 0:
        return None
    src = grade.stats(px)
    fitted = grade.Look(px, grade_target(src, g), strength)
    sig = hashlib.sha1((look["id"] + json.dumps(g, sort_keys=True) + px.tobytes()[:4096].hex()
                        + str(len(px)) + str(strength)).encode()).hexdigest()[:10]
    d = CACHE / "looks"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{look['id']}-{sig}.cube"
    if not path.exists():
        grade.write_cube(fitted.lut(), str(path), f"VibeCut · {look['name']}")
    after = grade.stats(fitted(px))
    return {"lut": str(path), "strength": strength, "words": grade.words(after),
            "numbers": {"before": {x: src[x] for x in ("warmth", "black", "sat")},
                        "after": {x: after[x] for x in ("warmth", "black", "sat")}}}


def joins_of(look: dict | None) -> dict | None:
    """The look's transition family as export.plan_transitions wants it."""
    j = (look or {}).get("joins")
    if not j:
        return None
    return {"between": j["between"], "within": j["within"], "dur": float(j.get("dur") or 0.0),
            "open": bool(j.get("open")), "close": bool(j.get("close"))}


def picture(b: dict | None, px: np.ndarray | None) -> dict | None:
    """The look's picture, with the creator's own transition picks on top
    (transitions.fold): those were chosen on this video, so they win."""
    from . import transitions
    return transitions.fold(b, _picture(b, px))


def _picture(b: dict | None, px: np.ndarray | None) -> dict | None:
    """What the look adds to the board's `style` for rendering: a borrowed
    style's own look and transitions win (they were chosen on purpose);
    the look fills in whatever that left empty. `px` = the story's pixels
    (see app._story_pixels); None skips the grade (preview needs joins only)."""
    b = b or {}
    look = get(b.get("look"))
    style = dict(b.get("style") or {})
    if not look:
        return style or None
    if not (style.get("look") or style.get("transitions") or style.get("letterbox")):
        # nothing of its own to render (a style that only retimed, like the
        # bed's beat): the picture is the look's, so the export says so
        style["name"] = look["name"]
    if not style.get("transitions") and look.get("joins"):
        style["transitions"] = joins_of(look)
    if not style.get("look") and look.get("grade"):
        if px is not None and len(px):
            fit = fit_grade(look, px)
            if fit:
                style["look"] = {"lut": fit["lut"], "strength": fit["strength"], "words": fit["words"]}
        else:
            # not fitted here (preview never grades); the UI still says a grade is coming
            style["look"] = {"lut": "", "strength": 1.0, "words": [], "pending": True}
    style.setdefault("name", look["name"])
    style.setdefault("traits", [])
    style.setdefault("ref", None)
    return style


def camera(items: list[dict], b: dict | None) -> list[dict]:
    """The look's camera on the timeline's shots, for export: a slow push
    over every shot, alternating in and out (`punch`), harder on the first
    shot of a part (`scene`) -- the short-form habit Remix uses. Export-only,
    like the grade; the preview shows the frame as filmed."""
    look = get((b or {}).get("look"))
    cam = (look or {}).get("camera")
    if not cam:
        return items
    out = [dict(it) for it in items]
    starts: set[str] = set()
    for bt in (b or {}).get("beats", [])[1:]:
        if bt["shots"]:
            starts.add(bt["shots"][0].get("id"))
    k = 0
    for it in out:
        if it["kind"] != "shot" or it.get("punch"):
            continue
        z = float(cam["scene"]) if it.get("shot_id") in starts else float(cam["punch"])
        if z:
            it["punch"] = z if k % 2 == 0 else -z
        k += 1
    return out
