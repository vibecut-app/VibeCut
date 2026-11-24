"""Watch it edit (show.py): after Make, the moves it made, one at a time.

Through the API with synthetic clips and a synthetic track (as test_make):
a short and a wide vlog are made, then /api/make/show is read. The moves
start from an empty timeline, lay the clips whole in the order they were
filmed, trim each part, lift the hook to the front, add the song (and the
cuts move onto its beat), the look, the words one at a time, and end on
exactly the edit that landed: the same shots, windows, fixes and words,
with the same ids. Reading it changes nothing, and once the edit has been
touched by hand there's nothing to play back.

    python tests/test_show.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-show-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


SRCS = ["testsrc2=size=640x360:rate=30", "mandelbrot=size=640x360:rate=30", "life=size=640x360:rate=30:mold=10:ratio=0.1",
        "smptebars=size=640x360:rate=30", "rgbtestsrc=size=640x360:rate=30", "gradients=size=640x360:rate=30:speed=0.05",
        "cellauto=size=640x360:rate=30:rule=110", "testsrc=size=640x360:rate=30"]


def clip(path: Path, d: float, src: str, when: str) -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=16000:a=0.02",
                    "-t", str(d), "-metadata", f"creation_time={when}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return str(path)


def shots(board: dict) -> list[tuple]:
    return [(e.get("key") or e["id"], round(e["start"], 3), round(e["end"], 3),
             tuple(sorted((k, json.dumps(e[k], sort_keys=True)) for k in e if k not in ("key", "id", "start", "end", "clip_id", "thumb",
                                                                                        "src_start", "src_end", "lean"))))
            for b in board["beats"] for e in b["shots"]]


def words(ov: dict) -> list[tuple]:
    return sorted((o["id"], o.get("text"), o.get("sub")) for o in ov["items"])


def make(c, fmt: str, look: str) -> dict:
    job = c.post("/api/make", json={"format": fmt, "look": look}).json()
    for _ in range(600):
        if job["stage"] in ("done", "error"):
            break
        time.sleep(0.25)
        job = c.get(f"/api/make/{job['id']}").json()
    return job


def walk(c, label: str, cat) -> None:
    real = c.get("/api/session").json()
    t0 = time.time()
    sh = c.get("/api/make/show").json()
    took = time.time() - t0
    steps, views = sh["steps"], sh["views"]
    kinds = [s["kind"] for s in steps]
    print(f"  ({label}: {len(steps)} steps, {len(views)} views, {took:.2f} s, {len(json.dumps(sh)) // 1024} KB)")
    print("   ", " · ".join(f"{k}" for k in dict.fromkeys(kinds)))
    check(f"{label}: there is something to watch, and every step says what it does",
          len(steps) > 5 and all(s["say"] and isinstance(s["at"], (int, float)) for s in steps), str(kinds))
    first = views[steps[0]["view"]]
    check(f"{label}: it starts on an empty timeline, with a board (so nothing else starts a story)",
          kinds[0] == "read" and first["board"] is not None and not first["timeline"]["items"])
    lays = [s for s in steps if s["kind"] == "lay"]
    laid = views[lays[0]["view"]]["timeline"]["items"] if lays else []
    check(f"{label}: the clips land one at a time, each a step that shows one more",
          lays and [s["reveal"] for s in lays] == list(range(1, len(laid) + 1))
          and all(s["shot"] == laid[s["reveal"] - 1]["key"] for s in lays), f"{len(lays)} of {len(laid)}")
    done = {(it["shot_id"]): it for it in real["timeline"]["items"] if it["kind"] == "shot"}
    whole = all(it["src_end"] - it["src_start"] >= (done[it["shot_id"]]["src_end"] - done[it["shot_id"]]["src_start"]) - 1e-3
                for it in laid if it["shot_id"] in done)
    check(f"{label}: …whole, never shorter than they end up", whole)
    filmed = [cat.shots[it["shot_id"]].when for it in laid]
    check(f"{label}: …in the order they were filmed", all(a <= b for a, b in zip(filmed, filmed[1:])),
          str([w.strftime("%H:%M") for w in filmed]))
    trims = [views[s["view"]]["timeline"]["total"] for s in steps if s["kind"] == "trim"]
    check(f"{label}: each part's trim makes the edit shorter", trims and views[lays[-1]["view"]]["timeline"]["total"] >= trims[0]
          and all(a >= b - 1e-6 for a, b in zip(trims, trims[1:])) and trims[-1] < views[lays[-1]["view"]]["timeline"]["total"],
          str([round(views[lays[-1]["view"]]["timeline"]["total"], 1)] + [round(t, 1) for t in trims]))
    hook = next((s for s in steps if s["kind"] == "hook"), None)
    if real["board"]["beats"][0]["title"] == "Hook" or (len(real["board"]["beats"]) > 1 and real["board"]["beats"][1]["title"] == "Hook"):
        hk = next(b for b in real["board"]["beats"] if b["title"] == "Hook")["shots"][0]["key"]
        before = [it["key"] for it in views[steps[kinds.index("hook") - 1]["view"]]["timeline"]["items"]] if hook else []
        after = views[hook["view"]]["timeline"]["items"] if hook else []
        check(f"{label}: the best moment moves to the front", hook and hk in before and after[0]["key"] == hk and hook["at"] == 0.0,
              f"{before.index(hk) if hk in before else None} → 0")
    if real["music"]:
        mu = next((s for s in steps if s["kind"] == "music"), None)
        check(f"{label}: the song lands, named, and the music lane only has it from then on",
              mu and real["music"]["title"] in mu["say"] and views[mu["view"]]["music"]["title"] == real["music"]["title"]
              and all(views[s["view"]]["music"] is None for s in steps[:steps.index(mu)]), mu and mu["say"])
        check(f"{label}: …and nothing in a step asks for a mix to be rendered",
              all((v["mix"] or {}).get("audio", real["mix"]["audio"]) == real["mix"]["audio"] for v in views))
    ws = [s for s in steps if s["kind"] == "words" and s.get("overlay")]
    check(f"{label}: the words are typed one at a time, each shown on the picture",
          len(ws) == len(real["overlays"]["items"])
          and all(any(o["id"] == s["overlay"] and o["start"] <= s["at"] <= o["end"] for o in views[s["view"]]["overlays"]["items"]) for s in ws),
          f"{len(ws)} of {len(real['overlays']['items'])}")
    end = views[steps[-1]["view"]]
    check(f"{label}: it ends on exactly the edit that landed: shots, windows, fixes",
          shots(end["board"]) == shots(real["board"]), f"{len(shots(end['board']))} vs {len(shots(real['board']))}")
    check(f"{label}: …and words, with their ids", words(end["overlays"]) == words(real["overlays"]))
    check(f"{label}: …and the look and music", (end["overlays"]["look"]["id"] == real["overlays"]["look"]["id"])
          and ((end["music"] or {}).get("id") == (real["music"] or {}).get("id")))
    again = c.get("/api/session").json()
    check(f"{label}: watching changed nothing", json.dumps(again["turns"]) == json.dumps(real["turns"])
          and shots(again["board"]) == shots(real["board"]))


def main() -> int:
    from cutgrammar import music as mu
    from tests.test_bed import BPM, _track
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, wait
    from web.backend import app as backend, bed

    clips = [clip(PTMP / f"show-{i}.mp4", 7 + i % 3, SRCS[i], f"2026-09-20T{8 + (16 * i) // 60:02d}:{(16 * i) % 60:02d}:00") for i in range(8)]
    d = Path(tempfile.mkdtemp(prefix="vibecut-show-music-"))
    _track(str(d / "beat.wav"), 240.0, BPM, loud_from=24.0)
    pool = mu.LocalFolderSource(str(d)).list()
    real = bed.candidates
    bed.candidates = lambda pace, own, progress=None: (pool, "a test track")
    try:
        with TestClient(backend.app) as c:
            c.post("/api/projects", json={"name": "Show"})
            check("nothing to watch before anything is made", c.get("/api/make/show").json()["steps"] == [])
            wait(c, c.post("/api/import", json={"paths": clips}).json())
            for rec in backend.CLIPS.values():            # Vision reads the synthetic frames as documents
                for sh in rec.get("shots", []):
                    sh["utility"] = False
            print("a short")
            job = make(c, "short", "hype")
            check("made", job["stage"] == "done", job.get("error") or "")
            walk(c, "short", backend.CATALOG["cat"])
            print("a wide vlog")
            s = c.get("/api/session").json()
            c.post(f"/api/turns/{s['turns'][-1]['id']}/toggle", json={})
            job = make(c, "wide", "cozy")
            check("made", job["stage"] == "done", job.get("error") or "")
            walk(c, "wide", backend.CATALOG["cat"])
            print("after a hand edit")
            s = c.get("/api/session").json()
            k = s["timeline"]["items"][-1]["key"]
            r = c.post("/api/ops", json={"ops": [{"op": "drop_shot", "shot": k}], "label": "You deleted the last shot"})
            check("a hand edit landed", r.status_code == 200, str(r.status_code))
            check("…so there's nothing to play back", c.get("/api/make/show").json()["steps"] == [])
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
