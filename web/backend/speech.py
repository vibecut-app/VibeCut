"""Bridge to the on-device speech helper (speech/vibespeech.swift).

Only the talking-head mode (talk.py) uses this -- VibeCut's default path
still needs no transcript. macOS 26+ only: Apple's SpeechTranscriber runs on
this Mac, so audio never leaves it (the OS downloads the language model the
first time). Built into the cache on first use, like the Vision helper.

Transcripts are cached per clip and language next to the clip's index.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

from . import indexer

SRC = Path(__file__).parent / "speech" / "vibespeech.swift"
LOCALES = {"zh-CN": "Chinese", "en-US": "English"}
SR = 16000
_lock = threading.Lock()
_binary: Path | None = None
_failed: str | None = None


class SpeechError(Exception):
    pass


def ensure_built() -> Path:
    global _binary, _failed
    with _lock:
        if _binary:
            return _binary
        if _failed:
            raise SpeechError(_failed)
        if sys.platform != "darwin" or not shutil.which("swiftc"):
            _failed = "Transcribing needs macOS 26 or later with the Xcode command-line tools."
            raise SpeechError(_failed)
        h = hashlib.sha1(SRC.read_bytes()).hexdigest()[:10]
        target = indexer.CACHE / "bin" / f"vibespeech-{h}"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            p = subprocess.run(["swiftc", "-parse-as-library", "-O", str(SRC), "-o", str(tmp)],
                               capture_output=True, text=True)
            if p.returncode != 0:
                _failed = "The speech helper didn't build (needs macOS 26+): " + p.stderr[-300:]
                raise SpeechError(_failed)
            os.replace(tmp, target)
        _binary = target
        return _binary


def _wav(clip: dict) -> Path:
    d = indexer.clip_dir(clip["id"]) / "speech"
    d.mkdir(parents=True, exist_ok=True)
    out = d / "audio.wav"
    if not out.exists():
        tmp = d / "audio.tmp.wav"
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip["path"], "-vn", "-ac", "1", "-ar", str(SR),
                            "-c:a", "pcm_s16le", str(tmp)], capture_output=True, text=True)
        if p.returncode != 0:
            raise SpeechError(f"{clip['name']} has no sound to transcribe")
        os.replace(tmp, out)
    return out


def audio(clip: dict) -> np.ndarray:
    """Mono 16 kHz float samples of the clip (cached wav)."""
    raw = _wav(clip).read_bytes()
    k = raw.find(b"data")   # ffmpeg may write a LIST chunk before it
    body = raw[k + 8:] if k >= 0 else raw[44:]
    return np.frombuffer(body[:len(body) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


def transcribe(clip: dict, locale: str) -> list[dict]:
    """[{text, start, end, words: [{t, s, e, c}], segs: [word…]}] in source
    seconds; `c` is the recogniser's confidence in the word (0..1), None where
    it gave none. Cached."""
    if locale not in LOCALES:
        raise SpeechError(f"unsupported language {locale}")
    cache = indexer.clip_dir(clip["id"]) / "speech" / f"{locale}.v3.json"   # v2: + word segments; v3: + confidence
    if cache.exists():
        return json.loads(cache.read_text())
    binary = ensure_built()
    wav = _wav(clip)
    p = subprocess.run([str(binary), str(wav), locale], capture_output=True, text=True, timeout=1800)
    if p.returncode != 0:
        raise SpeechError(f"couldn't transcribe {clip['name']}: {p.stderr.strip()[-200:]}")
    out = parse(p.stdout)
    cache.write_text(json.dumps(out, ensure_ascii=False))
    return out


def _conf(w: dict) -> float | None:
    c = w.get("c")
    if c is None:
        return None
    try:
        return round(min(1.0, max(0.0, float(c))), 3)
    except (TypeError, ValueError):
        return None


def parse(stdout: str) -> list[dict]:
    """The helper's lines (one JSON result each) -> results in time order."""
    out = []
    for line in stdout.splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        words = [{"t": w["t"], "s": round(float(w["s"]), 3), "e": round(float(w["e"]), 3), "c": _conf(w)}
                 for w in r.get("words", []) if w.get("t", "").strip()]
        if words:
            out.append({"text": r.get("text", "").strip(), "start": words[0]["s"], "end": words[-1]["e"],
                        "words": words, "segs": [x for x in r.get("segs", []) if x.strip()]})
    out.sort(key=lambda r: r["start"])
    return out
