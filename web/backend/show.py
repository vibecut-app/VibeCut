"""Watch it edit (sarah, 2026-11-24: "instead of making it generating
immediate, can you show the specific moves you're doing ... edit and cut and
move around the panel with all the existing functions to get to the final
result"). After Make lands, the editor plays back how the edit was put
together, one move at a time, on its own timeline, panels and preview: the
clips laid down in the order they were filmed, each part trimmed to its
moments, the best moment moved to the front, the song and its beat, the
frame, the look, the words, the push-ins, then the passes that ran after.

Each step is a board, and the editor draws it exactly as it draws any edit.
From the song on, a step is the Make turn's own ops applied in order with
the ids the log gives them (`n{turn}{a, b, …}`), so the words placed here are
the words the finished edit has. The shots before that are the finished
board's own entries: whole clips first (at most `WHOLE_MAX_S`, so one long
take can't push the rest off screen), then each part trimmed to the windows
the picker chose before the music moved them (`raw`), then the hook lifted
out of its stop and the glimpses put in front.

Nothing here changes the project: the turn has already landed and Undo still
takes the whole edit back. It is a playback of moves already decided, which
the screen says. Free, no model."""
from __future__ import annotations

import copy
from datetime import datetime

from . import board as bd
from . import overlays as ov
from . import timeline

HOOK_BEAT = "r0"        # remix.board_of's hook part
WHOLE_MAX_S = 12.0      # a clip lands on the timeline at most this long [prior]
LEAD_S = 0.4            # a caption is shown this far in, past its entrance [prior]

# What each later turn the app adds by itself after Make was doing, in words.
LATER = {"Smoother cuts": "Nudging each cut onto movement",
         "From your profile": "Adding what your profile asks for"}


def _kind(op: dict) -> str:
    """Which move an op of the Make turn belongs to, in the order the show plays them."""
    k = op.get("op")
    if k in ("set_music", "set_join"):
        return "music"
    if k == "set_shot":
        f = set(op) - {"op", "shot", "all"}
        if f and f <= {"fill", "aim", "backdrop"}:
            return "frame"
        if f == {"punch"}:
            return "push"
        if f == {"speed"}:
            return "speed"
        return "other"
    if k == "split":
        return "speed"
    return {"set_look": "look", "set_transition": "joins", "overlay_style": "style",
            "add_overlay": "words", "edit_overlay": "words", "drop_overlay": "words",
            "add_graphic": "graphics", "edit_graphic": "graphics", "drop_graphic": "graphics"}.get(k, "other")


ORDER = ("music", "frame", "look", "style", "words", "push", "speed", "joins", "graphics", "other")


def _apply(board: dict, ops: list[tuple[int, dict]], tid: int, cat, proposals) -> dict:
    """The ops on a copy, named as the log names them; one that fails is passed over, as replay does."""
    for k, op in ops:
        try:
            board, _ = bd.apply(board, copy.deepcopy(op), cat, proposals, new_id=lambda k=k: f"n{tid}{chr(97 + k)}")
        except (bd.OpError, ov.OverlayError):
            continue
    return board


def _start(board: dict, key: str | None) -> float:
    for it in timeline.layout(board):
        if it["key"] == key:
            return it["seq_start"]
    return 0.0


def steps(make: bd.Turn, later: list[bd.Turn], cat, proposals=None, raw: dict | None = None,
          clips: int = 0, names: dict | None = None) -> list[dict]:
    """The moves, in order. Each: kind (what the editor shows), say (the one
    line), board, and where to look: `reveal` (the first n shots of a board
    being laid), `shot` / `overlay` / `join` to pick, `at` for the playhead.
    `raw`: shot id → the window picked before the music cut it to the beat.
    `names`: {"track": its title, "look": its name}. [] when the turn isn't a
    Make with its board (nothing to play back)."""
    ops = make.ops or []
    if not ops or ops[0].get("op") != "choose_option" or not ops[0].get("snapshot"):
        return []
    names = names or {}
    snap = copy.deepcopy(ops[0]["snapshot"])
    beats = snap.get("beats") or []
    tease = next((b for b in beats if b["id"] == bd.TEASER_BEAT), None)
    hook = next((b for b in beats if b["id"] == HOOK_BEAT and b is not tease), None)
    body = [b for b in beats if b is not tease and b is not hook]
    if not body:
        return []
    raw = raw or {}

    def whole(e: dict) -> dict:
        s = cat.shots.get(e.get("id"))
        if s is None or bd.is_gap(e) or bd.is_freeze(e):
            return dict(e)
        lo, hi = s.start, s.end
        span = max(WHOLE_MAX_S, e["end"] - e["start"])
        if hi - lo > span:
            mid = (e["start"] + e["end"]) / 2
            lo = max(lo, min(mid - span / 2, hi - span))
            hi = lo + span
        return {**e, "start": round(lo, 3), "end": round(hi, 3)}

    def picked(e: dict) -> dict:
        s, w = cat.shots.get(e.get("id")), raw.get(e.get("id"))
        if s is None or not w or e.get("teaser") or not (s.start - 1e-3 <= w[0] < w[1] <= s.end + 1e-3):
            return dict(e)
        return {**e, "start": round(w[0], 3), "end": round(w[1], 3)}

    def when(e: dict | None):
        s = cat.shots.get((e or {}).get("id"))
        return s.when if s is not None else None

    def filmed(es: list[dict]) -> list[dict]:
        return [e for _, e in sorted(enumerate(es), key=lambda ie: (when(ie[1]) is None, when(ie[1]) or datetime.min, ie[0]))]

    # each part in the order it was filmed, and the hook back where it was
    # filmed, so both can be seen moving to where the edit has them
    stops = [{**b, "shots": filmed(b["shots"])} for b in body]
    lifted: list[tuple[int, dict]] = []

    for e in (hook or {}).get("shots", []):
        w = when(e)
        best, at = 0, 0          # filmed when, unknown: it starts the first stop
        if w is not None:
            best, at = len(stops) - 1, len(stops[-1]["shots"])     # after everything, unless something is later
            for i, b in enumerate(stops):
                j = next((j for j, x in enumerate(b["shots"]) if when(x) is not None and when(x) > w), None)
                if j is None:
                    continue
                best, at = i, j
                if j == 0 and i > 0 and stops[i - 1]["shots"]:
                    # between two stops: the one filmed nearer to it
                    prev, nxt = when(stops[i - 1]["shots"][-1]), when(b["shots"][0])
                    if prev is not None and nxt is not None and (w - prev) < (nxt - w):
                        best, at = i - 1, len(stops[i - 1]["shots"])
                break
        stops[best]["shots"].insert(at, e)
        lifted.append((best, e))

    def board(bs: list[dict]) -> dict:
        return {**snap, "beats": bs}

    def stop_beats(trimmed: int) -> list[dict]:
        return [{**b, "shots": [(picked if i < trimmed else whole)(e) for e in b["shots"]]} for i, b in enumerate(stops)]

    out: list[dict] = []
    n_clips = len({e["id"].split(":")[0] for b in stops for e in b["shots"] if e.get("id")})
    out.append({"kind": "read", "say": f"Looking through your {clips or n_clips} clips", "board": board([])})
    laid = board(stop_beats(0))
    keys = [bd.key(e) for b in laid["beats"] for e in b["shots"]]
    for n, k in enumerate(keys, 1):
        out.append({"kind": "lay", "say": "Putting your clips on the timeline, in the order you filmed them",
                    "board": laid, "reveal": n, "shot": k})
    for i, b in enumerate(stops):
        bb = board(stop_beats(i + 1))
        first = bd.key(b["shots"][0]) if b["shots"] else None
        out.append({"kind": "trim", "say": "Trimming each clip to its best moment", "board": bb, "shot": first})
    cut = stop_beats(len(stops))
    if hook and hook["shots"]:
        ids = {id(e) for _, e in lifted}
        cut = [{**b, "shots": [x for x, e in zip(b["shots"], stops[i]["shots"]) if id(e) not in ids]} for i, b in enumerate(cut)]
        cut = [b for b in cut if b["shots"]]
        cut = [{**hook, "shots": [picked(e) for e in hook["shots"]]}] + cut
        out.append({"kind": "hook", "say": "Moving the best moment to the front", "board": board(cut),
                    "shot": bd.key(hook["shots"][0])})
    final = [{**b, "shots": [picked(e) for e in b["shots"]]} for b in body]
    lead = cut[:1] if hook and hook["shots"] else []
    if [bd.key(e) for b in cut[len(lead):] for e in b["shots"]] != [bd.key(e) for b in final for e in b["shots"]]:
        moves = [bd.key(e) for b in final for e in b["shots"]]
        was = [bd.key(e) for b in cut[len(lead):] for e in b["shots"]]
        cut = lead + final
        out.append({"kind": "order", "say": "Rearranging the shots in each part so they flow", "board": board(cut),
                    "shot": next((k for k, w in zip(moves, was) if k != w), None)})
    if tease and tease["shots"]:
        cut = [dict(tease)] + cut
        out.append({"kind": "teaser", "say": "Opening on a few glimpses of later in the day", "board": board(cut),
                    "shot": bd.key(tease["shots"][0])})

    # from here on, the turn's own ops on the finished board's shots
    now = copy.deepcopy(snap)
    groups: dict[str, list[tuple[int, dict]]] = {g: [] for g in ORDER}
    for k, op in enumerate(ops[1:], 1):
        groups[_kind(op)].append((k, op))
    moved = [(e["start"], e["end"]) for b in cut for e in b["shots"]] != [(e["start"], e["end"]) for b in now["beats"] for e in b["shots"]]
    if groups["music"] or moved:
        now = _apply(now, groups["music"], make.id, cat, proposals)
        song = names.get("track")
        said = (f"Adding a song, “{song}”" if song else "Adding a song") if groups["music"] else ""
        said = (said + ", and putting the cuts on its beat" if said else "Putting the cuts on the beat") if moved else said
        out.append({"kind": "music", "say": said, "board": now, "at": 0.0})
    if groups["frame"]:
        now = _apply(now, groups["frame"], make.id, cat, proposals)
        out.append({"kind": "frame", "say": "Filling the frame, so there are no black bars", "board": now,
                    "shot": groups["frame"][0][1].get("shot")})
    if groups["look"]:
        now = _apply(now, groups["look"], make.id, cat, proposals)
        look = names.get("look")
        out.append({"kind": "look", "say": f"Giving it the {look} look" if look else "Picking the look", "board": now})
    if groups["style"] and not groups["words"]:
        now = _apply(now, groups["style"], make.id, cat, proposals)
        out.append({"kind": "words", "say": "Styling the captions", "board": now})
    elif groups["style"]:
        now = _apply(now, groups["style"], make.id, cat, proposals)
    for k, op in groups["words"]:
        before = {o["id"] for o in now.get("overlays") or []}
        now = _apply(now, [(k, op)], make.id, cat, proposals)
        new = [o for o in now.get("overlays") or [] if o["id"] not in before]
        if op.get("op") != "add_overlay" or not new:
            continue
        o = new[0]
        # the words themselves: a title's own line (its date or place under it
        # is the second line), a caption's line without the place over it
        lines = [x.strip() for x in (o.get("text") or o.get("sub") or "").split("\n") if x.strip()]
        title = o.get("kind") in ("title", "heading")
        text = " ".join(lines) if title else (lines[-1] if lines else "")
        said = f"Typing the title, “{text}”" if title and text else f"Typing “{text}”" if text else "Placing a caption"
        out.append({"kind": "words", "say": said, "board": now, "overlay": o["id"]})
    if groups["push"]:
        now = _apply(now, groups["push"], make.id, cat, proposals)
        out.append({"kind": "push", "say": "Adding slow push-ins, so the picture keeps moving", "board": now,
                    "shot": groups["push"][0][1].get("shot")})
    if groups["speed"]:
        now = _apply(now, groups["speed"], make.id, cat, proposals)
        out.append({"kind": "speed", "say": "Speeding up into the drop", "board": now,
                    "shot": next((op.get("shot") for _, op in groups["speed"] if op.get("op") == "set_shot"), None)})
    if groups["joins"]:
        now = _apply(now, groups["joins"], make.id, cat, proposals)
        kinds = {op.get("kind") for _, op in groups["joins"]}
        out.append({"kind": "joins", "say": "Adding a flash on the drop" if kinds == {"flash"} else "Adding transitions",
                    "board": now, "join": groups["joins"][0][1].get("shot")})
    if groups["graphics"]:
        now = _apply(now, groups["graphics"], make.id, cat, proposals)
        out.append({"kind": "graphics", "say": "Adding graphics", "board": now})
    if groups["other"]:
        now = _apply(now, groups["other"], make.id, cat, proposals)
        out.append({"kind": "other", "say": "Finishing touches", "board": now})
    for t in later:
        if t.undone or not t.ops:
            continue
        now = _apply(now, list(enumerate(t.ops)), t.id, cat, proposals)
        said = "Checking its own edit" if t.kind == "check" else LATER.get(t.text, t.text)
        out.append({"kind": "turn", "say": said, "board": now, "turn": t.text})

    # where to look: the playhead on what just changed
    for s in out:
        if "at" in s:
            continue
        if s.get("overlay"):
            o = next((x for x in ov.resolve(s["board"]) if x["id"] == s["overlay"]), None)
            s["at"] = round(min(o["start"] + LEAD_S, (o["start"] + o["end"]) / 2), 3) if o else 0.0
        elif s.get("shot") or s.get("join"):
            s["at"] = _start(s["board"], s.get("shot") or s.get("join"))
            if s.get("join"):
                s["at"] = max(0.0, next((it["seq_end"] for it in timeline.layout(s["board"]) if it["key"] == s["join"]), 0.0) - 0.5)
        else:
            s["at"] = 0.0
    return out
