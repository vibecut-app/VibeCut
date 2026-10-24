"""Index a shoot: every clip decoded once, every shot scored and thumbnailed.

Runs cutgrammar in a process pool (one clip per worker), then the on-device
Vision pass over the thumbnails in one batch. Results are cached per file
(path + size + mtime), so dropping the same folder twice is instant.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cutgrammar import bestframe, features, media, shots, signals

from . import ink, sound, vision

CACHE = Path(os.environ.get("VIBECUT_CACHE", "~/.cache/vibecut")).expanduser()
VIDEO_EXT = {".mp4", ".mov"}
INDEX_VERSION = 4  # 3: per-second signals + sampled frames for reject/trim; 4: HDR thumbnails tone-mapped
WORKERS = max(2, min(6, (os.cpu_count() or 4) - 2))


def clip_id(path: str) -> str:
    st = os.stat(path)
    key = f"{os.path.realpath(path)}|{st.st_size}|{st.st_mtime_ns}|{INDEX_VERSION}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def clip_dir(cid: str) -> Path:
    return CACHE / "clips" / cid


def find_videos(folder: str) -> list[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.startswith(".") and Path(f).suffix.lower() in VIDEO_EXT:
                out.append(os.path.join(root, f))
    return sorted(out)


def index_clip(path: str) -> dict:
    """Worker: one file -> index.json + one thumbnail per shot."""
    cid = clip_id(path)
    d = clip_dir(cid)
    done = d / "index.json"
    if done.exists():
        return json.loads(done.read_text())
    d.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    m = media.load_index(path, audio=True)
    sh = shots.detect(m)
    bfs = bestframe.best_frames(m, sh)
    thumbs = [f"shot{s.index:03d}.jpg" for s in sh]
    # What a person looks at is shown the way the phone showed it (HDR ->
    # SDR); everything measured below still reads the frames as decoded.
    shown = media.to_sdr(m.preview, m.meta)
    bestframe.write_jpegs([shown[b.frame] for b in bfs], [str(d / t) for t in thumbs])

    # How much the picture changes second to second: a walking shot vs a
    # locked-off one. Keyframe-rate, so a coarse measure of energy only.
    y = m.frames.astype(np.float32).mean(axis=3)

    # Colour signature of each thumbnail: the subject axis falls back to
    # this when the on-device Vision pass is unavailable.
    def hist(frame: np.ndarray) -> list[float]:
        q = frame.astype(np.int32) * 4 // 256
        h = np.bincount((q[..., 0] * 16 + q[..., 1] * 4 + q[..., 2]).ravel(), minlength=64)
        return [round(float(x), 4) for x in h / h.sum()]
    diffs = np.abs(np.diff(y, axis=0)).mean(axis=(1, 2)) if len(y) > 1 else np.zeros(1)

    # Per-second signals for reject/trim, from this same decode, and the
    # sampled frames themselves so Vision can look for faces in each second.
    sig = signals.from_media(m)
    (d / "samples").mkdir(exist_ok=True)
    sample_names = [f"samples/{i:04d}.jpg" for i in range(len(m.preview))]
    bestframe.write_jpegs(list(shown), [str(d / n) for n in sample_names], quality=6)
    # What words on screen will sit on, as the viewer sees it (ink.py).
    ink.write(d, shown)

    rec = {
        "signals": sig.to_json(),
        "samples": {"times": [round(float(t), 3) for t in m.times], "files": sample_names},
        "marks": marks(m, diffs),
        "id": cid,
        "path": path,
        "name": os.path.basename(path),
        "duration": m.duration,
        "width": m.width,
        "height": m.height,
        "codec": m.meta.get("codec"),
        "capture_time": m.capture_time,
        "gps": list(m.gps) if m.gps else None,
        "sampling": m.meta.get("sampling"),
        "index_seconds": round(time.time() - t0, 2),
        "shots": [
            {
                "index": s.index,
                "start": round(s.start_t, 3),
                "end": round(s.end_t, 3),
                "thumb": thumbs[i],
                "best_t": round(b.t, 3),
                "quality": round(b.quality, 3),
                "parts": {k: round(v, 3) for k, v in b.parts.items()},
                "hist": hist(m.frames[b.frame]),
                "activity": round(float(diffs[max(0, s.start_frame - 1):max(1, s.end_frame - 1)].mean()), 2),
            }
            for i, (s, b) in enumerate(zip(sh, bfs))
        ],
    }
    done.write_text(json.dumps(rec))
    return rec


MIN_RUN_S = 0.4  # a pause or a burst shorter than this isn't an edit point


def marks(m, diffs: np.ndarray) -> list[dict]:
    """Moments inside a clip an editor cuts on, in source seconds.

    - Silence edges, from features.speech_mask at 10 ms: where talk or
      sound stops and where it comes back. Precise.
    - Motion onsets/offsets, from the frame-difference signal. Only as
      precise as the index's sampling (keyframes, ~1 s on iPhone), so each
      carries `approx`: half the gap between the samples it sits between.
    """
    out: list[dict] = []
    if m.has_audio:
        mask = features.speech_mask(m, 0.01)
        if mask.size:
            hop, min_run = 0.01, int(MIN_RUN_S / 0.01)
            # debounce: fold runs shorter than min_run into their neighbours
            edges = np.flatnonzero(np.diff(mask.astype(np.int8))) + 1
            bounds = [0, *edges.tolist(), len(mask)]
            runs = [(bounds[i], bounds[i + 1], bool(mask[bounds[i]])) for i in range(len(bounds) - 1)]
            merged: list[list] = []
            for a, b, v in runs:
                if merged and (b - a < min_run or merged[-1][2] == v):
                    merged[-1][1] = b
                else:
                    merged.append([a, b, v])
            for (a, _, v) in merged[1:]:
                out.append({"t": round(a * hop, 3), "kind": "sound" if v else "quiet", "approx": 0.0})

    if len(diffs) >= 3 and m.times is not None:
        med = float(np.median(diffs))
        mad = float(np.median(np.abs(diffs - med))) * 1.4826 + 1e-6
        hi, lo = med + 2.0 * mad, med + 0.5 * mad
        moving = diffs[0] > hi
        for i, d in enumerate(diffs):
            if (not moving and d > hi) or (moving and d < lo):
                moving = not moving
                a, b = float(m.times[i]), float(m.times[min(i + 1, len(m.times) - 1)])
                out.append({"t": round((a + b) / 2, 3), "kind": "motion_on" if moving else "motion_off",
                            "approx": round((b - a) / 2, 3)})
    return sorted(out, key=lambda x: x["t"])


def add_vision(recs: list[dict]) -> str:
    """Attach labels / faces / aesthetics / embedding to every shot.

    Returns which backend produced them ("vision" or "fallback").
    """
    todo = []
    for r in recs:
        vpath = clip_dir(r["id"]) / "vision.json"
        if vpath.exists():
            r["_vision"] = json.loads(vpath.read_text())
        else:
            todo.append(r)
    backend = "vision"
    if todo:
        imgs = [str(clip_dir(r["id"]) / s["thumb"]) for r in todo for s in r["shots"]]
        results, backend = vision.analyse(imgs)
        by_path = {res["path"]: res for res in results}
        for r in todo:
            per_shot = [by_path.get(str(clip_dir(r["id"]) / s["thumb"]), {}) for s in r["shots"]]
            v = {"backend": backend, "shots": per_shot}
            (clip_dir(r["id"]) / "vision.json").write_text(json.dumps(v))
            r["_vision"] = v
    # Faces on every sampled second (cached per clip): who is in frame, when.
    need = [r for r in recs if not (clip_dir(r["id"]) / "faces.json").exists()]
    need += stale_faces([r for r in recs if r not in need])
    if need:
        paths = [str(clip_dir(r["id"]) / f) for r in need for f in r["samples"]["files"]]
        found = vision.faces(paths)
        for r in need:
            boxes = [found.get(str(clip_dir(r["id"]) / f), []) for f in r["samples"]["files"]]
            track = vision.face_track(boxes, r["samples"]["times"], len(r["signals"]["quality"])) if found else []
            (clip_dir(r["id"]) / "faces.json").write_text(json.dumps(track))
            if found:   # where they are, for aiming a crop (aim.py)
                (clip_dir(r["id"]) / "faceboxes.json").write_text(json.dumps(boxes))
    for r in recs:
        r["faces"] = json.loads((clip_dir(r["id"]) / "faces.json").read_text())

    for r in recs:
        _attach_vision(r, r.pop("_vision"))
    return backend if todo else "cached"


def stale_faces(recs: list[dict]) -> list[dict]:
    """Clips whose faces.json predates face direction and head count (two
    columns a row), when Vision is here to read them again. Elsewhere the
    old rows stay: they still say who is in frame, just not which way."""
    old = []
    for r in recs:
        try:
            track = json.loads((clip_dir(r["id"]) / "faces.json").read_text())
        except (OSError, ValueError):
            continue
        if track and len(track[0]) < vision.TRACK_COLS:
            old.append(r)
    return old if old and vision.ensure_built() else []


def refresh_faces(recs: list[dict]) -> int:
    """Faces read again for clips indexed before face direction existed:
    once, on project open (like sound.add_sound). Returns how many."""
    need = [r for r in stale_faces(recs) if r.get("samples")]
    if not need:
        return 0
    paths = [str(clip_dir(r["id"]) / f) for r in need for f in r["samples"]["files"]]
    found = vision.faces(paths)
    if not found:
        return 0
    for r in need:
        boxes = [found.get(str(clip_dir(r["id"]) / f), []) for f in r["samples"]["files"]]
        r["faces"] = vision.face_track(boxes, r["samples"]["times"], len(r["signals"]["quality"]))
        (clip_dir(r["id"]) / "faces.json").write_text(json.dumps(r["faces"]))
        (clip_dir(r["id"]) / "faceboxes.json").write_text(json.dumps(boxes))
    return len(need)


def _attach_vision(rec: dict, v: dict) -> None:
    for s, res in zip(rec["shots"], v.get("shots", [])):
        s["labels"] = res.get("labels", [])
        s["faces"] = res.get("faces", 0)
        s["face_area"] = res.get("faceArea", 0.0)
        s["aesthetic"] = res.get("aesthetic")
        s["utility"] = res.get("utility")
        s["embedding"] = res.get("embedding", [])


def load_indexed(cid: str) -> dict | None:
    """A clip as `start()` would hand it back, from the cache alone -- what
    a reopened project reads instead of decoding anything again. None when
    the index is missing (cache cleared) or older than this code writes."""
    d = clip_dir(cid)
    try:
        rec = json.loads((d / "index.json").read_text())
        if rec.get("id") != cid or "signals" not in rec or "samples" not in rec:
            return None
        v = json.loads((d / "vision.json").read_text()) if (d / "vision.json").exists() else {"shots": []}
        _attach_vision(rec, v)
        rec["faces"] = json.loads((d / "faces.json").read_text()) if (d / "faces.json").exists() else []
        sound.attach(rec)
    except (OSError, ValueError):
        return None
    return rec


@dataclass
class Job:
    id: str
    paths: list[str]
    stage: str = "queued"          # indexing -> looking -> done | error
    done: int = 0
    started: float = field(default_factory=time.time)
    finished: float | None = None
    errors: list[dict] = field(default_factory=list)
    clips: list[dict] = field(default_factory=list)
    vision: str | None = None
    known: int = 0                 # already on the shelf, not re-indexed

    def public(self) -> dict:
        return {
            "id": self.id, "stage": self.stage, "done": self.done,
            "total": len(self.paths), "known": self.known, "errors": self.errors, "vision": self.vision,
            "elapsed": round((self.finished or time.time()) - self.started, 1),
        }


JOBS: dict[str, Job] = {}
_pool: ProcessPoolExecutor | None = None


def pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        # Spawned, not forked: the server already runs threads (uvicorn, the
        # Vision build, import jobs), and a forked worker can inherit a held
        # lock and never finish -- a job stuck at "7 of 8" forever.
        _pool = ProcessPoolExecutor(max_workers=WORKERS, mp_context=multiprocessing.get_context("spawn"))
    return _pool


def start(paths: list[str], on_done, known: int = 0) -> Job:
    job = Job(id=uuid.uuid4().hex[:8], paths=paths, known=known)
    JOBS[job.id] = job

    def run() -> None:
        try:
            job.stage = "indexing"
            futs = {pool().submit(index_clip, p): p for p in paths}
            for f in as_completed(futs):
                try:
                    job.clips.append(f.result())
                except Exception as e:  # noqa: BLE001
                    job.errors.append({"path": futs[f], "error": str(e)[:300]})
                job.done += 1
            job.stage = "looking"
            job.vision = add_vision(job.clips)
            sound.add_sound(job.clips)
            on_done(job)
            job.stage = "done"
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.errors.append({"path": None, "error": str(e)[:300]})
            job.stage = "error"
        finally:
            job.finished = time.time()

    threading.Thread(target=run, daemon=True).start()
    return job
