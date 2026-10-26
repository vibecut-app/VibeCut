"""Caption memory: the creator's own lines, learnt from her edits.

sarah, 2026-10-25: captions must come from her, not from a model -- the
way she fine-tuned a slide deck by editing it until it was hers. No tool
in the October 2026 scan learns a creator's words; they save how captions
look and generate what they say (reports/Vlog formats captions and
graphics.md). So VibeCut does the reverse and generates nothing:

1. **Memory.** Every caption she retypes, deletes or writes by hand is
   kept with its context: the line VibeCut had written, what the shot
   showed (top labels), the hour, the place, the weekday, where in the
   video it sat. Local only ($VIBECUT_CACHE/caption-memory.json); never
   mirrored (her text is personal; only derived rules could ever leave).
2. **Her lines first.** A new stop gets one of her own past lines whose
   context matches (labels, time of day, place, position); a line that
   named the place or the hour is kept as a template ("lunch at {place}")
   and filled for the new stop. Never the same line twice in a video; of
   equal matches the one used least. Nothing matches well: VibeCut's own
   phrase table, shaped by her rules, or nothing at all.
3. **Her rules.** Counted from her edits, never guessed: all lowercase,
   how she ends a line (no full stop, "!", "…", an emoji of her own),
   whether she deletes the hour lines ("good morning") or the place line.
   A rule needs MIN_RULE edits and RULE_SHARE agreement; each can be
   switched off on the profile page, and her lines can be added or
   removed there directly ("My lines").

Every number here is a prior. Suggestions are judged the way PRELUDE
(NeurIPS 2024) judges learning from edits: the edit distance from what
VibeCut offered to what she kept should fall from video to video.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from pathlib import Path

MAX_EVENTS = 1000        # oldest edits drop off after this many
MIN_MATCH = 0.45         # context overlap a past line needs to be offered again [prior]
MIN_RULE = 3             # edits before a habit becomes a rule [prior]
RULE_SHARE = 0.7         # share of her lines that must agree [prior]
TOP_LABELS = 6
PLACEHOLDERS = {"what you said here", "part", "title", "chapter", "name", "new caption"}
# What VibeCut writes when only the hour is known (make.HOUR_LINES); deleting these is a habit of its own.
HOUR_WORDS = {"late night", "early start", "good morning", "midday", "afternoon", "evening", "night time",
              "morning", "around noon", "night", "early morning"}
SLOTS = ("place", "weekday", "tod")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐❤]")
_lock = threading.Lock()


def _file() -> Path:
    from .indexer import CACHE
    return CACHE / "caption-memory.json"


def _read() -> dict:
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False))
    tmp.replace(p)


def _norm(s: str | None) -> str:
    return " ".join((s or "").split())


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------

def tod(hour: int | None) -> str:
    """The same buckets as make.time_of_day."""
    if hour is None:
        return ""
    h = hour
    return ("late night" if h < 5 else "early morning" if h < 8 else "morning" if h < 11 else "around noon" if h < 14
            else "afternoon" if h < 17 else "evening" if h < 20 else "night")


def context(labels: dict | list | None, when=None, place: str | None = None, where: str = "stop",
            fmt: str | None = None) -> dict:
    """What a caption sat over: the shot's top labels, the hour and its
    time-of-day word, the weekday, the place, its position in the video."""
    if isinstance(labels, dict):
        top = [k for k, _ in sorted(labels.items(), key=lambda kv: -kv[1])[:TOP_LABELS]]
    else:
        top = list(labels or [])[:TOP_LABELS]
    hour = when.hour if when is not None else None
    return {"labels": top, "hour": hour, "tod": tod(hour), "weekday": when.strftime("%A") if when is not None else "",
            "place": place or "", "where": where, "format": fmt or ""}


def similarity(a: dict, b: dict) -> float:
    """0..1: what the two moments share -- mostly what was in the picture."""
    la, lb = set(a.get("labels") or []), set(b.get("labels") or [])
    lab = len(la & lb) / len(la | lb) if la and lb else 0.0
    same_tod = 1.0 if a.get("tod") and a.get("tod") == b.get("tod") else 0.0
    same_place = 1.0 if a.get("place") and a.get("place") == b.get("place") else 0.0
    same_where = 1.0 if a.get("where") == b.get("where") else 0.0
    return 0.6 * lab + 0.2 * same_tod + 0.15 * same_place + 0.05 * same_where


# --------------------------------------------------------------------------
# 1. memory
# --------------------------------------------------------------------------

def record(before: str | None, after: str | None, ctx: dict, sub_before: str | None = None,
           sub_after: str | None = None, project: str | None = None) -> dict | None:
    """One hand edit of a caption. `before` is what VibeCut (or the editor's
    placeholder) had on screen, `after` what she left. Returns the event,
    or None when nothing changed."""
    b, a = _norm(before), _norm(after)
    if b.lower() in PLACEHOLDERS:
        b = ""
    if a.lower() in PLACEHOLDERS:
        return None
    sb, sa = _norm(sub_before), _norm(sub_after)
    if b == a and sb == sa:
        return None
    kind = "add" if not b and a else "delete" if b and not a else "retype"
    ev = {"kind": kind, "before": b, "after": a, "sub_before": sb, "sub_after": sa, "ctx": ctx,
          "project": project, "at": time.time()}
    with _lock:
        d = _read()
        d["events"] = (d.get("events") or [])[-(MAX_EVENTS - 1):] + [ev]
        _write(d)
    return ev


def events() -> list[dict]:
    return list(_read().get("events") or [])


# --------------------------------------------------------------------------
# 2. her lines, and templates made from them
# --------------------------------------------------------------------------

def templatise(text: str, ctx: dict) -> str:
    """Her line with the facts VibeCut knows swapped for slots: the place she
    named, the weekday, the time-of-day word. "lunch at Joe's Pizza" over a
    shot at Joe's Pizza is "lunch at {place}"."""
    out = text
    for slot in SLOTS:
        v = (ctx.get(slot) or "").strip()
        if len(v) >= 3:
            out = re.sub(re.escape(v), "{" + slot + "}", out, flags=re.I)
    return out


def fill(template: str, ctx: dict) -> str | None:
    """A template for this moment, or None when a slot can't be filled."""
    out = template
    for slot in SLOTS:
        tag = "{" + slot + "}"
        if tag in out:
            v = (ctx.get(slot) or "").strip()
            if not v:
                return None
            out = out.replace(tag, v)
    return out


def lines() -> list[dict]:
    """Her lines: what she wrote by hand or retyped to (latest first, each
    once), plus the ones she added on the profile page, minus the ones she
    removed there. [{text, template, ctx, mine (added on the profile)}]"""
    d = _read()
    removed = {x.lower() for x in d.get("removed") or []}
    seen: set[str] = set()
    out: list[dict] = []
    for ev in reversed(d.get("events") or []):
        t = ev.get("after") or ""
        if not t or t.lower() in seen or t.lower() in removed:
            continue
        seen.add(t.lower())
        out.append({"text": t, "template": templatise(t, ev.get("ctx") or {}), "ctx": ev.get("ctx") or {}, "mine": False})
    for t in d.get("mine") or []:
        if t.lower() not in seen and t.lower() not in removed:
            seen.add(t.lower())
            out.append({"text": t, "template": t, "ctx": {}, "mine": True})
    return out


def add_line(text: str) -> None:
    t = _norm(text)[:80]
    if not t:
        return
    with _lock:
        d = _read()
        d["mine"] = [t] + [x for x in d.get("mine") or [] if x.lower() != t.lower()]
        d["removed"] = [x for x in d.get("removed") or [] if x.lower() != t.lower()]
        _write(d)


def remove_line(text: str) -> None:
    t = _norm(text)
    with _lock:
        d = _read()
        d["mine"] = [x for x in d.get("mine") or [] if x.lower() != t.lower()]
        d["removed"] = sorted({*(d.get("removed") or []), t})
        _write(d)


class Memory:
    """A read of the memory for one Make: her lines and rules, and what this
    video has already used (never the same line twice)."""

    def __init__(self, data: list[dict] | None = None, rule_set: dict | None = None) -> None:
        self.lines = lines() if data is None else data
        self.rules = rules() if rule_set is None else rule_set
        self.used: set[str] = set()
        self._uses = Counter(e.get("after", "").lower() for e in events())

    def suggest(self, ctx: dict) -> tuple[str, str] | None:
        """(line, why) from her own lines, or None when nothing she wrote fits
        this moment well enough."""
        best = None
        for ln in self.lines:
            if ln["ctx"].get("where") and ctx.get("where") and ln["ctx"]["where"] != ctx["where"]:
                continue                  # a title she wrote is not a stop's line, nor the other way round
            text = fill(ln["template"], ctx)
            if not text or text.lower() in self.used:
                continue
            # a line she added on the profile page has no context: it matches on its words alone
            score = similarity(ln["ctx"], ctx) if ln["ctx"] else _word_match(text, ctx)
            if score < MIN_MATCH:
                continue
            key = (score, -self._uses.get(ln["text"].lower(), 0))
            if best is None or key > best[0]:
                best = (key, text, ln)
        if best is None:
            return None
        _, text, ln = best
        self.used.add(text.lower())
        why = "one of your lines" if ln["template"] == ln["text"] else f"your line “{ln['text']}”, for this place and time"
        return text, why

    def shape(self, text: str, hour_line: bool = False) -> str:
        """VibeCut's own line in her style: her case and ending; empty when
        she deletes this kind of line."""
        r = self.rules
        if not text:
            return ""
        if hour_line and r.get("drop_hour", {}).get("on"):
            return ""
        out = text
        if r.get("case", {}).get("on"):
            out = out.lower()
        end = r.get("end", {})
        if end.get("on"):
            out = out.rstrip(".!…?~ ")
            if end["value"] != "none":
                out = f"{out} {end['value']}" if _EMOJI.match(end["value"]) else out + end["value"]
        if out.lower() in self.used:
            return ""
        self.used.add(out.lower())
        return out

    def keep_place(self) -> bool:
        return not self.rules.get("drop_place", {}).get("on")


def _word_match(text: str, ctx: dict) -> float:
    """A profile line against a moment: does it name what the picture shows?"""
    words = set(re.findall(r"[a-z]+", text.lower()))
    labels = {w for lab in ctx.get("labels") or [] for w in lab.lower().split("_")}
    return 0.6 if words & labels else 0.0


# --------------------------------------------------------------------------
# 3. her rules, counted from her edits
# --------------------------------------------------------------------------

def _ending(t: str) -> str:
    t = t.rstrip()
    if not t:
        return "none"
    if _EMOJI.match(t[-1]):
        return t[-1]
    if t.endswith("…") or t.endswith("..."):
        return "…"
    return t[-1] if t[-1] in ".!?~" else "none"


def rules() -> dict:
    """{rule id: {on, value, n, says}} -- only rules her edits support."""
    d = _read()
    off = set(d.get("off") or [])
    evs = d.get("events") or []
    # her line-by-line captions; a title is set differently (Title Case is normal there)
    hers = [e["after"] for e in evs if e.get("after") and re.search(r"[A-Za-z]", e["after"])
            and (e.get("ctx") or {}).get("where") != "title"]
    out: dict[str, dict] = {}
    if len(hers) >= MIN_RULE:
        low = sum(t == t.lower() for t in hers) / len(hers)
        if low >= RULE_SHARE:
            out["case"] = {"value": "lower", "n": len(hers), "says": "All lowercase"}
        ends = Counter(_ending(t) for t in hers)
        top, n = ends.most_common(1)[0]
        if n / len(hers) >= RULE_SHARE:
            says = ("No full stop at the end" if top == "none" else f"You end lines with {top}")
            out["end"] = {"value": top, "n": len(hers), "says": says}
        words = sorted(len(t.split()) for t in hers)
        out["length"] = {"value": f"{words[0]}–{words[-1]}", "n": len(hers), "says": f"{words[0]}–{words[-1]} words a line",
                         "describes": True}
    hour_deletes = [e for e in evs if e.get("kind") == "delete" and e.get("before", "").lower().rstrip(".!") in HOUR_WORDS]
    if len(hour_deletes) >= MIN_RULE:
        out["drop_hour"] = {"value": True, "n": len(hour_deletes), "says": "You delete time-of-day lines like “good morning”"}
    place_drops = [e for e in evs if e.get("sub_before") and not e.get("sub_after") and e.get("kind") != "add"]
    if len(place_drops) >= MIN_RULE:
        out["drop_place"] = {"value": True, "n": len(place_drops), "says": "You take the place name off"}
    for k, v in out.items():
        v["on"] = k not in off and not v.get("describes")
    return out


def switch(rule: str, on: bool) -> None:
    with _lock:
        d = _read()
        off = set(d.get("off") or [])
        (off.discard if on else off.add)(rule)
        d["off"] = sorted(off)
        _write(d)


def voice() -> dict:
    """The profile page's card: her rules in plain words, her lines, and how
    VibeCut's offers have been landing (PRELUDE's measure: edit distance
    from what was offered to what she kept, oldest half vs newest half)."""
    evs = events()
    return {"rules": [{"id": k, **v} for k, v in rules().items()],
            "lines": [{"text": ln["text"], "mine": ln["mine"]} for ln in lines()][:60],
            "edits": len(evs), "trend": distance_trend(evs)}


def distance(a: str, b: str) -> int:
    """Levenshtein distance by character."""
    a, b = a or "", b or ""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def distance_trend(evs: list[dict]) -> dict | None:
    """Mean edit distance from VibeCut's line to hers, first half of her
    edits vs the second; None under 2 × MIN_RULE retypes."""
    xs = [distance(e["before"], e["after"]) for e in evs if e.get("kind") == "retype"]
    if len(xs) < 2 * MIN_RULE:
        return None
    h = len(xs) // 2
    return {"before": round(sum(xs[:h]) / h, 1), "after": round(sum(xs[h:]) / (len(xs) - h), 1), "n": len(xs)}
