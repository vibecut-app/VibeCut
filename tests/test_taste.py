"""Taste in the loop: the creator's words reach the picks and the lines.

- taste_text renders the profile and the confirmed rules, or nothing.
- The judge hands the taste to whatever asks the model (a stand-in sees it).
- words: a stand-in writer gets each stop's time and labels plus the taste,
  and its lines replace the label table's phrases on the board -- in caps
  when the reel's words were caps. A failing writer changes nothing.
- Through the API: a saved profile and a confirmed rule are in the make
  job's taste.

    python tests/test_taste.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-taste-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def main() -> int:
    from web.backend import make, remix, select as sel

    print("the taste, in words")
    t = make.taste_text({"name": "Sarah", "handle": "@s", "about": "campus days", "vibes": ["cozy", "playful"], "pace": "Quick", "avoid": "my face for too long"},
                        "CREATOR RULES: never two identical shots")
    check("profile and rules, in that order", t.startswith("CREATOR TASTE") and "Sarah (@s)" in t and "cozy, playful" in t and "Never: my face" in t and t.endswith("identical shots"), t[:80])
    check("nothing said, nothing rendered", make.taste_text(None, "") == "" and make.taste_text({}, "") == "")
    check("rules alone still render", make.taste_text(None, "CREATOR RULES: x") == "CREATOR RULES: x")

    print("the judge and the writer")
    def pick(sid, score, dur=1.0, labels=None):
        shot = SimpleNamespace(id=sid, start=0.0, end=dur, clip_id="c", clip_name="c", when=datetime(2026, 9, 22, 8, 35), labels=labels or {})
        return sel.Pick(shot, "hero", 0.0, dur, score, "", 0)
    plan = sel.Plan(hook=[pick("h", 0.9)], sessions=[[pick("a", 0.5, labels={"cup": 0.9, "table": 0.5}), pick("b", 0.6, labels={"laptop": 0.8})],
                                                  [pick("c", 0.7, labels={"stairs": 0.7})]], titles=["Morning", "Noon"])
    seen = {}
    def writer(items, about, taste):
        seen["items"], seen["about"], seen["taste"] = items, about, taste
        return ["morning coffee", "up we go"]
    lines = make.words(plan, "A day at uni", "CREATOR TASTE: cozy", writer)
    check("the writer gets each stop's time and labels, the video and the taste",
          seen["items"][0]["time"] == remix._clock(datetime(2026, 9, 22, 8, 35)) and "cup" in seen["items"][0]["labels"] and "laptop" in seen["items"][0]["labels"]
          and seen["items"][1]["labels"] == ["stairs"] and seen["taste"] == "CREATOR TASTE: cozy", json.dumps(seen["items"]))
    check("its lines come back, one per stop", lines == ["morning coffee", "up we go"], str(lines))
    fp = make.fingerprint("short", "fast", 60.0)
    ops = make.ops(plan, fp, None, "short", "hype", "A day at uni", set(), lines=lines)
    parts = [o["text"] for o in ops if o.get("kind") == "part"]
    check("the written lines are on the board, no clock stamp in front", parts == ["morning coffee", "up we go"], str(parts))
    caps_fp = {**fp, "text": {"share": 0.5, "band": "bottom", "hold_s": 2.0, "upper": True, "first_s": 0.0}, "refs_used": True}
    parts = [o["text"] for o in make.ops(plan, caps_fp, None, "short", "hype", "A day at uni", set(), lines=lines) if o.get("kind") == "part"]
    check("in caps when the reel's words were caps", parts and all(p.isupper() for p in parts), str(parts))
    def broken(items, about, taste):
        raise RuntimeError("no")
    plain = make.plain_lines(plan, None)
    check("a failing writer leaves the plain lines: what the picture shows", make.words(plan, "A day", "", broken) == plain and plain == ["coffee run", "up we go"], str(plain))
    check("no key: the plain lines", make.words(plan, "A day", "") == plain)
    print("through the API")
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend, bed
    SRCS = ["testsrc2=size=640x360:rate=30", "mandelbrot=size=640x360:rate=30", "life=size=640x360:rate=30:mold=10:ratio=0.1",
            "smptebars=size=640x360:rate=30", "rgbtestsrc=size=640x360:rate=30", "gradients=size=640x360:rate=30:speed=0.05"]
    import subprocess
    def clip2(path, d, src, when):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=16000:a=0.02",
                        "-t", str(d), "-metadata", f"creation_time={when}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
        return str(path)
    clips = [clip2(PTMP / f"ta-{i}.mp4", 7 + i % 3, SRCS[i], f"2026-09-20T{8 + (16 * i) // 60:02d}:{(16 * i) % 60:02d}:00") for i in range(6)]
    real = bed.candidates
    bed.candidates = lambda pace, own, progress=None: ([], "nothing")
    try:
        with TestClient(backend.app) as c:
            c.post("/api/profile", json={"profile": {"name": "Sarah", "vibes": ["cozy"], "avoid": "long talking"}})
            backend.PREFS.rules.append({"id": "r9", "rule": "never two identical shots", "klass": "long_term", "active": True, "scope": "every video", "counter": "", "reason": "", "evidence": [], "created": time.time(), "history": []})
            c.post("/api/projects", json={"name": "Taste"})
            wait(c, c.post("/api/import", json={"paths": clips}).json())
            for rec in backend.CLIPS.values():
                for sh in rec.get("shots", []):
                    sh["utility"] = False
            job = c.post("/api/make", json={"format": "short", "look": "cozy", "music": False}).json()
            for _ in range(400):
                if job["stage"] in ("done", "error"):
                    break
                time.sleep(0.25)
                job = c.get(f"/api/make/{job['id']}").json()
            taste = (backend.MAKE["job"].result or {}).get("taste", "")
            check("the make job carries the profile and the confirmed rule", "Sarah" in taste and "cozy" in taste and "identical shots" in taste, taste[:120])
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
