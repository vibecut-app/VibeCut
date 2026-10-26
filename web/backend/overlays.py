"""Words on screen: titles, part labels, name tags, captions, dates, end cards.

An overlay is part of the edit, so it lives on the working storyboard and is
changed only by operations in the same turn log as every cut (board.py):
added, edited and removed like a shot, undone like one. Nothing here renders
pixels. The browser draws overlays with one function for both the preview and
the export, so what the creator sees is what gets exported.

Three decisions carry the design:

- **Anchored, not placed.** An overlay hangs off something in the edit -- the
  whole edit, its end, a part, or one shot -- plus an offset. Move the part
  and its label moves with it; trim the edit and the end card stays at the
  end; remove the shot and the name tag over it goes too (and the diff says
  so). A time on the timeline is converted to an anchor when the op is first
  applied and recorded that way, so replay after an undo can't drift.
- **One look per video.** Font, colour, caption position and backing are
  one style for the whole edit, not per overlay. Two fonts and captions that
  wander are exactly the "surface consistency" tells VibeCut exists to
  remove, so they are made impossible rather than warned about.
- **A library, not a generator.** Suggestions pick from a fixed set of kinds
  and fill them from what the edit already knows (part titles, capture dates,
  the creator's own voiceover lines and name). Nothing invents copy: a kind
  with nothing true to say is left out rather than filled with placeholder
  text. This idea -- curated cards, the machine only picks and times them --
  comes from Overlay Studio (see NOTICE); the code is VibeCut's own.

The checks at the bottom report and never change anything: every finding
carries the number it is based on and a verdict, like cutgrammar's rules.
"""

from __future__ import annotations

import re
from datetime import datetime

FRAME = 1 / 30

# kind -> defaults. `dur` None = as long as what it hangs off.
KINDS: dict[str, dict] = {
    "title":    {"label": "Title",      "pos": "center",      "size": "L", "anim": "rise",  "dur": 3.0},
    "part":     {"label": "Part label", "pos": "bottom-left", "size": "M", "anim": "slide", "dur": 3.0},
    "name":     {"label": "Name tag",   "pos": "bottom-left", "size": "M", "anim": "slide", "dur": 4.0},
    "caption":  {"label": "Caption",    "pos": "bottom",      "size": "M", "anim": "fade",  "dur": 3.0},
    "date":     {"label": "Date",       "pos": "top-right",   "size": "S", "anim": "type",  "dur": 3.0},
    "end":      {"label": "End card",   "pos": "center",      "size": "L", "anim": "fade",  "dur": 3.0},
    "chapters": {"label": "Chapter bar", "pos": "top",        "size": "S", "anim": "fade",  "dur": None},
    # a chapter's own title in a designed look, with a plain line under it
    # (story.py; sarah's reference vlog, 2026-10-18: script "Morning Routine",
    # red spaced "OOTD", each over a plain subtitle). Its look is its own, not
    # the captions' one style.
    "heading":  {"label": "Chapter title", "pos": "center",     "size": "M", "anim": "rise",  "dur": 2.4},
}
HEADING_LOOKS = ("script", "spaced", "bold", "serif")
POSITIONS = ("top-left", "top", "top-right", "left", "center", "right",
             "bottom-left", "bottom", "bottom-right")
SIZES = ("S", "M", "L")
ANIMS = ("fade", "rise", "slide", "type", "none")
ANCHORS = ("edit", "end", "beat", "shot")

FONTS = ("Clean", "Editorial", "Rounded", "Mono", "Condensed")
BACKINGS = ("shadow", "box", "none")
DEFAULT_STYLE = {"font": "Clean", "color": "#ffffff", "accent": "#b9d9eb", "captions": "bottom",
                 "backing": "shadow"}

# Caption templates (the Style tab when a caption is clicked): how every
# caption in the video is dressed -- lettering, edge, backing -- drawn by
# overlayDraw.ts for preview and export alike. None = Soft, the quiet vlog
# caption: small, lowercase, the look's lettering, a soft shadow, low left.
# "outlined" is sarah's own hand edit: serif, black edge, the time on top.
# The last five are word art (sarah, 2026-10-18): neon, glow, a gradient, 3D
# letters and a retro hard drop, the kinds CapCut offers.
TEMPLATES = {"outlined": "Outlined", "bold": "Big & bold", "label": "Label", "highlight": "Highlighter",
             "handwritten": "Handwritten", "tape": "Typed tape", "pop": "Pop colour", "quiet": "Quiet",
             "neon": "Neon", "glow": "Glow", "gradient": "Gradient", "extrude": "3D", "retro": "Retro drop"}
# How captions arrive (the Animation tab). None = the look's own entrance.
ENTERS = {"fade": "Fade up", "pop": "Pop", "slide": "Slide in", "stamp": "Stamp", "type": "Typewriter",
          "word": "Word by word"}
# The captions' colour, picked by hand (the Captions tab). None = automatic:
# the look's colour, swapped by ink.py for one that reads over the footage.
# A picked colour is kept as picked; the edge or glow around it does the reading.
# The captions' typeface, picked by hand (the Captions tab). None = the
# template's or the look's own. Ids of web/frontend/src/captionFonts.ts, whose
# openly licensed files ship with the app so preview and export match.
TYPEFACES = {"tiktok-sans": "TikTok Sans", "montserrat": "Montserrat", "poppins": "Poppins",
             "bebas-neue": "Bebas Neue", "anton": "Anton", "archivo-black": "Archivo Black",
             "luckiest-guy": "Luckiest Guy", "bangers": "Bangers", "fredoka": "Fredoka",
             "permanent-marker": "Permanent Marker", "caveat": "Caveat", "pacifico": "Pacifico",
             "lobster": "Lobster", "playfair-display": "Playfair Display", "courier-prime": "Courier Prime"}
# The captions' outline, shadow, background box and letter weight, set by
# hand with sliders (the Captions tab; sarah, 2026-10-18). None = the
# template's own; a width / opacity of 0 = none at all. Sizes are shares of
# the letter size, so they hold at any frame size.
DRESS = {
    "outline": {"width": (0.0, 0.4)},
    "shadow": {"opacity": (0.0, 1.0), "blur": (0.0, 1.5), "dist": (0.0, 0.4)},
    "backdrop": {"opacity": (0.0, 1.0), "round": (0.0, 0.5)},
}
THICK_MAX = 0.15
DRESS_NAMES = {"outline": "outline", "shadow": "shadow", "backdrop": "background", "thick": "letter weight"}
STYLE_FIELDS = ("font", "color", "accent", "captions", "backing", "template", "enter", "text_color", "typeface",
                "outline", "shadow", "backdrop", "thick")
PICKED = ("template", "enter", "text_color", "typeface", "outline", "shadow", "backdrop", "thick")   # never come from a look, so need no marking

TEXT_MAX = 140
EDITABLE = ("text", "sub", "pos", "size", "anim", "dur", "place", "look", "lines")
# One line of a group tuned on its own (sarah, 2026-10-20: a chapter title and
# the line under it are "a group of captions" she tunes independently, like
# CapCut's grouped text). "main" is the title or the words, "sub" the line
# under a title or the place name above a caption. Each takes the Captions
# panel's own fields, plus a size and a nudge from where the group puts it
# (shares of the frame's short side). Unset = the group's look.
LINE_ROLES = ("main", "sub")
LINE_LOOK = ("text_color", "typeface", "outline", "shadow", "backdrop", "thick")
LINE_NUMS = {"scale": (0.4, 3.0), "dx": (-1.0, 1.0), "dy": (-1.0, 1.0)}
# Dragged on the picture by hand: block centre as a fraction of the frame and
# a size multiplier. Overrides pos/size (and, for captions, the caption line).
SCALE_MIN, SCALE_MAX = 0.4, 3.0


class OverlayError(Exception):
    pass


def style_of(board: dict | None) -> dict:
    """The one style for the whole video: defaults, the look (looks.py),
    then whatever the creator set by hand."""
    from . import looks
    return looks.style(board, DEFAULT_STYLE)


def _hex(v: object) -> str | None:
    if isinstance(v, str) and len(v) == 7 and v[0] == "#":
        try:
            int(v[1:], 16)
            return v.lower()
        except ValueError:
            return None
    return None


def clean_style(patch: dict) -> dict:
    out = {}
    if "font" in patch:
        if patch["font"] not in FONTS:
            raise OverlayError(f"font must be one of {', '.join(FONTS)}")
        out["font"] = patch["font"]
    for k in ("color", "accent"):
        if k in patch:
            if not _hex(patch[k]):
                raise OverlayError(f"{k} must be a colour like #ffcc00")
            out[k] = _hex(patch[k])
    if "captions" in patch:
        if patch["captions"] not in ("bottom", "center"):
            raise OverlayError("captions go at the bottom or in the center")
        out["captions"] = patch["captions"]
    if "backing" in patch:
        if patch["backing"] not in BACKINGS:
            raise OverlayError(f"backing must be one of {', '.join(BACKINGS)}")
        out["backing"] = patch["backing"]
    for k, allowed in (("template", TEMPLATES), ("enter", ENTERS), ("typeface", TYPEFACES)):
        if k in patch:
            if patch[k] is not None and patch[k] not in allowed:
                raise OverlayError(f"{k} must be one of {', '.join(allowed)}")
            out[k] = patch[k]
    for k, nums in DRESS.items():
        if k in patch:
            v = patch[k]
            if v is None:
                out[k] = None
                continue
            if not isinstance(v, dict) or not _hex(v.get("color")):
                raise OverlayError(f"{k} needs a colour like #ffcc00")
            d = {"color": _hex(v["color"])}
            for n, (lo, hi) in nums.items():
                x = v.get(n)
                if not isinstance(x, (int, float)) or isinstance(x, bool) or not lo <= x <= hi:
                    raise OverlayError(f"{k} {n} must be between {lo} and {hi}")
                d[n] = round(float(x), 3)
            out[k] = d
    if "thick" in patch:
        v = patch["thick"]
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= THICK_MAX):
            raise OverlayError(f"thick must be between 0 and {THICK_MAX}")
        out["thick"] = None if v is None else round(float(v), 3)
    if "text_color" in patch:
        if patch["text_color"] is not None and not _hex(patch["text_color"]):
            raise OverlayError("text_color must be a colour like #ffcc00")
        out["text_color"] = _hex(patch["text_color"])
    return out


def clean_lines(v) -> dict:
    """{role: look or None}; None (or an empty look) puts that line back to the group's."""
    if not isinstance(v, dict) or not v or set(v) - set(LINE_ROLES):
        raise OverlayError(f"lines are {' and '.join(LINE_ROLES)}")
    out: dict = {}
    for role, look in v.items():
        if look is None:
            out[role] = None
            continue
        if not isinstance(look, dict) or set(look) - set(LINE_LOOK) - set(LINE_NUMS):
            raise OverlayError(f"a line's look takes {', '.join(LINE_LOOK + tuple(LINE_NUMS))}")
        d = clean_style({k: look[k] for k in LINE_LOOK if k in look})
        for n, (lo, hi) in LINE_NUMS.items():
            if n in look:
                x = look[n]
                if x is not None and (not isinstance(x, (int, float)) or isinstance(x, bool) or not lo <= x <= hi):
                    raise OverlayError(f"a line's {n} must be between {lo} and {hi}")
                d[n] = None if x is None else round(float(x), 4)
        out[role] = d
    return out


def clean_fields(patch: dict, kind: str) -> dict:
    """Validate the editable fields of one overlay."""
    out = {}
    for k in ("text", "sub"):
        if k in patch:
            v = patch[k]
            if not isinstance(v, str):
                raise OverlayError(f"{k} must be text")
            out[k] = v.strip()[:TEXT_MAX]
    if "pos" in patch:
        if patch["pos"] not in POSITIONS:
            raise OverlayError(f"position must be one of {', '.join(POSITIONS)}")
        out["pos"] = patch["pos"]
    if "size" in patch:
        if patch["size"] not in SIZES:
            raise OverlayError("size must be S, M or L")
        out["size"] = patch["size"]
    if "anim" in patch:
        if patch["anim"] not in ANIMS:
            raise OverlayError(f"animation must be one of {', '.join(ANIMS)}")
        out["anim"] = patch["anim"]
    if "dur" in patch:
        d = patch["dur"]
        if d is not None:
            d = float(d)
            if not (0.3 <= d <= 3600):
                raise OverlayError("an overlay lasts between 0.3 s and an hour")
            d = round(d, 3)
        out["dur"] = d
    if "place" in patch:
        p = patch["place"]
        if p is None:
            out["place"] = None
        else:
            try:
                x, y = float(p["x"]), float(p["y"])
                sc = float(p.get("scale", 1.0))
            except (KeyError, TypeError, ValueError) as e:
                raise OverlayError("a place is {x, y, scale}") from e
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise OverlayError("a place is inside the picture (0 to 1)")
            out["place"] = {"x": round(x, 4), "y": round(y, 4),
                            "scale": round(min(SCALE_MAX, max(SCALE_MIN, sc)), 3)}
    if "look" in patch:
        if kind != "heading" or patch["look"] not in HEADING_LOOKS:
            raise OverlayError(f"a chapter title's look is one of {', '.join(HEADING_LOOKS)}")
        out["look"] = patch["look"]
    if "lines" in patch:
        out["lines"] = clean_lines(patch["lines"])
    if kind != "chapters" and "text" in out and not out["text"]:
        raise OverlayError("an overlay needs some text")
    return out


# --------------------------------------------------------------------------
# where things are in the edit
# --------------------------------------------------------------------------

def _entries(board: dict) -> list[tuple[str, str, float, float]]:
    """(beat id, entry key, seq start, seq end) in playing order."""
    out, t = [], 0.0
    for b in board.get("beats", []):
        for e in b["shots"]:
            d = (e["end"] - e["start"]) / float(e.get("speed") or 1.0)
            out.append((b["id"], e.get("key") or e["id"], t, t + d))
            t += d
    return out


def _spans(board: dict) -> tuple[dict, dict, float]:
    """beat id -> (start, end), entry key -> (start, end), total."""
    beats: dict[str, list[float]] = {}
    shots: dict[str, tuple[float, float]] = {}
    total = 0.0
    for bid, k, a, z in _entries(board):
        shots[k] = (a, z)
        if bid in beats:
            beats[bid][1] = z
        else:
            beats[bid] = [a, z]
        total = z
    return {k: tuple(v) for k, v in beats.items()}, shots, total


def anchor_span(board: dict, anchor: dict) -> tuple[float, float] | None:
    beats, shots, total = _spans(board)
    to = anchor.get("to")
    if to in ("edit", "end"):
        return (0.0, total) if total > 0 else None
    if to == "beat":
        return beats.get(anchor.get("id"))
    if to == "shot":
        return shots.get(anchor.get("id"))
    return None


def exists(board: dict, anchor: dict) -> bool:
    return anchor_span(board, anchor) is not None


def anchor_at(board: dict, t: float, prefer: dict | None = None) -> tuple[dict, float]:
    """A sequence time -> (anchor, offset). Edit- and end-anchored overlays
    stay that way; everything else hangs off whatever is under `t`."""
    beats, shots, total = _spans(board)
    if total <= 0:
        raise OverlayError("there is no edit to put an overlay on")
    t = max(0.0, min(t, total - FRAME))
    to = (prefer or {}).get("to")
    if to == "edit":
        return {"to": "edit"}, round(t, 3)
    if to == "end":
        return {"to": "end"}, round(total - t, 3)
    if to == "beat":
        for bid, (a, z) in beats.items():
            if a <= t < z:
                return {"to": "beat", "id": bid}, round(t - a, 3)
    for k, (a, z) in shots.items():
        if a <= t < z:
            return {"to": "shot", "id": k}, round(t - a, 3)
    raise OverlayError(f"nothing in the edit at {t:.2f}s")


def resolve(board: dict | None, items: list[dict] | None = None) -> list[dict]:
    """Every overlay (or `items` anchored the same way: graphics.py) with its
    sequence start and end, in time order."""
    if not board:
        return []
    beats, shots, total = _spans(board)
    out = []
    for o in board.get("overlays", []) if items is None else items:
        span = anchor_span(board, o["anchor"])
        if span is None:
            continue
        a, z = span
        if o["anchor"]["to"] == "end":
            start = total - o["at"]
            length = o["dur"] if o["dur"] is not None else o["at"]
        else:
            start = a + min(o["at"], max(0.0, z - a - FRAME))
            length = o["dur"] if o["dur"] is not None else (z - a) - (start - a)
        start = max(0.0, start)
        end = start + max(length, FRAME)
        out.append({**o, "start": round(start, 3), "end": round(end, 3),
                    "shown_end": round(min(end, total), 3)})
    out.sort(key=lambda x: (x["start"], x["id"]))
    return out


# --------------------------------------------------------------------------
# ops (called from board.apply, which owns copying and the log)
# --------------------------------------------------------------------------

def add(b: dict, op: dict, new_id) -> None:
    kind = op.get("kind")
    if kind not in KINDS:
        raise OverlayError(f"unknown overlay kind {kind!r}")
    if kind == "chapters" and len(b.get("beats", [])) < 2:
        raise OverlayError("a chapter bar needs at least two parts")
    d = KINDS[kind]
    if "anchor" not in op:
        # First application: turn where it was asked for into an anchor.
        if op.get("beat"):
            op["anchor"], op["at"] = {"to": "beat", "id": op.pop("beat")}, float(op.get("at", 0.0))
        elif op.get("shot"):
            op["anchor"], op["at"] = {"to": "shot", "id": op.pop("shot")}, float(op.get("at", 0.0))
        elif kind in ("end",):
            op["anchor"], op["at"] = {"to": "end"}, float(d["dur"])
        elif kind in ("chapters",):
            op["anchor"], op["at"] = {"to": "edit"}, 0.0
        else:
            op["anchor"], op["at"] = anchor_at(b, float(op.pop("start", 0.0)))
    op.pop("start", None)
    if op["anchor"].get("to") not in ANCHORS:
        raise OverlayError("an overlay hangs off the edit, its end, a part or a shot")
    if not exists(b, op["anchor"]):
        raise OverlayError("what that overlay was attached to is no longer in the edit")
    op.setdefault("id", new_id())
    if any(o["id"] == op["id"] for o in b.get("overlays", [])):
        raise OverlayError(f"overlay {op['id']} already exists")
    fields = clean_fields({k: op[k] for k in EDITABLE if k in op}, kind)
    o = {"id": op["id"], "kind": kind, "text": "", "sub": "",
         "pos": d["pos"], "size": d["size"], "anim": d["anim"], "dur": d["dur"],
         "anchor": dict(op["anchor"]), "at": round(max(0.0, float(op["at"])), 3), **fields}
    if kind == "caption":
        o["pos"] = "bottom"     # captions follow the one caption position
    if kind == "heading":
        o.setdefault("look", "spaced")    # thin, white, spaced capitals: the day-vlog chapter title
    if kind != "chapters" and not o["text"]:
        raise OverlayError("an overlay needs some text")
    b.setdefault("overlays", []).append(o)


def _find(b: dict, oid: str | None) -> dict:
    for o in b.get("overlays", []):
        if o["id"] == oid:
            return o
    if oid in ("all_captions", "all_titles"):   # the chat's every-caption edit
        kind, what = ("caption", "captions") if oid == "all_captions" else ("heading", "chapter titles")
        if any(o["kind"] == kind for o in b.get("overlays", [])):
            raise OverlayError(f"every one of the {what} at once can only be moved, sized or removed")
        raise OverlayError(f"there are no {what} in this edit")
    raise OverlayError(f"no overlay {oid}")


def edit(b: dict, op: dict) -> None:
    o = _find(b, op.get("overlay"))
    if "start" in op:
        # Moved on the timeline: re-anchor where it landed, record the anchor.
        op["anchor"], op["at"] = anchor_at(b, float(op.pop("start")), prefer=o["anchor"])
    if "anchor" in op:
        if not exists(b, op["anchor"]):
            raise OverlayError("that overlay's new place is no longer in the edit")
        o["anchor"], o["at"] = dict(op["anchor"]), round(max(0.0, float(op.get("at", 0.0))), 3)
    fields = clean_fields({k: op[k] for k in EDITABLE if k in op}, o["kind"])
    if o["kind"] == "caption":
        fields.pop("pos", None)
    if not fields and "anchor" not in op:
        raise OverlayError("nothing to change")
    if "lines" in fields:
        # one line's look merges into what it had; a field set to None goes
        lines = dict(o.get("lines") or {})
        for role, look in fields.pop("lines").items():
            merged = {k: x for k, x in {**(lines.get(role) or {}), **(look or {})}.items() if x is not None} if look else {}
            if merged:
                lines[role] = merged
            else:
                lines.pop(role, None)
        if lines:
            o["lines"] = lines
        else:
            o.pop("lines", None)
    o.update(fields)


def drop(b: dict, op: dict) -> None:
    o = _find(b, op.get("overlay"))
    b["overlays"].remove(o)


def set_style(b: dict, op: dict) -> None:
    patch = clean_style({k: op[k] for k in STYLE_FIELDS if k in op})
    if not patch:
        raise OverlayError("nothing to change")
    b["overlay_style"] = {**(b.get("overlay_style") or {}), **patch}
    # Remembered as set by hand, so a later look fills in only the rest. The
    # profile's saved defaults (source "profile") are a starting point, not
    # a choice made on this video: a look replaces them.
    # (A template, an entrance or a picked colour never comes from a look, so it needs no marking.)
    if op.get("source") != "profile" and set(patch) - set(PICKED):
        b["style_set"] = sorted(set(b.get("style_set") or []) | (set(patch) - set(PICKED)))


def prune(b: dict) -> None:
    """Overlays go with what they hang off, and so do graphics."""
    from . import graphics
    graphics.prune(b)
    if b.get("overlays"):
        b["overlays"] = [o for o in b["overlays"] if exists(b, o["anchor"])]
        if not b["overlays"]:
            b.pop("overlays")
        elif len(b.get("beats", [])) < 2:
            b["overlays"] = [o for o in b["overlays"] if o["kind"] != "chapters"]


# --------------------------------------------------------------------------
# diff lines
# --------------------------------------------------------------------------

def _name(o: dict) -> str:
    label = KINDS[o["kind"]]["label"].lower()
    text = o.get("text") or ""
    if not text:
        return label
    return f"{label} “{text if len(text) <= 32 else text[:31] + '…'}”"


def describe(a: dict | None, b: dict | None) -> list[dict]:
    A = {o["id"]: o for o in (a or {}).get("overlays", [])}
    B = {o["id"]: o for o in (b or {}).get("overlays", [])}
    lines = []
    added = [o for k, o in B.items() if k not in A]
    removed = [o for k, o in A.items() if k not in B]
    if len(added) > 3:
        counts: dict[str, int] = {}
        for o in added:
            counts[o["kind"]] = counts.get(o["kind"], 0) + 1
        def one(label: str) -> str:
            return ("an " if label[0] in "aeiou" else "a ") + label
        parts = [f"{n} {KINDS[k]['label'].lower()}s" if n > 1 else one(KINDS[k]["label"].lower())
                 for k, n in sorted(counts.items(), key=lambda kv: list(KINDS).index(kv[0]))]
        lines.append({"kind": "added", "text": f"Added {what_list(parts)}"})
    else:
        lines += [{"kind": "added", "text": f"Added the {_name(o)}"} for o in added]
    for o in removed:
        gone = b is not None and not exists(b, o["anchor"])
        lines.append({"kind": "removed", "text": f"Removed the {_name(o)}"
                      + (" with what it was on" if gone else "")})
    for k, o in B.items():
        if k not in A:
            continue
        old = A[k]
        what = []
        if old["text"] != o["text"] or old["sub"] != o["sub"]:
            what.append("words")
        if old["anchor"] != o["anchor"] or abs(old["at"] - o["at"]) > 0.005:
            what.append("timing")
        if old["dur"] != o["dur"]:
            what.append("length")
        if old.get("look") != o.get("look"):
            what.append("style")
        if (old["pos"], old.get("place")) != (o["pos"], o.get("place")):
            what.append("place")
        if old["size"] != o["size"]:
            what.append("size")
        if old["anim"] != o["anim"]:
            what.append("animation")
        if old.get("lines") != o.get("lines"):
            what.append("look")
        if what:
            lines.append({"kind": "retitled", "text": f"Changed the {what_list(what)} of the {_name(o)}"})
    sa, sb_ = (a or {}).get("overlay_style"), (b or {}).get("overlay_style")
    if b is not None and sa != sb_ and sb_:
        sa_, sb2 = style_of(a), style_of(b)
        for k, names, what in (("template", TEMPLATES, "Captions"), ("enter", ENTERS, "Captions come in"),
                               ("typeface", TYPEFACES, "Caption font")):
            if sa_.get(k) != sb2.get(k):
                v = sb2.get(k)
                # no template = the quiet vlog caption, called Soft in the Style tab
                none = "Soft" if k == "template" else "back to the look's own"
                lines.append({"kind": "retitled", "text": f"{what}: {names[v]}" if v else f"{what}: {none}"})
        dressed = [DRESS_NAMES[k] for k in DRESS_NAMES if sa_.get(k) != sb2.get(k)]
        if dressed:
            lines.append({"kind": "retitled", "text": f"Changed the captions' {what_list(dressed)}"})
        if sa_.get("text_color") != sb2.get("text_color"):
            v = sb2.get("text_color")
            lines.append({"kind": "retitled", "text": f"Caption colour: {v}" if v else "Caption colour: automatic"})
        changed = [k for k in ("font", "color", "accent", "captions", "backing")
                   if style_of(a).get(k) != style_of(b).get(k)]
        if changed:
            lines.append({"kind": "retitled", "text": "Text style: " + ", ".join(
                f"{k} {style_of(b)[k]}" for k in changed)})
    return _fold(lines)


def _fold(lines: list[dict]) -> list[dict]:
    """The same change to many overlays (every caption moved at once) reads as
    one line, not one per caption."""
    groups: dict[str, list[tuple[int, str]]] = {}
    for i, l in enumerate(lines):
        m = re.match(r"Changed the (.+) of the (.+?) “", l["text"]) if l["kind"] == "retitled" else None
        if m:
            groups.setdefault(m.group(1), []).append((i, m.group(2)))
    drop, put = set(), {}
    for what, ix in groups.items():
        if len(ix) > 3:
            counts: dict[str, int] = {}
            for _, label in ix:
                counts[label] = counts.get(label, 0) + 1
            many = [f"{n} {label}s" if n > 1 else ("an " if label[0] in "aeiou" else "a ") + label
                    for label, n in counts.items()]
            put[ix[0][0]] = {"kind": "retitled", "text": f"Changed the {what} of {what_list(many)}"}
            drop |= {i for i, _ in ix[1:]}
    return [put.get(i, l) for i, l in enumerate(lines) if i not in drop]


def what_list(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


# --------------------------------------------------------------------------
# suggestions: fill kinds from what the edit already knows
# --------------------------------------------------------------------------

def _clip_when(cat, key: str) -> datetime | None:
    sid = key.split("~")[0]
    s = cat.shots.get(sid)
    return s.when if s else None


def suggest(board: dict, cat, profile: dict | None = None, title: str | None = None,
            kinds: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """-> (add_overlay ops for what's missing, notes on what was left out and why).

    Only adds: an overlay already there is the creator's, and suggesting
    again never replaces it."""
    profile = profile or {}
    want = set(kinds or ("title", "part", "date", "caption", "name", "end"))
    have = board.get("overlays", [])
    have_kinds = {o["kind"] for o in have}
    have_beats = {o["anchor"].get("id") for o in have if o["anchor"].get("to") == "beat"}
    beats = board.get("beats", [])
    ops: list[dict] = []
    notes: list[str] = []
    voice = board.get("option") == "voice"

    if "title" in want and "title" not in have_kinds:
        text = (title or "").strip() or board.get("name", "")
        if text and text not in ("Your cut",):
            ops.append({"op": "add_overlay", "kind": "title", "text": text[:60], "anchor": {"to": "edit"}, "at": 0.4})
        else:
            notes.append("No opening title: say what the video is (or type a title) and it will use that.")

    if "part" in want and not voice and len(beats) >= 2:
        # The first part is introduced by the title; label the rest.
        for i, bt in enumerate(beats):
            if i == 0 and ("title" in have_kinds or any(o["kind"] == "title" for o in ops)):
                continue
            if bt["id"] in have_beats:
                continue
            ops.append({"op": "add_overlay", "kind": "part", "text": bt["title"],
                        "sub": f"Part {i + 1}", "anchor": {"to": "beat", "id": bt["id"]}, "at": 0.3})
    elif "part" in want and len(beats) < 2:
        notes.append("No part labels: the story has only one part.")

    if "date" in want and "date" not in have_kinds and not voice:
        # A date where the day changes -- only when there is more than one day.
        days, first = [], {}
        for bt in beats:
            for e in bt["shots"]:
                if e.get("gap") or not e.get("id"):
                    continue
                w = _clip_when(cat, e["id"])
                if w and w.date() not in first:
                    first[w.date()] = (bt["id"], e.get("key") or e["id"], w)
                    days.append(w.date())
                break
        if len(days) >= 2:
            for d in days:
                _, k, w = first[d]
                ops.append({"op": "add_overlay", "kind": "date", "text": w.strftime("%a %-d %b").upper(),
                            "anchor": {"to": "shot", "id": k}, "at": 0.2})
        else:
            notes.append("No date stamps: everything was filmed on one day (or undated).")

    if "caption" in want and "caption" not in have_kinds:
        if voice:
            for bt in beats:
                line = bt.get("line") or bt["title"]
                ops.append({"op": "add_overlay", "kind": "caption", "text": line,
                            "anchor": {"to": "beat", "id": bt["id"]}, "at": 0.0, "dur": None})
        elif kinds and "caption" in kinds:
            notes.append("No captions: there is no voiceover to take the words from. Start from "
                         "“Follow the voiceover”, or add captions by hand.")

    if "name" in want and "name" not in have_kinds:
        name = (profile.get("name") or "").strip()
        handle = (profile.get("handle") or "").strip()
        cam = None
        for bt in beats:
            for e in bt["shots"]:
                s = cat.shots.get(e.get("id") or "")
                if s and s.face_area >= 0.04 and e["end"] - e["start"] >= 2.5:
                    cam = e.get("key") or e["id"]
                    break
            if cam:
                break
        if name and cam:
            # Never on top of the opening title: two things arriving at once
            # means neither gets read.
            _, shots, _ = _spans(board)
            cam_start = shots[cam][0]
            titled = "title" in have_kinds or any(o["kind"] == "title" for o in ops)
            title_end = 0.4 + KINDS["title"]["dur"] if titled else 0.0
            ops.append({"op": "add_overlay", "kind": "name", "text": name,
                        "sub": handle if handle.startswith("@") or not handle else "@" + handle,
                        "anchor": {"to": "shot", "id": cam}, "at": round(max(0.5, title_end + 0.3 - cam_start), 3)})
        elif not name:
            notes.append("No name tag: add your name in Creator profile first.")
        else:
            notes.append("No name tag: no shot of you talking to the camera.")

    if "end" in want and "end" not in have_kinds:
        handle = (profile.get("handle") or "").strip()
        sub = (handle if handle.startswith("@") else "@" + handle) if handle else ""
        ops.append({"op": "add_overlay", "kind": "end", "text": "Thanks for watching", "sub": sub,
                    "anchor": {"to": "end"}, "at": 3.0})

    return ops, notes


def style_from_profile(profile: dict | None) -> dict:
    p = profile or {}
    out = {}
    if p.get("font") in FONTS:
        out["font"] = p["font"]
    if _hex(p.get("color")):
        out["accent"] = _hex(p["color"])
    if p.get("captionPosition") == "Middle":
        out["captions"] = "center"
    return out


# --------------------------------------------------------------------------
# checks: report, never change
# --------------------------------------------------------------------------

# Viewers read on-screen text at about 15 characters a second (the usual
# subtitle ceiling is 17); CJK is denser, ~7 a second. Plus a beat to notice
# the text arrived at all. Guesses in the same sense as cutgrammar's
# thresholds: they rank findings, they don't change anything.
CPS_LATIN = 15.0
CPS_CJK = 7.0
NOTICE_S = 0.5
MAX_ON_SCREEN = 2
FACE_AREA_CAM = 0.04
MIDDLE = {"left", "center", "right"}


def read_time(text: str) -> float:
    cjk = sum(1 for ch in text if "㐀" <= ch <= "鿿" or "぀" <= ch <= "ヿ")
    rest = len(text) - cjk
    return NOTICE_S + cjk / CPS_CJK + rest / CPS_LATIN


def _region(o: dict, style: dict) -> str:
    if o.get("place"):
        # placed by hand: judge it where it is, still only warn
        p = o["place"]
        row = "top" if p["y"] < 0.33 else "bottom" if p["y"] > 0.67 else ""
        col = "left" if p["x"] < 0.33 else "right" if p["x"] > 0.67 else ""
        return "-".join(x for x in (row, col) if x) or "center"
    if o["kind"] == "caption":
        return "center" if style["captions"] == "center" else "bottom"
    return o["pos"]


def check(board: dict | None, cat=None) -> list[dict]:
    """Findings: {overlay, rule, value, verdict, basis, message}."""
    if not board:
        return []
    items = resolve(board)
    style = style_of(board)
    _, shots, total = _spans(board)
    out = []

    def f(o, rule, value, verdict, message, basis="edit"):
        out.append({"overlay": o["id"], "rule": rule, "value": round(value, 3), "verdict": verdict,
                    "basis": basis, "message": message})

    for o in items:
        shown = o["shown_end"] - o["start"]
        # 1. Past the end: the viewer never sees the rest.
        lost = o["end"] - o["shown_end"]
        if lost > FRAME:
            f(o, "cut_off", lost, "bad" if lost >= shown else "warn",
              f"The edit ends {lost:.1f}s before this does." if lost < shown
              else "It starts after the edit has ended.")
        # 2. On screen too briefly to read.
        # Subtitles of speech go at the speaker's pace; that's not the overlay's fault.
        if o["kind"] != "chapters" and not o.get("speech"):
            need = read_time(o["text"] + " " + o.get("sub", ""))
            ratio = shown / need if need else 9
            if ratio < 1:
                f(o, "read_time", ratio, "bad" if ratio < 0.6 else "warn",
                  f"On screen {shown:.1f}s; reading it takes about {need:.1f}s.")
        # 3. Middle of the frame over someone talking to camera -- judged
        #    from the shot's best still, so it's a warning, never 'bad'.
        if cat is not None and _region(o, style) in MIDDLE:
            for k, (a, z) in shots.items():
                if a < o["shown_end"] and o["start"] < z:
                    s = cat.shots.get(k.split("~")[0])
                    if s and s.face_area >= FACE_AREA_CAM:
                        f(o, "over_face", s.face_area, "warn",
                          "May cover the face of someone talking to camera (judged from one frame).",
                          basis="still")
                        break

    # 4. Two in the same place at once draw on top of each other.
    # 5. More than two at once is clutter, wherever they are.
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if b["start"] >= a["shown_end"]:
                break
            ov = min(a["shown_end"], b["shown_end"]) - b["start"]
            if ov > FRAME and _region(a, style) == _region(b, style) and "chapters" not in (a["kind"], b["kind"]):
                f(b, "collides", ov, "bad", f"Overlaps the {_name(a)} in the same spot for {ov:.1f}s.")
    edges = sorted({x for o in items for x in (o["start"], o["shown_end"])})
    for t0, t1 in zip(edges, edges[1:]):
        on = [o for o in items if o["start"] <= t0 and o["shown_end"] >= t1 and o["kind"] != "chapters"]
        if len(on) > MAX_ON_SCREEN and t1 - t0 > FRAME:
            f(on[-1], "crowded", len(on), "warn", f"{len(on)} overlays on screen at once around "
              f"{int(t0 // 60)}:{t0 % 60:04.1f}.")
            break
    # One finding per (overlay, rule).
    seen, uniq = set(), []
    for x in out:
        k = (x["overlay"], x["rule"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq
