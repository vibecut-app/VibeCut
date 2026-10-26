"""Defaults that follow the creator: what they picked last time is what is
offered next time. Layer 1 of preserving preference (2026-10-18).

Only the picks the creator makes with their own hands are remembered -- the
frame and the look from Make, the frame chip, a look chosen under Captions,
a caption template or entrance, the Music switch -- and only as the
*preselected* answer, shown with "as last time". Nothing is applied
silently, nothing is learned from what they didn't say. Layer 2 (the
profile's taste and confirmed rules in the judge's prompt) and layer 3
(undo and verdicts as candidate rules) are not here.

Your profile's start (sarah, 2026-10-14, brought back 2026-10-19): asked
once after an export -- what they make, how fast they like the cuts, the
transition between shots, the captions -- and kept here too, as `makes`,
`pace`, `transition` and `captions` ("off" = no captions; a caption style is
`caption_template` like any other). Unlike the rest, these are where the next
video *starts* (app._from_profile), and the pace, the captions switch and a
transition for every cut are only learned from Frames once a profile was
made: a skipped question was a "no".

Kept in $VIBECUT_CACHE/settings.json beside the music folder, so it lives
with the cache and leaves with it.
"""

from __future__ import annotations

import json
import threading
import time

from .indexer import CACHE

SETTINGS = CACHE / "settings.json"
KEYS = ("format", "look", "music", "caption_template", "caption_enter", "vibe", "sfx",
        "makes", "pace", "transition", "captions")
ASKED = ("made", "skipped")
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


def asked() -> str | None:
    """How the profile question after an export was answered: "made",
    "skipped", or None while it hasn't been asked."""
    how = (_read().get("profile_ask") or {}).get("how")
    return how if how in ASKED else None


def answer(how: str) -> str:
    """Record the answer. A skip never undoes a profile that was made."""
    if how not in ASKED:
        raise ValueError(f"how is one of {', '.join(ASKED)}")
    with _lock:
        data = _read()
        was = (data.get("profile_ask") or {}).get("how")
        if not (how == "skipped" and was == "made"):
            data["profile_ask"] = {"how": how, "at": time.time()}
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(SETTINGS)
        return data["profile_ask"]["how"]


def forget() -> None:
    with _lock:
        data = _read()
        data.pop("defaults", None)
        data.pop("profile_ask", None)
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data))
