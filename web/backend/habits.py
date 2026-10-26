"""The second video is better because of the first.

What the creator does to one video -- the shots they remove, the ones they
bring back or hold longer, the music they switch off, the lines they
retype -- is the clearest statement of taste there is, and until
2026-10-18 it was recorded and then forgotten. This module turns it into
*habits*, with three rules that keep it honest:

1. **A habit needs more than one video.** The same thing done on
   MIN_PROJECTS different videos (whiteboard shots removed twice, food
   held longer twice, music off twice) is a habit; once is an edit.
2. **A habit biases, it never decides.** It adds a small weight per label
   to the moment picker (select.hero_score), sets the music switch's
   default, and lends the writer the creator's own phrasing. The hook, the
   beat and the ending are untouched.
3. **Every use is said, and undoable in one tap.** The Make turn's reply
   carries "Kept more food and fewer lecture shots, as you did last
   time"; Undo switches that habit off, records that, and the video is
   made again without it. A habit used three times without being undone
   is offered once as a rule in the creator's words (preferences.py); it
   never becomes one by itself.

Signals are gathered from the turn log when a video is exported
(`record`), kept on the project (`events`, kind "signals"), and read
across every project when a video is made (`derive`). Habits live in
$VIBECUT_CACHE/habits.json with their evidence and their off switch.
Weights are priors.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .indexer import CACHE

FILE = CACHE / "habits.json"
MIN_PROJECTS = 2          # videos a thing must happen on before it is a habit
LABEL_W = 0.2             # the bias a label habit adds to a shot's score (hero_score is ~0..1)
TOP_LABELS = 3            # labels per shot that count as "what it was"
MAX_PHRASES = 20
SUGGEST_AFTER = 3         # uses without an undo before a habit is offered as a rule
MACHINE_TEXTS = ("Made your video", "Music and the beat", "Captions, as you asked", "Took out shots that repeat another",
                 "Smoother cuts", "Remix", "You picked a version")   # "No music" is the creator's own switch, so it counts
_lock = threading.Lock()


# --------------------------------------------------------------------------
# signals: what one video's edits say
# --------------------------------------------------------------------------

def _top(labels: dict | None) -> list[str]:
    return [k for k, _ in sorted((labels or {}).items(), key=lambda kv: -kv[1])[:TOP_LABELS]]


def signals(turns: list, cat) -> list[dict]:
    """From the live turns of a session: removed / kept shots with their
    labels, the music switched off by hand, lines retyped. Turns the machine
    made (the bed, the captions) are not the creator's hand and don't count."""
    out: list[dict] = []
    for t in turns:
        if t.undone or t.kind != "direct" or any(t.text.startswith(m) for m in MACHINE_TEXTS):
            continue
        for o in t.ops:
            op = o.get("op")
            if op == "drop_shot" and o.get("shot"):
                s = cat.shots.get(str(o["shot"]).split("~")[0])
                if s is not None:
                    out.append({"what": "removed", "labels": _top(s.labels), "hour": s.when.hour if s.when else None})
            elif op in ("add_shot", "swap_shot"):
                sid = o.get("with") or o.get("shot") or o.get("id")
                s = cat.shots.get(str(sid)) if sid else None
                if s is not None:
                    out.append({"what": "kept", "labels": _top(s.labels), "hour": s.when.hour if s.when else None})
            elif op == "trim" and o.get("edge") == "out" and o.get("shot"):
                s = cat.shots.get(str(o["shot"]).split("~")[0])
                if s is not None and float(o.get("to", 0)) > 0:
                    out.append({"what": "held", "labels": _top(s.labels), "hour": s.when.hour if s.when else None})
            elif op == "set_music" and o.get("track") is None:
                out.append({"what": "music_off"})
            elif op == "edit_overlay" and isinstance(o.get("text"), str) and o["text"].strip():
                out.append({"what": "retyped", "text": " ".join(o["text"].split())[:80]})
    return out


def record(project, turns: list, cat) -> list[dict]:
    """Keep this video's signals on its record (called when it is exported)."""
    sig = signals(turns, cat)
    project.events = [e for e in project.events if e.get("kind") != "signals"]
    project.events.append({"kind": "signals", "at": time.time(), "items": sig})
    return sig


# --------------------------------------------------------------------------
# habits: what more than one video says
# --------------------------------------------------------------------------

def _read() -> dict:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {"habits": [], "phrases": []}


def _write(data: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(FILE)


def load() -> list[dict]:
    return _read().get("habits", [])


def derive(projects: list) -> list[dict]:
    """Habits from every project's signals, merged with what was already
    known (its off switch and use count survive). `projects` are Project
    records or plain dicts with name / events."""
    seen_removed: dict[str, set] = {}
    seen_kept: dict[str, set] = {}
    music_off: set = set()
    phrases: list[str] = []
    for p in projects:
        name = getattr(p, "name", None) or (p.get("name") if isinstance(p, dict) else "") or "?"
        events = getattr(p, "events", None) or (p.get("events") if isinstance(p, dict) else []) or []
        for e in events:
            if e.get("kind") == "scene_verdict" and e.get("word") in ("cut", "longer"):
                # one word per scene after watching (vlog.py step 8): cut = removed, longer = held
                for l in e.get("labels", [])[:TOP_LABELS]:
                    (seen_removed if e["word"] == "cut" else seen_kept).setdefault(l, set()).add(name)
                continue
            if e.get("kind") != "signals":
                continue
            for s in e.get("items", []):
                if s["what"] == "removed":
                    for l in s.get("labels", []):
                        seen_removed.setdefault(l, set()).add(name)
                elif s["what"] in ("kept", "held"):
                    for l in s.get("labels", []):
                        seen_kept.setdefault(l, set()).add(name)
                elif s["what"] == "music_off":
                    music_off.add(name)
                elif s["what"] == "retyped" and s.get("text") and s["text"] not in phrases:
                    phrases.append(s["text"])
    with _lock:
        data = _read()
        old = {h["id"]: h for h in data.get("habits", [])}
        habits: list[dict] = []

        def put(hid: str, kind: str, label: str | None, weight: float, where: set, text: str) -> None:
            prev = old.get(hid, {})
            habits.append({"id": hid, "kind": kind, "label": label, "weight": weight, "n": len(where),
                           "evidence": sorted(where), "text": text,
                           "used": prev.get("used", 0), "off": prev.get("off", False), "since": prev.get("since") or time.time()})

        for l, where in seen_removed.items():
            if len(where) >= MIN_PROJECTS and l not in seen_kept:
                put(f"avoid:{l}", "avoid", l, -LABEL_W, where, f"fewer {l} shots")
        for l, where in seen_kept.items():
            if len(where) >= MIN_PROJECTS and l not in seen_removed:
                put(f"prefer:{l}", "prefer", l, LABEL_W, where, f"more {l} shots")
        if len(music_off) >= MIN_PROJECTS:
            put("music_off", "music_off", None, 0.0, music_off, "no music unless you ask")
        data["habits"] = habits
        data["phrases"] = (phrases + [x for x in data.get("phrases", []) if x not in phrases])[:MAX_PHRASES]
        _write(data)
    return habits


def active(habits: list[dict] | None = None) -> list[dict]:
    return [h for h in (habits if habits is not None else load()) if not h.get("off")]


def bias(habits: list[dict] | None = None) -> dict[str, float]:
    """Label -> weight for the moment picker, from the habits that are on."""
    return {h["label"]: float(h["weight"]) for h in active(habits) if h.get("label")}


def music_default(habits: list[dict] | None = None) -> bool | None:
    """False when the creator keeps switching music off; None = no habit."""
    return False if any(h["id"] == "music_off" for h in active(habits)) else None


def phrases() -> list[str]:
    return _read().get("phrases", [])


def remember_phrase(text: str) -> None:
    text = " ".join((text or "").split())[:80]
    if not text:
        return
    with _lock:
        data = _read()
        ph = [text] + [x for x in data.get("phrases", []) if x != text]
        data["phrases"] = ph[:MAX_PHRASES]
        _write(data)


def used(ids: list[str]) -> list[dict]:
    """Count a use for each habit that acted; returns those now due to be offered as a rule."""
    due = []
    with _lock:
        data = _read()
        for h in data.get("habits", []):
            if h["id"] in ids:
                h["used"] = h.get("used", 0) + 1
                if h["used"] >= SUGGEST_AFTER and not h.get("offered"):
                    due.append(h)
        _write(data)
    return due


def switch(hid: str, off: bool) -> dict | None:
    """The one tap: a habit on or off, recorded."""
    with _lock:
        data = _read()
        for h in data.get("habits", []):
            if h["id"] == hid:
                h["off"] = bool(off)
                h.setdefault("history", []).append({"at": time.time(), "off": bool(off)})
                _write(data)
                return h
    return None


def mark_offered(hid: str) -> None:
    with _lock:
        data = _read()
        for h in data.get("habits", []):
            if h["id"] == hid:
                h["offered"] = True
        _write(data)


def describe(habits: list[dict]) -> str:
    """One line for the reply: what the habits did this time."""
    if not habits:
        return ""
    more = [h["label"] for h in habits if h["kind"] == "prefer"]
    fewer = [h["label"] for h in habits if h["kind"] == "avoid"]
    parts = []
    if more:
        parts.append("more " + ", ".join(more))
    if fewer:
        parts.append("fewer " + ", ".join(fewer) + " shots")
    if any(h["id"] == "music_off" for h in habits):
        parts.append("no music")
    return ("Kept " + " and ".join(parts) + ", as you did last time.") if parts else ""
