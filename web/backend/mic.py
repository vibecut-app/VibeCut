"""The creator's own voice, recorded over the playing edit (a voiceover).

Why this exists, in editing terms: a day told in your own words holds
together in a way a montage doesn't -- the voice carries the viewer across
cuts that would otherwise read as a pile of clips, and it is the one sound
on a phone that can't be borrowed. CapCut and iMovie both have it as one
button: Record, the video plays, you talk, and the take lands on its own
strip where you started, with the music going quieter under it.

Nothing is transcribed and nothing leaves the computer; this is not the
script-led voiceover proposal (voiceover.py). A take is saved once as
48 kHz stereo WAV under $VIBECUT_CACHE/voice/, named by id; the board keeps
only that id, its place and its level (board.add_voice), and the mixer
(audiomix) places it and ducks the music where the voice is heard.

VOICE_DUCK and the speaking gate are priors, like every number in
cutgrammar -- calibrate before trusting.
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
import wave
from pathlib import Path

import numpy as np

from .indexer import CACHE

DIR = CACHE / "voice"
SR = 48000
MIN_S = 0.3          # a click on Record and straight off again: nothing to keep
MAX_BYTES = 200 * 1024 * 1024
VOICE_DUCK = 0.3     # the music under a voice, as a share of its level [prior]
WIN_S = 0.05         # the speaking gate's window
GATE = 0.2           # heard: louder than this share of the take's loud end [prior]
FLOOR = 0.006        # never call room hiss a voice, however quiet the take
BRIDGE_S = 0.6       # pauses shorter than this keep the music down (a breath, not a stop)
PAD_S = 0.1


class MicError(ValueError):
    pass


def valid(vid: str) -> bool:
    return 8 <= len(vid or "") <= 32 and all(ch in "0123456789abcdef" for ch in vid)


def path_of(vid: str) -> Path:
    if not valid(vid):
        raise MicError("no such recording")
    return DIR / f"{vid}.wav"


def save(data: bytes, suffix: str = ".webm") -> tuple[str, float]:
    """A take from the browser (webm / ogg / mp4, whatever its recorder made),
    as WAV. Its id and length in seconds."""
    if not data:
        raise MicError("Nothing was recorded. Is the microphone on?")
    if len(data) > MAX_BYTES:
        raise MicError("That recording is too long to keep.")
    DIR.mkdir(parents=True, exist_ok=True)
    vid = uuid.uuid4().hex[:12]
    dest = path_of(vid)
    suffix = suffix if suffix in (".webm", ".ogg", ".mp4", ".m4a", ".wav") else ".webm"
    with tempfile.NamedTemporaryFile(dir=DIR, suffix=suffix, delete=False) as fh:
        fh.write(data)
        raw = Path(fh.name)
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(raw), "-vn",
                            "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(dest)], capture_output=True)
    finally:
        raw.unlink(missing_ok=True)
    if p.returncode != 0 or not dest.exists():
        dest.unlink(missing_ok=True)
        raise MicError("That recording couldn’t be read.")
    with wave.open(str(dest)) as w:
        dur = w.getnframes() / float(w.getframerate() or SR)
    if dur < MIN_S:
        dest.unlink(missing_ok=True)
        raise MicError("That recording was too short to keep. Talk for a moment longer.")
    return vid, round(dur, 3)


def speaking(seg: np.ndarray) -> list[tuple[float, float]]:
    """Where in a take the voice is heard (seconds from its start): the music
    ducks there and comes back up in the pauses between sentences."""
    w = int(WIN_S * SR)
    if len(seg) < w:
        return []
    k = len(seg) // w
    mono = np.asarray(seg[:k * w], np.float32).mean(axis=1).reshape(k, w)
    rms = np.sqrt((mono ** 2).mean(axis=1))
    on = rms > max(FLOOR, GATE * float(np.percentile(rms, 95)))
    spans: list[list[float]] = []
    for i in np.flatnonzero(on):
        a, b = i * WIN_S, (i + 1) * WIN_S
        if spans and a - spans[-1][1] < BRIDGE_S:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    end = k * WIN_S
    return [(max(0.0, a - PAD_S), min(end, b + PAD_S)) for a, b in spans]
