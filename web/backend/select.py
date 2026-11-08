"""Which shots make the cut, when the cut has to be short.

The three storyboards use every usable shot: a whole day in six parts. A
short-form edit can't -- a reference reel holds a shot for 0.7 s and is
over in 30, so 42 clips have to become 35 or so moments, and the choice is
the edit. What an editor does by eye is approximated here with numbers:

- **Hero over filler.** A shot earns its place by craft (sharp, exposed,
  steady), by showing the creator (a face that is neither absent nor
  filling the frame), by a subject the eye can find, and -- the one that
  matters most for "the important pictures" -- by being *distinctive*:
  labels rare across the shoot (the plate, the boba, the sunset crosswalk)
  are the moments; labels every clip shares (people, structure) are the
  walking-around in between.
- **Cover the day.** Picks are spread across the shoot's sessions in
  proportion to the square root of footage, so a three-minute study clip
  supplies a couple of seconds, not a third of the video.
- **No near-repeats.** Two shots that look alike within fifteen minutes
  are one shot; the better one stays.
- **Cut on the action.** A shot's window starts just before its busiest
  second (subject + motion), so the cut lands on movement, which is the one
  transition rule with an eye-tracking study behind it.
- **Hook.** The strongest moment of the day opens the video, held as long
  as the reference holds its first shot, so the payoff comes before the
  setup. It plays again in its place; that repeat is the cold-open pattern.

Every weight and threshold below is a first guess. `tests/test_select.py`
checks that each one moves the choice the way it claims, not that the
numbers are right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from . import storyboard as sb

DUP_SIM = 0.90            # embedding cosine above this, within DUP_MIN, is the same picture
DUP_MIN = 15.0
FACE_ON_CAMERA = (0.015, 0.30)   # face area that reads as "the creator, in the world"
MOTION_SHAKY = 40.0       # mean luma change per keyframe-second that reads as thrown around
MOTION_STILL = 4.0        # below this the picture is a still
CLIP_CAP = 1              # picks one clip may supply inside one session (a long clip: 2)
LONG_CLIP_S = 60.0
NOVELTY_MIN = 0.22        # a pick must differ from the session's earlier picks by this much:
                          # on real footage, three takes of the same boba cup sit at cosine
                          # 0.71-0.82, and different scenes at ~0.6, so 0.78 is the line
LEAD_IN = 0.5             # the busiest second sits mid-window: the cut in and the cut out both
                          # land while something moves, which is what joins two shots
EDGE_S = 0.6              # the first moments of a clip are the phone coming up; cut in after
MIN_SHOT_S = 0.5          # a shot shorter than this is a detector artefact, not a moment
SCORE_FLOOR = 0.45        # below this a shot doesn't fill a quota; the video runs shorter
W = {"craft": 0.30, "distinct": 0.25, "camera": 0.20, "subject": 0.15, "motion": 0.10}
HOOK_W = {"distinct": 0.4, "contrast": 0.2, "late": 0.1}   # on top of the hero score


@dataclass
class Pick:
    shot: sb.Shot
    role: str                       # hook | hero | filler
    start: float
    end: float
    score: float
    why: str
    session: int = 0
    short: bool = False             # filmed shorter than the pace asked for
    room: tuple[float, float] | None = None   # a teaser glimpse: the source seconds it may use (make.teaser)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Plan:
    hook: list[Pick]
    sessions: list[list[Pick]]      # chronological picks per session
    titles: list[str]
    notes: list[str] = field(default_factory=list)
    dropped_dup: int = 0
    # a vlog's teaser (make.teaser): glimpses of later moments before the hook and the title
    teaser: list[Pick] = field(default_factory=list)

    @property
    def picks(self) -> list[Pick]:
        return self.teaser + self.hook + [p for s in self.sessions for p in s]

    @property
    def duration(self) -> float:
        return sum(p.duration for p in self.picks)


# --------------------------------------------------------------------------
# per-shot evidence
# --------------------------------------------------------------------------

def _sig(clips: dict[str, dict], s: sb.Shot, name: str) -> np.ndarray:
    """One value per second of the shot's span, or an empty array."""
    arr = np.asarray((clips.get(s.clip_id) or {}).get("signals", {}).get(name) or [], dtype=np.float32)
    if arr.size == 0:
        return arr
    a, b = int(max(0, s.start)), int(min(len(arr), math.ceil(s.end)))
    return arr[a:max(b, a + 1)]


def idf(shots: list[sb.Shot]) -> dict[str, float]:
    """How rare each label is across the shoot: rare means a moment, common means background."""
    n = max(1, len(shots))
    df: dict[str, int] = {}
    for s in shots:
        for k in s.labels:
            df[k] = df.get(k, 0) + 1
    return {k: math.log((n + 1) / (v + 1)) for k, v in df.items()}


def distinctiveness(s: sb.Shot, weights: dict[str, float], top: int = 3) -> float:
    """0..1: mean rarity of the shot's strongest labels, on a log scale."""
    if not s.labels or not weights:
        return 0.0
    keys = sorted(s.labels, key=lambda k: -s.labels[k])[:top]
    hi = max(weights.values()) or 1.0
    return float(np.clip(np.mean([weights.get(k, 0.0) for k in keys]) / hi, 0, 1))


def camera(s: sb.Shot) -> float:
    lo, hi = FACE_ON_CAMERA
    if lo <= s.face_area <= hi:
        return 1.0
    return 0.55 if s.faces else 0.35


def motion_ok(clips: dict[str, dict], s: sb.Shot) -> float:
    m = _sig(clips, s, "motion")
    if m.size == 0:
        return 0.5
    med = float(np.median(m))
    if med >= MOTION_SHAKY:
        return float(np.clip(1 - (med - MOTION_SHAKY) / MOTION_SHAKY, 0, 1)) * 0.5
    if med <= MOTION_STILL:
        return 0.6
    return 1.0


def subject(clips: dict[str, dict], s: sb.Shot) -> float:
    x = _sig(clips, s, "subject")
    return float(np.clip(np.mean(x) / 0.5, 0, 1)) if x.size else 0.5


def hero_score(s: sb.Shot, clips: dict[str, dict], weights: dict[str, float],
               bias: dict[str, float] | None = None) -> tuple[float, dict]:
    parts = {"craft": s.score, "distinct": distinctiveness(s, weights), "camera": camera(s),
             "subject": subject(clips, s), "motion": motion_ok(clips, s)}
    score = sum(W[k] * v for k, v in parts.items())
    if bias:
        # the creator's habits (habits.py): a small push per label, on top of craft
        h = sum(w * float(c) for l, w in bias.items() for ll, c in s.labels.items() if ll == l)
        if h:
            parts["habit"] = round(h, 3)
            score += h
    return score, parts


def busiest(clips: dict[str, dict], s: sb.Shot, lo: float, hi: float) -> float:
    """The second inside [lo, hi] where subject and movement peak -- where to cut in."""
    sub, mot = _sig(clips, s, "subject"), _sig(clips, s, "motion")
    n = min(sub.size, mot.size)
    if n == 0:
        return (lo + hi) / 2
    base = int(max(0, s.start))
    m = mot[:n] / (mot[:n].max() + 1e-6)
    interest = sub[:n] + 0.5 * m
    ts = base + np.arange(n) + 0.5
    ok = (ts >= lo) & (ts <= hi)
    if not ok.any():
        return (lo + hi) / 2
    k = int(np.argmax(np.where(ok, interest, -1)))
    return float(ts[k])


def contrast(clips: dict[str, dict], s: sb.Shot) -> float:
    x = _sig(clips, s, "contrast")
    return float(np.clip(np.mean(x), 0, 1)) if x.size else 0.5


def window(clips: dict[str, dict], s: sb.Shot, want: float) -> tuple[float, float, bool]:
    """A `want`-second window that cuts in just before the busiest second."""
    lo, hi = s.start, s.end
    if hi - lo <= want + 1e-3:
        return lo, hi, True
    if hi - lo >= want + EDGE_S:
        lo = lo + EDGE_S
    t = busiest(clips, s, lo + LEAD_IN * want, hi - (1 - LEAD_IN) * want)
    a = float(np.clip(t - LEAD_IN * want, lo, hi - want))
    return round(a, 3), round(a + want, 3), False


# --------------------------------------------------------------------------
# choosing
# --------------------------------------------------------------------------

def dedupe(shots: list[sb.Shot]) -> tuple[list[sb.Shot], int]:
    """Drop the weaker of two look-alikes filmed within DUP_MIN minutes."""
    keep: list[sb.Shot] = []
    dropped = 0
    for s in sorted(shots, key=lambda x: -x.score):
        dup = False
        for k in keep:
            if s.when and k.when and abs((s.when - k.when).total_seconds()) > DUP_MIN * 60:
                continue
            if s.vec.size == k.vec.size and float(np.dot(s.vec, k.vec)) >= DUP_SIM:
                dup = True
                break
        if dup:
            dropped += 1
        else:
            keep.append(s)
    return sorted(keep, key=lambda x: x.order), dropped


def sessions_of(shots: list[sb.Shot], cap: int = sb.MAX_BEATS) -> list[list[sb.Shot]]:
    seq = sb.chrono(shots)
    if not seq:
        return []
    groups: list[list[sb.Shot]] = [[seq[0]]]
    for prev, s in zip(seq, seq[1:]):
        gap = (s.when - prev.when).total_seconds() if (s.when and prev.when) else 0
        new_day = bool(s.when and prev.when and s.when.date() != prev.when.date())
        if gap > sb.SESSION_GAP.total_seconds() or new_day:
            groups.append([s])
        else:
            groups[-1].append(s)
    return sb._merge_smallest(groups, cap, key=lambda g: g[0].when or datetime.max)


def quotas(groups: list[list[sb.Shot]], n: int) -> list[int]:
    """Spread n picks over sessions by sqrt(footage), at least one each, never more than there are."""
    if not groups:
        return []
    weight = np.sqrt([sum(s.duration for s in g) for g in groups])
    weight = weight / weight.sum() if weight.sum() > 0 else np.ones(len(groups)) / len(groups)
    q = np.maximum(1, np.floor(weight * n)).astype(int)
    q = np.minimum(q, [len(g) for g in groups])
    left = n - int(q.sum())
    frac = weight * n - np.floor(weight * n)
    for i in np.argsort(-frac):
        if left <= 0:
            break
        if q[i] < len(groups[i]):
            q[i] += 1
            left -= 1
    return [int(x) for x in q]


def _novel(s: sb.Shot, taken: list[sb.Shot]) -> float:
    if not taken:
        return 1.0
    sims = [float(np.dot(s.vec, t.vec)) for t in taken if t.vec.size == s.vec.size]
    return 1.0 - max(sims) if sims else 1.0


def choose(shots: list[sb.Shot], clips: dict[str, dict], n: int, hook_n: int = 1,
           bias: dict[str, float] | None = None, min_s: float = MIN_SHOT_S) -> Plan:
    """n moments from the shoot, plus hook_n that open it. `bias`: the
    creator's label habits (habits.py), a nudge on top of craft. `min_s`:
    shots filmed shorter than this can't hold the pace asked for (a vlog
    wants room to rest in; a reel doesn't)."""
    shots, dropped = dedupe([s for s in shots if not s.utility and s.duration >= max(min_s, MIN_SHOT_S)])
    weights = idf(shots)
    scored = {s.id: hero_score(s, clips, weights, bias) for s in shots}
    groups = sessions_of(shots)
    q = quotas(groups, max(1, n))
    picked: list[list[sb.Shot]] = []
    for g, k in zip(groups, q):
        taken: list[sb.Shot] = []
        per_clip: dict[str, int] = {}
        for s in sorted(g, key=lambda x: -scored[x.id][0]):
            if len(taken) >= k:
                break
            if scored[s.id][0] < SCORE_FLOOR and taken:
                break   # the rest of this session is weaker than the floor; run short instead
            cap = 2 if (clips.get(s.clip_id) or {}).get("duration", 0) >= LONG_CLIP_S else CLIP_CAP
            if per_clip.get(s.clip_id, 0) >= cap or _novel(s, taken) < NOVELTY_MIN:
                continue
            taken.append(s)
            per_clip[s.clip_id] = per_clip.get(s.clip_id, 0) + 1
        picked.append(sorted(taken, key=lambda x: x.order))

    # The hook: the moment that is most *this day* -- distinctive, punchy, and
    # by preference from later on, so the payoff comes before the setup.
    pool = [s for g in picked for s in g]

    def punch(s: sb.Shot) -> float:
        return (scored[s.id][0] + HOOK_W["distinct"] * scored[s.id][1]["distinct"]
                + HOOK_W["contrast"] * contrast(clips, s) + HOOK_W["late"] * _late(s, pool))

    hook: list[sb.Shot] = []
    for s in sorted(pool, key=lambda x: (-punch(x), -x.order)):
        if len(hook) >= hook_n:
            break
        if all(_novel(s, [h]) >= 0.3 for h in hook):
            hook.append(s)

    def mk(s: sb.Shot, role: str, sess: int) -> Pick:
        sc, parts = scored[s.id]
        why = ", ".join(f"{k} {v:.2f}" for k, v in sorted(parts.items(), key=lambda kv: -W.get(kv[0], 1.0) * kv[1])[:3])
        return Pick(s, role, s.start, s.end, sc, why, sess)

    plan = Plan(
        hook=[mk(s, "hook", 0) for s in hook],
        sessions=[[mk(s, "hero" if scored[s.id][0] >= _median(scored) else "filler", i) for s in g]
                  for i, g in enumerate(picked)],
        titles=[sb.part_of_day(g[0].when) if g and g[0].when else f"Part {i + 1}" for i, g in enumerate(groups)],
        dropped_dup=dropped,
    )
    if dropped:
        plan.notes.append(f"Left out {dropped} near-repeat shot{'s' * (dropped != 1)}.")
    return plan


def _late(s: sb.Shot, pool: list[sb.Shot]) -> float:
    orders = [x.order for x in pool]
    lo, hi = min(orders), max(orders)
    return (s.order - lo) / (hi - lo) if hi > lo else 0.0


def _median(scored: dict[str, tuple[float, dict]]) -> float:
    return float(np.median([v[0] for v in scored.values()])) if scored else 0.0


def time_windows(plan: Plan, clips: dict[str, dict], targets: list[float], hook_s: float) -> None:
    """Give every pick its window: the hook held for hook_s, the rest following `targets` in order."""
    for p in plan.hook:
        p.start, p.end, p.short = window(clips, p.shot, hook_s)
    seq = [p for s in plan.sessions for p in s]
    # a tiny shoot can leave more picks than targets (or none at all): pad
    # with the last target, else the hook's own length -- never index into nothing
    pad = targets[-1] if targets else hook_s
    for p, want in zip(seq, targets + [pad] * max(0, len(seq) - len(targets))):
        p.start, p.end, p.short = window(clips, p.shot, want)


# --------------------------------------------------------------------------
# judged (plan step 4): with a key, Claude sees one frame per candidate --
# the rules' picks plus the next few runners-up in that session -- and says
# which to keep. The rules still set the pool, the quota and the windows;
# the model only chooses among what the rules already found good enough.
# No key, an error or an odd answer: the rules' picks stand, and the plan
# says so in its notes.
# --------------------------------------------------------------------------

RUNNERS_UP = 2       # extra candidates a session offers the judge, beyond its quota [prior]
JUDGE_MIN = 3        # fewer candidates than this: nothing to judge


def _frame(clips: dict[str, dict], s: sb.Shot) -> bytes | None:
    from . import indexer
    c = clips.get(s.clip_id) or {}
    name = (s.thumb or "").rsplit("/", 1)[-1]
    p = indexer.clip_dir(c.get("id", s.clip_id)) / name if name else None
    try:
        return p.read_bytes() if p and p.exists() else None
    except OSError:
        return None


def judge(plan: Plan, shots: list[sb.Shot], clips: dict[str, dict], ask=None, taste: str = "") -> Plan:
    """Re-pick each session with `ask(options, keep) -> (indices, why)`;
    the default is llm.rank_shots with the creator's `taste` when a key is
    set, else nothing happens."""
    if ask is None:
        from . import llm
        if not llm.available():
            return plan
        ask = lambda options, keep: llm.rank_shots(options, keep, taste)  # noqa: E731
    weights = idf(shots)
    scored = {s.id: hero_score(s, clips, weights) for s in shots}
    by_id = {s.id: s for s in shots}
    groups = sessions_of([s for s in shots if not s.utility and s.duration >= MIN_SHOT_S])
    judged = 0
    for i, sess in enumerate(plan.sessions):
        if not sess or i >= len(groups):
            continue
        taken = [p.shot.id for p in sess]
        extra = [s.id for s in sorted(groups[i], key=lambda x: -scored[x.id][0]) if s.id not in taken][:RUNNERS_UP]
        cand = [by_id[k] for k in taken + extra if k in by_id]
        if len(cand) < JUDGE_MIN or len(cand) <= len(taken):
            continue
        options = []
        for s in cand:
            fr = _frame(clips, s)
            if fr is None:
                break
            options.append({"label": f"{s.clip_name} {s.start:.0f}s, rules {scored[s.id][0]:.2f}", "frame": fr})
        if len(options) != len(cand):
            continue
        try:
            keep, why = ask(options, len(taken))
        except Exception:  # noqa: BLE001 -- the rules' picks stand
            continue
        chosen = [cand[k] for k in keep]
        plan.sessions[i] = [Pick(s, "hero" if scored[s.id][0] >= _median(scored) else "filler", s.start, s.end,
                                 scored[s.id][0], f"judged: {why}" if why else "judged", i)
                            for s in sorted(chosen, key=lambda x: x.order)]
        judged += 1
    if judged:
        plan.notes.append(f"Claude judged the moments in {judged} session{'s' * (judged != 1)} from one frame each.")
    return plan
