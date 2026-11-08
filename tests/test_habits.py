"""The second video is better because of the first -- and says so, and undoes.

- Signals: hand edits (removed / kept shots with labels, music off, a
  retyped line) are read from a session; the machine's own turns are not.
- Habits: the same thing on two videos is a habit; on one it isn't; a label
  both removed and kept is neither. Off switches and use counts survive
  a re-derive. Three uses without an undo and it is due as a rule.
- Bias: a habit nudges the picker's score by label, never more.
- Lines: without a key, a stop reads "place, time of day" from GPS and the
  clock, never a clock stamp alone; nothing to say stays silent.
- Through the API: a habit is applied to a Make, said in the reply, listed
  with its evidence, switched off in one call and the video made again.

    python tests/test_habits.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-habits-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def main() -> int:
    from tests.test_board import PROPOSALS, session
    from web.backend import habits, make, select as sel
    mk = lambda d: PROPOSALS  # noqa: E731

    print("signals")
    s, cat = session()
    first = s.board["beats"][0]["shots"][0]["id"]
    cat.shots[first].labels = {"whiteboard": 0.9, "classroom": 0.6}
    s.add({"kind": "direct", "text": "You removed a shot", "ops": [{"op": "drop_shot", "shot": first}]}, cat, mk)
    s.add({"kind": "direct", "text": "No music", "ops": [{"op": "set_music", "track": None}]}, cat, mk)
    s.add({"kind": "direct", "text": "Music and the beat", "ops": [{"op": "set_music", "track": None}]}, cat, mk)   # the machine's
    sig = habits.signals(s.turns, cat)
    check("a removed shot, by hand, with its labels; music off by hand; not the machine's turn",
          [x["what"] for x in sig] == ["removed", "music_off"] and sig[0]["labels"][0] == "whiteboard", json.dumps(sig))

    print("habits")
    habits._write({"habits": [], "phrases": []})
    one = [{"name": "Mon", "events": [{"kind": "signals", "items": [{"what": "removed", "labels": ["whiteboard"]}, {"what": "music_off"}]}]}]
    check("one video is an edit, not a habit", habits.derive(one) == [])
    two = one + [{"name": "Tue", "events": [{"kind": "signals", "items": [{"what": "removed", "labels": ["whiteboard"]}, {"what": "kept", "labels": ["food"]}, {"what": "music_off"}]}]},
                 {"name": "Wed", "events": [{"kind": "signals", "items": [{"what": "held", "labels": ["food"]}, {"what": "retyped", "text": "finally tried the matcha place"}]}]}]
    hs = habits.derive(two)
    ids = sorted(h["id"] for h in hs)
    check("two videos make habits: fewer whiteboard, more food, no music", ids == ["avoid:whiteboard", "music_off", "prefer:food"], str(ids))
    check("each names its evidence", next(h for h in hs if h["id"] == "avoid:whiteboard")["evidence"] == ["Mon", "Tue"])
    check("the bias is a small weight per label", habits.bias(hs) == {"whiteboard": -habits.LABEL_W, "food": habits.LABEL_W})
    check("music default follows", habits.music_default(hs) is False)
    check("retyped lines are remembered as phrasing", habits.phrases() == ["finally tried the matcha place"])
    habits.switch("avoid:whiteboard", True)
    hs = habits.derive(two)
    check("an off switch survives a re-derive, and the bias drops it", next(h for h in hs if h["id"] == "avoid:whiteboard")["off"] and "whiteboard" not in habits.bias(hs))
    mixed = two + [{"name": "Thu", "events": [{"kind": "signals", "items": [{"what": "kept", "labels": ["whiteboard"]}]}]}]
    check("a label both removed and kept is no habit", not any(h["id"] == "avoid:whiteboard" for h in habits.derive(mixed)))
    hs = habits.derive(two)
    for _ in range(3):
        due = habits.used(["prefer:food"])
    check("three uses without an undo: due to be offered as a rule", due and due[0]["id"] == "prefer:food")
    check("the reply line", habits.describe([h for h in hs if h["id"] in ("prefer:food", "music_off")]) == "Kept more food and no music, as you did last time.",
          habits.describe([h for h in hs if h["id"] in ("prefer:food", "music_off")]))

    print("the bias in the picker")
    shot = SimpleNamespace(score=0.5, labels={"food": 0.8}, vec=None, clip_id="c", faces=0, face_area=0.0, activity=5.0, duration=3.0, id="a:0", quality=0.5, worth=None, contrast=0.0, start=0.0, end=3.0)
    base = sel.hero_score(shot, {"c": {"signals": {"motion": [5.0] * 3, "subject": [0.5] * 3, "sharpness": [0.5] * 3, "duration": 3}, "shots": []}}, {})[0]
    boosted = sel.hero_score(shot, {"c": {"signals": {"motion": [5.0] * 3, "subject": [0.5] * 3, "sharpness": [0.5] * 3, "duration": 3}, "shots": []}}, {}, {"food": 0.2})[0]
    check("a habit nudges the score by label weight × confidence", abs((boosted - base) - 0.16) < 1e-6, f"{boosted - base:.3f}")

    print("lines from place and time")
    def pick(sid, when, gps=None):
        return sel.Pick(SimpleNamespace(id=sid, start=0.0, end=2.0, clip_id="c", clip_name="c", when=when, gps=gps, labels={}), "hero", 0.0, 2.0, 0.5, "", 0)
    from web.backend import places
    plan = sel.Plan(hook=[], sessions=[[pick("a", datetime(2026, 9, 22, 8, 35), (40.8078, -73.964))], [pick("b", datetime(2026, 9, 22, 15, 10))], [pick("c", None)]], titles=["a", "b", "c"])
    found = {places.key((40.8078, -73.964)): {"area": "Morningside Heights", "city": "New York"}}
    lines = make.plain_lines(plan, found)
    check("the place once, above how the day moved on; the hour alone; nothing", lines == ["Morningside Heights\ngood morning", "afternoon", ""], str(lines))
    ops = make.ops(plan, make.fingerprint("short", "fast", 60.0), None, "short", "cozy", "A day", set(), lines=lines)
    parts = [o["text"] for o in ops if o.get("kind") == "part"]
    subs = [o.get("sub") for o in ops if o.get("kind") == "part"]
    check("the lines go on the board without a clock stamp, the place above the first, and a silent stop stays silent",
          parts == ["good morning", "afternoon"] and subs == ["Morningside Heights", None], str(list(zip(parts, subs))))
    check("no key: the writer gives the plain lines", make.words(plan, "A day", "", None, None, found) == lines)

    print("through the API")
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend, bed
    import subprocess
    SRCS = ["testsrc2=size=640x360:rate=30", "mandelbrot=size=640x360:rate=30", "life=size=640x360:rate=30:mold=10:ratio=0.1",
            "smptebars=size=640x360:rate=30", "rgbtestsrc=size=640x360:rate=30", "gradients=size=640x360:rate=30:speed=0.05"]
    def clip2(path, d, src, when):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=16000:a=0.02",
                        "-t", str(d), "-metadata", f"creation_time={when}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
        return str(path)
    clips = [clip2(PTMP / f"hb-{i}.mp4", 7 + i % 3, SRCS[i], f"2026-09-20T{8 + (16 * i) // 60:02d}:{(16 * i) % 60:02d}:00") for i in range(6)]
    real = bed.candidates
    bed.candidates = lambda pace, own, progress=None: ([], "nothing")
    try:
        with TestClient(backend.app) as c:
            c.post("/api/projects", json={"name": "Habits"})
            wait(c, c.post("/api/import", json={"paths": clips}).json())
            label = next((l for rec in backend.CLIPS.values() for sh in rec["shots"] for l, _ in sh.get("labels", [])[:1]), None)
            for rec in backend.CLIPS.values():
                for sh in rec.get("shots", []):
                    sh["utility"] = False
            check("the synthetic clips carry a label to habit on", bool(label), str(label))
            # two earlier videos that kept that label: a habit the make will act on
            habits._write({"habits": [{"id": f"prefer:{label}", "kind": "prefer", "label": label, "weight": 0.2, "n": 2, "evidence": ["Mon", "Tue"],
                                       "text": f"more {label} shots", "used": 0, "off": False, "since": time.time()}], "phrases": []})
            real_derive = habits.derive
            habits.derive = lambda projects: habits.load()      # the fixture habit stands in for cross-project signals
            try:
                job = c.post("/api/make", json={"format": "short", "look": "cozy", "music": False}).json()
                for _ in range(400):
                    if job["stage"] in ("done", "error"):
                        break
                    time.sleep(0.25)
                    job = c.get(f"/api/make/{job['id']}").json()
                s = c.get("/api/session").json()
                check("the make says what the habit did", f"more {label}" in s["turns"][-1]["reply"] and s["habits"] and s["habits"][0]["id"] == f"prefer:{label}", s["turns"][-1]["reply"][-120:])
                r = c.get("/api/habits").json()
                check("habits are listed with their evidence and the use counted", r["habits"][0]["evidence"] == ["Mon", "Tue"] and r["habits"][0]["used"] == 1)
                r = c.post(f"/api/habits/prefer:{label}", json={"off": True, "remake": True}).json()
                for _ in range(400):
                    if r.get("stage") in ("done", "error"):
                        break
                    time.sleep(0.25)
                    r = c.get(f"/api/make/{r['id']}").json()
                s = c.get("/api/session").json()
                check("off in one call, and made again without it", r.get("stage") == "done" and not s["habits"] and f"more {label}" not in s["turns"][-1]["reply"]
                      and c.get("/api/habits").json()["habits"][0]["off"] is True, s["turns"][-1]["reply"][-80:])
            finally:
                habits.derive = real_derive
            backend._close_project()
    finally:
        bed.candidates = real

    print()
    if failures:
        print(f"{len(failures)} failed: {failures}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
