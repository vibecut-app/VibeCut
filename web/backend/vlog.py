"""The vlog grammar: scenes, the three-shot rule, stillness.

Why this exists (2026-10-19, after the creator watched a made video: "the
cut is too random, it's not those pretty vlogs on YouTube"). Laid out shot
by shot, her cut was 28 singles of 0.6–1.1 s, grouped by 45-minute gaps,
every one chosen on its own worth and none on what sat next to it. The
vlogs she means do three things ours didn't (design/research 01, 06, and
the editing-craft reading of 2026-10-19):

1. **Scenes, not sessions.** A scene is a place and an activity: a new
   one when the GPS moves on or twenty minutes pass (brief.spots), not
   when forty-five minutes do. Four to seven scenes for a 90-second vlog.
2. **The three-shot rule.** Inside a scene the shots run wide → medium →
   close: the place, the person doing the thing, the detail (the plate,
   the cup, the hands, the face). Two look-alikes never sit together.
   A scene ends on a detail or a face, not on a passing street.
3. **Stillness.** The longest holds go to the stillest shots -- a window,
   a cup, a view -- and a handheld walk gets a short one. Shots run 3–6 s
   (make.PRIOR for tall / wide), cut where the action ends.

What the index already knows is enough for all three: face area and face
count for shot size, labels for details, per-second motion for stillness,
GPS and capture time for scenes. Nothing new is read from the files.
Every threshold here is a prior until the creator says otherwise.
"""

from __future__ import annotations

import numpy as np

from . import brief, select as sel, storyboard as sb

CLOSE_FACE = 0.06        # a face this big is a close shot
MEDIUM_FACE = 0.015      # a face this big is a medium shot
DETAIL = {"plate", "tableware", "utensil", "cup", "drinking_glass", "fork", "spoon", "cookware", "food", "dessert",
          "beverage", "plant", "foliage", "flower", "book", "document", "laptop", "computer", "keyboard", "pen",
          "office_supplies", "consumer_electronics", "art", "decoration", "frame", "textile", "jewelry", "hat", "shoe",
          "eyeglasses", "raw_glass", "appliance", "machine"}
WIDE = {"outdoor", "sky", "blue_sky", "cloudy", "night_sky", "land", "structure", "road", "path", "crosswalk", "grass",
        "fence", "conveyance", "portal", "interior_room", "window", "door", "stairs", "crowd"}
LOOKALIKE = 0.78         # embedding cosine: the same view again
STILL, BUSY = 15.0, 40.0 # per-second motion (index units): rest, and walking with the phone
STILL_HOLD, BUSY_HOLD = 1.5, 0.7
MIN_HOLD_S, MAX_HOLD_S = 1.5, 7.0
MAX_SCENES = 7
MIN_PICK_S = 2.5         # a shot filmed shorter than this can't hold a vlog's pace
LENGTH_OK = 0.9          # a vlog this close to the length asked for is left alone
ASK_MORE_MAX = 1.6       # ...else more moments are asked for, at most this many times over


def shot_size(s) -> str:
    """wide / medium / close, from what the index knows of the frame."""
    fa = float(getattr(s, "face_area", 0.0) or 0.0)
    top = [k for k, _ in sorted((getattr(s, "labels", None) or {}).items(), key=lambda kv: -kv[1])[:4]]
    if fa >= CLOSE_FACE or any(t in DETAIL for t in top[:2]):
        return "close"
    if fa >= MEDIUM_FACE or (getattr(s, "faces", 0) or 0) > 0:
        return "medium"
    return "wide"


def _sim(a, b) -> float:
    va, vb = getattr(a, "vec", None), getattr(b, "vec", None)
    if va is None or vb is None or getattr(va, "size", 0) == 0 or va.size != vb.size:
        return 0.0
    return float(np.dot(va, vb))


def sequence(picks: list[sel.Pick]) -> list[sel.Pick]:
    """The three-shot order for one scene: wide, then medium, then close,
    each class in filming order; look-alikes kept apart; the scene ends on
    a close shot or a face when it has one."""
    if len(picks) <= 1:
        return list(picks)
    rank = {"wide": 0, "medium": 1, "close": 2}
    ordered = sorted(picks, key=lambda p: (rank[shot_size(p.shot)], p.shot.order))
    # keep look-alikes apart: a shot too like the one before it moves one place
    # on, once; when everything left looks the same there is nothing to do
    out: list[sel.Pick] = []
    pending = list(ordered)
    deferred: set[str] = set()
    while pending:
        nxt = pending.pop(0)
        if out and pending and nxt.shot.id not in deferred and _sim(out[-1].shot, nxt.shot) >= LOOKALIKE:
            deferred.add(nxt.shot.id)
            pending.insert(1, nxt)
            continue
        out.append(nxt)
    # end on a detail or a face
    last_close = next((i for i in range(len(out) - 1, -1, -1)
                       if shot_size(out[i].shot) == "close" or (getattr(out[i].shot, "faces", 0) or 0) > 0), None)
    if last_close is not None and last_close != len(out) - 1:
        out.append(out.pop(last_close))
    return out


def scenes(plan: sel.Plan) -> None:
    """Regroup the plan's picks into scenes in place: a stop of the day
    (brief.spots: a place, twenty minutes) is sequenced wide -> medium ->
    close on its own; stops are then folded, smallest neighbours first,
    into at most MAX_SCENES, and a folded scene keeps its stops in the
    order of the day -- breakfast never comes after the walk."""
    picks = [p for sess in plan.sessions for p in sess]
    if not picks:
        return
    where = brief.spots([p.shot for p in picks])
    groups: dict[int, list[sel.Pick]] = {}
    for p in picks:
        groups.setdefault(where.get(p.shot.id, 0), []).append(p)
    stops = [sequence(sorted(g, key=lambda p: p.shot.order)) for _, g in sorted(groups.items())]
    folded: list[list[list[sel.Pick]]] = [[st] for st in stops if st]
    while len(folded) > MAX_SCENES:
        i = min(range(len(folded) - 1), key=lambda j: sum(map(len, folded[j])) + sum(map(len, folded[j + 1])))
        folded[i:i + 2] = [folded[i] + folded[i + 1]]
    plan.stops = folded                       # the stops inside each scene: flow() reorders within one, never across
    plan.sessions = [[p for st in scene for p in st] for scene in folded]
    plan.titles = titles(plan.sessions)
    for i, sess in enumerate(plan.sessions):
        for p in sess:
            p.session = i


def titles(sessions: list[list[sel.Pick]]) -> list[str]:
    """A part's name: the time of day, and the clock when a day has two
    afternoons ("Afternoon", "Afternoon, 3 pm"); never "Part 4"."""
    out: list[str] = []
    for i, g in enumerate(sessions):
        when = g[0].shot.when if g else None
        if not when:
            out.append(f"Scene {i + 1}")
            continue
        name = sb.part_of_day(when)
        if any(t == name or t.startswith(name + ",") for t in out):
            h = when.hour % 12 or 12
            name = f"{name}, {h}{':%02d' % when.minute if when.minute else ''} {'am' if when.hour < 12 else 'pm'}"
        out.append(name)
    return out


def stillness(s) -> float:
    """How much longer (or shorter) a shot may hold than the median: still
    frames rest, handheld walks don't."""
    a = float(getattr(s, "activity", 0.0) or 0.0)
    return STILL_HOLD if a < STILL else BUSY_HOLD if a > BUSY else 1.0


def breathe(plan: sel.Plan, clips: dict, fp: dict) -> dict:
    """Give every pick a hold: the vlog's median, the arc's curve for where
    it sits, times its stillness, clamped to MIN_HOLD_S..MAX_HOLD_S; cut in
    where the action is (select.window). Returns a small report."""
    seq = [p for sess in plan.sessions for p in sess]
    n = max(len(seq), 1)
    med = float(fp.get("median_s") or 4.0)
    curve = fp.get("curve") or [1.0] * 5
    held, short = 0, 0
    for k, p in enumerate(seq):
        pos = (k + 0.5) / n
        c = float(np.interp(pos * (len(curve) - 1), range(len(curve)), curve))
        want = float(np.clip(med * c * stillness(p.shot), MIN_HOLD_S, MAX_HOLD_S))
        p.start, p.end, p.short = sel.window(clips, p.shot, want)
        held += stillness(p.shot) > 1.0
        short += p.short
    return {"shots": len(seq), "still_held": held, "filmed_too_short": short, "median_s": med}


def describe(plan: sel.Plan) -> str:
    sizes = [[shot_size(p.shot) for p in sess] for sess in plan.sessions]
    return f"{len(plan.sessions)} scenes, " + "; ".join("→".join(x[0] for x in s) for s in sizes if s)


# --------------------------------------------------------------------------
# 5. continuity between neighbours: inside a scene, the light flows
# --------------------------------------------------------------------------

MAX_FLOW = 8             # scenes longer than this keep their three-shot order (the search would be guesswork)
LOOKALIKE_PEN = 1.5      # a look-alike next to its twin costs more than any lighting jump
END_PEN = 1.0            # a scene that could end on a detail or a face but doesn't


def _side(p: sel.Pick, clips: dict):
    """The pick as the cut checker sees it (seams.side), or None."""
    from . import seams
    s = p.shot
    try:
        return seams.side({"kind": "shot", "clip_id": s.clip_id, "shot_id": s.id, "key": s.id,
                           "src_start": p.start, "src_end": p.end}, clips)
    except Exception:  # noqa: BLE001 -- a clip the checker can't read is just unmeasured
        return None


def _pair(sides: dict, a, b, cache: dict) -> float:
    from cutgrammar import joins
    if a is None or b is None or sides.get(a.shot.id) is None or sides.get(b.shot.id) is None:
        return 0.0
    k = (a.shot.id, b.shot.id)
    if k not in cache:
        fs = joins.measure(sides[a.shot.id], sides[b.shot.id])
        joins.gate(fs, {"meta", "still", "audio"})
        cache[k] = joins.cost(fs)
    return cache[k]


def _closes(p: sel.Pick) -> bool:
    return shot_size(p.shot) == "close" or (getattr(p.shot, "faces", 0) or 0) > 0


def flow(plan: sel.Plan, clips: dict) -> int:
    """Within each scene, among the orders that keep wide -> medium -> close,
    take the one whose cuts are smoothest by the joins checker (brightness,
    colour, energy, loudness steps), with look-alikes apart and the scene
    still ending on a detail or a face. Returns how many scenes moved."""
    import itertools
    moved = 0
    stops = getattr(plan, "stops", None) or [[sess] for sess in plan.sessions]
    flat = [p for scene in stops for st in scene for p in st]
    for scene in stops:
        for k, sess in enumerate(scene):
            if not 2 <= len(sess) <= MAX_FLOW:
                continue
            moved += _flow_stop(sess, scene, k, flat, clips, plan)
    plan.sessions = [[p for st in scene for p in st] for scene in stops]
    return moved


def _flow_stop(sess: list[sel.Pick], scene: list[list[sel.Pick]], k: int, flat: list[sel.Pick], clips: dict, plan: sel.Plan) -> int:
    import itertools
    sides = {p.shot.id: _side(p, clips) for p in sess}
    if not any(sides.values()):
        return 0
    rank = {"wide": 0, "medium": 1, "close": 2}
    tiers = [[p for p in sess if rank[shot_size(p.shot)] == t] for t in range(3)]
    can_close = any(_closes(p) for p in sess)
    cache: dict = {}
    i0 = flat.index(sess[0])
    before = flat[i0 - 1] if i0 > 0 else (plan.hook[-1] if plan.hook else None)
    after = flat[i0 + len(sess)] if i0 + len(sess) < len(flat) else None
    for q in (before, after):
        if q is not None and q.shot.id not in sides:
            sides[q.shot.id] = _side(q, clips)
    if True:
        def total(order: list[sel.Pick]) -> float:
            c = _pair(sides, before, order[0], cache) + _pair(sides, order[-1], after, cache)
            for x, y in zip(order, order[1:]):
                c += _pair(sides, x, y, cache)
                if _sim(x.shot, y.shot) >= LOOKALIKE:
                    c += LOOKALIKE_PEN
            if can_close and not _closes(order[-1]):
                c += END_PEN
            return c

        best, best_c = list(sess), total(sess)
        for perm in itertools.product(*(itertools.permutations(t) if t else [()] for t in tiers)):
            order = [p for tier in perm for p in tier]
            c = total(order)
            if c < best_c - 1e-6:
                best, best_c = order, c
        if [p.shot.id for p in best] != [p.shot.id for p in sess]:
            scene[k] = best
            return 1
    return 0


# --------------------------------------------------------------------------
# 6. music phrases as scenes: a scene change lands on a phrase, not every cut on a beat
# --------------------------------------------------------------------------

PHRASE_BEATS = 16        # four bars: where a track's phrases turn [prior]
HALF_PHRASE = 8          # a scene shorter than a phrase lands on two bars


def phrase(plan: sel.Plan, clips: dict, period: float) -> dict:
    """The hook ends on a whole beat (so the drop lands), and every scene
    runs a whole number of phrases: its shots stretch or shrink together,
    within the hold clamp, and what's left goes to the closing shot. Shots
    inside a scene fall where the action ends, not on a beat."""
    for p in plan.hook:
        beats = max(2, int(round(p.duration / period)))
        p.start, p.end, p.short = sel.window(clips, p.shot, beats * period)
    report = {"scenes": 0, "on_phrase": 0}
    for sess in plan.sessions:
        if not sess:
            continue
        report["scenes"] += 1
        total = sum(p.duration for p in sess)
        unit = (PHRASE_BEATS if total >= 0.75 * PHRASE_BEATS * period else HALF_PHRASE) * period
        want_total = max(unit, round(total / unit) * unit)
        factor = want_total / total if total > 0 else 1.0
        for p in sess:
            want = float(np.clip(p.duration * factor, MIN_HOLD_S, MAX_HOLD_S))
            p.start, p.end, p.short = sel.window(clips, p.shot, want)
        left = want_total - sum(p.duration for p in sess)
        # the closing shot takes up the slack where it has footage (it rests on the detail)
        for p in reversed(sess):
            if abs(left) < 1e-3:
                break
            room = (p.shot.end - p.end) if left > 0 else (p.end - p.start - MIN_HOLD_S)
            give = min(left, room) if left > 0 else max(left, -room)
            if give > 1e-3 or give < -1e-3:
                p.end = round(p.end + give, 3)
                left -= give
        if abs(sum(p.duration for p in sess) - want_total) < 0.05:
            report["on_phrase"] += 1
    return report


# --------------------------------------------------------------------------
# 7. natural sound up front: the place's own sound carries, music rises on a scene change
# --------------------------------------------------------------------------

MUSIC_GAIN = 0.5         # the bed at a scene change [prior]
SETTLE = 0.6             # ...and this share of it inside the scene: about a third under the place's sound
SWELL_S = 2.0            # how long the music stays up as a scene opens


def swells(plan: sel.Plan) -> list[list[float]]:
    """Duck entries in edit seconds: inside every scene the music settles to
    SETTLE of its gain; around each scene change it is at full. Talking
    ducks (bed.ducks) sit under these; the mixer takes the quieter."""
    out: list[list[float]] = []
    t = sum(p.duration for p in plan.hook)
    for sess in plan.sessions:
        if not sess:
            continue
        a, b = t + SWELL_S, t + sum(p.duration for p in sess) - SWELL_S
        if b - a >= 1.0:
            out.append([round(a, 3), round(b, 3), SETTLE])
        t += sum(p.duration for p in sess)
    return out


def carries(plan: sel.Plan) -> list[dict]:
    """set_join ops: inside a scene the place's sound runs on under the next
    shot (an L cut); a scene change keeps the board's default."""
    out = []
    for sess in plan.sessions:
        for p in sess[:-1]:
            out.append({"op": "set_join", "shot": p.shot.id, "sound": "carry_out"})
    return out


# --------------------------------------------------------------------------
# 8. then judge it: one word per scene -- keep, cut, longer
# --------------------------------------------------------------------------

WORDS = ("keep", "cut", "longer")
LONGER = 0.35            # "longer" holds each shot this much more, where it has footage
LONGER_MAX_S = 2.0


def verdict_ops(board: dict, cat, beat_id: str, word: str) -> tuple[list[dict], str, dict]:
    """(ops, the turn's text, the record) for one scene's word. keep = no
    ops; cut = every shot of the scene out; longer = each shot's out point
    later, where its clip has footage. The record carries what the scene
    was (its labels, holds), so a verdict can later be read against the
    picker's reasons (the calibration record), and habits.py reads cut /
    longer as removed / held."""
    if word not in WORDS:
        raise ValueError(f"a scene's word is one of {', '.join(WORDS)}")
    beat = next((b for b in board.get("beats", []) if b.get("id") == beat_id), None)
    if beat is None:
        raise ValueError("no such scene")
    shots = [e for e in beat.get("shots", []) if not e.get("gap")]
    labels: dict[str, float] = {}
    for e in shots:
        s = cat.shots.get(str(e["id"]).split("~")[0]) if cat else None
        for k, v in (getattr(s, "labels", None) or {}).items():
            labels[k] = max(labels.get(k, 0.0), float(v))
    rec = {"kind": "scene_verdict", "beat": beat_id, "title": beat.get("title", ""), "word": word,
           "shots": len(shots), "seconds": round(sum(float(e["end"]) - float(e["start"]) for e in shots), 2),
           "labels": [k for k, _ in sorted(labels.items(), key=lambda kv: -kv[1])[:5]]}
    title = beat.get("title") or "this"
    if word == "keep":
        return [], f"Kept the {title} scene", rec
    if word == "cut":
        ops = [{"op": "drop_shot", "shot": e.get("key") or e["id"]} for e in shots]
        return ops, f"Cut the {title} scene", rec
    ops = []
    for e in shots:
        s = cat.shots.get(str(e["id"]).split("~")[0]) if cat else None
        src_end = float(getattr(s, "end", e["end"])) if s is not None else float(e["end"])
        more = min(LONGER_MAX_S, LONGER * (float(e["end"]) - float(e["start"])))
        to = min(src_end, float(e["end"]) + more)
        if to > float(e["end"]) + 0.1:
            ops.append({"op": "trim", "shot": e.get("key") or e["id"], "edge": "out", "to": round(to, 3)})
    return ops, f"Held the {title} scene longer", rec
