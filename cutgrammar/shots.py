"""Shot boundary detection.

Histogram-distance with an adaptive threshold -- the same family as
PySceneDetect, which is what the tech plan calls for in v1. Hard cuts are
what vlogs are made of, and this catches them without a GPU or a model
download. Gradual transitions (dissolves, fades) are the known blind spot;
TransNetV2 is the upgrade path when they start to matter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .features import luma
from .media import Media

BINS = 8  # per channel -> 512-bin RGB histogram


@dataclass
class Shot:
    index: int
    start_frame: int
    end_frame: int  # exclusive
    start_t: float
    end_t: float

    @property
    def duration(self) -> float:
        return self.end_t - self.start_t

    @property
    def n_frames(self) -> int:
        return self.end_frame - self.start_frame


def histograms(frames: np.ndarray) -> np.ndarray:
    """(n, H, W, 3) uint8 -> (n, BINS**3) float32, L1-normalised."""
    q = (frames.astype(np.uint16) * BINS) >> 8  # 0..BINS-1
    idx = q[..., 0] * BINS * BINS + q[..., 1] * BINS + q[..., 2]
    idx = idx.reshape(len(frames), -1)

    out = np.zeros((len(frames), BINS ** 3), dtype=np.float32)
    for i, row in enumerate(idx):
        out[i] = np.bincount(row, minlength=BINS ** 3)
    out /= out.sum(axis=1, keepdims=True) + 1e-9
    return out


def hist_distance(h: np.ndarray) -> np.ndarray:
    """Per-frame-pair histogram intersection distance. Length n-1."""
    inter = np.minimum(h[:-1], h[1:]).sum(axis=1)
    return 1.0 - inter


def detect(
    media: Media,
    min_shot_s: float = 0.4,
    k: float = 6.0,
    floor: float = 0.28,
) -> list[Shot]:
    """Find hard cuts.

    Threshold is adaptive: median + k * MAD over the whole distance curve,
    floored so that a very static video doesn't produce phantom cuts.
    """
    if media.n_frames < 3:
        return [Shot(0, 0, media.n_frames, 0.0, media.duration)]

    h = histograms(media.frames)
    d = hist_distance(h)

    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med))) + 1e-9
    thresh = max(med + k * mad, floor)

    min_gap = max(int(min_shot_s * media.fps), 2)
    cuts: list[int] = []
    last = -min_gap
    for i in np.flatnonzero(d > thresh):
        i = int(i) + 1  # boundary belongs to the *next* frame
        if i - last >= min_gap:
            cuts.append(i)
            last = i

    bounds = [0, *cuts, media.n_frames]
    return [
        Shot(n, a, b, media.t(a), media.t(b))
        for n, (a, b) in enumerate(zip(bounds[:-1], bounds[1:]))
    ]


def shot_histograms(media: Media, shots: list[Shot]) -> np.ndarray:
    """One mean histogram per shot -- used for near-duplicate detection."""
    h = histograms(media.frames)
    out = np.zeros((len(shots), h.shape[1]), dtype=np.float32)
    for i, s in enumerate(shots):
        out[i] = h[s.start_frame : s.end_frame].mean(axis=0)
    return out


# --------------------------------------------------------------------------
# jump cuts
# --------------------------------------------------------------------------
#
# A jump cut removes a stretch from inside one take: the camera and the room
# stay put, the person in front of it jumps. It is the talking vlogger's
# basic tool (pauses and fluffs cut out), and to the histogram it is no cut
# at all -- the same colours are in the frame before and after. What gives
# it away is time: movement is a run of changing frames, a jump is one frame
# that changes a lot between frames that barely change.
#
# Needs every frame (load()). On keyframe samples (load_index, ~1 a second)
# every pair of samples is a "jump", so nothing can be read there.

JUMP_CHANGE = 20.0      # luma step that counts as a pixel changing (0-255)
JUMP_MIN_SHARE = 0.05   # at least this share of the picture changes (~65 of 48x27)
JUMP_SPIKE = 4.0        # ... and this many times the busy level around it
JUMP_WINDOW_S = 0.5     # "around it": this far either side
JUMP_NEIGHBOUR = 0.5    # the frames either side change less than this share of the jump
JUMP_MAX_SHARE = 0.6    # more than this and it's a new picture, not the same room
JUMP_BRIGHT_STEP = 8.0  # a bigger change in mean luma is a flash or exposure jump
# All priors, set on synthetic fixtures (tests/test_jump_cuts.py).


def jump_cuts(
    media: Media,
    shot_list: list[Shot],
    min_shot_s: float = 0.4,
    spike: float = JUMP_SPIKE,
    min_share: float = JUMP_MIN_SHARE,
) -> list[int]:
    """Frame indices where a jump cut lands inside a detected shot.

    Each index is the first frame after the jump, the way Shot.start_frame
    marks a cut. Index media gives [] (see the note above); callers that
    report a reading should treat that as not checked, not as none.
    """
    if media.times is not None or media.n_frames < 3:
        return []
    # share[i] / level[i] describe the change INTO frame i, as motion() does.
    # In chunks: ten minutes of float luma twice over is a lot of memory.
    share = np.zeros(media.n_frames, dtype=np.float32)
    level = np.zeros(media.n_frames, dtype=np.float32)
    for a in range(0, media.n_frames - 1, 2048):
        y = luma(media.frames[a:a + 2049])
        share[a + 1:a + len(y)] = (np.abs(np.diff(y, axis=0)) > JUMP_CHANGE).mean(axis=(1, 2))
        level[a + 1:a + len(y)] = np.abs(np.diff(y.mean(axis=(1, 2))))
    w = max(int(round(JUMP_WINDOW_S * media.fps)), 2)
    gap = max(int(min_shot_s * media.fps), 2)

    out: list[int] = []
    for s in shot_list:
        last = s.start_frame
        for i in range(s.start_frame + 1, s.end_frame - 1):
            c = share[i]
            if c < min_share or i - last < gap or s.end_frame - i < gap:
                continue
            if share[i - 1] > JUMP_NEIGHBOUR * c or share[i + 1] > JUMP_NEIGHBOUR * c:
                continue
            # The busy level is a high percentile, not the median: footage
            # conformed to double its rate shows movement as every other
            # frame changing, and those must not each read as a jump.
            around = np.concatenate([share[max(s.start_frame + 1, i - w):i - 1],
                                     share[i + 2:min(s.end_frame, i + w + 1)]])
            busy = float(np.percentile(around, 75)) if around.size else 0.0
            if c < spike * max(busy, min_share / spike):
                continue
            # Same room: most of the picture holds still across the jump. (A
            # layout correlation doesn't do here -- a person filling a third
            # of the frame moving sideways drags it under 0.5.)
            if c > JUMP_MAX_SHARE or level[i] > JUMP_BRIGHT_STEP:
                continue
            out.append(i)
            last = i
    return out

