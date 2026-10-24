"""Share it: each platform is checked against the file, and every way out is
on the record.

The rules (share.py): a vertical 25 s fits TikTok, Shorts and Reels; a
vertical 4 min is too long for a Short and a Reel but not for TikTok; a wide
video is a normal YouTube upload and is said to sit small on TikTok and
Reels. Through the API: a finished export lists its three platforms, each
browser-side share is recorded as a "share" event against that export, an
unknown one is refused, Show in Finder records itself, nothing is posted,
and launchlog counts the shares.

    python tests/test_share.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-share-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def rules() -> None:
    from web.backend import share
    by = lambda w, h, s: {p["id"]: p for p in share.targets(w, h, s)}  # noqa: E731
    short = by(1080, 1920, 25)
    check("a vertical 25 s fits all three", all(p["ok"] for p in short.values()), json.dumps(short)[:200])
    check("vertical and short = YouTube Shorts", short["youtube"]["name"] == "YouTube Shorts")
    long = by(1080, 1920, 240)
    check("a vertical 4 min is too long for a Short, said so", not long["youtube"]["ok"]
          and "Too long for a Short" in long["youtube"]["why"] and long["youtube"]["name"] == "YouTube")
    check("… and for a Reel", not long["instagram"]["ok"] and "Reel" in long["instagram"]["why"])
    check("… but not for TikTok", long["tiktok"]["ok"])
    wide = by(1920, 1080, 120)
    check("wide = a normal YouTube upload that fits", wide["youtube"]["ok"] and wide["youtube"]["name"] == "YouTube")
    check("wide on TikTok and Reels: kept, with the reason", not wide["tiktok"]["ok"] and "bars" in wide["tiktok"]["why"]
          and not wide["instagram"]["ok"])
    check("wide past 15 min: a note, not a refusal", by(1920, 1080, 20 * 60)["youtube"]["note"] is not None
          and by(1920, 1080, 20 * 60)["youtube"]["ok"])
    check("every platform opens its own https upload page", all(p["url"].startswith("https://") for p in short.values()))
    check("shapes", (share.shape(1080, 1920), share.shape(1920, 1080), share.shape(1080, 1080), share.shape(0, 0))
          == ("tall", "wide", "square", "unknown"))


def through_api() -> None:
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend
    from web.backend import launchlog
    a = clip(PTMP / "sh-a.mp4", 6, "0xff8a1e", "0x2a3440", "'325+40*sin(t)'", "2026-09-20T08:10:00")
    b = clip(PTMP / "sh-b.mp4", 7, "0x1ec8ff", "0x203028", "'120+30*t'", "2026-09-20T11:05:00")
    opened: list[list[str]] = []
    real_popen = backend.subprocess.Popen
    with TestClient(backend.app) as c:
        c.post("/api/projects", json={"name": "Share"})
        wait(c, c.post("/api/import", json={"paths": [a, b]}).json())
        c.post("/api/brief/auto", json={"format": "short", "look": "clean"})
        c.post("/api/cut/approve", json={})
        s = c.get("/api/session").json()
        s = c.post("/api/chat", json={"message": s["brief"]["message"], "style": s["brief"]["style"]}).json()
        c.post("/api/ops", json={"ops": [{"op": "choose_option", "option": s["proposals"]["options"][0]["key"]}], "label": "pick"})
        job = c.post("/api/export", json={"music": False}).json()
        jid = job["id"]
        check("not finished: no share list yet", c.get(f"/api/export/{jid}/share").status_code == 404)
        job = c.post(f"/api/export/{jid}/start", json={"schedule": []}).json()
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                break
            time.sleep(0.25)
            job = c.get(f"/api/export/{jid}").json()
        check("exported", job["stage"] == "done", job.get("error") or "")
        t = c.get(f"/api/export/{jid}/share").json()
        check("a short lists TikTok, YouTube Shorts and Instagram, all fitting",
              [p["name"] for p in t["platforms"]] == ["TikTok", "YouTube Shorts", "Instagram"]
              and all(p["ok"] for p in t["platforms"]) and t["shape"] == "tall", json.dumps(t)[:240])
        check("there are words to post with, never empty", t["post"]["caption"].strip() != "" and "#vlog" in t["post"]["hashtags"]
              and "#shorts" in t["post"]["hashtags"], json.dumps(t["post"])[:200])
        check("cover stills are offered, the hook first, none chosen yet", t["covers"] and t["cover"] is None
              and t["covers"][0]["t"] < 2.5, json.dumps(t["covers"]))
        r = c.get(t["covers"][0]["url"])
        check("a still is a small JPEG of the file", r.status_code == 200 and r.content[:2] == b"\xff\xd8"
              and r.headers["content-type"] == "image/jpeg")
        check("a moment outside the video is refused", c.post(f"/api/export/{jid}/cover", json={"t": 999}).status_code == 400)
        cv = c.post(f"/api/export/{jid}/cover", json={"t": t["covers"][0]["t"]}).json()
        beside = os.path.join(os.path.dirname(job["path"]), cv["file"])
        check("the chosen cover is saved full size beside the video", cv["file"].endswith(" cover.jpg") and os.path.isfile(beside)
              and os.path.getsize(beside) > os.path.getsize(os.path.join(os.environ["VIBECUT_CACHE"], "covers", jid,
                                                                          f"{int(round(t['covers'][0]['t'] * 1000))}.jpg")), json.dumps(cv))
        check("it is on the export's record, and served", c.get(f"/api/export/{jid}/share").json()["cover"]["file"] == cv["file"]
              and c.get(f"/api/export/{jid}/cover").content == open(beside, "rb").read())
        for how in ("download", "tiktok", "caption"):
            check(f"{how} is recorded", c.post(f"/api/export/{jid}/shared", json={"how": how}).status_code == 200)
        check("an unknown share is refused", c.post(f"/api/export/{jid}/shared", json={"how": "fax"}).status_code == 400)
        check("photos can't be claimed from the browser", c.post(f"/api/export/{jid}/shared", json={"how": "photos"}).status_code == 400)
        check("a missing export is a 404", c.post("/api/export/nope/shared", json={"how": "download"}).status_code == 404)
        # stand in for Finder only around this call (subprocess.run uses Popen too)
        backend.subprocess.Popen = lambda args, *k, **kw: opened.append(list(args))  # type: ignore[assignment]
        try:
            c.post(f"/api/export/{jid}/reveal")
        finally:
            backend.subprocess.Popen = real_popen  # type: ignore[assignment]
        ev = [e for e in backend.PROJECT["p"].events if e.get("kind") == "share"]
        want = ["download", "tiktok", "caption"] + (["finder"] if sys.platform == "darwin" else [])
        check("the shares are events against export 0", [e["how"] for e in ev] == want and all(e["export"] == 0 for e in ev),
              json.dumps(ev))
        if sys.platform == "darwin":
            check("Show in Finder reveals the file", opened and opened[-1][:2] == ["open", "-R"])
        backend._close_project()
    summ = launchlog.summary()
    check("launchlog counts shared projects and each way", summ["shared"] == 1 and summ["shares"].get("tiktok") == 1
          and summ["shares"].get("download") == 1, json.dumps({k: summ[k] for k in ("shared", "shares")}))
    check("the page says it", "Shared 1" in launchlog.page(summ) and "tiktok 1" in launchlog.page(summ))
    check("an older record without shares still counts", launchlog.summary([{"name": "old"}])["shared"] == 0)


def main() -> int:
    print("share rules")
    rules()
    print("through the API")
    through_api()
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
