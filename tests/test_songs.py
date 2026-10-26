"""Songs to swap, transition sounds, a trending sound as a guide.

- rank_from keeps the ranking: several distinct songs, best first, and
  pick_from is its first.
- The creator's picks lean the ranking (songs.remember / lean_for): the
  same pool ranks a fast song higher after fast songs were picked.
- Transition sounds go where the export really swipes / flashes / drops:
  a short gets a whoosh on its swipe and a riser + hit on the drop; a vlog
  only its scene-change swipes, quieter; never two closer than GAP_S.
- A trending sound is read from a file (tempo, beat), and a guide never
  reaches an export: export.create drops it and says what to add.
- Through the API: Make leaves a list; a swap on a made vlog moves only the
  music and keeps the mix; on an untouched short the video is made again on
  the new beat; Undo brings the old song back; the sounds switch; a
  trending sound lands as a guide with no credit and no sounds.

    python tests/test_songs.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-songs-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def main() -> int:
    from cutgrammar import music as mu, sfxpack
    from tests.test_bed import _track
    from web.backend import export, remix, sfx, songs, trend

    print("a ranking, not one pick")
    d = Path(tempfile.mkdtemp(prefix="vibecut-songs-pool-"))
    for name, bpm in (("slow", 92.0), ("mid", 110.0), ("fast", 132.0)):
        _track(str(d / f"{name}.wav"), 200.0, bpm, loud_from=20.0)
    pool = mu.LocalFolderSource(str(d)).list()
    fp = {"bpm": (85, 135), "energy": None, "hook_s": 2.5}
    ranked = remix.rank_from(pool, fp, 40.0, 2.5, 5)
    check("several distinct songs, best first", len(ranked) >= 2 and len({x["track"].id for x in ranked}) == len(ranked)
          and all(a["score"] >= b["score"] for a, b in zip(ranked, ranked[1:])), str([(x["track"].title, x["score"]) for x in ranked]))
    check("pick_from is the ranking's first", remix.pick_from(pool, fp, 40.0, 2.5)["track"].id == ranked[0]["track"].id)

    print("the creator's picks lean it")
    fast = next(t for t in pool if t.title == "fast")
    score = lambda rk, name: next(x["score"] for x in rk if x["track"].title == name)  # noqa: E731
    before = remix.rank_from(pool, fp, 40.0, 2.5, 5, songs.lean_for(None))
    for _ in range(3):
        songs.remember(fast, pool)
    after = remix.rank_from(pool, fp, 40.0, 2.5, 5, songs.lean_for(None))
    gain_fast = score(after, "fast") - score(before, "fast")
    gain_mid = score(after, "mid") - score(before, "mid")
    check("after picking the fast song, its score rises and the others' doesn't",
          gain_fast > 0.05 and gain_mid < gain_fast, f"fast {gain_fast:+.3f}, mid {gain_mid:+.3f}")
    check("…by a lean, not a takeover: never more than PICK_W + LOOK_W", gain_fast <= songs.PICK_W + songs.LOOK_W + 1e-9)
    lean = songs.lean_for(None)
    slow = next(t for t in pool if t.title == "slow")
    check("…and the songs passed over count a little against them", lean(slow) < lean(fast), f"{lean(slow):.3f} vs {lean(fast):.3f}")
    look = songs.lean_for("cozy", {"picks": [], "passed": {}})
    tagged = type("T", (), {"meta": {"licence": {"tags": ["acoustic"]}}, "title": "x", "bpm": None, "id": "z"})()
    plain = type("T", (), {"meta": {"licence": {"tags": ["techno"]}}, "title": "y", "bpm": None, "id": "w"})()
    check("the look leans to its own kind of song", look(tagged) == songs.LOOK_W and look(plain) == 0.0)

    print("VibeCut's own transition sounds")
    for n in sfxpack.SOUNDS:
        x = sfxpack.render(n)
        pk = int(abs(x).max(axis=1).argmax())
        check(f"{n}: stereo, peaks where it says", x.shape[1] == 2 and abs(pk / sfxpack.SR - sfxpack.SOUNDS[n].peak_s) < 0.2,
              f"peak at {pk / sfxpack.SR:.2f} s, says {sfxpack.SOUNDS[n].peak_s}")
    w = sfxpack.render("whoosh")
    check("a whoosh passes from left to right", abs(w[: len(w) // 3, 0]).sum() > abs(w[: len(w) // 3, 1]).sum()
          and abs(w[-len(w) // 3:, 1]).sum() > abs(w[-len(w) // 3:, 0]).sum())

    print("where they go")
    # four 3 s shots of a 10 s clip each (footage past both ends: a swipe has its handles)
    clips = {f"c{i}": {"id": f"c{i}", "duration": 10.0, "path": f"/nowhere/{i}.mp4"} for i in range(4)}

    def board(beats):
        return {"look": "cozy", "beats": [{"id": f"b{k}", "title": f"p{k}", "shots": [
            {"id": f"c{i}:0", "clip_id": f"c{i}", "start": 3.0, "end": 6.0} for i in ids]} for k, ids in enumerate(beats)]}
    two_parts = board([[0, 1], [2, 3]])                       # cozy swipes between parts, cuts inside
    got = sfx.place(two_parts, clips, None, vlog=False)
    check("a whoosh on the swipe between the parts, its rush on the cut",
          [x["sound"] for x in got] == ["whoosh"] and abs(got[0]["at"] + sfxpack.SOUNDS["whoosh"].peak_s - 6.0) < 0.05, json.dumps(got))
    short = sfx.place(two_parts, clips, {"drop": 4.0, "in": 1.0}, vlog=False)
    names = sorted(x["sound"] for x in short)
    check("a short's drop gets a riser and a hit", names.count("riser") == 1 and names.count("hit") == 1, str(names))
    vl = sfx.place(two_parts, clips, {"drop": 4.0, "in": 1.0}, vlog=True)
    check("a vlog: the scene change only, quieter, no riser or hit",
          [x["sound"] for x in vl] == ["whoosh"] and vl[0]["gain"] < got[0]["gain"], json.dumps(vl))
    cutty = board([[0], [1], [2], [3]])                         # every cut a swipe, 3 s apart
    many = sfx.place({**cutty, "beats": [{**bt, "shots": [{**e, "end": 4.0} for e in bt["shots"]]} for bt in cutty["beats"]]},
                     clips, None, vlog=False)                   # 1 s apart now
    gaps = [b["at"] - a["at"] for a, b in zip(many, many[1:])]
    check("never two closer than GAP_S", all(g >= sfx.GAP_S - 1e-6 for g in gaps), str(gaps))

    print("a trending sound, read from a file")
    td = Path(tempfile.mkdtemp(prefix="vibecut-trend-"))
    _track(str(td / "sound.wav"), 60.0, 128.0, loud_from=8.0)
    done = []
    job = trend.start(str(td / "sound.wav"), done.append)
    for _ in range(200):
        if done:
            break
        time.sleep(0.1)
    check("read: a guide with its tempo", job.stage == "done" and job.track and job.track.meta.get("guide")
          and abs(float(job.track.bpm) - 128.0) < 3, json.dumps(job.public()))
    check("found again by id after a restart", trend.find(job.track.id) is not None)
    try:
        trend.start("/nowhere/at/all.mp3")
        check("a missing file is refused", False)
    except ValueError:
        check("a missing file is refused", True)

    print("a guide never reaches an export")
    v = td / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-t", "3",
                    "-pix_fmt", "yuv420p", str(v)], check=True)
    vclips = {"v": {"id": "v", "path": str(v), "duration": 3.0, "width": 320, "height": 180, "rotation": 0}}
    items = [{"kind": "shot", "key": "v:0", "shot_id": "v:0", "clip_id": "v", "beat_id": "b", "src_start": 0.0, "src_end": 2.0,
              "seq_start": 0.0, "seq_end": 2.0, "n": 1}]
    from web.backend import musiclib
    musiclib.STATE["tracks"].append(job.track)
    ej = export.create(items, vclips, "guide test", job.track.path, None,
                       mix={"track": job.track.id, "in": 1.5, "guide": True, "sfx": [{"path": "x", "at": 0}]})
    check("the file goes out without the sound, and says what to add from where",
          ej.music is None and ej.mix is None and any("starting at 0:02" in n or "starting at 0:01" in n for n in ej.notes),
          json.dumps(ej.notes))
    ej2 = export.create(items, vclips, "bed test", job.track.path, None, mix={"track": job.track.id, "in": 1.5})
    check("a normal bed still goes out", ej2.music == job.track.path)

    api(pool)
    print()
    print("all passed" if not failures else f"{len(failures)} failed: {failures}")
    return 1 if failures else 0


def api(pool) -> None:
    print("through the API")
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, wait
    from web.backend import app as backend, bed
    srcs = ["testsrc2=size=640x360:rate=30", "mandelbrot=size=640x360:rate=30", "life=size=640x360:rate=30:mold=10:ratio=0.1",
            "smptebars=size=640x360:rate=30", "rgbtestsrc=size=640x360:rate=30", "gradients=size=640x360:rate=30:speed=0.05",
            "cellauto=size=640x360:rate=30:rule=110", "testsrc=size=640x360:rate=30"]

    def clip(path, dur, src, when):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=pink:r=16000:a=0.02",
                        "-t", str(dur), "-metadata", f"creation_time={when}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
        return str(path)
    paths = [clip(PTMP / f"sg-{i}.mp4", 7 + i % 3, srcs[i], f"2026-09-20T{8 + (16 * i) // 60:02d}:{(16 * i) % 60:02d}:00") for i in range(8)]
    real = bed.candidates
    bed.candidates = lambda pace, own, progress=None: (pool, "test songs")

    def make(c, fmt, look):
        job = c.post("/api/make", json={"format": fmt, "look": look}).json()
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                break
            time.sleep(0.25)
            job = c.get(f"/api/make/{job['id']}").json()
        return job

    try:
        with TestClient(backend.app) as c:
            c.post("/api/projects", json={"name": "Songs"})
            wait(c, c.post("/api/import", json={"paths": paths}).json())
            for rec in backend.CLIPS.values():
                for sh in rec.get("shots", []):
                    sh["utility"] = False
            job = make(c, "wide", "cozy")
            check("a wide Make", job["stage"] == "done", job.get("error") or "")
            o = c.get("/api/music/options").json()
            check("the Music panel has songs to swap, the one under the video marked",
                  o["status"] == "ready" and len(o["songs"]) >= 2 and sum(s["in_use"] for s in o["songs"]) == 1,
                  json.dumps([(s["title"], s["in_use"], s["why"]) for s in o["songs"]]))
            s0 = c.get("/api/session").json()
            m0 = dict(backend.SESSION.board["music"])
            cuts0 = [it["seq_end"] for it in s0["timeline"]["items"]]
            other = next(x for x in o["songs"] if not x["in_use"])
            s1 = c.post("/api/music/swap", json={"track_id": other["id"]}).json()
            m1 = backend.SESSION.board["music"]
            check("a swap on a made vlog: the new song, the mix kept, the cuts where they were",
                  m1["track"] == other["id"] and m1.get("gain") == m0.get("gain") and m1.get("duck") == m0.get("duck")
                  and [it["seq_end"] for it in s1["timeline"]["items"]] == cuts0 and s1["turns"][-1]["text"].startswith(backend.SONG_TEXT),
                  json.dumps({"turn": s1["turns"][-1]["text"], "reply": s1["turns"][-1]["reply"]}))
            check("…and it teaches the taste", any(p["id"] == other["id"] for p in songs_load()["picks"]))
            s2 = c.post(f"/api/turns/{s1['turns'][-1]['id']}/toggle", json={}).json()
            check("undo brings the first song back", backend.SESSION.board["music"]["track"] == m0["track"])
            s3 = c.post("/api/sfx", json={"on": True}).json()
            on = backend.SESSION.board["music"].get("sfx") or []
            check("transition sounds switch on as a turn (a vlog: scene changes only)",
                  s3["turns"][-1]["text"] == "Transition sounds" and all(x["sound"] in ("whoosh", "swish") for x in on), json.dumps(on))
            c.post("/api/sfx", json={"on": False})
            check("…and off", not backend.SESSION.board["music"].get("sfx"))

            job = make(c, "short", "hype")
            check("a short Make", job["stage"] == "done", job.get("error") or "")
            o = c.get("/api/music/options").json()
            check("an untouched short says a swap makes it again", o["rebuilds"] is True and len(o["songs"]) >= 2, json.dumps(o["rebuilds"]))
            other = next(x for x in o["songs"] if not x["in_use"])
            s4 = c.post("/api/music/swap", json={"track_id": other["id"]}).json()
            grid = s4["timeline"]["grid"]
            period = 60.0 / grid["bpm"]
            cuts = [it["seq_end"] for it in s4["timeline"]["items"][:-1]]
            on_grid = sum(abs(((t - grid["phase"]) / (period / 2)) - round((t - grid["phase"]) / (period / 2))) * period / 2 <= 0.05 for t in cuts)
            check("made again on the new song's beat", backend.SESSION.board["music"]["track"] == other["id"] and cuts
                  and on_grid == len(cuts) and "made again" in s4["turns"][-1]["reply"], f"{on_grid} of {len(cuts)}; {s4['turns'][-1]['reply']}")

            td = Path(tempfile.mkdtemp(prefix="vibecut-trend-api-"))
            from tests.test_bed import _track
            _track(str(td / "trending.wav"), 75.0, 120.0, loud_from=6.0)
            tj = c.post("/api/music/trend", json={"source": str(td / "trending.wav")}).json()
            for _ in range(300):
                if tj["stage"] in ("done", "error"):
                    break
                time.sleep(0.2)
                tj = c.get(f"/api/music/trend/{tj['id']}").json()
            s5 = c.get("/api/session").json()
            check("a trending sound lands as a guide: no credit, no transition sounds, how to add it said",
                  tj["stage"] == "done" and s5["music"] and s5["music"]["guide"] and s5["music"]["credit"] is None
                  and not backend.SESSION.board["music"].get("sfx") and "add it in TikTok or Instagram" in s5["turns"][-1]["reply"],
                  json.dumps({"job": tj.get("error"), "music": s5["music"], "reply": s5["turns"][-1]["reply"][:160]}))
            bad = c.post("/api/sfx", json={"on": True})
            check("…and transition sounds are refused with it", bad.status_code == 409)
            backend._close_project()
    finally:
        bed.candidates = real


def songs_load():
    from web.backend import songs
    return songs.load()


if __name__ == "__main__":
    sys.exit(main())
