"""VibeCut's own transition sounds: whoosh, swish, riser, hit, pop.

Why this exists (2026-10-24, the user: "those transition audios -- how do we
add them in"). The sounds short-form editors lay on a whip, a slide, a zoom
or the drop are a small family, and every app ships its own. Freesound has
some (openverse.sfx), but commercial use of its API is negotiated case by
case (design/research/02) and an offline Mac gets nothing. So, like the
backup songs (songpack.py), they are composed here from noise and sine
sweeps with a fixed seed: ours, CC0, a few lines of code instead of audio
files, rendered once into the cache as 48 kHz stereo WAV and mixed like any
other sound effect (audiomix: `{"path", "at", "gain"}` on the bed's `sfx`).

Each sound has a `peak_s`: where its loudest moment sits, so a whoosh is
placed with its rush on the cut, not starting at it.

A transition sound is easily an amateur tell when it is loud or on every
cut (design/research/09: DJI's action-matched effects, "risky"). Where they
go, and how loud, is make.transition_sounds' call; gains here are only the
sound's own shape. Every number is a prior.
"""

from __future__ import annotations

import os
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

VERSION = 1
SR = 48000


@dataclass(frozen=True)
class Sound:
    name: str
    title: str
    dur: float
    peak_s: float


SOUNDS = {
    "whoosh": Sound("whoosh", "Whoosh", 0.7, 0.42),     # a whip pan or a swipe
    "swish": Sound("swish", "Swish", 0.35, 0.2),         # a quick slide, lighter
    "riser": Sound("riser", "Riser", 1.6, 1.55),         # builds into the drop
    "hit": Sound("hit", "Hit", 0.9, 0.02),               # the drop, a flash
    "pop": Sound("pop", "Pop", 0.18, 0.01),              # a caption popping in
}


def cache_dir() -> Path:
    root = Path(os.environ.get("VIBECUT_CACHE", str(Path.home() / ".cache" / "vibecut")))
    return root / "music" / "sfx-pack" / f"v{VERSION}"


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _sweep_filter(x: np.ndarray, f0: float, f1: float, q: float = 1.2) -> np.ndarray:
    """A band-pass whose centre glides f0 -> f1 (a state-variable filter, one
    sample at a time: the glide is what makes air sound like it moves)."""
    out = np.zeros_like(x)
    lo = bp = 0.0
    fc = np.geomspace(max(f0, 20.0), max(f1, 20.0), len(x))
    damp = 1.0 / q
    for i, v in enumerate(x):
        f = 2.0 * np.sin(np.pi * fc[i] / SR)
        hi = v - lo - damp * bp
        bp += f * hi
        lo += f * bp
        out[i] = bp
    return out


def _env(n: int, peak: int, attack: float = 2.0, release: float = 3.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float32)
    up = (t[:peak] / max(peak, 1)) ** attack
    down = (1 - (t[peak:] - peak) / max(n - peak, 1)) ** release
    return np.concatenate([up, down]).astype(np.float32)


def render(name: str) -> np.ndarray:
    """(n, 2) float32 at SR, peak-normalised to -1 dBFS."""
    s = SOUNDS[name]
    n = int(s.dur * SR)
    pk = int(s.peak_s * SR)
    t = np.arange(n, dtype=np.float32) / SR
    if name == "whoosh":
        mono = _sweep_filter(_noise(n, 1), 300, 3500) * _env(n, pk, 2.5, 2.0)
        pan = np.clip((t - s.peak_s) / 0.25, -1, 1) * 0.6          # it passes from left to right
    elif name == "swish":
        mono = _sweep_filter(_noise(n, 2), 1200, 6000, 1.6) * _env(n, pk, 1.5, 2.5)
        pan = np.clip((t - s.peak_s) / 0.12, -1, 1) * 0.5
    elif name == "riser":
        air = _sweep_filter(_noise(n, 3), 200, 5000, 0.9) * _env(n, pk, 2.2, 0.5)
        tone = np.sin(2 * np.pi * np.cumsum(np.geomspace(110, 880, n)) / SR).astype(np.float32) * _env(n, pk, 3.0, 0.5)
        mono = air + 0.25 * tone
        pan = np.zeros(n, np.float32)
    elif name == "hit":
        f = np.geomspace(90, 38, n)
        body = np.sin(2 * np.pi * np.cumsum(f) / SR).astype(np.float32) * np.exp(-t / 0.28).astype(np.float32)
        click = _sweep_filter(_noise(n, 4), 4000, 1500, 0.8) * np.exp(-t / 0.02).astype(np.float32)
        mono = body + 0.6 * click
        pan = np.zeros(n, np.float32)
    elif name == "pop":
        f = np.geomspace(900, 500, n)
        mono = np.sin(2 * np.pi * np.cumsum(f) / SR).astype(np.float32) * np.exp(-t / 0.04).astype(np.float32)
        pan = np.zeros(n, np.float32)
    else:
        raise KeyError(name)
    # micro fades: a click at either end is the tell of a cut-off sound
    m = int(0.004 * SR)
    mono[:m] *= np.linspace(0, 1, m, dtype=np.float32)
    mono[-m:] *= np.linspace(1, 0, m, dtype=np.float32)
    left, right = mono * np.sqrt((1 - pan) / 2), mono * np.sqrt((1 + pan) / 2)
    st = np.stack([left, right], axis=1).astype(np.float32)
    peak = float(np.abs(st).max()) or 1.0
    return st * (10 ** (-1 / 20) / peak)


def path_for(name: str) -> str:
    """The sound's WAV in the cache, rendered on first use."""
    d = cache_dir()
    p = d / f"{name}.wav"
    if not p.exists():
        d.mkdir(parents=True, exist_ok=True)
        x = np.clip(render(name), -1, 1)
        tmp = p.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((x * 32767).astype("<i2").tobytes())
        tmp.replace(p)
    return str(p)


def public() -> list[dict]:
    return [{"id": s.name, "title": s.title, "dur": s.dur} for s in SOUNDS.values()]
