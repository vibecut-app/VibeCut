"""The music folder and track suggestions for the working storyboard.

Thin glue: the matching lives in cutgrammar.music. This keeps the folder
setting (a small JSON file in the cache dir), extracts features in the
background with progress, and turns the storyboard into Sections -- each
beat's shot lengths plus each shot's motion from the index.
"""

from __future__ import annotations

import json
import os
import threading

from cutgrammar import music, openverse, songpack

from . import board as bd
from .indexer import CACHE

SETTINGS = CACHE / "settings.json"

# The track the edit is using (chosen by the user from the suggestions).
CURRENT: dict = {"track_id": None}

STATE = {"folder": None, "status": "none", "done": 0, "total": 0,
         "tracks": [], "errors": [], "error": None}
_lock = threading.Lock()


def _save(folder: str | None) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        data = {}
    data["music_folder"] = folder
    SETTINGS.write_text(json.dumps(data))


def load_setting() -> str | None:
    try:
        return json.loads(SETTINGS.read_text()).get("music_folder")
    except (OSError, ValueError):
        return None


def set_folder(folder: str | None) -> dict:
    folder = os.path.expanduser(folder.strip()) if folder else None
    if folder and not os.path.isdir(folder):
        raise ValueError(f"not a folder: {folder}")
    _save(folder)
    with _lock:
        STATE.update(folder=folder, status="indexing" if folder else "none", done=0, total=0,
                     tracks=[], errors=[], error=None)
    if folder:
        threading.Thread(target=_index, args=(folder,), daemon=True).start()
    return public()


def _index(folder: str) -> None:
    def progress(done: int, total: int) -> None:
        if STATE["folder"] == folder:
            STATE.update(done=done, total=total)
    try:
        src = music.LocalFolderSource(folder, progress=progress)
        tracks = src.list()
        if STATE["folder"] == folder:
            STATE.update(tracks=tracks, errors=src.errors, status="ready")
    except Exception as e:  # noqa: BLE001
        if STATE["folder"] == folder:
            STATE.update(status="error", error=str(e)[:300])


def public() -> dict:
    return {k: STATE[k] for k in ("folder", "status", "done", "total", "error")} | {
        "tracks": len(STATE["tracks"]), "unreadable": len(STATE["errors"])}


def sections(board: dict, cat: bd.Catalog) -> list[music.Section]:
    out = []
    for b in board["beats"]:
        durs = [s["end"] - s["start"] for s in b["shots"]]
        motion = [cat.shots[s["id"]].activity if s.get("id") in cat.shots else 0.0 for s in b["shots"]]
        out.append(music.Section(b["title"], durs, motion))
    return out


def suggest(board: dict | None, cat: bd.Catalog) -> dict:
    out = public()
    if board is None or STATE["status"] != "ready":
        return out
    r = music.match(sections(board, cat), STATE["tracks"])
    out.update({k: r[k] for k in ("edit_seconds", "too_short", "flat")})
    out["suggestions"] = [{
        "id": s.track.id, "title": s.track.title, "duration": round(s.track.duration, 1),
        "bpm": s.track.bpm, "score": s.score, "reason": s.reason,
        "audio": f"/api/music/audio/{s.track.id}",
    } for s in r["suggestions"]]
    return out


def current() -> music.Track | None:
    return find(CURRENT["track_id"])


def use(track_id: str | None) -> None:
    if track_id is not None and find(track_id) is None:
        raise ValueError("no such track in the music folder")
    CURRENT["track_id"] = track_id


# Ids looked for in the music cache and not there, so a session poll doesn't
# walk the folders again for a file that's gone.
_MISSING: set[str] = set()


def find(track_id: str | None) -> music.Track | None:
    """A track by id: the music folder's, or one the bed or a Remix fetched
    in an earlier run. Those were only kept in memory, so after a restart the
    board's set_music named a track nothing could find and the edit lost its
    song, though the file was still in the cache."""
    if track_id is None:
        return None
    t = next((t for t in STATE["tracks"] if t.id == track_id), None)
    if t is not None or track_id in _MISSING:
        return t
    t = _cached(track_id)
    if t is None:
        _MISSING.add(track_id)
    else:
        STATE["tracks"].append(t)
    return t


def _cached(track_id: str) -> music.Track | None:
    """The track in VibeCut's own music cache (Openverse downloads, the
    backup songs) whose id is `track_id`, dressed as when it was picked."""
    pack = songpack.cache_dir()
    folders = [(openverse.cache_dir() / "tracks", openverse.dress)]
    folders += [(d, songpack.dress) for d in sorted(pack.iterdir()) if d.is_dir()] if pack.is_dir() else []
    from web.backend import trend
    folders.append((trend.cache_dir(), trend.dress))      # trending sounds read as guides (trend.py)
    for folder, dress in folders:
        src = music.LocalFolderSource(str(folder))
        for f in src.files() if folder.is_dir() else []:
            if music.track_id(str(f)) == track_id:
                try:
                    return dress(src.one(f))
                except Exception:  # noqa: BLE001 -- an unreadable file is a missing one
                    return None
    return None


def current_public() -> dict | None:
    t = current()
    return None if t is None else {"id": t.id, "title": t.title, "duration": round(t.duration, 2),
                                   "bpm": t.bpm, "audio": f"/api/music/audio/{t.id}"}


def path_for(track_id: str) -> str | None:
    t = find(track_id)
    return t.path if t else None
