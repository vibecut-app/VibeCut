"""Where to cut into a shot and out of it, learnt from pros' own edits.

Make keeps a few seconds of each clip, and which seconds is a guess today:
select.window puts the clip's busiest second in the middle of the window,
so "the cut in and the cut out both land while something moves". Nobody
checked that against an editor.

The method is Learning to Cut (Pardo et al., ICCV 2021,
github.com/PardoAlejo/LearningToCut, MIT; see NOTICE): every real cut in a
finished edit is a decision, and the moments the editor could have cut at
instead are its negatives -- for the cut out of a shot, the earlier moments
of the same shot; for the cut into the next, its later ones. A scorer is
trained to rank the real moment first among them (softmax over each cut's
candidates, InfoNCE). Their model runs on full-rate picture and sound
features in PyTorch; this keeps the method and reads only what VibeCut
already has for a phone clip at Make time, so what is learnt from a pro's
edit can be asked of a clip:

- the words: voiced intervals at 10 ms (signals.voiced_of), only where the
  sound classifier hears a voice (signals.gated, as with_voice does)
- laughter, once a second (the Mac's sound classifier)
- movement, subject and edge once a second, as the index reads them
  (signals.from_media's own definitions, on the seconds the shot holds whole)

Nothing says where in the shot a moment sits (the paper's rule too): a
pro's out-point is always the shot's last moment, so anything that knew
where the shot ends would "find" every cut. A cut out is read looking back
from it only, a cut in looking ahead only; nothing within GAP of the cut
is read, so the cut's own jump in picture and sound can't give it away;
candidates sit only where everything they read lies inside the shot; and
a reading one candidate of a cut lacks is left out for that whole cut.

Records (taste/cuts/<id>.json, written by `taste.collect --only cuts` on
sarah's Mac from the vlogs already measured): numbers only -- where the
cuts are, when someone is talking, the once-a-second readings, and a 10 Hz
movement and level curve kept for looking into later. No frame, no word,
no sound is kept.

    python -m taste.cuts train     # leave-one-creator-out against the rule

The scorer is used only on the side (in, out) where it finds the pros'
cuts more often than the rule does on creators it never saw, by a margin
the bootstrap over creators can't explain away (`trusted`). Every
constant here is a prior.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
OUT = HERE / "cuts"
MODEL = HERE / "model" / "cuts.json"
REPORT = HERE / "model" / "cuts-report.md"
VERSION = 1

STEP = 0.1            # candidates every tenth of a second
SPAN = 3.0            # a cut out is looked for in the shot's last 3 s, a cut in in its first 3 s
REACH = 1.0           # how far back (out) or ahead (in) the words are read
GAP = 0.05            # nothing this close to the cut is read: the cut's own jump in sound and picture
HIT = 0.3             # within this of the pro's cut counts as finding it (the paper used 0.33 s)
MIN_SHOT = 1.0        # the paper dropped shots under a second
MIN_CANDS = 5         # a cut with fewer places to choose from says nothing
WORD_MIN = 0.08       # signals.voiced_of drops blips under 80 ms; a clipped word is held to the same
TALK_S = 1.0          # talking share is read over the second next to the cut
GAPS = (0.15, 0.35, 0.7)   # time since a word ended (out) / until one starts (in): near / short / mid / far (to REACH)
HARD = ("cut", "jump")     # a dissolve, dip or flash blends the two shots: not a place to learn a cut point
FINE_HZ = 10
L2 = 1.0
BOOT = 2000
MIN_CREATORS = 8      # fewer unseen creators than this and the test is too thin to trust
MIN_CUTS = 200
NUDGE = 1.0           # in Make the scorer moves the rule's window by at most this (see place)

NAMES = ("word", "near", "short", "mid", "far", "talk", "laugh", "motion", "subject", "edge")
SAY = {"word": "mid-word", "near": "a word ended / starts under 0.15 s away",
       "short": "a word ended / starts 0.15-0.35 s away", "mid": "a word ended / starts 0.35-0.7 s away",
       "far": "a word ended / starts 0.7-1 s away", "talk": "talking in the second next to the cut",
       "laugh": "laughter next to the cut", "motion": "movement in the second next to the cut",
       "subject": "a clear subject in frame",
       "edge": "the subject near the frame's edge"}


def _r(x, nd: int = 3):
    return None if x is None else round(float(x), nd)


# --------------------------------------------------------------------------
# what a moment looks like, from either side of the pipeline
# --------------------------------------------------------------------------

@dataclass
class Track:
    """One shot's readings, on its own clock (a pro's video, or a clip).
    `lo`..`hi`: the stretch that is this shot's own picture and sound.
    `grid`: second k -> (motion, subject, edge), the index's reading of a
    frame in second k (motion against the frame a second earlier), for the
    seconds whose two frames both lie in lo..hi (see grid_keys)."""
    lo: float
    hi: float
    voiced: list
    grid: dict
    laugh: list | None = None


def grid_keys(lo: float, hi: float, n: int | None = None) -> range:
    """The seconds whose frame (at k + 0.5 in a pro's video; a keyframe in
    second k in a clip) and the frame a second before both lie in lo..hi."""
    top = math.floor(hi - 0.5 + 1e-9) + 1
    return range(max(1, math.ceil(lo + 0.5 - 1e-9)), top if n is None else min(n, top))


def _point(t: float, side: str) -> float:
    return t - GAP if side == "out" else t + GAP


def _second(p: float, side: str) -> int:
    """The grid second read for a cut at p: the last whose frame comes by p
    (out), the first whose earlier frame comes at p or after (in) -- so a
    pro's frames on the far side of the cut are never read."""
    return math.floor(p - 0.5 + 1e-9) if side == "out" else math.ceil(p + 0.5 - 1e-9)


def features(tr: Track, t: float, side: str) -> list:
    """The readings of a cut at `t` ("out": the shot ends there; "in": it
    starts there), None where the track hasn't that reading."""
    out = side == "out"
    p = _point(t, side)
    w0, w1 = (max(tr.lo, p - REACH), p) if out else (p, min(tr.hi, p + REACH))
    t0, t1 = (p - TALK_S, p) if out else (p, p + TALK_S)
    word, gap, talk = 0.0, None, 0.0
    for s0, e0 in tr.voiced:
        s, e = max(s0, w0), min(e0, w1)
        if e - s < WORD_MIN - 1e-9:
            continue
        talk += max(0.0, min(e, t1) - max(s, t0))
        if s0 < p < e0:
            word = 1.0
        elif out and e0 <= p:
            gap = p - e0 if gap is None else min(gap, p - e0)
        elif not out and s0 >= p:
            gap = s0 - p if gap is None else min(gap, s0 - p)
    bins = [0.0] * 4
    if gap is not None and not word:
        bins[sum(gap >= g for g in GAPS)] = 1.0

    laugh = None
    if tr.laugh:
        # a ~1 s window centred in second k hears [k - 0.5, k + 1.5)
        k = math.floor(p - 1.5 + 1e-9) if out else math.ceil(p + 0.5 - 1e-9)
        if 0 <= k < len(tr.laugh) and k - 0.5 >= tr.lo - 1e-9 and k + 1.5 <= tr.hi + 1e-9:
            laugh = float(tr.laugh[k])

    here = tr.grid.get(_second(p, side))
    return [word, *bins, talk / TALK_S, laugh,
            math.log1p(here[0]) if here else None, here[1] if here else None, here[2] if here else None]


def interest(tr: Track, t: float, side: str) -> float | None:
    """Today's rule read at one moment: select.busiest's interest
    (subject + half the movement against the shot's most) in the second
    next to the cut -- the rule cuts in and out "while something moves"."""
    v = tr.grid.get(_second(_point(t, side), side))
    if v is None:
        return None
    top = max(x[0] for x in tr.grid.values()) + 1e-6
    return float(v[1] + 0.5 * v[0] / top)


def matrix(tr: Track, ts, side: str, keep: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(times, readings, rule) for one cut's candidates.

    A reading some candidates lack (there's no room for it behind them in
    the shot): with `keep` (the pro's own moment, when learning), those
    candidates are dropped if MIN_CANDS remain with the pro's among them
    -- which candidates have room depends on where they sit, never on
    what's there, so the comparison stays fair; otherwise, and always in
    Make, that reading is left out for every candidate (0), so having it
    can't tell one from another. The rule likewise."""
    ts = np.asarray(ts, dtype=np.float64)
    X = np.array([[np.nan if v is None else float(v) for v in features(tr, t, side)] for t in ts], dtype=np.float64)
    X = X.reshape(len(ts), len(NAMES))
    rule = np.array([np.nan if (r := interest(tr, t, side)) is None else r for t in ts], dtype=np.float64)
    gone = np.isnan(X)
    some = gone.any(axis=0) & ~gone.all(axis=0)
    if keep is not None and some.any():
        ok = ~gone[:, some].any(axis=1)
        if ok.sum() >= MIN_CANDS and ok[keep]:
            ts, X, rule = ts[ok], X[ok], rule[ok]
    X[:, np.isnan(X).any(axis=0)] = 0.0
    rule = np.zeros(len(ts)) if np.isnan(rule).any() else rule
    return ts, X, rule


# --------------------------------------------------------------------------
# a pro's finished vlog -> a record (on the Mac, while the download exists)
# --------------------------------------------------------------------------

def _grey(frames: np.ndarray) -> np.ndarray:
    f = frames.astype(np.float32)
    return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]


def grid_of(m, grey: np.ndarray, lo: float, hi: float) -> dict:
    """Second k -> [motion, subject, edge]: the index's reading (a frame a
    second, motion against the one before) of the frame at k + 0.5, for the
    seconds whose two frames lie in lo..hi -- the shot's own frames only.
    Keys are strings (JSON)."""
    from cutgrammar import signals
    fps = m.fps or 30.0
    out = {}
    for k in grid_keys(lo, hi):
        i, j = int(round((k + 0.5) * fps)), int(round((k - 0.5) * fps))
        if j < 0 or i >= len(grey):
            continue
        mot = float(np.abs(grey[i] - grey[j]).mean())
        sub, edge = signals.subject_presence(signals._small_grey(m.frames[i:i + 1], signals.SAL_W)[0])
        out[str(k)] = [_r(mot), _r(sub), _r(edge)]
    return out


def fine_of(m, grey: np.ndarray) -> dict:
    """10 Hz movement and sound level of the whole edit: for looking into
    what the once-a-second readings miss. Not used to train (a pro's mix
    carries music a phone clip doesn't)."""
    from cutgrammar import features as feat
    fps = m.fps or 30.0
    idx = np.round(np.arange(0, m.duration, 1 / FINE_HZ) * fps).astype(int)
    idx = idx[idx < len(grey)]
    mo = np.zeros(len(idx))
    if len(idx) > 1:
        mo[1:] = np.abs(grey[idx[1:]] - grey[idx[:-1]]).mean(axis=(1, 2))
    db, _ = feat.frame_audio(m, 1 / FINE_HZ)
    return {"hz": FINE_HZ, "motion": [round(float(x), 1) for x in mo],
            "level": [round(float(x), 1) for x in db]}


def read_video(path: str, *, id: str, group: str, creator: str, limit_s: float | None = None, mac: bool = True,
               log=print, loaded=None) -> dict:
    """One finished vlog -> its record: the cuts (as describe reads them),
    each shot's own stretch and once-a-second readings, the voiced
    intervals (gated by the classifier's voice on the Mac) and laughter."""
    from cutgrammar import media, signals
    from . import describe

    m = loaded if loaded is not None else media.load(path, limit_s=limit_s)
    dur = float(m.duration)
    n = max(1, math.ceil(dur - 1e-6))
    joins, fades = describe.joins_of(m, log)
    per = None
    if mac and m.has_audio:
        from web.backend import sound
        sbin = sound.ensure_built()
        if sbin is not None:
            per = describe._read_sound(sound, sbin, path, limit_s, n)
    _, voiced = signals.voiced_of(m, n)
    if per and per.get("voice"):
        voiced = signals.gated(voiced, signals.voice_gate(per["voice"], n))

    grey = _grey(m.frames) if m.n_frames else np.zeros((0, 1, 1), dtype=np.float32)
    edges = [0.0, *[x["t"] for x in joins], dur]
    kinds = [None, *[x["kind"] for x in joins], None]
    soft = [0.0, *[x["dur"] / 2 for x in joins], 0.0]
    fade_in = max([x["dur"] for x in fades if x["kind"] == "fade_in"], default=0.0)
    fade_out = max([x["dur"] for x in fades if x["kind"] == "fade_out"], default=0.0)
    shots = []
    for i, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        # the shot's own stretch: not the blend of a soft join, not a fade
        lo = a + (soft[i] if kinds[i] not in HARD else 0.0) + (fade_in if i == 0 else 0.0)
        hi = b - (soft[i + 1] if kinds[i + 1] not in HARD else 0.0) - (fade_out if i == len(edges) - 2 else 0.0)
        shots.append({"a": _r(a), "b": _r(b), "lo": _r(lo), "hi": _r(hi), "into": kinds[i], "out": kinds[i + 1],
                      "grid": grid_of(m, grey, lo, hi) if hi > lo else {}})
    rec = {"v": VERSION, "id": id, "group": group, "creator": creator, "fps": _r(m.fps), "duration": _r(dur),
           "cutoff": bool(limit_s and dur >= limit_s - 1), "have": ["sound"] if per else [],
           "shots": shots, "voiced": voiced, "laugh": per["laughter"] if per else None,
           "fine": fine_of(m, grey) if m.n_frames else None}
    hard = sum(x["kind"] in HARD for x in joins)
    log(f"  {len(shots)} shots, {hard} hard cuts, {len(voiced)} stretches of talking"
        + ("" if per else " (no sound classifier: talking from the level only)"))
    return rec


def save(rec: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, separators=(",", ":")))


def load_records(folder: Path | None = None) -> list[dict]:
    folder = folder or OUT
    out = []
    for p in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            r = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if r.get("v") == VERSION:
            out.append(r)
    return out


# --------------------------------------------------------------------------
# every cut in a record -> two choices, each with its candidates
# --------------------------------------------------------------------------

def creator_key(name: str) -> str:
    """One creator under one name across the lists ("Casey Neistat" in the
    long list, "caseyneistat" in the shorts), so a creator held out of
    training is held out whole."""
    return re.sub(r"[^a-z0-9]", "", name.lower().split("(")[0]) or name


def _track(rec: dict, sh: dict, lo: float, hi: float) -> Track:
    """The part lo..hi of a pro's shot, with only the seconds it holds."""
    inside = set(grid_keys(lo, hi))
    grid = {int(k): tuple(v) for k, v in (sh.get("grid") or {}).items() if int(k) in inside}
    return Track(lo, hi, rec.get("voiced") or [], grid, rec.get("laugh"))


def groups(rec: dict) -> list[dict]:
    """Each hard cut is two decisions: where the shot before it ends (its
    candidates: the same shot's earlier moments) and where the shot after
    it starts (that shot's later ones). True = the pro's own moment.

    A cut out is read in the second half of its shot only, a cut in in the
    first half: the pro chose both ends of a shot, so a late candidate for
    the cut in, reading ahead, would read the run-up to the pro's own cut
    out -- where the shot ends, by another road (it lifted a model to 5
    points over chance on a made-up set where nothing marked the cut in)."""
    out = []
    for sh in rec.get("shots") or []:
        a, b = float(sh["a"]), float(sh["b"])
        if b - a < MIN_SHOT:
            continue
        lo, hi = float(sh.get("lo", a)), float(sh.get("hi", b))
        mid = (a + b) / 2
        for side, kind in (("out", sh.get("out")), ("in", sh.get("into"))):
            if kind not in HARD:
                continue
            tr = _track(rec, sh, max(lo, mid), hi) if side == "out" else _track(rec, sh, lo, min(hi, mid))
            if side == "out":
                ts = [round(b - j * STEP, 3) for j in range(int(round(SPAN / STEP)) + 1)]
                ts = [t for t in ts if t - GAP - REACH >= tr.lo - 1e-9]
                true = b
            else:
                ts = [round(a + j * STEP, 3) for j in range(int(round(SPAN / STEP)) + 1)]
                ts = [t for t in ts if t + GAP + REACH <= tr.hi + 1e-9]
                true = a
            if len(ts) < MIN_CANDS:
                continue
            ts, X, rule = matrix(tr, ts, side, keep=0)      # the pro's own moment is the first listed
            out.append({"side": side, "ts": ts, "true": true, "X": X, "rule": rule,
                        "words": rule - X[:, 0], "creator": creator_key(rec.get("creator") or rec.get("id") or ""),
                        "group": rec.get("group"), "id": rec.get("id")})
    return out


# --------------------------------------------------------------------------
# the scorer: a conditional logit per side, fitted by Newton's method
# --------------------------------------------------------------------------

def _newton(data: list[tuple[np.ndarray, int]], l2: float, iters: int = 50) -> np.ndarray:
    d = data[0][0].shape[1]
    w = np.zeros(d)
    for _ in range(iters):
        g, H = l2 * w, l2 * np.eye(d)
        for X, y in data:
            s = X @ w
            p = np.exp(s - s.max())
            p /= p.sum()
            xb = p @ X
            g += xb - X[y]
            H += (X.T * p) @ X - np.outer(xb, xb)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w


def fit(gs: list[dict], l2: float = L2) -> dict:
    model = {"v": VERSION, "names": list(NAMES)}
    for side in ("out", "in"):
        sel = [g for g in gs if g["side"] == side]
        if not sel:
            model[side] = None
            continue
        allx = np.vstack([g["X"] for g in sel])
        mu, sd = allx.mean(axis=0), allx.std(axis=0)
        sd[sd < 1e-9] = 1.0
        data = [((g["X"] - mu) / sd, int(np.argmin(np.abs(g["ts"] - g["true"])))) for g in sel]
        w = _newton(data, l2)
        model[side] = {"mean": mu.tolist(), "std": sd.tolist(), "w": w.tolist()}
    return model


def score(model: dict, X: np.ndarray, side: str) -> np.ndarray:
    m = model.get(side)
    if not m:
        return np.zeros(len(X))
    return ((X - np.asarray(m["mean"])) / np.asarray(m["std"])) @ np.asarray(m["w"])


def hit(scores: np.ndarray, ts: np.ndarray, true: float) -> float:
    """1 when the top candidate is within HIT of the pro's cut; ties share.
    Flattering to any scorer of smooth readings: the pro's moment is always
    at an end of the candidates, and the top of a smooth curve over a
    stretch lands at an end more often than chance (3 points over the
    random rate on a made-up set where nothing marked the cuts). Reported,
    not used to decide."""
    top = np.flatnonzero(scores >= scores.max() - 1e-9)
    return float(np.mean(np.abs(ts[top] - true) <= HIT + 1e-6))


def rank(scores: np.ndarray, ts: np.ndarray, true: float) -> float | None:
    """How often the pro's own moment scores above a candidate more than
    HIT away (a tie is half): 0.5 for any scorer that knows nothing,
    wherever in the shot the pro's moment sits. This decides."""
    i = int(np.argmin(np.abs(ts - true)))
    far = np.abs(ts - true) > HIT + 1e-6
    if not far.any():
        return None
    d = scores[i] - scores[far]
    return float(np.mean((d > 1e-12) + 0.5 * (np.abs(d) <= 1e-12)))


# --------------------------------------------------------------------------
# the test: creators the scorer never saw, against the rule
# --------------------------------------------------------------------------

WAYS = ("model", "rule", "words")


def evaluate(recs: list[dict], seed: int = 0) -> dict:
    gs = [g for r in recs for g in groups(r)]
    creators = sorted({g["creator"] for g in gs})
    for c in creators:
        mdl = fit([g for g in gs if g["creator"] != c])
        for g in gs:
            if g["creator"] != c:
                continue
            sc = {"model": score(mdl, g["X"], g["side"]), "rule": g["rule"], "words": g["words"]}
            g["hit"] = {w: hit(v, g["ts"], g["true"]) for w, v in sc.items()}
            g["hit"]["random"] = float(np.mean(np.abs(g["ts"] - g["true"]) <= HIT + 1e-6))
            g["rank"] = {w: rank(v, g["ts"], g["true"]) for w, v in sc.items()}
    gs = [g for g in gs if "rank" in g and g["rank"]["model"] is not None]
    rng = random.Random(seed)

    def part(sel: list[dict]) -> dict:
        if not sel:
            return {"cuts": 0}
        out = {"cuts": len(sel), "creators": len({g["creator"] for g in sel}),
               "rank": {w: round(float(np.mean([g["rank"][w] for g in sel])), 4) for w in WAYS},
               "hit": {w: round(float(np.mean([g["hit"][w] for g in sel])), 4) for w in (*WAYS, "random")}}
        best = max(("rule", "words"), key=lambda w: out["rank"][w])
        by: dict[str, list[float]] = {}
        for g in sel:
            by.setdefault(g["creator"], []).append(g["rank"]["model"] - g["rank"][best])
        names = sorted(by)
        diffs = []
        for _ in range(BOOT if len(names) > 1 else 0):
            pick = [by[rng.choice(names)] for _ in names]
            diffs.append(sum(map(sum, pick)) / sum(map(len, pick)))
        out["against"] = best
        out["gain"] = round(out["rank"]["model"] - out["rank"][best], 4)
        out["gain_low"] = round(float(np.percentile(diffs, 2.5)), 4) if diffs else None
        out["gain_high"] = round(float(np.percentile(diffs, 97.5)), 4) if diffs else None
        return out

    report = {"all": part(gs)}
    for side in ("out", "in"):
        report[side] = part([g for g in gs if g["side"] == side])
        for grp in ("long", "short"):
            report[f"{side}_{grp}"] = part([g for g in gs if g["side"] == side and g["group"] == grp])
    report["videos"] = len(recs)
    report["creators"] = len(creators)
    return report


def wins(part: dict) -> bool:
    """The scorer is trusted on a side only when it beats the better
    reading of the rule on creators it never saw, with the bootstrap's low
    end above zero, over enough creators and cuts to mean something."""
    return bool(part.get("cuts", 0) >= MIN_CUTS and part.get("creators", 0) >= MIN_CREATORS
                and part.get("gain_low") is not None and part["gain_low"] > 0)


def train(folder: Path | None = None, model_path: Path | None = None, report_path: Path | None = None,
          log=print) -> dict | None:
    folder, model_path, report_path = folder or OUT, model_path or MODEL, report_path or REPORT
    recs = load_records(folder)
    if not recs:
        log(f"no records in {folder}: run `python -m taste.collect --only cuts` on the Mac first")
        return None
    rep = evaluate(recs)
    model = fit([g for r in recs for g in groups(r)])
    model.update(trained=time.strftime("%Y-%m-%d"), report=rep,
                 trusted={side: wins(rep[side]) for side in ("out", "in")})
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, indent=1))
    text = describe_report(model)
    report_path.write_text(text)
    log(text)
    _cache.clear()
    return model


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def describe_report(model: dict) -> str:
    rep = model["report"]
    lines = [f"# Where pros cut in and out ({model.get('trained')})", "",
             f"{rep['videos']} vlogs, {rep['creators']} creators; every cut scored by a scorer that never saw "
             "its creator. Score = how often the pro's own moment beats a moment more than "
             f"{HIT} s away (50% = no idea). Top = the best moment lands within {HIT} s of the pro's "
             "(flattering to the scorer; not used to decide).", "",
             "| | cuts | scorer | rule (busiest) | rule, never mid-word | scorer vs the better rule (95%) "
             "| top: scorer / rule / chance |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for key, name in (("out", "cut out"), ("out_long", "  long vlogs"), ("out_short", "  shorts"),
                      ("in", "cut in"), ("in_long", "  long vlogs"), ("in_short", "  shorts"), ("all", "both")):
        p = rep.get(key) or {}
        if not p.get("cuts"):
            continue
        gain = (f"{100 * p['gain']:+.1f} pts ({100 * p['gain_low']:+.1f} to {100 * p['gain_high']:+.1f})"
                if p.get("gain_low") is not None else f"{100 * p['gain']:+.1f} pts")
        r, h = p["rank"], p["hit"]
        lines.append(f"| {name} | {p['cuts']} | {_pct(r['model'])} | {_pct(r['rule'])} | {_pct(r['words'])} | {gain} "
                     f"| {_pct(h['model'])} / {_pct(h[p['against']])} / {_pct(h['random'])} |")
    lines += ["", "Used in Make: " + (", ".join(s for s in ("out", "in") if model["trusted"].get(s)) or "neither side")
              + f" (needs the low end above zero, {MIN_CREATORS}+ creators, {MIN_CUTS}+ cuts).", ""]
    for side, name in (("out", "Cutting out"), ("in", "Cutting in")):
        m = model.get(side)
        if not m:
            continue
        w = sorted(zip(NAMES, m["w"]), key=lambda x: -abs(x[1]))
        lines.append(f"{name}, what the pros' cuts lean on (weights on standardised readings):")
        lines += [f"- {'more' if v > 0 else 'less'} {SAY[k]} ({v:+.2f})" for k, v in w[:5] if abs(v) >= 0.05]
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# in Make
# --------------------------------------------------------------------------

_cache: dict = {}


def load(path: Path | None = None) -> dict | None:
    path = path or MODEL
    try:
        st = path.stat().st_mtime
    except OSError:
        return None
    if _cache.get("at") != (str(path), st):
        try:
            m = json.loads(path.read_text())
        except (OSError, ValueError):
            m = None
        _cache.update(at=(str(path), st), model=m if m and m.get("v") == VERSION else None)
    return _cache["model"]


def trusted(path: Path | None = None) -> bool:
    m = load(path)
    return bool(m and any((m.get("trusted") or {}).values()))


def clip_track(rec: dict, lo: float, hi: float) -> Track:
    """A clip's index readings as a Track: the same seconds a pro's shot
    gives (signals' own motion / subject / edge, grid_keys), its voiced
    intervals as sound.attach left them (gated by the voice), its
    laughter."""
    sig = rec.get("signals") or {}
    mo, su, ed = sig.get("motion") or [], sig.get("subject") or [], sig.get("edge") or []
    n = min(len(mo), len(su), len(ed))
    grid = {k: (float(mo[k]), float(su[k]), float(ed[k])) for k in grid_keys(lo, hi, n)}
    return Track(float(lo), float(hi), sig.get("voiced") or [], grid, (rec.get("sound") or {}).get("laughter"))


def place(rec: dict, start: float, end: float, want: float, lo: float, hi: float, around: float | None = None,
          model: dict | None = None) -> float | None:
    """Where a `want`-second window of the clip shot start..end should
    begin, within lo..hi: the moment the pros' scorer rates best for the
    cut in plus the cut out, on the sides it's trusted on. `around`: the
    rule's own start, which the scorer may move by at most NUDGE (the rule
    still decides which part of the clip; the scorer, the exact cut). None
    when there's nothing to decide or no trusted scorer."""
    mdl = model if model is not None else load()
    if not mdl or hi - lo < want + STEP - 1e-9:
        return None
    ok = mdl.get("trusted") or {}
    if not any(ok.values()):
        return None
    a0, a1 = lo, hi - want
    if around is not None:
        a0, a1 = max(a0, around - NUDGE), min(a1, around + NUDGE)
    if a1 < a0:
        return None
    starts = np.round(np.arange(a0, a1 + 1e-6, STEP), 3)
    tr = clip_track(rec, start, end)
    total = np.zeros(len(starts))
    if ok.get("in"):
        total += score(mdl, matrix(tr, starts, "in")[1], "in")
    if ok.get("out"):
        total += score(mdl, matrix(tr, starts + want, "out")[1], "out")
    if around is not None:
        total -= 1e-6 * np.abs(starts - around)     # a tie keeps the rule's choice
    return float(starts[int(np.argmax(total))])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m taste.cuts")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("train", help="test on unseen creators against the rule, then fit on all")
    rd = sub.add_parser("read", help="read one finished video into a record (prints a summary)")
    rd.add_argument("path")
    rd.add_argument("--id", default="X001")
    rd.add_argument("--group", default="short", choices=["short", "long"])
    rd.add_argument("--creator", default="someone")
    rd.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "read":
        rec = read_video(a.path, id=a.id, group=a.group, creator=a.creator)
        gs = groups(rec)
        print(f"{len(gs)} cut decisions ({sum(g['side'] == 'out' for g in gs)} out, "
              f"{sum(g['side'] == 'in' for g in gs)} in)")
        if a.save:
            save(rec, OUT / f"{a.id}.json")
        return
    train()


if __name__ == "__main__":
    main()
