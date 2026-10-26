"""Save as my recipe: an edit the creator liked cuts and dresses the next one.

Discrimination: two edits that differ only in shot length (0.8 s vs 2.4 s)
give recipes whose fingerprints recover each length; an edit with words and
one without give a worded and a wordless recipe (and the wordless one makes
a video with no words); an effect on 9 of 10 shots is "every shot", on 5 of
10 it isn't; the music's tempo and its rising energy over the seconds that
played are read back. Through the API with synthetic clips: a hand-dressed
edit (a typeface, a fade between every shot, VHS on every shot) is saved,
listed under Cut it like with its frame and look, and a Make on another
video with it carries that dress in the same turn (one Undo), while a Make
without it doesn't; same name replaces, rename and delete work, and a
deleted recipe is no longer the remembered pick.

    python tests/test_recipes.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-recipes-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def board_of(lens: list[float], words: bool = True, effect_on: int = 0) -> dict:
    from web.backend import board as bd
    shots = [{"id": f"c{i}:0", "start": 0.0, "end": d} for i, d in enumerate(lens)]
    for e in shots[:effect_on]:
        e["effect"], e["effect_amount"] = "vhs", 1.5
    b = {"beats": [{"id": "b1", "title": "", "shots": shots}], "overlays": []}
    if words:
        for i in range(0, len(lens), 2):
            b, _ = bd.apply(b, {"op": "add_overlay", "kind": "caption", "text": f"so good {i}",
                                "anchor": {"to": "shot", "id": f"c{i}:0"}, "at": 0.1, "dur": 1.2},
                            None, None, new_id=lambda i=i: f"o{i}")
    return b


def unit() -> None:
    import numpy as np
    from cutgrammar import music as mu
    from web.backend import make, recipes

    print("measuring an edit")
    quick = recipes.measure(board_of([0.8] * 24), None, "short")
    slow = recipes.measure(board_of([2.4] * 24), None, "tall")
    fq = recipes.fingerprint({"style": quick["style"], "name": "Quick"})
    fs = recipes.fingerprint({"style": slow["style"], "name": "Slow"})
    check("shot length is recovered from each edit", abs(fq["median_s"] - 0.8) < 0.04 and abs(fs["median_s"] - 2.4) < 0.12,
          f"{fq['median_s']} vs {fs['median_s']}")
    check("and Make takes it like a vibe", make.fingerprint("short", "fast", 60.0, vibe=fq)["median_s"] == fq["median_s"]
          and make.fingerprint("tall", "calm", 60.0, vibe=fs)["median_s"] == fs["median_s"])
    check("the frame is kept, the recipe names itself", quick["dress"]["format"] == "short" and not fs["vertical"] is False
          and "your recipe “Quick”" == fq["like"] and "reference" not in __import__("web.backend.remix", fromlist=["x"]).describe(fq))

    worded, wordless = board_of([1.0] * 12), board_of([1.0] * 12, words=False)
    w1 = recipes.measure(worded, None, "short")["style"]["words"]
    w0 = recipes.measure(wordless, None, "short")["style"]["words"]
    check("words on screen: share, band, hold and the lines themselves", w1["share"] > 0.5 and w1["band"] == "bottom"
          and abs(w1["hold_s"] - 1.2) < 0.01 and w1["samples"][0] == "so good 0", json.dumps(w1)[:200])
    check("an edit without words gives a wordless recipe", w0["share"] == 0.0)
    from web.backend import board as bd
    top, _ = bd.apply(worded, {"op": "add_overlay", "kind": "title", "text": "A day", "anchor": {"to": "edit"}, "at": 0.0, "dur": 3.0},
                      None, None, new_id=lambda: "t1")
    for o in top["overlays"]:
        if o["kind"] == "caption":
            o["pos"], o["kind"] = "top", "part"
    check("the lines' place is where the lines sit, not the centred title",
          recipes.measure(top, None, "short")["style"]["words"]["band"] == "top")
    fp0 = recipes.fingerprint({"style": recipes.measure(wordless, None, "short")["style"], "name": "Plain"})
    from types import SimpleNamespace
    from datetime import datetime
    from web.backend import select as sel

    def pick(sid, dur=1.0):
        shot = SimpleNamespace(id=sid, start=0.0, end=dur, clip_id="c", clip_name="c", when=datetime(2026, 9, 22, 8, 35), labels={})
        return sel.Pick(shot, "hero", 0.0, dur, 0.5, "", 0)
    plan = sel.Plan(hook=[pick("h")], sessions=[[pick("a"), pick("b")]], titles=["Stop"])
    made = make.ops(plan, fp0, None, "short", None, "A day", set())
    check("…and a video made from it has no words", not any(o["op"] == "add_overlay" for o in made), str([o["op"] for o in made]))
    fp1 = recipes.fingerprint({"style": recipes.measure(worded, None, "short")["style"], "name": "Said"})
    made1 = make.ops(plan, fp1, None, "short", None, "A day", set())
    check("…while the worded one does", any(o["op"] == "add_overlay" for o in made1))

    many = recipes.measure(board_of([1.0] * 10, effect_on=9), None, "short")["dress"]["effect"]
    half = recipes.measure(board_of([1.0] * 10, effect_on=5), None, "short")["dress"]["effect"]
    check("an effect on 9 of 10 shots is for every shot, on 5 of 10 it isn't",
          many == {"effect": "vhs", "effect_amount": 1.5} and half is None, f"{many} / {half}")

    # loud for 10 s, then a 30 s climb from quiet: the edit played the climb
    tr = mu.Track(path="/tmp/rising.wav", duration=120.0, bpm=96.0,
                  energy=np.r_[np.full(10, 0.9), np.linspace(0.1, 0.9, 30), np.full(80, 0.9)])
    b = board_of([1.0] * 30)
    b["music"] = {"track": tr.id, "in": 10.0, "gain": 0.8}
    m = recipes.measure(b, tr, "short")
    check("the music's tempo, and its energy over the seconds that played", m["style"]["music"]["bpm"] == 96.0
          and m["style"]["music"]["arc"] == "builds" and m["dress"]["music"], json.dumps(m["style"]["music"])[:120])
    b["music"]["in"] = 0.0
    check("…from where it came in, not from the top of the track", recipes.measure(b, tr, "short")["style"]["music"]["arc"] != "builds")
    flat = mu.Track(path="/tmp/flat.wav", duration=120.0, bpm=128.0, energy=np.full(120, 0.5))
    b["music"]["track"] = flat.id
    check("…a steady track reads steady", recipes.measure(b, flat, "short")["style"]["music"]["arc"] == "steady")

    print("the dress on a new board")
    rec = {"name": "D", "dress": {"captions": {"typeface": "montserrat", "template": "outlined"},
                                  "transition": {"kind": "dissolve", "dur": 0.4}, "effect": {"effect": "vhs", "effect_amount": 1.5}}}
    nb = board_of([1.0] * 4, words=False)
    from web.backend import board as bd
    split_after = bd.applied(nb, [{"op": "split", "shot": "c0:0", "at": 0.5}], None, None)
    ops = recipes.dress_ops(rec, split_after)
    kinds = [o["op"] for o in ops]
    check("caption style, one transition for every cut, the effect on every shot (both halves of a split too)",
          kinds[:2] == ["overlay_style", "set_transition"] and kinds.count("set_shot") == 5
          and ops[0]["typeface"] == "montserrat" and ops[1]["all"] is True, str(kinds))
    check("a bad caption style in a saved recipe is dropped, not fatal",
          [o["op"] for o in recipes.dress_ops({"dress": {"captions": {"typeface": "comic-sans"}}}, nb)] == [])

    print("keeping them")
    r1, rep1 = recipes.save("Day vlog", quick, {"name": "Sep 22"})
    r2, rep2 = recipes.save("  day   VLOG ", slow, {"name": "Sep 23"})
    check("the same name again replaces that recipe", not rep1 and rep2 and r1["id"] == r2["id"] and len(recipes.list_all()) == 1
          and recipes.get(r1["id"])["style"]["pace"]["median_s"] == 2.4)
    r3, _ = recipes.save("Weekend", quick)
    check("listed newest first, by id with or without its prefix", [r["name"] for r in recipes.list_all()] == ["Weekend", "day VLOG"]
          and recipes.get(recipes.PREFIX + r3["id"])["name"] == "Weekend" and recipes.get("../../etc") is None)
    try:
        recipes.rename(r3["id"], "Day vlog")
        check("renaming onto another recipe's name is refused", False)
    except recipes.RecipeError:
        check("renaming onto another recipe's name is refused", True)
    check("rename", recipes.rename(r3["id"], "Weekends")["name"] == "Weekends" and recipes.get(r3["id"])["name"] == "Weekends")
    try:
        recipes.save("   ", quick)
        check("a recipe needs a name", False)
    except recipes.RecipeError:
        check("a recipe needs a name", True)
    pub = recipes.public(recipes.get(r3["id"]))
    check("offered with its frame, look and music switch", pub["kind"] == "recipe" and pub["id"].startswith(recipes.PREFIX)
          and pub["dress"] == {"format": "short", "look": None, "music": False} and pub["line"].startswith("your recipe · "), json.dumps(pub)[:200])
    check("delete", recipes.delete(r3["id"]) and recipes.get(r3["id"]) is None and not recipes.delete(r3["id"]))
    recipes.delete(r1["id"])
    try:
        recipes.measure(None, None, "short")
        check("no edit, nothing to save", False)
    except recipes.RecipeError:
        check("no edit, nothing to save", True)


def through_api() -> None:
    import subprocess
    from cutgrammar import music as mu
    from tests.test_bed import BPM, _track
    from tests.test_projects import TMP as PTMP, wait
    from fastapi.testclient import TestClient
    from web.backend import app as backend, bed, recipes

    print("through the API")
    SRCS = ["testsrc2=size=640x360:rate=30", "mandelbrot=size=640x360:rate=30", "life=size=640x360:rate=30:mold=10:ratio=0.1",
            "smptebars=size=640x360:rate=30", "rgbtestsrc=size=640x360:rate=30", "gradients=size=640x360:rate=30:speed=0.05",
            "cellauto=size=640x360:rate=30:rule=110", "testsrc=size=640x360:rate=30"]

    def clip(path, d, src, when):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=16000:a=0.02",
                        "-t", str(d), "-metadata", f"creation_time={when}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
        return str(path)
    clips = [clip(PTMP / f"rc-{i}.mp4", 7 + i % 3, SRCS[i], f"2026-09-20T{8 + (16 * i) // 60:02d}:{(16 * i) % 60:02d}:00") for i in range(8)]
    d = Path(tempfile.mkdtemp(prefix="vibecut-recipe-music-"))
    _track(str(d / "beat.wav"), 240.0, BPM, loud_from=24.0)
    pool = mu.LocalFolderSource(str(d)).list()
    real = bed.candidates
    bed.candidates = lambda pace, own, progress=None: (pool, "a test track")

    def make(c, **req):
        job = c.post("/api/make", json=req).json()
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                break
            time.sleep(0.25)
            job = c.get(f"/api/make/{job['id']}").json()
        return job

    def shots(s):
        return [x for x in s["timeline"]["items"] if x["kind"] == "shot"]

    def board():
        return backend.SESSION.board or {}

    def made_turn(s):
        return next(t for t in reversed(s["turns"]) if t["text"] == "Made your video" and not t["undone"])

    try:
        with TestClient(backend.app) as c:
            c.post("/api/projects", json={"name": "Recipe source"})
            wait(c, c.post("/api/import", json={"paths": clips[:6]}).json())
            for rec in backend.CLIPS.values():
                for sh in rec.get("shots", []):
                    sh["utility"] = False
            check("a first video", make(c, format="short", look="hype")["stage"] == "done")
            r = c.get("/api/recipes/draft")
            check("the draft reads the edit before anything is kept", r.status_code == 200 and r.json()["name"] == "Recipe source"
                  and any("Hype look" in w for w in r.json()["words"]), json.dumps(r.json())[:240])
            s = c.get("/api/session").json()
            keys = [x["key"] for x in s["timeline"]["items"] if x["kind"] == "shot"]
            dressed = [{"op": "overlay_style", "typeface": "montserrat", "text_color": "#ffd166"},
                       {"op": "set_transition", "all": True, "kind": "dissolve", "dur": 0.4}] + \
                      [{"op": "set_shot", "shot": k, "effect": "vhs", "effect_amount": 1.5} for k in keys]
            s = c.post("/api/ops", json={"ops": dressed, "label": "dressed by hand"}).json()
            check("dressed by hand", (board().get("picture_all") or {}).get("kind") == "dissolve"
                  and all(e.get("effect") == "vhs" for e in shots(s)), json.dumps(board().get("picture_all")))
            r = c.post("/api/recipes", json={"name": "My day"})
            check("saved", r.status_code == 200 and not r.json()["replaced"], r.text[:200])
            words = r.json()["recipe"]["words"]
            check("it says what it keeps", any("Montserrat" in w for w in words) and "fade between every shot" in words
                  and "VHS on every shot" in words, str(words))
            again = c.post("/api/recipes", json={"name": "my day"}).json()
            check("saving under the same name replaces it", again["replaced"] and len(c.get("/api/recipes").json()["recipes"]) == 1)
            rid = again["recipe"]["id"]

            c.post("/api/projects", json={"name": "Next video"})
            wait(c, c.post("/api/import", json={"paths": clips[2:]}).json())
            for rec in backend.CLIPS.values():
                for sh in rec.get("shots", []):
                    sh["utility"] = False
            st = c.get("/api/brief/setup").json()
            mine = next((v for v in st["vibes"] if v["id"] == rid), None)
            check("offered first under Cut it like, with its frame and look", st["vibes"][0]["id"] == rid and mine
                  and mine["dress"]["format"] == "short" and mine["dress"]["look"] == "hype", json.dumps(st["vibes"])[:200])

            check("a Make without it", make(c, format="short", look="hype")["stage"] == "done")
            s = c.get("/api/session").json()
            check("…has none of that dress", not board().get("picture_all") and not any(e.get("effect") for e in shots(s))
                  and (board().get("overlay_style") or {}).get("typeface") is None)
            c.post(f"/api/turns/{made_turn(s)['id']}/toggle")

            check("a Make with it", make(c, format="short", look="hype", vibe=rid)["stage"] == "done")
            s = c.get("/api/session").json()
            t = made_turn(s)
            ost = board().get("overlay_style") or {}
            check("…carries its caption style, its fade between every shot and VHS on every shot",
                  ost.get("typeface") == "montserrat" and ost.get("text_color") == "#ffd166"
                  and (board().get("picture_all") or {}).get("kind") == "dissolve" and shots(s) and all(e.get("effect") == "vhs" for e in shots(s)),
                  json.dumps({"style": ost, "all": board().get("picture_all")}))
            check("…says it was cut like the recipe", "cut like your recipe “my day”" in t["reply"], t["reply"][:160])
            check("…nothing skipped, and the AI didn't plan it", not t.get("skipped") and not backend.MAKE["job"].result.get("ai"))
            c.post(f"/api/turns/{t['id']}/toggle")
            s = c.get("/api/session").json()
            check("one Undo takes the video and its dress back", not board().get("picture_all") and not any(e.get("effect") for e in shots(s)))

            check("the pick is remembered", c.get("/api/brief/setup").json()["vibe"] == rid)
            r = c.patch(f"/api/recipes/{rid}", json={"name": "Day in my life"})
            check("rename", r.status_code == 200 and r.json()["recipe"]["name"] == "Day in my life")
            r = c.delete(f"/api/recipes/{rid}")
            check("delete", r.status_code == 200 and r.json()["recipes"] == [] and c.delete(f"/api/recipes/{rid}").status_code == 404)
            st = c.get("/api/brief/setup").json()
            check("a deleted recipe is no longer the remembered pick", st["vibe"] is None and not any(v["id"] == rid for v in st["vibes"]))
            check("…and a Make naming it falls back to the frame's own pace", make(c, format="short", look="hype", vibe=rid)["stage"] == "done"
                  and "recipe" not in made_turn(c.get("/api/session").json())["reply"])
    finally:
        bed.candidates = real
        for r in recipes.list_all():
            recipes.delete(r["id"])


def main() -> int:
    unit()
    through_api()
    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'all passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
