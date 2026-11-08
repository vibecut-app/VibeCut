"""The default video's words and length (2026-10-25).

A day on one campus was captioned "Columbia University, morning",
"…, around noon", "…, night" -- seven lines, two identical: a geotag, not
a caption. And the setup promised "about 50 seconds" for a video Make cut
to 29. Each fixture differs from its control in one respect:

- one place all day vs a new place at every stop: the name is said once,
  above the line, where the day arrives there;
- what the picture shows vs nothing labelled: the line says what's
  happening ("lunch"), else how the day moved on ("good morning");
- the same thing twice: never the same line twice, a stop with nothing new
  says nothing (and remix.captions doesn't fill it from its own table);
- a thin shoot vs plenty: the vlog's holds stretch to the length asked
  (vlog.fill) and the setup never promises more than Make can reach
  (vlog.reach, brief.length_for), while plenty of footage is left alone.

    python tests/test_plain_lines.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-lines-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


CAMPUS = (40.8075, -73.9626)
PARK = (40.7812, -73.9665)


def pick(sid, hour, gps=None, labels=None, dur=2.0, filmed=None, activity=10.0):
    shot = SimpleNamespace(id=sid, start=0.0, end=filmed or dur, clip_id=sid, clip_name=sid,
                           when=datetime(2026, 9, 22, hour, 10) if hour is not None else None,
                           gps=gps, labels=labels or {}, activity=activity, score=0.5, vec=None)
    from web.backend import select as sel
    return sel.Pick(shot, "hero", 0.0, dur, 0.5, "", 0)


def main() -> int:
    from web.backend import brief, make, places, remix, select as sel, vlog

    found = {places.key(CAMPUS): {"area": "Columbia University", "city": "New York"},
             places.key(PARK): {"area": "Central Park", "city": "New York"}}
    hours = [8, 9, 12, 15, 18, 21, 22]

    print("one place all day vs a new place at every stop")
    one = sel.Plan(hook=[], sessions=[[pick(f"s{i}", h, CAMPUS)] for i, h in enumerate(hours)], titles=[""] * 7)
    lines = make.plain_lines(one, found)
    named = sum("Columbia University" in l for l in lines)
    check("one place: named once, at the first stop", named == 1 and lines[0].startswith("Columbia University" + make.PLACE_SEP), str(lines))
    said = [l.split(make.PLACE_SEP)[-1] for l in lines if l]
    check("no line said twice", len(said) == len(set(said)), str(said))
    check("two stops in the same hour: the second says nothing new", lines[1] == "", str(lines))
    moving = sel.Plan(hook=[], sessions=[[pick("a", 9, CAMPUS)], [pick("b", 15, PARK)], [pick("c", 18, CAMPUS)]], titles=[""] * 3)
    ml = make.plain_lines(moving, found)
    check("control, a new place at every stop: each is named where the day arrives there",
          [l.split(make.PLACE_SEP)[0] for l in ml] == ["Columbia University", "Central Park", "Columbia University"], str(ml))

    print("what the picture shows vs nothing labelled")
    food = sel.Plan(hook=[], sessions=[[pick("a", 12, None, {"plate": 0.8, "food": 0.6})], [pick("b", 12, None, {})]], titles=["", ""])
    fl = make.plain_lines(food, None)
    check("a plate at noon says lunch, not the hour", fl[0] == "lunch", str(fl))
    check("control, nothing labelled in the same hour: nothing new to say", fl[1] == "", str(fl))
    bare = sel.Plan(hook=[], sessions=[[pick("a", 8)], [pick("b", 21)]], titles=["", ""])
    check("nothing labelled: how the day moved on, never a clock",
          make.plain_lines(bare, None) == ["good morning", "night time"], str(make.plain_lines(bare, None)))

    print("the same thing twice")
    twice = sel.Plan(hook=[], sessions=[[pick("a", 12, None, {"plate": 0.9})], [pick("b", 13, None, {"plate": 0.9})],
                                        [pick("c", 13, None, {"plate": 0.9, "laptop": 0.5})]], titles=[""] * 3)
    tl = make.plain_lines(twice, None)
    check("lunch once; the next stop says nothing; one with something else says that", tl == ["lunch", "", "work work work"], str(tl))
    caps = remix.captions(twice, "a day in my life", None, phrases=tl, clock=False)
    scenes = [c["text"] for c in caps if c["kind"] == "scene"]
    check("an empty line stays empty on screen (remix.captions doesn't fill it from its table)",
          scenes == ["lunch", "work work work"], str(scenes))
    starts = {c["text"]: c["start"] for c in caps if c["kind"] == "scene"}
    check("…and a silent stop's seconds still pass: the next line starts at its own stop, not the silent one's",
          starts.get("work work work") == 4.0, str(starts))

    print("the place rides above the line on the board")
    ops = make.ops(one, make.fingerprint("tall", "balanced", 30.0), None, "tall", "cozy", "A day in my life", set(), lines=lines)
    parts = [o for o in ops if o.get("kind") == "part"]
    subs = [o.get("sub") for o in parts if o.get("sub")]
    check("one overlay carries the place as its sub line; none carries it in its words",
          subs == ["Columbia University"] and not any("Columbia" in o["text"] for o in parts), str([(o["text"], o.get("sub")) for o in parts]))
    check("no overlay repeats another's words", len({o["text"] for o in parts}) == len(parts), str([o["text"] for o in parts]))

    print("a thin shoot vs plenty")
    def thin_plan(n, held=1.0, filmed=6.0):
        return sel.Plan(hook=[], sessions=[[pick(f"t{i}", 9 + i % 12, None, {}, dur=held, filmed=filmed, activity=5.0 + i)] for i in range(n)],
                        titles=[""] * n)
    clips: dict = {}
    real_window = sel.window
    sel.window = lambda clips_, shot, want: (0.0, round(min(want, shot.end - shot.start), 3), want > shot.end - shot.start + 1e-3)
    try:
        thin = thin_plan(6)
        added = vlog.fill(thin, clips, 24.0)
        check("thin: the holds stretch to the length asked", abs(thin.duration - 24.0) < 0.1 and added > 17, f"{thin.duration:.1f} s, +{added:.1f}")
        check("…never past FILL_MAX_S or what was filmed",
              all(p.duration <= min(vlog.FILL_MAX_S, p.shot.end - p.shot.start) + 1e-6 for p in thin.picks))
        tight = thin_plan(6, filmed=1.5)
        vlog.fill(tight, clips, 24.0)
        check("…and a shoot filmed short can't be stretched past itself", abs(tight.duration - 9.0) < 0.1, f"{tight.duration:.1f} s")
        plenty = thin_plan(30, held=1.0)
        before = plenty.duration
        check("control, plenty already at its length: nothing moves", vlog.fill(plenty, clips, 30.0) == 0.0 and plenty.duration == before)
        talk = thin_plan(2)
        check("talk keeps its sentence: a talking shot is never stretched",
              vlog.fill(talk, clips, 20.0, talking={talk.picks[0].shot.id}) > 0 and talk.picks[0].duration == 1.0)
    finally:
        sel.window = real_window

    print("the promise")
    marks = {"seconds": 50, "marks": [{"key": "short", "seconds": 50}], "max": 50}
    check("a vlog never promises more than Make can reach", brief.length_for("tall", marks, 38.4) == 38 and brief.length_for("wide", marks, 38.4) == 38)
    check("control, footage to spare: the mark stands", brief.length_for("tall", marks, 120.0) == 50)
    check("a short keeps its own mark", brief.length_for("short", marks, 10.0) == 50)
    shots = [SimpleNamespace(start=0.0, end=e, score=1 - i / 10, vec=None, gps=None, when=None, clip_id=f"c{i}")
             for i, e in enumerate([8.0, 3.0, 1.0, 12.0])]
    r = vlog.reach(shots, vision=False)
    check("reach: each pickable shot at most FILL_MAX_S, too-short ones not at all",
          abs(r - (vlog.FILL_MAX_S + 3.0 + vlog.FILL_MAX_S)) < 1e-6, f"{r}")

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
