"""Caption memory and her-lines-first captions (captionmem.py, 2026-10-25).

sarah: captions come from her, not from a model. Each fixture differs from
its control in one respect:

- a moment like one she captioned vs an unrelated one: her line comes back
  only for the matching moment;
- a line naming the place she was at vs one that doesn't: the first becomes
  a template filled with the new place ("lunch at {place}");
- the same moment twice in one video: her line once, never repeated;
- three lowercase edits vs mixed case: only the first makes a rule; three
  deleted "good morning"s vs one: only the first drops hour lines; a rule
  switched off stops acting;
- leave-one-video-out on a synthetic creator: what VibeCut offers lands
  closer to her final line (edit distance) than today's phrase table;
- through the API: retyping the made title, writing over a new caption's
  placeholder and deleting record one event each with its moment; adding
  the placeholder and moving a caption record nothing.

    python tests/test_caption_memory.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-capmem-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def fresh() -> None:
    from web.backend import captionmem
    try:
        captionmem._file().unlink()
    except OSError:
        pass


def at(h: int, day: int = 22) -> datetime:
    return datetime(2026, 9, day, h, 10)


def main() -> int:
    from web.backend import captionmem as cm, make, select as sel

    print("her line comes back for a moment like the one she captioned")
    fresh()
    cm.record("lunch", "noodles with mei", cm.context({"plate": 0.9, "food": 0.8, "table": 0.5}, at(12)))
    mem = cm.Memory()
    hit = mem.suggest(cm.context({"plate": 0.8, "food": 0.7}, at(13)))
    check("a plate at lunchtime: her line", hit is not None and hit[0] == "noodles with mei", str(hit))
    miss = cm.Memory().suggest(cm.context({"stairs": 0.9, "building": 0.6}, at(9)))
    check("control, stairs in the morning: nothing of hers fits, so nothing is offered", miss is None, str(miss))

    print("a line that named the place becomes a template")
    fresh()
    cm.record("lunch", "lunch at Joe's Pizza", cm.context({"plate": 0.9, "pizza": 0.7}, at(12), "Joe's Pizza"))
    cm.record("coffee run", "the usual oat latte", cm.context({"cup": 0.9}, at(9), "Blue Bottle"))
    mem = cm.Memory()
    t = mem.suggest(cm.context({"plate": 0.9, "pizza": 0.6}, at(13), "Prince Street Pizza"))
    check("the new place fills her template", t is not None and t[0] == "lunch at Prince Street Pizza", str(t))
    check("…and it says it was her line, for this place", t is not None and "Joe's Pizza" in t[1], str(t))
    u = cm.Memory().suggest(cm.context({"cup": 0.9}, at(9), "Another Cafe"))
    check("control, a line that didn't name the place stays as she wrote it", u is not None and u[0] == "the usual oat latte", str(u))
    no_place = cm.Memory().suggest(cm.context({"plate": 0.9, "pizza": 0.6}, at(13), None))
    check("a template whose place isn't known isn't filled with nothing", no_place is None or "{" not in no_place[0], str(no_place))

    print("never the same line twice in a video")
    mem = cm.Memory()
    first = mem.suggest(cm.context({"cup": 0.9}, at(9)))
    second = mem.suggest(cm.context({"cup": 0.9}, at(10)))
    check("her line once; the second coffee gets something else or nothing", first and (second is None or second[0] != first[0]),
          f"{first} / {second}")

    print("her rules, only from her edits")
    fresh()
    for b, a in [("Coffee run", "coffee first"), ("Class time", "back to class"), ("Heading out", "off we go")]:
        cm.record(b, a, cm.context({}, at(10)))
    r = cm.rules()
    check("three lowercase lines: an all-lowercase rule", r.get("case", {}).get("on"), str(r))
    check("…and her ending: no full stop", r.get("end", {}).get("value") == "none", str(r.get("end")))
    check("VibeCut's own line comes out in her case", cm.Memory().shape("Up We Go.") == "up we go", cm.Memory().shape("Up We Go."))
    fresh()
    for b, a in [("Coffee run", "Coffee First"), ("Class time", "back to class"), ("Heading out", "Off We Go")]:
        cm.record(b, a, cm.context({}, at(10)))
    check("control, mixed case: no case rule", "case" not in cm.rules(), str(cm.rules()))
    fresh()
    for h in (8, 9, 21):
        cm.record("good morning" if h < 12 else "night time", "", cm.context({}, at(h)))
    check("three hour lines deleted: hour lines are dropped", cm.rules().get("drop_hour", {}).get("on"))
    check("…so VibeCut's hour line says nothing", cm.Memory().shape("good morning", hour_line=True) == "")
    cm.switch("drop_hour", False)
    check("switched off on the profile: it says the hour line again", cm.Memory().shape("good morning", hour_line=True) == "good morning")
    fresh()
    cm.record("good morning", "", cm.context({}, at(8)))
    check("control, one deletion: no rule", "drop_hour" not in cm.rules())

    print("in Make's captions")
    fresh()
    cm.record("lunch", "noodles with mei", cm.context({"plate": 0.9, "food": 0.8}, at(12)))

    def pick(sid, h, labels):
        return sel.Pick(SimpleNamespace(id=sid, start=0.0, end=2.0, clip_id=sid, clip_name=sid, when=at(h), gps=None,
                                        labels=labels, activity=10.0), "hero", 0.0, 2.0, 0.5, "", 0)
    plan = sel.Plan(hook=[], sessions=[[pick("a", 9, {"cup": 0.9})], [pick("b", 12, {"plate": 0.9, "food": 0.7})],
                                       [pick("c", 19, {"plate": 0.8, "food": 0.6})]], titles=[""] * 3)
    lines = make.plain_lines(plan, None)
    check("her line where the moment matches, the table elsewhere, never twice",
          lines[0] == "coffee run" and lines[1] == "noodles with mei" and lines[2] != "noodles with mei", str(lines))
    fresh()
    check("control, no memory: today's table lines", make.plain_lines(plan, None)[1] == "lunch", str(make.plain_lines(plan, None)))

    print("titles stay titles")
    fresh()
    for t in ("Saturday In Morningside", "A Very Long Week", "Paris, Finally"):
        cm.record("A day in my life", t, cm.context({"plate": 0.9}, at(12), None, "title"))
    check("a title she wrote is never offered as a stop's line", cm.Memory().suggest(cm.context({"plate": 0.9}, at(12))) is None)
    check("…and her Title Case titles make no case rule for captions", "case" not in cm.rules(), str(cm.rules()))

    print("profile lines and switches")
    fresh()
    cm.add_line("matcha o'clock")
    v = cm.voice()
    check("a line added on the profile is in her lines", any(l["text"] == "matcha o'clock" and l["mine"] for l in v["lines"]))
    hit = cm.Memory().suggest(cm.context({"matcha": 0.9, "cup": 0.8}, at(15)))
    check("…and offered when the picture shows what it names", hit is not None and hit[0] == "matcha o'clock", str(hit))
    cm.remove_line("matcha o'clock")
    check("removed: never offered again", cm.Memory().suggest(cm.context({"matcha": 0.9}, at(15))) is None)

    print("leave one video out: closer to what she writes than the table")
    # a synthetic creator with a steady voice: lowercase, a line per scene, the place in her lunch lines
    shoots = [
        [("cup", 9, "Cafe Nana", "coffee first"), ("plate", 12, "Joe's Pizza", "lunch at Joe's Pizza"), ("book", 15, "Butler Library", "library grind")],
        [("cup", 8, "Blue Bottle", "coffee first"), ("plate", 13, "Sweetgreen", "lunch at Sweetgreen"), ("book", 16, "Butler Library", "library grind")],
        [("cup", 9, "Joe Coffee", "coffee first"), ("plate", 12, "Mamoun's", "lunch at Mamoun's"), ("book", 14, "Avery Library", "library grind")],
    ]
    table = {"cup": "coffee run", "plate": "lunch", "book": "study time"}
    ours, base = [], []
    for held in range(len(shoots)):
        fresh()
        for i, shoot in enumerate(shoots):
            if i == held:
                continue
            for lab, h, place, mine in shoot:
                cm.record(table[lab], mine, cm.context({lab: 0.9}, at(h, 20 + i), place))
        mem = cm.Memory()
        for lab, h, place, mine in shoots[held]:
            got = mem.suggest(cm.context({lab: 0.9}, at(h, 25), place))
            offered = got[0] if got else mem.shape(table[lab])
            ours.append(cm.distance(offered, mine))
            base.append(cm.distance(table[lab], mine))
    check("mean edit distance to her final line is lower than the table's", sum(ours) < sum(base) * 0.5,
          f"ours {sum(ours) / len(ours):.1f} vs table {sum(base) / len(base):.1f}")

    print("through the API")
    fresh()
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend, bed
    clips = [clip(PTMP / f"cm-{i}.mp4", 6 + i % 3, ["white", "red", "blue", "green", "yellow", "gray"][i], "black", "40",
                  f"2026-09-20T{8 + 2 * i:02d}:00:00") for i in range(6)]
    real = bed.candidates
    bed.candidates = lambda pace, own, progress=None: ([], "nothing")
    try:
        with TestClient(backend.app) as c:
            c.post("/api/projects", json={"name": "Memory"})
            wait(c, c.post("/api/import", json={"paths": clips}).json())
            job = c.post("/api/make", json={"format": "short", "look": "cozy", "music": False}).json()
            for _ in range(400):
                j = c.get(f"/api/make/{job['id']}").json()
                if j["stage"] in ("done", "error"):
                    break
                time.sleep(0.1)
            s = c.get("/api/session").json()
            title = next((o for o in s["overlays"]["items"] if o["kind"] == "title"), None)
            check("Make put a title to work with", title is not None, str([(o["kind"], o["text"]) for o in s["overlays"]["items"]]))
            if title:
                c.post("/api/ops", json={"ops": [{"op": "edit_overlay", "overlay": title["id"], "text": "Saturday In Morningside"}], "label": "words"})
                c.post("/api/ops", json={"ops": [{"op": "add_overlay", "kind": "caption", "text": "What you said here", "start": 2.0}], "label": "added"})
                added = next(o for o in c.get("/api/session").json()["overlays"]["items"] if o["kind"] == "caption")
                c.post("/api/ops", json={"ops": [{"op": "edit_overlay", "overlay": added["id"], "text": "late breakfast"}], "label": "words"})
                c.post("/api/ops", json={"ops": [{"op": "edit_overlay", "overlay": added["id"], "place": {"x": 0.3, "y": 0.8, "scale": 1}}], "label": "moved"})
                c.post("/api/ops", json={"ops": [{"op": "drop_overlay", "overlay": title["id"]}], "label": "removed"})
                evs = cm.events()
                check("a retype, a line written over the placeholder, a deletion; the add and the move record nothing",
                      [e["kind"] for e in evs] == ["retype", "add", "delete"], str([e["kind"] for e in evs]))
                check("the retype keeps VibeCut's line and hers", evs and evs[0]["before"] == title["text"] and evs[0]["after"] == "Saturday In Morningside",
                      str(evs[:1]))
                check("her written line keeps the moment it sat over (the hour filmed)",
                      len(evs) > 1 and evs[1]["after"] == "late breakfast" and evs[1]["ctx"]["hour"] is not None, str(evs[1] if len(evs) > 1 else None))
                v = c.get("/api/captions/voice").json()
                check("her lines are in the voice card", {"Saturday In Morningside", "late breakfast"} <= {l["text"] for l in v["lines"]}, str(v["lines"]))
                v = c.post("/api/captions/lines", json={"text": "late night ramen"}).json()
                check("a line added through the API", any(l["text"] == "late night ramen" for l in v["lines"]))
                check("the edit itself landed as a turn, unchanged by the memory",
                      any(o["text"] == "late breakfast" for o in c.get("/api/session").json()["overlays"]["items"]))
    finally:
        bed.candidates = real

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
