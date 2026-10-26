"""Bridge to the on-device Vision helper (vision/vibevision.swift).

macOS only. Compiled once into the cache on first use; if the toolchain or
the OS is missing, analyse() returns empty results and the storyboard falls
back to colour signatures -- the product still works, the subject axis is
just cruder.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SRC = Path(__file__).parent / "vision" / "vibevision.swift"
_lock = threading.Lock()
_binary: Path | None = None
_failed: str | None = None

CHUNK = 24
TEXT_CHUNK, TEXT_TIMEOUT_S = 8, 60       # fast OCR: a chunk of frames gets a minute
# Accurate OCR (--text2) takes several times as long a frame, and the
# first CJK frame may wait on the OS loading a language: fewer frames a
# process, more time each. [prior: not yet timed on her Mac]
TEXT2_CHUNK, TEXT2_TIMEOUT_S = 4, 180


def _target() -> Path:
    from .indexer import CACHE
    h = hashlib.sha1(SRC.read_bytes()).hexdigest()[:10]
    return CACHE / "bin" / f"vibevision-{h}"


def ensure_built() -> Path | None:
    """Compile the helper if needed. Safe to call from several threads."""
    global _binary, _failed
    with _lock:
        if _binary or _failed:
            return _binary
        if sys.platform != "darwin" or not shutil.which("swiftc"):
            _failed = "not on macOS with swiftc"
            return None
        target = _target()
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            p = subprocess.run(["swiftc", "-O", str(SRC), "-o", str(tmp)],
                               capture_output=True, text=True)
            if p.returncode != 0:
                _failed = p.stderr[-400:]
                print(f"[vision] build failed, using colour fallback:\n{_failed}")
                return None
            os.replace(tmp, target)
        _binary = target
        return _binary


def status() -> str:
    return "ready" if _binary else ("unavailable" if _failed else "building")


def _run(binary: Path, paths: list[str]) -> list[dict]:
    p = subprocess.run([str(binary), *paths], capture_output=True, text=True)
    out = []
    for line in p.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def analyse(paths: list[str]) -> tuple[list[dict], str]:
    binary = ensure_built()
    if binary is None or not paths:
        return [], "fallback"
    chunks = [paths[i:i + CHUNK] for i in range(0, len(paths), CHUNK)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = [r for rs in ex.map(lambda c: _run(binary, c), chunks) for r in rs]
    for r in results:  # flatten [{label: conf}] -> [[label, conf]]
        r["labels"] = [[k, round(v, 3)] for d in r.get("labels", []) for k, v in d.items()]
        r["embedding"] = [round(x, 4) for x in r.get("embedding", [])]
    return results, "vision"


def faces(paths: list[str]) -> dict[str, list[list[float]]]:
    """Face boxes per image, or {} when Vision isn't available."""
    binary = ensure_built()
    if binary is None or not paths:
        return {}
    chunks = [paths[i:i + 64] for i in range(0, len(paths), 64)]

    def run(chunk: list[str]) -> list[dict]:
        p = subprocess.run([str(binary), "--faces", *chunk], capture_output=True, text=True)
        out = []
        for line in p.stdout.splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out
    with ThreadPoolExecutor(max_workers=4) as ex:
        return {r["path"]: r["faces"] for rs in ex.map(run, chunks) for r in rs}


def _lines(out) -> list[dict]:
    if isinstance(out, bytes):     # what a timed-out run had printed comes back as bytes
        out = out.decode("utf-8", errors="replace")
    got = []
    for line in (out or "").splitlines():
        try:
            got.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return got


def text(paths: list[str], accurate: bool = False):
    """Words on screen per image ({path: [{text, box, conf}]}), or {} when
    Vision isn't available. Only timing and place are used downstream.

    `accurate` (the helper's --text2): Apple's accurate recogniser with
    language detection, the only level that reads Korean, Japanese and
    Chinese captions as well as Latin ones. Several times slower, so it
    runs in smaller chunks with longer to finish, and returns
    `(found, failed)`: `failed` = the frames nobody read (a chunk that hung
    or crashed), so a caller marks those words unknown rather than absent.
    """
    binary = ensure_built()
    if binary is None or not paths:
        return ({}, list(paths)) if accurate else {}
    mode, size, limit = ("--text2", TEXT2_CHUNK, TEXT2_TIMEOUT_S) if accurate else ("--text", TEXT_CHUNK, TEXT_TIMEOUT_S)
    chunks = [paths[i:i + size] for i in range(0, len(paths), size)]

    def run(chunk: list[str]) -> list[dict]:
        try:
            # a hang in the recogniser must never stall a learn: a chunk gets a time limit
            p = subprocess.run([str(binary), mode, *chunk], capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired as e:
            # the helper prints each frame as it finishes, so the ones before the hang still count
            return _lines(e.stdout)
        return _lines(p.stdout)
    with ThreadPoolExecutor(max_workers=4) as ex:
        found = {r["path"]: r.get("items", []) for rs in ex.map(run, chunks) for r in rs if "path" in r}
    if not accurate:
        return found
    return found, [p for p in paths if p not in found]


# A face this much smaller than the largest in frame is someone in the
# background (a lecture hall, a street), not a second person in the shot.
COMPANION = 0.25
# Turned less than this from the lens counts as looking into it. [prior]
FACING_DEG = 25.0
TRACK_COLS = 4   # faces.json rows written before face direction had 2


def face_track(boxes_per_sample: list[list[list[float]]], times: list[float], n_sec: int) -> list[list[float]]:
    """Per-second [presence, edge, people, facing] from face boxes on each
    sampled frame.

    Presence: the largest face is at least ~1% of the frame. Edge: that face
    touches or nearly touches a side -- someone entering or leaving. People:
    how many faces are in the shot (background faces left out). Facing: the
    share of samples where the largest face looks into the lens; -1 when the
    helper gave no direction (older macOS), so nobody guesses from it.
    """
    per = []
    for boxes in boxes_per_sample:
        if not boxes:
            per.append((0.0, 0.0, 0, 0.0))
            continue
        big = max(boxes, key=lambda b: b[2] * b[3])
        x, y, w, h = big[:4]
        presence = min(1.0, (w * h) / 0.01)
        gap = min(x, y, 1 - (x + w), 1 - (y + h))
        people = sum(1 for b in boxes if b[2] * b[3] >= COMPANION * w * h)
        facing = -1.0 if len(big) < 5 else float(abs(big[4]) <= FACING_DEG)
        per.append((presence, max(0.0, min(1.0, (0.04 - gap) / 0.04)), people, facing))
    out = []
    for k in range(n_sec):
        idx = [i for i, t in enumerate(times) if k <= t < k + 1]
        if not idx and times:
            idx = [min(range(len(times)), key=lambda i: abs(times[i] - (k + 0.5)))]
        if not idx:
            out.append([0.0, 0.0, 0.0, -1.0])
            continue
        seen = [per[i][3] for i in idx if per[i][0] > 0]
        out.append([round(sum(per[i][0] for i in idx) / len(idx), 3),
                    round(max(per[i][1] for i in idx), 3),
                    float(max(per[i][2] for i in idx)),
                    -1.0 if not seen or min(seen) < 0 else round(sum(seen) / len(seen), 3)])
    return out
