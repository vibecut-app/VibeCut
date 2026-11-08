"""Make picks with the taste model: a few cuts of the same moments, the one
that reads most like the good vlogs kept.

Why this exists (2026-10-21, sarah: the taste model should be "the essence
of our algo"): the rules make one edit and every choice in it is a prior --
the fixed shot-length spread, the stop's order, which moment opens it, how
long the opening and the ending hold. An editor tries a
few of those and keeps the one that plays best. Here the taste model
(taste/model.py, learnt from real vlogs) is the one who watches: each
variant is one small change an editor might try, built as the same ops Make
lands, read without rendering (taste.describe.from_board) and scored.
Today's edit is always variant 0, so the model can keep it, and it only
gives way to a variant that beats it by MIN_GAIN. A winner then has each
other part of the video (PARTS) tried on top of it, one change per part, so
her own taste (the cards after Make, prefer.py, teach the model) can show
in a part whose change didn't win alone.

Nothing here is paid or decoded: the moments, the judge, the track and the
words were chosen once by Make; a variant only re-windows picks it already
has, re-fits them to the same track and drop, and reorders. Only on the
rules path: an AI-planned edit's chapters name their own picks.

The joins are not a variant (yet): "straight cuts" as a set_transition over
every join is stored as the creator's own pick (`picture_all`), which a
later set_look keeps -- a machine choice would outlive the look it was made
against. That needs a source on the pick in board / transitions first.

Off with VIBECUT_TASTE=0, off until a model is trained
(taste/model/<group>.json), and off for a group whose model can't yet tell
a real edit from a damaged one on creators it never saw (MIN_LOCO). The
first shorts model (4 creators) managed 66% and stayed off; retrained on
12 creators it managed 85% (2026-10-21), so shorts are picked too.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

from taste import describe as ds
from taste import model as tm

from . import board as bd, make, remix, select as sel, vlog

MAX_VARIANTS = 8        # today's edit plus up to 7 changes; each costs ~0.05 s to build and read [prior]
MIN_GAIN = 0.05         # a variant must beat today's edit by this much to replace it: scores are
                        # differences on the model's own scale, and a hair's breadth is noise [prior]
OPEN_HOLD = 1.6         # "hold the opening": the hook this many times as long [prior]
END_TRY = (1, 2, 3)     # ending holds tried, in beats [prior; make.END_BEATS is today's]
WIDE_FACE = 0.05        # a shot whose largest face fills less than this is a wide look at the place [prior]
MIN_LOCO = 0.75         # a model picks only if, on creators it never saw, it tells the real edit from a
                        # damaged copy this often (the report's "leave one creator out") [prior]

# the part of the video each change is in: Make keeps at most one change per
# part, and the cards after Make (prefer.py) ask about one part at a time
PART = {"held_open": "opening", "runner_up_hook": "opening", "rhythm_by_role": "rhythm",
        "strongest_last": "order", "filming_order": "order", "wide_first": "order",
        "end_1": "ending", "end_2": "ending", "end_3": "ending"}
PARTS = ("opening", "rhythm", "order", "ending")      # in the order the video plays them

# what the reply says when a variant wins: "The taste model chose <says>."
SAYS = {
    "today": "today's cut",
    "rhythm_by_role": "a rhythm that holds the strong moments and moves quickly through the rest",
    "held_open": "a longer-held opening",
    "runner_up_hook": "a different moment to open on",
    "strongest_last": "every stop ending on its strongest moment",
    "filming_order": "each stop in the order it was filmed",
    "wide_first": "each stop opening on a wide look at the place",
}

_MODELS: dict[str, tuple[tuple, tm.Model | None]] = {}


def _stamp(group: str) -> tuple:
    """When the model file and her picks last changed: a new training or a
    new pick is read on the next Make, with no restart."""
    out = []
    for p in (tm.MODEL_DIR / f"{group}.json", tm._personal_path()):
        try:
            out.append(Path(p).stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def model_for(fmt: str) -> tm.Model | None:
    """The group's model for this frame, loaded once per process (and again
    when its file or her picks change); None when nothing is trained."""
    group = ds.GROUP_OF_FORMAT.get(fmt, "long")
    stamp = _stamp(group)
    hit = _MODELS.get(group)
    if hit is None or hit[0] != stamp:
        m = tm.load(group)
        hit = (stamp, m if m is not None and trusted(m) else None)
        _MODELS[group] = hit
    return hit[1]


def trusted(m: tm.Model) -> bool:
    """Good enough to choose between cuts: its own report says it told real
    from damaged on unseen creators at least MIN_LOCO of the time."""
    loco = (m.report or {}).get("loco")
    return isinstance(loco, (int, float)) and loco >= MIN_LOCO


def enabled(fmt: str) -> bool:
    return os.environ.get("VIBECUT_TASTE", "1") != "0" and model_for(fmt) is not None


def copy_plan(plan: sel.Plan) -> sel.Plan:
    """A plan the variants may re-cut: new Picks, the same Shots (their
    embeddings are never copied). See map/make.md, mutation hazards."""
    return dataclasses.replace(plan, hook=[dataclasses.replace(p) for p in plan.hook],
                               teaser=[dataclasses.replace(p) for p in plan.teaser],
                               sessions=[[dataclasses.replace(p) for p in s] for s in plan.sessions],
                               titles=list(plan.titles), notes=list(plan.notes))


# --------------------------------------------------------------------------
# the variants: one change each, the way an editor tries a cut both ways
# --------------------------------------------------------------------------

def _ids(plan: sel.Plan) -> list[list[str]]:
    return [[p.shot.id for p in s] for s in plan.sessions]


def _strongest_last(plan: sel.Plan) -> None:
    for s in plan.sessions:
        if len(s) > 1:
            best = max(s, key=lambda p: p.score)
            s.remove(best)
            s.append(best)


def _filming_order(plan: sel.Plan) -> None:
    for s in plan.sessions:
        s.sort(key=lambda p: p.shot.order)


def _wide(p: sel.Pick) -> bool:
    return not getattr(p.shot, "faces", 0) and float(getattr(p.shot, "face_area", 0.0) or 0.0) < WIDE_FACE


def _wide_first(plan: sel.Plan) -> None:
    # the establishing shot: a stop reads as a place before it reads as people
    for s in plan.sessions:
        w = next((p for p in s if _wide(p)), None)
        if w is not None and s[0] is not w:
            s.remove(w)
            s.insert(0, w)


def _runner_up(plan: sel.Plan) -> sel.Pick | None:
    # not a shot the teaser already glimpses (make.teaser): it would play twice in a row
    hook = {p.shot.id for p in plan.hook} | {p.shot.id for p in plan.teaser}
    heroes = [p for s in plan.sessions for p in s if p.role == "hero" and p.shot.id not in hook]
    return max(heroes, key=lambda p: p.score) if heroes else None


def _swap_hook(plan: sel.Plan, clips: dict[str, dict]) -> bool:
    """Open on the strongest hero instead of the punchiest moment. The old
    hook goes back into its stop where it was filmed (make.moments lifted it
    out), the new one is lifted out of its stop: still never a shot twice."""
    new = _runner_up(plan)
    if new is None or len(plan.hook) != 1:
        return False
    old = plan.hook[0]
    home = next((i for i, s in enumerate(plan.sessions) if new in s), None)
    plan.sessions[home].remove(new)
    # the old hook's stop: the one whose filming span holds it, else the nearest
    spans = [(i, min(p.shot.order for p in s), max(p.shot.order for p in s)) for i, s in enumerate(plan.sessions) if s]
    o = old.shot.order
    i = (min(spans, key=lambda x: 0 if x[1] <= o <= x[2] else min(abs(o - x[1]), abs(o - x[2])))[0]
         if spans else home)
    want = new.duration
    hook = dataclasses.replace(new, role="hook", session=0)
    hook.start, hook.end, hook.short = sel.window(clips, hook.shot, old.duration)
    back = dataclasses.replace(old, role="hero", session=i)
    back.start, back.end, back.short = sel.window(clips, back.shot, want)
    plan.hook = [hook]
    # at its filming place among the others, which keep their order (the
    # last stop's strongest-last ending, make.end_strong, stays as it was)
    stop = plan.sessions[i]
    at = next((k for k, p in enumerate(stop) if p.shot.order > o), len(stop))
    if stop and i == len(plan.sessions) - 1 and at == len(stop):
        at -= 1          # never after the moment the video ends on
    stop.insert(at, back)
    return True


def _role_rhythm(plan: sel.Plan, clips: dict[str, dict], fp: dict) -> None:
    """Hero shots held at the top of the spread, filler at the bottom, in
    place of the fixed pattern (remix._spread): the length follows what the
    moment is worth, a quick run landing on something held."""
    lo, hi = fp.get("spread", make.SPREAD)
    body = [p for s in plan.sessions for p in s]
    for k, p in enumerate(body):
        want = fp["median_s"] * remix._curve_at(fp["curve"], (k + 0.5) / max(len(body), 1)) * (hi if p.role == "hero" else lo)
        p.start, p.end, p.short = sel.window(clips, p.shot, want)


def _hold_open(plan: sel.Plan, clips: dict[str, dict]) -> None:
    for p in plan.hook:
        p.start, p.end, p.short = sel.window(clips, p.shot, p.duration * OPEN_HOLD)


def variants(plan: sel.Plan, fp: dict, fmt: str, look: str | None = None, mx: dict | None = None) -> list[dict]:
    """Up to MAX_VARIANTS specs, today's edit first; the same plan gives the
    same list (no randomness). A spec is {"name", "says", ...its knob}; only
    changes that would change something are offered."""
    out = [{"name": "today"}]
    body = [p for s in plan.sessions for p in s]
    if len({p.role for p in body}) > 1 and not make.is_vlog(fmt, fp):
        # a vlog's holds already follow what each shot is (vlog.breathe); the
        # spread's held end there is a talking shot's, not a hero's
        out.append({"name": "rhythm_by_role"})
    if plan.hook and any(p.shot.end - p.shot.start > p.duration + 0.2 for p in plan.hook):
        out.append({"name": "held_open"})
    if len(plan.hook) == 1 and _runner_up(plan) is not None:
        out.append({"name": "runner_up_hook"})
    if mx and plan.sessions and plan.sessions[-1]:
        today = make.end_beats(fp, mx["period"])
        out.extend({"name": f"end_{k}", "end": k} for k in END_TRY if k != today)
    for name, how in (("strongest_last", _strongest_last), ("filming_order", _filming_order),
                      ("wide_first", _wide_first)):
        trial = copy_plan(plan)
        how(trial)
        if _ids(trial) != _ids(plan):
            out.append({"name": name})
    for v in out:
        v["says"] = SAYS.get(v["name"]) or f"an ending held {v.get('end')} beat{'s' * (v.get('end') != 1)}"
    return out[:MAX_VARIANTS]


def _refit(clips: dict[str, dict], plan: sel.Plan, fp: dict, mx: dict | None, end: int | None = None,
           fmt: str = "short", talking: set[str] | None = None) -> dict | None:
    """make.music without the search: the same track and drop, this plan's
    shots on its beat, the in-point moved so the drop still lands at the end
    of the hook. False when the track no longer covers the edit."""
    if not mx:
        return None
    vmx = dict(mx)
    period = vmx["period"]
    make.fit_beat(plan, clips, fp, fmt, period, talking)
    make.hold_ending(clips, plan, period, make.end_beats(fp, period))
    if end and plan.sessions and plan.sessions[-1]:
        p = plan.sessions[-1][-1]
        if p.shot.end - p.shot.start >= end * period - 1e-3:
            p.start, p.end, p.short = sel.window(clips, p.shot, end * period)
    vmx["in"] = round(max(0.0, vmx["drop"] - make.opening_s(plan, fp)), 3)
    if vmx["in"] + plan.duration > vmx["track"].duration:
        return False
    return vmx


# when several changes make one cut (the cards, prefer.py): the shots' lengths
# first, then which moment opens and how long, then each stop's order; the
# ending is the music's refit
CHANGE_ORDER = ("rhythm_by_role", "runner_up_hook", "held_open", "strongest_last", "filming_order", "wide_first")


def _change(plan: sel.Plan, name: str, clips: dict[str, dict], fp: dict) -> bool:
    """One variant's change on `plan`; False when it can't be made."""
    if name == "rhythm_by_role":
        _role_rhythm(plan, clips, fp)
    elif name == "held_open":
        _hold_open(plan, clips)
    elif name == "runner_up_hook":
        return _swap_hook(plan, clips)
    elif name == "strongest_last":
        _strongest_last(plan)
    elif name == "filming_order":
        _filming_order(plan)
    elif name == "wide_first":
        _wide_first(plan)
    return True


def build(spec: dict | list[dict], raw: sel.Plan, clips: dict[str, dict], fp: dict, mx: dict | None, fmt: str,
          look: str | None, about: str, talking: set[str], lines: list[str] | None) -> tuple | None:
    """One variant from the plan as it was before music: (plan, mx, ops), or
    None when it can't be made. A list of specs makes one cut with each of
    their changes (at most one per part of the video: prefer.KIND)."""
    specs = spec if isinstance(spec, list) else [spec]
    plan = copy_plan(raw)
    rank = {n: i for i, n in enumerate(CHANGE_ORDER)}
    for s in sorted(specs, key=lambda s: rank.get(s["name"], len(rank))):
        if not _change(plan, s["name"], clips, fp):
            return None
    vmx = _refit(clips, plan, fp, mx, next((s["end"] for s in specs if s.get("end")), None), fmt, talking)
    if vmx is False:
        return None
    ops = make.ops(plan, fp, vmx, fmt, look, about, talking, lines=lines, clips=clips)
    return plan, vmx, ops


def board_of(ops: list[dict], cat: bd.Catalog) -> dict | None:
    """The board the ops make, as Session.replay would: an op that fails is skipped."""
    b = None
    for k, op in enumerate(ops):
        try:
            b, _ = bd.apply(b, op, cat, None, new_id=lambda k=k: f"t{k}")
        except bd.OpError:
            continue
    return b


def keeps_length(plan: sel.Plan, base: sel.Plan, fp: dict, fmt: str) -> bool:
    """A vlog version may not trade away the length the setup promised
    (2026-10-25: a one-beat ending, picked by the model, took a 42 s vlog
    to 33): it stays within vlog.LENGTH_OK of it, or no shorter than
    today's edit when that one already fell short. A short is the reel's
    length, whatever its ending."""
    want = float(fp.get("duration") or 0.0)
    if fmt == "short" or not want:
        return True
    return plan.duration >= vlog.LENGTH_OK * want - 1e-3 or plan.duration >= base.duration - 0.5


def choose(clips: dict[str, dict], raw: sel.Plan, fp: dict, mx: dict | None, fmt: str, look: str | None,
           about: str, talking: set[str], lines: list[str] | None, base: tuple, cat: bd.Catalog | None = None,
           model: tm.Model | None = None) -> tuple[sel.Plan, dict | None, list[dict], dict]:
    """Score today's edit (`base` = its (plan, mx, ops), as Make built it)
    against the variants of `raw` (the plan before music re-cut it); when
    one wins, try each other part's changes on top of it, keeping one that
    gains MIN_GAIN. Returns the winner's (plan, mx, ops) and a report:
    {"picked" (the winning single change's index), "name", "chosen" (every
    change kept), "of" (cuts read), "score", "base_score", "why", "says",
    "variants" and "specs" (the singles), "elapsed"}."""
    t0 = time.time()
    model = model or model_for(fmt)
    if model is None:
        raise ValueError("no taste model for this frame")
    cat = cat or bd.Catalog.from_clips(list(clips.values()))
    track = mx["track"] if mx else None
    tried: list[tuple[dict, tuple, dict, float]] = []
    seen: list[list[dict]] = []
    for spec in variants(raw, fp, fmt, look, mx):
        made = base if spec["name"] == "today" else build(spec, raw, clips, fp, mx, fmt, look, about, talking, lines)
        if made is None or made[2] in seen:
            continue                      # couldn't be made, or came out as a cut already tried
        if spec["name"] != "today" and not keeps_length(made[0], base[0], fp, fmt):
            continue
        seen.append(made[2])
        board = board_of(made[2], cat)
        if not board:
            continue
        desc = ds.from_board(board, clips, cat, fmt, track=track)
        tried.append((spec, made, desc, model.score(desc)))
    if not tried or tried[0][0]["name"] != "today":
        raise ValueError("today's edit couldn't be read")
    base_score = tried[0][3]
    best = max(range(len(tried)), key=lambda i: (tried[i][3] - (0.0 if i == 0 else MIN_GAIN), -i))
    chosen = [tried[best][0]]
    spec, made, desc, score = tried[best]
    if best:
        # then each other part on top of the winner, in the order the video plays: an editor
        # who settled the opening still tries the ending both ways. This is how a taste she
        # showed in one part (her picks, prefer.py) can reach a video whose best change is elsewhere.
        for part in PARTS:
            if part in {PART.get(c["name"]) for c in chosen}:
                continue
            trials = []
            for s_, *_ in tried[1:]:
                if PART.get(s_["name"]) != part:
                    continue
                m_ = build(chosen + [s_], raw, clips, fp, mx, fmt, look, about, talking, lines)
                if m_ is None or m_[2] in seen or not keeps_length(m_[0], base[0], fp, fmt):
                    continue
                seen.append(m_[2])
                b_ = board_of(m_[2], cat)
                if not b_:
                    continue
                d_ = ds.from_board(b_, clips, cat, fmt, track=track)
                trials.append((s_, m_, d_, model.score(d_)))
            top = max(trials, key=lambda t: t[3], default=None)
            if top is not None and top[3] >= score + MIN_GAIN:
                chosen.append(top[0])
                _, made, desc, score = top
    why = model.explain(desc, top=3, against=tried[0][2] if best else None)
    report = {"picked": best, "name": spec["name"], "of": len(seen), "score": round(score, 3),
              "base_score": round(base_score, 3), "says": " and ".join(c["says"] for c in chosen),
              "why": [w["says"] for w in why],
              "variants": [{"name": s["name"], "score": round(sc, 3)} for s, _, _, sc in tried],
              "specs": [dict(s) for s, _, _, _ in tried], "chosen": [dict(c) for c in chosen],
              "model": {"group": model.group, "date": model.date}, "elapsed": round(time.time() - t0, 2)}
    plan, vmx, ops = made
    return plan, vmx, ops, report


def sentence(report: dict | None) -> str:
    """The reply's line when the model kept another cut than today's."""
    if not report or not report.get("picked"):
        return ""
    return f"The taste model chose {report['says']}."
