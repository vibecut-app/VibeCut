"""How editors cut a clip, read from screen recordings of them editing.

sarah, 2026-11-24: "vibecut needs to learn and imitate how humans edit,
instead of looking at a video and then generating a product lookalike",
then, of the "edit my vlog with me" videos: "isnt there tutorials on
youtube and xiaohongshu" and "build 1".

A finished vlog shows what an editor kept. A screen recording of them
editing it also shows, in the editor's preview window, the raw clips
playing before they were cut. Matching each shot of the finished vlog
back to where its footage played in that window (taste.pairs) gives, for
every clip they looked at, the seconds they kept and the seconds around
them they left out, and which clips they looked at and dropped. That is
the decision Make takes for every phone clip, and a finished vlog alone
can't show it.

Reading one recording (`read_video`):

1. Study: the recording at 2 fps, grey, 192 px wide. The editor's screen
   is what stays put. Frames where it doesn't (the host talking to camera,
   the finished vlog shown full screen, a zoom into the timeline) are
   "away". The preview window is the rectangle that keeps changing while
   the screen around it stays put. A timeline strip that scrolls sideways
   under a fixed playhead (CapCut, 剪映 on a phone) changes too; a sideways
   shift explains its change, which tells it apart.
2. Read: the preview window at 10 fps, 48 x 27, cut into playbacks. A
   playback is a run of steady change with no cut, no pause and no time
   away from the editor.
3. Final: the finished vlog. That is the posted vlog when the list links
   one (`final_url`). Otherwise it is whichever stretch away from the
   editor the playbacks explain best: the "here's the finished video" at
   the end or the start. Failing that, it is the last long run of the
   timeline playing through. It must explain MIN_COVER of its seconds.
4. Match: each shot of the finished vlog is found in the playback that
   showed the most of its clip around it, so the clip's left-out seconds
   are seen. The recording's own speed-up (editing shown at 4x) comes
   from the matches, and a shot the editor sped up or slowed is marked.

Record (taste/tutorials/<id>.json, on sarah's Mac; *.json stays out of
git): numbers only. It holds where the preview sits, each clip played
(its seconds on the clip's own clock), the windows kept, the
once-a-second movement / subject / edge as Make's index reads a clip,
the clips played and never kept, and when everything played. No frame,
word or sound is kept.

Learning (`train`): every kept window is a choice among the other
windows of the same length in the same clip. It is ranked with a
conditional logit on what Make knows about a clip at Make time
(movement, subject and edge around the cut in, the cut out and inside),
and tested leave-one-creator-out against select.window's rule, the
clip's middle and chance. Where in the clip a window sits is never read,
nor how far it is from the rule's (which knows where the clip starts): a
playback starts and stops where the editor clicked, so its ends say more
about the editor's hand than about the clip.

    python -m taste.tutorial read <recording> [--final <posted vlog>]
    python -m taste.tutorial train

Every constant is a prior.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import pairs as P

HERE = Path(__file__).parent
OUT = HERE / "tutorials"
LIST = HERE / "data" / "tutorials.csv"
MODEL = HERE / "model" / "tutorials.json"
REPORT = HERE / "model" / "tutorials-report.md"
VERSION = 1

# --- reading a recording ----------------------------------------------------
STUDY_FPS = 2.0
STUDY_W = 192
READ_FPS = 10.0
CHANGE = 16           # grey levels: a pixel that moved this much changed
NEAR = 0.5            # a frame where more of the screen than this differs from the usual one is away
STATIC = 0.15         # a pixel differing from the usual screen in under this share of the editor's frames stays put
MIN_STILL = 0.2       # a recording where less than this of the screen stays put isn't an editor's screen
AWAY = 0.25           # a frame where this share of what stays put has changed is away from the editor
BAND = 6              # rows looked at together for a scrolling strip
SCROLL = 0.25         # a sideways shift explaining a strip's change down to this ratio...
SCROLL_SHARE = 0.6    # ...in this share of its changes: a timeline scrolling under a fixed playhead
TAU = 0.4             # the preview: where change is at least this share of the screen's busiest
MIN_ACT = 0.05        # the busiest pixels changing less often than this: nothing ever played
MIN_AREA = 0.03       # a preview smaller than this share of the screen isn't one
ASPECT = (0.3, 3.5)
HOLD_D = 1.0          # grey levels between frames: below this the preview isn't moving
HOLD_S = 0.5          # ...for this long: paused
CUT_SIM = 0.45        # two frames less alike than this: a cut
PLAY_MIN_S = 1.0      # a playback shorter than this is a click, not a look
FINAL_MIN_S = 20.0    # a finished vlog shown in the recording lasts at least this
CHAIN_MIN = 3         # ...and the timeline playing it through crosses at least this many cuts
MIN_COVER = 0.3       # share of the finished vlog's seconds the playbacks must explain
EDGE_TRIM_S = 0.25    # the first and last moments of a stretch away may be a transition
SPEED_OFF = 0.25      # a shot whose speed is this far off the recording's own was sped up / slowed in the edit
DROP_MIN_S = 2.0      # a playback shorter than this (clip time) says little about a dropped clip
SAME = 0.9            # pictures this alike are the same moment (a clip seen twice)
MAX_S = 3600.0        # only the first hour of a recording is read

# --- learning ---------------------------------------------------------------
STEP = 0.1
HIT = 0.3             # candidates nearer the editor's own than this aren't compared (cuts.HIT)
MIN_W = 0.5
ROOM = (1.5, 1.0)     # a window learnt from has this much of the clip before and after it, so every
                      # reading around it exists (movement starts a second in): one at a playback's
                      # edge would be told from the others by what's missing, not by what's there
MIN_CANDS = 5
MIN_CREATORS = 8
MIN_DECISIONS = 200
L2 = 1.0
BOOT = 2000
EDGE_S = 0.6          # select.EDGE_S
LEAD_IN = 0.5         # select.LEAD_IN

NAMES = ("pre_motion", "in_motion", "out_motion", "post_motion", "in_subject", "out_subject",
         "in_edge", "out_edge", "held_motion", "held_subject", "peak")
SAY = {"pre_motion": "movement just before the cut in", "in_motion": "movement just after the cut in",
       "out_motion": "movement just before the cut out", "post_motion": "movement just after the cut out",
       "in_subject": "a clear subject at the cut in", "out_subject": "a clear subject at the cut out",
       "in_edge": "the subject near the frame's edge at the cut in",
       "out_edge": "the subject near the frame's edge at the cut out",
       "held_motion": "movement inside the kept part", "held_subject": "a clear subject inside the kept part",
       "peak": "the clip's liveliest second inside the kept part"}


def _r(x, nd: int = 3):
    return None if x is None else round(float(x), nd)


@dataclass
class Clip:
    """Frames at a steady rate, as pairs.align and pairs.source read them."""
    frames: np.ndarray
    fps: float

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    @property
    def duration(self) -> float:
        return len(self.frames) / self.fps


# --------------------------------------------------------------------------
# decoding
# --------------------------------------------------------------------------

def probe(path: str) -> tuple[int, int, float]:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", path], capture_output=True, text=True)
    d = json.loads(p.stdout or "{}")
    st = (d.get("streams") or [{}])[0]
    return int(st.get("width") or 0), int(st.get("height") or 0), float((d.get("format") or {}).get("duration") or 0)


def _decode(path: str, vf: str, w: int, h: int, rgb: bool = False, t0: float = 0.0,
            dur: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if t0 > 0:
        cmd += ["-ss", f"{t0:.3f}"]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    ch = 3 if rgb else 1
    cmd += ["-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24" if rgb else "gray", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-400:])
    n = len(p.stdout) // (w * h * ch)
    a = np.frombuffer(p.stdout[: n * w * h * ch], np.uint8)
    return a.reshape(n, h, w, 3) if rgb else a.reshape(n, h, w)


def _even(x: float) -> int:
    return max(2, int(round(x)) // 2 * 2)


def study(path: str, size: tuple[int, int], limit_s: float | None = None) -> np.ndarray:
    """The whole screen at STUDY_FPS, grey, STUDY_W wide."""
    w0, h0 = size
    w, h = STUDY_W, _even(STUDY_W * h0 / max(1, w0))
    return _decode(path, f"fps={STUDY_FPS},scale={w}:{h}:flags=area", w, h, dur=limit_s)


def read_region(path: str, box: tuple[int, int, int, int] | None, t0: float = 0.0,
                dur: float | None = None) -> np.ndarray:
    """A rectangle of the screen (source pixels; None = all of it) at
    READ_FPS, squashed to 48 x 27 like every other frame VibeCut reads."""
    crop = f"crop={box[2]}:{box[3]}:{box[0]}:{box[1]}," if box else ""
    return _decode(path, f"fps={READ_FPS},{crop}scale=48:27:flags=area", 48, 27, rgb=True, t0=t0, dur=dur)


# --------------------------------------------------------------------------
# the editor's screen and its preview window
# --------------------------------------------------------------------------

def _chunks(n: int, size: int = 256):
    for i in range(0, n, size):
        yield slice(i, min(n, i + size))


def screen(g: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(away: per study frame, still: the pixels of the editor's screen that
    stay put). Every frame is away when nothing stays put."""
    n = len(g)
    usual = np.median(g[:: max(1, n // 400)], axis=0).astype(np.int16)
    frac = np.zeros(n)
    for c in _chunks(n):
        frac[c] = (np.abs(g[c].astype(np.int16) - usual) > CHANGE).mean(axis=(1, 2))
    near = frac < NEAR
    if near.sum() < 10:
        return np.ones(n, bool), np.zeros(g.shape[1:], bool)
    changed = np.zeros(g.shape[1:], np.float64)
    idx = np.flatnonzero(near)
    for c in _chunks(len(idx)):
        changed += (np.abs(g[idx[c]].astype(np.int16) - usual) > CHANGE).sum(axis=0)
    still = changed / len(idx) < STATIC
    if still.mean() < MIN_STILL:
        return np.ones(n, bool), still
    away = np.zeros(n, bool)
    for c in _chunks(n):
        d = np.abs(g[c].astype(np.int16) - usual)[:, still] > CHANGE
        away[c] = d.mean(axis=1) > AWAY
    return away, still


def activity(g: np.ndarray, away: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(how often each pixel changes between two frames of the editor,
    the frame pairs looked at)."""
    idx = np.flatnonzero(~away[:-1] & ~away[1:])
    act = np.zeros(g.shape[1:], np.float64)
    for c in _chunks(len(idx)):
        i = idx[c]
        act += (np.abs(g[i + 1].astype(np.int16) - g[i].astype(np.int16)) > CHANGE).sum(axis=0)
    return act / max(1, len(idx)), idx


def scrolling(g: np.ndarray, pairs_idx: np.ndarray) -> np.ndarray:
    """Rows of a strip whose change is mostly the same picture moved
    sideways: a timeline running under a fixed playhead, not a preview."""
    h, w = g.shape[1:]
    rows = np.zeros(h, bool)
    if len(pairs_idx) < 5:
        return rows
    reach = max(2, w // 6)
    for r0 in range(0, h, BAND):
        band = slice(r0, min(h, r0 + BAND))
        a = g[pairs_idx, band].astype(np.int16)
        b = g[pairs_idx + 1, band].astype(np.int16)
        res0 = np.abs(b - a).mean(axis=(1, 2))
        moving = res0 > 2.0
        if moving.sum() < 5 or moving.mean() < 0.02:
            continue
        a, b, res0 = a[moving][:200], b[moving][:200], res0[moving][:200]
        best = np.full(len(a), np.inf)
        for dx in range(1, reach + 1):
            best = np.minimum(best, np.abs(b[:, :, dx:] - a[:, :, :-dx]).mean(axis=(1, 2)))
            best = np.minimum(best, np.abs(b[:, :, :-dx] - a[:, :, dx:]).mean(axis=(1, 2)))
        if (best < SCROLL * res0).mean() >= SCROLL_SHARE:
            rows[band] = True
    return rows


def _best_rect(s: np.ndarray) -> tuple[float, int, int, int, int]:
    """The rectangle with the largest sum of `s`: (sum, x0, x1, y0, y1), inclusive."""
    h, w = s.shape
    cs = np.zeros((h, w + 1))
    cs[:, 1:] = np.cumsum(s, axis=1)
    best = (-np.inf, 0, 0, 0, 0)
    for left in range(w):
        col = cs[:, left + 1:] - cs[:, [left]]          # (h, right): each row's sum over left..right
        m = col.shape[1]
        cur = np.zeros(m)
        start = np.zeros(m, int)
        top = np.full(m, -np.inf)
        y0 = np.zeros(m, int)
        y1 = np.zeros(m, int)
        for r in range(h):
            fresh = cur <= 0
            cur = np.where(fresh, col[r], cur + col[r])
            start = np.where(fresh, r, start)
            better = cur > top
            top = np.where(better, cur, top)
            y0 = np.where(better, start, y0)
            y1 = np.where(better, r, y1)
        j = int(np.argmax(top))
        if top[j] > best[0]:
            best = (float(top[j]), left, left + j, int(y0[j]), int(y1[j]))
    return best


def monitor(act: np.ndarray, scroll_rows: np.ndarray) -> tuple[int, int, int, int] | None:
    """The preview window (x, y, w, h in study pixels), or None."""
    h, w = act.shape
    a = act.copy()
    a[scroll_rows] = 0.0
    top = float(np.percentile(a, 99.5))
    if top < MIN_ACT:
        return None
    _, x0, x1, y0, y1 = _best_rect(a - TAU * top)
    rw, rh = x1 - x0 + 1, y1 - y0 + 1
    if rw * rh < MIN_AREA * w * h or not ASPECT[0] <= rw / rh <= ASPECT[1]:
        return None
    return x0, y0, rw, rh


def _to_source(box, size, study_shape, inset: float = 0.02) -> tuple[int, int, int, int]:
    """A study-pixel box -> source pixels, pulled in a little off its border."""
    (w0, h0), (hs, ws) = size, study_shape
    sx, sy = w0 / ws, h0 / hs
    x, y, w, h = box
    dx, dy = w * inset, h * inset
    cx, cy = _even((x + dx) * sx), _even((y + dy) * sy)
    cw, ch = _even((w - 2 * dx) * sx), _even((h - 2 * dy) * sy)
    return cx, cy, min(cw, w0 - cx), min(ch, h0 - cy)


def picture_box(g: np.ndarray) -> tuple[int, int, int, int] | None:
    """Where the picture is in frames shown full screen: bars (letterbox,
    a vertical video on a wide screen) never change and are dark."""
    if len(g) < 2:
        return None
    sd = g.std(axis=0)
    live = (sd > 4) | (g.mean(axis=0) > 24)
    ys, xs = np.flatnonzero(live.any(axis=1)), np.flatnonzero(live.any(axis=0))
    if not len(ys) or not len(xs):
        return None
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]
    if (x1 - x0 + 1) * (y1 - y0 + 1) < 0.2 * g.shape[1] * g.shape[2]:
        return None
    return int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)


# --------------------------------------------------------------------------
# what played in the preview
# --------------------------------------------------------------------------

def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Runs of True as (start, end exclusive)."""
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def away_at(away: np.ndarray, n: int) -> np.ndarray:
    """Study frames' away -> each read frame's (away if either neighbour is)."""
    if not len(away):
        return np.zeros(n, bool)
    r = np.arange(n) * STUDY_FPS / READ_FPS
    lo = np.clip(np.floor(r).astype(int), 0, len(away) - 1)
    hi = np.clip(np.ceil(r).astype(int), 0, len(away) - 1)
    return away[lo] | away[hi]


def playbacks(frames: np.ndarray, away: np.ndarray, fps: float = READ_FPS) -> list[tuple[int, int]]:
    """Runs of the preview playing one clip: no cut, no pause, no time away."""
    n = len(frames)
    if n < 2:
        return []
    g = P._grey(frames)
    d = np.r_[np.inf, np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))]
    pic = P.pictures(frames)[:, 0]
    sim = np.r_[-1.0, (pic[1:] * pic[:-1]).sum(axis=1)]
    paused = np.zeros(n, bool)
    for a, b in _runs(d < HOLD_D):
        if b - a >= round(HOLD_S * fps):
            paused[a:b] = True
    use = ~away & ~paused
    out = []
    start = None
    for j in range(n):
        if not use[j]:
            if start is not None:
                out.append((start, j))
            start = None
        elif start is None or sim[j] < CUT_SIM:
            if start is not None:
                out.append((start, j))
            start = j
    if start is not None:
        out.append((start, n))
    return [(a, b) for a, b in out if (b - a) / fps >= PLAY_MIN_S]


def _shots_cuts(frames: np.ndarray, fps: float) -> list[float]:
    """Hard cuts of frames read in the recording (shots.detect)."""
    from cutgrammar import media, shots
    m = media.Media(path="", fps=fps, duration=len(frames) / fps, width=48, height=27, creation_time=None,
                    location=None, frames=frames, audio=np.zeros(0, np.float32))
    return [s.start_t for s in shots.detect(m)[1:]]


def _widest(srcs: list[P.Source]):
    """Of the playbacks explaining a shot, the one that showed the most of
    its clip (playback seconds / its speed); the earliest of equals."""
    def choose(fits):
        return max(fits, key=lambda x: (round(srcs[x[0]].duration / max(x[1][0], 1e-6), 1), -x[0]))
    return choose


def _match(final: Clip, cuts: list[float], srcs: list[P.Source]) -> list[dict]:
    return P.align(final, cuts, srcs, per_source=True, choose=_widest(srcs))


# --------------------------------------------------------------------------
# one recording -> its record
# --------------------------------------------------------------------------

def _grid(frames: np.ndarray, rate: float, length: float) -> dict:
    """Once-a-second readings of a clip that played at `rate` recording
    seconds per clip second: movement (against the frame a clip second
    earlier), subject and edge at k + 0.5, as Make's index reads a clip."""
    from cutgrammar import signals
    g = P._grey(frames)
    n = len(frames)
    mot, sub, edg = [], [], []
    for k in range(int(math.floor(length + 1e-9))):
        i = int(round((k + 0.5) * rate * READ_FPS))
        if i >= n:
            break
        j = int(round((k - 0.5) * rate * READ_FPS))
        mot.append(_r(np.abs(g[i] - g[j]).mean()) if k >= 1 and j >= 0 else None)
        s, e = signals.subject_presence(signals._small_grey(frames[i:i + 1], signals.SAL_W)[0])
        sub.append(_r(s))
        edg.append(_r(e))
    return {"motion": mot, "subject": sub, "edge": edg}


def _same_as(a: np.ndarray, b: np.ndarray) -> bool:
    """Most of playback a's pictures are found in playback b."""
    if not len(a) or not len(b):
        return False
    return float(((a @ b.T).max(axis=1) >= SAME).mean()) >= 0.5


def _candidates(path, size, g, away, mon_frames, pbs, final_path, log) -> list[dict]:
    """Every stretch that could be the finished vlog: frames, cuts, and the
    playbacks it may not be matched against (its own)."""
    out = []
    if final_path:
        from cutgrammar import media
        m = media.load(final_path)
        out.append({"source": "posted", "t0": 0.0, "t1": float(m.duration), "frames": m.frames,
                    "fps": float(m.fps or 30.0), "own": set()})
    for a, b in _runs(away):
        t0, t1 = a / STUDY_FPS + EDGE_TRIM_S, b / STUDY_FPS - EDGE_TRIM_S
        if t1 - t0 < FINAL_MIN_S:
            continue
        box = picture_box(g[a:b])
        if box is None:
            continue
        src = _to_source(box, size, g.shape[1:], inset=0.0)
        out.append({"source": "shown", "t0": t0, "t1": t1, "frames": read_region(path, src, t0, t1 - t0),
                    "fps": READ_FPS, "own": set()})
    # the timeline playing through: playbacks one after another, split only by cuts
    chains, cur = [], []
    for i, (a, b) in enumerate(pbs):
        if cur and a == pbs[cur[-1]][1]:
            cur.append(i)
        else:
            if cur:
                chains.append(cur)
            cur = [i]
    if cur:
        chains.append(cur)
    long = [c for c in chains if len(c) >= CHAIN_MIN and (pbs[c[-1]][1] - pbs[c[0]][0]) / READ_FPS >= FINAL_MIN_S]
    if long:
        c = long[-1]
        a, b = pbs[c[0]][0], pbs[c[-1]][1]
        out.append({"source": "timeline", "t0": a / READ_FPS, "t1": b / READ_FPS, "frames": mon_frames[a:b],
                    "fps": READ_FPS, "own": set(c)})
    log(f"  {len(out)} stretch{'es' * (len(out) != 1)} that could be the finished vlog")
    return out


def read_video(path: str, *, id: str, creator: str, final_path: str | None = None, app: str = "",
               limit_s: float | None = MAX_S, log=print) -> dict:
    """One screen recording (and the posted vlog, if given) -> its record."""
    w0, h0, dur = probe(path)
    rec = {"v": VERSION, "id": id, "creator": creator, "app": app, "duration": _r(dur),
           "read_s": _r(min(dur, limit_s) if limit_s else dur)}
    g = study(path, (w0, h0), limit_s)
    away, still = screen(g)
    rec["away"] = _r(away.mean())
    act, idx = activity(g, away)
    rows = scrolling(g, idx)
    box = monitor(act, rows)
    if box is None:
        rec["error"] = "no preview window found"
        log(f"  {rec['error']}")
        return rec
    hs, ws = g.shape[1:]
    rec["preview"] = [_r(box[0] / ws), _r(box[1] / hs), _r(box[2] / ws), _r(box[3] / hs)]
    rec["scrolling"] = bool(rows.any())
    src_box = _to_source(box, (w0, h0), (hs, ws))
    mon = read_region(path, src_box, 0.0, limit_s)
    aw = away_at(away, len(mon))
    pbs = playbacks(mon, aw)
    rec["playbacks"] = [[_r(a / READ_FPS), _r(b / READ_FPS)] for a, b in pbs]
    log(f"  preview at {rec['preview']}, {len(pbs)} playbacks, {100 * rec['away']:.0f}% of the time away")
    if not pbs:
        rec["error"] = "nothing played in the preview"
        return rec
    srcs = [P.source(Clip(mon[a:b], READ_FPS), str(i)) for i, (a, b) in enumerate(pbs)]

    best = None
    for c in _candidates(path, (w0, h0), g, away, mon, pbs, final_path, log):
        fin = Clip(c["frames"], c["fps"])
        use = [s if int(s.id) not in c["own"] else P.Source(s.id, s.duration, s.times[:0], s.desc[:0])
               for s in srcs]
        shots = _match(fin, _shots_cuts(c["frames"], c["fps"]), use)
        cov = P.coverage(shots)
        log(f"  {c['source']} {c['t0']:.0f}-{c['t1']:.0f} s: {len(shots)} shots, {100 * cov:.0f}% found in the playbacks")
        if best is None or cov > best[1]:
            best = (c, cov, shots)
    if best is None or best[1] < MIN_COVER:
        rec["error"] = "the finished vlog wasn't found in the playbacks"
        rec["cover"] = _r(best[1]) if best else 0.0
        log(f"  {rec['error']}")
        return rec
    c, cov, shots = best
    rec["final"] = {"source": c["source"], "t0": _r(c["t0"]), "t1": _r(c["t1"]), "cover": _r(cov),
                    "shots": len(shots)}

    # the recording's own speed: playback seconds per clip second, from what most shots agree on
    sp = [s["speed"] for s in shots if s.get("clip") is not None]
    rate = float(np.exp(np.median(np.log(sp))))
    rec["rate"] = _r(rate)
    clips: dict[int, dict] = {}
    for k, s in enumerate(shots):
        if s.get("clip") is None:
            continue
        pi = int(s["clip"])
        a, b = pbs[pi]
        length = (b - a) / READ_FPS / rate
        cl = clips.setdefault(pi, {"playback": pi, "t0": _r(a / READ_FPS), "t1": _r(b / READ_FPS),
                                   "length": _r(length), "kept": []})
        e = s["speed"] / rate                              # clip seconds per finished-vlog second
        # a finished vlog read off the recording starts and ends where the study's half-second
        # frames say: its first shot's cut in and its last shot's cut out may be lost
        cut = c["source"] == "shown" and (k == 0 or k == len(shots) - 1)
        cl["kept"].append({"in": _r(s["src_in"] / rate), "out": _r(s["src_out"] / rate), "shot": k,
                           "at": s["a"], "speed": _r(e, 2), "steady": abs(math.log(e)) <= math.log(1 + SPEED_OFF),
                           "share": s["share"], "sim": s["sim"], **({"cut_off": True} if cut else {})})
    for pi, cl in clips.items():
        a, b = pbs[pi]
        cl["kept"].sort(key=lambda x: x["in"])
        cl["grid"] = _grid(mon[a:b], rate, cl["length"])

    kept_pics = [srcs[pi].desc[:, 0] for pi in clips]
    dropped, seen = [], []
    for i, (a, b) in enumerate(pbs):
        length = (b - a) / READ_FPS / rate
        if i in clips or i in c["own"] or length < DROP_MIN_S:
            continue
        pic = srcs[i].desc[:, 0]
        if any(_same_as(pic, k) for k in kept_pics) or any(_same_as(pic, s) for s in seen):
            continue                                     # part of a kept clip, or a clip seen before
        seen.append(pic)
        dropped.append({"playback": i, "t0": _r(a / READ_FPS), "t1": _r(b / READ_FPS), "length": _r(length),
                        "grid": _grid(mon[a:b], rate, length)})
    rec["clips"] = sorted(clips.values(), key=lambda x: x["t0"])
    rec["dropped"] = dropped
    rec["shots"] = [{"a": s["a"], "b": s["b"], "playback": None if s.get("clip") is None else int(s["clip"])}
                    for s in shots]
    n_k = sum(len(x["kept"]) for x in rec["clips"])
    log(f"  {len(rec['clips'])} clips kept ({n_k} windows), {len(dropped)} played and dropped, "
        f"recording at {1 / rate:.1f}x")
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


def needs(row: dict, folder: Path | None = None) -> bool:
    try:
        return json.loads(((folder or OUT) / f"{row['id']}.json").read_text()).get("v") != VERSION
    except (OSError, ValueError):
        return True


# --------------------------------------------------------------------------
# a window of a clip, as either side of the pipeline sees it
# --------------------------------------------------------------------------

@dataclass
class Readings:
    """A clip's once-a-second readings on its own clock: centres k + 0.5,
    movement scaled by the clip's most (as select.busiest does)."""
    lo: float
    hi: float
    t_mot: np.ndarray
    mot: np.ndarray
    t_sub: np.ndarray
    sub: np.ndarray
    edge: np.ndarray


def readings(motion, subject, edge, lo: float, hi: float, base: float = 0.0) -> Readings | None:
    """Second k of the series is the clip moment base + k + 0.5; only the
    seconds inside lo..hi are kept."""
    t_m = np.array([base + k + 0.5 for k, v in enumerate(motion) if v is not None], dtype=np.float64)
    m = np.array([float(v) for v in motion if v is not None], dtype=np.float64)
    n = min(len(subject), len(edge))
    t_s = base + np.arange(n) + 0.5
    s = np.array([0.0 if v is None else float(v) for v in subject[:n]], dtype=np.float64)
    e = np.array([0.0 if v is None else float(v) for v in edge[:n]], dtype=np.float64)
    km, ks = (t_m >= lo) & (t_m <= hi), (t_s >= lo) & (t_s <= hi)
    t_m, m, t_s, s, e = t_m[km], m[km], t_s[ks], s[ks], e[ks]
    if len(t_s) < 1:
        return None
    if len(m):
        m = m / (m.max() + 1e-6)
    return Readings(lo, hi, t_m, m, t_s, s, e)


def _at(t: np.ndarray, x: np.ndarray, at: np.ndarray, inside: bool = False) -> np.ndarray:
    """The series read at `at` between its readings; with `inside`, NaN
    outside the first and last reading (a held end value would say "near
    the clip's start" by itself)."""
    at = np.asarray(at, dtype=np.float64)
    if not len(t):
        return np.full(at.shape, np.nan)
    v = np.interp(at, t, x)
    return np.where((at >= t[0] - 1e-9) & (at <= t[-1] + 1e-9), v, np.nan) if inside else v


def interest(R: Readings) -> tuple[np.ndarray, np.ndarray]:
    """select.busiest's interest (subject + half the movement), per second."""
    mot = _at(R.t_mot, R.mot, R.t_sub) if len(R.t_mot) else np.zeros(len(R.t_sub))
    return R.t_sub, R.sub + 0.5 * mot


def rule_start(R: Readings, w: float) -> float:
    """select.window's rule on these readings: past the clip's first
    EDGE_S, the busiest second in the middle of the window."""
    lo, hi = R.lo, R.hi
    if hi - lo >= w + EDGE_S:
        lo += EDGE_S
    a, b = lo + LEAD_IN * w, hi - (1 - LEAD_IN) * w
    ts, it = interest(R)
    ok = (ts >= a) & (ts <= b)
    t = float(ts[int(np.argmax(np.where(ok, it, -1)))]) if ok.any() else (a + b) / 2
    return float(np.clip(t - LEAD_IN * w, lo, hi - w))


def features(R: Readings, starts: np.ndarray, w: float) -> np.ndarray:
    """(n, len(NAMES)) readings of the windows starting at `starts`; NaN
    where the second around a reading isn't inside the clip."""
    s = np.asarray(starts, dtype=np.float64)
    e = s + w

    def room(at):
        return (at - 0.5 >= R.lo - 1e-9) & (at + 0.5 <= R.hi + 1e-9)

    def mot(at):
        return np.where(room(at), _at(R.t_mot, R.mot, at, inside=True), np.nan)

    def sub(x, at):
        return np.where(room(at), _at(R.t_sub, x, at, inside=True), np.nan)

    def held(t, x):
        inner = np.linspace(0, 1, 9)[None, :] * w + s[:, None]      # (n, 9) moments inside the window
        return _at(t, x, inner.ravel(), inside=True).reshape(inner.shape).mean(axis=1)   # NaN if any is

    held_m, held_s = held(R.t_mot, R.mot), held(R.t_sub, R.sub)
    ts, it = interest(R)
    top = it.max() if len(it) else 0.0
    peak = np.array([(it[(ts >= a) & (ts <= b)].max() if ((ts >= a) & (ts <= b)).any() else 0.0) / (top + 1e-6)
                     for a, b in zip(s, e)])
    cols = [mot(s - 0.5), mot(s + 0.5), mot(e - 0.5), mot(e + 0.5),
            sub(R.sub, s + 0.5), sub(R.sub, e - 0.5), sub(R.edge, s + 0.5), sub(R.edge, e - 0.5),
            held_m, held_s, peak]
    return np.stack(cols, axis=1)


def matrix(R: Readings, starts, w: float, rule: float, keep: int | None = None):
    """(starts, readings, rule score) for one choice. A reading some windows
    lack (no room for it in the clip): with `keep` (the editor's own, when
    learning) those windows are dropped if MIN_CANDS remain with the
    editor's among them -- which windows have room depends on where they
    sit, never on what's there; otherwise, and always in Make, that
    reading is left out for every window (cuts.matrix's rule)."""
    starts = np.asarray(starts, dtype=np.float64)
    X = features(R, starts, w)
    gone = np.isnan(X)
    some = gone.any(axis=0) & ~gone.all(axis=0)
    if keep is not None and some.any():
        need = some & ~gone[keep]                 # readings the editor's own window has
        ok = ~gone[:, need].any(axis=1)
        if ok.sum() >= MIN_CANDS:
            starts, X = starts[ok], X[ok]
    X[:, np.isnan(X).any(axis=0)] = 0.0
    return starts, X, -np.abs(starts - rule)


def choices(rec: dict) -> list[dict]:
    """Every kept window of a clip that had room around it -> a choice
    among the clip's other windows of its length. Windows another kept
    part of the same clip covers aren't counted against it. Not counted: a
    shot the editor sped up or slowed (its length in the clip is a guess),
    one the recording's edge cut off, and one without ROOM around it in
    what played."""
    from .cuts import creator_key
    out = []
    for cl in rec.get("clips") or []:
        L = float(cl["length"])
        g = cl.get("grid") or {}
        R = readings(g.get("motion") or [], g.get("subject") or [], g.get("edge") or [], 0.0, L)
        if R is None:
            continue
        for k in cl["kept"]:
            a, b = float(k["in"]), float(k["out"])
            w = b - a
            if not k.get("steady") or k.get("cut_off") or w < MIN_W or a < ROOM[0] or L - b < ROOM[1]:
                continue
            ts = np.round(np.arange(0.0, L - w + 1e-6, STEP), 3)
            others = [(float(o["in"]), float(o["out"])) for o in cl["kept"] if o is not k]
            ok = np.array([all(min(t + w, ob) - max(t, oa) <= 0.5 * w for oa, ob in others) for t in ts])
            ts = np.r_[a, ts[ok & (np.abs(ts - a) > 1e-6)]]           # the editor's own first
            if (np.abs(ts - a) > HIT + 1e-6).sum() < MIN_CANDS:
                continue
            rule = rule_start(R, w)
            ts, X, rs = matrix(R, ts, w, rule, keep=0)
            middle = -np.abs(ts - (L - w) / 2)
            out.append({"ts": ts, "true": a, "X": X, "rule": rs, "middle": middle, "w": w, "L": L,
                        "creator": creator_key(rec.get("creator") or rec.get("id") or ""), "id": rec.get("id")})
    return out


# --------------------------------------------------------------------------
# the scorer, tested on creators it never saw
# --------------------------------------------------------------------------

def fit(gs: list[dict], l2: float = L2) -> dict:
    from .cuts import _newton
    allx = np.vstack([g["X"] for g in gs])
    mu, sd = allx.mean(axis=0), allx.std(axis=0)
    sd[sd < 1e-9] = 1.0
    data = [((g["X"] - mu) / sd, int(np.argmin(np.abs(g["ts"] - g["true"])))) for g in gs]
    w = _newton(data, l2)
    return {"v": VERSION, "names": list(NAMES), "mean": mu.tolist(), "std": sd.tolist(), "w": w.tolist()}


def score(model: dict, X: np.ndarray) -> np.ndarray:
    return ((X - np.asarray(model["mean"])) / np.asarray(model["std"])) @ np.asarray(model["w"])


WAYS = ("model", "rule", "middle", "chance")


def evaluate(recs: list[dict], seed: int = 0) -> dict:
    from .cuts import rank
    gs = [g for r in recs for g in choices(r)]
    creators = sorted({g["creator"] for g in gs})
    for c in creators:
        train_on = [g for g in gs if g["creator"] != c]
        if not train_on:
            continue
        mdl = fit(train_on)
        for g in gs:
            if g["creator"] == c:
                g["rank"] = {"model": rank(score(mdl, g["X"]), g["ts"], g["true"]),
                             "rule": rank(g["rule"], g["ts"], g["true"]),
                             "middle": rank(g["middle"], g["ts"], g["true"]), "chance": 0.5}
    gs = [g for g in gs if "rank" in g and g["rank"]["model"] is not None]
    out = {"choices": len(gs), "creators": len({g["creator"] for g in gs}), "videos": len(recs)}
    if not gs:
        return out
    out["rank"] = {w: round(float(np.mean([g["rank"][w] for g in gs])), 4) for w in WAYS}
    best = max(("rule", "middle", "chance"), key=lambda w: out["rank"][w])
    by: dict[str, list[float]] = {}
    for g in gs:
        by.setdefault(g["creator"], []).append(g["rank"]["model"] - g["rank"][best])
    names = sorted(by)
    rng = random.Random(seed)
    diffs = []
    for _ in range(BOOT if len(names) > 1 else 0):
        pick = [by[rng.choice(names)] for _ in names]
        diffs.append(sum(map(sum, pick)) / sum(map(len, pick)))
    out["against"] = best
    out["gain"] = round(out["rank"]["model"] - out["rank"][best], 4)
    out["gain_low"] = round(float(np.percentile(diffs, 2.5)), 4) if diffs else None
    out["gain_high"] = round(float(np.percentile(diffs, 97.5)), 4) if diffs else None
    return out


def wins(rep: dict) -> bool:
    """Trusted only when it beats the best of the rule, the middle and
    chance on creators it never saw, the bootstrap's low end above zero,
    over enough creators and choices to mean something. Chance counts: a
    playback starts where the editor clicked, which can make both rules
    look worse than they are on a clip as filmed."""
    return bool(rep.get("choices", 0) >= MIN_DECISIONS and rep.get("creators", 0) >= MIN_CREATORS
                and rep.get("gain_low") is not None and rep["gain_low"] > 0)


def habits(recs: list[dict]) -> dict:
    """What the recordings show about editors' hands, whatever the scorer
    makes of it: how much of a clip they keep, and where."""
    kept_share, kept_s, where, pieces, sped = [], [], [], [], 0
    n_clips = n_drop = 0
    for r in recs:
        n_drop += len(r.get("dropped") or [])
        for cl in r.get("clips") or []:
            n_clips += 1
            L = float(cl["length"])
            ks = cl["kept"]
            pieces.append(len(ks))
            sped += sum(not k.get("steady") for k in ks)
            tot = sum(float(k["out"]) - float(k["in"]) for k in ks)
            if L > 0:
                kept_share.append(min(1.0, tot / L))
            for k in ks:
                w = float(k["out"]) - float(k["in"])
                kept_s.append(w)
                if L - w > 0.5:
                    where.append(float(k["in"]) / (L - w))
    q = lambda xs: [round(float(np.percentile(xs, p)), 3) for p in (25, 50, 75)] if xs else None
    return {"recordings": len(recs), "read": sum("error" not in r for r in recs), "clips_kept": n_clips,
            "clips_dropped": n_drop, "kept_share": q(kept_share), "kept_s": q(kept_s), "where": q(where),
            "two_or_more": round(float(np.mean([p >= 2 for p in pieces])), 3) if pieces else None,
            "speed_changed": sped}


def train(folder: Path | None = None, model_path: Path | None = None, report_path: Path | None = None,
          log=print) -> dict | None:
    folder, model_path, report_path = folder or OUT, model_path or MODEL, report_path or REPORT
    recs = load_records(folder)
    if not recs:
        log(f"no records in {folder}: run `python -m taste.collect --only tutorials` on the Mac first")
        return None
    rep = evaluate(recs)
    gs = [g for r in recs for g in choices(r)]
    model = fit(gs) if gs else {"v": VERSION, "names": list(NAMES)}
    model.update(trained=time.strftime("%Y-%m-%d"), report=rep, habits=habits(recs), trusted=wins(rep))
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
    rep, h = model.get("report") or {}, model.get("habits") or {}
    lines = [f"# Where editors cut inside a clip, from {h.get('read', 0)} of {h.get('recordings', 0)} "
             f"screen recordings ({model.get('trained', '')})", ""]
    if h.get("clips_kept"):
        ks, kw, wh = h.get("kept_share") or [None] * 3, h.get("kept_s") or [None] * 3, h.get("where") or [None] * 3
        lines += [f"- {h['clips_kept']} clips kept, {h['clips_dropped']} played and dropped.",
                  f"- Of a clip they played, editors kept {_pct(ks[1])} (half the clips between "
                  f"{_pct(ks[0])} and {_pct(ks[2])}); a kept window ran {kw[1]:.1f} s (median).",
                  f"- {_pct(h.get('two_or_more'))} of kept clips gave two windows or more; "
                  f"{h.get('speed_changed', 0)} windows were sped up or slowed.",
                  f"- Where the window started, from 0 (the clip's start) to 1 (its end): median {wh[1]}, "
                  f"quartiles {wh[0]}-{wh[2]}. Only a hint: a playback starts and stops where the editor clicked.",
                  ""]
    if rep.get("choices"):
        r = rep["rank"]
        lines += [f"On {rep['choices']} choices by {rep['creators']} creators the scorer never saw, how often the "
                  "editor's own window ranks above another more than 0.3 s away (50% = chance):",
                  f"- scorer {_pct(r['model'])}, Make's rule {_pct(r['rule'])}, the clip's middle {_pct(r['middle'])}",
                  f"- against the better of those ({rep['against']}): {100 * rep['gain']:+.1f} points, "
                  f"95% from {100 * (rep.get('gain_low') or 0):+.1f} to {100 * (rep.get('gain_high') or 0):+.1f}",
                  f"- trusted in Make: {'yes' if model.get('trusted') else 'no'} (needs {MIN_CREATORS}+ creators, "
                  f"{MIN_DECISIONS}+ choices and the low end above zero)", ""]
        if model.get("w"):
            w = np.asarray(model["w"])
            order = np.argsort(-np.abs(w))[:4]
            lines.append("Leans: " + "; ".join(f"{SAY[NAMES[i]]} {w[i]:+.2f}" for i in order))
    else:
        lines.append("No window had room around it to learn from yet.")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Make: where in a clip to take a window
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
        _cache.update(at=(str(path), st), model=m if m and m.get("v") == VERSION and m.get("w") else None)
    return _cache["model"]


def place(rec: dict, start: float, end: float, want: float, lo: float, hi: float, around: float | None = None,
          model: dict | None = None) -> float | None:
    """Where a `want`-second window of the clip shot start..end should
    begin, within lo..hi, as the editors in the recordings would take it
    (their scorer over the clip's index readings), among the windows with
    every reading around them. `around`: the rule's own start, kept on a
    tie. None when the scorer isn't trusted, there's no choice, or the
    clip has no readings."""
    mdl = model if model is not None else load()
    if not mdl or not mdl.get("trusted") or hi - lo < want + STEP - 1e-9:
        return None
    sig = rec.get("signals") or {}
    mo, su, ed = sig.get("motion") or [], sig.get("subject") or [], sig.get("edge") or []
    n = min(len(mo), len(su), len(ed))
    # the index's first second copies the second's movement (nothing a second earlier to
    # compare with); the recordings have none there, and neither does this
    R = readings([None, *mo[1:n]] if n else [], su[:n], ed[:n], float(start), float(end))
    if R is None:
        return None
    rule = float(around) if around is not None else rule_start(R, want)
    starts = np.round(np.arange(lo, hi - want + 1e-6, STEP), 3)
    starts = np.unique(np.append(starts, round(float(np.clip(rule, lo, hi - want)), 3)))
    X = features(R, starts, want)
    # only windows it can read whole, as every window it learnt from was (ROOM); a clip
    # too short for one is left to the rule
    whole = ~np.isnan(X[:, ~np.isnan(X).all(axis=0)]).any(axis=1)
    if whole.sum() < 2:
        return None
    starts, X = starts[whole], np.nan_to_num(X[whole])
    sc = score(mdl, X) - 1e-6 * np.abs(starts - rule)              # a tie keeps the rule's choice
    return float(starts[int(np.argmax(sc))])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m taste.tutorial")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("train", help="test on unseen creators against Make's rule, then fit on all")
    rd = sub.add_parser("read", help="read one screen recording into a record (prints a summary)")
    rd.add_argument("path")
    rd.add_argument("--final", help="the finished vlog, when it's a file of its own")
    rd.add_argument("--id", default="T000")
    rd.add_argument("--creator", default="someone")
    rd.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "read":
        rec = read_video(a.path, id=a.id, creator=a.creator, final_path=a.final)
        print(f"{len(choices(rec))} choices to learn from")
        if a.save:
            save(rec, OUT / f"{a.id}.json")
        return
    train()


if __name__ == "__main__":
    main()
