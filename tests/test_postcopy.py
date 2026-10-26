"""Words to post with: a draft from where and when the edit was filmed.

From a made-up edit of known places and times: the line names the city
and the day ("A Saturday in Lisbon, morning to night"), several days read
as days away, an evening as an evening; a title on screen wins; hashtags
are a few, CamelCase, deduplicated, #shorts only for a Short; chapters
follow YouTube's rules (first at 0:00, ≥ 3, each ≥ 10 s, too-close marks
folded, none for a Short) and come from chapter titles before places; no
GPS still gives a line.

    python tests/test_postcopy.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-postcopy-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


PLACES = {  # rounded "lat,lon" -> Apple's answer, as places.py caches it
    "38.711,-9.139": {"at": "38.711,-9.139", "place": "Time Out Market", "area": "Cais do Sodré", "city": "Lisbon"},
    "38.714,-9.133": {"at": "38.714,-9.133", "place": "", "area": "Alfama", "city": "Lisbon"},
    "38.693,-9.206": {"at": "38.693,-9.206", "place": "Belém Tower", "area": "Belém", "city": "Lisbon"},
}
GPS = {"a": [38.7111, -9.1391], "b": [38.7142, -9.1331], "c": [38.6931, -9.2061]}


def edit(times: dict[str, str], lengths=(14, 12, 16), gps=True):
    clips = {k: {"capture_time": t, **({"gps": GPS[k]} if gps else {})} for k, t in times.items()}
    items, at = [], 0.0
    for k, d in zip(times, lengths):
        items.append({"kind": "shot", "clip_id": k, "seq_start": at, "seq_end": at + d})
        at += d
    return items, clips, at


def main() -> int:
    from web.backend import places, postcopy
    places._cache_file().parent.mkdir(parents=True, exist_ok=True)
    places._cache_file().write_text(json.dumps(PLACES))

    day = {"a": "2026-09-19T09:10:00", "b": "2026-09-19T13:30:00", "c": "2026-09-19T19:05:00"}
    items, clips, total = edit(day)
    d = postcopy.draft(items, clips, [], total, short=False)
    check("one day, morning to night, named by its city", d["line"] == "A Saturday in Lisbon, morning to night", d["line"])
    check("a few hashtags: the kind, #vlog, the city, a place", d["hashtags"] == ["#dayinmylife", "#vlog", "#Lisbon", "#TimeOutMarket"],
          str(d["hashtags"]))
    check("the caption is the line and the tags", d["caption"] == d["line"] + "\n\n" + " ".join(d["hashtags"]))
    check("chapters by place, the first at 0:00", [(c["t"], c["name"]) for c in d["chapters"]]
          == [(0.0, "Time Out Market"), (14.0, "Alfama"), (26.0, "Belém Tower")], json.dumps(d["chapters"]))
    check("YouTube's description carries them", "0:00 Time Out Market\n0:14 Alfama\n0:26 Belém Tower" in d["youtube"]["description"],
          d["youtube"]["description"])

    s = postcopy.draft(items, clips, [], total, short=True)
    check("a Short: #shorts, no chapters", "#shorts" in s["hashtags"] and not s["chapters"] and len(s["hashtags"]) <= postcopy.MAX_TAGS)

    trip = {"a": "2026-09-18T10:00:00", "b": "2026-09-19T12:00:00", "c": "2026-09-21T15:00:00"}
    items2, clips2, total2 = edit(trip)
    t = postcopy.draft(items2, clips2, [], total2, short=False)
    check("several days read as days away", t["line"] == "3 days in Lisbon" and t["hashtags"][0] == "#travel", t["line"] + " " + str(t["hashtags"]))
    wk = {"a": "2026-09-19T10:00:00", "b": "2026-09-20T12:00:00", "c": "2026-09-20T15:00:00"}
    w = postcopy.draft(*edit(wk)[:2], [], 42, short=False)
    check("a Saturday and Sunday is a weekend", w["line"] == "A weekend in Lisbon" and w["hashtags"][0] == "#weekendvlog",
          w["line"] + " " + str(w["hashtags"]))
    eve = {"a": "2026-09-19T19:00:00", "b": "2026-09-19T20:30:00", "c": "2026-09-19T22:05:00"}
    e = postcopy.draft(*edit(eve)[:2], [], 42, short=False)
    check("an evening", e["line"] == "An evening in Lisbon", e["line"])

    title = [{"kind": "title", "text": "Lisbon, finally", "start": 0}]
    check("a title on screen wins", postcopy.draft(items, clips, title, total, short=False)["line"] == "Lisbon, finally")
    heads = [{"kind": "heading", "text": n, "start": t} for n, t in (("Breakfast", 0.4), ("The old town", 15), ("Sunset", 30))]
    h = postcopy.draft(items, clips, heads, total, short=False)
    check("chapter titles on screen come before places", [c["name"] for c in h["chapters"]] == ["Breakfast", "The old town", "Sunset"]
          and h["chapters"][0]["t"] == 0.0, json.dumps(h["chapters"]))

    check("a mark under 10 s after the last is folded", postcopy.chapters([(0, "A"), (4, "B"), (12, "C"), (30, "D")], 60)
          == [{"t": 0.0, "name": "A"}, {"t": 12.0, "name": "C"}, {"t": 30.0, "name": "D"}])
    check("fewer than three is none", postcopy.chapters([(0, "A"), (20, "B")], 60) == [])
    check("a last chapter under 10 s from the end is dropped", postcopy.chapters([(0, "A"), (20, "B"), (40, "C"), (55, "D")], 60)
          == [{"t": 0.0, "name": "A"}, {"t": 20.0, "name": "B"}, {"t": 40.0, "name": "C"}])

    n = postcopy.draft(*edit(day, gps=False)[:2], [], total, short=False)
    check("no GPS still gives a line, and no place tags", n["line"] == "A Saturday in my life, morning to night"
          and n["hashtags"] == ["#dayinmylife", "#vlog"] and not n["chapters"], n["line"] + " " + str(n["hashtags"]))
    check("tags keep letters in any script", postcopy._tag("São Paulo") == "#SãoPaulo" and postcopy._tag("东京 塔") == "#东京塔"
          and postcopy._tag("123") is None)
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
