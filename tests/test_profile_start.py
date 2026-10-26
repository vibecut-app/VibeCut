"""Your profile's start: asked once after an export, where the next video starts.

Unit: the question is unanswered at first, a skip never undoes a profile
that was made, forgetting clears it.
Through the API: logged out sees no question and can't save; Skip answers
it; bad picks are refused; a save changes only what it sends. Then the same
footage made twice, without and with a profile: without, the pace is the
footage's and nothing is added; with one, the pace is the profile's, a
"From your profile" turn puts its transition at every cut and takes the
captions off, and Undo takes only that away. A lesson gets subtitles of
what's said in place of Make's lines (the recogniser stood in for). A
chosen story gets the profile's caption style and transition. The pace,
the captions switch and a transition for every cut keep the profile up to
date, and only once a profile was made.

    python tests/test_profile_start.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-start-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
os.environ.pop("VIBECUT_PUBLIC", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def main() -> int:
    from web.backend import defaults
    print("the answer")
    defaults.forget()
    check("not asked at first", defaults.asked() is None)
    check("a skip is kept", defaults.answer("skipped") == "skipped" and defaults.asked() == "skipped")
    check("a profile made after a skip counts", defaults.answer("made") == "made")
    check("a later skip never undoes it", defaults.answer("skipped") == "made" and defaults.asked() == "made")
    defaults.forget()
    check("forgetting clears it", defaults.asked() is None)

    print("through the API")
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, wait
    from web.backend import app as backend, bed
    # eight clips that look like eight different things, so the video has cuts (as test_make)
    import subprocess
    SRCS = ["testsrc2=size=640x360:rate=30", "mandelbrot=size=640x360:rate=30", "life=size=640x360:rate=30:mold=10:ratio=0.1",
            "smptebars=size=640x360:rate=30", "rgbtestsrc=size=640x360:rate=30", "gradients=size=640x360:rate=30:speed=0.05",
            "cellauto=size=640x360:rate=30:rule=110", "testsrc=size=640x360:rate=30"]

    def clip2(path, d, src, when):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=16000:a=0.02",
                        "-t", str(d), "-metadata", f"creation_time={when}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
        return str(path)
    clips = [clip2(PTMP / f"ps-{i}.mp4", 7 + i % 3, SRCS[i], f"2026-09-20T{8 + (16 * i) // 60:02d}:{(16 * i) % 60:02d}:00") for i in range(8)]
    real = bed.candidates
    bed.candidates = lambda pace, own, progress=None: ([], "nothing")
    from web.backend import make
    paces: list[str] = []
    real_start = make.start

    def spy(*a, **k):                     # the pace Make is asked to cut at
        paces.append(a[3])
        return real_start(*a, **k)
    make.start = spy
    visitor = {"x-vibecut-visitor": "1"}
    try:
        with TestClient(backend.app) as c:
            r = c.get("/api/profile/start").json()
            check("asked, on this computer", r["signed_in"] and r["ask"] and not r["made"], json.dumps(r))
            r = c.get("/api/profile/start", headers=visitor).json()
            check("logged out: no question, nothing shown", r == {"signed_in": False, "ask": False, "made": False}, json.dumps(r))
            check("logged out can't save or skip",
                  c.post("/api/profile/start", json={"pace": "fast"}, headers=visitor).status_code == 401
                  and c.post("/api/profile/skip", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 401)
            check("and nothing was kept", defaults.asked() is None and "pace" not in defaults.get())
            r = c.post("/api/profile/skip").json()
            check("Not now: not asked again", not r["ask"] and not r["made"])
            bad = [c.post("/api/profile/start", json=b).status_code for b in
                   ({"pace": "slow"}, {"transition": "wipe"}, {"template": "comic"}, {"makes": "films"})]
            check("picks it doesn't know are refused", bad == [422] * 4, str(bad))
            r = c.post("/api/profile/start", json={"makes": "vlog", "pace": "calm", "transition": "dissolve",
                                                  "captions": True, "template": "tape"}).json()
            check("saved: made, as picked", r["made"] and not r["ask"] and (r["makes"], r["pace"], r["transition"], r["captions"], r["template"])
                  == ("vlog", "calm", "dissolve", True, "tape"), json.dumps(r))
            r = c.post("/api/profile/start", json={"pace": "fast"}).json()
            check("one tap changes only that", (r["pace"], r["transition"], r["template"]) == ("fast", "dissolve", "tape"), json.dumps(r))
            r = c.post("/api/profile/start", json={"transition": "cut", "template": None}).json()
            check("a plain cut and Soft captions are no pick at all", r["transition"] is None and r["template"] is None
                  and "transition" not in defaults.get() and "caption_template" not in defaults.get(), json.dumps(r))

            def wait_make(job):
                for _ in range(600):
                    if job["stage"] in ("done", "error"):
                        return job
                    time.sleep(0.25)
                    job = c.get(f"/api/make/{job['id']}").json()
                return job

            def shoot(name: str) -> None:
                c.post("/api/projects", json={"name": name})
                wait(c, c.post("/api/import", json={"paths": clips}).json())
                for rec in backend.CLIPS.values():
                    for sh in rec.get("shots", []):
                        sh["utility"] = False

            def made_turns(s: dict) -> list[str]:
                return [t["text"] for t in s["turns"] if not t["undone"]]

            print("the same footage, without a profile")
            defaults.forget()
            shoot("Without")
            job = wait_make(c.post("/api/make", json={"format": "tall", "look": "cozy", "music": False}).json())
            s = c.get("/api/session").json()
            footage_pace = paces[-1]
            n_words = len(backend.SESSION.board.get("overlays") or [])
            check("made with the footage's pace, nothing added", job["stage"] == "done" and "From your profile" not in made_turns(s)
                  and "profile" not in s["brief"]["tempo"], json.dumps({"pace": footage_pace, "turns": made_turns(s)}))
            check("Make put words on screen", n_words > 0, str(n_words))
            c.post("/api/pace", json={"pace": "calm" if footage_pace != "calm" else "fast"})
            c.post("/api/captions", json={"on": False})
            check("no profile: Frames teaches it nothing", "pace" not in defaults.get() and "captions" not in defaults.get(),
                  json.dumps(defaults.get()))
            backend._close_project()

            print("the same footage, with a profile")
            want = "calm" if footage_pace != "calm" else "fast"
            c.post("/api/profile/start", json={"makes": "vlog", "pace": want, "transition": "dissolve", "captions": False})
            shoot("With")
            s = c.post("/api/brief/auto", json={"format": "tall", "look": "cozy"}).json()
            check("the brief starts from the profile's pace, and says so", s["brief"]["style"]["pace"] == want
                  and "your profile" in s["brief"]["tempo"], json.dumps({"pace": s["brief"]["style"]["pace"], "tempo": s["brief"]["tempo"]}))
            job = wait_make(c.post("/api/make", json={"format": "tall", "look": "cozy", "music": False}).json())
            s = c.get("/api/session").json()
            b = backend.SESSION.board
            check("Make cuts at the profile's pace, not the footage's", paces[-2:] == [footage_pace, want], str(paces))
            mine = [t for t in s["turns"] if t["text"] == "From your profile" and not t["undone"]]
            check("one turn from the profile, right after Make", job["stage"] == "done" and len(mine) == 1
                  and made_turns(s)[-1] == "From your profile", json.dumps(made_turns(s)))
            check("its transition at every cut", (b.get("picture_all") or {}).get("kind") == "dissolve", json.dumps(b.get("picture_all")))
            check("no captions", not b.get("overlays"), str(len(b.get("overlays") or [])))
            check("it says what it did", "no captions" in mine[0]["reply"] and "fade at every cut" in mine[0]["reply"], mine[0]["reply"])
            s = c.post(f"/api/turns/{mine[0]['id']}/toggle").json()
            b = backend.SESSION.board
            check("Undo takes only that away", len(b.get("overlays") or []) == n_words and not (b.get("picture_all") or {}).get("kind"),
                  json.dumps({"words": len(b.get("overlays") or []), "all": b.get("picture_all")}))

            print("Frames keeps the profile up to date")
            c.post(f"/api/turns/{mine[0]['id']}/toggle")
            c.post("/api/pace", json={"pace": "balanced"})
            check("the pace", defaults.get().get("pace") == "balanced")
            c.post("/api/captions", json={"on": True})
            check("captions back on", "captions" not in defaults.get() and c.get("/api/profile/start").json()["captions"] is True)
            c.post("/api/ops", json={"ops": [{"op": "set_transition", "all": True, "kind": "flash"}], "label": "Flash"})
            check("a transition for every cut", defaults.get().get("transition") == "flash")
            c.post("/api/ops", json={"ops": [{"op": "set_transition", "shot": backend.SESSION.board["beats"][0]["shots"][0]["id"],
                                              "kind": "blur"}], "label": "Blur"})
            check("but not one cut's", defaults.get().get("transition") == "flash")

            print("a chosen story")
            c.post("/api/profile/start", json={"template": "tape", "transition": "zoom", "captions": True})
            opts = [o for o in (backend.SESSION.proposals or {}).get("options", []) if o.get("key") != "made"]
            if opts:
                s = c.post("/api/ops", json={"ops": [{"op": "choose_option", "option": opts[0]["key"]}], "label": "Other story"}).json()
                b = backend.SESSION.board
                check("its caption style and transition", (b.get("picture_all") or {}).get("kind") == "zoom"
                      and (not b.get("overlays") or (b.get("overlay_style") or {}).get("template") == "tape"),
                      json.dumps({"all": b.get("picture_all"), "style": b.get("overlay_style"), "turns": made_turns(s)[-4:]}))
            else:
                check("other stories to choose from", False, json.dumps(list((backend.SESSION.proposals or {}).keys())))
            backend._close_project()

            print("a lesson")
            c.post("/api/profile/start", json={"makes": "lesson", "transition": "cut", "captions": True, "template": None})
            said: list[str] = []

            def heard(board, cat, clips_, about=""):
                said.append(about)
                first = board["beats"][0]["shots"][0]
                return [{"op": "add_overlay", "kind": "caption", "text": "so this is how you fold it",
                         "anchor": {"to": "shot", "id": first.get("key") or first["id"]}, "at": 0.2, "dur": 1.5}], []
            real_subs = backend.subtitles.caption_ops
            backend.subtitles.caption_ops = heard
            try:
                shoot("Lesson")
                job = wait_make(c.post("/api/make", json={"format": "tall", "look": "cozy", "music": False}).json())
            finally:
                backend.subtitles.caption_ops = real_subs
            b = backend.SESSION.board
            words = b.get("overlays") or []
            s = c.get("/api/session").json()
            check("the brief asks for subtitles", s["brief"]["style"]["captions"] == "transcribe", s["brief"]["said"])
            check("subtitles of what's said, in place of Make's lines", job["stage"] == "done" and said
                  and any(o["text"] == "so this is how you fold it" for o in words)
                  and not any(o["kind"] == "part" for o in words), json.dumps([(o["kind"], o["text"]) for o in words]))
            check("a plain cut adds no transition", not (b.get("picture_all") or {}).get("kind"))
            backend._close_project()
    finally:
        bed.candidates = real
        make.start = real_start
        defaults.forget()

    print()
    if failures:
        print(f"{len(failures)} failed: {failures}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
