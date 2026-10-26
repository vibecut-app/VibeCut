"""Post a finished video to the creator's own YouTube channel -- only when
they press Post on a screen that shows what goes up, where, and to whom.

The user's decision of 2026-10-23 ("start direct posting with YouTube …
with a confirm before every post"). How it is done, and why this way:

- **The creator's own Google sign-in.** OAuth 2.0 for installed apps, as
  Google documents it for desktop programs: a one-time listener on a free
  port of 127.0.0.1 is the redirect, PKCE (S256) instead of a secret, and
  a `state` that must come back unchanged. Scopes: `youtube.upload` (post
  only, no edits or deletes) and `youtube.readonly` (to name the channel
  on the confirm screen -- you can't confirm a post to a channel you can't
  see).
- **Tokens stay on this Mac.** The refresh token is in the macOS Keychain
  (`security`), elsewhere in a 0600 file under the cache; the channel's
  name and picture (not secret) in `youtube.json` beside it. Access tokens
  live in memory. Disconnect revokes the token at Google and forgets it.
- **One confirm per post.** `prepare` hands out a single-use code for one
  export; `post` refuses without it (app.py). Nothing here posts by itself,
  retries a post, or posts again.
- **Resumable upload over urllib** (no Google SDK; the repo is numpy +
  fastapi): the metadata starts a session, the file goes up in chunks
  (multiples of 256 KiB), a dropped chunk asks where the upload stands and
  carries on from there. Stop between chunks leaves nothing on YouTube.
- **Shorts** have no flag: YouTube makes a vertical video of 3 min or less
  a Short by itself (share.py says which it will be).

Config: YOUTUBE_CLIENT_ID (a "Desktop app" OAuth client from the creator's
Google Cloud project; YOUTUBE_CLIENT_SECRET if Google issued one) in the
environment or web/.env. Without it `configured()` is False and the app
says so where the button would be. VIBECUT_GOOGLE_BASE points every Google
address at a stand-in (tests, the walkthrough); VIBECUT_YT_STORE=file keeps
tokens out of the Keychain.
"""

from __future__ import annotations

import base64
import hashlib
import html
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .indexer import CACHE

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
SCOPES = ("https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly")
KEYCHAIN_SERVICE = "VibeCut YouTube"
TIMEOUT_S = 30.0
SIGN_IN_S = 10 * 60          # the sign-in page waits this long for the creator
CHUNK = 8 * 1024 * 1024      # a multiple of 256 KiB, as resumable uploads ask
RETRIES = 5
TITLE_MAX = 100              # YouTube's limits on the snippet
DESCRIPTION_MAX = 5000
PRIVACY = ("private", "unlisted", "public")
CATEGORY = "22"              # People & Blogs: where vlogs live


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        k, _, v = line.strip().partition("=")
        if k and v and not k.startswith("#") and k.strip().startswith("YOUTUBE_"):
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()


def _urls() -> dict:
    base = os.environ.get("VIBECUT_GOOGLE_BASE", "").rstrip("/")
    if base:
        return {"auth": base + "/o/oauth2/v2/auth", "token": base + "/token", "revoke": base + "/revoke",
                "api": base + "/youtube/v3", "upload": base + "/upload/youtube/v3"}
    return {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
            "revoke": "https://oauth2.googleapis.com/revoke", "api": "https://www.googleapis.com/youtube/v3",
            "upload": "https://www.googleapis.com/upload/youtube/v3"}


def client() -> tuple[str, str | None] | None:
    cid = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    return (cid, os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip() or None) if cid else None


def configured() -> bool:
    return client() is not None


# --------------------------------------------------------------------------
# where the sign-in is kept
# --------------------------------------------------------------------------

def _info_path() -> Path:
    return CACHE / "youtube.json"


def _keychain() -> bool:
    return sys.platform == "darwin" and os.environ.get("VIBECUT_YT_STORE", "keychain") != "file"


def _account() -> str:
    return client()[0] if client() else "vibecut"


def _save_refresh(token: str) -> None:
    if _keychain():
        subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", _account(), "-w", token],
                       check=True, capture_output=True, timeout=20)
        return
    p = CACHE / "youtube-token"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token)
    os.chmod(p, 0o600)


def _load_refresh() -> str | None:
    if _keychain():
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", _account(), "-w"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or None if r.returncode == 0 else None
    p = CACHE / "youtube-token"
    return p.read_text().strip() or None if p.exists() else None


def _drop_refresh() -> None:
    if _keychain():
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", _account()],
                       capture_output=True, timeout=20)
    (CACHE / "youtube-token").unlink(missing_ok=True)


def _info() -> dict:
    try:
        return json.loads(_info_path().read_text())
    except (OSError, ValueError):
        return {}


def _set_info(d: dict | None) -> None:
    if d is None:
        _info_path().unlink(missing_ok=True)
        return
    _info_path().parent.mkdir(parents=True, exist_ok=True)
    _info_path().write_text(json.dumps(d))


# --------------------------------------------------------------------------
# talking to Google
# --------------------------------------------------------------------------

class YouTubeError(Exception):
    """Something to tell the creator, in plain words."""


def _say(code: int, body: bytes | str) -> str:
    """Google's error, as the creator should hear it."""
    try:
        d = json.loads(body)
    except (ValueError, TypeError):
        d = {}
    err = d.get("error")
    reason = ""
    if isinstance(err, dict):
        reason = ((err.get("errors") or [{}])[0].get("reason") or err.get("status") or "")
        msg = err.get("message") or ""
    else:
        reason, msg = str(err or ""), d.get("error_description") or ""
    if reason == "invalid_grant":
        return "YouTube signed VibeCut out (sign-ins from an app still in testing last 7 days). Connect again."
    if reason in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"):
        return "YouTube's upload limit for today is used up. Try tomorrow, or use YouTube's upload page."
    if reason == "youtubeSignupRequired":
        return "This Google account has no YouTube channel yet. Make one on youtube.com, then connect again."
    if reason in ("invalidTitle", "invalidDescription"):
        return "YouTube didn't take the title or description. Leave out < and >, and keep the title short."
    if code == 403 and "insufficient" in msg.lower():
        return "VibeCut wasn't given permission to post. Connect again and allow uploads."
    return f"YouTube said no ({code}{': ' + msg[:160] if msg else ''})."


def _form(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise YouTubeError(_say(e.code, e.read())) from e
    except OSError as e:
        raise YouTubeError("Couldn't reach Google — check the internet connection.") from e


_ACCESS: dict = {"token": None, "until": 0.0}


def access_token() -> str:
    if _ACCESS["token"] and time.time() < _ACCESS["until"] - 60:
        return _ACCESS["token"]
    refresh, c = _load_refresh(), client()
    if not refresh or not c:
        raise YouTubeError("Connect your YouTube channel first.")
    data = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": c[0]}
    if c[1]:
        data["client_secret"] = c[1]
    try:
        d = _form(_urls()["token"], data)
    except YouTubeError as e:
        if "signed VibeCut out" in str(e):
            forget()
        raise
    _ACCESS.update(token=d["access_token"], until=time.time() + float(d.get("expires_in", 3600)))
    return d["access_token"]


def _get(path: str, query: dict) -> dict:
    req = urllib.request.Request(f"{_urls()['api']}/{path}?{urllib.parse.urlencode(query)}",
                                 headers={"Authorization": "Bearer " + access_token()})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise YouTubeError(_say(e.code, e.read())) from e
    except OSError as e:
        raise YouTubeError("Couldn't reach YouTube — check the internet connection.") from e


def channel() -> dict | None:
    """The channel a post would land on: id, name, picture."""
    items = _get("channels", {"part": "snippet", "mine": "true"}).get("items") or []
    if not items:
        return None
    sn = items[0].get("snippet") or {}
    thumb = ((sn.get("thumbnails") or {}).get("default") or {}).get("url")
    return {"id": items[0].get("id"), "title": sn.get("title") or "your channel", "thumb": thumb}


# --------------------------------------------------------------------------
# sign-in: Google's page in the browser, the answer to a one-time listener
# --------------------------------------------------------------------------

SIGNIN: dict = {"state": None, "verifier": None, "redirect": None, "server": None, "error": None, "busy": False}
_lock = threading.Lock()

_PAGE = """<!doctype html><meta charset=utf-8><title>VibeCut</title>
<body style="font:16px -apple-system,system-ui,sans-serif;background:#f6f3ee;color:#222;display:grid;place-items:center;height:90vh">
<div style="text-align:center"><p style="font-size:22px">{head}</p><p style="color:#666">{line}</p></div>"""


def _finish(query: dict) -> tuple[str, str]:
    """The browser came back from Google: check it, trade the code for tokens."""
    with _lock:
        state, verifier, redirect = SIGNIN["state"], SIGNIN["verifier"], SIGNIN["redirect"]
    if not state or query.get("state") != state:
        return "That sign-in link is stale.", "Go back to VibeCut and press Connect again."
    if query.get("error"):
        SIGNIN["error"] = "You didn't allow it on Google's page, so nothing changed."
        return "Not connected.", "You can close this tab."
    c = client()
    data = {"grant_type": "authorization_code", "code": query.get("code", ""), "client_id": c[0],
            "redirect_uri": redirect, "code_verifier": verifier}
    if c[1]:
        data["client_secret"] = c[1]
    try:
        d = _form(_urls()["token"], data)
        if not d.get("refresh_token"):
            raise YouTubeError("Google didn't give VibeCut a lasting sign-in. Press Connect again.")
        granted = set((d.get("scope") or " ".join(SCOPES)).split())
        if SCOPES[0] not in granted:
            raise YouTubeError("Uploading wasn't allowed on Google's page. Connect again and tick it.")
        _save_refresh(d["refresh_token"])
        _ACCESS.update(token=d["access_token"], until=time.time() + float(d.get("expires_in", 3600)))
        ch = channel()
        _set_info({"channel": ch, "at": time.time()})
        SIGNIN["error"] = None if ch else "This Google account has no YouTube channel yet. Make one on youtube.com, then connect again."
    except YouTubeError as e:
        SIGNIN["error"] = str(e)
        return "Not connected.", html.escape(str(e))
    finally:
        with _lock:
            SIGNIN.update(state=None, verifier=None)
    return "Connected to YouTube.", "You can close this tab and go back to VibeCut."


class _Answer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 -- http.server's name
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}
        if not q:            # a favicon or a probe: not the answer
            self.send_response(404)
            self.end_headers()
            return
        head, line = _finish(q)
        body = _PAGE.format(head=head, line=line).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if SIGNIN["state"] is None and SIGNIN.get("server") is self.server:
            _stop_listener()

    def log_message(self, *a):  # quiet
        pass


def _stop_listener() -> None:
    srv = SIGNIN.get("server")
    SIGNIN["server"] = None
    if srv:
        def down():
            srv.shutdown()
            srv.server_close()    # free the port: a late answer is refused, not left hanging
        threading.Thread(target=down, daemon=True).start()


def _expire(srv) -> None:
    """Nobody came back from Google's page in time: stop listening."""
    if SIGNIN.get("server") is srv:
        _stop_listener()
        with _lock:
            SIGNIN.update(state=None, verifier=None)


def connect() -> str:
    """Start a sign-in: the address of Google's page for the creator to open."""
    c = client()
    if not c:
        raise YouTubeError("YouTube isn't set up on this Mac (no YOUTUBE_CLIENT_ID in web/.env).")
    _stop_listener()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    srv.timeout = 1
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}"
    with _lock:
        SIGNIN.update(state=state, verifier=verifier, redirect=redirect, server=srv, error=None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    timer = threading.Timer(SIGN_IN_S, _expire, args=(srv,))
    timer.daemon = True          # never keeps the app from quitting
    timer.start()
    q = {"client_id": c[0], "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
         "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
         "access_type": "offline", "prompt": "consent"}
    return _urls()["auth"] + "?" + urllib.parse.urlencode(q)


def status() -> dict:
    info = _info()
    connected = bool(info) and _load_refresh() is not None
    return {"configured": configured(), "connected": connected, "channel": info.get("channel") if connected else None,
            "signing_in": SIGNIN["state"] is not None, "error": SIGNIN["error"],
            "keychain": _keychain()}


def forget() -> None:
    _drop_refresh()
    _set_info(None)
    _ACCESS.update(token=None, until=0.0)


def disconnect() -> None:
    """Sign out: Google forgets VibeCut's access, and so does this Mac."""
    token = _load_refresh()
    if token:
        try:
            _form(_urls()["revoke"], {"token": token})
        except YouTubeError:
            pass          # already revoked, or offline: forgetting it here is what matters
    forget()
    SIGNIN["error"] = None


# --------------------------------------------------------------------------
# the post: one resumable upload, started only by a confirmed request
# --------------------------------------------------------------------------

def check_meta(title: str, description: str, privacy: str, kids: bool | None) -> dict:
    title, description = title.strip(), description.strip()
    if not title:
        raise ValueError("Give it a title.")
    if len(title) > TITLE_MAX:
        raise ValueError(f"The title is {len(title)} characters; YouTube takes {TITLE_MAX}.")
    if len(description.encode()) > DESCRIPTION_MAX:
        raise ValueError(f"The description is too long for YouTube ({DESCRIPTION_MAX} bytes at most).")
    if any(ch in title + description for ch in "<>"):
        raise ValueError("YouTube doesn't take < or > in a title or description.")
    if privacy not in PRIVACY:
        raise ValueError("Choose who can see it.")
    if kids is None:
        raise ValueError("Say whether it's made for kids — YouTube asks every video.")
    return {"snippet": {"title": title, "description": description, "categoryId": CATEGORY},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(kids)}}


@dataclass
class Post:
    id: str
    path: str
    meta: dict
    short: bool
    stage: str = "uploading"          # uploading → done | error | stopped
    sent: int = 0
    total: int = 0
    video: str | None = None
    privacy: str | None = None        # what YouTube says it is, after
    error: str | None = None
    stop: bool = False
    cover: str | None = None          # the chosen cover's JPEG, sent once the video is up
    cover_state: str | None = None    # "set", or why it wasn't
    started: float = field(default_factory=time.time)

    def public(self) -> dict:
        asked = self.meta["status"]["privacyStatus"]
        url = (f"https://youtube.com/shorts/{self.video}" if self.short else f"https://youtu.be/{self.video}") if self.video else None
        return {"id": self.id, "stage": self.stage, "sent": self.sent, "total": self.total,
                "progress": round(self.sent / self.total, 3) if self.total else 0.0,
                "title": self.meta["snippet"]["title"], "asked": asked, "privacy": self.privacy,
                "video": self.video, "url": url,
                "studio": f"https://studio.youtube.com/video/{self.video}/edit" if self.video else None,
                "error": self.error, "cover": self.cover_state, "elapsed": round(time.time() - self.started, 1)}


POSTS: dict[str, Post] = {}


def _chunk() -> int:
    return int(os.environ.get("VIBECUT_YT_CHUNK", CHUNK))


def _open_session(post: Post) -> str:
    q = urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status"})
    req = urllib.request.Request(f"{_urls()['upload']}/videos?{q}", method="POST", data=json.dumps(post.meta).encode(),
                                 headers={"Authorization": "Bearer " + access_token(),
                                          "Content-Type": "application/json; charset=UTF-8",
                                          "X-Upload-Content-Length": str(post.total),
                                          "X-Upload-Content-Type": "video/mp4"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            loc = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        raise YouTubeError(_say(e.code, e.read())) from e
    except OSError as e:
        raise YouTubeError("Couldn't reach YouTube — check the internet connection.") from e
    if not loc:
        raise YouTubeError("YouTube didn't open an upload. Try again in a minute.")
    return loc


def _put(session: str, body: bytes, rng: str) -> tuple[int, dict, dict]:
    """One PUT to the session: (status, headers, json). 308 = keep going."""
    req = urllib.request.Request(session, method="PUT", data=body,
                                 headers={"Authorization": "Bearer " + access_token(), "Content-Length": str(len(body)),
                                          "Content-Range": rng})
    try:
        with urllib.request.urlopen(req, timeout=max(TIMEOUT_S, 120)) as r:
            return r.status, dict(r.headers), json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        if e.code == 308:
            return 308, dict(e.headers), {}
        try:
            j = json.loads(raw or b"{}")
        except ValueError:
            j = {}
        return e.code, dict(e.headers), {"_raw": raw, **j}


def _next_byte(headers: dict) -> int:
    rng = {k.lower(): v for k, v in headers.items()}.get("range")
    return int(rng.rsplit("-", 1)[1]) + 1 if rng else 0


def _run(post: Post, on_done) -> None:
    try:
        session = _open_session(post)
        size, at, tries = post.total, 0, 0
        with open(post.path, "rb") as f:
            while True:
                if post.stop:
                    post.stage = "stopped"
                    return
                f.seek(at)
                body = f.read(_chunk())
                end = at + len(body) - 1
                try:
                    code, headers, j = _put(session, body, f"bytes {at}-{end}/{size}")
                except OSError:
                    code, headers, j = 0, {}, {}
                if code in (200, 201):
                    post.sent, post.video = size, j.get("id")
                    post.privacy = (j.get("status") or {}).get("privacyStatus")
                    post.stage = "done"
                    break
                if code == 308:
                    at, tries = _next_byte(headers), 0
                    post.sent = at
                    continue
                if code in (0, 500, 502, 503, 504) and tries < RETRIES:
                    # dropped: ask where it stands, then carry on from there
                    tries += 1
                    time.sleep(min(2 ** tries, 30) * float(os.environ.get("VIBECUT_YT_BACKOFF", 1)))
                    try:
                        code, headers, j = _put(session, b"", f"bytes */{size}")
                    except OSError:
                        continue
                    if code in (200, 201):
                        post.sent, post.video = size, j.get("id")
                        post.privacy = (j.get("status") or {}).get("privacyStatus")
                        post.stage = "done"
                        break
                    if code == 308:
                        at = _next_byte(headers)
                        post.sent = at
                    continue
                raise YouTubeError(_say(code, j.get("_raw") or json.dumps(j)))
    except YouTubeError as e:
        post.stage, post.error = "error", str(e)
    except Exception as e:  # noqa: BLE001 -- the job reports, never crashes the app
        post.stage, post.error = "error", f"The upload stopped: {e}"
    finally:
        if post.stage == "done" and post.cover and post.video:
            post.cover_state = set_thumbnail(post.video, post.cover)
        if on_done:
            try:
                on_done(post)
            except Exception:  # noqa: BLE001
                pass


def set_thumbnail(video: str, jpeg: str) -> str:
    """The creator's chosen cover as the video's thumbnail. A refusal never
    undoes the post: it is said, and the cover stays beside the file."""
    try:
        body = Path(jpeg).read_bytes()
    except OSError:
        return "The cover file is gone, so YouTube kept its own."
    req = urllib.request.Request(f"{_urls()['upload']}/thumbnails/set?{urllib.parse.urlencode({'videoId': video})}",
                                 method="POST", data=body,
                                 headers={"Authorization": "Bearer " + access_token(), "Content-Type": "image/jpeg",
                                          "Content-Length": str(len(body))})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S):
            return "set"
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return ("YouTube didn't take the cover: custom covers need a verified channel "
                    "(youtube.com/verify). It's saved beside the video for later.")
        return "YouTube didn't take the cover. " + _say(e.code, e.read())
    except (OSError, YouTubeError):
        return "Couldn't send the cover — it's saved beside the video; add it in YouTube Studio."


def start(path: str, meta: dict, short: bool, on_done=None, cover: str | None = None) -> Post:
    if not os.path.isfile(path):
        raise YouTubeError("The exported file is no longer where it was saved.")
    post = Post(id=uuid.uuid4().hex[:12], path=path, meta=meta, short=short, total=os.path.getsize(path),
                cover=cover if cover and not short else None)
    POSTS[post.id] = post
    threading.Thread(target=_run, args=(post, on_done), daemon=True).start()
    return post
