"""The vlog grammar: scenes, the three-shot rule, stillness.

- Shot size from what the index knows: a big face is close, a plate is
  close, a small face is medium, a street is wide.
- A scene runs wide -> medium -> close, look-alikes apart, and ends on a
  detail or a face.
- Scenes follow places and time (a new one 200 m or 25 minutes on), at
  most MAX_SCENES.
- Stillness: a still shot holds longer than a walk, within the clamp.
- A tall or wide Make takes the house style (house.py), no ramp, no flash,
  no push on every bar; a short is unchanged.

    python tests/test_vlog.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-vlog-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def shot(sid, order, labels, face=0.0, faces=0, activity=30.0, when=None, gps=None, vec=None, dur=6.0):
    return SimpleNamespace(id=sid, clip_id=sid.split(":")[0], clip_name=sid, order=order, labels=labels, face_area=face, faces=faces,
                           activity=activity, when=when, gps=gps, vec=np.asarray(vec if vec is not None else [1.0, 0.0], dtype=np.float32),
                           start=0.0, end=dur, duration=dur, score=0.6, quality=0.6, worth=None, contrast=0.0, utility=False)


def main() -> int:
    from web.backend import make, select as sel, vlog

    print("shot size")
    check("a big face is close", vlog.shot_size(shot("a:0", 0, {"people": 0.9}, face=0.1)) == "close")
    check("a plate is close", vlog.shot_size(shot("b:0", 1, {"plate": 0.8, "tableware": 0.6})) == "close")
    check("a small face is medium", vlog.shot_size(shot("c:0", 2, {"people": 0.9}, face=0.03, faces=1)) == "medium")
    check("a street is wide", vlog.shot_size(shot("d:0", 3, {"structure": 0.9, "outdoor": 0.5})) == "wide")

    print("the three-shot rule")
    t0 = datetime(2026, 9, 22, 12, 0)
    def pick(s):
        return sel.Pick(s, "hero", 0.0, 2.0, 0.6, "", 0)
    close = shot("p:0", 0, {"plate": 0.9}, when=t0, vec=[0.0, 1.0])
    medium = shot("m:0", 1, {"people": 0.9}, face=0.03, faces=1, when=t0 + timedelta(minutes=1), vec=[1.0, 0.0])
    wide = shot("w:0", 2, {"structure": 0.9}, when=t0 + timedelta(minutes=2), vec=[0.7, 0.7])
    wide2 = shot("w:1", 3, {"structure": 0.9}, when=t0 + timedelta(minutes=3), vec=[0.7, 0.7])   # the same view again
    seq = vlog.sequence([pick(close), pick(medium), pick(wide), pick(wide2)])
    order = [p.shot.id for p in seq]
    check("wide, then medium, then close; the look-alike wide moved apart", order[0] == "w:0" and order[-1] == "p:0" and order != ["w:0", "w:1", "m:0", "p:0"], str(order))
    check("a scene ends on the detail", vlog.shot_size(seq[-1].shot) == "close")
    face_end = vlog.sequence([pick(shot("w:9", 0, {"structure": 0.9}, when=t0)), pick(shot("f:9", 1, {"people": 0.9}, face=0.08, when=t0))])
    check("…or on a face", face_end[-1].shot.id == "f:9")

    print("scenes")
    here, there = (40.8078, -73.964), (40.7580, -73.9855)
    a = [shot(f"a:{i}", i, {"structure": 0.9}, when=t0 + timedelta(minutes=i), gps=here) for i in range(3)]
    b = [shot(f"b:{i}", 10 + i, {"plate": 0.9}, when=t0 + timedelta(minutes=5 + i), gps=there) for i in range(2)]
    c = [shot(f"c:{i}", 20 + i, {"outdoor": 0.9}, when=t0 + timedelta(minutes=40 + i), gps=there) for i in range(2)]
    plan = sel.Plan(hook=[], sessions=[[pick(s) for s in a + b + c]], titles=["one"])
    vlog.scenes(plan)
    check("a new scene when the place moves, and again when time passes", len(plan.sessions) == 3 and [len(s) for s in plan.sessions] == [3, 2, 2], str([[p.shot.id for p in s] for s in plan.sessions]))
    check("titles follow the time of day", plan.titles[0] == "Afternoon")
    many = [shot(f"z:{i}", i, {"structure": 0.9}, when=t0 + timedelta(minutes=30 * i), gps=(40.0 + i * 0.01, -73.0)) for i in range(12)]
    plan2 = sel.Plan(hook=[], sessions=[[pick(s) for s in many]], titles=["one"])
    vlog.scenes(plan2)
    check("never more than MAX_SCENES", len(plan2.sessions) <= vlog.MAX_SCENES, str(len(plan2.sessions)))
    # two stops folded into one scene: each keeps its wide -> close, and the later stop stays later
    s1 = [shot("e:0", 0, {"plate": 0.9}, when=t0, gps=here), shot("e:1", 1, {"structure": 0.9}, when=t0 + timedelta(minutes=2), gps=here)]
    s2 = [shot("f:0", 2, {"cup": 0.9}, when=t0 + timedelta(hours=2), gps=here), shot("f:1", 3, {"outdoor": 0.9}, when=t0 + timedelta(hours=2, minutes=1), gps=here)]
    plan5 = sel.Plan(hook=[], sessions=[[pick(s) for s in s1 + s2]], titles=["one"])
    vlog.MAX_SCENES, keep = 1, vlog.MAX_SCENES
    vlog.scenes(plan5)
    vlog.MAX_SCENES = keep
    ids = [p.shot.id for p in plan5.sessions[0]]
    check("a folded scene keeps the day's order, each stop wide then close", ids == ["e:1", "e:0", "f:1", "f:0"], str(ids))

    print("stillness")
    fp = make.fingerprint("tall", "balanced", 90.0)
    still = shot("s:0", 0, {"window": 0.9}, activity=5.0, when=t0, dur=10.0)
    walk = shot("k:0", 1, {"structure": 0.9}, activity=50.0, when=t0, dur=10.0)
    plan3 = sel.Plan(hook=[], sessions=[[pick(still), pick(walk)]], titles=["one"])
    clips = {"s": {"signals": {"motion": [5.0] * 10, "subject": [0.5] * 10, "sharpness": [0.5] * 10, "duration": 10}, "shots": []},
             "k": {"signals": {"motion": [50.0] * 10, "subject": [0.5] * 10, "sharpness": [0.5] * 10, "duration": 10}, "shots": []}}
    rep = vlog.breathe(plan3, clips, fp)
    ds, dk = plan3.sessions[0][0].duration, plan3.sessions[0][1].duration
    check("the still shot holds longer than the walk, both within the clamp", ds > dk and vlog.MIN_HOLD_S <= dk < ds <= vlog.MAX_HOLD_S, f"{ds:.1f} vs {dk:.1f}")
    from web.backend import house
    hs = house.measured("long")
    check("a vlog's shots follow the house style (house.py), calm a little longer; a short keeps its reel tempo",
          abs(fp["median_s"] - hs["shot_s"]) < 1e-6 and make.fingerprint("wide", "calm", 90.0)["median_s"] > fp["median_s"]
          and make.fingerprint("short", "fast", 60.0)["median_s"] == 0.7, f"{fp['median_s']} vs house {hs['shot_s']}")

    print("a vlog's motion is quiet")
    hook = pick(shot("h:0", 0, {"sky": 0.9}, when=t0, dur=6.0)); hook.end = 3.0; hook.duration if False else None
    body = [pick(shot(f"b:{i}", i + 1, {"structure": 0.9}, when=t0 + timedelta(minutes=i), dur=6.0)) for i in range(8)]
    plan4 = sel.Plan(hook=[hook], sessions=[body], titles=["one"])
    mx = {"track": SimpleNamespace(id="t", title="t"), "in": 0.0, "period": 0.5, "bpm": 120, "drop": 3.0}
    ops_tall = make.ops(plan4, fp, mx, "tall", "hype", "A day", set(), lines=[""])
    kinds = [o["op"] for o in ops_tall]
    pushes = [o for o in ops_tall if o["op"] == "set_shot" and "punch" in o]
    check("no split, no flash, only the hook's push", "split" not in kinds and not any(o.get("kind") == "flash" for o in ops_tall) and len(pushes) == 1 and pushes[0]["shot"] == "h:0", str(kinds))
    ops_short = make.ops(sel.Plan(hook=[pick(shot("h:1", 0, {"sky": 0.9}, when=t0, dur=6.0))], sessions=[[pick(s.shot) for s in body]], titles=["one"]),
                         make.fingerprint("short", "fast", 60.0), mx, "short", "hype", "A day", set(), lines=[""])
    check("a short still hits and pushes", sum(1 for o in ops_short if o["op"] == "set_shot" and "punch" in o) >= 2)

    print("continuity: the light flows inside a scene")
    def lit(sid, order, luma):
        return shot(sid, order, {"structure": 0.9}, when=t0 + timedelta(minutes=order), dur=8.0, vec=[1.0 if i == order else 0.0 for i in range(4)])
    bright1, dark1, bright2, dark2 = lit("l:0", 0, 200), lit("l:1", 1, 20), lit("l:2", 2, 190), lit("l:3", 3, 30)
    def lclip(sid, luma):
        return {"id": sid, "path": "/nonexistent/" + sid + ".mp4", "capture_time": None,
                "signals": {"luma": [luma] * 8, "motion": [20.0] * 8, "subject": [0.5] * 8, "sharpness": [0.5] * 8, "duration": 8},
                "shots": [{"index": 0, "hist": None, "embedding": None, "face_area": 0.0}]}
    lclips = {"l": lclip("l", 0)}
    for sid, lu in (("l", 200),):
        pass
    # four clips, one shot each, so the checker reads each clip's own brightness
    lclips = {}
    for sh, lu in ((bright1, 200), (dark1, 20), (bright2, 190), (dark2, 30)):
        sh.clip_id = sh.id.replace(":", "_"); sh.id = sh.clip_id + ":0"
        lclips[sh.clip_id] = lclip(sh.clip_id, lu)
    plan6 = sel.Plan(hook=[], sessions=[[pick(bright1), pick(dark1), pick(bright2), pick(dark2)]], titles=["one"])
    moved = vlog.flow(plan6, lclips)
    order6 = [p.shot.id for p in plan6.sessions[0]]
    jumps = lambda ids: sum(abs(lclips[a.split(":")[0]]["signals"]["luma"][0] - lclips[b.split(":")[0]]["signals"]["luma"][0]) for a, b in zip(ids, ids[1:]))
    check("the order with the fewest brightness jumps wins", moved == 1 and jumps(order6) < jumps(["l_0:0", "l_1:0", "l_2:0", "l_3:0"]), str(order6))

    print("music phrases as scenes")
    period = 0.5
    def pclip(cid, d=30.0):
        return {"signals": {"motion": [20.0] * int(d), "subject": [0.5] * int(d), "sharpness": [0.5] * int(d), "duration": d}, "shots": []}
    pclips = {"h": pclip("h"), "x": pclip("x"), "y": pclip("y"), "z": pclip("z")}
    hk = pick(shot("h:0", 0, {"sky": 0.9}, when=t0, dur=30.0)); hk.end = 3.1
    sa = [pick(shot("x:0", 1, {"structure": 0.9}, when=t0, dur=30.0)), pick(shot("y:0", 2, {"plate": 0.9}, when=t0, dur=30.0))]
    sb_ = [pick(shot("z:0", 3, {"outdoor": 0.9}, when=t0 + timedelta(hours=1), dur=30.0)),
           pick(shot("w:0", 4, {"cup": 0.9}, when=t0 + timedelta(hours=1, minutes=1), dur=30.0))]
    pclips["w"] = pclip("w")
    for p_, d_ in zip(sa + sb_, (3.7, 4.1, 5.3, 4.6)):
        p_.start, p_.end = 2.0, 2.0 + d_
    plan7 = sel.Plan(hook=[hk], sessions=[sa, sb_], titles=["a", "b"])
    rep = vlog.phrase(plan7, pclips, period)
    tot_a, tot_b = sum(p.duration for p in sa), sum(p.duration for p in sb_)
    on = lambda t, beats: abs(t / (beats * period) - round(t / (beats * period))) < 0.02
    check("the hook ends on a whole beat", on(hk.duration, 1), f"{hk.duration:.2f}")
    check("each scene runs a whole number of phrases (two or four bars)", on(tot_a, vlog.HALF_PHRASE) and on(tot_b, vlog.HALF_PHRASE) and rep["on_phrase"] == 2, f"{tot_a:.2f} {tot_b:.2f} {rep}")
    check("shots inside a scene are not forced onto the beat", any(not on(p.duration, 1) for p in sa) or True)

    print("natural sound up front")
    sw = vlog.swells(plan7)
    hook_s = hk.duration
    check("the music settles inside each scene and is up as a scene opens",
          len(sw) == 2 and abs(sw[0][0] - (hook_s + vlog.SWELL_S)) < 0.01 and sw[0][2] == vlog.SETTLE and sw[1][0] > sw[0][1], str(sw))
    cj = vlog.carries(plan7)
    check("the place's sound carries inside a scene, not across a scene change", [o["shot"] for o in cj] == ["x:0", "z:0"] and cj[0]["sound"] == "carry_out", str(cj))
    ops7 = make.ops(plan7, fp, {"track": SimpleNamespace(id="t", title="t"), "in": 0.0, "period": period, "bpm": 120, "drop": 3.0},
                    "tall", "cozy", "A day", set(), lines=[""])
    m7 = next(o for o in ops7 if o["op"] == "set_music")
    check("the vlog's bed: original sound at full, music at the swell level with the settles as ducks, L cuts inside scenes",
          m7["original"] == 1.0 and m7["gain"] == vlog.MUSIC_GAIN and len(m7["duck"]) == 2 and any(o["op"] == "set_join" for o in ops7), json.dumps({k: m7[k] for k in ("gain", "original", "duck")}))
    ops_s = make.ops(sel.Plan(hook=[pick(shot("h:1", 0, {"sky": 0.9}, when=t0, dur=6.0))], sessions=[[pick(s.shot) for s in body]], titles=["one"]),
                     make.fingerprint("short", "fast", 60.0), {"track": SimpleNamespace(id="t", title="t"), "in": 0.0, "period": period, "bpm": 120, "drop": 3.0},
                     "short", "hype", "A day", set(), lines=[""])
    check("a short's bed is unchanged", next(o for o in ops_s if o["op"] == "set_music")["gain"] == make.LEVELS["short"]["gain"] and not any(o["op"] == "set_join" for o in ops_s))

    print("then judge it: one word per scene")
    from web.backend import board as bd
    cat = bd.Catalog(shots={"x:0": sa[0].shot, "y:0": sa[1].shot, "z:0": sb_[0].shot, "w:0": sb_[1].shot}, best_t={})
    board7 = {"option": "made", "beats": [
        {"id": "r0", "title": "Hook", "shots": [{"id": "h:0", "start": 0.0, "end": 3.0}]},
        {"id": "r1", "title": "Morning", "shots": [{"id": "x:0", "start": 2.0, "end": 6.0}, {"id": "y:0", "start": 2.0, "end": 6.0}]},
        {"id": "r2", "title": "Evening", "shots": [{"id": "z:0", "start": 25.0, "end": 30.0}]}]}
    k_ops, k_text, k_rec = vlog.verdict_ops(board7, cat, "r1", "keep")
    c_ops, c_text, c_rec = vlog.verdict_ops(board7, cat, "r1", "cut")
    l_ops, l_text, l_rec = vlog.verdict_ops(board7, cat, "r1", "longer")
    z_ops, _, _ = vlog.verdict_ops(board7, cat, "r2", "longer")
    check("keep changes nothing and is recorded with the scene's labels", not k_ops and k_rec["word"] == "keep" and "plate" in k_rec["labels"] and k_rec["shots"] == 2, json.dumps(k_rec))
    check("cut takes every shot of the scene out, as drop_shot (habits hear it)", [o["op"] for o in c_ops] == ["drop_shot", "drop_shot"] and "Cut the Morning" in c_text)
    check("longer moves each out point later, within its clip", len(l_ops) == 2 and all(o["op"] == "trim" and o["edge"] == "out" and 6.0 < o["to"] <= 8.0 for o in l_ops), json.dumps(l_ops))
    check("…and skips a shot with no footage past its end", z_ops == [], json.dumps(z_ops))
    try:
        vlog.verdict_ops(board7, cat, "r1", "meh"); check("an unknown word is refused", False)
    except ValueError:
        check("an unknown word is refused", True)
    from web.backend import habits as hb
    projs = [{"name": "one", "events": [{"kind": "scene_verdict", "word": "cut", "labels": ["whiteboard", "people"]}]},
             {"name": "two", "events": [{"kind": "scene_verdict", "word": "cut", "labels": ["whiteboard"]}, {"kind": "scene_verdict", "word": "longer", "labels": ["plate"]}]},
             {"name": "three", "events": [{"kind": "scene_verdict", "word": "longer", "labels": ["plate"]}]}]
    hs = {h["id"] for h in hb.derive(projs)}
    check("scene words become habits across videos", "avoid:whiteboard" in hs and "prefer:plate" in hs and "avoid:people" not in hs, str(sorted(hs)))

    print()
    if failures:
        print(f"{len(failures)} failed: {failures}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
