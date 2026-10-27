"""The working storyboard, and the operations that edit it.

The rule this module exists for: a conversation *edits* a storyboard, it
never regenerates one. "The opening is too slow" changes the opening and
leaves everything else exactly where the creator put it. Regenerating loses
their edits and makes the tool feel random.

So the storyboard is a pure function of a turn log: each turn is a list of
operations, applied in order by deterministic code. Undoing any turn --
not just the last -- is replaying the log without it. An operation that no
longer makes sense after an undo (it touched a beat that turn created) is
skipped and reported, never guessed at.

Operations reference beats and shots by stable id. Anything decided at
apply time (which shelf shot replaces another, what a proposal looked like
when it was chosen) is written back into the recorded op, so replay is
exact even after the proposals or the shelf change.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field

import numpy as np

from . import overlays as ov
from . import restyle
from . import storyboard as sb

# Pace. Trimming keeps each shot centred on its best frame, so a tighter
# section loses handling and dead air before it loses the moment.
PACE = {("tighter", "a_little"): 0.75, ("tighter", "a_lot"): 0.5,
        ("looser", "a_little"): 1.33, ("looser", "a_lot"): 2.0}
MIN_SHOT_S = 1.5

# What the chat model may emit.
LLM_OPS = ("choose_option", "move_beat", "drop_beat", "drop_shot", "swap_shot",
           "add_shot", "move_shot", "retitle_beat", "set_pace", "open_with", "end_with",
           "add_overlay", "edit_overlay", "drop_overlay", "set_join", "set_look")
# Plus the precise timeline edits, which come from the keyboard, never from
# a sentence: cut at a point, trim an edge to a point, remove a range.
OPS = LLM_OPS + ("split", "trim", "drop_range", "overlay_style", "apply_style", "set_music", "set_transition")
# How the sound crosses a cut (audiomix.py): hard, carried out (L), carried in (J).
JOIN_SOUNDS = ("cut", "carry_out", "carry_in", "default")
# What set_music may record about the bed under the edit (export and preview mix it the same).
MUSIC_KEYS = ("track", "in", "gain", "original", "level", "fade_out", "duck", "sfx", "volume")
# volume: the music's own Volume slider, on top of the level it was placed at (1 = as placed, up to 2)
MUSIC_VOLUME_MAX = 2.0
# Words on screen (overlays.py): same log, same undo, but they never touch a shot.
OVERLAY_OPS = ("add_overlay", "edit_overlay", "drop_overlay", "overlay_style")
# A shot's own sound taken off onto its own strip under the picture (the
# "extract audio" every editor has): then it can be moved, made louder or
# quieter, muted or deleted on its own. From the timeline, never chat.
# A voiceover (mic.py): the creator's own voice recorded over the playing
# edit, on its own strip like the extracted ones, changed and deleted the same
# way (edit_audio / drop_audio). From the Record button, never chat.
SOUND_OPS = ("extract_audio", "edit_audio", "drop_audio", "add_voice")
OPS = OPS + SOUND_OPS
# Graphic animations drawn over the footage (graphics.py): same log, same
# undo, anchored like captions. From the Graphic animations tab, never chat.
GRAPHIC_OPS = ("add_graphic", "edit_graphic", "drop_graphic")
OPS = OPS + GRAPHIC_OPS
AUDIO_GAIN_MAX = 2.0   # 200%: louder than filmed, short of distorting most phone sound
# The everyday shot fixes every editor has, on the shot itself: speed (slow
# motion, fast forward), its own volume or mute, a quarter turn for a clip
# filmed sideways, and filling the frame (crop the edges) instead of bars.
# From the shot menu, never chat. Kept on the entry, so a cut keeps them.
OPS = OPS + ("set_shot",)
# The clip tools every editor has next to Split: Duplicate (the shot again,
# right after itself), Freeze frame (hold the frame under the playhead, like
# CapCut's Freeze), and Reverse (a set_shot field: the shot plays backwards).
OPS = OPS + ("duplicate_shot", "freeze_frame")
FREEZE_S = 3.0        # a freeze frame's length when none is asked for (CapCut's default)
FREEZE_MAX = 30.0
SPEEDS = (0.25, 4.0)           # the slowest and fastest a shot may play
SHOT_FX = ("speed", "gain", "mute", "rotate", "fill", "mirror", "fade_in", "fade_out",
           "punch", "effect", "effect_amount", "reverse")
PUNCH_MAX = 0.25     # a push into (or out of) the frame over the shot, as a share of its size
# effect: one of effects.KINDS (Shake, Glitch, VHS...), picked in the Effects tab
FX_PLAIN = {"speed": 1.0, "gain": 1.0, "mute": False, "rotate": 0, "fill": False, "mirror": False,
            "fade_in": 0.0, "fade_out": 0.0, "punch": 0.0, "effect": None, "effect_amount": 1.0,
            "reverse": False}
FADE_MAX = 5.0   # a shot's own sound fading in or out, seconds

FRAME = 1 / 30  # sequence frame; the smallest piece a cut or trim may leave


# A storyboard entry is {"id": source shot, "start", "end"} in source seconds,
# optionally with "key" when one source shot appears more than once (after a
# cut). A gap is {"key", "id": None, "gap": True, "start": 0, "end": length}:
# same duration arithmetic, nothing to show.
def key(e: dict) -> str:
    return e.get("key") or e["id"]


def seq_dur(e: dict) -> float:
    """How long an entry lasts in the edit: its source seconds at its speed."""
    return (e["end"] - e["start"]) / float(e.get("speed") or 1.0)


def is_freeze(e: dict) -> bool:
    """A held frame (freeze_frame): it shows `start` for end - start seconds.
    Its span is kept as long as it lasts so every sum over the edit stays
    plain arithmetic; only the player, export and mixer read it as one frame."""
    return bool(e.get("freeze"))


def is_gap(e: dict) -> bool:
    return bool(e.get("gap"))


def _gap(k: str, dur: float) -> dict:
    return {"key": k, "id": None, "gap": True, "start": 0.0, "end": round(dur, 3)}


class OpError(Exception):
    pass


# --------------------------------------------------------------------------
# catalogue: every shot on the shelf, with what the ops need to know
# --------------------------------------------------------------------------

@dataclass
class Catalog:
    shots: dict[str, sb.Shot]
    best_t: dict[str, float]

    @classmethod
    def from_clips(cls, clips: list[dict]) -> "Catalog":
        shots = {s.id: s for s in sb.shots_from_clips(clips)}
        best = {f"{c['id']}:{s['index']}": s["best_t"] for c in clips for s in c["shots"]}
        return cls(shots, best)

    def get(self, sid: str) -> sb.Shot:
        if sid not in self.shots:
            raise OpError(f"no shot {sid} on the shelf")
        return self.shots[sid]


def board_from_option(option: dict) -> dict:
    prefix = option["key"][0]
    return {
        "option": option["key"],
        "name": option["name"],
        "structure": option["summary"],
        "beats": [{
            "id": f"{prefix}{i + 1}",
            "title": b["title"],
            "detail": b["detail"],
            **({"line": b["line"]} if b.get("line") else {}),
            # a voiceover line nothing shows stays a gap of its length
            "shots": [_gap(s["key"], s["end"] - s["start"]) if s.get("gap")
                      else {"id": s["id"], "start": s["start"], "end": s["end"]} for s in b["shots"]],
        } for i, b in enumerate(option["beats"])],
    }


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def _beat(board: dict, bid: str | None) -> dict:
    for b in board["beats"]:
        if b["id"] == bid:
            return b
    raise OpError(f"no beat {bid}")


def _where(board: dict, sid: str | None) -> tuple[dict, int]:
    for b in board["beats"]:
        for i, s in enumerate(b["shots"]):
            if key(s) == sid:
                return b, i
    raise OpError(f"shot {sid} is not in the storyboard")


def _on_board(board: dict) -> set[str]:
    return {s["id"] for b in board["beats"] for s in b["shots"] if s["id"]}


def _keys(board: dict) -> set[str]:
    return {key(s) for b in board["beats"] for s in b["shots"]}


def _fresh_key(board: dict, base: str) -> str:
    keys, k, n = _keys(board), base, 2
    while k in keys:
        k, n = f"{base}.{n}", n + 1
    return k


def _flat(board: dict) -> list[tuple[dict, int, float]]:
    """(beat, index, sequence start) for every entry, in playing order."""
    out, t = [], 0.0
    for b in board["beats"]:
        for i, s in enumerate(b["shots"]):
            out.append((b, i, t))
            t += seq_dur(s)
    return out


def seq_start(board: dict, k: str) -> float | None:
    for b, i, t in _flat(board):
        if key(b["shots"][i]) == k:
            return t
    return None


def _split(board: dict, k: str, at: float) -> str | None:
    """Cut entry `k` at source time `at`. Returns the second piece's key,
    or None when `at` is already an edge (nothing to cut)."""
    beat, i = _where(board, k)
    e = beat["shots"][i]
    if abs(at - e["start"]) < FRAME / 2 or abs(at - e["end"]) < FRAME / 2:
        return None
    if is_gap(e):
        raise OpError("a gap can't be cut — delete it instead")
    if not (e["start"] < at < e["end"]):
        raise OpError(f"{at:.2f}s is outside that shot ({e['start']:.2f}–{e['end']:.2f}s)")
    second = {"key": _fresh_key(board, f"{e['id']}~{int(round(at * 1000))}"), "id": e["id"],
              "start": round(at, 3), "end": e["end"],
              **{f: e[f] for f in SHOT_FX if f in e and f != "fade_in"}}
    if is_freeze(e):
        # both halves hold the same frame; `at` only says how long each lasts
        second.update(freeze=True, start=e["start"], end=round(e["start"] + e["end"] - at, 3))
    elif e.get("reverse"):
        # played backwards, the later source plays first: the first piece
        # keeps [at, end], the second is [start, at]
        second.update(start=e["start"], end=round(at, 3))
        e["start"] = round(at, 3)
        e.pop("fade_out", None)
        beat["shots"].insert(i + 1, second)
        _sound_follows(board, k, second["key"])
        return second["key"]
    e.pop("fade_out", None)   # the fade in stays at the start, the fade out goes with the end
    e["end"] = round(at, 3)
    beat["shots"].insert(i + 1, second)
    _sound_follows(board, k, second["key"])
    return second["key"]


def _sound_follows(board: dict, k: str, new: str) -> None:
    off = (board.get("sound") or {}).get("off")
    if off is not None and k in off:
        off.append(new)   # its sound is on a strip: a copy or a cut doesn't bring it back


def play_offset(e: dict, at: float) -> float:
    """Seconds into the entry (at its speed) where source time `at` plays."""
    sp = float(e.get("speed") or 1.0)
    return ((e["end"] - at) if e.get("reverse") else (at - e["start"])) / sp


def _insert_at(beat: dict, entry: dict, op: dict) -> None:
    """Insert before `op.before` (a shot id) if given, else at `op.to_index`, else at the end."""
    if op.get("before"):
        for i, s in enumerate(beat["shots"]):
            if key(s) == op["before"]:
                beat["shots"].insert(i, entry)
                return
        raise OpError(f"shot {op['before']} is not in beat {beat['id']}")
    k = op.get("to_index")
    k = len(beat["shots"]) if k is None else max(0, min(int(k), len(beat["shots"])))
    beat["shots"].insert(k, entry)


def _span(cat: Catalog, sid: str, dur: float) -> tuple[float, float]:
    """A window of `dur` seconds inside the shot, centred on its best frame."""
    s = cat.get(sid)
    dur = max(min(dur, s.end - s.start), min(MIN_SHOT_S, s.end - s.start))
    c = cat.best_t.get(sid, (s.start + s.end) / 2)
    a = min(max(s.start, c - dur / 2), s.end - dur)
    return round(a, 3), round(a + dur, 3)


def _shot_fx(b: dict, op: dict) -> None:
    """Speed, volume, mute, turn and fill on one shot. A value back at its
    default is removed, so an untouched shot stays a plain entry."""
    beat, i = _where(b, op.get("shot"))
    e = beat["shots"][i]
    if is_gap(e):
        raise OpError("an empty space has nothing to change")
    if not any(f in op for f in SHOT_FX):
        raise OpError("nothing to change")
    if "speed" in op:
        e["speed"] = round(max(SPEEDS[0], min(SPEEDS[1], float(op["speed"]))), 3)
    if "gain" in op:
        e["gain"] = round(max(0.0, min(AUDIO_GAIN_MAX, float(op["gain"]))), 3)
    if "mute" in op:
        e["mute"] = bool(op["mute"])
    if "rotate" in op:
        r = int(op["rotate"])
        if r % 90:
            raise OpError("a shot turns in quarter turns (0, 90, 180, 270)")
        e["rotate"] = r % 360
    if "fill" in op:
        e["fill"] = bool(op["fill"])
    if "mirror" in op:
        e["mirror"] = bool(op["mirror"])
    for f in ("fade_in", "fade_out"):
        if f in op:
            e[f] = round(max(0.0, min(FADE_MAX, float(op[f]))), 2)
    if "punch" in op:
        # the camera's push over the shot: + in, - out (export's zoompan; the player's scale)
        e["punch"] = round(max(-PUNCH_MAX, min(PUNCH_MAX, float(op["punch"]))), 3)
    if "effect" in op:
        from . import effects
        if op["effect"] is not None and op["effect"] not in effects.KINDS:
            raise OpError(f"no effect called {op['effect']!r}")
        e["effect"] = op["effect"]
        if not op["effect"]:
            e.pop("effect_amount", None)
    if "effect_amount" in op:
        from . import effects
        e["effect_amount"] = effects.clamp_amount(op["effect_amount"])
    if "reverse" in op:
        if is_freeze(e) and op["reverse"]:
            raise OpError("a held frame looks the same backwards")
        e["reverse"] = bool(op["reverse"])
    for f, plain in FX_PLAIN.items():
        if f in e and e[f] == plain:
            del e[f]


def _freeze(b: dict, op: dict) -> None:
    """Hold the frame at source time `at` of a shot for `dur` seconds, cut in
    where it plays (CapCut's Freeze). The held frame keeps the shot's turn,
    mirror and fill, plays no sound, and is a shot of its own after that."""
    beat, i = _where(b, op.get("shot"))
    e = beat["shots"][i]
    if is_gap(e):
        raise OpError("an empty space has no frame to hold")
    if is_freeze(e):
        raise OpError("this is already a held frame — drag its end to make it longer")
    at = float(op.get("at", e["start"]))
    if not (e["start"] - FRAME / 2 <= at <= e["end"] + FRAME / 2):
        raise OpError(f"{at:.2f}s is outside that shot ({e['start']:.2f}–{e['end']:.2f}s)")
    off = play_offset(e, at)
    at = max(e["start"], min(at, e["end"] - FRAME))   # the last frame still has to be a frame
    dur = max(FRAME, min(FREEZE_MAX, float(op.get("dur") or FREEZE_S)))
    hold = {"key": op.get("key") or _fresh_key(b, f"{e['id']}#{int(round(at * 1000))}"), "id": e["id"],
            "start": round(at, 3), "end": round(at + dur, 3), "freeze": True,
            **{f: e[f] for f in ("rotate", "fill", "mirror") if f in e}}
    op["key"], op["dur"] = hold["key"], round(dur, 3)
    if off < FRAME / 2:
        pos = i                               # at the moment it starts playing: before it
    elif off > seq_dur(e) - FRAME * 1.5:
        pos = i + 1                           # at its last frame: after it
    else:
        _split(b, key(e), at)
        pos = i + 1
    beat["shots"].insert(pos, hold)


def _effect_name(k) -> str:
    from . import effects
    return effects.describe(k)


def _sound_op(b: dict, op: dict, kind: str, new_id) -> None:
    """Extracted sound. `sound.off` lists the entries whose own sound no
    longer plays under them; `sound.strips` is what was taken off, each at a
    place in the edit (sequence seconds), like an unlinked audio clip: it
    stays where it was put when shots before it change."""
    snd = b.setdefault("sound", {"off": [], "strips": []})
    if kind == "add_voice":
        # the board keeps the recording's name only; mic.path_of finds the file
        f = str(op.get("voice") or "")
        if not (8 <= len(f) <= 32 and all(ch in "0123456789abcdef" for ch in f)):
            raise OpError("no such recording")
        dur = float(op.get("dur") or 0.0)
        if dur <= 0:
            raise OpError("the recording is empty")
        sid = op.get("id") or new_id()
        op["id"] = sid
        snd.setdefault("voice", []).append({"id": sid, "file": f, "at": round(max(0.0, float(op.get("at") or 0.0)), 3),
                                            "dur": round(dur, 3), "gain": 1.0, "mute": False})
        return
    if kind == "extract_audio":
        k = op.get("shot")
        beat, i = _where(b, k)
        e = beat["shots"][i]
        if is_gap(e) or is_freeze(e):
            raise OpError("an empty space has no sound to take off" if is_gap(e) else "a held frame has no sound")
        if k in snd["off"]:
            raise OpError("this shot's sound is already on its own strip")
        sid = op.get("id") or new_id()
        op["id"] = sid
        snd["off"].append(k)
        # The strip sounds as the shot did: its speed, volume and fades come
        # with it (a 4x shot's sound stays as long as the shot, not 4x longer).
        strip = {"id": sid, "shot": e["id"], "start": e["start"], "end": e["end"],
                 "at": round(seq_start(b, k), 3), "gain": 0.0 if e.get("mute") else float(e.get("gain", 1.0)),
                 "mute": False, "from": k}
        for f in ("speed", "fade_in", "fade_out"):
            if e.get(f):
                strip[f] = e[f]
        snd["strips"].append(strip)
        return
    voice = snd.get("voice") or []
    strip = next((x for x in snd["strips"] + voice if x["id"] == op.get("audio")), None)
    if strip is None:
        raise OpError(f"no sound strip {op.get('audio')!r}")
    if kind == "drop_audio":
        # Like any editor: deleting the strip leaves the shot silent. Undo brings it back.
        (voice if strip in voice else snd["strips"]).remove(strip)
        return
    if "gain" in op:
        strip["gain"] = round(max(0.0, min(AUDIO_GAIN_MAX, float(op["gain"]))), 3)
    if "mute" in op:
        strip["mute"] = bool(op["mute"])
    if "at" in op:
        strip["at"] = round(max(0.0, float(op["at"])), 3)
    for f in ("fade_in", "fade_out"):
        if f in op:
            v = round(max(0.0, min(FADE_MAX, float(op[f]))), 2)
            if v:
                strip[f] = v
            else:
                strip.pop(f, None)


def _prune(board: dict) -> None:
    board["beats"] = [b for b in board["beats"] if b["shots"]]


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def apply(board: dict | None, op: dict, cat: Catalog, proposals: dict | None,
          new_id: callable) -> tuple[dict | None, dict]:
    """Apply one op to a copy of `board`. Returns (board, op as recorded)."""
    kind = op.get("op")
    if kind not in OPS:
        raise OpError(f"unknown operation {kind!r}")
    # null means "not given" -- except an overlay's length, where it means
    # "as long as what it hangs off" (a caption filling its spoken line) and its
    # place, where it means "back where it usually goes" (undoing a drag).
    op = {k: v for k, v in op.items() if v is not None or (k in ("dur", "place") and kind in OVERLAY_OPS + GRAPHIC_OPS)
          or (k in ("template", "enter", "text_color", "typeface", "outline", "shadow", "backdrop", "thick")
              and kind == "overlay_style")   # None = back to the look's own
          or (k == "effect" and kind == "set_shot")}   # None = no effect

    if kind == "choose_option":
        snap = op.get("snapshot")
        if snap is None:
            opts = {o["key"]: o for o in (proposals or {}).get("options", [])}
            if op.get("option") not in opts:
                raise OpError(f"no proposal {op.get('option')!r} to choose")
            snap = board_from_option(opts[op["option"]])
            op["snapshot"] = snap
        return copy.deepcopy(snap), op

    if board is None:
        if kind not in ("add_shot", "open_with", "end_with"):
            raise OpError("there is no storyboard yet — choose one of the proposals first")
        # Dragging a shot onto an empty timeline starts a hand-built storyboard.
        board = {"option": "manual", "name": "Your cut", "structure": "Built by hand from the shelf.",
                 "beats": []}
    b = copy.deepcopy(board)

    if kind in OVERLAY_OPS:
        try:
            {"add_overlay": lambda: ov.add(b, op, new_id), "edit_overlay": lambda: ov.edit(b, op),
             "drop_overlay": lambda: ov.drop(b, op), "overlay_style": lambda: ov.set_style(b, op)}[kind]()
        except (ov.OverlayError, ValueError, TypeError) as e:
            raise OpError(str(e)) from e
        return b, op

    if kind in GRAPHIC_OPS:
        from . import graphics
        try:
            graphics.apply(b, op, new_id)
        except (graphics.GraphicError, ValueError, TypeError) as e:
            raise OpError(str(e)) from e
        return b, op

    if kind == "apply_style":
        # A borrowed style (restyle.py): retimes shots, and records the look
        # and transitions for export. Comes from the style card, never chat.
        try:
            restyle.apply(b, op, cat)
        except restyle.StyleError as e:
            raise OpError(str(e)) from e
        return b, op

    if kind == "set_join":
        # The join *after* this shot. Addressed by entry key, like every
        # other op, so it travels with the shot and survives replay.
        k, sound = op.get("shot"), op.get("sound", "default")
        if sound not in JOIN_SOUNDS:
            raise OpError(f"a join's sound is one of {', '.join(JOIN_SOUNDS)}, not {sound!r}")
        beat, i = _where(b, k)
        if beat is b["beats"][-1] and i == len(beat["shots"]) - 1:
            raise OpError("that's the last shot — there's no cut after it")
        joins = dict(b.get("joins") or {})
        if sound == "default":
            joins.pop(k, None)
        else:
            joins[k] = {"sound": sound}
        b["joins"] = joins
        return b, op

    if kind == "set_transition":
        # How the picture crosses a cut, picked by the creator (transitions.py):
        # the join after this shot, or every cut. From the timeline, never chat.
        from . import transitions

        def where(k):
            beat, i = _where(b, k)
            if beat is b["beats"][-1] and i == len(beat["shots"]) - 1:
                raise OpError("that's the last shot — there's no cut after it")
        try:
            transitions.apply(b, op, where)
        except transitions.TransitionError as e:
            raise OpError(str(e)) from e
        return b, op

    if kind == "set_shot":
        _shot_fx(b, op)
        return b, op

    if kind == "duplicate_shot":
        # the shot again, right after itself, with everything done to it
        beat, i = _where(b, op.get("shot"))
        e = beat["shots"][i]
        if is_gap(e):
            raise OpError("an empty space has nothing to copy")
        dup = {**copy.deepcopy(e), "key": op.get("key") or _fresh_key(b, key(e))}
        op["key"] = dup["key"]
        beat["shots"].insert(i + 1, dup)
        _sound_follows(b, key(e), dup["key"])
        return b, op

    if kind == "freeze_frame":
        _freeze(b, op)
        return b, op

    if kind in SOUND_OPS:
        _sound_op(b, op, kind, new_id)
        return b, op

    if kind == "set_look":
        # The vibe of the words on screen, for the whole video (looks.py).
        from . import looks
        try:
            looks.apply(b, op)
        except ValueError as e:
            raise OpError(str(e)) from e
        return b, op

    if kind == "set_music":
        # The bed under the whole edit: which track, where it starts, how
        # loud, where it ducks. From the music card or a Remix, never chat.
        b["music"] = {k: op[k] for k in MUSIC_KEYS if k in op}
        if "volume" in b["music"]:
            v = round(max(0.0, min(MUSIC_VOLUME_MAX, float(b["music"]["volume"]))), 2)
            if v == 1.0:
                del b["music"]["volume"]
            else:
                b["music"]["volume"] = v
        return b, op

    if kind == "move_beat":
        beat = _beat(b, op.get("beat"))
        b["beats"].remove(beat)
        k = max(0, min(int(op.get("to_index", 0)), len(b["beats"])))
        b["beats"].insert(k, beat)

    elif kind == "drop_beat":
        b["beats"].remove(_beat(b, op.get("beat")))

    elif kind == "drop_shot":
        beat, i = _where(b, op.get("shot"))
        e = beat["shots"].pop(i)
        if op.get("leave_gap") and not is_gap(e):  # lift: keep everything after in place
            beat["shots"].insert(i, _gap(f"gap~{key(e)}", e["end"] - e["start"]))
        _prune(b)

    elif kind == "split":
        if _split(b, op.get("shot"), float(op.get("at", -1))) is None:
            raise OpError("that point is already a cut")

    elif kind == "trim":
        beat, i = _where(b, op.get("shot"))
        e = beat["shots"][i]
        if is_gap(e):
            raise OpError("trim a shot, not a gap")
        src = cat.get(e["id"])
        to, edge = float(op.get("to", 0)), op.get("edge")
        if edge not in ("in", "out"):
            raise OpError("trim needs edge 'in' or 'out'")
        if is_freeze(e):
            # a held frame keeps its frame; either end only makes it longer or shorter
            grow = (e["start"] - to) if edge == "in" else (to - e["end"])
            new = max(FRAME, min(FREEZE_MAX, e["end"] - e["start"] + grow))
            removed = e["end"] - e["start"] - new
            e["end"] = round(e["start"] + new, 3)
            if op.get("leave_gap") and removed > FRAME / 2:
                beat["shots"].insert(i + (edge == "out"), _gap(f"gap~{edge}~{key(e)}", removed))
            return b, op
        if e.get("reverse"):
            # `edge` is the end that plays first / last; backwards, the
            # first to play is the source's end. `to` stays a source time.
            if edge == "in":
                to = min(src.end, max(to, e["start"] + FRAME))
                removed, e["end"] = e["end"] - to, round(to, 3)
                if op.get("leave_gap") and removed > FRAME / 2:
                    beat["shots"].insert(i, _gap(f"gap~in~{key(e)}", removed))
            else:
                to = max(src.start, min(to, e["end"] - FRAME))
                removed, e["start"] = to - e["start"], round(to, 3)
                if op.get("leave_gap") and removed > FRAME / 2:
                    beat["shots"].insert(i + 1, _gap(f"gap~out~{key(e)}", removed))
            return b, op
        if edge == "in":
            to = max(src.start, min(to, e["end"] - FRAME))
            removed, e["start"] = to - e["start"], round(to, 3)
            if op.get("leave_gap") and removed > FRAME / 2:
                beat["shots"].insert(i, _gap(f"gap~in~{key(e)}", removed))
        elif edge == "out":
            to = min(src.end, max(to, e["start"] + FRAME))
            removed, e["end"] = e["end"] - to, round(to, 3)
            if op.get("leave_gap") and removed > FRAME / 2:
                beat["shots"].insert(i + 1, _gap(f"gap~out~{key(e)}", removed))
        else:
            raise OpError("trim needs edge 'in' or 'out'")

    elif kind == "drop_range":
        # Both ends are (entry, source time), so replay can't drift.
        t0 = seq_start(b, op.get("from_shot"))
        t1 = seq_start(b, op.get("to_shot"))
        if t0 is None or t1 is None:
            raise OpError("the marked range refers to a shot that's no longer there")
        f_e = _where(b, op["from_shot"])
        t_e = _where(b, op["to_shot"])
        fe, te = f_e[0]["shots"][f_e[1]], t_e[0]["shots"][t_e[1]]
        a = t0 + play_offset(fe, float(op["from_at"]))
        z = t1 + play_offset(te, float(op["to_at"]))
        if z - a < FRAME / 2:
            raise OpError("mark an out point after the in point")
        k2 = _split(b, op["to_shot"], float(op["to_at"]))
        _split(b, op["from_shot"], float(op["from_at"]))
        doomed = []
        for bt, i, t in _flat(b):
            e = bt["shots"][i]
            if t >= a - FRAME / 2 and t + seq_dur(e) <= z + FRAME / 2:
                doomed.append((bt, key(e)))
        if not doomed:
            raise OpError("nothing inside that range")
        first_beat, first_i = _where(b, doomed[0][1])
        for bt, k in doomed:
            bt["shots"] = [x for x in bt["shots"] if key(x) != k]
        if op.get("leave_gap"):
            first_beat["shots"].insert(min(first_i, len(first_beat["shots"])),
                                       _gap(f"gap~{doomed[0][1]}", z - a))
        _prune(b)
        del k2

    elif kind == "retitle_beat":
        title = (op.get("title") or "").strip()
        if not title:
            raise OpError("a new title is needed")
        _beat(b, op.get("beat"))["title"] = title

    elif kind == "set_pace":
        beat = _beat(b, op.get("beat"))
        pace = (op.get("direction", "tighter"), op.get("amount", "a_little"))
        if pace not in PACE:
            raise OpError(f"pace must be tighter/looser, a_little/a_lot, not {pace}")
        f = PACE[pace]
        for s in beat["shots"]:
            if not is_gap(s):
                s["start"], s["end"] = _span(cat, s["id"], (s["end"] - s["start"]) * f)

    elif kind == "swap_shot":
        beat, i = _where(b, op.get("shot"))
        old = beat["shots"][i]
        if is_gap(old):
            raise OpError("that's a gap, not a shot")
        with_id = op.get("with_shot") or _better_than(b, cat, old["id"])
        if with_id in _on_board(b):
            raise OpError(f"shot {with_id} is already in the storyboard")
        a, e = _span(cat, with_id, old["end"] - old["start"])  # keep the slot's length
        beat["shots"][i] = {"id": with_id, "start": a, "end": e}
        op["with_shot"] = with_id

    elif kind in ("add_shot", "move_shot"):
        sid = op.get("shot")
        if kind == "add_shot":
            s = cat.get(sid)
            if sid in _on_board(b):
                raise OpError(f"shot {sid} is already in the storyboard")
            entry = {"id": sid, "start": s.start, "end": s.end}
            # a window of it (the rough cut's trim) when one is given
            if op.get("start") is not None and op.get("end") is not None:
                a, z = max(s.start, float(op["start"])), min(s.end, float(op["end"]))
                if z - a >= min(MIN_SHOT_S, s.end - s.start):
                    entry = {"id": sid, "start": round(a, 3), "end": round(z, 3)}
        else:
            src, i = _where(b, sid)
            entry = src["shots"].pop(i)
        if op.get("beat"):
            target = _beat(b, op["beat"])
        elif b["beats"]:
            target = b["beats"][-1]
        else:
            target = {"id": new_id(), "title": "New", "detail": "", "shots": []}
            b["beats"].append(target)
            op["beat"] = target["id"]
        _insert_at(target, entry, op)
        _prune(b)

    elif kind in ("open_with", "end_with"):
        sid = op.get("shot")
        if sid in _keys(b):
            src, i = _where(b, sid)
            entry = src["shots"].pop(i)
        else:
            s = cat.get(sid)
            entry = {"id": sid, "start": s.start, "end": s.end}
        if not b["beats"]:
            b["beats"].append({"id": new_id(), "title": "Opening", "detail": "", "shots": []})
        if kind == "open_with":
            b["beats"][0]["shots"].insert(0, entry)
        else:
            b["beats"][-1]["shots"].append(entry)
        _prune(b)

    ov.prune(b)  # overlays go with what they hang off
    return b, op


def applied(board: dict | None, ops: list[dict], cat: Catalog | None, proposals: dict | None,
            first_id: int = 0) -> dict | None:
    """The board those ops would make, worked out on a copy; nothing is
    logged and an op that fails is passed over, as replay would. `first_id`
    numbers what they add on from ops already applied (never a story's own
    part ids, t1, t2 …)."""
    for k, op in enumerate(ops, first_id):
        try:
            board, _ = apply(board, op, cat, proposals, new_id=lambda k=k: f"trial{k}")
        except (OpError, ov.OverlayError):
            continue
    return board


def _better_than(board: dict, cat: Catalog, sid: str) -> str:
    """The shelf shot that could stand in for `sid`: looks like it, but better made."""
    cur = cat.get(sid)
    used = _on_board(board)
    best, best_v = None, -1e9
    for c in cat.shots.values():
        if c.id in used or c.utility:
            continue
        sim = float(np.dot(cur.vec, c.vec)) if cur.vec.shape == c.vec.shape else 0.0
        gain = c.score - cur.score
        if gain <= 0:
            continue
        v = 0.6 * sim + 0.4 * gain
        if v > best_v:
            best, best_v = c.id, v
    if best is None:
        raise OpError("nothing on the shelf is better made than that shot")
    return best


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------

def _stay_put(seq: list[str], order: dict[str, int]) -> set[str]:
    """Longest run of items already in relative order -- everything else 'moved'."""
    import bisect
    keys = [order[x] for x in seq]
    tails, idx, prev = [], [], [-1] * len(keys)
    for i, k in enumerate(keys):
        j = bisect.bisect_left([keys[t] for t in tails], k)
        if j == len(tails):
            tails.append(i)
        else:
            tails[j] = i
        prev[i] = tails[j - 1] if j else -1
    keep, i = set(), tails[-1] if tails else -1
    while i >= 0:
        keep.add(seq[i])
        i = prev[i]
    return keep


def _total(board: dict | None) -> float:
    return sum(seq_dur(e) for bt in (board or {}).get("beats", []) for e in bt["shots"])


def diff(a: dict | None, b: dict | None) -> dict:
    """What changed from a to b, at beat and shot level."""
    A = a["beats"] if a else []
    B = b["beats"] if b else []
    ab = {x["id"]: x for x in A}
    bb = {x["id"]: x for x in B}
    out = {"beats": {"removed": [], "added": [], "moved": [], "retitled": []},
           "shots": {"removed": [], "added": [], "moved": [], "trimmed": []},
           "replaced": (a or {}).get("option") != (b or {}).get("option") or (a is None) != (b is None),
           "total": [round(_total(a), 3), round(_total(b), 3)]}

    common = [x["id"] for x in B if x["id"] in ab]
    stay = _stay_put(common, {x["id"]: i for i, x in enumerate(A)})
    for x in A:
        if x["id"] not in bb:
            out["beats"]["removed"].append({"id": x["id"], "title": x["title"], "n": len(x["shots"]),
                                            "dur": sum(seq_dur(s) for s in x["shots"])})
    for i, x in enumerate(B):
        if x["id"] not in ab:
            out["beats"]["added"].append({"id": x["id"], "title": x["title"]})
        else:
            if x["id"] not in stay:
                out["beats"]["moved"].append({"id": x["id"], "title": x["title"], "to": i})
            if ab[x["id"]]["title"] != x["title"]:
                out["beats"]["retitled"].append({"id": x["id"], "from": ab[x["id"]]["title"], "to": x["title"]})

    def flat(beats):
        return [(bt["id"], s) for bt in beats for s in bt["shots"]]
    fa, fb = flat(A), flat(B)
    sa = {key(s): (bid, s) for bid, s in fa}
    sb_ = {key(s): (bid, s) for bid, s in fb}
    removed_beats = {r["id"] for r in out["beats"]["removed"]}
    before_ids = {s["id"] for _, s in fa if s["id"]}
    for bid, s in fa:
        if key(s) not in sb_:
            out["shots"]["removed"].append({"id": key(s), "beat": bid, "with_beat": bid in removed_beats,
                                            "gap": is_gap(s), "dur": round(seq_dur(s), 2)})
    common = [key(s) for _, s in fb if key(s) in sa]
    stay = _stay_put(common, {key(s): i for i, (_, s) in enumerate(fa)})
    for bid, s in fb:
        k = key(s)
        if k not in sa:
            out["shots"]["added"].append({
                "id": k, "beat": bid, "gap": is_gap(s), "dur": round(seq_dur(s), 2),
                # a new piece of a shot that was already there = a cut
                "split": bool(s["id"]) and s["id"] in before_ids and b is not None,
                "at": seq_start(b, k)})
            continue
        obid, os_ = sa[k]
        if obid != bid or k not in stay:
            out["shots"]["moved"].append({"id": k, "beat": bid, "from_beat": obid})
        d0, d1 = os_["end"] - os_["start"], s["end"] - s["start"]
        if abs(d0 - d1) > 0.02:
            out["shots"]["trimmed"].append({"id": k, "beat": bid, "from": round(d0, 2), "to": round(d1, 2)})
    return out


def describe(d: dict, a: dict | None, b: dict | None, ops: list[dict] | None = None) -> list[dict]:
    """The diff as short lines a creator can read, grouped by beat."""
    title = {x["id"]: x["title"] for x in ((a or {}).get("beats", []) + (b or {}).get("beats", []))}
    lines = []
    # A marked range taken out is one action, however many pieces it touched.
    if ops and all(o.get("op") == "drop_range" for o in ops) and a is not None:
        for o in ops:
            t = seq_start(a, o.get("from_shot", ""))
            if t is None:
                continue
            fb, fi = _where(a, o["from_shot"])
            start = t + float(o["from_at"]) - fb["shots"][fi]["start"]
            removed = d["total"][0] - d["total"][1] if not o.get("leave_gap") else None
            where = f"{int(start // 60)}:{start % 60:05.2f}"
            text = (f"Removed {removed:.2f}s at {where}, closed up" if removed is not None
                    else f"Lifted a range at {where}, gap left")
            lines.append({"kind": "removed" if removed is not None else "gap", "beat": fb["id"], "text": text})
        if lines:
            return lines + ov.describe(a, b)
    if d["replaced"] and b:
        lines.append({"kind": "replaced", "text": f"Started from “{b['name']}”"})
        return lines
    # A copy or a held frame shares its source shot, so the diff alone reads it as a cut.
    if ops and b is not None and all(o.get("op") in ("duplicate_shot", "freeze_frame") for o in ops):
        for o in ops:
            k = o.get("key")
            t = seq_start(b, k) if k else None
            if t is None:
                continue
            bt, _ = _where(b, k)
            text = (f"Copied a shot in “{bt['title']}”" if o["op"] == "duplicate_shot"
                    else f"Held a frame for {float(o.get('dur') or FREEZE_S):g}s at {int(t // 60)}:{t % 60:05.2f}")
            lines.append({"kind": "added", "beat": bt["id"], "shot": k, "text": text})
        return lines

    def mmss(s: float) -> str:
        return f"{int(s // 60)}:{int(s % 60):02d}"

    def n(k: int, what: str = "shot") -> str:
        return f"{k} {what}{'s' * (k != 1)}"

    for r in d["beats"]["removed"]:
        lines.append({"kind": "removed", "text": f"Removed “{r['title']}” ({n(r['n'])}, {mmss(r['dur'])})", "beat": r["id"]})
    for m in d["beats"]["moved"]:
        lines.append({"kind": "moved", "text": f"Moved “{m['title']}” to position {m['to'] + 1}", "beat": m["id"]})
    for r in d["beats"]["retitled"]:
        lines.append({"kind": "retitled", "text": f"Renamed “{r['from']}” → “{r['to']}”", "beat": r["id"]})
    for x in d["beats"]["added"]:
        lines.append({"kind": "added", "text": f"New beat “{x['title']}”", "beat": x["id"]})

    def clock(t: float | None) -> str:
        return "" if t is None else f"{int(t // 60)}:{t % 60:05.2f}"

    cuts = [x for x in d["shots"]["added"] if x.get("split")]
    gaps_added = [x for x in d["shots"]["added"] if x.get("gap")]
    added = {x["id"]: x for x in d["shots"]["added"] if not x.get("split") and not x.get("gap")}
    cut_ids = {x["id"].split("~")[0] for x in cuts}
    loose_removed = [r for r in d["shots"]["removed"] if not r["with_beat"]]
    shots_removed = [r for r in loose_removed if not r.get("gap")]

    for c in cuts:
        lines.append({"kind": "cut", "beat": c["beat"], "shot": c["id"],
                      "text": f"Cut “{title.get(c['beat'], c['beat'])}” at {clock(c['at'])}"})

    trims: dict[str, list] = {}
    for t in d["shots"]["trimmed"]:
        # the first piece of a cut shot gets shorter by definition -- not a trim
        if t["id"].split("~")[0] in cut_ids and not shots_removed:
            continue
        trims.setdefault(t["beat"], []).append(t)
    for bid, ts in trims.items():
        a0, a1 = sum(t["from"] for t in ts), sum(t["to"] for t in ts)
        if len(ts) == 1:
            verb = "Trimmed" if a1 < a0 else "Extended"
            text = f"{verb} a shot in “{title.get(bid, bid)}”: {a0:.2f}s → {a1:.2f}s"
        else:
            verb = "Tightened" if a1 < a0 else "Loosened"
            text = f"{verb} “{title.get(bid, bid)}”: {n(len(ts))}, {mmss(a0)} → {mmss(a1)}"
        lines.append({"kind": "trimmed", "beat": bid, "text": text})

    for g in gaps_added:
        lines.append({"kind": "gap", "beat": g["beat"], "text": f"Left a {g['dur']:.2f}s gap in “{title.get(g['beat'], g['beat'])}”"})
    for r in loose_removed:
        if r.get("gap"):
            lines.append({"kind": "removed", "beat": r["beat"], "text": f"Closed a {r['dur']:.2f}s gap"})

    # A removal and an addition in the same beat in one turn reads as a swap.
    by_beat: dict[str, list] = {}
    for r in shots_removed:
        swap = next((x for x in added.values() if x["beat"] == r["beat"]), None)
        if swap:
            lines.append({"kind": "swapped", "beat": r["beat"], "shot": swap["id"],
                          "text": f"Swapped a shot in “{title.get(r['beat'], r['beat'])}” for a better one"})
            added.pop(swap["id"])
        else:
            by_beat.setdefault(r["beat"], []).append(r)
    for bid, rs in by_beat.items():
        total = sum(r["dur"] for r in rs)
        what = "a shot" if len(rs) == 1 else n(len(rs))
        lines.append({"kind": "removed", "beat": bid, "shot": rs[0]["id"] if len(rs) == 1 else None,
                      "text": f"Removed {what} ({total:.2f}s) from “{title.get(bid, bid)}”"})
    for x in added.values():
        lines.append({"kind": "added", "beat": x["beat"], "shot": x["id"],
                      "text": f"Added a shot to “{title.get(x['beat'], x['beat'])}”"})
    moved_beats = {m["id"] for m in d["beats"]["moved"]}
    shot_moves = [m for m in d["shots"]["moved"] if m["beat"] not in moved_beats or m["beat"] != m["from_beat"]]
    if shot_moves and not d["beats"]["moved"]:
        where = {title.get(m["beat"], m["beat"]) for m in shot_moves}
        lines.append({"kind": "moved", "text": f"Moved {n(len(shot_moves))} within “{'”, “'.join(sorted(where))}”"})
    lines += ov.describe(a, b)
    lines += restyle.describe(a, b)
    lines += _describe_sound(a, b)
    from . import looks
    lines += looks.describe(a, b)
    from . import transitions
    lines += transitions.describe(a, b)
    from . import graphics
    lines += graphics.describe(a, b)
    if not lines:
        lines.append({"kind": "none", "text": "No change"})
    return lines


SOUND_WORDS = {"carry_out": "the sound now flows on past", "carry_in": "the next sound now starts before",
               "cut": "the sound now cuts cleanly at"}


def _describe_sound(a: dict | None, b: dict | None) -> list[dict]:
    """Joins and music, in words. Computed from the boards, like the rest."""
    if a is None or b is None:
        return []
    lines = []
    ja, jb = a.get("joins") or {}, b.get("joins") or {}
    where = {key(s): bt for bt in b["beats"] for s in bt["shots"]}
    for k in sorted(set(ja) | set(jb)):
        if ja.get(k) == jb.get(k):
            continue
        bt = where.get(k)
        place = f"the cut after a shot in “{bt['title']}”" if bt else "a cut"
        text = (f"At {place}, {SOUND_WORDS[jb[k]['sound']]} it" if k in jb
                else f"At {place}, the sound is back to automatic")
        lines.append({"kind": "sound", "beat": bt["id"] if bt else None, "shot": k, "text": text})
    ea = {key(s): s for bt in a["beats"] for s in bt["shots"]}
    for bt in b["beats"]:
        for s in bt["shots"]:
            o = ea.get(key(s))
            if o is None or is_gap(s):
                continue
            for f, plain in FX_PLAIN.items():
                x, y = o.get(f, plain), s.get(f, plain)
                if x == y:
                    continue
                if f == "effect_amount" and not s.get("effect"):
                    continue
                text = {"speed": lambda: f"Shot plays at {y:g}×" if y != 1 else "Shot back to normal speed",
                        "gain": lambda: f"Shot volume {round(x * 100)}% → {round(y * 100)}%",
                        "mute": lambda: "Muted a shot" if y else "Unmuted a shot",
                        "rotate": lambda: f"Turned a shot to {y}°",
                        "fill": lambda: "Shot fills the frame (edges cropped)" if y else "Shot shows its whole picture",
                        "mirror": lambda: "Mirrored a shot" if y else "Shot no longer mirrored",
                        "fade_in": lambda: f"Shot's sound fades in over {y:g}s" if y else "Shot's sound starts without a fade",
                        "fade_out": lambda: f"Shot's sound fades out over {y:g}s" if y else "Shot's sound ends without a fade",
                        "effect": lambda: f"Shot has the {_effect_name(y)} effect" if y else f"Took the {_effect_name(x)} effect off a shot",
                        "effect_amount": lambda: f"Shot's effect at {round(y * 100)}%",
                        # Make's motion on the beat; a describe without it raised on "Make my video again"
                        "punch": lambda: ("Shot pushes in" if y > 0 else "Shot pulls out") if y else "Shot holds still",
                        "reverse": lambda: "Shot plays backwards" if y else "Shot plays forwards again",
                        }[f]()
                lines.append({"kind": "sound" if f in ("gain", "mute", "fade_in", "fade_out") else "trimmed", "beat": bt["id"],
                              "shot": key(s), "text": text})
    sa = {x["id"]: x for x in (a.get("sound") or {}).get("strips", [])}
    sb_ = {x["id"]: x for x in (b.get("sound") or {}).get("strips", [])}
    for i in sb_.keys() - sa.keys():
        lines.append({"kind": "sound", "shot": sb_[i]["from"], "text": "Took a shot's sound off onto its own strip"})
    for i in sa.keys() - sb_.keys():
        lines.append({"kind": "sound", "text": "Deleted a sound strip (its shot stays silent)"})
    for i in sa.keys() & sb_.keys():
        x, y = sa[i], sb_[i]
        if x["mute"] != y["mute"]:
            lines.append({"kind": "sound", "text": "Muted a sound strip" if y["mute"] else "Unmuted a sound strip"})
        if x["gain"] != y["gain"]:
            lines.append({"kind": "sound", "text": f"Sound strip volume {round(x['gain'] * 100)}% → {round(y['gain'] * 100)}%"})
        for f, word in (("fade_in", "in"), ("fade_out", "out")):
            if x.get(f, 0) != y.get(f, 0):
                lines.append({"kind": "sound", "text": f"Sound strip fades {word} over {y.get(f, 0):g}s"
                              if y.get(f) else f"Sound strip no longer fades {word}"})
        if x["at"] != y["at"]:
            lines.append({"kind": "sound", "text": f"Moved a sound strip {'later' if y['at'] > x['at'] else 'earlier'} by {abs(y['at'] - x['at']):.2f}s"})
    va = {x["id"]: x for x in (a.get("sound") or {}).get("voice", [])}
    vb = {x["id"]: x for x in (b.get("sound") or {}).get("voice", [])}
    for i in vb.keys() - va.keys():
        lines.append({"kind": "sound", "text": f"Recorded {vb[i]['dur']:.1f}s of your voice at {int(vb[i]['at'] // 60)}:{int(vb[i]['at'] % 60):02d}"})
    for i in va.keys() - vb.keys():
        lines.append({"kind": "sound", "text": "Deleted a recording of your voice"})
    for i in va.keys() & vb.keys():
        x, y = va[i], vb[i]
        if x["mute"] != y["mute"]:
            lines.append({"kind": "sound", "text": "Muted your voice" if y["mute"] else "Unmuted your voice"})
        if x["gain"] != y["gain"]:
            lines.append({"kind": "sound", "text": f"Your voice's volume {round(x['gain'] * 100)}% → {round(y['gain'] * 100)}%"})
        for f, word in (("fade_in", "in"), ("fade_out", "out")):
            if x.get(f, 0) != y.get(f, 0):
                lines.append({"kind": "sound", "text": f"Your voice fades {word} over {y.get(f, 0):g}s"
                              if y.get(f) else f"Your voice no longer fades {word}"})
        if x["at"] != y["at"]:
            lines.append({"kind": "sound", "text": f"Moved your voice {'later' if y['at'] > x['at'] else 'earlier'} by {abs(y['at'] - x['at']):.2f}s"})
    if (a.get("music") or None) != (b.get("music") or None):
        m, m0 = b.get("music") or {}, a.get("music") or {}
        only_volume = {k: v for k, v in m.items() if k != "volume"} == {k: v for k, v in m0.items() if k != "volume"}
        lines.append({"kind": "sound", "text": f"Music volume {round(float(m0.get('volume', 1)) * 100)}% → "
                                              f"{round(float(m.get('volume', 1)) * 100)}%" if only_volume and m
                      else "Music taken off the edit" if "track" in m and not m["track"]
                      else "Music under the edit changed"})
    return lines


# --------------------------------------------------------------------------
# session: the turn log
# --------------------------------------------------------------------------

@dataclass
class Turn:
    id: int
    kind: str                       # "chat" | "direct" | "check" (the AI checking its own edit)
    text: str                       # what the user said / did
    ops: list[dict]                 # as recorded (after first application)
    reply: str = ""
    question: str | None = None
    choices: list[str] = field(default_factory=list)
    direction: dict | None = None   # {"text", "themes", "labels"} when this turn set one
    undone: bool = False
    at: float = field(default_factory=time.time)
    cost: float | None = None       # dollars, when an AI answered this turn
    sheets: list[str] = field(default_factory=list)   # contact sheets the AI looked at (selfcheck.py)
    # filled by replay
    skipped: list[str] = field(default_factory=list)
    diff: dict | None = None
    lines: list[dict] = field(default_factory=list)


class Session:
    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.board: dict | None = None
        self.proposals: dict | None = None
        self._next = 1

    def replay(self, cat: Catalog, make_proposals) -> None:
        """Rebuild the board from the log. Each op is applied or skipped, never guessed."""
        board, proposals = None, None
        for t in self.turns:
            if t.undone:
                continue  # keeps its last diff, so the UI can show what Redo would bring back
            t.skipped, t.diff, t.lines = [], None, []
            if t.direction is not None:
                proposals = make_proposals(t.direction)
            before = board
            recorded = []
            for k, op in enumerate(t.ops):
                try:
                    board, rec = apply(board, op, cat, proposals,
                                       new_id=lambda k=k, t=t: f"n{t.id}{chr(97 + k)}")
                    recorded.append(rec)
                except OpError as e:
                    t.skipped.append(str(e))
                    recorded.append(op)
            t.ops = recorded
            if t.ops:
                t.diff = diff(before, board)
                t.lines = describe(t.diff, before, board, t.ops)
        self.board, self.proposals = board, proposals

    def add(self, turn_kwargs: dict, cat: Catalog, make_proposals) -> Turn:
        t = Turn(id=self._next, **turn_kwargs)
        self._next += 1
        self.turns.append(t)
        self.replay(cat, make_proposals)
        return t

    def toggle(self, tid: int, cat: Catalog, make_proposals) -> None:
        for t in self.turns:
            if t.id == tid:
                t.undone = not t.undone
        self.replay(cat, make_proposals)

    def last_active(self) -> Turn | None:
        return next((t for t in reversed(self.turns) if not t.undone and t.ops), None)
