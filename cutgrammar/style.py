"""Learn the craft of an edit someone admires, as numbers.

A creator says "I want it to feel like *that* video". What they are
pointing at is mostly decisions an editor made, and those are measurable:
how long shots are held and whether that quickens towards the end; how
one shot becomes the next (a hard cut, a dissolve, a dip to black, a white
flash); whether the cuts land on the music's beat; the grade; the frame.
None of that is the reference's footage, music or words -- only its habits.
The creator's own frames are the only ones that ever reach their video.

`learn()` measures those habits on the same 48x27 arrays as every grammar
rule. Each trait names the evidence it rests on (evidence.py): transitions
and beat alignment need every frame, so on a keyframe-only reading they
come back pending rather than guessed. Every threshold that turns a number
into a word is a first guess, uncalibrated, like the rest of cutgrammar.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from . import evidence, features, grade, music
from . import shots as shots_mod
from .media import Media

VERSION = 2          # 2: opening, ending, words

# transitions
DARK = 6.0             # mean luma below this is black (a fade reaches true black; a night shot rarely does)
BRIGHT = 238.0         # above this is a white flash
MAX_DIP_S = 2.0        # longer than this, a black stretch is a shot, not a transition
MAX_FLASH_S = 0.6
MAX_SLUG_S = 0.5       # a hard cut to black and back is a dip only if this short
RAMP_S = 1.5           # how far a fade's ramp is followed either side
RAMP_STEP = 1.0        # luma change per frame that still counts as ramping (above codec noise)
MIN_RAMP = 3           # frames of ramp that make a fade, not a cut
LIFTED_BLACK = 48.0    # a flat frame darker than this is black in a graded edit
BLANK_CHROMA = 64.0    # ...if its channels are this close: a teal-graded black is ~50, a navy card ~128
DISSOLVE_S = (0.3, 0.5, 0.8, 1.2)
DISSOLVE_RESID = 0.55  # how far mid-frames may sit from a straight blend of the ends
                       # (handheld footage keeps moving during a dissolve)
DISSOLVE_MIN_DIFF = 25.0  # mean pixel change across the window for a candidate
# Where the halfway frame's contrast sits between its ends' (0) and the
# exact blend's (1). On real footage 27 of 28 dissolves scored >= 0.6.
DISSOLVE_BLEND_SCORE = 0.6
MIN_BLEND_DROP = 0.06     # below this the two ends blend invisibly; no call
FLAT = 4.0                # luma std below this is a flat frame
FLAT_RESID = 0.15
HABIT_SHARE = 0.15        # a soft transition is a habit only above this share of joins
DISSOLVE_MIN_MID = 0.1  # seconds of in-between frames a dissolve must show
DISSOLVE_MAX_STEP = 0.3 # no single frame may carry more of the change than this
# Luma layouts this correlated are one shot, not two. Set on real handheld
# footage (tests/test_style.py, VIBECUT_REAL_CLIPS): real dissolves between
# two clips mostly correlate <= 0.37 end to end, camera moves inside a shot
# mostly >= 0.5; at 0.5, 23 of 27 real dissolves are kept and 20 of 23 moves
# rejected. The moves that get through are why a habit needs HABIT_SHARE.
SAME_PICTURE_R = 0.5

# beat alignment
ONSET_HOP_S = 0.01
BEAT_TOL_S = 0.06      # a cut within this of an onset is "on" it
ON_BEAT_HIT = 0.45     # guesses: share of cuts on a beat, and how far above chance
ON_BEAT_LIFT = 1.8

PACE_BINS = 5
MUSIC_POINTS = 32


# --------------------------------------------------------------------------
# transitions
# --------------------------------------------------------------------------

def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) of each run of True."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def blank(media: Media) -> tuple[np.ndarray, np.ndarray]:
    """Per frame: is it a black frame, a white frame?

    Black is below DARK -- or, in a graded edit whose blacks are lifted, a
    dark frame with nothing in it: a dip to black bottoms out at the
    grade's black, which can be luma 20+, but it is still flat. Letterbox
    rows are left out; they are flat in every frame.
    """
    top, bottom = letterbox(media.frames)
    f = media.frames[:, top:media.frames.shape[1] - bottom].astype(np.float32)
    y = f @ grade.LUMA.astype(np.float32)
    mean = y.mean(axis=(1, 2))
    rgb = f.mean(axis=(1, 2))
    # flat, and near grey: a graded black is tinted a little, a navy title card a lot
    flat = (y.reshape(len(y), -1).std(axis=1) < FLAT) & (rgb.max(axis=1) - rgb.min(axis=1) < BLANK_CHROMA)
    dark = min(DARK, 0.35 * float(np.median(mean))) if len(mean) else DARK
    return (mean < dark) | ((mean < LIFTED_BLACK) & flat), (mean > BRIGHT) | ((mean > 200) & flat)


def _dips(b: np.ndarray, fps: float, black: np.ndarray, white: np.ndarray) -> list[dict]:
    """Fades through black and white flashes, from mean brightness alone.

    A fade is recognised by where it bottoms out, then followed outwards
    while the brightness keeps ramping, so its length is the whole ramp,
    not just the black frames. A dark *shot* also bottoms out, but it is
    cut to and from: with no ramp on either side, only a short black slug
    counts as a dip.
    """
    n, out = len(b), []
    ramp = max(1, int(RAMP_S * fps))
    for a, z in _runs(black):
        if (z - a) / fps > MAX_DIP_S and 0 < a and z < n:
            continue
        s = a
        while s > 0 and a - s < ramp and b[s - 1] > b[s] + RAMP_STEP:
            s -= 1
        e = z
        while e < n and e - z < ramp and b[e] > b[e - 1] + RAMP_STEP:
            e += 1
        # a hard cut is a one-frame "ramp"
        if a - s < MIN_RAMP and e - z < MIN_RAMP and (z - a) / fps > MAX_SLUG_S and 0 < a and z < n:
            continue
        if a == 0:
            if z < n:
                out.append({"kind": "fade_in", "t": 0.0, "dur": round(e / fps, 3)})
            continue
        if z >= n:
            out.append({"kind": "fade_out", "t": round(n / fps, 3), "dur": round((n - s) / fps, 3)})
            continue
        out.append({"kind": "dip_black", "t": round((a + z) / 2 / fps, 3),
                    "dur": round((e - s) / fps, 3), "_span": (s, e)})
    for a, z in _runs(white):
        if (z - a) / fps > MAX_FLASH_S or a == 0 or z >= n:
            continue
        if b[max(0, a - 2)] < b[a] - 30 and b[min(n - 1, z + 1)] < b[z - 1] - 30:
            out.append({"kind": "flash", "t": round((a + z) / 2 / fps, 3),
                        "dur": round((z - a) / fps, 3), "_span": (a, z)})
    return out


def _same_picture(a: np.ndarray, b: np.ndarray) -> bool:
    """Do two flattened 48x27 RGB frames show the same layout of light and dark?"""
    ya = a.reshape(-1, 3) @ grade.LUMA
    yb = b.reshape(-1, 3) @ grade.LUMA
    if ya.std() < 1e-3 or yb.std() < 1e-3:
        return False
    return float(np.corrcoef(ya, yb)[0, 1]) > SAME_PICTURE_R


def _blend(f: np.ndarray, y: np.ndarray, i: int, L: int, fps: float) -> dict | None:
    """Is the window f[i] .. f[i+L] a dissolve? The reading if so, else None."""
    A, B = f[i], f[i + L]
    # Walking into the light or an exposure ramp is also a blend of its
    # ends -- but of the same picture. A dissolve joins two.
    if _same_picture(A, B):
        return None
    d = B - A
    nn = float(d @ d)
    mids = f[i + 1: i + L]
    alpha = (mids - A) @ d / nn
    resid = float((np.linalg.norm(mids - A - alpha[:, None] * d, axis=1) / np.sqrt(nn)).mean())
    # Handheld drift either side of a hard cut fits loosely too, but its
    # alpha still jumps at the cut; a dissolve's passes through the middle.
    moving = np.flatnonzero((alpha > 0.1) & (alpha < 0.9))
    steps = np.diff(np.concatenate([[0.0], alpha, [1.0]]))
    if not (len(moving) >= DISSOLVE_MIN_MID * fps and steps.min() > -0.08
            and steps.max() < DISSOLVE_MAX_STEP and resid < DISSOLVE_RESID):
        return None
    # Halfway through a dissolve the frame *is* A/2 + B/2, and an average of
    # two pictures has less contrast than either -- exactly how much less is
    # computable from A and B. A camera move keeps its ends' contrast (a
    # little less, from blur). So: where does the halfway frame sit, from
    # "like its ends" (0) to "exactly the blend" (1)? Flat frames have no
    # contrast to lose; there only a near-perfect blend counts.
    k = i + 1 + int(np.argmin(np.abs(alpha - 0.5)))
    sa, sb = float(y[i].std()), float(y[i + L].std())
    if min(sa, sb) < FLAT:
        if resid > FLAT_RESID:
            return None
    else:
        ends = (sa + sb) / 2
        blend = float((0.5 * y[i] + 0.5 * y[i + L]).std())
        if (ends - blend) / ends < MIN_BLEND_DROP:
            return None   # these two would blend without a trace: can't tell
        if (ends - float(y[k].std())) / (ends - blend) < DISSOLVE_BLEND_SCORE:
            return None
    # Length from the 10-90% rise, scaled to the whole: the tails of the
    # ramp drown in handheld drift and would make every dissolve read long.
    inner = np.flatnonzero((alpha > 0.1) & (alpha < 0.9))
    span = (inner[-1] - inner[0] + 2) / fps / 0.8
    return {"kind": "dissolve", "t": round(k / fps, 3), "dur": round(span, 3),
            "_span": (i + int(inner[0]), i + int(inner[-1]) + 2), "_fit": (span, -resid),
            # saw the whole ramp, settled frames either side of it
            "_whole": bool(alpha.min() < 0.1 and alpha.max() > 0.9)}


def _dissolves(frames: np.ndarray, fps: float, dark: np.ndarray) -> list[dict]:
    """Cross-dissolves: windows whose middle frames are blends of their ends.

    The shot detector only sees hard cuts; a dissolve changes the picture
    as much, but spread over many frames. So: find windows whose ends
    differ a lot, then keep those whose middle frames really are
    A*(1-a) + B*a with a rising through the middle (`_blend`) -- a camera
    move changes the picture gradually too, but is not a blend of its ends.
    """
    n = len(frames)
    if n < 8:
        return []
    f = frames.reshape(n, -1).astype(np.float32)
    y = f.reshape(n, -1, 3) @ grade.LUMA.astype(np.float32)
    found = []
    for secs in DISSOLVE_S:
        L = int(round(secs * fps))
        if L < 4 or L >= n - 1:
            continue
        change = np.abs(f[L:] - f[:-L]).mean(axis=1)                 # pixels, i -> i+L
        blacks = sliding_window_view(dark, L + 1).any(axis=1)[: len(change)]
        # Handheld footage changes this much almost everywhere, so a run
        # of candidates can hold several dissolves: every window is judged.
        for i in np.flatnonzero((change > DISSOLVE_MIN_DIFF) & ~blacks)[:: max(1, L // 4)]:
            hit = _blend(f, y, int(i), L, fps)
            if hit:
                found.append(hit)
    # The same dissolve fits several windows. One shorter than the dissolve
    # sees only part of it, so the longest measured span wins.
    found.sort(key=lambda x: x["_fit"], reverse=True)
    keep: list[dict] = []
    for x in found:
        if all(abs(x["t"] - k["t"]) > max(x["dur"], k["dur"]) / 2 + 0.1 for k in keep):
            keep.append(x)
    # Its length is the median over every window that fit it: one long
    # window stretched by drift shouldn't set it.
    for k in keep:
        near = [x for x in found if abs(x["t"] - k["t"]) <= k["dur"] / 2]
        whole = [x["dur"] for x in near if x["_whole"]] or [x["dur"] for x in near]
        k["dur"] = round(float(np.median(whole)), 3)
    return sorted(keep, key=lambda x: x["t"])


def transitions(media: Media, shot_list: list[shots_mod.Shot] | None = None) -> list[dict]:
    """Every boundary between two shots, with what kind it is.

    [{kind: cut | dissolve | dip_black | flash | fade_in | fade_out, t, dur}]
    """
    fps = media.fps or 30.0
    sh = shot_list if shot_list is not None else shots_mod.detect(media)
    b = features.brightness(media)
    black, white = blank(media)
    special = _dips(b, fps, black, white)
    if media.n_frames > 1:
        dark = black
        # Letterbox bars are identical in every shot; left in, they make
        # any two shots look like the same picture.
        top, bottom = letterbox(media.frames)
        pic = media.frames[:, top:media.frames.shape[1] - bottom]
        special += _dissolves(pic, fps, dark)

    def inside(t: float, x: dict) -> bool:
        if "_span" not in x:
            return False
        s, e = x["_span"]
        return s / fps - 0.1 <= t <= e / fps + 0.1

    # Half of a fade to black is a blend of a shot and a darker frame, so
    # it also fits the dissolve model; the dip is the truer reading.
    dips = [x for x in special if x["kind"] != "dissolve"]
    special = dips + [x for x in special if x["kind"] == "dissolve"
                      and not any(inside(x["t"], y) for y in dips)]
    cuts = [{"kind": "cut", "t": round(s.start_t, 3), "dur": 0.0} for s in sh[1:]
            if not any(inside(s.start_t, x) for x in special)]
    out = sorted(cuts + special, key=lambda x: x["t"])
    for x in out:
        for k in ("_span", "_fit", "_whole"):
            x.pop(k, None)
    return out


def transition_style(trans: list[dict]) -> dict:
    """Counts, shares and typical lengths -- the habit, not the instances."""
    between = [x for x in trans if x["kind"] not in ("fade_in", "fade_out")]
    kinds = ("cut", "dissolve", "dip_black", "flash")
    counts = {k: sum(x["kind"] == k for x in between) for k in kinds}
    total = max(1, len(between))
    dur = {k: round(float(np.median([x["dur"] for x in between if x["kind"] == k])), 3)
           for k in kinds[1:] if counts[k]}
    share = {k: round(counts[k] / total, 3) for k in kinds}
    opens = any(x["kind"] == "fade_in" for x in trans)
    closes = any(x["kind"] == "fade_out" for x in trans)
    w = []
    soft = 1.0 - share["cut"]
    if not between:
        w.append("one continuous shot")
    elif max(share[k] for k in kinds[1:]) < HABIT_SHARE:
        w.append("hard cuts only")
    else:
        main = max(kinds[1:], key=lambda k: counts[k])
        name = {"dissolve": "dissolves", "dip_black": "dips to black", "flash": "white flashes"}[main]
        w.append(f"mostly {name}" if share[main] >= 0.5 else f"hard cuts, with {name} ({counts[main]} of {len(between)})")
    if opens:
        w.append("opens from black")
    if closes:
        w.append("fades out at the end")
    return {"counts": counts, "share": share, "dur": dur, "open": opens, "close": closes,
            "words": w}


# --------------------------------------------------------------------------
# pace
# --------------------------------------------------------------------------

def boundaries(trans: list[dict]) -> list[float]:
    return [x["t"] for x in trans if x["kind"] not in ("fade_in", "fade_out")]


def pace(duration: float, bounds: list[float]) -> dict:
    """How long shots are held, and how that changes through the video.

    `curve` is the median shot length in each fifth of the video relative
    to the overall median: [1.5, 1.2, 1, 0.8, 0.6] is an edit that
    quickens -- the most common arc in a travel montage.
    """
    edges = np.array([0.0, *sorted(t for t in bounds if 0 < t < duration), duration])
    lens = np.diff(edges)
    lens = lens[lens > 1e-3]
    if len(lens) == 0:
        return {}
    med = float(np.median(lens))
    mids = (edges[:-1] + edges[1:])[: len(lens)] / 2 / max(duration, 1e-9)
    curve = []
    for k in range(PACE_BINS):
        sel = (mids >= k / PACE_BINS) & (mids < (k + 1) / PACE_BINS)
        curve.append(float(np.median(lens[sel])) / med if sel.any() else np.nan)
    curve = np.array(curve)
    if np.isnan(curve).all():
        curve = np.ones(PACE_BINS)
    ok = ~np.isnan(curve)
    curve = np.interp(np.arange(PACE_BINS), np.flatnonzero(ok), curve[ok])
    trend = float(np.log(np.mean(curve[-2:]) / np.mean(curve[:2])))
    cv = float(lens.std() / (lens.mean() + 1e-9))
    per_min = 60.0 * len(lens) / max(duration, 1e-9)
    w = [f"about {med:.1f} s a shot" if med < 10 else f"long takes (about {med:.0f} s)"]
    # the median, not cuts per minute: one long take shouldn't make a
    # quick edit read as slow
    w.append("quick cutting" if med < 1.5 else "slow, lingering" if med > 6 else "steady pace")
    if trend < -0.25:
        w.append("speeds up towards the end")
    elif trend > 0.25:
        w.append("slows down towards the end")
    if len(lens) >= 3 and cv < 0.35:
        w.append("even, metronomic rhythm")
    return {"shots": int(len(lens)), "per_min": round(per_min, 2), "median_s": round(med, 3),
            "p10_s": round(float(np.percentile(lens, 10)), 3),
            "p90_s": round(float(np.percentile(lens, 90)), 3), "cv": round(cv, 3),
            "first_s": round(float(lens[0]), 3), "curve": [round(float(c), 3) for c in curve],
            "trend": round(trend, 3), "words": w}


# --------------------------------------------------------------------------
# beat alignment and music feel
# --------------------------------------------------------------------------

def onsets(media: Media) -> np.ndarray:
    """Times (s) where energy appears in the sound -- hits, not level."""
    env = features.spectral_flux(media, ONSET_HOP_S).astype(np.float64)
    if env.size < 10:
        return np.zeros(0)
    local = np.convolve(env, np.ones(50) / 50, mode="same")
    env = np.maximum(env - local, 0)
    if env.max() <= 0:
        return np.zeros(0)
    thr = np.percentile(env[env > 0], 80) if (env > 0).any() else 0
    gap = int(0.1 / ONSET_HOP_S)
    peaks, last = [], -gap
    for i in range(1, len(env) - 1):
        if env[i] > thr and env[i] >= env[i - 1] and env[i] >= env[i + 1] and i - last >= gap:
            peaks.append(i)
            last = i
    # flux fires as a hit enters the analysis window; label by its centre
    # (the same correction music.estimate_bpm makes)
    win_s = max(int(16000 * ONSET_HOP_S) * 4, 512) / 16000
    return np.array(peaks) * ONSET_HOP_S + win_s / 2


def beat_sync(media: Media, bounds: list[float], on: np.ndarray | None = None) -> dict | None:
    """Do the cuts land on the music's beat?

    Only a steady tempo can answer this. Onsets alone can't: when sound is
    cut together with picture, every cut makes its own onset (the very
    habit check_jl_cuts measures), so "cuts land on onsets" is true of any
    hard-synced edit. So the claim rests on the beat grid: the share of cuts
    within BEAT_TOL_S of a beat, against the share of all moments that are
    (`chance`). Onset numbers are kept alongside, as information only.
    """
    if not media.has_audio or len(bounds) < 3:
        return None
    on = onsets(media) if on is None else on
    cuts = np.asarray(bounds)
    out: dict = {"bpm": None, "on_grid": None, "chance": None, "lift": None, "beats_per_shot": None}
    if len(on):
        near = np.min(np.abs(cuts[:, None] - on[None, :]), axis=1)
        out["onset_hit"] = round(float(np.mean(near < BEAT_TOL_S)), 3)
    bpm, info = music.estimate_bpm(media)
    if not bpm or info.get("phase") is None:
        out["cuts_on_beat"] = False
        out["words"] = ["no steady beat to cut to"]
        return out
    period = 60.0 / bpm
    ph = (cuts - info["phase"]) / period
    on_grid = float(np.mean(np.abs(ph - np.round(ph)) * period < BEAT_TOL_S))
    chance = min(1.0, 2 * BEAT_TOL_S / period)
    lens = np.diff(np.concatenate([[0.0], cuts]))
    out.update(bpm=bpm, phase=info["phase"], on_grid=round(on_grid, 3), chance=round(chance, 3),
               lift=round(on_grid / chance, 2), beats_per_shot=round(float(np.median(lens) / period), 2))
    out["cuts_on_beat"] = bool(on_grid >= ON_BEAT_HIT and on_grid / chance >= ON_BEAT_LIFT)
    if out["cuts_on_beat"]:
        bps = out["beats_per_shot"]
        out["words"] = ["cuts land on the beat",
                        f"about {bps:.0f} beats a shot" if bps >= 1.5 else "a cut on almost every beat"]
    else:
        out["words"] = [f"cuts ignore the {bpm:.0f} BPM beat"]
    return out


def arc_of(curve) -> str:
    """The shape of a 0..1 energy curve, in words the music search knows."""
    thirds = [float(np.mean(c)) for c in np.array_split(np.asarray(curve, dtype=np.float64), 3)]
    if thirds[2] - thirds[0] > 0.2:
        return "builds"
    if thirds[0] - thirds[2] > 0.2:
        return "winds down"
    if thirds[1] - max(thirds[0], thirds[2]) > 0.15:
        return "peaks in the middle"
    return "steady"


def music_feel(media: Media) -> dict | None:
    """The music's energy arc and tempo -- what to look for in the creator's
    own library, never the track itself."""
    if not media.has_audio:
        return None
    e = music.energy_curve(media)
    if len(e) < 4:
        return None
    bpm, _ = music.estimate_bpm(media)
    curve = music._resample(e.astype(np.float64), MUSIC_POINTS)
    arc = arc_of(curve)
    w = [f"{arc} energy"]
    if bpm:
        w.append(f"a steady beat around {bpm:.0f} BPM"
                 + (" (upbeat)" if bpm >= 115 else " (relaxed)" if bpm < 90 else ""))
    else:
        w.append("no steady beat")
    bright = music.brightness(media)
    if bright:
        w.append("a bright, airy sound" if bright > 2500 else "a warm, low sound" if bright < 1200 else "a full, even sound")
    return {"bpm": bpm, "energy": [round(float(x), 3) for x in curve], "arc": arc, "bright": bright, "words": w}


# --------------------------------------------------------------------------
# frame and look
# --------------------------------------------------------------------------

def letterbox(frames: np.ndarray) -> tuple[int, int]:
    """Black bars top and bottom, in 48x27 rows. A row is a bar if it is
    black in nearly every frame -- dark scenes come and go, bars don't."""
    if len(frames) == 0:
        return 0, 0
    y = grade._luma(frames.astype(np.float64).reshape(-1, 3)).reshape(frames.shape[:3])
    black = (y.mean(axis=2) < 16).mean(axis=0) > 0.95        # per row
    H = len(black)
    top = 0
    while top < H // 3 and black[top]:
        top += 1
    bottom = 0
    while bottom < H // 3 and black[H - 1 - bottom]:
        bottom += 1
    if top + bottom < 2:
        return 0, 0
    return top, bottom


def frame_style(media: Media, bars: tuple[int, int]) -> dict:
    w, h = media.width or 16, media.height or 9
    rot = media.meta.get("rotation", 0) if media.meta else 0
    if rot in (90, 270):
        w, h = h, w
    H = media.frames.shape[1] if media.n_frames else 27
    visible = (H - sum(bars)) / H
    aspect = round(w / (h * visible), 2) if visible > 0 else None
    out = {"vertical": h > w, "aspect": round(w / h, 3), "bars": list(bars),
           "letterbox": aspect if sum(bars) else None}
    words = ["vertical (9:16)" if h > w else "horizontal"]
    if out["letterbox"]:
        words.append(f"cinematic bars ({out['letterbox']:.2f}:1)")
    out["words"] = words
    return out


def look(media: Media, bars: tuple[int, int], skip: np.ndarray | None = None) -> dict:
    frames = media.frames if skip is None else media.frames[~skip]
    s = grade.stats(grade.pixels(frames, bars=bars))
    return {**s, "words": grade.words(s)} if s else {}


# --------------------------------------------------------------------------

NEEDS = {
    "opening": [evidence.MOTION],
    "ending": [evidence.MOTION],
    "words": [evidence.STILL],
    "pace": [evidence.STILL],
    "transitions": [evidence.MOTION],
    "beat": [evidence.MOTION, evidence.AUDIO],
    "music": [evidence.AUDIO],
    "look": [evidence.STILL],
    "frame": [evidence.META, evidence.STILL],
}


# --------------------------------------------------------------------------
# the reel's ideas: where its words sit and for how long, how it opens, how
# it ends. Rhythm alone (pace, beat, look) made a copy that marched like the
# reference and said nothing like it (2026-10-18).
# --------------------------------------------------------------------------

TEXT_BANDS = ((0.0, 0.33, "bottom"), (0.33, 0.66, "middle"), (0.66, 1.01, "top"))   # of frame height, origin bottom
TEXT_MIN_CONF = 0.3
EDGE_S = 2.0              # the opening and the ending are judged on their first / last two seconds


def text_style(events: list[dict], duration: float) -> dict | None:
    """`events` = [{"t": s, "items": [{"text", "box": [x, y, w, h], "conf"}]}] at a
    steady sample rate -> when and where a reel puts words on screen."""
    if not events:
        return None
    ts = sorted(e["t"] for e in events)
    step = float(np.median(np.diff(ts))) if len(ts) > 1 else 0.5
    on = []
    bands = {"bottom": 0, "middle": 0, "top": 0}
    heights, cards_words, letters, upper = [], [], 0, 0
    samples: list[str] = []            # the reel's own lines, a few, for the writer's ear
    for e in sorted(events, key=lambda e: e["t"]):
        items = [i for i in e.get("items", []) if i.get("conf", 1) >= TEXT_MIN_CONF and i.get("text", "").strip()]
        on.append(bool(items))
        for i in items:
            x, y, w, h = i["box"]
            cy = y + h / 2
            for lo, hi, name in TEXT_BANDS:
                if lo <= cy < hi:
                    bands[name] += 1
            heights.append(h)
            cards_words.append(len(i["text"].split()))
            line = " ".join(i["text"].split())
            if 2 <= len(line) <= 48 and line.lower() not in {x.lower() for x in samples} and len(samples) < 12:
                samples.append(line)
            for ch in i["text"]:
                if ch.isalpha():
                    letters += 1
                    upper += ch.isupper()
    on_arr = np.array(on, dtype=bool)
    # the recogniser misses a frame now and then; a one-sample hole inside a
    # caption is the same caption, not two short ones (held 0.8 s read on a
    # reel whose captions plainly held 2–3 s, 2026-10-18)
    if len(on_arr) > 2:
        holes = (~on_arr[1:-1]) & on_arr[:-2] & on_arr[2:]
        on_arr[1:-1] |= holes
    runs = _runs(on_arr)
    share = float(on_arr.mean())
    if share == 0:
        return {"share": 0.0, "first_s": None, "band": None, "hold_s": None, "cards": 0, "upper": None,
                "size": None, "words_per_card": None, "words": ["no words on screen"]}
    first = float(ts[int(np.flatnonzero(on_arr)[0])])
    hold = float(np.median([(b - a) * step for a, b in runs])) if runs else step
    band = max(bands, key=bands.get)
    up = upper / letters if letters else 0.0
    words = [f"words on screen {share:.0%} of the time", f"usually at the {band}", f"each held about {hold:.1f} s"]
    words.append("first words at the start" if first <= 1.0 else f"first words at {first:.0f} s")
    if up > 0.8:
        words.append("ALL CAPS")
    return {"share": round(share, 3), "first_s": round(first, 2), "band": band, "hold_s": round(hold, 2),
            "cards": len(runs), "upper": round(up, 2), "size": round(float(np.median(heights)), 3),
            "words_per_card": round(float(np.median(cards_words)), 1), "samples": samples,
            "bands": {k: round(v / max(1, sum(bands.values())), 2) for k, v in bands.items()}, "words": words}


def _motion_per_s(media: Media) -> np.ndarray:
    f = media.frames.astype(np.float32)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2, 3)) if len(f) > 1 else np.zeros(1)
    fps = int(round(media.fps or 30))
    n = max(1, len(d) // fps)
    return np.array([d[k * fps:(k + 1) * fps].mean() for k in range(n)])


def opening(media: Media, bounds: list[float]) -> dict:
    """How the reel opens: how long before the first cut, and whether the
    first seconds move more than the rest (a hook on action)."""
    m = _motion_per_s(media)
    k = max(1, int(EDGE_S))
    ratio = float(m[:k].mean() / (m.mean() + 1e-6)) if len(m) else 1.0
    first_cut = float(min(bounds)) if bounds else media.duration
    words = [f"first cut at {first_cut:.1f} s", "opens on action" if ratio > 1.25 else "opens still" if ratio < 0.75 else "opens at its own pace"]
    return {"first_cut_s": round(first_cut, 2), "motion_ratio": round(ratio, 2), "words": words}


def ending(media: Media, bounds: list[float], trans: list[dict]) -> dict:
    """How the reel ends: the last shot's length, whether it fades, whether
    the last seconds calm down or keep moving."""
    inside = [b for b in bounds if 0 < b < media.duration]
    last = media.duration - (max(inside) if inside else 0.0)
    m = _motion_per_s(media)
    k = max(1, int(EDGE_S))
    ratio = float(m[-k:].mean() / (m.mean() + 1e-6)) if len(m) else 1.0
    fades = any(x["kind"] == "fade_out" for x in trans)
    words = [f"last shot held {last:.1f} s", "fades out" if fades else "ends on a cut",
             "ends still" if ratio < 0.75 else "ends on action" if ratio > 1.25 else "ends at its own pace"]
    return {"last_s": round(last, 2), "fade_out": fades, "motion_ratio": round(ratio, 2), "words": words}


def learn(media: Media, shot_list: list[shots_mod.Shot] | None = None, text: list[dict] | None = None) -> dict:
    """Everything a reference video can teach, each trait with its evidence.
    `text` = sampled words-on-screen events (web/backend/vision.text over
    frames of the source), when the Mac's Vision could read them."""
    have = evidence.available(media)
    sh = shot_list if shot_list is not None else shots_mod.detect(media)
    trans = transitions(media, sh)
    bounds = boundaries(trans)
    fps = media.fps or 30.0
    # Frames inside a dip, flash or fade are the transition, not the grade.
    black, white = blank(media)
    skip = black | white
    for x in trans:
        if x["kind"] in ("dip_black", "flash", "fade_in", "fade_out"):
            a = int(max(0.0, x["t"] - (x["dur"] if x["kind"] == "fade_out" else x["dur"] / 2)) * fps)
            z = int((x["t"] + (x["dur"] if x["kind"] == "fade_in" else x["dur"] / 2)) * fps) + 1
            skip[a:z] = True
    bars = letterbox(media.frames)

    traits = {
        "pace": pace(media.duration, bounds) or None,
        "transitions": {**transition_style(trans), "list": trans[:300]},
        "beat": beat_sync(media, bounds),
        "music": music_feel(media),
        "look": look(media, bars, skip) or None,
        "frame": frame_style(media, bars),
        "opening": opening(media, bounds),
        "ending": ending(media, bounds, trans),
        "words": text_style(text, media.duration) if text is not None else None,
    }
    for k, v in traits.items():
        if v is None:
            if k == "words":
                traits[k] = {"pending": ["vision"], "evidence": [evidence.STILL],
                             "words": ["not checked — reading words on screen needs the Mac's Vision"]}
            continue
        lacking = evidence.missing(NEEDS[k], have)
        v["evidence"] = list(NEEDS[k])
        if lacking:
            v["pending"] = lacking
            v["words"] = [f"not checked — needs {evidence.describe(lacking)}"]
    return {"version": VERSION, "duration": round(media.duration, 3), "fps": round(fps, 3),
            "width": media.width, "height": media.height, "have": sorted(have), **traits}


def summary(style: dict) -> list[str]:
    """One line per trait, for a terminal or a card."""
    out = []
    for k in ("pace", "transitions", "beat", "music", "look", "frame", "opening", "ending", "words"):
        v = style.get(k)
        if v and v.get("words"):
            out.append(f"{k:<12} " + ", ".join(v["words"]))
    return out
