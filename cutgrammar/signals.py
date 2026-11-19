"""Per-second signals of a clip: what reject.py and trim.py decide from.

Everything is computed from the arrays the index decode already produced
(load_index: keyframe samples at thumbnail size, mono 16 kHz audio) -- no
second pass over the file.

- quality   bestframe's frame score (sharpness, exposure, contrast, steadiness)
- luma      mean brightness, 0..255
- motion    how much the picture changes over a second: near zero is a dead
            frame, very high is a shaking camera or a whip-pan
- subject   is there *something* in frame, and is it inside it: spectral-
            residual saliency (Hou & Zhang, CVPR 2007) on a small grey image.
            Model-free, so it knows "a distinct thing is there", not what.
- edge      how close that subject sits to the side of the frame -- high
            when it is leaving or entering
- speech    fraction of each second that is voiced (features.speech_mask),
            plus the voiced intervals themselves at 10 ms, so a cut can
            avoid landing mid-word

Resolution is the index's: keyframes, ~1 s on iPhone. Motion and subject
are therefore per-second judgements; only speech is finer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from . import bestframe, features
from .media import Media, area_resize

SAL_W = 64  # saliency is computed on a 64-px-wide grey image


@dataclass
class ClipSignals:
    duration: float
    quality: list[float]
    sharpness: list[float]
    luma: list[float]
    contrast: list[float]
    motion: list[float]
    subject: list[float]
    edge: list[float]
    speech: list[float]
    voiced: list[list[float]]      # [[start, end], ...] seconds
    thumb: list[float]             # 16x9 grey vector: a model-free fingerprint

    @property
    def n(self) -> int:
        return len(self.quality)

    def arr(self, name: str) -> np.ndarray:
        return np.asarray(getattr(self, name), dtype=np.float64)

    def to_json(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], float):
                d[k] = [round(x, 4) for x in v]
        return d

    @classmethod
    def from_json(cls, d: dict) -> "ClipSignals":
        return cls(**d)


# --------------------------------------------------------------------------
# saliency
# --------------------------------------------------------------------------

def _box(x: np.ndarray, k: int) -> np.ndarray:
    """k x k mean filter, edges padded (separable)."""
    p = k // 2
    y = np.pad(x, p, mode="edge")
    c = np.cumsum(np.cumsum(y, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def saliency(grey: np.ndarray) -> np.ndarray:
    """Spectral residual saliency map, normalised to sum to 1."""
    f = np.fft.fft2(grey)
    amp = np.log(np.abs(f) + 1e-9)
    residual = amp - _box(amp, 3)
    s = np.abs(np.fft.ifft2(np.exp(residual + 1j * np.angle(f)))) ** 2
    s = _box(_box(s, 5), 5)      # ~ Gaussian blur
    return s / (s.sum() + 1e-12)


def subject_presence(grey: np.ndarray) -> tuple[float, float]:
    """(presence 0..1, edge 0..1) for one frame.

    Presence: how concentrated the saliency is -- a distinct thing draws it
    into one place; an empty wall, the ground or a lens cap spread it out.
    Edge: how near the salient mass sits to the left/right/top/bottom side.
    """
    if grey.std() < 2.0:  # flat frame: nothing to look at
        return 0.0, 0.0
    s = saliency(grey)
    flat = np.sort(s.ravel())[::-1]
    top = flat[: max(1, len(flat) // 10)].sum()          # mass in the top 10% of pixels
    presence = float(np.clip((top - 0.25) / 0.35, 0, 1))
    h, w = s.shape
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = float((s * xs).sum() / (w - 1)), float((s * ys).sum() / (h - 1))
    d = min(cx, 1 - cx, cy, 1 - cy)                      # distance to nearest side, 0..0.5
    edge = float(np.clip((0.2 - d) / 0.15, 0, 1))
    return presence, edge


# --------------------------------------------------------------------------
# per-second assembly
# --------------------------------------------------------------------------

def _grey(frames: np.ndarray) -> np.ndarray:
    f = frames.astype(np.float32)
    return 0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]


def _small_grey(frames: np.ndarray, w: int) -> np.ndarray:
    """(n, H, W, 3) -> (n, h, w) grey, box-filtered."""
    h = max(4, int(round(frames.shape[1] * w / frames.shape[2])))
    return _grey(area_resize(frames, w, h))


def voiced_of(m: Media, n_sec: int) -> tuple[list[float], list[list[float]]]:
    """Speech from the level: the voiced share of each second, and the
    voiced intervals at 10 ms (blips under 80 ms dropped). One function,
    so a pro's edit (taste/cuts.py) is heard the way a clip is."""
    speech = [0.0] * n_sec
    voiced: list[list[float]] = []
    if m.has_audio:
        mask = features.speech_mask(m, 0.01)
        if mask.size:
            for k in range(n_sec):
                seg = mask[k * 100:(k + 1) * 100]
                speech[k] = float(seg.mean()) if seg.size else 0.0
            edges = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(np.int8), [0]])))
            for a, b in zip(edges[::2], edges[1::2]):
                if b - a >= 8:  # ignore blips under 80 ms
                    voiced.append([round(a * 0.01, 2), round(b * 0.01, 2)])
    return speech, voiced


def from_media(m: Media) -> ClipSignals:
    frames = m.preview if m.preview is not None else m.frames
    times = m.times if m.times is not None else np.arange(len(frames)) / max(m.fps, 1e-6)
    n_sec = max(1, int(np.ceil(m.duration - 1e-6)))

    fs = bestframe.frame_scores(frames)
    small = _grey(m.frames)                                  # 48x27 grey
    luma = small.mean(axis=(1, 2))
    # motion: change against the sample one second earlier
    mot = np.zeros(len(frames))
    for i in range(1, len(frames)):
        j = int(np.argmin(np.abs(times[:i] - (times[i] - 1.0))))
        mot[i] = np.abs(small[i] - small[j]).mean()
    if len(frames) > 1:
        mot[0] = mot[1]
    subj = np.array([subject_presence(g) for g in _small_grey(frames, SAL_W)])

    def per_second(x: np.ndarray) -> list[float]:
        out = []
        for k in range(n_sec):
            inside = (times >= k) & (times < k + 1)
            if inside.any():
                out.append(float(x[inside].mean()))
            else:  # between keyframes: the nearest sample stands in
                out.append(float(x[int(np.argmin(np.abs(times - (k + 0.5))))]))
        return out

    speech, voiced = voiced_of(m, n_sec)

    best = int(np.argmax(fs["total"])) if len(frames) else 0
    thumb = _small_grey(frames[best:best + 1], 16)[0].ravel() if len(frames) else np.zeros(144)
    thumb = (thumb - thumb.mean()) / (thumb.std() + 1e-6)

    return ClipSignals(
        duration=float(m.duration),
        quality=per_second(fs["total"]),
        sharpness=per_second(fs["sharpness"]),
        luma=per_second(luma),
        contrast=per_second(fs["contrast"]),
        motion=per_second(mot),
        subject=per_second(subj[:, 0]),
        edge=per_second(subj[:, 1]),
        speech=speech,
        voiced=voiced,
        thumb=[float(x) for x in thumb],
    )


# --------------------------------------------------------------------------
# voice, from a real sound classifier
# --------------------------------------------------------------------------

# Below VOICE_LO a second has no voice in it; above VOICE_HI it is talking. [prior]
VOICE_LO, VOICE_HI = 0.15, 0.45


def with_voice(sig: ClipSignals, voice: list[float]) -> ClipSignals:
    """The same signals, with `speech` counting only seconds where a voice is heard.

    `speech` from the level alone can't tell a voice from a song: a clip
    with music under it reads as someone talking the whole way through,
    and a talking clip is never trimmed to a chosen length (trim.py). A
    sound classifier's per-second probability of a voice decides which
    loud seconds are words; the voiced intervals in seconds without a
    voice are dropped too, so a cut isn't kept off a beat as if it were a word.
    """
    if not voice or sig.n == 0:
        return sig
    gate = voice_gate(voice, sig.n)
    d = sig.to_json()
    d["speech"] = [round(float(s * g), 4) for s, g in zip(sig.speech, gate)]
    d["voiced"] = gated(sig.voiced, gate)
    return ClipSignals.from_json(d)


def voice_gate(voice: list[float], n: int) -> np.ndarray:
    """0..1 per second: how surely the loud seconds are a voice."""
    v = np.asarray(list(voice[:n]) + [voice[-1]] * max(0, n - len(voice)), dtype=np.float64)
    return np.clip((v - VOICE_LO) / (VOICE_HI - VOICE_LO), 0, 1)


def gated(voiced: list[list[float]], gate: np.ndarray) -> list[list[float]]:
    """The voiced intervals whose middle second has a voice in it."""
    return [w for w in voiced if gate[min(int((w[0] + w[1]) / 2), len(gate) - 1)] > 0]
