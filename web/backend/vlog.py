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
   a cup, a view -- and a handheld walk gets a short one, cut where the
   action ends.

Rewritten 2026-10-24 against what the good vlogs measured (house.py): the
3–6 s a shot of 2026-10-19 was a guess, and the real ones are quicker and
far less even -- b-roll at about 2 s, a second for a walk, a long rest on
one still shot per scene, talk to the lens held for its sentence and broken
up by cutaways, music stepping out while someone talks. Between 2026-10-23
and this date none of this ran: a merge kept a make.py without it.

What the index already knows is enough for all three: face area and face
count for shot size, labels for details, per-second motion for stillness,
GPS and capture time for scenes. Nothing new is read from the files.
Every threshold here is a prior until the creator says otherwise.
"""

from __future__ import annotations

import math

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
STILL_HOLD, BUSY_HOLD = 1.3, 0.45   # around the house's b-roll length [priors]
REST = 2.6               # a scene's one still rest: this many b-roll lengths, inside the good side's held shots [prior]
MIN_HOLD_S, MAX_HOLD_S = 0.9, 16.0   # the good long vlogs' quick shots (p10 ~1 s) and held ones (p90 up to 16 s)
MAX_SCENES = 7
MIN_PICK_S = 1.5         # a shot filmed shorter than this can't hold even a quick b-roll beat (was 2.5 s
                         # while every shot held 3–6 s; the good vlogs' b-roll runs about 2 s, house.py)
LENGTH_OK = 0.9          # a vlog this close to the length asked for is left alone
ASK_MORE_MAX = 1.6       # ...else more moments are asked for, at most this many times over
FILL_MAX_S = 5.0         # when the shoot has no more moments, a b-roll shot may hold this long to reach
                         # the length promised -- inside the good vlogs' held shots (p90 up to 16 s) [prior]


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


def sequence(picks: list[sel.Pick], talking: set[str] | None = None) -> list[sel.Pick]:
    """The three-shot order for one scene: wide, then medium, then close,
    each class in filming order; look-alikes kept apart; the scene ends on
    a close shot or a face when it has one; talk to the lens never runs into
    more talk while there is b-roll to cut away to (cutaways)."""
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
    return cutaways(out, talking)


def _talks(p: sel.Pick, talking: set[str] | None) -> bool:
    return bool(talking) and p.shot.id in talking


def cutaways(order: list[sel.Pick], talking: set[str] | None) -> list[sel.Pick]:
    """Talk broken up by b-roll: the good vlogs hold someone talking to the
    lens, then cut away (house.py; "the longest talk with no cutaway" is one
    of the taste model's strongest signals). Two talking shots side by side
    get the nearest b-roll moved between them; the talk keeps its order, and
    the b-roll its own. Nothing moves when the scene is all talk or none."""
    if not talking or len(order) < 3:
        return list(order)
    talk = [p for p in order if _talks(p, talking)]
    roll = [p for p in order if not _talks(p, talking)]
    if not talk or not roll:
        return list(order)
    if all(not (_talks(a, talking) and _talks(b, talking)) for a, b in zip(order, order[1:])):
        return list(order)
    # open the way the scene opened (on b-roll when it did), then alternate
    # talk with as much b-roll as there is, the rest of the b-roll after
    out: list[sel.Pick] = []
    lead = not _talks(order[0], talking)
    gaps = len(talk) - 1 + (1 if lead else 0)
    share = [len(roll) // max(gaps, 1) + (1 if k < len(roll) % max(gaps, 1) else 0) for k in range(max(gaps, 1))]
    r = iter(roll)
    k = 0
    if lead:
        out.extend(next(r) for _ in range(share[k]))
        k += 1
    for i, t in enumerate(talk):
        out.append(t)
        if i < len(talk) - 1:
            out.extend(next(r) for _ in range(share[k] if k < len(share) else 0))
            k += 1
    out.extend(r)
    return out


def scenes(plan: sel.Plan, talking: set[str] | None = None) -> None:
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
    stops = [sequence(sorted(g, key=lambda p: p.shot.order), talking) for _, g in sorted(groups.items())]
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
    if a < STILL:
        return STILL_HOLD
    # between rest and a walk the hold shortens with the movement, so a
    # shoot's lengths spread like the good vlogs' instead of sitting on one
    return float(np.interp(a, [STILL, BUSY], [1.0, BUSY_HOLD]))


def _house(fp: dict) -> dict:
    from . import house
    return fp.get("house") or house.measured("long")


def rest_of(sess: list[sel.Pick], talking: set[str] | None) -> sel.Pick | None:
    """The scene's one long rest: its stillest b-roll shot, if any is still."""
    still = [p for p in sess if not _talks(p, talking) and float(getattr(p.shot, "activity", 99.0) or 0.0) < STILL]
    return min(still, key=lambda p: float(getattr(p.shot, "activity", 0.0) or 0.0)) if still else None


LAUGH_S = 1              # a heard second of laughter (worth.py's reading)...
LAUGH_MEAN = 0.3         # ...or this much laughter on average over the shot (the taste model's LAUGH_ON)


def laughs(p: sel.Pick, clips: dict | None) -> bool:
    """Someone laughs in this shot, as either reading hears it."""
    from . import worth
    rec = (clips or {}).get(p.shot.clip_id)
    if not rec:
        return False
    secs = worth._secs(rec, "laughter", p.shot.start, p.shot.end)
    return worth._count(rec, "laughter", p.shot.start, p.shot.end) >= LAUGH_S or (
        len(secs) > 0 and float(np.mean(secs)) >= LAUGH_MEAN)


def hold_for(p: sel.Pick, h: dict, c: float, rest: bool, talking: set[str] | None, laugh: bool = False) -> float:
    """One shot's hold, the way the good vlogs hold that kind of shot
    (house.py): talk to the lens its sentence (at least the house's talk
    length, the whole shot as filmed up to their held shots), a laugh the
    same (the taste model: good vlogs hold a laugh 1.5x, ours cut it to
    0.4x), a scene's still rest REST b-roll lengths, other b-roll the
    house's b-roll length by its stillness (a walk about a second). `c` is
    the arc's curve here."""
    if _talks(p, talking) or laugh:
        whole = float(p.shot.end - p.shot.start)
        return float(np.clip(max(whole, h["talk_s"]), MIN_HOLD_S, min(MAX_HOLD_S, h["held_s"])))
    base = h["broll_s"] * c
    want = base * REST if rest else base * stillness(p.shot)
    return float(np.clip(want, MIN_HOLD_S, MAX_HOLD_S))


def breathe(plan: sel.Plan, clips: dict, fp: dict, talking: set[str] | None = None) -> dict:
    """Give every pick a hold by what it is (hold_for), with the arc's curve
    for where it sits; cut in where the action is (select.window). The pace
    word moves every hold with the house median. Returns a small report."""
    seq = [p for sess in plan.sessions for p in sess]
    n = max(len(seq), 1)
    h = dict(_house(fp))
    scale = float(fp.get("median_s") or h["shot_s"]) / float(h["shot_s"] or 1.0)
    h["broll_s"] = h["broll_s"] * scale
    curve = fp.get("curve") or [1.0] * 5
    rests = {id(r) for r in (rest_of(sess, talking) for sess in plan.sessions) if r is not None}
    held, short, talk = 0, 0, 0
    k = 0
    for sess in plan.sessions:
        for p in sess:
            pos = (k + 0.5) / n
            c = float(np.interp(pos * (len(curve) - 1), range(len(curve)), curve))
            want = hold_for(p, h, c, id(p) in rests, talking, laughs(p, clips))
            p.start, p.end, p.short = sel.window(clips, p.shot, want)
            held += id(p) in rests
            talk += _talks(p, talking)
            short += p.short
            k += 1
    return {"shots": len(seq), "rests": held, "talk": talk, "filmed_too_short": short,
            "broll_s": round(h["broll_s"], 2)}


def fill(plan: sel.Plan, clips: dict, target: float, talking: set[str] | None = None) -> float:
    """A thin shoot: every moment is already in and the vlog still runs
    short of the length the setup promised (2026-10-25: "about 50 seconds"
    became 29). Hold the b-roll longer, up to FILL_MAX_S each and never
    past what was filmed, the stillest first -- a held still shot rests, a
    held walk drags. Talk keeps its sentence. Returns the seconds added."""
    short = target - plan.duration
    if short <= 0.05:
        return 0.0
    added = 0.0
    seq = [p for sess in plan.sessions for p in sess if not _talks(p, talking)]
    for p in sorted(seq, key=lambda p: float(getattr(p.shot, "activity", 0.0) or 0.0)):
        room = min(FILL_MAX_S, float(p.shot.end - p.shot.start)) - p.duration
        if room <= 0.05:
            continue
        give = min(room, short - added)
        before = p.duration
        p.start, p.end, p.short = sel.window(clips, p.shot, before + give)
        added += p.duration - before
        if added >= short - 0.05:
            break
    return round(added, 3)


def reach(shots: list, vision: bool = True) -> float:
    """How long a vlog Make can run on this footage: every shot it can pick
    (filmed at least MIN_PICK_S, look-alikes once), each held at most
    FILL_MAX_S. The setup promises no more than this (brief.length_for)."""
    kept: list = []
    for s in sorted(shots, key=lambda s: s.score, reverse=True):
        if s.end - s.start < MIN_PICK_S or (vision and any(brief.alike(s, k) for k in kept)):
            continue
        kept.append(s)
    return float(sum(min(FILL_MAX_S, s.end - s.start) for s in kept))


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


TALK_RUN_PEN = 2.0       # two talking shots side by side when b-roll could sit between them


def flow(plan: sel.Plan, clips: dict, talking: set[str] | None = None) -> int:
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
            moved += _flow_stop(sess, scene, k, flat, clips, plan, talking)
    plan.sessions = [[p for st in scene for p in st] for scene in stops]
    return moved


def _flow_stop(sess: list[sel.Pick], scene: list[list[sel.Pick]], k: int, flat: list[sel.Pick], clips: dict, plan: sel.Plan,
               talking: set[str] | None = None) -> int:
    import itertools
    sides = {p.shot.id: _side(p, clips) for p in sess}
    if not any(sides.values()):
        return 0
    rank = {"wide": 0, "medium": 1, "close": 2}
    tiers = [[p for p in sess if rank[shot_size(p.shot)] == t] for t in range(3)]
    can_close = any(_closes(p) for p in sess)
    can_cut_away = any(_talks(p, talking) for p in sess) and any(not _talks(p, talking) for p in sess)
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
                if can_cut_away and _talks(x, talking) and _talks(y, talking):
                    c += TALK_RUN_PEN
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


def phrase(plan: sel.Plan, clips: dict, period: float, fp: dict | None = None,
           talking: set[str] | None = None) -> dict:
    """The hook ends on a whole beat (so the drop lands), and every scene
    runs a whole number of phrases: its b-roll stretches or shrinks together,
    within the hold clamp, and what's left goes to the closing shot. Talk to
    the lens keeps its sentence. Shots inside a scene fall where the action
    ends, not on a beat."""
    # a teaser's glimpses (make.teaser): each a whole number of beats, quick, inside the seconds it was
    # given -- so the drop, at the teaser's end, lands on a beat
    for p in plan.teaser:
        beats = max(1, int(round(p.duration / period)))
        lo, hi = p.room or (p.shot.start, p.shot.end)
        want = min(beats * period, hi - lo)
        p.start = round(max(lo, min(p.start, hi - want)), 3)
        p.end = round(p.start + want, 3)
    for p in plan.hook:
        beats = max(2, int(round(p.duration / period)))
        p.start, p.end, p.short = sel.window(clips, p.shot, beats * period)
    report = {"scenes": 0, "on_phrase": 0}
    # a scene rounds up to its next phrase while the video is short of its length, so
    # the beat fit doesn't take back what was promised (50 s asked, 32 cut, 29 after the fit)
    short = float((fp or {}).get("duration") or 0.0) - plan.duration
    for sess in plan.sessions:
        if not sess:
            continue
        report["scenes"] += 1
        total = sum(p.duration for p in sess)
        unit = (PHRASE_BEATS if total >= 0.75 * PHRASE_BEATS * period else HALF_PHRASE) * period
        n = total / unit
        want_total = max(unit, (math.ceil(n - 0.05) if short > 0.25 * unit else round(n)) * unit)
        rest = rest_of(sess, talking)
        keep = lambda p: _talks(p, talking) or p is rest or laughs(p, clips)  # noqa: E731 -- held as held
        fixed = sum(p.duration for p in sess if keep(p))
        factor = (want_total - fixed) / (total - fixed) if total - fixed > 0 else 1.0
        for p in sess:
            if keep(p):
                continue
            want = float(np.clip(p.duration * factor, MIN_HOLD_S, MAX_HOLD_S))
            p.start, p.end, p.short = sel.window(clips, p.shot, want)
        left = want_total - sum(p.duration for p in sess)
        # the closing shot takes up the slack where it has footage (it rests on the detail)
        for p in reversed(sess):
            if abs(left) < 1e-3:
                break
            if _talks(p, talking):
                continue
            room = (p.shot.end - p.end) if left > 0 else (p.end - p.start - MIN_HOLD_S)
            give = min(left, room) if left > 0 else max(left, -room)
            if give > 1e-3 or give < -1e-3:
                p.end = round(p.end + give, 3)
                left -= give
        if abs(sum(p.duration for p in sess) - want_total) < 0.05:
            report["on_phrase"] += 1
        short -= sum(p.duration for p in sess) - total
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
    t = sum(p.duration for p in plan.teaser) + sum(p.duration for p in plan.hook)
    for sess in plan.sessions:
        if not sess:
            continue
        a, b = t + SWELL_S, t + sum(p.duration for p in sess) - SWELL_S
        if b - a >= 1.0:
            out.append([round(a, 3), round(b, 3), SETTLE])
        t += sum(p.duration for p in sess)
    return out


TALK_OUT = 0.05          # music while someone talks to the lens: out, as in the good vlogs (house.py:
                         # a median 2% of their talking time has music under it) [prior]
TALK_EASE_S = 0.4        # it leaves just before the first word and comes back just after the last


def talk_out(board: dict, talking: set[str] | None) -> list[list[float]]:
    """Duck entries in edit seconds: the music steps out under every talking
    stretch (bed.ducks' stretches, at TALK_OUT, eased in and out)."""
    from . import bed
    out = []
    for a, b, _g in bed.ducks(board, talking or set()):
        out.append([round(max(0.0, a - TALK_EASE_S), 3), round(b + TALK_EASE_S, 3), TALK_OUT])
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
