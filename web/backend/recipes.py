"""Recipes: an edit the creator liked, saved so the next video is cut and
dressed the same way.

Idea 4 from the open tools (OpenStoryline saves an edit as a reusable
recipe); sarah chose to build it once barbie's Watch screen and vibes were
in main (2026-10-18). "Save as my recipe" sits next to Download on the
Watch screen and in the name menu; a saved recipe is offered under "Cut it
like" in the two picks, beside the viral library's vibes, and picking it
also picks its frame, look and music switch (still changeable there).

A recipe is *measured* from the finished edit, never copied from it:

- the cut, as the same style record a learnt reel gives (style.pace over
  the edit's own cuts, its length, how long the last shot holds, where the
  words sit and how long they stay, the music's tempo and energy over the
  seconds it played), reduced by remix.fingerprint, so make.py takes it
  exactly as it takes a vibe;
- the dress the creator chose: the caption style (overlay_style as set on
  the board), one transition for every cut, one effect on (nearly) every
  shot, the look, the frame, music on or off. These ride on the Make turn
  as ops, so one Undo takes the whole video back;
- the caption lines, as a sample of the creator's voice for the writer.

No frame, clip or sound of the edit is kept. A recipe, like a vibe, sets
the cut itself, so the AI doesn't plan a video made from one and nothing
is spent. Recipes live in $VIBECUT_CACHE/recipes/ and are mirrored to
Supabase as kind "vibe", key "recipe:<id>" (cloud.py; the table's kinds
have no "recipe", and vibe rows are only ever pushed, never pulled).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter

import numpy as np

from cutgrammar import music as mu
from cutgrammar import style as st

from . import brief, cloud, effects, looks, overlays, remix, timeline, transitions
from .indexer import CACHE

DIR = CACHE / "recipes"
PREFIX = "recipe:"
NAME_MAX = 40
COMMON = 0.75        # an effect on this share of the shots was meant for every shot [prior]
SAMPLES = 12
LINE_MAX = 120       # the line under Cut it like
TITLE_KINDS = ("title", "heading", "end", "chapters")
VERSION = 1


class RecipeError(ValueError):
    pass


# --------------------------------------------------------------------------
# measuring: the finished edit -> a recipe
# --------------------------------------------------------------------------

def _band(region: str) -> str:
    return "top" if region.startswith("top") else "bottom" if region.startswith("bottom") else "middle"


def _union(spans: list[tuple[float, float]]) -> float:
    out, end = 0.0, -1.0
    for a, z in sorted(spans):
        if z <= end:
            continue
        out += z - max(a, end)
        end = z
    return out


def words_of(board: dict, total: float) -> dict:
    """Where the edit's words sit and how long they stay, in text_style's
    shape (style.text_style reads the same from a reel's frames)."""
    ostyle = overlays.style_of(board)
    ovs = [o for o in overlays.resolve(board) if (o.get("text") or "").strip() or (o.get("sub") or "").strip()]
    if not ovs:
        return {"share": 0.0, "first_s": None, "band": None, "hold_s": None, "cards": 0, "upper": None,
                "size": None, "words_per_card": None, "samples": [], "words": ["no words on screen"]}
    spans = [(o["start"], max(o["start"], min(o["shown_end"], total))) for o in ovs]
    # where the running lines sit, by how long each stays; a title or a
    # chapter title is centred whatever the edit does with its words
    lines = [(o, z - a) for o, (a, z) in zip(ovs, spans) if o["kind"] not in TITLE_KINDS] \
        or [(o, z - a) for o, (a, z) in zip(ovs, spans)]
    bands: Counter = Counter()
    for o, held in lines:
        bands[_band(overlays._region(o, ostyle))] += held
    texts = [" ".join(f"{o.get('sub') or ''} {o.get('text') or ''}".split()) for o in ovs]
    letters = [ch for t in texts for ch in t if ch.isalpha()]
    samples: list[str] = []
    for o in ovs:
        line = " ".join((o.get("text") or "").split())
        if o["kind"] != "date" and 2 <= len(line) <= 48 and line.lower() not in {x.lower() for x in samples}:
            samples.append(line)
    share = _union(spans) / total if total else 0.0
    band = bands.most_common(1)[0][0]
    hold = float(np.median([z - a for a, z in spans]))
    first = min(a for a, _ in spans)
    return {"share": round(share, 3), "first_s": round(first, 2), "band": band, "hold_s": round(hold, 2),
            "cards": len(ovs), "upper": bool(letters) and sum(ch.isupper() for ch in letters) / len(letters) > 0.8,
            "size": None, "words_per_card": round(float(np.median([len(t.split()) for t in texts])), 1),
            "samples": samples[:SAMPLES],
            "words": [f"words {round(share * 100)}% of the time, {_where(band)}", f"each held about {hold:.1f} s"]}


def music_of(board: dict, track: mu.Track | None, total: float) -> dict | None:
    """The tempo and the energy over the seconds of the track that played."""
    m = board.get("music") or {}
    if not m.get("track") or track is None:
        return None
    e = np.asarray(track.energy, dtype=np.float64)
    a = int(max(0.0, float(m.get("in") or 0.0)) * mu.ENERGY_HZ)
    part = e[a: a + max(1, int(round(total * mu.ENERGY_HZ)))]
    if len(part) < 4:
        part = e
    curve = mu._resample(part, st.MUSIC_POINTS) if len(part) else None
    return {"bpm": float(track.bpm) if track.bpm else None,
            "energy": [round(float(x), 3) for x in curve] if curve is not None else None,
            "arc": st.arc_of(curve) if curve is not None else "steady", "bright": None}


def _common_effect(shots: list[dict]) -> dict | None:
    fx = Counter(it["effect"] for it in shots if it.get("effect"))
    if not fx:
        return None
    kind, n = fx.most_common(1)[0]
    if n < COMMON * len(shots):
        return None
    amounts = [float(it.get("effect_amount", 1.0)) for it in shots if it.get("effect") == kind]
    return {"effect": kind, "effect_amount": round(float(np.median(amounts)), 2)}


def measure(board: dict | None, track: mu.Track | None, fmt: str | None) -> dict:
    """{style, dress} from the edit as it stands now."""
    items = timeline.layout(board)
    shots = [it for it in items if it["kind"] == "shot"]
    if not board or not shots:
        raise RecipeError("There's no edit to save yet: make your video first.")
    total = float(items[-1]["seq_end"])
    bounds = [float(it["seq_end"]) for it in items[:-1]]
    fmt = fmt if fmt in brief.FORMATS else "tall"
    style = {"pace": st.pace(total, bounds) or None, "music": music_of(board, track, total),
             "duration": round(total, 2), "words": words_of(board, total),
             "ending": {"last_s": round(float(items[-1]["seq_end"] - items[-1]["seq_start"]), 2)},
             "frame": {"vertical": fmt != "wide"}}
    cap = {k: v for k, v in (board.get("overlay_style") or {}).items() if k in overlays.STYLE_FIELDS}
    dress = {"format": fmt, "look": board.get("look"), "music": bool((board.get("music") or {}).get("track")),
             "captions": cap or None, "transition": board.get("picture_all"),
             "effect": _common_effect(shots)}
    return {"style": style, "dress": dress}


def _length(s: float) -> str:
    """The video's length as the timeline reads it: 0:45, 1:05, or 8.5 s."""
    if round(s, 1) < 10:
        return f"{s:.1f} s"
    m, r = divmod(int(round(s)), 60)
    return f"{r} s" if not m else f"{m}:{r:02d}"


def _where(band: str | None) -> str:
    return "in the middle" if band == "middle" else f"at the {band or 'bottom'}"


def words(rec: dict) -> list[str]:
    """What a recipe will do, in the creator's words, for the save dialog
    and the Cut it like line."""
    s, d = rec["style"], rec["dress"]
    p = s.get("pace") or {}
    out = [brief.FORMATS.get(d.get("format"), "Vlog · vertical").split(" ·")[0] + " frame"]
    if p:
        out.append(f"{_length(s['duration'])}, about {p['median_s']:.1f} s a shot")
    lk = looks.get(d.get("look")) if d.get("look") else None
    if lk:
        out.append(f"{lk['name']} look")
    w = s.get("words") or {}
    cap = d.get("captions") or {}
    if not w.get("share"):
        out.append("no words")
    else:
        name = overlays.TEMPLATES.get(cap.get("template"), "Soft")
        face = overlays.TYPEFACES.get(cap.get("typeface"))
        out.append(f"{name} captions" + (f" in {face}" if face else "") + f" {_where(w.get('band'))}")
    tr = d.get("transition")
    if tr and tr.get("kind") in transitions.KINDS and tr["kind"] != "cut":
        out.append(f"{transitions.KINDS[tr['kind']]['name'].lower()} between every shot")
    fx = d.get("effect")
    if fx and fx.get("effect") in effects.KINDS:
        out.append(f"{effects.KINDS[fx['effect']]} on every shot")
    m = s.get("music") or {}
    if not d.get("music"):
        out.append("no music")
    elif m.get("bpm"):
        arc = m.get("arc") or "builds"
        out.append(f"music around {m['bpm']:.0f} BPM " + ("with a steady feel" if arc == "steady" else f"that {arc}"))
    else:
        out.append("music")
    return out


# --------------------------------------------------------------------------
# keeping them
# --------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:24] or "recipe"


def _name(name: str | None) -> str:
    n = " ".join((name or "").split())[:NAME_MAX]
    if not n:
        raise RecipeError("A recipe needs a name.")
    return n


def _write(rec: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DIR / f"{rec['id']}.tmp"
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    tmp.replace(DIR / f"{rec['id']}.json")
    cloud.push("vibe", PREFIX + rec["id"], rec, rec["saved_at"])


def list_all() -> list[dict]:
    out = []
    if DIR.exists():
        for p in DIR.glob("*.json"):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda r: -r.get("saved_at", 0))


def get(rid: str | None) -> dict | None:
    if not rid:
        return None
    rid = rid[len(PREFIX):] if rid.startswith(PREFIX) else rid
    if not re.fullmatch(r"[a-z0-9-]{1,40}", rid):
        return None
    try:
        return json.loads((DIR / f"{rid}.json").read_text())
    except (OSError, ValueError):
        return None


def by_name(name: str) -> dict | None:
    key = " ".join(name.split()).lower()
    return next((r for r in list_all() if r["name"].lower() == key), None)


def save(name: str, measured: dict, source: dict | None = None) -> tuple[dict, bool]:
    """Keep a measured edit under a name. The same name again replaces that
    recipe (as other editors do with a preset). Returns (recipe, replaced)."""
    name = _name(name)
    old = by_name(name)
    now = time.time()
    rec = {"id": old["id"] if old else f"{_slug(name)}-{uuid.uuid4().hex[:6]}", "name": name,
           "style": measured["style"], "dress": measured["dress"], "source": source or {},
           "made_at": old.get("made_at", now) if old else now, "saved_at": now, "version": VERSION}
    rec["words"] = words(rec)
    _write(rec)
    return rec, old is not None


def rename(rid: str, name: str) -> dict:
    rec = get(rid)
    if rec is None:
        raise KeyError(rid)
    name = _name(name)
    other = by_name(name)
    if other and other["id"] != rec["id"]:
        raise RecipeError(f"You already have a recipe called “{other['name']}”.")
    rec["name"], rec["saved_at"] = name, time.time()
    _write(rec)
    return rec


def delete(rid: str) -> bool:
    rec = get(rid)
    if rec is None:
        return False
    (DIR / f"{rec['id']}.json").unlink(missing_ok=True)
    cloud.push("vibe", PREFIX + rec["id"], {"id": rec["id"], "deleted": True}, time.time())
    return True


def public(rec: dict) -> dict:
    d = rec["dress"]
    ws = rec.get("words") or words(rec)
    line = "your recipe · " + ws[0]
    for w in ws[1:]:                   # whole items only: no list cut off mid-word
        if len(line) + 2 + len(w) > LINE_MAX:
            break
        line += ", " + w
    return {"id": PREFIX + rec["id"], "name": rec["name"], "kind": "recipe", "line": line, "words": ws,
            "dress": {"format": d.get("format"), "look": d.get("look"), "music": bool(d.get("music"))},
            "from": (rec.get("source") or {}).get("name"), "saved_at": rec.get("saved_at")}


# --------------------------------------------------------------------------
# using one: the fingerprint for make.py, and the dress as ops
# --------------------------------------------------------------------------

def fingerprint(rec: dict) -> dict:
    fp = remix.fingerprint([rec["style"]])
    fp["like"] = f"your recipe “{rec['name']}”"
    return fp


def phrasing(rec: dict | None) -> list[str]:
    return list(((rec or {}).get("style", {}).get("words") or {}).get("samples") or [])


def dress_ops(rec: dict, board: dict | None) -> list[dict]:
    """The creator's own dress on a freshly made board: their caption style,
    their transition between every cut, their effect on every shot."""
    d = rec.get("dress") or {}
    out: list[dict] = []
    cap = d.get("captions") or {}
    try:
        cap = overlays.clean_style(cap)
    except overlays.OverlayError:
        cap = {}
    if cap:
        out.append({"op": "overlay_style", **cap, "source": "recipe"})
    tr = d.get("transition")
    if tr and tr.get("kind") in transitions.KINDS:
        out.append({"op": "set_transition", "all": True, "kind": tr["kind"], "dur": tr.get("dur")})
    fx = d.get("effect")
    if fx and fx.get("effect") in effects.KINDS:
        for it in timeline.layout(board):
            if it["kind"] == "shot":
                out.append({"op": "set_shot", "shot": it["key"], "effect": fx["effect"],
                            "effect_amount": fx.get("effect_amount", 1.0)})
    return out
