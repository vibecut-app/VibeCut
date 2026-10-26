"""Graphic animations: a fixed set of animated pieces drawn on top of the
footage (sarah, 2026-10-19: "make it an extra tool on the right called
graphic animations").

A title card that builds itself, a chapter opener, a route drawn between the
day's stops, a place pin, a camcorder frame, a clock, stickers that bounce on
the beat, sparkles, a hand-drawn circle and a progress bar. Each is code
drawn over the frames the creator filmed -- never generated video, never a
frame from anywhere else -- by one function in the browser
(web/frontend/src/graphicDraw.ts) for the preview and the export alike, the
way captions are.

They live on the board as `graphics`, changed only by ops in the same turn
log as every cut: added, edited, removed and undone like a caption, and
anchored the same way (overlays.py: the whole edit, a part, or a shot, plus
an offset), so a piece moves with what it hangs off and goes with it. They
are kept apart from the captions so the Captions switch, the caption checks
and the writer never touch them.

What a piece says comes only from what the edit already knows -- the video's
name and days, a part's title, the place a clip was filmed, its recording
time. A piece with nothing true to show (a route with no places) says why
instead of being offered. The beat, the camcorder's clock, the clock's time
and the route are read per request from the edit as it stands, never stored,
so they follow every cut.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta

from . import overlays as ov

# piece -> how it's added: what it hangs off by default, how long it lasts
# (None = as long as what it hangs off), its own colour, whether it carries
# words. Durations and colours are priors.
PIECES: dict[str, dict] = {
    "title":     {"label": "Title card",     "hang": "edit",  "dur": 3.5,  "tint": "#ffffff", "words": True},
    "chapter":   {"label": "Chapter opener", "hang": "part",  "dur": 3.2,  "tint": "#f6ead7", "words": True},
    "route":     {"label": "Route map",      "hang": "shot",  "dur": 4.0,  "tint": "#c97b84", "words": False},
    "pin":       {"label": "Place pin",      "hang": "shot",  "dur": 3.0,  "tint": "#c97b84", "words": True},
    "camcorder": {"label": "Camcorder",      "hang": "here",  "dur": None, "tint": "#ffffff", "words": True},
    "clock":     {"label": "Clock",          "hang": "shot",  "dur": 3.5,  "tint": "#c97b84", "words": True},
    "stickers":  {"label": "Beat sticker",   "hang": "shot",  "dur": 3.0,  "tint": "#e8b4b8", "words": False},
    "sparkles":  {"label": "Sparkles",       "hang": "shot",  "dur": 3.0,  "tint": "#ffe08a", "words": False},
    "circle":    {"label": "Circle it",      "hang": "shot",  "dur": 3.0,  "tint": "#c96f58", "words": True},
    "progress":  {"label": "Progress bar",   "hang": "edit",  "dur": None, "tint": "#ffffff", "words": False},
}
STICKERS = ("heart", "star", "smile", "sun", "flower", "bolt", "note", "sparkle")
OPS = ("add_graphic", "edit_graphic", "drop_graphic")
EDITABLE = ("text", "sub", "tint", "place", "dur", "sticker", "size")
TEXT_MAX = 80
SAME_PLACE_M = 150.0    # one stop of the route, as brief.SAME_PLACE_M
MAX_STOPS = 8


class GraphicError(Exception):
    pass


def label(piece: str) -> str:
    return PIECES.get(piece, {}).get("label", "graphic")


# --------------------------------------------------------------------------
# ops (called from board.apply, which owns copying and the log)
# --------------------------------------------------------------------------

def _clean(patch: dict, piece: str) -> dict:
    out = {}
    for k in ("text", "sub"):
        if k in patch:
            if not isinstance(patch[k], str):
                raise GraphicError(f"{k} must be text")
            out[k] = patch[k].strip()[:TEXT_MAX]
    if "tint" in patch:
        v = patch["tint"]
        if v is not None and not ov._hex(v):
            raise GraphicError("a colour is like #ffcc00")
        out["tint"] = ov._hex(v) if v else None
    if "sticker" in patch:
        if piece != "stickers" or patch["sticker"] not in STICKERS:
            raise GraphicError(f"a sticker is one of {', '.join(STICKERS)}")
        out["sticker"] = patch["sticker"]
    if "dur" in patch:
        d = patch["dur"]
        if d is not None:
            d = float(d)
            if not 0.5 <= d <= 3600:
                raise GraphicError("a graphic lasts between half a second and an hour")
            d = round(d, 3)
        out["dur"] = d
    if "place" in patch:
        # the same {x, y, scale} as a caption dragged on the picture; how big
        # it is lives in `size`, so it can change without moving it
        out.update(ov.clean_fields({"place": patch["place"]}, "graphic"))
    if "size" in patch:
        try:
            out["size"] = round(min(ov.SCALE_MAX, max(ov.SCALE_MIN, float(patch["size"]))), 3)
        except (TypeError, ValueError) as e:
            raise GraphicError("a size is a number, 1 = as it comes") from e
    return out


def add(b: dict, op: dict, new_id) -> None:
    piece = op.get("piece")
    if piece not in PIECES:
        raise GraphicError(f"unknown graphic {piece!r}")
    d = PIECES[piece]
    if "anchor" not in op:
        # First application: where it was asked for becomes an anchor.
        t = float(op.pop("start", 0.0))
        hang = d["hang"]
        if hang == "edit":
            op["anchor"], op["at"] = {"to": "edit"}, 0.0 if piece == "progress" else max(0.0, t)
        elif hang == "part":   # a chapter opener opens its part
            a, _ = ov.anchor_at(b, t, prefer={"to": "beat"})
            op["anchor"], op["at"] = a, 0.0
        elif hang == "here":   # from here to the end of the part
            op["anchor"], op["at"] = ov.anchor_at(b, t, prefer={"to": "beat"})
        else:
            op["anchor"], op["at"] = ov.anchor_at(b, t)
    op.pop("start", None)
    if not ov.exists(b, op["anchor"]):
        raise GraphicError("what that graphic was on is no longer in the edit")
    op.setdefault("id", "g" + new_id())
    if any(g["id"] == op["id"] for g in b.get("graphics", [])):
        raise GraphicError(f"graphic {op['id']} already exists")
    fields = _clean({k: op[k] for k in EDITABLE if k in op}, piece)
    g = {"id": op["id"], "piece": piece, "anchor": dict(op["anchor"]), "at": round(max(0.0, float(op.get("at", 0.0))), 3),
         "dur": d["dur"], "text": "", "sub": "", "tint": None, **fields}
    if piece == "stickers":
        g.setdefault("sticker", "heart")
    b.setdefault("graphics", []).append(g)


def _find(b: dict, gid: str | None) -> dict:
    for g in b.get("graphics", []):
        if g["id"] == gid:
            return g
    raise GraphicError(f"no graphic {gid}")


def edit(b: dict, op: dict) -> None:
    g = _find(b, op.get("graphic"))
    if "start" in op:
        # moved on the timeline: re-anchored where it landed
        op["anchor"], op["at"] = ov.anchor_at(b, float(op.pop("start")), prefer=g["anchor"])
    if "anchor" in op:
        if not ov.exists(b, op["anchor"]):
            raise GraphicError("that graphic's new place is no longer in the edit")
        g["anchor"], g["at"] = dict(op["anchor"]), round(max(0.0, float(op.get("at", 0.0))), 3)
    fields = _clean({k: op[k] for k in EDITABLE if k in op}, g["piece"])
    if not fields and "anchor" not in op:
        raise GraphicError("nothing to change")
    g.update(fields)


def drop(b: dict, op: dict) -> None:
    b["graphics"].remove(_find(b, op.get("graphic")))
    if not b["graphics"]:
        b.pop("graphics")


def apply(b: dict, op: dict, new_id) -> None:
    kind = op.get("op")
    try:
        {"add_graphic": lambda: add(b, op, new_id), "edit_graphic": lambda: edit(b, op),
         "drop_graphic": lambda: drop(b, op)}[kind]()
    except ov.OverlayError as e:
        raise GraphicError(str(e)) from e


def prune(b: dict) -> None:
    """Graphics go with what they hang off, like captions."""
    if b.get("graphics"):
        b["graphics"] = [g for g in b["graphics"] if ov.exists(b, g["anchor"])]
        if not b["graphics"]:
            b.pop("graphics")


def describe(a: dict | None, b: dict | None) -> list[dict]:
    A = {g["id"]: g for g in (a or {}).get("graphics", [])}
    B = {g["id"]: g for g in (b or {}).get("graphics", [])}
    lines = []
    for k, g in B.items():
        if k not in A:
            lines.append({"kind": "added", "text": f"Added the {label(g['piece']).lower()}"})
    for k, g in A.items():
        if k not in B:
            gone = b is not None and not ov.exists(b, g["anchor"])
            lines.append({"kind": "removed", "text": f"Removed the {label(g['piece']).lower()}"
                          + (" with what it was on" if gone else "")})
    for k, g in B.items():
        old = A.get(k)
        if not old:
            continue
        what = []
        if (old["text"], old["sub"]) != (g["text"], g["sub"]):
            what.append("words")
        if old["anchor"] != g["anchor"] or abs(old["at"] - g["at"]) > 0.005:
            what.append("timing")
        if old["dur"] != g["dur"]:
            what.append("length")
        if old.get("place") != g.get("place"):
            what.append("place")
        if old.get("size", 1) != g.get("size", 1):
            what.append("size")
        if old.get("tint") != g.get("tint"):
            what.append("colour")
        if old.get("sticker") != g.get("sticker"):
            what.append("sticker")
        if what:
            lines.append({"kind": "retitled", "text": f"Changed the {ov.what_list(what)} of the {label(g['piece']).lower()}"})
    return lines


# --------------------------------------------------------------------------
# what the edit knows: words to start from, and what a piece can show
# --------------------------------------------------------------------------

def _when(cat, e: dict) -> datetime | None:
    s = cat.shots.get((e.get("id") or "").split("~")[0]) if e.get("id") else None
    if not s or s.when is None:
        return None
    return s.when + timedelta(seconds=max(0.0, e["start"] - s.start))


def _gps(cat, e: dict):
    s = cat.shots.get((e.get("id") or "").split("~")[0]) if e.get("id") else None
    return s.gps if s and s.gps else None


def _entries(board: dict) -> list[tuple[dict, dict, float, float]]:
    """(beat, entry, seq start, seq end) in playing order."""
    out, t = [], 0.0
    for bt in board.get("beats", []):
        for e in bt["shots"]:
            d = (e["end"] - e["start"]) / float(e.get("speed") or 1.0)
            out.append((bt, e, t, t + d))
            t += d
    return out


def _at(board: dict, t: float) -> tuple[dict, dict, float, float] | None:
    es = _entries(board)
    for x in es:
        if x[2] <= t < x[3]:
            return x
    return es[-1] if es else None


def _metres(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


def stops(board: dict | None, cat, found: dict | None = None) -> list[dict]:
    """The day's stops in the order the video shows them: [{gps, name, start}],
    a new stop when the place moves on more than SAME_PLACE_M; a return visit
    is the stop it returns to. `start` = where it first shows (edit seconds)."""
    from . import places as pl
    out: list[dict] = []
    for _, e, a, _z in _entries(board or {}):
        g = _gps(cat, e) if not e.get("gap") else None
        if not g:
            continue
        if any(_metres(s["gps"], g) <= SAME_PLACE_M for s in out):
            continue
        out.append({"gps": [float(g[0]), float(g[1])], "name": pl.name_at(g, found) if found else None, "start": a})
    return out[:MAX_STOPS]


def can(board: dict | None, cat) -> dict[str, str | None]:
    """Per piece: None = ready, else why not, in her words."""
    if not board or not board.get("beats"):
        return {p: "Make your video first" for p in PIECES}
    out: dict[str, str | None] = {p: None for p in PIECES}
    if len(stops(board, cat)) < 2:
        out["route"] = "Needs clips filmed in at least two places, with the phone's location saved"
    if not any(_when(cat, e) for _, e, _, _ in _entries(board) if not e.get("gap")):
        out["clock"] = "Needs clips with a recording time"
    return out


def _date(w: datetime) -> str:
    return f"{w:%B} {w.day}, {w.year}"


def _days(cat, board: dict) -> str:
    ws = sorted(w for w in (_when(cat, e) for _, e, _, _ in _entries(board)) if w)
    if not ws:
        return ""
    a, z = ws[0], ws[-1]
    if a.date() == z.date():
        return _date(a)
    if (a.year, a.month) == (z.year, z.month):
        return f"{a:%B} {a.day}–{z.day}, {a.year}"
    return f"{a:%B} {a.day} – {z:%B} {z.day}, {z.year}"


def words(piece: str, board: dict, cat, t: float, name: str, found: dict | None = None) -> dict:
    """The words a piece starts with, from what the edit knows; never made up."""
    from . import places as pl
    here = _at(board, t)
    bt, e = (here[0], here[1]) if here else (None, None)
    w = _when(cat, e) if e else None
    if piece == "title":
        days = _days(cat, board)
        # projects.auto_name: "Sep 22", "Sep 22–24", or "New video" before the clips are read
        dated = name == "New video" or bool(re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d", name or ""))
        first = next((s["name"] for s in stops(board, cat, found) if s["name"]), None)
        if dated:   # the name is already the day: under it, the place or the weekday
            ws = sorted(x for x in (_when(cat, e2) for _, e2, _, _ in _entries(board)) if x)
            return {"text": name if name != "New video" else (days or "My day"),
                    "sub": first or (f"{ws[0]:%A}" if ws else "")}
        return {"text": name or "My day", "sub": days}
    if piece == "chapter" and bt:
        n = [b["id"] for b in board["beats"]].index(bt["id"]) + 1
        return {"text": bt["title"], "sub": f"{n:02d}"}
    if piece == "pin":
        place = pl.name_at(_gps(cat, e), found) if e and found and _gps(cat, e) else None
        return {"text": place or (bt["title"] if bt else "Here")}
    if piece == "camcorder":
        return {"text": f"{w:%b %d %Y}".upper() if w else ""}
    return {}


def op_for(piece: str, board: dict, cat, t: float, name: str, found: dict | None = None, **picked) -> dict:
    """The add_graphic op for a piece put on at `t` (the playhead)."""
    if piece not in PIECES:
        raise GraphicError(f"unknown graphic {piece!r}")
    why = can(board, cat).get(piece)
    if why:
        raise GraphicError(why)
    op = {"op": "add_graphic", "piece": piece, "start": round(max(0.0, t), 3), **words(piece, board, cat, t, name, found)}
    for k in ("tint", "sticker", "place", "size"):
        if picked.get(k) is not None:
            op[k] = picked[k]
    return op


# --------------------------------------------------------------------------
# what the browser draws: resolved times plus what's read from the edit now
# --------------------------------------------------------------------------

def cached_places() -> dict:
    """The place names already looked up (places.py), read without asking
    anyone: the route's labels on every request cost nothing."""
    from . import places as pl
    try:
        return json.loads(pl._cache_file().read_text())
    except (OSError, ValueError):
        return {}


def _seconds(w: datetime) -> float:
    return w.hour * 3600 + w.minute * 60 + w.second + w.microsecond / 1e6


def public(board: dict | None, cat, grid: dict | None = None, found: dict | None = None) -> dict:
    if not board:
        return {"items": [], "can": can(board, cat)}
    items = ov.resolve(board, board.get("graphics", []))
    es = _entries(board)
    route = None
    out = []
    for g in items:
        g = {**g, "tint": g.get("tint") or PIECES[g["piece"]]["tint"]}
        if g["piece"] == "stickers":
            g["beat"] = grid   # the music's beat in edit time; None = a steady pulse
        elif g["piece"] == "camcorder":
            # the clock as filmed, shot by shot: [start, end, seconds of day at start, speed]
            g["times"] = [[round(a, 3), round(z, 3), round(_seconds(w), 3), float(e.get("speed") or 1.0)]
                          for _, e, a, z in es if z > g["start"] and a < g["shown_end"]
                          and not e.get("gap") and (w := _when(cat, e)) is not None]
        elif g["piece"] == "clock":
            # the moment under its first frame, as the phone recorded it
            at = _at(board, g["start"])
            w = _when(cat, at[1]) if at else None
            if w:
                w += timedelta(seconds=max(0.0, g["start"] - at[2]) * float(at[1].get("speed") or 1.0))
            g["clock"] = round(_seconds(w) / 60.0, 2) if w else None
        elif g["piece"] == "route":
            route = route if route is not None else _projected(stops(board, cat, found))
            here = 0
            for k, s in enumerate(route["stops"]):
                if s["start"] <= g["start"] + 1e-6:
                    here = k
            g["stops"] = [{"x": s["x"], "y": s["y"], "name": s["name"]} for s in route["stops"]]
            g["aspect"], g["here"] = route["aspect"], here
        out.append(g)
    return {"items": out, "can": can(board, cat)}


def _projected(ss: list[dict]) -> dict:
    """Stops on a flat little map: equirectangular, north up, fitted in a
    unit box with its own aspect (kept between 0.6 and 1.8 so a day along one
    street still reads as a route, not a line)."""
    if not ss:
        return {"stops": [], "aspect": 1.0}
    lat0 = sum(s["gps"][0] for s in ss) / len(ss)
    xs = [s["gps"][1] * math.cos(math.radians(lat0)) for s in ss]
    ys = [-s["gps"][0] for s in ss]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    side = max(w, h, 1e-9)
    aspect = min(1.8, max(0.6, (w or side * 0.6) / (h or side * 0.6)))
    bw, bh = (side, side / aspect) if aspect >= 1 else (side * aspect, side)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return {"aspect": round(aspect, 3), "stops": [
        {"x": round(0.5 + (x - cx) / bw, 4), "y": round(0.5 + (y - cy) / bh, 4), "name": s["name"], "start": s["start"]}
        for s, x, y in zip(ss, xs, ys)]}
