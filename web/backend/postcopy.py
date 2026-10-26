"""The words a finished video is posted with, from what the edit knows.

Every platform asks for text next to the file: TikTok and Instagram a
caption, YouTube a title and a description. The Share box had nothing to
paste for most edits (a made video rarely has a title on screen), so the
creator faced a blank box at the last step. This writes a first draft from
the edit itself -- never from the model, never a frame:

- **The line**: the title on screen if there is one, else where and when it
  was filmed, the way a person would say it ("A Saturday in Brooklyn",
  "3 days in Lisbon"), from the clips in the edit (their recording time and
  the place names places.py already looked up; cache only, no new lookups).
- **Hashtags**: a few, never a wall (`MAX_TAGS`): what kind of video it is
  (a day, a weekend, days away), #vlog, the city and the first named place,
  and #shorts when YouTube will make it a Short.
- **YouTube chapters**: chapter titles on screen, else the stops by place,
  written the way YouTube reads them -- the first at 0:00, at least
  `MIN_CHAPTERS`, each at least `CHAPTER_MIN_S` long. Not for a Short.
- **The music credit** stays apart: the Share box adds it to whatever the
  creator writes, because the song's licence asks for it.

The creator edits all of it; nothing here is posted by itself.
"""

from __future__ import annotations

import re
from collections import Counter

from . import places
from . import storyboard as sb

MAX_TAGS = 5            # a few tags read as a creator; a wall reads as spam [prior]
MIN_CHAPTERS = 3        # YouTube shows chapters only from three
CHAPTER_MIN_S = 10.0    # … each at least ten seconds long
TITLE_MAX = 100         # YouTube's title limit


def _tag(name: str) -> str | None:
    """'Morningside Heights' -> '#MorningsideHeights'; letters in any script kept."""
    words = re.findall(r"\w+", name or "", flags=re.UNICODE)
    words = [w for w in words if not w.isdigit()]
    if not words:
        return None
    return "#" + "".join(w[:1].upper() + w[1:] for w in words)


def _clock(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _found(clips: list[dict]) -> dict:
    """Place answers already in the cache for these clips (no new lookups)."""
    gps = [c.get("gps") for c in clips if c.get("gps")]
    return places.lookup(gps, ask=lambda keys: []) if gps else {}


def stops(items: list[dict], clips: dict[str, dict], found: dict) -> list[dict]:
    """Where the edit goes, in edit order: [{t, name, city}], a new stop when
    the named place changes."""
    out: list[dict] = []
    for it in items:
        c = clips.get(it.get("clip_id") or "")
        if not c or not c.get("gps"):
            continue
        r = found.get(places.key(c["gps"]) or "")
        name = places.short_name(r)
        if not name:
            continue
        if not out or out[-1]["name"] != name:
            out.append({"t": float(it["seq_start"]), "name": name, "city": (r or {}).get("city") or None})
    return out


def line(items: list[dict], clips: dict[str, dict], where: list[dict], title: str | None = None) -> str:
    """One line that says what the video is."""
    if title and title.strip():
        return title.strip()[:TITLE_MAX]
    whens = sorted(w for w in (sb.parse_when(clips.get(it.get("clip_id") or "", {}).get("capture_time"))
                               for it in items) if w)
    days = sorted({w.date() for w in whens})
    cities = Counter(s["city"] for s in where if s["city"])
    place = cities.most_common(1)[0][0] if cities else (where[0]["name"] if where else None)
    at = f" in {place}" if place else ""
    if len(days) >= 2:
        weekend = all(d.weekday() >= 5 for d in days) and len(days) <= 3
        return ("A weekend" + at) if weekend else f"{len(days)} days{at or ' away'}"
    if whens:
        a, b = whens[0], whens[-1]
        if a.hour >= 17:
            return "An evening" + (at or " out")
        if a.hour < 12 and b.hour >= 17:
            return f"A {a.strftime('%A')}{at or ' in my life'}, morning to night"
        return f"A {a.strftime('%A')}{at or ' in my life'}"
    return f"A day{at}" if at else "A day in my life"


def hashtags(items: list[dict], clips: dict[str, dict], where: list[dict], short: bool) -> list[str]:
    whens = sorted(w for w in (sb.parse_when(clips.get(it.get("clip_id") or "", {}).get("capture_time"))
                               for it in items) if w)
    days = {w.date() for w in whens}
    weekend = 2 <= len(days) <= 3 and all(d.weekday() >= 5 for d in days)
    kind = "#weekendvlog" if weekend else "#travel" if len(days) >= 2 else "#dayinmylife"
    tags = [kind, "#vlog"]
    cities = Counter(s["city"] for s in where if s["city"])
    if cities:
        tags.append(_tag(cities.most_common(1)[0][0]))
    named = next((s["name"] for s in where if s["name"] not in cities), None)
    if named:
        tags.append(_tag(named))
    if short:
        tags.append("#shorts")
    seen, out = set(), []
    for t in tags:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_TAGS]


def chapters(marks: list[tuple[float, str]], total: float) -> list[dict]:
    """YouTube's rules: first at 0:00, each ≥ CHAPTER_MIN_S, at least
    MIN_CHAPTERS, else none. A mark too close to the last is folded into it."""
    out: list[dict] = []
    for t, name in sorted(marks):
        name = (name or "").strip()
        if not name:
            continue
        if not out:
            out.append({"t": 0.0, "name": name})
        elif t - out[-1]["t"] >= CHAPTER_MIN_S and name != out[-1]["name"]:
            out.append({"t": float(t), "name": name})
    if out and total - out[-1]["t"] < CHAPTER_MIN_S:
        out.pop()
    return out if len(out) >= MIN_CHAPTERS else []


def draft(items: list[dict], clips: dict[str, dict], overlays: list[dict], total: float, short: bool) -> dict:
    """{line, hashtags, caption, chapters, youtube: {title, description}}.
    `overlays` as overlays.resolve gives them (with start times)."""
    used = [clips[i] for i in {it.get("clip_id") for it in items} if i in clips]
    where = stops(items, clips, _found(used))
    title = next((o["text"] for o in overlays if o.get("kind") == "title" and o.get("text")), None)
    first = line(items, clips, where, title)
    tags = hashtags(items, clips, where, short)
    heads = [(o["start"], o["text"]) for o in overlays if o.get("kind") == "heading" and o.get("text")]
    chap = [] if short else chapters(heads if len(heads) >= MIN_CHAPTERS else [(s["t"], s["name"]) for s in where], total)
    desc = [first]
    if chap:
        desc += ["", *(f"{_clock(c['t'])} {c['name']}" for c in chap)]
    if tags:
        desc += ["", " ".join(tags)]
    return {"line": first, "hashtags": tags, "caption": first + ("\n\n" + " ".join(tags) if tags else ""),
            "chapters": chap, "youtube": {"title": first[:TITLE_MAX], "description": "\n".join(desc)}}
