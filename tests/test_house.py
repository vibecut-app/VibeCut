"""The house style: Make cut to what the good vlogs measured (house.py).

Each rule is checked the way a discrimination test is: two fixtures that
differ in one respect, and the rule has to move.

- house.recipe reads taste/'s files: its median is the fingerprint's, its
  spread's held end is the good side's p90 (far wider than the old guess).
- Talk broken up by cutaways: two talking shots side by side get b-roll
  between them; the same scene with no talk is left as it was.
- Holds by what the shot is: talk keeps its sentence, a laugh is held, a
  scene's still rest holds longer than other b-roll, a walk is quick.
- Music in parts: the bed steps out under talk to the lens; a montage with
  no talk keeps it under everything.
- The board is read the way a real vlog is: music heard where it isn't
  ducked out, not "on" the moment a track is set.

    python tests/test_house.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-house-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


T0 = datetime(2026, 9, 22, 12, 0)


def shot(sid, order, labels, face=0.0, faces=0, activity=30.0, dur=8.0):
    return SimpleNamespace(id=sid, clip_id=sid.split(":")[0], clip_name=sid, order=order, labels=labels, face_area=face,
                           faces=faces, activity=activity, when=T0 + timedelta(minutes=order), gps=(40.0, -73.0),
                           vec=np.asarray([1.0, 0.0] if order % 2 else [0.0, 1.0], dtype=np.float32),
                           start=0.0, end=dur, duration=dur, score=0.6, quality=0.6, worth=None, contrast=0.0, utility=False)


def clip(cid, dur=8.0, motion=30.0, laugh=0.0):
    n = int(dur)
    return {"id": cid, "signals": {"motion": [motion] * n, "subject": [0.5] * n, "sharpness": [0.5] * n, "duration": dur},
            "shots": [], "sound": {"laughter": [laugh] * n, "voice": [0.0] * n, "music": [0.0] * n}}


def main() -> int:
    from taste import describe as ds
    from web.backend import house, make, select as sel, vlog

    def pick(s, a=0.0, b=2.0):
        return sel.Pick(s, "hero", a, b, 0.6, "", 0)

    print("the recipe comes from the measured vlogs")
    fpj = json.loads(open(os.path.join(house.ROOT, "fingerprints", "long.json")).read())["traits"]
    r = house.recipe("wide")
    check("its median is the good long vlogs' typical shot", abs(r["median_s"] - fpj["shot_s"]["median"]) < 1e-3,
          f"{r['median_s']} vs {fpj['shot_s']['median']}")
    check("its held end reaches their held shots (p90), far past the old 1.5x guess",
          r["spread"][1] * r["median_s"] > 5.0 and r["spread"][1] > make.SPREAD[1] * 2, str(r["spread"]))
    check("the shot-by-shot readings are there: b-roll quicker than talk, music out under talk",
          r["house"]["broll_s"] < r["house"]["talk_s"] and r["house"]["music_under_talk"] < 0.2, json.dumps(
              {k: r["house"][k] for k in ("broll_s", "talk_s", "music_under_talk")}))
    check("a fresh checkout without the files falls back, never fails", house.FALLBACK["long"]["shot_s"] > 0)

    print("talk broken up by cutaways")
    talk = [shot(f"t{i}:0", i, {"people": 0.9}, face=0.08, faces=1, activity=10.0) for i in range(3)]
    roll = [shot(f"b{i}:0", 10 + i, {"structure": 0.9}, activity=30.0) for i in range(3)]
    talking = {s.id for s in talk}
    order = [pick(x) for x in talk + roll]                 # every talk shot runs into the next
    out = vlog.cutaways(order, talking)
    runs = sum(1 for a, b in zip(out, out[1:]) if a.shot.id in talking and b.shot.id in talking)
    before = sum(1 for a, b in zip(order, order[1:]) if a.shot.id in talking and b.shot.id in talking)
    check("talk next to talk before, never after", before == 2 and runs == 0, " ".join(p.shot.id for p in out))
    check("nothing is lost or repeated", sorted(p.shot.id for p in out) == sorted(p.shot.id for p in order))
    check("the talk keeps its order", [p.shot.id for p in out if p.shot.id in talking] == [s.id for s in talk])
    same = vlog.cutaways(order, set())
    check("with no talk nothing moves", [p.shot.id for p in same] == [p.shot.id for p in order])

    print("holds by what the shot is")
    h = house.measured("long")
    tk = shot("t9:0", 0, {"people": 0.9}, face=0.08, faces=1, activity=10.0, dur=7.0)
    walk = shot("w9:0", 1, {"structure": 0.9}, activity=60.0)
    still = shot("s9:0", 2, {"window": 0.9}, activity=4.0)
    mid = shot("m9:0", 3, {"structure": 0.9}, activity=25.0)
    ht = vlog.hold_for(pick(tk), h, 1.0, False, {tk.id})
    hw = vlog.hold_for(pick(walk), h, 1.0, False, set())
    hr = vlog.hold_for(pick(still), h, 1.0, True, set())
    hs = vlog.hold_for(pick(still), h, 1.0, False, set())
    hm = vlog.hold_for(pick(mid), h, 1.0, False, set())
    check("talk keeps its whole sentence (7 s filmed)", abs(ht - 7.0) < 1e-6, f"{ht:.2f}")
    check("the same shot, not talking, is cut like b-roll", vlog.hold_for(pick(tk), h, 1.0, False, set()) < ht)
    check("a walk is quick, about a second", hw <= 1.2 and hw < hm, f"walk {hw:.2f}, b-roll {hm:.2f}")
    check("a scene's still rest holds longest of its b-roll", hr > hs > hm, f"rest {hr:.2f}, still {hs:.2f}, b-roll {hm:.2f}")
    laugh = shot("l9:0", 4, {"people": 0.9}, activity=30.0, dur=5.0)
    clips = {"l9": clip("l9", 5.0, laugh=0.8), "m9": clip("m9", 8.0, laugh=0.0)}
    check("a laugh is heard, plain b-roll isn't", vlog.laughs(pick(laugh), clips) and not vlog.laughs(pick(mid), clips))
    check("a laugh is held like talk", vlog.hold_for(pick(laugh), h, 1.0, False, set(), True) > vlog.hold_for(pick(laugh), h, 1.0, False, set()))

    print("music in parts")
    board = {"beats": [{"id": "b0", "title": "one", "shots": [
        {"id": "t1:0", "clip_id": "t1", "start": 0.0, "end": 4.0},
        {"id": "b1:0", "clip_id": "b1", "start": 0.0, "end": 2.0},
        {"id": "t2:0", "clip_id": "t2", "start": 0.0, "end": 4.0}]}]}
    ducks = vlog.talk_out(board, {"t1:0", "t2:0"})
    check("the bed steps out under each stretch of talk", len(ducks) == 2 and all(g == vlog.TALK_OUT for _, _, g in ducks), str(ducks))
    check("a montage with no talk keeps the bed under everything", vlog.talk_out(board, set()) == [])

    print("the board read as a real vlog is")
    shots = [{"t": 0.0, "d": 5.0, "music": 0.0}, {"t": 5.0, "d": 5.0, "music": 0.0}]
    full = ds.heard_share(shots, {"track": "x", "duck": []}, 10.0)
    half = ds.heard_share(shots, {"track": "x", "duck": [[0.0, 5.0, vlog.TALK_OUT]]}, 10.0)
    soft = ds.heard_share(shots, {"track": "x", "duck": [[0.0, 5.0, 0.6]]}, 10.0)
    none = ds.heard_share(shots, None, 10.0)
    own = ds.heard_share([{"t": 0.0, "d": 10.0, "music": 0.9}], None, 10.0)
    check("a bed under all of it reads 1.0", full == 1.0, str(full))
    check("out under half of it reads 0.5", abs(half - 0.5) < 0.03, str(half))
    check("settled but audible still counts as music", soft == 1.0, str(soft))
    check("no bed, no music in the footage: 0; music in the footage itself counts", none == 0.0 and own == 1.0, f"{none} {own}")

    print("Make's wiring")
    fp = make.fingerprint("wide", "balanced", 90.0)
    check("a wide Make is a vlog, a short and a reel copy aren't",
          make.is_vlog("wide", fp) and not make.is_vlog("short", fp) and not make.is_vlog("wide", {**fp, "refs_used": True}))

    print()
    print("all passed" if not failures else f"{len(failures)} failed: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
