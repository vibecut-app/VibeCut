"""A stand-in for Google's sign-in and YouTube's upload, on 127.0.0.1.

Just enough of each to hold VibeCut to the real protocol: the consent page
answers at once (or says no), the token endpoint checks the PKCE verifier
against the challenge and the redirect against the one asked for, the
channel list needs the bearer token, and a resumable upload is put
together from its chunks by Content-Range (308 + Range until the last,
then the video). Switches: `deny`, `no_channel`, `quota`, `drop_once`
(one chunk answered 503 and not kept), `force_private`, `thumb_refuse`;
thumbnails.set keeps what it was sent.

    python tests/fake_google.py 8790     # serve it, for a walkthrough
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import re
import sys
import threading
import urllib.parse


class Fake:
    def __init__(self) -> None:
        self.codes: dict[str, dict] = {}       # code -> {challenge, redirect}
        self.access = "ya29.stand-in"
        self.refresh = "1//stand-in-refresh"
        self.revoked: list[str] = []
        self.sessions: dict[str, dict] = {}    # n -> {meta, total, data}
        self.puts: list[str] = []              # Content-Range of every PUT
        self.uploads: list[dict] = []          # finished: {meta, data}
        self.deny = self.no_channel = self.quota = self.drop_once = self.force_private = False
        self.dropped = False
        self.thumbs: list[dict] = []           # {video, bytes}
        self.thumb_refuse = False
        self.srv: http.server.ThreadingHTTPServer | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def start(self, port: int = 0) -> "Fake":
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, body: dict | None = None, headers: dict | None = None) -> None:
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                if body is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _authed(self) -> bool:
                if self.headers.get("Authorization") != "Bearer " + fake.access:
                    self._send(401, {"error": {"code": 401, "message": "Invalid Credentials", "errors": [{"reason": "authError"}]}})
                    return False
                return True

            def do_GET(self):  # noqa: N802
                u = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                if u.path == "/o/oauth2/v2/auth":
                    code = f"code-{len(fake.codes)}"
                    fake.codes[code] = {"challenge": q.get("code_challenge"), "redirect": q.get("redirect_uri"),
                                        "scope": q.get("scope"), "method": q.get("code_challenge_method")}
                    ans = {"error": "access_denied", "state": q.get("state")} if fake.deny else {"code": code, "state": q.get("state")}
                    self._send(302, None, {"Location": q["redirect_uri"] + "?" + urllib.parse.urlencode(ans)})
                elif u.path == "/youtube/v3/channels":
                    if not self._authed():
                        return
                    items = [] if fake.no_channel else [{"id": "UCstandin", "snippet": {"title": "Sarah's Days", "thumbnails": {}}}]
                    self._send(200, {"items": items})
                else:
                    self._send(404, {"error": "not here"})

            def do_POST(self):  # noqa: N802
                u = urllib.parse.urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if u.path == "/token":
                    f = dict(urllib.parse.parse_qsl(body.decode()))
                    if f.get("grant_type") == "authorization_code":
                        c = fake.codes.pop(f.get("code", ""), None)
                        ok = c and c["redirect"] == f.get("redirect_uri") and c["method"] == "S256" and c["challenge"] == \
                            base64.urlsafe_b64encode(hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                        if not ok:
                            return self._send(400, {"error": "invalid_grant", "error_description": "Bad code or verifier"})
                        return self._send(200, {"access_token": fake.access, "refresh_token": fake.refresh, "expires_in": 3599,
                                                "scope": c["scope"], "token_type": "Bearer"})
                    if f.get("grant_type") == "refresh_token":
                        if f.get("refresh_token") != fake.refresh or f.get("refresh_token") in fake.revoked:
                            return self._send(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
                        return self._send(200, {"access_token": fake.access, "expires_in": 3599, "token_type": "Bearer"})
                    return self._send(400, {"error": "unsupported_grant_type"})
                if u.path == "/revoke":
                    fake.revoked.append(dict(urllib.parse.parse_qsl(body.decode())).get("token", ""))
                    return self._send(200, {})
                if u.path == "/upload/youtube/v3/thumbnails/set":
                    if not self._authed():
                        return
                    if fake.thumb_refuse:
                        return self._send(403, {"error": {"code": 403, "message": "The authenticated user doesn't have permissions to upload and set custom video thumbnails.",
                                                          "errors": [{"reason": "forbidden"}]}})
                    vid = dict(urllib.parse.parse_qsl(u.query)).get("videoId")
                    fake.thumbs.append({"video": vid, "bytes": body, "type": self.headers.get("Content-Type")})
                    return self._send(200, {"items": [{"default": {"url": "https://i.ytimg.com/x.jpg"}}]})
                if u.path == "/upload/youtube/v3/videos":
                    if not self._authed():
                        return
                    if fake.quota:
                        return self._send(403, {"error": {"code": 403, "message": "quota",
                                                          "errors": [{"reason": "quotaExceeded"}]}})
                    n = str(len(fake.sessions))
                    fake.sessions[n] = {"meta": json.loads(body), "total": int(self.headers["X-Upload-Content-Length"]),
                                        "data": bytearray(), "query": u.query}
                    return self._send(200, {}, {"Location": f"{fake.base}/upload/session/{n}"})
                self._send(404, {"error": "not here"})

            def do_PUT(self):  # noqa: N802
                m = re.fullmatch(r"/upload/session/(\d+)", urllib.parse.urlsplit(self.path).path)
                if not m or m.group(1) not in fake.sessions or not self._authed():
                    return self._send(404, {"error": "no session"}) if not m or m.group(1) not in fake.sessions else None
                s = fake.sessions[m.group(1)]
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                rng = self.headers.get("Content-Range", "")
                fake.puts.append(rng)
                got = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", rng)
                if got:
                    a = int(got.group(1))
                    if fake.drop_once and not fake.dropped and a > 0:
                        fake.dropped = True
                        return self._send(503, {"error": {"code": 503, "message": "backend error"}})
                    if a != len(s["data"]):
                        return self._send(400, {"error": {"code": 400, "message": f"expected byte {len(s['data'])}, got {a}"}})
                    s["data"] += body
                if len(s["data"]) >= s["total"]:
                    fake.uploads.append({"meta": s["meta"], "data": bytes(s["data"]), "query": s["query"]})
                    priv = "private" if fake.force_private else s["meta"]["status"]["privacyStatus"]
                    return self._send(201, {"id": f"vid{len(fake.uploads)}", "status": {"privacyStatus": priv,
                                                                                         "uploadStatus": "uploaded"}})
                hdr = {"Range": f"bytes=0-{len(s['data']) - 1}"} if s["data"] else {}
                self._send(308, None, hdr)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self


if __name__ == "__main__":
    f = Fake().start(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    print("stand-in Google at", f.base, flush=True)
    threading.Event().wait()
