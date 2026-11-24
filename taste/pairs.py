"""Where each shot of a finished vlog came from in its raw footage.

sarah, 2026-11-24: "could you find raw footage (unedited videos) that a
blogger already posted on the internet and try training on that?". A
finished vlog shows what a pro kept; only next to the clips it was cut
from does it show what they left out, and where inside a clip they cut in
and out. That is Make's own question about a phone clip.

`align` finds, for every shot of the edit, the raw clip it was taken from
and the stretch of that clip it shows, from the same tiny frames
`media.load` gives everything else (48 x 27, read once). Each frame is
reduced to its grey picture with its brightness and contrast taken out, so
a pro's grade doesn't hide it; the clip's frames are also read cropped in
(a punch-in, a stabiliser's zoom). A shot's frames vote for (clip, offset);
the offset that most frames agree on wins, at the clip's own speed first,
then any steady speed (a slow-motion or sped-up shot). A shot no clip
explains (titles, stock, footage that wasn't shared) is left unmatched,
never forced.

Records are numbers only: which clip, the stretch kept, its speed and how
sure the match is. No frame is kept.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

STEP_S = 0.1          # source frames are compared every 0.1 s; a match lands between them by the curve
GRID = (24, 14)       # the picture compared: 48 x 27 halved, grey, normalised
SCALES = (1.0, 0.88, 0.76)   # source read whole and punched in (an edit's crop of the clip)
EDGE_S = 0.15         # a shot's first and last frames may be a blend; not used to match
TOP_K = 4             # source frames each edit frame votes for
SIM_MIN = 0.80        # below this two pictures aren't the same moment
TOL_S = 0.15          # a vote agrees with an offset within this
AGREE = 0.6           # share of a shot's frames that must agree with its match
SPEEDS = (1.0, 0.5, 2.0, 0.25, 0.4, 0.8, 1.25, 1.5, 3.0, 4.0)   # steady speeds tried after 1x
MIN_SHOT_S = 0.4      # shorter shots are too few frames to place


@dataclass
class Source:
    """One raw clip as the matcher sees it."""
    id: str
    duration: float
    times: np.ndarray      # (n,) seconds of the compared frames
    desc: np.ndarray       # (n, len(SCALES), d) normalised pictures


def _norm(x: np.ndarray) -> np.ndarray:
    """Brightness and contrast out: a grade moves both, the picture stays."""
    x = x.reshape(x.shape[0], -1).astype(np.float32)
    x = x - x.mean(axis=1, keepdims=True)
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.maximum(n, 1e-3)


def _grey(frames: np.ndarray) -> np.ndarray:
    f = frames.astype(np.float32)
    return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]


def _resize(grey: np.ndarray, w: int, h: int) -> np.ndarray:
    """Box resize of (n, H, W) float pictures."""
    from cutgrammar import media
    g = np.clip(grey, 0, 255).astype(np.uint8)[..., None].repeat(3, axis=3)
    return media.area_resize(g, w, h)[..., 0].astype(np.float32)


def _crop(grey: np.ndarray, s: float) -> np.ndarray:
    if s >= 0.999:
        return grey
    h, w = grey.shape[1:3]
    ch, cw = max(2, round(h * s)), max(2, round(w * s))
    y, x = (h - ch) // 2, (w - cw) // 2
    return grey[:, y:y + ch, x:x + cw]


def pictures(frames: np.ndarray, scales=(1.0,)) -> np.ndarray:
    """(n, len(scales), d): each frame grey, cropped to each scale, on GRID."""
    g = _grey(frames)
    return np.stack([_norm(_resize(_crop(g, s), *GRID)) for s in scales], axis=1)


def source(m, id: str) -> Source:
    """A raw clip's pictures every STEP_S (from media.load's frames)."""
    fps = float(m.fps or 30.0)
    n = m.n_frames
    every = max(1, round(STEP_S * fps))
    idx = np.arange(0, n, every)
    return Source(id=id, duration=float(m.duration), times=idx / fps,
                  desc=pictures(m.frames[idx], SCALES) if len(idx) else np.zeros((0, len(SCALES), GRID[0] * GRID[1])))


def _votes(q: np.ndarray, srcs: list[Source]) -> list[list[tuple[int, float, float, int]]]:
    """For each edit picture, its TOP_K best (source, time, similarity, scale)."""
    out: list[list[tuple[int, float, float, int]]] = [[] for _ in range(len(q))]
    for si, s in enumerate(srcs):
        if not len(s.times):
            continue
        sims = np.einsum("qd,nsd->qns", q, s.desc)           # (q, n, scales)
        best_scale = sims.argmax(axis=2)
        best = sims.max(axis=2)                              # (q, n)
        k = min(TOP_K, best.shape[1])
        top = np.argpartition(-best, k - 1, axis=1)[:, :k]
        n = best.shape[1]
        for qi in range(len(q)):
            for j in top[qi]:
                t = float(s.times[j])
                if 0 < j < n - 1:        # between two compared frames: the peak of the curve through three
                    y0, y1, y2 = best[qi, j - 1], best[qi, j], best[qi, j + 1]
                    den = y0 - 2 * y1 + y2
                    if den < -1e-6:
                        t += float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5)) * float(s.times[j + 1] - s.times[j])
                out[qi].append((si, t, float(best[qi, j]), int(best_scale[qi, j])))
    for qi in range(len(q)):
        out[qi] = sorted(out[qi], key=lambda v: -v[2])[:TOP_K]
    return out


def _fit(ts: np.ndarray, votes, src: int) -> tuple[float, float, float, float] | None:
    """The steady speed and offset (src_t = speed * t + c) most of the shot's
    frames agree on in source `src`: (speed, c, share agreeing, mean sim)."""
    best = None
    for speed in SPEEDS:
        cs, ws = [], []
        for t, vs in zip(ts, votes):
            for (si, st, sim, _) in vs:
                if si == src and sim >= SIM_MIN:
                    cs.append(st - speed * t)
                    ws.append(sim)
        if not cs:
            continue
        cs, ws = np.asarray(cs), np.asarray(ws)
        # the offset with the most agreeing frames (each frame counted once)
        for c0 in cs:
            agree, sims = 0, []
            for t, vs in zip(ts, votes):
                hit = [sim for (si, st, sim, _) in vs if si == src and sim >= SIM_MIN
                       and abs(st - speed * t - c0) <= TOL_S * max(1.0, speed)]
                if hit:
                    agree += 1
                    sims.append(max(hit))
            share = agree / len(ts)
            key = (round(share, 3), float(np.mean(sims)) if sims else 0.0)
            if best is None or key > (round(best[2], 3), best[3]):
                best = (speed, float(c0), share, key[1])
        if speed == 1.0 and best and best[2] >= AGREE:
            break                                    # at the clip's own speed: no need to try others
    return best


def align(edit, cuts: list[float], srcs: list[Source]) -> list[dict]:
    """Every shot of the finished edit (between `cuts`, seconds, with 0 and
    the end implied) -> {a, b, clip, src_in, src_out, speed, share, sim} or
    {a, b, clip: None} when no raw clip explains it."""
    fps = float(edit.fps or 30.0)
    dur = float(edit.duration)
    edges = [0.0, *sorted(t for t in cuts if 0 < t < dur), dur]
    shots = []
    for a, b in zip(edges[:-1], edges[1:]):
        row = {"a": round(a, 3), "b": round(b, 3), "clip": None}
        lo, hi = a + EDGE_S, b - EDGE_S
        if hi - lo < MIN_SHOT_S - 2 * EDGE_S or hi <= lo:
            shots.append(row)
            continue
        ts = np.arange(lo, hi, STEP_S)
        idx = np.clip(np.round(ts * fps).astype(int), 0, edit.n_frames - 1)
        q = pictures(edit.frames[idx])[:, 0]
        votes = _votes(q, srcs)
        best = None
        for si in {v[0] for vs in votes for v in vs if v[2] >= SIM_MIN}:
            f = _fit(ts, votes, si)
            if f and (best is None or (f[2], f[3]) > (best[1][2], best[1][3])):
                best = (si, f)
        if best and best[1][2] >= AGREE:
            si, (speed, c, share, sim) = best
            s = srcs[si]
            src_in, src_out = speed * a + c, speed * b + c
            row.update(clip=s.id, src_in=round(max(0.0, src_in), 3), src_out=round(min(s.duration, src_out), 3),
                       speed=speed, share=round(share, 3), sim=round(sim, 3))
        shots.append(row)
    return shots


def kept(shots: list[dict]) -> dict[str, list[list[float]]]:
    """Clip id -> the stretches of it the edit shows, merged, in order."""
    out: dict[str, list[list[float]]] = {}
    for s in shots:
        if s.get("clip"):
            out.setdefault(s["clip"], []).append([s["src_in"], s["src_out"]])
    for k, spans in out.items():
        spans.sort()
        merged = [spans[0]]
        for x0, x1 in spans[1:]:
            if x0 <= merged[-1][1] + 0.05:
                merged[-1][1] = max(merged[-1][1], x1)
            else:
                merged.append([x0, x1])
        out[k] = [[round(x0, 3), round(x1, 3)] for x0, x1 in merged]
    return out


def coverage(shots: list[dict]) -> float:
    """Share of the edit's seconds placed in a raw clip."""
    tot = sum(s["b"] - s["a"] for s in shots)
    hit = sum(s["b"] - s["a"] for s in shots if s.get("clip"))
    return hit / tot if tot > 0 else 0.0


def _r(x: float) -> float:
    return round(float(x), 3) if math.isfinite(x) else 0.0
