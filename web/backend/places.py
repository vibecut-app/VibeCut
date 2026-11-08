"""Where a clip was filmed, in words: "Shibuya", "Golden Gate Park".

A describing caption reads better with the place in it, and phones record
GPS with every clip. The coordinates are turned into a name by Apple's
geocoder on this Mac (place/vibeplace.swift): only the coordinates go to
Apple's free location service, nothing of the footage, no key, no cost.

Coordinates are rounded to ~100 m before asking, so a whole afternoon in one
neighbourhood is one request, and every answer is cached in the cache folder.
Off macOS, offline, or for clips with no GPS, there is no place -- and a
caption simply leaves the place out.
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

SRC = Path(__file__).parent / "place" / "vibeplace.swift"
ROUND = 3            # decimal places: ~100 m, one neighbourhood
_lock = threading.Lock()
_binary: Path | None = None
_failed: str | None = None


def _cache_file() -> Path:
    from .indexer import CACHE
    return CACHE / "places.json"


def ensure_built() -> Path | None:
    global _binary, _failed
    with _lock:
        if _binary or _failed:
            return _binary
        if sys.platform != "darwin" or not shutil.which("swiftc"):
            _failed = "not on macOS with swiftc"
            return None
        from .indexer import CACHE
        h = hashlib.sha1(SRC.read_bytes()).hexdigest()[:10]
        target = CACHE / "bin" / f"vibeplace-{h}"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            p = subprocess.run(["swiftc", "-O", str(SRC), "-o", str(tmp)], capture_output=True, text=True)
            if p.returncode != 0:
                _failed = p.stderr[-400:]
                print(f"[places] build failed, captions go without places:\n{_failed}")
                return None
            os.replace(tmp, target)
        _binary = target
        return _binary


def key(gps) -> str | None:
    if not gps or len(gps) != 2:
        return None
    return f"{round(float(gps[0]), ROUND)},{round(float(gps[1]), ROUND)}"


def short_name(r: dict | None) -> str | None:
    """The name a creator would put on screen: a named place, else the
    neighbourhood, else the city. Never a street address."""
    if not r:
        return None
    for k in ("place", "area", "city"):
        v = (r.get(k) or "").strip()
        if v:
            return v
    return None


def lookup(gps_list: list, ask=None) -> dict[str, dict]:
    """{rounded "lat,lon": answer} for every coordinate, asking only for new ones.
    `ask(keys) -> [answers]` stands in for the helper (tests)."""
    keys = sorted({k for k in (key(g) for g in gps_list) if k})
    path = _cache_file()
    try:
        cache = json.loads(path.read_text())
    except (OSError, ValueError):
        cache = {}
    todo = [k for k in keys if k not in cache]
    if todo:
        if ask is None:
            binary = ensure_built()
            if binary is not None:
                def ask(ks: list[str]) -> list[dict]:
                    p = subprocess.run([str(binary), *ks], capture_output=True, text=True, timeout=30 + 2 * len(ks))
                    out = []
                    for line in p.stdout.splitlines():
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                    return out
        if ask is not None:
            try:
                for r in ask(todo):
                    if r.get("at") in todo and not r.get("error"):
                        cache[r["at"]] = r
            except (OSError, subprocess.SubprocessError):
                pass
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(cache))
            except OSError:
                pass
    return {k: cache[k] for k in keys if k in cache}


def cached(gps_list: list) -> dict[str, dict]:
    """What the geocoder already answered for these coordinates; never asks
    (for a request that must not wait on the helper)."""
    try:
        cache = json.loads(_cache_file().read_text())
    except (OSError, ValueError):
        return {}
    keys = {k for k in (key(g) for g in gps_list) if k}
    return {k: cache[k] for k in keys if k in cache}


def name_at(gps, found: dict[str, dict]) -> str | None:
    return short_name(found.get(key(gps) or ""))
