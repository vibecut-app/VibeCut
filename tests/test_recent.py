"""Your recent videos: Home shows each video as its own picture, with Open
and Share (recent.py).

The rules: the video is the last export in the edit's own frame whose file
is still there (a version in the other frame only when that's all there
is); the card's moment is the chosen cover's, else the hook's middle noted
at export, else a little way in. Through the API: a made video lists its
first shot and length before it's exported; once exported its card is a
small JPEG of the export at the hook; after a restart (export jobs gone)
Share opens the project and takes the export up again from its record, so
the Share box works on the same file; a video with no export left to
share is refused with what to do, and a moved file takes the card back to
the edit's picture.

    python tests/test_recent.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-recent-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def rules() -> None:
    from web.backend import recent
    d = tempfile.mkdtemp(prefix="recent-files-")
    a, b, gone = (os.path.join(d, n) for n in ("a.mp4", "b.mp4", "gone.mp4"))
    for f in (a, b):
        open(f, "wb").write(b"x")
    ex = [{"job": "1", "path": a}, {"job": "2", "path": b, "alt": True}, {"job": "3", "path": gone}]
    check("the video is the last export in its own frame that is still there", recent.video_of(ex)[0] == 0)
    check("… a version in the other frame only when that's all there is",
          recent.video_of([{"path": b, "alt": True}, {"path": gone}])[0] == 0)
    check("nothing left on disk: no video", recent.video_of([{"path": gone}]) is None and recent.video_of([]) is None)
    check("the card's moment: the chosen cover's first",
          recent.poster_t({"cover": {"t": 4.2}, "poster_t": 1.0, "seconds": 30}) == 4.2)
    check("… else the hook's middle noted at export", recent.poster_t({"poster_t": 1.25, "seconds": 30}) == 1.25)
    check("… else a little way in, never past 3 s or the end",
          recent.poster_t({"seconds": 10}) == 1.5 and recent.poster_t({"seconds": 60}) == 3.0
          and recent.poster_t({"seconds": 0.05}) == 0.0)
    p = recent.public("abc123abc123", ex)
    check("a card carries the file, its length and where its picture is",
          p["file"] == "a.mp4" and p["poster"].startswith("/api/projects/abc123abc123/poster?v=") and not p["alt"], json.dumps(p))


def through_api() -> None:
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend
    from web.backend import covers, export
    from web.backend import projects as pj
    a = clip(PTMP / "rv-a.mp4", 6, "0xff8a1e", "0x2a3440", "'325+40*sin(t)'", "2026-09-20T08:10:00")
    b = clip(PTMP / "rv-b.mp4", 7, "0x1ec8ff", "0x203028", "'120+30*t'", "2026-09-20T11:05:00")
    with TestClient(backend.app) as c:
        pid = c.post("/api/projects", json={"name": "Recent"}).json()["project"]["id"]
        wait(c, c.post("/api/import", json={"paths": [a, b]}).json())
        c.post("/api/brief/auto", json={"format": "short", "look": "clean"})
        c.post("/api/cut/approve", json={})
        s = c.get("/api/session").json()
        s = c.post("/api/chat", json={"message": s["brief"]["message"], "style": s["brief"]["style"]}).json()
        c.post("/api/ops", json={"ops": [{"op": "choose_option", "option": s["proposals"]["options"][0]["key"]}], "label": "pick"})

        row = lambda: next(p for p in c.get("/api/projects").json()["projects"] if p["id"] == pid)  # noqa: E731
        r = row()
        first = c.get("/api/session").json()["board"]["beats"][0]["shots"][0]
        check("made, not exported: the card is the edit's first shot and its length, no Share",
              r["video"] is None and r["poster"] == first["thumb"] and r["seconds"] and r["seconds"] > 1,
              json.dumps({k: r[k] for k in ("video", "poster", "seconds")}))
        check("… and Share says why", c.post(f"/api/projects/{pid}/share").status_code == 409)
        check("… no export picture", c.get(f"/api/projects/{pid}/poster").status_code == 404)

        job = c.post("/api/export", json={"music": False}).json()
        jid = job["id"]
        job = c.post(f"/api/export/{jid}/start", json={"schedule": []}).json()
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                break
            time.sleep(0.25)
            job = c.get(f"/api/export/{jid}").json()
        check("exported", job["stage"] == "done", job.get("error") or "")
        rec = backend.PROJECT["p"].exports[-1]
        hook = covers.candidates(export.JOBS[jid].items)[0]
        check("the hook's middle is noted on the export's record", rec.get("poster_t") == hook, f"{rec.get('poster_t')} vs {hook}")
        r = row()
        check("exported: the card is the export, with its file and length",
              r["video"] and r["video"]["file"] == job["file"] and abs(r["video"]["seconds"] - job["total"]) < 0.01
              and r["stage"] == "exported", json.dumps(r["video"]))
        check("the edit's own length agrees with the export's", abs(r["seconds"] - job["total"]) < 0.6,
              f"{r['seconds']} vs {job['total']}")
        img = c.get(r["video"]["poster"])
        dims = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", "-"],
                              input=img.content, capture_output=True).stdout.decode().strip()
        check("its picture is a small JPEG of the export, long side 640", img.status_code == 200
              and img.content[:2] == b"\xff\xd8" and dims in ("360,640", "640,360"), dims)
        cv = c.post(f"/api/export/{jid}/cover", json={"t": 3.0}).json()
        r2 = row()
        check("a chosen cover moves the card's picture to that moment", r2["video"]["poster"] != r["video"]["poster"]
              and "3000-" in r2["video"]["poster"] and c.get(r2["video"]["poster"]).status_code == 200, json.dumps(cv))

        # a restart: no export jobs in memory, another project open
        export.JOBS.clear()
        other = c.post("/api/projects", json={"name": "Other"}).json()["project"]["id"]
        check("another project is open", backend.PROJECT["p"].id == other)
        check("an empty project has nothing to share", c.post(f"/api/projects/{other}/share").status_code == 409)
        rows = {p["id"]: p for p in c.get("/api/projects").json()["projects"]}
        check("… and no picture of a video", rows[other]["video"] is None and rows[other]["poster"] is None)
        j = c.post(f"/api/projects/{pid}/share")
        jj = j.json()
        check("Share from Home opens the video and takes its export up again", j.status_code == 200
              and backend.PROJECT["p"].id == pid and jj["id"] == jid and jj["stage"] == "done"
              and jj["file"] == job["file"] and jj["size"] == job["size"], json.dumps(jj)[:240])
        t = c.get(f"/api/export/{jid}/share").json()
        check("the Share box works on it: platforms, words, its cover",
              [p["name"] for p in t["platforms"]] == ["TikTok", "YouTube Shorts", "Instagram"]
              and t["post"]["caption"].strip() != "" and t["covers"] and t["cover"] and t["cover"]["t"] == 3.0,
              json.dumps({k: t[k] for k in ("post", "cover")})[:240])
        f = c.get(f"/api/export/{jid}/file")
        check("… and serves the same file", f.status_code == 200 and f.content == open(job["path"], "rb").read())
        check("sharing it is on the record", c.post(f"/api/export/{jid}/shared", json={"how": "download"}).status_code == 200
              and any(e.get("kind") == "share" and e.get("export") == 0 for e in backend.PROJECT["p"].events))
        again = c.post(f"/api/projects/{pid}/share").json()
        check("Share again reuses the same job", again["id"] == jid and len([k for k in export.JOBS if k == jid]) == 1)

        # the file moved away
        moved = job["path"] + ".moved"
        os.rename(job["path"], moved)
        try:
            r = row()
            check("a moved file: the card goes back to the edit's picture", r["video"] is None and r["poster"])
            check("… and Share says what to do", c.post(f"/api/projects/{pid}/share").status_code == 409
                  and "export it again" in c.post(f"/api/projects/{pid}/share").json()["detail"])
        finally:
            os.rename(moved, job["path"])
        check("a bad id is a 404", c.get("/api/projects/nope/poster").status_code == 404
              and c.post("/api/projects/nope/share").status_code == 404)
        backend._close_project()

        # a video saved before cards had the edit's picture: filled once, in the background
        before = row()
        path = pj.DIR / f"{pid}.json"
        rec = json.loads(path.read_text())
        rec["snapshot"].pop("poster"), rec["snapshot"].pop("seconds")
        rec["exports"][0]["path"] += ".gone"        # not exported any more, so the card shows the edit
        path.write_text(json.dumps(rec))
        r = c.get("/api/projects").json()
        old = next(p for p in r["projects"] if p["id"] == pid)
        check("an older video lists with no picture of its edit, and Home is told to ask again",
              old["poster"] is None and r["filling"] >= 1, json.dumps({"poster": old["poster"], "filling": r["filling"]}))
        for _ in range(120):
            if not r["filling"]:
                break
            time.sleep(0.25)
            r = c.get("/api/projects").json()
        new = next(p for p in r["projects"] if p["id"] == pid)
        check("… then its first shot and length are filled from its own log", new["poster"] == before["poster"]
              and new["seconds"] == before["seconds"] and r["filling"] == 0,
              json.dumps({k: new[k] for k in ("poster", "seconds")}))
        check("… without moving it in Home's order", abs(new["updated"] - old["updated"]) < 1e-6)
        check("… and only once", c.get("/api/projects").json()["filling"] == 0)


def main() -> int:
    print("rules")
    rules()
    print("through the API")
    through_api()
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
