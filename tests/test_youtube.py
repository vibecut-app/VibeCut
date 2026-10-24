"""Posting to YouTube: the creator's sign-in, one confirmed post at a time.

Against a stand-in Google (tests/fake_google.py), nothing leaves the Mac:
the sign-in uses PKCE and a state that must come back, a "no" on Google's
page connects nothing, the token is kept out of youtube.json; a post needs
the single-use code from this export's confirm screen and an answer to
"made for kids?", and goes up whole in chunks, even when one is dropped;
what YouTube says (private when public was asked) is reported; a used-up
quota is said plainly; Stop leaves nothing; a revoked sign-in is forgotten;
the post is on the project's record and launchlog counts it.

    python tests/test_youtube.py
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import urllib.parse
import urllib.request

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-youtube-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
os.environ["VIBECUT_YT_STORE"] = "file"        # never the real Keychain
os.environ["YOUTUBE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"
os.environ["VIBECUT_YT_CHUNK"] = "65536"        # several chunks from a small file
os.environ["VIBECUT_YT_BACKOFF"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def open_page(url: str) -> str:
    """What the creator's browser does: Google's page, then back to the listener."""
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.read().decode()


def wait_post(c, pid: str) -> dict:
    for _ in range(400):
        p = c.get(f"/api/youtube/posts/{pid}").json()
        if p["stage"] != "uploading":
            return p
        time.sleep(0.05)
    return p


def main() -> int:
    from tests.fake_google import Fake
    fake = Fake().start()
    os.environ["VIBECUT_GOOGLE_BASE"] = fake.base
    from web.backend import youtube

    print("sign-in")
    cid = os.environ.pop("YOUTUBE_CLIENT_ID")
    try:
        youtube.connect()
        check("without a client id it says so", False)
    except youtube.YouTubeError as e:
        check("without a client id it says so", "isn't set up" in str(e))
    os.environ["YOUTUBE_CLIENT_ID"] = cid
    url = youtube.connect()
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    check("Google's page is asked for PKCE, a state, a lasting sign-in, upload + read",
          q["code_challenge_method"] == "S256" and len(q["state"]) > 20 and q["access_type"] == "offline"
          and q["scope"].split() == list(youtube.SCOPES) and q["redirect_uri"].startswith("http://127.0.0.1:"), json.dumps(q)[:200])
    fake.deny = True
    page = open_page(url)
    s = youtube.status()
    check("a no on Google's page connects nothing, and says why", "Not connected" in page and not s["connected"]
          and "didn't allow" in (s["error"] or ""), s["error"] or "")
    fake.deny = False
    url = youtube.connect()
    page = open_page(url)
    s = youtube.status()
    check("a yes connects, naming the channel", "Connected to YouTube" in page and s["connected"]
          and s["channel"]["title"] == "Sarah's Days" and not s["signing_in"] and s["error"] is None, json.dumps(s))
    tok = youtube.CACHE / "youtube-token"
    check("the token is kept apart, readable by this user only", tok.exists()
          and stat.S_IMODE(tok.stat().st_mode) == 0o600 and fake.refresh not in youtube._info_path().read_text())
    redirect = q["redirect_uri"]
    try:
        stale = open_page(redirect + "?code=x&state=forged")
    except OSError:
        stale = "listener gone"
    check("a forged or old answer changes nothing", ("stale" in stale or stale == "listener gone") and youtube.status()["connected"])

    print("what a post must say")
    for args, why in [(("", "", "private", False), "title"), (("x" * 101, "", "private", False), "101"),
                      (("a <b>", "", "private", False), "<"), (("ok", "", "everyone", False), "who"),
                      (("ok", "", "private", None), "kids")]:
        try:
            youtube.check_meta(*args)
            check(f"refused: {why}", False)
        except ValueError:
            check(f"refused: {why}", True)
    m = youtube.check_meta(" A day ", "Music: x", "unlisted", False)
    check("a good one is the snippet and status YouTube takes", m == {
        "snippet": {"title": "A day", "description": "Music: x", "categoryId": "22"},
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}})

    print("through the API")
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend
    from web.backend import launchlog
    a = clip(PTMP / "yt-a.mp4", 6, "0xff8a1e", "0x2a3440", "'325+40*sin(t)'", "2026-09-20T08:10:00")
    b = clip(PTMP / "yt-b.mp4", 7, "0x1ec8ff", "0x203028", "'120+30*t'", "2026-09-20T11:05:00")
    with TestClient(backend.app) as c:
        check("the app says posting is set up", c.get("/api/projects").json()["capabilities"]["youtube"] is True)
        c.post("/api/projects", json={"name": "Post"})
        wait(c, c.post("/api/import", json={"paths": [a, b]}).json())
        c.post("/api/brief/auto", json={"format": "short", "look": "clean"})
        c.post("/api/cut/approve", json={})
        s = c.get("/api/session").json()
        s = c.post("/api/chat", json={"message": s["brief"]["message"], "style": s["brief"]["style"]}).json()
        c.post("/api/ops", json={"ops": [{"op": "choose_option", "option": s["proposals"]["options"][0]["key"]}], "label": "pick"})
        job = c.post("/api/export", json={"music": False}).json()
        jid = job["id"]
        job = c.post(f"/api/export/{jid}/start", json={"schedule": []}).json()
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                break
            time.sleep(0.25)
            job = c.get(f"/api/export/{jid}").json()
        check("exported", job["stage"] == "done", job.get("error") or "")
        data = open(job["path"], "rb").read()
        check("the file is bigger than one chunk", len(data) > 2 * 65536, str(len(data)))

        c.post("/api/youtube/disconnect")
        check("signed out: no confirm screen", c.post(f"/api/export/{jid}/youtube/prepare").status_code == 409)
        open_page(c.post("/api/youtube/connect").json()["url"])
        check("signed in again through the app", c.get("/api/youtube").json()["connected"])

        prep = c.post(f"/api/export/{jid}/youtube/prepare").json()
        check("the confirm screen: channel, title, a Short, a code", prep["channel"]["title"] == "Sarah's Days"
              and prep["title"] and prep["fit"]["name"] == "YouTube Shorts" and len(prep["confirm"]) > 10, json.dumps(prep)[:200])
        body = {"confirm": prep["confirm"], "title": "Saturday", "description": "a day out", "privacy": "public", "made_for_kids": False}
        check("no code, no post", c.post(f"/api/export/{jid}/youtube", json={**body, "confirm": "made-up"}).status_code == 409)
        check("no answer on kids, no post", c.post(f"/api/export/{jid}/youtube", json={**body, "made_for_kids": None}).status_code == 400)
        check("nothing reached YouTube yet", not fake.sessions)

        fake.drop_once = True
        p = c.post(f"/api/export/{jid}/youtube", json=body).json()
        p = wait_post(c, p["id"])
        up = fake.uploads[-1] if fake.uploads else {}
        check("posted, whole, byte for byte", p["stage"] == "done" and up.get("data") == data and p["video"] == "vid1",
              json.dumps({k: p[k] for k in ("stage", "error", "sent", "total")}))
        check("as a resumable upload, in chunks", "uploadType=resumable" in up.get("query", "")
              and sum(1 for r in fake.puts if not r.startswith("bytes */")) > 2)
        check("a dropped chunk asked where it stood and carried on", fake.dropped and any(r.startswith("bytes */") for r in fake.puts))
        check("with what the creator confirmed", up["meta"]["snippet"]["title"] == "Saturday"
              and up["meta"]["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False})
        check("a Short's address, and Studio's", p["url"] == "https://youtube.com/shorts/vid1" and p["studio"].endswith("/vid1/edit"))
        check("the code was used up", c.post(f"/api/export/{jid}/youtube", json=body).status_code == 409 and len(fake.uploads) == 1)
        pr = backend.PROJECT["p"]
        ev = [e for e in pr.events if e.get("how") == "youtube_post"]
        check("on the record: a share event and the post on its export", len(ev) == 1 and ev[0]["video"] == "vid1"
              and pr.exports[0]["posted"][0]["privacy"] == "public", json.dumps(ev))

        fake.force_private = True
        prep = c.post(f"/api/export/{jid}/youtube/prepare").json()
        p = wait_post(c, c.post(f"/api/export/{jid}/youtube", json={**body, "confirm": prep["confirm"]}).json()["id"])
        check("what YouTube set is reported beside what was asked", p["privacy"] == "private" and p["asked"] == "public")
        fake.force_private = False

        fake.quota = True
        prep = c.post(f"/api/export/{jid}/youtube/prepare").json()
        p = wait_post(c, c.post(f"/api/export/{jid}/youtube", json={**body, "confirm": prep["confirm"]}).json()["id"])
        check("a used-up quota is said plainly", p["stage"] == "error" and "limit for today" in (p["error"] or ""), p["error"] or "")
        fake.quota = False

        n = len(fake.uploads)
        post = youtube.Post(id="stop", path=job["path"], meta=youtube.check_meta("x", "", "private", False), short=True,
                            total=len(data), stop=True)
        youtube._run(post, None)
        check("Stop leaves nothing on YouTube", post.stage == "stopped" and len(fake.uploads) == n)
        backend._close_project()

        fake.revoked.append(fake.refresh)
        youtube._ACCESS.update(token=None, until=0.0)
        try:
            youtube.access_token()
            check("a revoked sign-in is said in plain words", False)
        except youtube.YouTubeError as e:
            check("a revoked sign-in is said in plain words", "Connect again" in str(e), str(e))
        check("… and forgotten", not youtube.status()["connected"])
        fake.revoked.clear()

        open_page(c.post("/api/youtube/connect").json()["url"])
        s = c.post("/api/youtube/disconnect").json()
        check("disconnect revokes at Google and forgets here", not s["connected"] and fake.refresh in fake.revoked
              and not tok.exists() and not youtube._info_path().exists())
    summ = launchlog.summary()
    check("launchlog counts what was posted from VibeCut", summ["posted"] == 2 and "posted from VibeCut 2" in launchlog.page(summ),
          json.dumps({k: summ[k] for k in ("posted", "shares")}))
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
