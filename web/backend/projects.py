"""Projects: one shoot, one edit, kept on disk between runs.

A project is small: which files it holds (by index id, so the per-file
cache does the heavy lifting), the turn log the storyboard is replayed
from, where the workflow stands, what the creator overrode at the gate,
the brief, and what has been exported. Nothing else needs saving, because
everything the UI shows is recomputed from these by the same code that
computes it live. The original media is never copied or written.

Files: $VIBECUT_CACHE/projects/<id>.json, plus projects.json for the
"which one is open" setting.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import board as bd
from . import indexer, recent
from .workflow import Workflow

DIR = indexer.CACHE / "projects"
SETTINGS = indexer.CACHE / "projects.json"
FORMAT = 1
_lock = threading.Lock()


class ProjectError(Exception):
    pass


@dataclass
class Project:
    id: str
    name: str
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    # index ids -> original paths (the cache holds the rest)
    clips: dict[str, str] = field(default_factory=dict)
    turns: list[dict] = field(default_factory=list)
    next_turn: int = 1
    workflow: dict = field(default_factory=lambda: Workflow().__dict__.copy())
    cut_overrides: dict[str, str] = field(default_factory=dict)
    cut_targets: dict[str, float] = field(default_factory=dict)
    cut_windows: dict[str, list[float]] = field(default_factory=dict)
    # the one-line description and the style answers, kept until the story is built
    brief: dict | None = None
    exports: list[dict] = field(default_factory=list)
    # files the last import couldn't read, so the footage screen can offer a retry
    import_errors: list[dict] = field(default_factory=list)
    # what edits taught about this video only (preferences.py); long-term rules live in the cache
    prefs: dict = field(default_factory=lambda: {"project": [], "decisions": {}})
    # what the dashboard shows for a project that isn't open: taken at save time
    snapshot: dict = field(default_factory=dict)
    # named by VibeCut from its clips (auto_name) until the creator renames it
    auto_name: bool = False
    # what happened to this video that isn't a turn (launchlog.py): the bed's
    # pick landing or not, an export's verdict -- {"kind", "at", ...}
    events: list[dict] = field(default_factory=list)
    format: int = FORMAT

    # ---- what the UI lists -------------------------------------------------
    def summary(self, clips: dict[str, dict] | None = None, board: dict | None = None) -> dict:
        """One row on the dashboard. `clips` and `board` are passed for the
        open project (live); a closed one reads its saved snapshot."""
        live = clips is not None
        snap = self.snapshot if not live else snapshot_of(clips or {}, board)
        n_clips = len(clips) if live else len(self.clips)
        edited = sum(1 for t in self.turns if not t.get("undone") and t.get("ops"))
        return {
            "id": self.id, "name": self.name, "created": self.created, "updated": self.updated,
            "clips": n_clips, "duration": snap.get("duration"), "cover": snap.get("cover"),
            # the made video before it's exported: its first shot and its length
            "poster": snap.get("poster"), "seconds": snap.get("seconds"),
            "stage": stage_of(self.workflow.get("state", "intake"), bool(snap.get("board")), bool(self.exports), n_clips,
                              bool(self.brief)),
            "edits": edited, "exports": len(self.exports),
            "board": snap.get("board"),
            "last_export": self.exports[-1] if self.exports else None,
            # the exported video Home shows and shares (recent.py)
            "video": recent.public(self.id, self.exports),
        }


def snapshot_of(clips: dict[str, dict], board: dict | None) -> dict:
    cs = list(clips.values())
    cover = None
    for c in sorted(cs, key=lambda c: (c.get("capture_time") or "", c["name"])):
        if c.get("shots"):
            cover = f"/api/thumbs/{c['id']}/{c['shots'][0]['thumb']}"
            break
    poster = seconds = None
    if board:
        entries = [e for b in board["beats"] for e in b["shots"]]
        seconds = round(sum(bd.seq_dur(e) for e in entries), 1)
        for e in entries:
            if bd.is_gap(e) or not e.get("id"):
                continue
            cid, _, idx = e["id"].partition(":")
            s = next((s for s in (clips.get(cid) or {}).get("shots", []) if str(s.get("index")) == idx), None)
            if s and s.get("thumb"):
                poster = f"/api/thumbs/{cid}/{s['thumb']}"
                break
    return {"duration": round(sum(c.get("duration", 0.0) for c in cs), 1), "cover": cover,
            "board": {"name": board["name"], "parts": len(board["beats"])} if board else None,
            "poster": poster, "seconds": seconds}


def stage_of(state: str, has_board: bool, exported: bool, n_clips: int, has_brief: bool = False) -> str:
    """Where a creator would pick this project up. The stepper's word
    (the same rule as the UI's stage.ts, so the two never disagree)."""
    if n_clips == 0:
        return "footage"
    if state in ("intake", "indexing", "rough-cut"):
        return "footage"
    if state == "cut-review":
        return "cut" if has_brief else "brief"
    if has_board:
        return "exported" if exported else "story"
    return "brief"


# ---- disk ------------------------------------------------------------------

def _path(pid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", pid):
        raise ProjectError(f"bad project id {pid!r}")
    return DIR / f"{pid}.json"


def _settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def _write_settings(data: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, SETTINGS)


def open_id() -> str | None:
    pid = _settings().get("open")
    return pid if pid and _path(pid).exists() else None


def set_open(pid: str | None) -> None:
    with _lock:
        s = _settings()
        s["open"] = pid
        _write_settings(s)


def load(pid: str) -> Project:
    p = _path(pid)
    try:
        data = json.loads(p.read_text())
    except OSError as e:
        raise ProjectError(f"no project {pid}") from e
    except ValueError as e:
        raise ProjectError(f"project {pid} is unreadable: {e}") from e
    if data.get("format", 1) > FORMAT:
        raise ProjectError(f"project {pid} was saved by a newer VibeCut")
    known = {f.name for f in Project.__dataclass_fields__.values()}
    return Project(**{k: v for k, v in data.items() if k in known})


def save(project: Project) -> None:
    """Atomic: a crash mid-write never leaves a half project behind."""
    with _lock:
        project.updated = time.time()
        DIR.mkdir(parents=True, exist_ok=True)
        p = _path(project.id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(project)))
        os.replace(tmp, p)


def create(name: str = "") -> Project:
    """A video starts without asking for a name (sarah, 2026-10-06: naming it
    is one more decision before anything happens). It is called "New video"
    until its clips are read, then named from them (auto_name)."""
    name = (name or "").strip()[:80]
    pr = Project(id=uuid.uuid4().hex[:12], name=name or NEW_NAME, auto_name=not name)
    save(pr)
    return pr


NEW_NAME = "New video"
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def auto_name(clips: list[dict]) -> str:
    """A name a creator would recognise, read from the clips alone: the days
    they were filmed, e.g. "Sep 22" or "Sep 22–24" (sarah, 2026-10-06: just
    the day for now). Dates are the camera's own wall-clock day."""
    days = sorted({str(c.get("capture_time") or "")[:10] for c in clips if len(str(c.get("capture_time") or "")) >= 10})
    days = [d for d in days if d[4:5] == "-" and d[7:8] == "-" and d[5:7].isdigit() and d[8:10].isdigit()]
    when = ""
    if days:
        def md(d: str) -> str:
            return f"{_MONTHS[int(d[5:7]) - 1]} {int(d[8:10])}"
        a, b = days[0], days[-1]
        when = md(a) if a == b else (f"{md(a)}–{int(b[8:10])}" if a[:7] == b[:7] else f"{md(a)} – {md(b)}")
        if a[:4] != b[:4]:
            when = f"{md(a)}, {a[:4]} – {md(b)}, {b[:4]}"
    return when or NEW_NAME


def list_all() -> list[Project]:
    if not DIR.exists():
        return []
    out = []
    for f in DIR.glob("*.json"):
        try:
            out.append(load(f.stem))
        except ProjectError:
            continue
    return sorted(out, key=lambda p: -p.updated)


def delete(pid: str) -> None:
    p = _path(pid)
    with _lock:
        if p.exists():
            p.unlink()
    if open_id() == pid:
        set_open(None)


# ---- turning live state into a record and back -------------------------------

def turn_to_dict(t: bd.Turn) -> dict:
    """Only what replay needs: the diff and lines are recomputed."""
    return {"id": t.id, "kind": t.kind, "text": t.text, "ops": t.ops, "reply": t.reply,
            "question": t.question, "choices": t.choices, "direction": t.direction,
            "undone": t.undone, "at": t.at, "cost": t.cost, **({"sheets": t.sheets} if t.sheets else {})}


def turn_from_dict(d: dict) -> bd.Turn:
    return bd.Turn(id=int(d["id"]), kind=d.get("kind", "direct"), text=d.get("text", ""),
                   ops=list(d.get("ops") or []), reply=d.get("reply", ""), question=d.get("question"),
                   choices=list(d.get("choices") or []), direction=d.get("direction"),
                   undone=bool(d.get("undone")), at=float(d.get("at") or time.time()),
                   cost=d.get("cost"), sheets=list(d.get("sheets") or []))


def capture(project: Project, clips: dict[str, dict], session: bd.Session, workflow: Workflow,
            plan, prefs=None) -> Project:
    """Write the live state into the record (in place) so it can be saved."""
    project.clips = {cid: c["path"] for cid, c in clips.items()}
    project.turns = [turn_to_dict(t) for t in session.turns]
    project.next_turn = session._next
    project.workflow = {"state": workflow.state, "decision": workflow.decision,
                        "revision": workflow.revision, "history": workflow.history[-50:]}
    project.cut_overrides = dict(plan.overrides) if plan else {}
    project.cut_targets = dict(plan.targets) if plan else {}
    project.cut_windows = {k: list(v) for k, v in plan.windows.items()} if plan else {}
    project.snapshot = snapshot_of(clips, session.board)
    if prefs is not None:
        project.prefs = {"project": list(prefs.project),
                         "decisions": {str(k): v for k, v in prefs.decisions.items()}}
    return project


def restore_prefs(project: Project, prefs) -> None:
    prefs.project = list((project.prefs or {}).get("project") or [])
    prefs.decisions = {int(k): v for k, v in ((project.prefs or {}).get("decisions") or {}).items()}


def restore_session(project: Project) -> bd.Session:
    s = bd.Session()
    s.turns = [turn_from_dict(t) for t in project.turns]
    s._next = max([project.next_turn] + [t.id + 1 for t in s.turns])
    return s


def restore_workflow(project: Project) -> Workflow:
    w = project.workflow or {}
    return Workflow(state=w.get("state", "intake"), decision=w.get("decision"),
                    revision=int(w.get("revision", 0)), history=list(w.get("history") or []))


def restore_clips(project: Project) -> tuple[dict[str, dict], list[dict]]:
    """Clips from the per-file cache. A file whose index is gone (cache
    cleared) or whose original moved is reported, not silently dropped."""
    clips: dict[str, dict] = {}
    missing: list[dict] = []
    for cid, path in project.clips.items():
        rec = indexer.load_indexed(cid)
        if rec is None:
            missing.append({"path": path, "error": "its index is gone from the cache — add the file again"})
            continue
        if not os.path.isfile(path):
            missing.append({"path": path, "error": "the original file has moved or been deleted"})
            continue
        clips[cid] = rec
    return clips, missing
