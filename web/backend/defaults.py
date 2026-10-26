"""Defaults that follow the creator: what they picked last time is what is
offered next time. Layer 1 of preserving preference (2026-10-18).

Only the picks the creator makes with their own hands are remembered -- the
frame and the look from Make, the frame chip, a look chosen under Captions,
a caption template or entrance, the Music switch -- and only as the
*preselected* answer, shown with "as last time". Nothing is applied
silently, nothing is learned from what they didn't say. Layer 2 (the
profile's taste and confirmed rules in the judge's prompt) and layer 3
(undo and verdicts as candidate rules) are not here.

Kept in $VIBECUT_CACHE/settings.json beside the music folder, so it lives
with the cache and leaves with it.
"""

from __future__ import annotations

import json
import threading
import time

from .indexer import CACHE

SETTINGS = CACHE / "settings.json"
KEYS = ("format", "look", "music", "caption_template", "caption_enter", "vibe", "sfx")
_lock = threading.Lock()


def _read() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def get() -> dict:
    """{key: value} for what has been remembered; empty when nothing has."""
    d = _read().get("defaults") or {}
    return {k: d[k] for k in KEYS if d.get(k) is not None}


def note(_sync: bool = True, **picks) -> dict:
    """Remember these picks (None clears one). Returns what is remembered now.
    Mirrored to Supabase when configured (cloud.py); `_sync=False` when the
    picks came *from* there."""
    with _lock:
        data = _read()
        d = dict(data.get("defaults") or {})
        for k, v in picks.items():
            if k not in KEYS:
                continue
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        d["at"] = time.time()
        data["defaults"] = d
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(SETTINGS)
    if _sync:
        from . import cloud
        for k, v in picks.items():
            if k in KEYS and v is not None:
                cloud.push("default", k, v)
    return get()


def forget() -> None:
    with _lock:
        data = _read()
        data.pop("defaults", None)
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data))
