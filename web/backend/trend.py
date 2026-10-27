"""Cut to a trending sound: the edit on its beat, the sound added in the app.

Why this exists (2026-10-24, the user: "the recently hot, trendy audios").
The sounds trending on TikTok and Reels can't go into a file VibeCut
exports: they live in each platform's own library, licensed for use inside
that app (design/research/01 §5: TikTok's Commercial Music Library and
Instagram's are in-app only; a business account may use only the cleared
slice). What *can* be done is what research/01 recommended: cut the video
to the sound, export it without music, and let the creator add the same
sound in the app when posting -- the cuts then land on its beat.

So a trending sound here is a **guide**, never a bed:

- the creator pastes the sound's link (a TikTok / Reel / Short using it,
  through yt-dlp, as Borrow a feeling reads a reference) or picks a saved
  file; only its first LIMIT_S seconds of sound are kept, in the cache;
- it is measured like any track (tempo, beat phase, energy, the drop);
- the edit is fitted to it (app.api_music_trend: the same swap as a
  suggested song) with `guide: true` on the board's music, so preview plays
  it on this Mac to cut by ear, and **export.create drops it**: the file
  goes out with the video's own sound and the transition sounds off, and
  the export says which sound to add and from which second.

Nothing is posted, uploaded or shared from here. Trending charts aren't
read either (research/04: no scraping; the TikTok Research API is closed to
commercial users) -- the creator brings the sound they want.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cutgrammar import music as mu

LIMIT_S = 90             # a trending sound is a clip of a song; this covers any short [prior]
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def cache_dir() -> Path:
    root = Path(os.environ.get("VIBECUT_CACHE", str(Path.home() / ".cache" / "vibecut")))
    return root / "music" / "trend"


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip()))


def ytdlp() -> str | None:
    return shutil.which("yt-dlp")


def _sid(source: str) -> str:
    return "trend-" + hashlib.sha1(source.strip().encode()).hexdigest()[:12]


@dataclass
class Job:
    id: str
    source: str
    sid: str
    stage: str = "fetching"       # fetching | reading | done | error
    error: str | None = None
    track: mu.Track | None = None
    started: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "stage": self.stage, "error": self.error,
                "title": self.track.title if self.track else None,
                "bpm": round(float(self.track.bpm)) if self.track and self.track.bpm else None,
                "elapsed": round(time.time() - self.started, 1)}


JOBS: dict[str, Job] = {}


def dress(t: mu.Track) -> mu.Track:
    """A measured sound as a guide: its title from the sidecar, `guide` set."""
    try:
        rec = json.loads(Path(t.path).with_suffix(".json").read_text())
    except (OSError, ValueError):
        rec = {}
    t.meta = {**t.meta, "guide": True, "source": rec.get("url"), "uploader": rec.get("uploader")}
    t.title = rec.get("title") or t.title
    return t


def start(source: str, on_done=None) -> Job:
    """Read a trending sound in the background. A link needs yt-dlp; a file
    may be a video (its sound is taken) or an audio file."""
    source = source.strip()
    if is_url(source):
        if not ytdlp():
            raise ValueError("Links need yt-dlp (brew install yt-dlp). Or save the sound and pick the file.")
    else:
        source = os.path.expanduser(source)
        if not os.path.isfile(source):
            raise ValueError(f"can't find {source}")
        if Path(source).suffix.lower() not in AUDIO_EXT | VIDEO_EXT:
            raise ValueError("that isn't a sound or a video file")
    job = Job(id=uuid.uuid4().hex[:10], source=source, sid=_sid(source))
    JOBS[job.id] = job

    def run() -> None:
        try:
            d = cache_dir()
            d.mkdir(parents=True, exist_ok=True)
            wav = d / f"{job.sid}.wav"
            info: dict = {}
            if not wav.exists():
                src = source
                tmp = d / f"{job.sid}.download"
                if is_url(source):
                    job.stage = "fetching"
                    tmp.mkdir(exist_ok=True)
                    cmd = [ytdlp() or "yt-dlp", "--no-playlist", "--no-part", "--restrict-filenames",
                           "-f", "ba/b", "--write-info-json", "--download-sections", f"*0-{LIMIT_S}",
                           "-o", str(tmp / "sound.%(ext)s"), "--", source]
                    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    if p.returncode != 0:
                        err = next((x for x in reversed((p.stderr or p.stdout).splitlines()) if "ERROR" in x), "download failed")
                        raise RuntimeError(err.replace("ERROR: ", "")[:240])
                    got = [f for f in tmp.iterdir() if f.name.startswith("sound.") and f.suffix != ".json"]
                    if not got:
                        raise RuntimeError("the link gave no sound")
                    src = str(got[0])
                    try:
                        meta = json.loads((tmp / "sound.info.json").read_text())
                    except (OSError, ValueError):
                        meta = {}
                    track = meta.get("track") or meta.get("title")
                    artist = meta.get("artist") or meta.get("uploader") or meta.get("channel")
                    info = {"title": f"{artist} — {track}" if artist and track and artist not in track else track,
                            "uploader": meta.get("uploader"), "url": meta.get("webpage_url") or source}
                else:
                    info = {"title": Path(source).stem, "url": None}
                job.stage = "reading"
                p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-t", str(LIMIT_S), "-vn", "-ac", "2",
                                    "-ar", "44100", str(wav)], capture_output=True, text=True, timeout=300)
                shutil.rmtree(tmp, ignore_errors=True)
                if p.returncode != 0 or not wav.exists():
                    raise RuntimeError("that file has no sound to read")
                wav.with_suffix(".json").write_text(json.dumps(info))
            job.stage = "reading"
            folder = mu.LocalFolderSource(str(cache_dir()))
            t = dress(folder.one(wav))
            if not t.bpm or (t.meta.get("tempo") or {}).get("phase") is None:
                raise RuntimeError("that sound has no steady beat to cut to")
            job.track = t
            job.stage = "done"
        except Exception as e:  # noqa: BLE001 -- said in the panel; nothing changed
            job.stage, job.error = "error", str(e)[:300]
        finally:
            if on_done:
                on_done(job)

    threading.Thread(target=run, daemon=True).start()
    return job


def find(track_id: str) -> mu.Track | None:
    """A guide read before (after a restart), by id."""
    d = cache_dir()
    if not d.is_dir():
        return None
    src = mu.LocalFolderSource(str(d))
    for f in src.files():
        if mu.track_id(str(f)) == track_id:
            try:
                return dress(src.one(f))
            except Exception:  # noqa: BLE001
                return None
    return None


def note(title: str, start_s: float) -> str:
    """What the export says about a guide."""
    m, s = divmod(int(round(start_s)), 60)
    return (f"Exported without music: add “{title}” in TikTok or Instagram when you post, starting at "
            f"{m}:{s:02d} of the sound. The cuts are on its beat; it isn't in this file because trending "
            f"sounds are licensed for use inside those apps.")
