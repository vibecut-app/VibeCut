"""Songs to swap between, and the music taste they teach.

Why this exists (2026-10-24, the user: "pick an audio that fits the user's
style, and the user can switch between a few suggestions"). The picker
(remix.rank_from) always ranked the pool and then threw away everything
after its first fit, so the only way to another song was the creator's own
folder. Now Make and the bed keep the top N; the Music panel lists them
with a play button and one reason each, and a pick swaps the song as one
undoable turn (app.api_music_swap).

The creator's style steers the ranking two ways, both small next to the fit
itself (tempo, energy shape, feel: remix.rank_from):

- **the look**: a Cozy video leans to acoustic / warm tags, Hype to
  energetic ones (LOOK_WORDS), +LOOK_W when a track's tags or title say so;
- **what they picked before** (`$VIBECUT_CACHE/music-taste.json`): a song
  they chose over the others counts for its tempo and its tags, +PICK_W at
  most; a song offered and passed over PASS_AFTER times counts a little
  against it. Only the creator's own swaps teach it -- the machine's first
  pick doesn't, or it would only ever learn itself.

Every weight is a prior. Nothing is sent anywhere; the taste file is local.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import numpy as np

N = 5                   # songs offered
LOOK_W = 0.06           # a track whose tags match the look [prior]
PICK_W = 0.12           # the most the creator's past picks can add [prior]
PASS_W = 0.04           # a track passed over PASS_AFTER times or more [prior]
PASS_AFTER = 2
KEEP = 40               # picks remembered

LOOK_WORDS = {
    "cozy": ("acoustic", "warm", "folk", "guitar", "ukulele", "chill", "lofi", "soft"),
    "quiet": ("ambient", "piano", "calm", "soft", "relax", "minimal"),
    "film": ("piano", "jazz", "acoustic", "strings", "nostalgic", "vintage"),
    "cinematic": ("cinematic", "orchestral", "epic", "strings", "score", "ambient"),
    "clean": ("pop", "indie", "electronic", "minimal"),
    "hype": ("energetic", "dance", "edm", "upbeat", "electronic", "hip hop", "trap", "phonk"),
    "playful": ("happy", "fun", "ukulele", "whistle", "upbeat", "quirky"),
}

LOCK = threading.Lock()


def _path() -> Path:
    root = Path(os.environ.get("VIBECUT_CACHE", str(Path.home() / ".cache" / "vibecut")))
    return root / "music-taste.json"


def load() -> dict:
    try:
        d = json.loads(_path().read_text())
        return {"picks": list(d.get("picks") or []), "passed": dict(d.get("passed") or {})}
    except (OSError, ValueError):
        return {"picks": [], "passed": {}}


def _save(d: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(p)


def tags_of(t) -> list[str]:
    meta = getattr(t, "meta", None) or {}
    lic = meta.get("licence") or {}
    raw = list(meta.get("tags") or []) + list(lic.get("tags") or []) + list(lic.get("genres") or [])
    return [str(x).lower() for x in raw if x]


def _words(t) -> str:
    return " ".join(tags_of(t) + [str(getattr(t, "title", "") or "").lower()])


def remember(chosen, offered: list) -> None:
    """The creator picked `chosen` out of `offered` (Track objects)."""
    with LOCK:
        d = load()
        d["picks"].append({"id": chosen.id, "title": chosen.title, "bpm": float(chosen.bpm or 0) or None,
                           "tags": tags_of(chosen)[:12], "at": time.time()})
        d["picks"] = d["picks"][-KEEP:]
        for t in offered:
            if t.id != chosen.id:
                d["passed"][t.id] = int(d["passed"].get(t.id, 0)) + 1
        _save(d)


def lean_for(look: str | None, taste: dict | None = None):
    """lean(track) -> a small score bonus from the look and the past picks."""
    taste = taste if taste is not None else load()
    words = LOOK_WORDS.get(look or "", ())
    bpms = [p["bpm"] for p in taste["picks"] if p.get("bpm")]
    liked: dict[str, int] = {}
    for p in taste["picks"]:
        for w in p.get("tags") or []:
            liked[w] = liked.get(w, 0) + 1
    mid = float(np.median(bpms)) if bpms else None
    top = {w for w, _ in sorted(liked.items(), key=lambda kv: -kv[1])[:8]}

    def lean(t) -> float:
        x = 0.0
        text = _words(t)
        if words and any(w in text for w in words):
            x += LOOK_W
        if mid and t.bpm:
            # half or double time is the same feel when picking by ear
            off = min(abs(np.log2(float(t.bpm) / mid)), abs(np.log2(2 * float(t.bpm) / mid)),
                      abs(np.log2(float(t.bpm) / (2 * mid))))
            x += PICK_W / 2 * float(np.clip(1 - off / 0.3, 0, 1))
        if top:
            hit = len(top & set(tags_of(t))) / len(top)
            x += PICK_W / 2 * min(1.0, 2 * hit)
        if taste["passed"].get(t.id, 0) >= PASS_AFTER:
            x -= PASS_W
        return x

    return lean


def why(mx: dict, look: str | None, taste: dict | None = None) -> str:
    """One plain reason for a suggestion."""
    t = mx["track"]
    taste = taste if taste is not None else load()
    bits = [f"{round(mx['bpm'])} BPM"]
    if any(w in _words(t) for w in LOOK_WORDS.get(look or "", ())):
        bits.append(f"fits the {look.title()} look")
    liked = {w for p in taste["picks"] for w in (p.get("tags") or [])}
    common = [w for w in tags_of(t) if w in liked][:2]
    if common:
        bits.append("like songs you picked (" + ", ".join(common) + ")")
    elif not bits[1:]:
        tg = [w for w in tags_of(t) if len(w) < 16][:2]
        if tg:
            bits.append(", ".join(tg))
    return " · ".join(bits)


def public(mx: dict, look: str | None, current: str | None, taste: dict | None = None) -> dict:
    t = mx["track"]
    return {"id": t.id, "title": t.title, "duration": round(float(t.duration), 1), "bpm": round(float(mx["bpm"])),
            "in": mx["in"], "credit": mx.get("credit"), "why": why(mx, look, taste),
            "audio": f"/api/music/audio/{t.id}", "in_use": t.id == current, "score": mx.get("score")}
