"""Preferences that follow the creator across machines: a Supabase mirror.

The user's decision of 2026-10-18: what the app learns about a person --
the defaults that follow them (defaults.py), the rules they confirmed
(preferences.py), their profile, and the styles they learnt from reels
(reference.py) -- lives in Supabase, so it is there on the next Mac and,
later, shared where they choose. Footage, the index and exports stay on
the machine; nothing here carries a frame.

How it is done, and why this way:

- **Local first.** Every record is written to its JSON on disk exactly as
  before; this module mirrors it. Offline, nothing changes. A push that
  fails is logged and retried on the next change; it never raises into a
  request and never blocks one (a thread per push).
- **PostgREST over urllib.** Supabase's REST endpoint is enough for upserts
  and reads; no SDK, no new dependency (the repo is numpy + fastapi).
  `Prefer: resolution=merge-duplicates` makes every push an upsert.
- **Identity.** Until there is a sign-in, a `device` id generated once into
  settings.json names the owner. When auth arrives it becomes the user id;
  the tables already key on it.
- **Newest wins.** On start, rows newer than the local copy are applied; a
  local change pushes its own `updated_at`. Clock skew between a laptop
  and the server is tolerated at CLOCK_SLOP seconds.

Config: SUPABASE_URL and SUPABASE_ANON_KEY in the environment or web/.env.
Without them `available()` is False and every call is a no-op. Tables:
supabase/migrations/0001_preferences.sql.
"""

from __future__ import annotations

import calendar
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .indexer import CACHE

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
SETTINGS = CACHE / "settings.json"
KINDS = ("default", "rule", "profile", "vibe", "resource")
CLOCK_SLOP = 5.0
TIMEOUT_S = 8.0
_lock = threading.Lock()
LOG: list[dict] = []       # the last few pushes and what became of them (for the capability line)
_pending: dict[tuple[str, str], dict] = {}   # (kind, key) -> row, retried on the next push


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        k, _, v = line.strip().partition("=")
        if k and v and not k.startswith("#") and k.strip().startswith("SUPABASE_"):
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()


def config() -> tuple[str, str] | None:
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_ANON_KEY", "")
    return (url, key) if url and key else None


def available() -> bool:
    return config() is not None


def device() -> str:
    """This machine's id, made once. The owner of every row until sign-in."""
    with _lock:
        try:
            data = json.loads(SETTINGS.read_text())
        except (OSError, ValueError):
            data = {}
        if not data.get("device"):
            data["device"] = uuid.uuid4().hex
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(SETTINGS)
        return data["device"]


def _request(method: str, table: str, query: str = "", body=None, prefer: str | None = None) -> list[dict]:
    cfg = config()
    if not cfg:
        return []
    url, key = cfg
    req = urllib.request.Request(f"{url}/rest/v1/{table}{('?' + query) if query else ''}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if prefer:
        req.add_header("Prefer", prefer)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        text = r.read().decode() or "[]"
    try:
        out = json.loads(text)
    except ValueError:
        return []
    return out if isinstance(out, list) else [out]


# --------------------------------------------------------------------------
# push: local change -> a row, in the background
# --------------------------------------------------------------------------

def _row(kind: str, key: str, value, at: float | None = None) -> dict:
    return {"device": device(), "kind": kind, "key": key, "value": value,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(at or time.time())) + "Z"}


def push(kind: str, key: str, value, at: float | None = None, wait: bool = False) -> None:
    """Mirror one record. Fire-and-forget unless `wait` (tests)."""
    if kind not in KINDS or not available():
        return
    row = _row(kind, key, value, at)
    with _lock:
        _pending[(kind, key)] = row

    def run() -> None:
        with _lock:
            rows = list(_pending.values())
        try:
            _request("POST", "preferences", body=rows, prefer="resolution=merge-duplicates,return=minimal")
            with _lock:
                for r in rows:
                    _pending.pop((r["kind"], r["key"]), None)
                LOG.append({"at": time.time(), "ok": True, "n": len(rows)})
        except (urllib.error.URLError, OSError, ValueError) as e:
            with _lock:
                LOG.append({"at": time.time(), "ok": False, "why": str(e)[:120]})
        with _lock:
            del LOG[:-20]

    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()


def push_rules(rules: list[dict]) -> None:
    for r in rules:
        if r.get("id"):
            push("rule", str(r["id"]), r, r.get("updated") or r.get("created"))


# --------------------------------------------------------------------------
# pull: rows newer than what's here
# --------------------------------------------------------------------------

def _parse_at(s: str) -> float:
    """An ISO UTC stamp -> epoch seconds. calendar.timegm, not mktime: the
    latter reads the struct as local time and is an hour off under DST."""
    try:
        return float(calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError):
        return 0.0


def pull(kind: str | None = None) -> list[dict]:
    """Every row this device owns (one kind, or all). [] offline."""
    if not available():
        return []
    q = f"device=eq.{urllib.parse.quote(device())}" + (f"&kind=eq.{kind}" if kind else "")
    try:
        rows = _request("GET", "preferences", q)
    except (urllib.error.URLError, OSError, ValueError) as e:
        with _lock:
            LOG.append({"at": time.time(), "ok": False, "why": str(e)[:120]})
        return []
    for r in rows:
        r["at"] = _parse_at(r.get("updated_at", ""))
    return rows


def newer(rows: list[dict], local_at: float) -> list[dict]:
    """The rows worth applying: later than the local copy, clock slop allowed."""
    return [r for r in rows if r.get("at", 0) > local_at + CLOCK_SLOP]


def status() -> dict:
    last = LOG[-1] if LOG else None
    return {"on": available(), "device": device() if available() else None,
            "last": last, "pending": len(_pending)}
