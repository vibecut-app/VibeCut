"""The beat sheet: the video's spine, planned before a single cut.

Why this exists (sarah, 2026-11-10: "our project right now doesnt
understand how to develop films like a filmmaker, it just takes the final
taste and turn it into a mashed video"). She was right about the default
path. With the AI off, Make scored each moment on its own worth, kept the
best in the order of the day and grouped them by place; nothing decided
what the video was, what each part of it was for, or what a moment was
there to do. The taste model only chose between small one-change versions
at the end. The AI story editor (story.py) plans chapters, but only with
the AI switched on and paid for.

A filmmaker starts from the spine. The pros' vlogs in taste/ (87 vlogs by
33 creators, every shot given its job by the AI editor when they were read,
taste/editor.py) say what that spine is, and `measured` reads it from those
files (nothing is downloaded; FALLBACK is the 2026-11-10 reading):

1. **A reason to watch** first, about 6% of the video (make.teaser, the hook).
2. **Chapters**, each a little story of 7-11 shots: it opens on a setup --
   where we are, arriving (70-79% of the pros' chapters) -- runs its steps,
   and when it has a payoff (half do) that sits in its last two shots.
3. **A peak**: one chapter runs 1.7-1.9x a typical one; the first is about
   typical; the last is shorter (0.86x), the wind-down.
4. **A sign-off**: the video ends on an outro (half of the pros' shorts,
   nearly always someone talking to the lens) or on the payoff held (four
   in ten).

What a moment *is* can't name its job: a reader of the phone's own
readings (faces, voice, laughter, motion, labels) trained on the pros'
shots names a creator's setups and payoffs barely better than guessing on
one it never saw (52% against 39%; setups 11%, payoffs 0%); only talk is
plain. A job comes from where a moment sits in its chapter. So the sheet
decides the slots first -- how many chapters, how long each, which is the
peak -- and then fills each slot with the moment that fits it best: the
arrival that looks most like a place for the setup, the chapter's strongest
moment for its payoff, the best of the rest for the steps, someone talking
to the lens late in the day for the sign-off.

Whose spine: the shorts'. VibeCut's vlogs run one to three minutes, the
length of the pros' shorts, which were also read whole; the long vlogs run
5-30 minutes with chapters of about 50 s, two to a VibeCut vlog. Both agree
on the story inside a chapter (the numbers above). The holds stay the long
vlogs' (house.py).

The vlog grammar still does the rest (vlog.py): holds by what each shot is,
talk broken up by cutaways, music in phrases. The day's order holds between
chapters. Inside one, the steps between the setup and the payoff run wide ->
medium -> close and are then ordered for the smoothest cuts (vlog.sequence,
vlog.flow): the first try kept them in filming order, and on the test day
the taste model read that as jumping about (continuity, one of its
strongest signals, dropped from about the good vlogs' level to below a
random order). The setup and the payoff never move. Off with
VIBECUT_BEATS=0 (the scene grammar of 2026-10-24 then cuts as before).
Every constant marked [prior] is a guess; the rest come from the pros.
"""

from __future__ import annotations

import csv
import functools
import json
import os
from pathlib import Path

import numpy as np

from . import brief, select as sel, storyboard as sb, vlog

ROOT = Path(__file__).resolve().parents[2] / "taste"
GROUP = {"short": "short", "tall": "long", "wide": "long"}

# the 2026-11-10 reading of taste/descriptions, rounded; used only when the
# files aren't there (a checkout without the data)
FALLBACK = {
    "long": {"chapter_shots": 11.0, "peak": 1.7, "first": 1.05, "last": 0.86, "mid_lo": 0.8, "mid_hi": 1.44,
             "opens_setup": 0.7, "payoff_in": 0.46, "payoff_last2": 0.46, "payoff_hold": 1.3, "hook_share": 0.06,
             "ends_signoff": 0.49, "ends_payoff": 0.41, "videos": 0, "creators": 0},
    "short": {"chapter_shots": 7.5, "peak": 1.93, "first": 1.0, "last": 0.86, "mid_lo": 0.83, "mid_hi": 1.39,
              "opens_setup": 0.79, "payoff_in": 0.51, "payoff_last2": 0.68, "payoff_hold": 1.08, "hook_share": 0.06,
              "ends_signoff": 0.49, "ends_payoff": 0.41, "videos": 0, "creators": 0},
}
OPENS = ("setup", "transit", "title")      # a chapter's first shot that says where we are
ENDS = ("payoff", "signoff")               # what a chapter ends on: these never move

MAX_CHAPTERS = vlog.MAX_SCENES
MIN_STORY = 3            # a chapter with fewer moments than this can't be a setup, a step and a payoff:
                         # it joins the stop filmed nearest to it [prior]
SETUP_LOOK = 3           # the setup is one of a chapter's first this-many moments: the arrival [prior]
SETUP_WIDE = 0.15        # ...the one that looks most like a place: wide, the first look at a new place [prior]
SETUP_NEW = 0.1
PAYOFF_LATE = 0.05       # ties go to the moment filmed later in the chapter: the food arrives, then it's eaten [prior]
SIGNOFF_TAIL = 1 / 3     # a sign-off is someone talking to the lens in the last third of the last chapter [prior]
PEAK_HOOK = 0.1          # the reason to watch comes from the peak chapter when it has a moment to spare [prior]
HOOK_LIKE = 0.3          # the hook must differ from every pick this much (select.choose's own line)


def enabled() -> bool:
    return os.environ.get("VIBECUT_BEATS", "1") != "0"


# --------------------------------------------------------------------------
# what the pros' vlogs say the spine is
# --------------------------------------------------------------------------

def _vlog_ids() -> set[str] | None:
    """The rows of the set that are vlogs (taste/data/*.csv): the readings of
    the ones judged "not a vlog" are kept on file but never learnt from."""
    keep, seen = set(), False
    for name in ("long-youtube.csv", "short-reels.csv"):
        try:
            with open(ROOT / "data" / name, newline="") as f:
                for r in csv.DictReader(f):
                    seen = True
                    if r.get("status") != "not a vlog":
                        keep.add(r["id"])
        except OSError:
            continue
    return keep if seen else None


def _descriptions(group: str) -> list[dict]:
    vlogs = _vlog_ids()
    out = []
    folder = ROOT / "descriptions"
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("group") != group or d.get("source") != "reference" or (vlogs is not None and d.get("id") not in vlogs):
            continue
        if not ((d.get("editor") or {}).get("chapters")) or not d.get("shots"):
            continue
        out.append(d)
    return out


def _chapters(d: dict) -> list[list[dict]]:
    sh = d["shots"]
    n = len(sh)
    return [sh[c["first"] - 1:c["last"]] for c in d["editor"]["chapters"]
            if isinstance(c.get("first"), int) and isinstance(c.get("last"), int) and 1 <= c["first"] <= c["last"] <= n]


def _creator_of() -> dict[str, str]:
    out = {}
    for name in ("long-youtube.csv", "short-reels.csv"):
        try:
            with open(ROOT / "data" / name, newline="") as f:
                out.update({r["id"]: r.get("creator") or r["id"] for r in csv.DictReader(f)})
        except OSError:
            continue
    return out


@functools.lru_cache(maxsize=4)
def measured(group: str) -> dict:
    """The spine as the pros' vlogs of `group` ('long' or 'short') run it.
    Long vlogs were read for their first five minutes, so their endings and
    last chapters say nothing: those come from the shorts, which were read
    whole. Falls back per number when there are under 3 to go on."""
    out = dict(FALLBACK[group])
    descs = _descriptions(group)
    whole = [d for g in ("short", "long") for d in _descriptions(g) if not d.get("cutoff")]
    spc, peak, first, last, mid, opens, has_pay, pay_last2, hook = [], [], [], [], [], [], [], [], []
    held: list[float] = []
    for d in descs:
        segs = _chapters(d)
        if not segs:
            continue
        med_shot = float(np.median([float(s["d"]) for s in d["shots"]]))
        spc += [len(s) for s in segs]
        lens = [sum(float(x["d"]) for x in s) for s in segs]
        if len(lens) >= 3:
            m = float(np.median(lens))
            peak.append(max(lens) / m)
            first.append(lens[0] / m)
            mid += [x / m for x in lens[1:-1]]
        for s in segs:
            roles = [x.get("role") for x in s]
            opens.append(roles[0] in OPENS)
            has_pay.append("payoff" in roles)
            if "payoff" in roles:
                pay_last2.append("payoff" in roles[-2:])
        held += [float(x["d"]) / med_shot for x in d["shots"] if x.get("role") == "payoff" and med_shot > 0]
        hk = (d["editor"].get("hook") or {}).get("shots") or []
        dur = float(d.get("duration") or 0.0)
        if dur > 0:
            hook.append(sum(float(d["shots"][i - 1]["d"]) for i in hk if isinstance(i, int) and 1 <= i <= len(d["shots"])) / dur)
    for d in whole:
        segs = _chapters(d)
        lens = [sum(float(x["d"]) for x in s) for s in segs]
        if len(lens) >= 3:
            last.append(lens[-1] / float(np.median(lens)))
    ends = [d["shots"][-1].get("role") for d in whole]
    for key, xs in (("chapter_shots", spc), ("peak", peak), ("first", first), ("last", last),
                    ("payoff_hold", held), ("hook_share", hook)):
        if len(xs) >= 3:
            out[key] = round(float(np.median(xs)), 3)
    if len(mid) >= 3:
        out["mid_lo"], out["mid_hi"] = (round(float(x), 3) for x in np.percentile(mid, [25, 75]))
    for key, xs in (("opens_setup", opens), ("payoff_in", has_pay), ("payoff_last2", pay_last2)):
        if len(xs) >= 3:
            out[key] = round(float(np.mean(xs)), 3)
    if len(ends) >= 3:
        out["ends_signoff"] = round(sum(e == "outro" for e in ends) / len(ends), 3)
        out["ends_payoff"] = round(sum(e == "payoff" for e in ends) / len(ends), 3)
    who = _creator_of()
    out["videos"], out["creators"] = len(descs), len({who.get(d["id"], d["id"]) for d in descs})
    return out


# --------------------------------------------------------------------------
# the spine: chapters, their share of the time, the peak
# --------------------------------------------------------------------------

def _gap(a: list[sb.Shot], b: list[sb.Shot]) -> float:
    """Minutes between the end of one stop and the start of the next; two
    with no clock between them join by size alone (after any with one)."""
    x, y = a[-1].when, b[0].when
    if x is not None and y is not None:
        return abs((y - x).total_seconds()) / 60.0
    return 1e6 + len(a) + len(b)


def chapters_of(pool: list[sb.Shot], want: int) -> list[list[sb.Shot]]:
    """The stops of the day (brief.spots: a place, twenty minutes), joined
    into at most `want` chapters in the day's order: first any stop too
    thin to tell a story joins the neighbour filmed nearest to it, then the
    two neighbours filmed closest together, until there are few enough --
    a walk and the café it led to are one chapter, lunch and the evening
    aren't."""
    where = brief.spots(pool)
    groups: dict[int, list[sb.Shot]] = {}
    for s in pool:
        groups.setdefault(where.get(s.id, 0), []).append(s)
    chs = [sorted(g, key=lambda s: s.order) for _, g in sorted(groups.items())]
    chs = [c for c in chs if c]
    while len(chs) > 1:
        thin = [i for i, c in enumerate(chs) if len(c) < MIN_STORY]
        if thin:
            i = min(thin, key=lambda i: len(chs[i]))
            left = _gap(chs[i - 1], chs[i]) if i > 0 else float("inf")
            right = _gap(chs[i], chs[i + 1]) if i < len(chs) - 1 else float("inf")
            j = i - 1 if left <= right else i
        elif len(chs) > want:
            j = min(range(len(chs) - 1), key=lambda k: (_gap(chs[k], chs[k + 1]), len(chs[k]) + len(chs[k + 1])))
        else:
            break
        chs[j:j + 2] = [chs[j] + chs[j + 1]]
    return chs


def _worth(s: sb.Shot, val: dict[str, float]) -> float:
    return float(s.worth) if s.worth is not None else val[s.id]


def shares(chs: list[list[sb.Shot]], val: dict[str, float], sheet: dict) -> tuple[list[float], int]:
    """Each chapter's weight in the time, and which is the peak: the one
    whose best moment is strongest runs `peak` times a typical chapter, the
    first `first`, the last `last` (the wind-down), the others inside the
    pros' middle half by how strong their best moment is."""
    n = len(chs)
    if n == 1:
        return [1.0], 0
    imp = [max(_worth(s, val) for s in c) for c in chs]
    peak = int(np.argmax(imp))
    others = sorted((i for i in range(n) if i != peak), key=lambda i: imp[i])
    rank = {i: (k / (len(others) - 1) if len(others) > 1 else 0.5) for k, i in enumerate(others)}
    w = []
    for i in range(n):
        if i == peak:
            w.append(sheet["peak"])
        elif i == n - 1:
            w.append(sheet["last"])
        elif i == 0:
            w.append(sheet["first"])
        else:
            w.append(sheet["mid_lo"] + (sheet["mid_hi"] - sheet["mid_lo"]) * rank[i])
    return w, peak


def seats(chs: list[list[sb.Shot]], weights: list[float], n: int) -> list[int]:
    """How many moments each chapter gets: n in proportion to its weight,
    at least enough to tell its story (MIN_STORY, or all it has), never more
    than it has; what a chapter can't take goes to the others by weight."""
    have = [len(c) for c in chs]
    w = np.asarray(weights, dtype=float)
    raw = n * w / w.sum()
    k = np.minimum(np.maximum(np.floor(raw), np.minimum(MIN_STORY, have)), have).astype(int)
    left = n - int(k.sum())
    order = sorted(range(len(chs)), key=lambda i: (-(raw[i] - np.floor(raw[i])), -w[i]))
    while left > 0:
        grew = False
        for i in order:
            if left <= 0:
                break
            if k[i] < have[i]:
                k[i] += 1
                left -= 1
                grew = True
        if not grew:
            break
    return [int(x) for x in k]


# --------------------------------------------------------------------------
# filling the slots
# --------------------------------------------------------------------------

def _talks(s: sb.Shot, talking: set[str]) -> bool:
    return s.id in talking


def _cap(s: sb.Shot, clips: dict) -> int:
    return 2 if (clips.get(s.clip_id) or {}).get("duration", 0) >= sel.LONG_CLIP_S else sel.CLIP_CAP


def _fits(s: sb.Shot, taken: list[sb.Shot], clips: dict) -> bool:
    """Room for one more from this clip, and not the same view again within
    a session (select.choose's rule: the same street at noon and at night
    are two moments, three takes of one cup are one)."""
    if sum(t.clip_id == s.clip_id for t in taken) >= _cap(s, clips):
        return False
    near = [t for t in taken if t.when is None or s.when is None or abs(t.when - s.when) <= sb.SESSION_GAP]
    return sel._novel(s, near) >= sel.NOVELTY_MIN


def setup_of(cands: list[sb.Shot], val: dict[str, float]) -> sb.Shot:
    """The chapter's setup: of its first SETUP_LOOK moments (the arrival),
    the one that best says where we are -- a wide look, the first look at a
    new place -- on top of how good it is."""
    def fit(s: sb.Shot) -> float:
        return (val[s.id] + SETUP_WIDE * (vlog.shot_size(s) == "wide")
                + SETUP_NEW * any("new place" in w for w in (s.worth_why or [])))
    return max(cands[:SETUP_LOOK], key=fit)


def payoff_of(cands: list[sb.Shot], val: dict[str, float], talking: set[str]) -> sb.Shot | None:
    """The chapter's payoff: its strongest moment (worth.py: craft plus
    feeling -- a laugh, a first look at a place), the later one on a tie.
    Talk to the lens is talk, not a payoff, unless there is nothing else."""
    quiet = [s for s in cands if not _talks(s, talking)] or list(cands)
    if not quiet:
        return None
    n = max(len(cands) - 1, 1)
    pos = {s.id: i / n for i, s in enumerate(cands)}
    return max(quiet, key=lambda s: _worth(s, val) + PAYOFF_LATE * pos[s.id])


def signoff_of(cands: list[sb.Shot], talking: set[str]) -> sb.Shot | None:
    """Someone talking to the lens late in the day: the pros' outro."""
    tail = cands[int(len(cands) * (1 - SIGNOFF_TAIL)):]
    late = [s for s in tail if _talks(s, talking)]
    return late[-1] if late else None


def job_of(s: sb.Shot, talking: set[str]) -> str:
    if _talks(s, talking):
        return "talk"
    if vlog.shot_size(s) == "close" and not (s.faces or 0):
        return "detail"
    return "step"


def fill(cands: list[sb.Shot], k: int, val: dict[str, float], clips: dict, talking: set[str],
         last: bool = False) -> list[tuple[sb.Shot, str]]:
    """One chapter, as a little story of k moments: the setup, the steps
    (wide -> medium -> close, look-alikes apart, talk broken up by
    cutaways: vlog.sequence), the payoff; the last chapter ends on its
    sign-off when it has one. -> [(shot, job)]."""
    if k <= 0 or not cands:
        return []
    if k == 1:
        p = payoff_of(cands, val, talking)
        return [(p, "payoff")] if p is not None else []
    setup = setup_of(cands, val)
    taken = [setup]
    sign = signoff_of(cands, talking) if last and k >= 3 else None
    if sign is setup:
        sign = None
    if sign is not None:
        taken.append(sign)
    rest = [s for s in cands if s not in taken]
    pay = payoff_of(rest, val, talking) if rest else None
    if pay is not None and not _fits(pay, taken, clips):
        pay = next((s for s in sorted(rest, key=lambda s: -_worth(s, val))
                    if not _talks(s, talking) and _fits(s, taken, clips)), pay)
    if pay is not None:
        taken.append(pay)
    steps: list[sb.Shot] = []
    for s in sorted((s for s in cands if s not in taken), key=lambda s: -val[s.id]):
        if len(taken) + len(steps) >= k:
            break
        if val[s.id] < sel.SCORE_FLOOR and steps:
            break          # the rest of the chapter is weaker than the floor: it runs short instead
        if _fits(s, taken + steps, clips):
            steps.append(s)
    # a detail when the steps have none and the chapter has one good enough (the
    # pros' chapters show the plate, the cup, the hands in two of three)
    if len(steps) >= 2 and not any(job_of(s, talking) == "detail" for s in steps):
        det = [s for s in cands if s not in taken and s not in steps and job_of(s, talking) == "detail"
               and val[s.id] >= sel.SCORE_FLOOR and _fits(s, taken + steps[:-1], clips)]
        if det:
            weakest = min(steps, key=lambda s: val[s.id])
            steps[steps.index(weakest)] = max(det, key=lambda s: val[s.id])
    steps.sort(key=lambda s: s.order)
    if setup in steps:
        steps.remove(setup)
    middle = vlog.sequence([sel.Pick(s, "", 0.0, 0.0, val[s.id], "", 0) for s in steps], talking)
    out = [(setup, "setup")] + [(p.shot, job_of(p.shot, talking)) for p in middle]
    if pay is not None:
        out.append((pay, "payoff"))
    if sign is not None:
        out.append((sign, "signoff"))
    return out


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------

def plan(clips: dict[str, dict], cut, fp: dict, talking: set[str] | None = None, bias: dict | None = None,
         length: float | None = None, min_s: float = vlog.MIN_PICK_S, group: str = "short") -> sel.Plan:
    """The vlog, planned from its spine: chapters, their time and their peak
    decided first, each chapter's slots filled with the moments that fit
    them, a reason to watch held back to open it. Windows are a first guess
    (the median shot): vlog.breathe holds each pick by what it is. Rules
    only: Claude's judge (select.judge) re-picks the old sessions, not
    these chapters, so it isn't asked here."""
    talking = set(talking or ())
    if cut is None:                       # no rough cut handed in: make one, as remix.plan_shots does
        from .cut import compute as rough_cut, for_story
        cut = for_story(rough_cut(clips, None))
    rejected, windows = cut
    shots = sb.shots_from_clips(list(clips.values()), (rejected, windows))
    shots, notes = sb.usable(shots)
    pool, dropped = sel.dedupe([s for s in shots if not s.utility and s.duration >= max(min_s, sel.MIN_SHOT_S)])
    if not pool:
        return sel.Plan(hook=[], sessions=[], titles=[], notes=notes)
    weights = sel.idf(pool)
    scored = {s.id: sel.hero_score(s, clips, weights, bias) for s in pool}
    val = {k: v[0] for k, v in scored.items()}
    median = float(np.median(list(val.values())))
    sheet = measured(group)
    total = float(length or fp["duration"])
    n_body = max(4, int(round(max(1.0, total - fp["hook_s"]) / fp["median_s"])))
    want = int(np.clip(round(n_body / sheet["chapter_shots"]), 1, MAX_CHAPTERS))
    chs = chapters_of(pool, want)
    w, peak = shares(chs, val, sheet)
    k = seats(chs, w, n_body)

    def mk(s: sb.Shot, job: str, i: int) -> sel.Pick:
        sc, parts = scored[s.id]
        why = ", ".join(f"{a} {b:.2f}" for a, b in sorted(parts.items(), key=lambda kv: -sel.W.get(kv[0], 1.0) * kv[1])[:3])
        a, b, short = sel.window(clips, s, fp["median_s"])
        return sel.Pick(s, "hero" if sc >= median else "filler", a, b, sc, f"{job}: {why}", i, short, job=job)

    sessions = [[mk(s, job, i) for s, job in fill(c, n, val, clips, talking, last=(i == len(chs) - 1))]
                for i, (c, n) in enumerate(zip(chs, k))]
    sessions = [s for s in sessions if s]
    for i, sess in enumerate(sessions):
        for p in sess:
            p.session = i
    # the reason to watch: the punchiest moment left over, from the peak by
    # preference -- held back, so the chapters keep their setup and payoff
    picked = [p.shot for sess in sessions for p in sess]
    used = {s.id for s in picked}
    peak_ids = {s.id for s in chs[peak]} if chs else set()

    def punch(s: sb.Shot) -> float:
        return (val[s.id] + sel.HOOK_W["distinct"] * scored[s.id][1]["distinct"]
                + sel.HOOK_W["contrast"] * sel.contrast(clips, s) + sel.HOOK_W["late"] * sel._late(s, pool)
                + PEAK_HOOK * (s.id in peak_ids))
    spare = [s for s in pool if s.id not in used and not _talks(s, talking) and sel._novel(s, picked) >= HOOK_LIKE]
    hook: list[sel.Pick] = []
    if spare:
        h = max(spare, key=punch)
        a, b, short = sel.window(clips, h, fp["hook_s"])
        hook = [sel.Pick(h, "hook", a, b, val[h.id], "the reason to watch", 0, short, job="hook")]
    else:
        # nothing to spare: the peak's strongest step opens the video and leaves its chapter
        si = next((i for i, sess in enumerate(sessions) if any(p.shot.id in peak_ids for p in sess)), None)
        steps = [p for p in sessions[si] if p.job in ("step", "detail")] if si is not None else []
        if steps:
            h = max(steps, key=lambda p: punch(p.shot))
            sessions[si].remove(h)
            a, b, short = sel.window(clips, h.shot, fp["hook_s"])
            hook = [sel.Pick(h.shot, "hook", a, b, h.score, "the reason to watch", 0, short, job="hook")]
    out = sel.Plan(hook=hook, sessions=sessions, titles=vlog.titles(sessions), notes=list(notes), dropped_dup=dropped)
    # vlog.flow reorders inside a stop and never across: the setup and the
    # chapter's ending are stops of their own, so only the steps move
    out.stops = [[part for part in (sess[:1], [p for p in sess[1:] if p.job not in ENDS],
                                    [p for p in sess[1:] if p.job in ENDS]) if part] for sess in sessions]
    peak_at = next((i for i, sess in enumerate(sessions) if any(p.shot.id in peak_ids for p in sess)), None)
    out.sheet = {"chapters": len(sessions), "peak": peak_at, "seats": k, "weights": [round(x, 2) for x in w],
                 "signoff": any(p.job == "signoff" for sess in sessions for p in sess),
                 "learnt_from": {"videos": sheet["videos"], "creators": sheet["creators"]}}
    if dropped:
        out.notes.append(f"Left out {dropped} near-repeat shot{'s' * (dropped != 1)}.")
    out.notes.append(describe(out))
    return out


def describe(plan: sel.Plan) -> str:
    """One line on the spine, for the plan's notes and the reply."""
    sh = getattr(plan, "sheet", None) or {}
    if not plan.sessions:
        return "No chapters: nothing to tell yet."
    names = list(plan.titles)
    peak = sh.get("peak")
    bits = [f"{n}{' (the peak)' if i == peak else ''}" for i, n in enumerate(names)]
    end = "a sign-off" if sh.get("signoff") else "its strongest moment"
    return (f"Planned as {len(plan.sessions)} chapter{'s' * (len(plan.sessions) != 1)} before cutting: "
            f"{', '.join(bits)}; each opens on where you are and ends on its best moment, and the video ends on {end}.")


def say(plan: sel.Plan) -> str:
    """The reply's sentence, or nothing when the sheet didn't plan this video."""
    return describe(plan) if getattr(plan, "sheet", None) else ""


if __name__ == "__main__":       # python -m web.backend.beats: the spine as the pros run it
    for g in ("long", "short"):
        print(g, json.dumps(measured(g)))
