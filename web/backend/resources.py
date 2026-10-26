"""My resources: the creator's own saved caption looks, animations,
transitions, effects, shot settings and songs, kept forever (sarah,
2026-10-19: "a resources folder so i can save my own animations or
templates forever", in the left rail, signed in to keep it).

A resource is what is on the video right now, taken off it by a Save button
where it was made -- never a copy typed in by hand, so what comes back is
exactly what was seen. Using one is ordinary ops (overlay_style,
set_transition, set_shot, set_music) as one undoable turn, so a resource
can never do anything an edit couldn't.

Kept outside every project in $VIBECUT_CACHE/resources.json, so it outlives
videos and restarts, and mirrored as kind `resource` (cloud.py) like the
defaults. Who it belongs to (`who`): until there are accounts, the browser on
the computer VibeCut runs on counts as signed in -- a request that reached
the server from elsewhere (a tunnel, the public link) is signed out and is
shown the log-in card instead. VIBECUT_PUBLIC=1 forces that for a server, and
the x-vibecut-visitor header (the app's "?visitor") for one browser, so the
owner can see what a visitor sees.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid

from . import board as bd
from .indexer import CACHE

FILE = CACHE / "resources.json"
# the folder's sections, in the order they are shown
KINDS = ("caption", "animation", "transition", "effect", "shot", "song", "graphic")
TITLES = {"caption": "Caption looks", "animation": "Animations", "transition": "Transitions",
          "effect": "Effects", "shot": "Shot settings", "song": "Songs", "graphic": "Graphic animations"}
NAME_MAX = 60
LIMIT = 300            # a folder, not a dump: oldest of a kind go first past this
# what a caption look carries: only what the creator picks by hand
# (overlays.PICKED), never the look's own defaults, so it lands the same on any
# video. The entrance is its own section (Animations), as in CapCut: a new
# look keeps how the words arrive, and the other way round.
CAPTION_KEYS = ("template", "text_color", "typeface", "outline", "shadow", "backdrop", "thick")
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
FORWARDED = ("x-forwarded-for", "forwarded", "cf-connecting-ip", "x-real-ip")
VISITOR = "x-vibecut-visitor"   # only ever takes the folder away, so it needs no checking
_lock = threading.Lock()


class ResourceError(Exception):
    pass


# --------------------------------------------------------------------------
# who is asking

def who(client_host: str | None, headers) -> dict:
    """Signed in or not. No accounts yet: this computer's own browser is the
    owner; anything relayed from elsewhere is a visitor, signed out."""
    if os.environ.get("VIBECUT_PUBLIC") == "1" or headers.get(VISITOR):
        return {"signed_in": False}
    relayed = any(headers.get(h) for h in FORWARDED)
    if client_host in LOOPBACK and not relayed:
        return {"signed_in": True, "as": "this computer"}
    return {"signed_in": False}


def signin_url() -> str | None:
    """Where Log in goes once accounts exist (the Launch work sets it)."""
    return os.environ.get("VIBECUT_SIGNIN_URL") or None


def signup_url() -> str | None:
    """Where "Create one now" goes; the log-in page until there's a separate one."""
    return os.environ.get("VIBECUT_SIGNUP_URL") or signin_url()


# --------------------------------------------------------------------------
# the folder

def _read() -> list[dict]:
    try:
        items = json.loads(FILE.read_text()).get("items") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [x for x in items if isinstance(x, dict) and x.get("kind") in KINDS]


def _write(items: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": items}))
    tmp.replace(FILE)


def _sync(item: dict) -> None:
    from . import cloud
    cloud.push("resource", item["id"], item, item.get("at"))


def all_items() -> list[dict]:
    """Newest first within each kind, kinds in folder order."""
    items = _read()
    return sorted(items, key=lambda x: (KINDS.index(x["kind"]), -float(x.get("at") or 0)))


def add(kind: str, value: dict, name: str | None = None) -> dict:
    if kind not in KINDS:
        raise ResourceError(f"can't keep a {kind!r}")
    name = (name or "").strip()[:NAME_MAX] or default_name(kind, value)
    with _lock:
        items = _read()
        same = next((x for x in items if x["kind"] == kind and x["value"] == value), None)
        if same:   # saved twice: one entry, moved to the top
            same["at"] = time.time()
            item = same
        else:
            item = {"id": uuid.uuid4().hex[:12], "kind": kind, "name": name, "value": value, "at": time.time()}
            items.append(item)
            mine = sorted((x for x in items if x["kind"] == kind), key=lambda x: x["at"])
            for old in mine[:max(0, len(mine) - LIMIT)]:
                items.remove(old)
        _write(items)
    _sync(item)
    return item


def rename(rid: str, name: str) -> dict:
    name = (name or "").strip()[:NAME_MAX]
    if not name:
        raise ResourceError("a name is needed")
    with _lock:
        items = _read()
        item = next((x for x in items if x["id"] == rid), None)
        if item is None:
            raise ResourceError("that's no longer in your resources")
        item["name"], item["at"] = name, time.time()
        _write(items)
    _sync(item)
    return item


def remove(rid: str) -> None:
    with _lock:
        items = _read()
        item = next((x for x in items if x["id"] == rid), None)
        if item is None:
            return
        items.remove(item)
        _write(items)
    from . import cloud
    cloud.push("resource", rid, {"deleted": True}, time.time())


def absorb(rows: list[dict]) -> None:
    """Rows from the mirror (another computer's saves): newer ones win."""
    with _lock:
        items = {x["id"]: x for x in _read()}
        for r in rows:
            v, rid = r.get("value") or {}, r.get("key")
            if not rid:
                continue
            have = items.get(rid)
            if have and float(have.get("at") or 0) >= float(r.get("at") or 0):
                continue
            if v.get("deleted"):
                items.pop(rid, None)
            elif v.get("kind") in KINDS and isinstance(v.get("value"), dict):
                items[rid] = {**v, "id": rid}
        _write(list(items.values()))


# --------------------------------------------------------------------------
# taken off the video

def _entry(b: dict, k: str | None) -> dict:
    if not k:
        raise ResourceError("click a shot first")
    try:
        beat, i = bd._where(b, k)
    except bd.OpError as e:
        raise ResourceError("that shot isn't in the video any more; click a shot") from e
    e = beat["shots"][i]
    if bd.is_gap(e):
        raise ResourceError("click a shot first, not an empty space")
    return e


def capture(kind: str, board: dict | None, shot: str | None = None, after: str | None = None,
            title_of=None, graphic: str | None = None) -> dict:
    """What's on the video now, as a resource's value. Raises when there's
    nothing of that kind to keep (a plain cut, no effect, the look's own captions)."""
    b = board or {}
    if not b.get("beats"):
        raise ResourceError("there's no video to save from yet")
    if kind in ("caption", "animation"):
        st = b.get("overlay_style") or {}
        keys = CAPTION_KEYS if kind == "caption" else ("enter",)
        v = {k: st[k] for k in keys if st.get(k) is not None}
        if not v:
            raise ResourceError("these captions are the look's own; change their style first, then save it"
                                if kind == "caption" else "pick an animation for the captions first")
        return v
    if kind == "transition":
        pick = ((b.get("picture_joins") or {}).get(after) if after else None) or b.get("picture_all")
        if not pick or pick.get("kind") == "cut":
            raise ResourceError("pick a transition first; a plain cut has nothing to keep")
        return {"kind": pick["kind"], "dur": pick["dur"]}
    if kind == "effect":
        e = _entry(b, shot)
        if not e.get("effect"):
            raise ResourceError("this shot has no effect to keep")
        return {"effect": e["effect"], "effect_amount": float(e.get("effect_amount") or 1.0)}
    if kind == "shot":
        e = _entry(b, shot)
        v = {f: e[f] for f in bd.SHOT_FX if f in e}
        if not v:
            raise ResourceError("this shot is as filmed; change its speed, turn, crop or effect first")
        return v
    if kind == "song":
        m = b.get("music") or {}
        if not m.get("track"):
            raise ResourceError("there's no music under this video")
        t = title_of(m["track"]) if title_of else None
        return {"track": m["track"], "in": float(m.get("in") or 0.0), "title": t or "A song"}
    if kind == "graphic":
        # the piece as it's dressed: colour, sticker, where and how big;
        # its words belong to the video it's on, so they're filled anew
        g = next((x for x in b.get("graphics") or [] if x["id"] == graphic), None) if graphic else None
        if g is None:
            raise ResourceError("click a graphic animation on the picture or the timeline first")
        from . import graphics
        v = {"piece": g["piece"], "tint": g.get("tint") or graphics.PIECES[g["piece"]]["tint"]}
        for k in ("sticker", "place", "size"):
            if g.get(k):
                v[k] = g[k]
        return v
    raise ResourceError(f"can't keep a {kind!r}")


def default_name(kind: str, v: dict) -> str:
    """A plain name from what it is; renamed in the folder."""
    from . import effects, overlays, transitions
    if kind == "caption":
        bits = [overlays.TYPEFACES.get(v.get("typeface") or "", ""), overlays.TEMPLATES.get(v.get("template") or "", "")]
        return " · ".join(x for x in bits if x) or "My caption look"
    if kind == "animation":
        return overlays.ENTERS.get(v.get("enter") or "", "My animation")
    if kind == "transition":
        return f"{transitions.KINDS.get(v['kind'], {}).get('name', v['kind'])} · {v['dur']:g}s"
    if kind == "effect":
        return f"{effects.describe(v['effect'])} · {round(v['effect_amount'] * 100)}%"
    if kind == "shot":
        bits = []
        if v.get("speed"):
            bits.append(f"{v['speed']:g}×")
        if v.get("reverse"):
            bits.append("backwards")
        if v.get("rotate"):
            bits.append(f"turned {v['rotate']}°")
        if v.get("mirror"):
            bits.append("mirrored")
        if v.get("fill"):
            bits.append("filled")
        if v.get("effect"):
            bits.append(effects.describe(v["effect"]))
        if "gain" in v or v.get("mute"):
            bits.append("muted" if v.get("mute") else f"sound {round(v['gain'] * 100)}%")
        return ", ".join(bits[:3]).capitalize() or "My shot settings"
    if kind == "song":
        return v.get("title") or "A song"
    if kind == "graphic":
        from . import graphics
        return " · ".join(x for x in (graphics.label(v.get("piece", "")), (v.get("sticker") or "").capitalize()) if x)
    return "Saved"


# --------------------------------------------------------------------------
# put back on a video

def ops_for(item: dict, board: dict | None, shot: str | None = None, after: str | None = None,
            have_track=None, graphic_op=None) -> tuple[list[dict], str]:
    """The ops that put a resource on the video, and the turn's words. An
    effect or a transition goes on the clicked shot / cut, else everywhere;
    shot settings need a clicked shot."""
    b = board or {}
    if not b.get("beats"):
        raise ResourceError("there's no video to use it on yet")
    kind, v, name = item["kind"], copy.deepcopy(item["value"]), item["name"]
    if kind in ("caption", "animation"):
        patch = {k: v.get(k) for k in (CAPTION_KEYS if kind == "caption" else ("enter",))}
        return [{"op": "overlay_style", **patch}], f"Your captions now use “{name}”"
    if kind == "transition":
        where = {"shot": after} if after else {"all": True}
        return ([{"op": "set_transition", "kind": v["kind"], "dur": v["dur"], **where}],
                f"“{name}” {'at that cut' if after else 'at every cut'}")
    shots = [bd.key(e) for bt in b["beats"] for e in bt["shots"] if not bd.is_gap(e)]
    if kind == "effect":
        keys = [shot] if shot else shots
        return ([{"op": "set_shot", "shot": k, "effect": v["effect"], "effect_amount": v["effect_amount"]} for k in keys],
                f"“{name}” on {'that shot' if shot else 'every shot'}")
    if kind == "shot":
        e = _entry(b, shot)
        fx = {f: v.get(f, plain) for f, plain in bd.FX_PLAIN.items()}
        if bd.is_freeze(e):   # a held frame takes only what it can show
            fx = {f: fx[f] for f in ("rotate", "fill", "mirror", "effect", "effect_amount")}
        return [{"op": "set_shot", "shot": shot, **fx}], f"That shot now has “{name}”"
    if kind == "song":
        if have_track is not None and not have_track(v["track"]):
            raise ResourceError("that song isn't on this computer any more")
        m = dict(b.get("music") or {})
        if not m.get("track"):   # no music yet: the bed's levels
            from . import audiomix
            m = {"gain": audiomix.MUSIC_GAIN, "original": 1.0, "fade_out": 2.0, "duck": [], "sfx": [], "level": True}
        m.update(track=v["track"], **{"in": v.get("in") or 0.0})
        return [{"op": "set_music", **{k: m[k] for k in bd.MUSIC_KEYS if k in m}}], f"“{name}” is under the video"
    if kind == "graphic" and graphic_op is not None:
        # at the playhead, with words from this video (app._graphic_op)
        return [graphic_op(v)], f"“{name}” is on the video at the playhead"
    raise ResourceError(f"can't use a {kind!r}")
