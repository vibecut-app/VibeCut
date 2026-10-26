"""VibeCut local server. Footage never leaves this machine; with a key set,
the storyboard *text* goes to the chat model (see llm.py).

    python -m web.backend            # from the repo root; serves :8765
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from contextlib import asynccontextmanager

import numpy as np

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cutgrammar import grade

from . import board as bd
from . import projects as pj
from . import audiomix, bed, brief, captionmem, cloud, cutnotes, defaults, habits, make, sfx, songs, trend, vibes, vlog, tempo, ink, moment, cut, export, looks, pitch, seams, selfcheck, smooth, sound, subtitles, places, indexer, llm, locate, musiclib, oai, overlays, reference, remix, share, covers, postcopy, speech, story, storyboard, talk, timeline, vision, voiceover, youtube
from .preferences import PreferenceError, Preferences
from .workflow import GATE, Workflow, WorkflowError

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Compiling the Vision helper takes ~30s the first time ever; do it now,
    # not when the first folder lands. Same for spinning up the workers.
    threading.Thread(target=vision.ensure_built, daemon=True).start()
    indexer.pool()
    if musiclib.load_setting() and os.path.isdir(musiclib.load_setting()):
        musiclib.set_folder(musiclib.load_setting())
    # What the mirror knows that this Mac doesn't yet (cloud.py): defaults and
    # rules newer than the local copies. In a thread: start must not wait on the net.
    threading.Thread(target=_cloud_pull, daemon=True).start()
    # The project that was open last time is open again, as it was left.
    last = pj.open_id()
    if last:
        try:
            _open_project(last)
        except pj.ProjectError:
            pj.set_open(None)
    yield


app = FastAPI(title="VibeCut", docs_url="/api/docs", lifespan=lifespan)

# The open project: whatever has been dropped into it, the working
# storyboard's turn log, and the shelf catalogue the ops resolve against.
# Everything here is rebuilt from the project's record (projects.py) and
# the per-file index cache; nothing lives only in memory.
PROJECT: dict = {"p": None}
CLIPS: dict[str, dict] = {}
VISION_USED = {"value": False}
SESSION = bd.Session()
CATALOG = {"cat": bd.Catalog({}, {})}
LOCK = threading.RLock()
# The rough cut (reject + trim) and where the edit stands relative to its gate.
PLAN: dict = {"plan": None}
WORKFLOW = Workflow()
# What the creator's edits have taught -- only what they confirmed.
PREFS = Preferences(indexer.CACHE / "preferences.json")


def _open_project(pid: str) -> pj.Project:
    """Make `pid` the open project: its clips from the cache, its log
    replayed, its gate where it was left."""
    global SESSION, WORKFLOW
    pr = pj.load(pid)
    with LOCK:
        clips, missing = pj.restore_clips(pr)
        # Clips indexed before the voice reading existed get it once, here.
        sound.add_sound(list(clips.values()))
        ink.fill(list(clips.values()))
        # and which way faces look (talking to the lens vs chatting), once
        indexer.refresh_faces(list(clips.values()))
        CLIPS.clear()
        CLIPS.update(clips)
        VISION_USED["value"] = vision.status() == "ready" and any(
            s.get("labels") for c in CLIPS.values() for s in c["shots"])
        SESSION = pj.restore_session(pr)
        WORKFLOW = pj.restore_workflow(pr)
        PREFS.new_project()
        pj.restore_prefs(pr, PREFS)
        old = cut.Plan(overrides=dict(pr.cut_overrides), targets=dict(pr.cut_targets),
                       windows=dict(pr.cut_windows))
        PLAN["plan"] = cut.compute(CLIPS, old) if CLIPS else None
        # A project whose files went missing since it was saved says so on
        # the footage screen; it never pretends they are there.
        if missing:
            pr.import_errors = missing + [e for e in pr.import_errors
                                          if e.get("path") not in {m["path"] for m in missing}]
        if not CLIPS and WORKFLOW.state != "intake":
            WORKFLOW = Workflow()
        PROJECT["p"] = pr
        _refresh_catalog()
        # A story picked before the repeat check existed gets it once, here.
        _drop_repeats(only_once=True)
    pj.set_open(pid)
    return pr


REPEATS_TEXT = "Took out shots that repeat another"


def _drop_repeats(only_once: bool = False) -> None:
    """No shot in the edit repeats another (sarah: never put identical
    shots in): the weaker of each look-alike goes, as one undoable turn.
    Runs when a story is chosen, and once for a story chosen before this
    existed; after that the creator's own edits are never second-guessed."""
    b = SESSION.board
    if not b or not VISION_USED["value"]:
        return
    if only_once:
        last = max((i for i, t in enumerate(SESSION.turns) if not t.undone
                    and any(o.get("op") == "choose_option" for o in t.ops)), default=None)
        if last is None or any(t.text == REPEATS_TEXT for t in SESSION.turns[last + 1:]):
            return
    ops, names = brief.repeat_ops(b, CATALOG["cat"])
    if not ops:
        return
    words = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
    reply = (f"Took out {len(ops)} shot{'s' * (len(ops) != 1)} that repeated another one in the edit "
             f"({words}); the better-made of each stays. Undo puts {'them' if len(ops) != 1 else 'it'} back.")
    SESSION.add({"kind": "direct", "text": REPEATS_TEXT, "ops": ops, "reply": reply},
                CATALOG["cat"], _make_proposals)


def _close_project() -> None:
    global SESSION, WORKFLOW
    with LOCK:
        PROJECT["p"] = None
        CLIPS.clear()
        SESSION = bd.Session()
        WORKFLOW = Workflow()
        PLAN["plan"] = None
        PREFS.new_project()
        _refresh_catalog()
    pj.set_open(None)


def _save() -> None:
    """The open project, as it stands, to disk. Cheap; called after every change."""
    pr = PROJECT["p"]
    if pr is None:
        return
    with LOCK:
        pj.capture(pr, CLIPS, SESSION, WORKFLOW, PLAN["plan"], PREFS)
    pj.save(pr)


def _meta() -> dict | None:
    pr = PROJECT["p"]
    return None if pr is None else pr.summary(CLIPS, SESSION.board)


def _cloud_pull() -> None:
    if not cloud.available():
        return
    rows = cloud.pull()
    local_at = float((defaults._read().get("defaults") or {}).get("at") or 0)
    picks = {r["key"]: r["value"] for r in cloud.newer([r for r in rows if r.get("kind") == "default"], local_at)}
    if picks:
        defaults.note(_sync=False, **picks)
    with LOCK:
        PREFS.absorb([r for r in rows if r.get("kind") == "rule"])
    prof = [r for r in rows if r.get("kind") == "profile" and r.get("key") == "me"]
    if prof:
        _profile_store(prof[-1]["value"], prof[-1].get("at") or 0, sync=False)


def _profile_store(profile: dict, at: float, sync: bool = True) -> dict:
    """The creator's profile, kept beside the defaults so it can be mirrored
    (the browser keeps its own copy in localStorage; this one follows them)."""
    with cloud._lock:
        try:
            data = json.loads(defaults.SETTINGS.read_text())
        except (OSError, ValueError):
            data = {}
        have = data.get("profile") or {}
        # a save by hand always wins; only a copy *from* the mirror defers to a newer local one
        if not sync and have and float(have.get("at") or 0) >= at:
            return have
        data["profile"] = {"at": at, "value": profile}
        defaults.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = defaults.SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(defaults.SETTINGS)
    if sync:
        cloud.push("profile", "me", profile, at)
    return data["profile"]


class ProfileReq(BaseModel):
    profile: dict


@app.get("/api/profile")
def api_profile_get() -> dict:
    try:
        data = json.loads(defaults.SETTINGS.read_text())
    except (OSError, ValueError):
        data = {}
    return {"profile": (data.get("profile") or {}).get("value"), "at": (data.get("profile") or {}).get("at"),
            "cloud": cloud.status()}


@app.post("/api/profile")
def api_profile_put(req: ProfileReq) -> dict:
    rec = _profile_store(req.profile, time.time())
    return {"profile": rec["value"], "at": rec["at"], "cloud": cloud.status()}


def _prefs_public() -> dict:
    out = PREFS.public(SESSION, PROJECT["p"].exports if PROJECT["p"] else None)
    # a habit used three times without an undo is offered once as a rule, in the creator's words
    for h in habits.load():
        if h.get("offered") and not h.get("off") and f"habit:{h['id']}" not in PREFS.suggested:
            out["suggestions"].append({"id": f"habit:{h['id']}", "source": "habit",
                                       "said": f"The app has kept {h['text']} on {h['n']} videos",
                                       "rule": h["text"].capitalize(), "suggested": "long_term"})
    return out


def _capabilities() -> dict:
    """What this machine can do, so the UI says so instead of failing later."""
    return {
        "cloud": cloud.available(),
        "llm": llm.available(),
        # who answers the chat now: "openai" (the course key, AI switch on), "claude", or None
        "chat": llm.chat_provider(),
        "speech": sys.platform == "darwin" and shutil.which("swiftc") is not None,
        "vision": vision.status(),
        "sound": sound.status(),
        "links": reference.ytdlp() is not None,
        "music_folder": musiclib.STATE.get("folder"),
        "youtube": youtube.configured(),
        "platform": sys.platform,
    }


# Mutating calls need an open project (the dashboard has none), and after
# they succeed the project is written to disk. Uploads, the finished-video
# tool and the reference library stand apart: they are not project state.
_NO_PROJECT_OK = ("/api/projects", "/api/upload", "/api/locate", "/api/polish", "/api/music/folder",
                  "/api/references", "/api/profile", "/api/vibes", "/api/youtube")
_NOT_SAVED = ("/api/projects", "/api/upload", "/api/locate", "/api/polish", "/api/music/folder", "/api/profile", "/api/vibes",
              "/api/youtube")


@app.middleware("http")
async def project_scope(request: Request, call_next):
    path = request.url.path
    mutating = request.method in ("POST", "DELETE", "PATCH", "PUT") and path.startswith("/api/")
    if mutating and PROJECT["p"] is None:
        if not path.startswith(_NO_PROJECT_OK) or path.endswith(("/apply", "/look")):
            return JSONResponse({"detail": "Open a project first."}, status_code=409)
    response = await call_next(request)
    if mutating and response.status_code < 400 and not path.startswith(_NOT_SAVED) \
            and "/frames/" not in path:
        _save()
    return response


def _make_proposals(direction: dict) -> dict:
    lean = None if direction.get("keywords") else (direction.get("themes", []), direction.get("labels", []))
    return storyboard.build(list(CLIPS.values()), direction.get("text", ""),
                            vision=VISION_USED["value"], lean=lean, cut=cut.for_story(PLAN["plan"]),
                            voiceover=direction.get("voiceover"), style=direction.get("style"))


def _direction() -> dict | None:
    """The direction the proposals are currently built from."""
    for t in reversed(SESSION.turns):
        if t.direction is not None and not t.undone:
            return t.direction
    return None


def _lean_labels() -> set[str]:
    for t in reversed(SESSION.turns):
        if t.direction is not None and not t.undone:
            return set(t.direction.get("labels", []))
    return set()


def _session() -> dict:
    """Everything the UI renders: the board (enriched for display), the log, proposals."""
    cat = CATALOG["cat"]
    lean = _lean_labels()

    def shot(e: dict) -> dict:
        if bd.is_gap(e):
            return {**e, "key": bd.key(e), "clip_id": None, "thumb": "", "src_start": 0,
                    "src_end": e["end"], "lean": False}
        s = cat.shots.get(e["id"])
        return {**e, "key": bd.key(e), "clip_id": s.clip_id if s else e["id"].split(":")[0],
                "thumb": s.thumb if s else "", "src_start": s.start if s else e["start"],
                "src_end": s.end if s else e["end"],
                "lean": bool(s and lean and any(s.labels.get(l, 0) >= 0.2 for l in lean))}

    b = SESSION.board
    board = None if b is None else {
        **{k: b[k] for k in ("option", "name", "structure")},
        "style": _style(b),
        "beats": [{**bt, "shots": [shot(x) for x in bt["shots"]]} for bt in b["beats"]],
    }
    tl = timeline.build(b, CLIPS, _track())
    tl["frame"] = export.frame_size(tl["items"], CLIPS, _want())
    last = SESSION.last_active()
    ghosts = []
    cuts = seams.check(tl["items"], CLIPS) if b else []
    review: list[dict] = []
    if last and last.diff and not last.diff["replaced"]:
        # What the latest turn removed, so the board can show it struck through.
        prev = _board_before(last)
        # A second look at the turn: did it make any cut rougher (or fix one)?
        review = seams.review(seams.check(timeline.build(prev, CLIPS, _track())["items"], CLIPS) if prev else [], cuts)
        for r in last.diff["beats"]["removed"]:
            old = next((x for x in (prev or {}).get("beats", []) if x["id"] == r["id"]), None)
            idx = [x["id"] for x in (prev or {}).get("beats", [])].index(r["id"]) if old else 0
            ghosts.append({"index": idx, "title": r["title"],
                           "thumbs": [cat.shots[x["id"]].thumb for x in (old or {}).get("shots", [])
                                      if x["id"] in cat.shots]})
    return {
        "board": board,
        "structure_note": _structure_note(b),
        "last": {"turn": last.id, "diff": last.diff, "ghosts": ghosts, "review": review} if last else None,
        "scenes": {e["beat"]: e["word"] for e in (PROJECT["p"].events if PROJECT["p"] else []) if e.get("kind") == "scene_verdict"},
        "seams": cuts,
        "turns": [{
            "id": t.id, "kind": t.kind, "text": t.text, "reply": t.reply, "question": t.question,
            "choices": t.choices, "lines": _with_thumbs(t.lines, cat), "skipped": t.skipped,
            "undone": t.undone, "at": t.at, "has_ops": bool(t.ops) or t.direction is not None, "cost": t.cost,
            "sheets": t.sheets,
            "direction": {k: t.direction[k] for k in ("themes",) if k in t.direction} if t.direction else None,
        } for t in SESSION.turns],
        "proposals": SESSION.proposals,
        "llm": llm.available(),
        "ai_spent": _ai_spent(),
        "timeline": tl,
        "overlays": _overlays_public(b, cat, tl),
        "workflow": WORKFLOW.public(),
        "cut": cut.summary(PLAN["plan"]) if PLAN["plan"] else None,
        "music": _music_public(),
        "bed": BED["job"].public() if BED["job"] else None,
        "mix": _mix_public(b, tl),
        "preferences": _prefs_public(),
        "habits": MAKE.get("last_habits") or [],
        "prefer": _prefer_public(),
        "voiceover": _voiceover_public(),
        "project": _meta(),
        "brief": PROJECT["p"].brief if PROJECT["p"] else None,
        "exports": list(PROJECT["p"].exports) if PROJECT["p"] else [],
        "import_errors": list(PROJECT["p"].import_errors) if PROJECT["p"] else [],
        "capabilities": _capabilities(),
    }


# --------------------------------------------------------------------------
# smoother cuts: asked for, one undoable turn (smooth.py)
# --------------------------------------------------------------------------

class SmoothReq(BaseModel):
    order: bool = True
    nudge: bool = True


@app.post("/api/cutnotes")
def api_cutnotes() -> dict:
    """Check my cut: timestamped notes on the edit as it stands, from the
    checks every turn already runs (cutnotes.py). Free, no model, changes
    nothing; the check is kept on the project (kind `cut_check`) with what
    it found, so later turns can show whether the notes were acted on."""
    with LOCK:
        b = SESSION.board
        if not b:
            raise HTTPException(400, "There's no edit to check yet.")
        tl = timeline.build(b, CLIPS, _track())
        rep = cutnotes.notes(tl["items"], seams.check(tl["items"], CLIPS), overlays.resolve(b),
                             overlays.check(b, CATALOG["cat"]))
        last = SESSION.last_active()
        rep["turn"] = last.id if last else None
        if PROJECT["p"]:
            by: dict[str, int] = {}
            for n in rep["notes"]:
                for k in n["checks"]:
                    by[k] = by.get(k, 0) + 1
            PROJECT["p"].events.append({"kind": "cut_check", "turn": rep["turn"], "notes": len(rep["notes"]),
                                        "checks": by, "at": time.time()})
        return rep


@app.post("/api/smooth")
def api_smooth(req: SmoothReq) -> dict:
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Choose a story first — there are no cuts to smooth yet.")
        ops, said = smooth.propose(SESSION.board, CLIPS, CATALOG["cat"], order=req.order, nudge=req.nudge)
        if not ops:
            raise HTTPException(409, said)
        SESSION.add({"kind": "direct", "text": "Smoother cuts", "ops": ops, "reply": said},
                    CATALOG["cat"], _make_proposals)
        return _session()


# --------------------------------------------------------------------------
# the sound under the edit: the board's own music, and one mixed track
# --------------------------------------------------------------------------

def _track():
    """The track under the edit: the storyboard's (set_music -- undoable,
    replayed), else whatever the music card last put under it."""
    m = (SESSION.board or {}).get("music")
    if m is not None and "track" in m:
        return musiclib.find(m["track"])
    return musiclib.current()


def _story_pixels(b: dict | None):
    """A sample of the story's pixels (its shots' thumbnails at 48×27), for
    fitting a look's grade. Reads JPEGs only; never the original files."""
    if not b:
        return None
    thumbs = reference._board_thumbs(b, CATALOG["cat"])
    if not thumbs:
        return None
    pick = [thumbs[i] for i in np.unique(np.linspace(0, len(thumbs) - 1, min(looks.GRADE_SHOTS, len(thumbs))).astype(int))]
    small = [x for x in (reference._read_jpeg(q, 48, 27) for q in pick) if x is not None]
    return grade.pixels(np.stack(small)) if small else None


def _style(b: dict | None, for_export: bool = False) -> dict | None:
    """The board's rendering style: a borrowed style, with the look filling
    in the joins and (at export, where pixels are touched) the grade.
    Preview and export both come through here so they can't disagree."""
    return looks.picture(b, _story_pixels(b) if for_export else None)


def _music_public() -> dict | None:
    t = _track()
    if t is None:
        return None
    from cutgrammar import openverse as ov
    lic = (t.meta or {}).get("licence")
    m = (SESSION.board or {}).get("music") or {}
    guide = bool(m.get("guide")) and m.get("track") == t.id
    return {"id": t.id, "title": t.title, "duration": round(t.duration, 2),
            "bpm": t.bpm, "audio": f"/api/music/audio/{t.id}",
            # the licence's credit line, for the caption (pasted with it on Save);
            # a trending sound (trend.py) has none: it isn't in the file
            "credit": None if guide else (ov.credit(lic) if lic else None),
            "guide": guide, "start_at": round(float(m.get("in") or 0.0), 2) if guide else None,
            "sfx": len(m.get("sfx") or [])}


# Specs of mixes the UI has been told about, by key; the file is rendered
# on first request, so a session poll never waits for audio.
MIXES: dict[str, dict] = {}


_SESSION_TRACK = object()


def _mix_spec(b: dict | None, items: list[dict], track=_SESSION_TRACK) -> dict | None:
    """`track`: the music under `b`, when it isn't the session's board (a card's version)."""
    if not b or not items:
        return None
    t = _track() if track is _SESSION_TRACK else track
    sp = export.spans(items)
    plan, _ = export.plan_transitions(sp, CLIPS, _style(b))
    music = export.music_spec(t.path if t else None, b.get("music"))
    return audiomix.spec(sp, CLIPS, b.get("joins"), plan, music, audiomix.strips_of(b))


def _keep_mix(sp: dict) -> str:
    """Remember a mix spec so /api/mix can render it; its key."""
    k = audiomix.key_of(sp)
    MIXES[k] = sp
    while len(MIXES) > 64:   # only recent edits can still be asked for
        MIXES.pop(next(iter(MIXES)))
    return k


def _mix_public(b: dict | None, tl: dict) -> dict | None:
    """What the preview plays: the same sound export will write."""
    sp = _mix_spec(b, tl["items"])
    if sp is None:
        return None
    k = _keep_mix(sp)
    joins = audiomix.joins_for(sp["items"], sp["joins"])
    # The picture side of the same plan export renders (plan_transitions):
    # per shot, frames of handle for a dissolve and any dip or flash, so the
    # player can show the join the file will have. Only non-trivial entries.
    trans = [{"key": it["key"], "head": p["head"], "tail": p["tail"], "blend": p.get("blend"),
              "fade_in": list(p["fade_in"]) if p["fade_in"] else None,
              "fade_out": list(p["fade_out"]) if p["fade_out"] else None,
              "swipe": bool(p.get("swipe"))}
             for it, p in zip(sp["items"], sp["transitions"] or [])
             if p["head"] or p["tail"] or p["fade_in"] or p["fade_out"]]
    size = tl.get("frame") or {"w": 1920, "h": 1080}
    bar = export._bar(size, _style(b))
    return {"key": k, "audio": f"/api/mix/{k}.wav", "transitions": trans,
            "bars": round(bar / size["h"], 4) if bar else 0.0,
            # `fits`: False where a carry was asked for but the shot wasn't
            # filmed long enough past the cut -- it plays as a clean break, and says so
            "joins": [{"after": it["key"], "at": sp["items"][i + 1]["seq_start"], **j,
                       "fits": audiomix.fits(sp["items"], CLIPS, i, j["sound"]),
                       **_picture_at(b, sp["transitions"] or [], i, it["key"])}
                      for i, (it, j) in enumerate(zip(sp["items"], joins))]}


def _picture_at(b: dict, plan: list[dict], i: int, k: str) -> dict:
    """What the picture does at the cut after item i (what will play), and
    what the creator picked there, if anything (transitions.py)."""
    p, q = (plan[i] if i < len(plan) else {}), (plan[i + 1] if i + 1 < len(plan) else {})
    if p.get("blend"):
        shown = p["blend"]
    elif p.get("fade_out") and q.get("fade_in"):
        shown = "flash" if p["fade_out"][1] == "white" else "dip_black"
    else:
        shown = "cut"
    one = (b.get("picture_joins") or {}).get(k)
    pick = one or b.get("picture_all") or {}
    return {"picture": shown, "picked": pick.get("kind"), "picked_dur": pick.get("dur"),
            "picked_all": bool(pick) and not one}


@app.get("/api/mix/{name}")
def api_mix(name: str) -> FileResponse:
    k = name.removesuffix(".wav")
    sp = MIXES.get(k)
    if sp is None:
        raise HTTPException(404, "that mix is out of date")
    try:
        path = audiomix.preview_file(sp, dict(CLIPS))
    except (OSError, subprocess.CalledProcessError) as e:
        raise HTTPException(500, f"couldn't mix the sound: {e}") from e
    return FileResponse(path, media_type="audio/wav",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


def _overlays_public(b: dict | None, cat, tl: dict) -> dict:
    """Words on screen as both preview and export draw them: resolved times
    (on the beat, if the look says so), one style with the look's motion."""
    style = overlays.style_of(b)
    items = overlays.resolve(b)
    if (style.get("motion") or {}).get("beat_lock"):
        items = looks.beat_lock(items, tl.get("grid"), tl.get("total", 0.0))
    # each overlay's colour against what's behind it, from the video's own palette
    items = ink.for_board(items, style, timeline.layout(b), CLIPS)
    return {"items": items, "style": style, "findings": overlays.check(b, cat),
            "look": {"id": (b or {}).get("look"), "overrides": looks.overrides(b), "all": looks.public()}}


def _voiceover_public() -> dict | None:
    v = (_direction() or {}).get("voiceover")
    return None if not v else {"source": v["source"], "timing": v["timing"],
                               "lines": len(v["lines"]), "total": v["total"]}


def _board_before(turn: bd.Turn) -> dict | None:
    """Replay up to (not including) `turn` -- cheap, the log is short."""
    sub = bd.Session()
    sub.turns = [t for t in SESSION.turns if t.id < turn.id]
    sub.replay(CATALOG["cat"], _make_proposals)
    return sub.board


def _structure_note(b: dict | None) -> str | None:
    if not b:
        return None
    edits = sum(1 for t in SESSION.turns if not t.undone and t.ops
                and not any(o.get("op") == "choose_option" for o in t.ops))
    return b["structure"] + (f" Edited {edits}×." if edits else "")


def _with_thumbs(lines: list[dict], cat: bd.Catalog) -> list[dict]:
    out = []
    for l in lines:
        l = dict(l)
        if l.get("shot") and l["shot"] in cat.shots:
            l["thumb"] = cat.shots[l["shot"]].thumb
        out.append(l)
    return out


def _refresh_catalog() -> None:
    CATALOG["cat"] = bd.Catalog.from_clips(list(CLIPS.values()))
    SESSION.replay(CATALOG["cat"], _make_proposals)


def _public_clip(c: dict) -> dict:
    return {
        **{k: c[k] for k in ("id", "name", "duration", "width", "height", "capture_time",
                             "gps", "sampling", "index_seconds")},
        "video": f"/api/video/{c['id']}",
        "cut": _cut_of(c["id"]),
        "shots": [{
            "id": f"{c['id']}:{s['index']}", "index": s["index"], "start": s["start"],
            "end": s["end"], "best_t": s["best_t"], "quality": s["quality"],
            "aesthetic": s.get("aesthetic"), "labels": s.get("labels", [])[:4],
            "faces": s.get("faces", 0), "utility": s.get("utility"),
            "thumb": f"/api/thumbs/{c['id']}/{s['thumb']}",
        } for s in c["shots"]],
        # ~1 frame a second, for the rough cut's hover preview before the video seeks
        "samples": {"times": (c.get("samples") or {}).get("times", []),
                    "base": f"/api/samples/{c['id']}/"},
    }


def _cut_of(cid: str) -> dict | None:
    """What the rough cut decided about a clip: shown on the shelf, with its reason."""
    p = PLAN["plan"]
    d = p.clips.get(cid) if p else None
    if not d:
        return None
    return {"rejected": d["rejected"], "auto_rejected": d["auto_rejected"], "zh": d["zh"], "en": d["en"],
            "override": d["override"], "flags": d["flags"],
            "windows": {sid: s["use"] for sid, s in d["shots"].items()}}


def _project() -> dict:
    clips = sorted(CLIPS.values(), key=lambda c: (storyboard.parse_when(c.get("capture_time"))
                                                  or storyboard.datetime.max, c["name"]))
    return {"clips": [_public_clip(c) for c in clips], "vision": vision.status(), "project": _meta()}


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------

class LocateReq(BaseModel):
    files: list[dict]


@app.post("/api/locate")
def api_locate(req: LocateReq) -> dict:
    return locate.resolve(req.files, known=[c["path"] for c in CLIPS.values()])


UPLOADS = indexer.CACHE / "uploads"


@app.post("/api/upload")
async def api_upload(request: Request) -> dict:
    """Raw-body upload of one file the locator couldn't find on disk."""
    rel = unquote(request.headers.get("x-relpath", ""))
    batch = request.headers.get("x-batch", "default")
    name = Path(rel).name
    if Path(name).suffix.lower() not in indexer.VIDEO_EXT:
        raise HTTPException(400, "only .mp4 / .mov")
    d = UPLOADS / "".join(ch for ch in batch if ch.isalnum())[:32]
    d.mkdir(parents=True, exist_ok=True)
    dest = d / uuid.uuid4().hex[:8] / name  # keep the creator's file name
    dest.parent.mkdir()
    with open(dest, "wb") as fh:
        async for chunk in request.stream():
            fh.write(chunk)
    return {"path": str(dest)}


class ImportReq(BaseModel):
    paths: list[str] = []
    folder: str | None = None


@app.post("/api/import")
def api_import(req: ImportReq) -> dict:
    paths = list(req.paths)
    if req.folder:
        if not os.path.isdir(req.folder):
            raise HTTPException(400, f"not a folder: {req.folder}")
        paths += indexer.find_videos(req.folder)
    asked = list(dict.fromkeys(paths))
    paths = [p for p in asked if os.path.isfile(p) and Path(p).suffix.lower() in indexer.VIDEO_EXT]
    pr = PROJECT["p"]
    # A file that isn't there (moved since the project was saved, a bad
    # path) is reported on the footage screen, not dropped on the floor.
    gone = [{"path": p, "error": "no such file" if not os.path.isfile(p) else "only .mp4 / .mov"}
            for p in asked if p not in paths]
    if pr is not None and gone:
        with LOCK:
            pr.import_errors = [e for e in pr.import_errors if e.get("path") not in {g["path"] for g in gone}] + gone
    if not paths:
        raise HTTPException(400, "no .mp4 or .mov files" if not gone else gone[0]["error"] + ": " + Path(gone[0]["path"]).name)
    # Adding to a session: only what isn't on the shelf already gets indexed.
    fresh = [p for p in paths if indexer.clip_id(p) not in CLIPS]

    def done(job: indexer.Job) -> None:
        with LOCK:
            for c in job.clips:
                CLIPS[c["id"]] = c
            VISION_USED["value"] = vision.status() == "ready"
            _refresh_catalog()
            if pr is not None:
                # Files that couldn't be read stay listed (with a retry) until they can.
                tried = {p for p in paths}
                pr.import_errors = [e for e in pr.import_errors if e.get("path") not in tried] + list(job.errors)
            if not job.clips:
                return
            # Stage 1 + 2: reject and trim, then stop at the gate for a person.
            PLAN["plan"] = cut.compute(CLIPS, PLAN["plan"])
            if WORKFLOW.state in ("intake", "indexing"):
                if WORKFLOW.state == "intake":
                    WORKFLOW.advance("indexing", f"{len(job.clips)} clips indexed")
                WORKFLOW.advance("rough-cut", "reject + trim computed")
                WORKFLOW.advance("cut-review", cut.summary(PLAN["plan"])["line_en"])
                # the clips are read: start fetching music for their pace now, so
                # "Make my video" finds tracks waiting rather than hunting (make.py)
                if musiclib.STATE["status"] != "ready" and os.environ.get("VIBECUT_BED", "1") != "0":
                    try:
                        bed.prefetch(tempo.read(list(CLIPS.values()), cut.for_story(PLAN["plan"]))["pace"])
                    except Exception:  # noqa: BLE001 -- a warm-up, nothing more
                        pass
            else:
                WORKFLOW.reopen("system", f"{len(job.clips)} new clip(s) to review")
            SESSION.replay(CATALOG["cat"], _make_proposals)
        if pr is not None and pr.auto_name and job.clips:
            # Named from its clips' days, so a new video needs no name typed in.
            name = pj.auto_name(list(CLIPS.values()))
            with LOCK:
                if pr.auto_name:
                    pr.name = name
        if pr is not None and pr is PROJECT["p"]:
            _save()

    return indexer.start(fresh, done, known=len(paths) - len(fresh)).public()


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = indexer.JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    return job.public()


@app.get("/api/project")
def api_project() -> dict:
    return _project()


@app.delete("/api/project")
def api_clear() -> dict:
    """Start the open project over: its footage, log and gate. The files
    on disk and their index are untouched."""
    global SESSION, WORKFLOW
    with LOCK:
        CLIPS.clear()
        SESSION = bd.Session()
        PREFS.new_project()
        WORKFLOW = Workflow()
        PLAN["plan"] = None
        if PROJECT["p"]:
            PROJECT["p"].brief = None
            PROJECT["p"].import_errors = []
        _refresh_catalog()
    return _project()


# --------------------------------------------------------------------------
# projects: the dashboard's list, and which one is open (projects.py)
# --------------------------------------------------------------------------

class ProjectReq(BaseModel):
    name: str = ""


class BriefReq(BaseModel):
    message: str | None = None
    style: dict | None = None
    said: str = ""


def _summaries() -> list[dict]:
    cur = PROJECT["p"]
    out = []
    for p in pj.list_all():
        if cur is not None and p.id == cur.id:
            out.append(cur.summary(CLIPS, SESSION.board))
        else:
            out.append(p.summary())
    return out


@app.get("/api/projects")
def api_projects() -> dict:
    return {"projects": _summaries(), "open": PROJECT["p"].id if PROJECT["p"] else None,
            "capabilities": _capabilities()}


@app.post("/api/projects")
def api_project_create(req: ProjectReq) -> dict:
    _save()
    pr = pj.create(req.name)
    _open_project(pr.id)
    return {"project": _meta(), "session": _session()}


@app.post("/api/projects/{pid}/open")
def api_project_open(pid: str) -> dict:
    if PROJECT["p"] is not None and PROJECT["p"].id == pid:
        return {"project": _meta(), "session": _session()}
    _save()
    try:
        _open_project(pid)
    except pj.ProjectError as e:
        raise HTTPException(404, str(e)) from e
    return {"project": _meta(), "session": _session()}


@app.post("/api/projects/close")
def api_project_close() -> dict:
    _save()
    _close_project()
    return {"projects": _summaries(), "open": None}


@app.patch("/api/projects/{pid}")
def api_project_rename(pid: str, req: ProjectReq) -> dict:
    name = req.name.strip()[:80]
    if not name:
        raise HTTPException(400, "give it a name")
    cur = PROJECT["p"]
    if cur is not None and cur.id == pid:
        cur.name, cur.auto_name = name, False
        _save()
        return {"project": _meta()}
    try:
        pr = pj.load(pid)
    except pj.ProjectError as e:
        raise HTTPException(404, str(e)) from e
    pr.name, pr.auto_name = name, False
    pj.save(pr)
    return {"project": pr.summary()}


@app.delete("/api/projects/{pid}")
def api_project_delete(pid: str) -> dict:
    """Removes the project record only -- never a clip, never an export."""
    if PROJECT["p"] is not None and PROJECT["p"].id == pid:
        _close_project()
    try:
        pj.delete(pid)
    except pj.ProjectError as e:
        raise HTTPException(404, str(e)) from e
    return {"projects": _summaries(), "open": PROJECT["p"].id if PROJECT["p"] else None}


@app.post("/api/project/brief")
def api_project_brief(req: BriefReq) -> dict:
    """The one-line description and style answers, kept on the project
    until the story is built (and after, as a record of what was asked)."""
    pr = PROJECT["p"]
    if pr is None:
        raise HTTPException(409, "Open a project first.")
    if req.message is None or not req.message.strip():
        pr.brief = None
    else:
        pr.brief = {"message": req.message.strip(), "style": brief.clean_style(req.style) or {},
                    "said": req.said, "at": time.time()}
        if pr.brief["style"].get("captions") == "transcribe":
            # Transcribing takes a while; start now so the subtitles are
            # ready when a story is chosen. On this Mac, free, cached.
            subtitles.prefetch(list(CLIPS.values()), req.message)
    return _session()


# --------------------------------------------------------------------------
# storyboards
# --------------------------------------------------------------------------

class ChatReq(BaseModel):
    message: str
    # Answers to the style questions (brief.py), sent with the first description.
    style: dict | None = None
    # The cost the chat box showed for this message (/api/chat/estimate). On
    # the course key only a message sent with its cost shown is answered.
    ai_ok: float | None = None
    # The moment it's about (edit seconds: a clicked shot or the paused
    # frame), or None for the whole video.
    t: float | None = None
    # The box's id for this message, so Stop can find it.
    rid: str | None = None


def _chat_gate(ai_ok: float | None) -> str | None:
    """Who answers this message, or a refusal. On OpenAI's course key ($25
    for the whole team) a message goes only when the box showed its cost."""
    who = llm.chat_provider()
    if who == "openai" and ai_ok is None:
        raise HTTPException(409, "Send it from the chat box, which shows what a message costs before it goes.")
    return who


def _chat_spent(out: dict, where: str) -> float | None:
    """Keep what an answer cost with the project; -> dollars."""
    u = out.get("usage") or {}
    if "cost" not in u:
        return None
    if PROJECT["p"] is not None:
        PROJECT["p"].events.append({"kind": "chat", "at": time.time(), "where": where, "model": u.get("model"),
                                    "cost": u["cost"], "tokens_in": u.get("prompt_tokens"),
                                    "tokens_out": u.get("completion_tokens")})
    return u["cost"]


def _ai_spent() -> float:
    """Dollars AI has cost on this video: every chat answer, AI-planned Make
    and check of the edit."""
    pr = PROJECT["p"]
    if pr is None:
        return 0.0
    return round(sum(float(e.get("cost") or (e.get("ai") or {}).get("cost") or 0) for e in pr.events
                     if e.get("kind") in ("chat", "make", "check")), 4)


class QuestionsReq(BaseModel):
    message: str


@app.get("/api/session")
def api_session() -> dict:
    with LOCK:
        return _session()


@app.post("/api/chat")
def api_chat(req: ChatReq) -> dict:
    """One conversational turn: message -> operations -> applied, diffed, undoable.
    The AI is asked outside the lock, so the app keeps playing and answering
    while it thinks; the answer is applied to the edit as it is when it lands."""
    msg = req.message.strip()
    if not msg:
        raise HTTPException(400, "empty message")
    if not CLIPS:
        raise HTTPException(400, "drop some clips in first")
    if WORKFLOW.state not in ("story", "styling"):
        # The gate: nothing is built on the rough cut until a person has seen it.
        raise HTTPException(409, "Look over what was cut first — approve it, then we’ll build the story.")
    with LOCK:
        cat = CATALOG["cat"]
        if llm.chat_provider() == "openai" and req.ai_ok is None and SESSION.board is None:
            # The first story built from the brief, by the app, not a message
            # someone priced and sent: by keywords, free, as with no AI.
            who = None
        else:
            who = _chat_gate(req.ai_ok)
        if who:
            context, image = _target(req.t)
            asked, asked_on = llm.prepare(msg, cat, SESSION, PREFS.for_model(), moment=context), SESSION
        else:
            out = llm.interpret_offline(msg, cat, SESSION, PREFS.for_model())
    if who:
        rid = req.rid or ""
        try:
            out = llm.ask(asked, image, who)
        except llm.LLMError as e:
            with LOCK:
                paid = _chat_spent({"usage": e.usage}, "chat")
                if paid:
                    _save()     # a failed request isn't saved by the middleware; what it cost must be
            STOPPED.discard(rid)
            raise HTTPException(502, str(e) + (f" That try cost {_cents(paid)}." if paid else "")) from e
    with LOCK:
        if out.get("error"):
            raise HTTPException(409, out["error"])
        cost = _chat_spent(out, "chat") if who else None
        if who and rid in STOPPED:
            # Stop was pressed while it thought: the answer is dropped, its cost is kept
            STOPPED.discard(rid)
            return {**_session(), "stopped": True, "stop_cost": cost}
        if who and asked_on is not SESSION:
            raise HTTPException(409, "Another video was opened while the AI answered, so nothing was changed.")
        direction = out.get("direction")
        if direction is not None:
            direction = {**direction, "text": msg}
            # A new description of the video keeps the voiceover it's told over.
            vo = (_direction() or {}).get("voiceover")
            if vo:
                direction["voiceover"] = vo
            # ...and the style answers, unless this message brings new ones.
            style = brief.clean_style(req.style) or (_direction() or {}).get("style")
            if style:
                direction["style"] = style
        ops = out.get("ops", [])
        if req.t is not None:
            ops = [o for o in ops if o.get("op") != "choose_option"]   # about a moment of this edit, never a new one
        SESSION.add({"kind": "chat", "text": msg, "ops": ops,
                     "reply": out.get("reply", ""), "question": out.get("question"),
                     "choices": out.get("choices", []) if out.get("question") else [],
                     "direction": direction, "cost": cost}, CATALOG["cat"], _make_proposals)
        return _session()


# Chat requests whose Stop was pressed while the AI thought (by the id the box gave them).
STOPPED: set[str] = set()


class StopReq(BaseModel):
    rid: str


@app.post("/api/chat/stop")
def api_chat_stop(req: StopReq) -> dict:
    """Stop: the answer, when it comes, changes nothing. What it cost is still
    counted (the AI has already been asked). Needs no lock: the chat that is
    waiting holds none."""
    if req.rid:
        STOPPED.add(req.rid)
    return {"ok": True}


def _cents(usd: float) -> str:
    return "under 1¢" if usd < 0.01 else f"{round(usd * 100)}¢" if usd < 1 else f"${usd:.2f}"


def _target(t: float | None) -> tuple[str, str | None]:
    """The moment a chat message is about (a clicked shot or the paused
    frame), as text for the model and its frame; nothing when it's about the
    whole video or there's nothing there."""
    if t is None or not SESSION.board:
        return "", None
    try:
        m = _moment(t)
    except HTTPException:
        return "", None
    return moment.describe(m), moment.image(m)


@app.get("/api/chat/estimate")
def api_chat_estimate(t: float | None = None) -> dict:
    """What one chat message would cost now, before it is sent (about the
    moment at `t`, if given), and what AI has cost on this video so far.
    Never calls a model."""
    with LOCK:
        who = llm.chat_provider()
        if not who:
            return {"provider": None, "model": None, "tokens_in": 0, "usd": [0.0, 0.0], "on": False,
                    "spent": _ai_spent()}
        extra, frame = 300, False
        if t is not None and SESSION.board:
            try:
                m = _moment(t, words=False)
                extra, frame = extra + 400 + len(moment.describe(m)), bool(m.get("frame"))
            except HTTPException:
                pass
        est = llm.estimate(_prompt_chars() + extra, frame)
        # what each typed character adds, so a long message's price moves as it's typed
        per_char = llm.chat_prices()[1] / llm.CHARS_PER_TOKEN / 1e6
        return {**est, "on": True, "spent": _ai_spent(), "per_char": per_char, "base_chars": 300}


def _prompt_chars() -> int:
    """The chat prompt's length before the creator's words. It hardly moves
    between messages, so it is measured once per state of the edit."""
    state = (id(SESSION), len(SESSION.turns), sum(1 for x in SESSION.turns if x.undone), id(CATALOG["cat"]))
    if _ESTIMATE.get("state") != state:
        _ESTIMATE.update(state=state, chars=llm.prompt_chars(CATALOG["cat"], SESSION, PREFS.for_model()))
    return _ESTIMATE["chars"]


class MomentReq(BaseModel):
    t: float
    message: str = ""
    # earlier exchanges in this pause's chat box, oldest first: {"who": "you"|"ai", "text"}
    history: list[dict] = []
    # the cost the box showed (see ChatReq.ai_ok)
    ai_ok: float | None = None


def _moment(t: float, words: bool = True) -> dict:
    b = SESSION.board
    if not b:
        raise HTTPException(409, "Pick a story first.")
    # the words on screen need every overlay resolved (ink included), which
    # is slow; the box's header doesn't need them, only the message does
    items = _overlays_public(b, CATALOG["cat"], {})["items"] if words else []
    m = moment.at(b, CATALOG["cat"], CLIPS, items, t)
    if m is None:
        raise HTTPException(404, "Nothing in the edit at that moment.")
    return m


@app.post("/api/moment")
def api_moment(req: MomentReq) -> dict:
    """The paused moment: what the chat box is pinned to, and what one message
    about it would cost. Never calls the model."""
    with LOCK:
        m = _moment(req.t, words=False)
        who = llm.chat_provider()
        # + the moment's own lines and words, roughly
        return {"header": moment.header(m), "key": m["key"], "llm": who is not None, "provider": who,
                "estimate": moment.estimate(_prompt_chars() + 400 + len(moment.describe(m)), bool(m.get("frame")))}


_ESTIMATE: dict = {}


@app.post("/api/moment/chat")
def api_moment_chat(req: MomentReq) -> dict:
    """One message about the paused moment -> a reply and, where it fits, the
    edit it proposes. Proposed only: Apply sends the ops to /api/ops, one
    undoable turn, like every other edit."""
    msg = req.message.strip()
    if not msg:
        raise HTTPException(400, "empty message")
    if llm.chat_provider() is None:
        raise HTTPException(409, "Chatting about a moment needs AI: turn AI on in the top bar. Each message shows "
                                 "what it costs before it's sent." if oai.has_key() else
                                 "Chatting about a moment needs AI, and there's no AI key on this Mac.")
    with LOCK:
        who = _chat_gate(req.ai_ok)
        m = _moment(req.t)
        said = "\n".join(f"{'CREATOR' if h.get('who') == 'you' else 'YOU (earlier)'}: {h.get('text', '')}"
                         for h in req.history[-6:] if isinstance(h, dict))
        context = moment.describe(m) + (f"\nEarlier in this conversation about this moment:\n{said}" if said else "")
        try:
            out = llm.interpret(msg, CATALOG["cat"], SESSION, PREFS.for_model(), moment=context,
                                image_b64=moment.image(m), who=who)
        except llm.LLMError as e:
            paid = _chat_spent({"usage": e.usage}, "moment")
            if paid:
                _save()     # a failed request isn't saved by the middleware; what it cost must be
            raise HTTPException(502, str(e) + (f" That try cost {_cents(paid)}." if paid else "")) from e
        cost = _chat_spent(out, "moment")
        ops = [o for o in out.get("ops") or [] if o.get("op") != "choose_option"]
        preview = None
        if ops:
            # what Apply would change, computed on a copy -- never reported by the model
            try:
                trial = bd.Session()
                trial.turns = copy.deepcopy(SESSION.turns)
                trial._next = SESSION._next
                trial.replay(CATALOG["cat"], _make_proposals)
                t = trial.add({"kind": "direct", "text": msg, "ops": ops}, CATALOG["cat"], _make_proposals)
                preview = {"lines": [l["text"] for l in t.lines], "skipped": t.skipped}
            except Exception as e:  # noqa: BLE001 -- a proposal that can't apply is shown as such
                preview = {"lines": [], "skipped": [str(e)]}
        return {"reply": out.get("question") or out.get("reply") or "", "choices": out.get("choices", []),
                "ops": ops, "preview": preview, "header": moment.header(m), "cost": cost, "spent": _ai_spent()}


SUGGESTED: dict = {}     # clip ids -> suggestions, so a revisit doesn't ask again


def _portrait_share() -> float:
    """How much of the usable footage was filmed upright, by seconds."""
    up = total = 0.0
    for sh in _pool():
        c = CLIPS.get(sh.clip_id) or {}
        d = sh.end - sh.start
        total += d
        if c.get("height", 0) > c.get("width", 0):
            up += d
    return up / total if total else 0.0


def _want() -> str | None:
    """The frame the creator picked up front (brief.FORMATS), if any."""
    pr = PROJECT["p"]
    return ((pr.brief or {}).get("style") or {}).get("format") if pr else None


@app.get("/api/brief/setup")
def api_brief_setup() -> dict:
    """What the up-front popup shows: the frame the footage suggests, the
    looks, and the lengths the slider knows -- defaults only, nothing chosen."""
    with LOCK:
        if not CLIPS:
            raise HTTPException(409, "Add clips first.")
        about = pitch.guess(list(CLIPS.values())) or "My video"
        marks = brief.length_marks(_usable_s(), about)
        share = _portrait_share()
        remembered = defaults.get()
        return {"format": remembered.get("format") or brief.suggest_format(share, marks["max"]),
                "suggested": brief.suggest_format(share, marks["max"]), "remembered": remembered,
                "music": remembered.get("music", "on") != "off", "portrait_share": round(share, 2),
                "formats": [{"key": k, "label": v, "seconds": round(brief.length_for(k, marks, _vlog_reach()))} for k, v in brief.FORMATS.items()],
                "look": (_direction() or {}).get("style", {}).get("look") or remembered.get("look") or "cozy",
                "vibes": vibes.choices(), "vibe": remembered.get("vibe"),
                "looks": looks.public(), "about": about}


class BriefAutoReq(BaseModel):
    format: str | None = None
    look: str | None = None
    music: bool | None = None       # None = as last time (defaults.py), else this time's switch
    vibe: str | None = None         # "Cut it like": a library vibe id or ref:<rid> (vibes.py); None = the frame's prior
    ai_ok: float | None = None      # Make only: the AI estimate the creator saw and went ahead with


@app.post("/api/brief/auto")
def api_brief_auto(req: BriefAutoReq | None = None) -> dict:
    """Two picks and no more (the format and the look, plan step 2; the rest
    was dropped by sarah on 2026-10-07): what the video is comes from the
    clips, its length from the format, captions on, the pace read from the
    footage. All changeable in Frames. No model."""
    pr = PROJECT["p"]
    if pr is None:
        raise HTTPException(409, "Open a project first.")
    req = req or BriefAutoReq()
    if req.format is not None and req.format not in brief.FORMATS:
        raise HTTPException(422, "format is short, tall or wide")
    if req.look is not None and req.look not in brief.LOOK_IDS:
        raise HTTPException(422, "no such look")
    with LOCK:
        about = pitch.guess(list(CLIPS.values())) or "My video"
        marks = brief.length_marks(_usable_s(), about)
        # the tempo the footage asks for (sarah, 2026-10-07), not a question
        feel = tempo.read(list(CLIPS.values()), cut.for_story(PLAN["plan"]))
        fmt = req.format or brief.suggest_format(_portrait_share(), marks["max"])
        style = {"seconds": brief.length_for(fmt, marks, _vlog_reach()), "captions": "describe", "pace": feel["pace"],
                 "format": fmt, "look": req.look or "cozy", "vibe": req.vibe or None}
        pr.brief = {"message": about, "style": brief.clean_style(style) or {}, "tempo": feel["why"],
                    "said": f"{brief.FORMATS[fmt].split(' ·')[0]} · about {brief.say_length(style['seconds'])} · "
                            f"{tempo.NAMES[feel['pace']].lower()} · {looks.get(style['look'])['name']} · captions",
                    "at": time.time()}
        # the pace is known now: start fetching the free tracks for it, so the
        # bed under the story lands in seconds rather than minutes (bed.py)
        if musiclib.STATE["status"] != "ready" and os.environ.get("VIBECUT_BED", "1") != "0":
            bed.prefetch(feel["pace"])
        return _session()


# --------------------------------------------------------------------------
# make: the two picks -> a finished video on the board (make.py)
# --------------------------------------------------------------------------

MAKE: dict = {"job": None}
MAKE_TEXT = "Made your video"


@app.post("/api/make")
def api_make(req: BriefAutoReq | None = None) -> dict:
    """The main path since 2026-10-17: the brief from the two picks, the gate
    passed in the creator's name (pressing Make *is* the decision), then the
    one pipeline runs as a job and lands as one undoable turn. Returns the
    job; poll /api/make/{id}; the session has the video when it's done."""
    api_brief_auto(req)
    with LOCK:
        if not CLIPS:
            raise HTTPException(409, "Add clips first.")
        if MAKE["job"] and MAKE["job"].stage not in ("done", "error"):
            return MAKE["job"].public()
        if WORKFLOW.state == GATE:
            WORKFLOW.approve("user", "made from the two picks")
        pr = PROJECT["p"]
        style = (pr.brief or {}).get("style") or {}
        about = (pr.brief or {}).get("message") or "My video"
        # the direction turn: the other stories (Other stories…) are built from it
        if not any(t.direction for t in SESSION.turns if not t.undone):
            SESSION.add({"kind": "chat", "text": about, "ops": [],
                         "direction": {"text": about, "style": style, "themes": [], "labels": []}},
                        CATALOG["cat"], _make_proposals)
        own = musiclib.STATE["tracks"] if musiclib.STATE["status"] == "ready" else None
        clips = dict(CLIPS)
        cut_now = cut.for_story(PLAN["plan"])
        remembered = defaults.get()
        # the creator's habits, from every video so far (habits.py): a nudge
        # on the picks, the music switch's default, their own phrasing
        hab = habits.derive(pj.list_all())
        h_music = habits.music_default(hab)
        want_music = (req.music if (req and req.music is not None)
                      else (h_music if h_music is not None else remembered.get("music", "on") != "off"))
        h_bias = habits.bias(hab)
        h_used = [h for h in habits.active(hab) if (h.get("label") and h["label"] in h_bias) or (h["id"] == "music_off" and not want_music)]
        found = places.lookup([c.get("gps") for c in CLIPS.values()])
        # the creator's own picks follow them to the next video (defaults.py, layer 1)
        defaults.note(format=style.get("format"), look=style.get("look"), music="on" if want_music else "off",
                      vibe=style.get("vibe") or None)
        vibe_fp = vibes.fingerprint_for(style.get("vibe"))
        try:
            prof = (json.loads(defaults.SETTINGS.read_text()).get("profile") or {}).get("value")
        except (OSError, ValueError):
            prof = None
        taste = make.taste_text(prof, PREFS.for_model())
        caption_style = {k: remembered[f"caption_{k}"] for k in ("template", "enter") if remembered.get(f"caption_{k}")}

    def on_done(job: make.Job) -> None:
        with LOCK:
            if MAKE["job"] is not job or job.stage != "done" or not job.result:
                return
            mx = job.result["music"]
            if mx:
                t = mx["track"]
                if not any(x.id == t.id for x in musiclib.STATE["tracks"]):
                    musiclib.STATE["tracks"].append(t)
                musiclib.use(t.id)
            ops_ = list(job.result["ops"])
            if caption_style:
                ops_.append({"op": "overlay_style", **caption_style, "source": "defaults"})   # as last time
            acted = [h for h in h_used if (h.get("label") and any(h["label"] in (CATALOG["cat"].shots[e["id"]].labels if e["id"] in CATALOG["cat"].shots else {})
                                                                       for bt in job.result["ops"][0]["snapshot"]["beats"] for e in bt["shots"]))
                     or h["id"] == "music_off"]
            said = habits.describe(acted)
            job.result["habits"] = [{"id": h["id"], "text": h["text"]} for h in acted]
            MAKE["last_habits"] = job.result["habits"]
            if acted:
                due = habits.used([h["id"] for h in acted])
                for h in due:
                    habits.mark_offered(h["id"])
            made_turn = SESSION.add({"kind": "direct", "text": MAKE_TEXT, "ops": ops_,
                                     "reply": job.result["reply"] + (" " + said if said else "")},
                                    CATALOG["cat"], _make_proposals)
            # the songs to swap between (songs.py), and what a remake on another one needs
            _songs_set(mx, job.result.get("remake"), made_turn.id, style.get("look"), style.get("format", "tall"),
                       extra=ops_[len(job.result["ops"]):])
            # "which do you like better?" (prefer.py): the versions the taste model weighed
            pick_ = job.result.get("taste_pick") or {}
            PREFER["deck"] = (prefer.Deck(job.result["deck"], pick_, made_turn.id, getattr(PROJECT["p"], "id", None),
                                          extra=ops_[len(job.result["ops"]):])
                              if job.result.get("deck") and len(pick_.get("specs") or []) > 1 else None)
            if job.result.get("check"):
                _check_landed(job.result["check"], PROJECT["p"], "make")     # its fixes undo on their own
            if style.get("format", "tall") != "short" and not job.result["fp"].get("refs_used") and SESSION.board:
                # a vlog's cuts sit on movement (vlog.py step 5): the smoother's nudge, as its
                # own turn so one undo takes it back and an undo is heard (preferences.py)
                try:
                    n_ops, n_said = smooth.propose(SESSION.board, clips, CATALOG["cat"], order=False, nudge=True)
                    if n_ops:
                        SESSION.add({"kind": "direct", "text": "Smoother cuts", "ops": n_ops, "reply": n_said},
                                    CATALOG["cat"], _make_proposals)
                except Exception as e:  # noqa: BLE001 -- a nudge that fails leaves the cut as made
                    job.result.setdefault("notes", []).append(f"no nudge: {e}")
            pr_ = PROJECT["p"]
            if pr_ is not None and pr_.brief:
                # the chips read the brief: after Make it must describe the cut, not the guess
                fp_ = job.result["fp"]
                pace_ = make.pace_of(fp_)
                pr_.brief = {**pr_.brief,
                             "style": {**(pr_.brief.get("style") or {}), "pace": pace_,
                                       "seconds": round(job.result["plan"].duration, 1)},
                             "tempo": f"{tempo.NAMES[pace_]}: about {fp_['median_s']:.1f} s a shot, "
                                      + ("from your reels." if fp_.get("refs_used") else "the way a short is cut." if fp_["median_s"] < 1.3 else "the way a vlog breathes.")}
            if PROJECT["p"] is not None:
                PROJECT["p"].events.append({"kind": "make", "at": time.time(), "music": bool(mx),
                                            "seconds": round(job.result["plan"].duration, 1),
                                            "ai": job.result.get("ai"),
                                            "elapsed": round(time.time() - job.started, 1)})
        _save()

    def register(job: make.Job) -> None:
        MAKE["job"] = job     # before the thread runs: a fast job must not land as "not mine"

    # the AI plans this edit only when it is switched on and the creator went
    # ahead having seen what it would cost (/api/make/estimate); a chosen vibe
    # sets the cut itself, so it never spends then
    use_ai = bool(req and req.ai_ok is not None and oai.enabled() and not vibe_fp)

    def check_made(ops_: list[dict], period: float | None) -> dict:
        # the finished cut as it will land, worked out on a copy of the log (the price shown covered this look)
        with LOCK:
            trial = bd.Session()
            trial.turns = copy.deepcopy(SESSION.turns)
            trial._next = SESSION._next
            trial.add({"kind": "direct", "text": MAKE_TEXT, "ops": copy.deepcopy(ops_)}, CATALOG["cat"], _make_proposals)
            board_, cat_, clips_ = trial.board, CATALOG["cat"], dict(CLIPS)
        return _check(board_, cat_, clips_, style.get("format", "tall"), float(style.get("seconds") or 60.0), period)

    job = make.start(clips, cut_now, style.get("format", "tall"), style.get("pace", "balanced"),
                     style.get("look"), about, float(style.get("seconds") or 60.0), own, None, None, on_done,
                     want_music=want_music, register=register, vibe=vibe_fp, taste=taste,
                     bias=h_bias, found=found, phrasing=habits.phrases(),
                     use_ai=use_ai, check=check_made if use_ai else None,
                     want_sfx=remembered.get("sfx", "on") != "off")
    return job.public()


@app.get("/api/habits")
def api_habits() -> dict:
    """What the app has learned about the creator, each with its evidence and its switch."""
    return {"habits": habits.load(), "phrases": habits.phrases(), "last": MAKE.get("last_habits") or []}


class HabitReq(BaseModel):
    off: bool
    remake: bool = False


@app.post("/api/habits/{hid}")
def api_habit_switch(hid: str, req: HabitReq) -> dict:
    """The one tap: a habit off (or on), recorded; `remake` makes the video again without it."""
    h = habits.switch(hid, req.off)
    if h is None:
        raise HTTPException(404, "no such habit")
    if req.remake and SESSION.board is not None:
        pr = PROJECT["p"]
        style = ((pr.brief or {}).get("style") or {}) if pr else {}
        last = next((t for t in reversed(SESSION.turns) if t.text == MAKE_TEXT and not t.undone), None)
        with LOCK:
            if last:
                SESSION.toggle(last.id, CATALOG["cat"], _make_proposals)
        return api_make(BriefAutoReq(format=style.get("format"), look=style.get("look"),
                                     music=None, vibe=style.get("vibe")))
    return {"habit": h}


@app.get("/api/captions/voice")
def api_caption_voice() -> dict:
    """Her caption voice (captionmem.py): the rules her edits support, in
    plain words with their switches, and her lines. Local; never mirrored."""
    return captionmem.voice()


class CaptionLineReq(BaseModel):
    text: str
    remove: bool = False


@app.post("/api/captions/lines")
def api_caption_line(req: CaptionLineReq) -> dict:
    """Add one of her lines by hand, or take one out of the bank."""
    if not req.text.strip():
        raise HTTPException(422, "a line needs some words")
    (captionmem.remove_line if req.remove else captionmem.add_line)(req.text)
    return captionmem.voice()


class CaptionRuleReq(BaseModel):
    on: bool


@app.post("/api/captions/rules/{rid}")
def api_caption_rule(rid: str, req: CaptionRuleReq) -> dict:
    captionmem.switch(rid, req.on)
    return captionmem.voice()


@app.get("/api/vibes")
def api_vibes() -> dict:
    """The library's vibes and the creator's own learnt reels, for "Cut it like"."""
    return {"vibes": vibes.choices()}


class AIReq(BaseModel):
    on: bool


def _ai_public() -> dict:
    return {"available": oai.has_key(), "on": oai.enabled(), "model": oai.model()}


@app.get("/api/ai")
def api_ai() -> dict:
    """The AI switch (sarah, 2026-10-18): off by default; on means each
    edit shows its cost first. No key in web/.env: it can't be turned on."""
    return _ai_public()


@app.post("/api/ai")
def api_ai_set(req: AIReq) -> dict:
    if req.on and not oai.has_key():
        raise HTTPException(409, "There's no AI key in web/.env on this Mac, so AI can't be turned on.")
    oai.switch(req.on)
    return _ai_public()


@app.get("/api/make/estimate")
def api_make_estimate() -> dict:
    """What letting the AI plan this edit would cost, before anything is
    sent: how many moments it would see, and dollars at the model's price."""
    with LOCK:
        if not CLIPS:
            raise HTTPException(409, "Add clips first.")
        clips = dict(CLIPS)
        cut_now = cut.for_story(PLAN["plan"]) if PLAN["plan"] else None
    out = _ai_public()
    if not out["on"]:
        return {**out, "moments": 0, "dollars": 0.0}
    n = len(story.candidates(clips, cut_now))
    # planning it, then one look at the finished cut (selfcheck.py); the plan
    # keeps at most CHECK_SHOTS of the moments [prior], so this never comes out low
    plan_usd, check_usd = story.estimate(n), selfcheck.estimate(min(n, CHECK_SHOTS))
    return {**out, "moments": n, "dollars": round(plan_usd + check_usd, 3),
            "plan": round(plan_usd, 3), "check": round(check_usd, 3)}


class VibeReq(BaseModel):
    niche: str
    name: str | None = None
    links: list[str]


@app.post("/api/vibes")
def api_vibe_start(req: VibeReq) -> dict:
    """Learn a vibe from reels (links or files on this Mac), as a job."""
    srcs = [x.strip() for x in req.links if x.strip()]
    if len(srcs) < vibes.MIN_REELS:
        raise HTTPException(400, f"A vibe needs at least {vibes.MIN_REELS} reels.")
    if not req.niche.strip():
        raise HTTPException(400, "Say what these reels have in common.")
    return vibes.start(req.niche.strip(), (req.name or "").strip() or None, srcs).public()


@app.get("/api/vibes/jobs/{jid}")
def api_vibe_status(jid: str) -> dict:
    job = vibes.JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    return job.public()


@app.get("/api/vibes/{vid}")
def api_vibe_get(vid: str) -> dict:
    """Get a vibe's data including full blueprint and emotional intelligence."""
    rec = vibes.get(vid)
    if not rec:
        raise HTTPException(404, "no such vibe")
    blueprint = rec.get("blueprint", {})
    return {
        "id": rec["id"],
        "name": rec["name"],
        "niche": rec.get("niche"),
        "n": rec.get("n"),
        "recipe": rec.get("recipe"),
        "blueprint": blueprint,  # Full detailed analysis
        "emotional_blueprint": blueprint.get("emotional_blueprint"),  # Emotional intelligence layer
        "summary": rec.get("words", []),
    }


@app.get("/api/make/{jid}")
def api_make_status(jid: str) -> dict:
    job = make.JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    return job.public()


# --------------------------------------------------------------------------
# which do you like better? a few cards after Make (prefer.py; sarah, 2026-10-21)
# --------------------------------------------------------------------------

from . import prefer  # noqa: E402

PREFER: dict = {"deck": None}
PREFER_LOCK = threading.Lock()     # builds a card outside LOCK; never taken while holding LOCK
# what the app puts on a made video by itself, from what the creator told it, as a turn of its own
# after Make (a profile's captions or transition at every cut), by that turn's text -> what puts it
# on again. Under such a turn the video is still as made, so a pick may land; the picked version
# then gets it too, inside the pick's own turn, so one Undo brings the other version back whole.
REDRESS: dict[str, Callable[[prefer.Deck], None]] = {}


def _basis(d: prefer.Deck) -> int | None:
    """Under LOCK: the turn the video's version is read from, the last live
    one, looking past what REDRESS put on by itself since."""
    live = [t for t in SESSION.turns if not t.undone and t.ops]
    while live and live[-1].text in REDRESS and live[-1].id not in d.turns:
        live.pop()
    return live[-1].id if live else None


def _follow(d: prefer.Deck) -> bool:
    """Under LOCK: whether the video is as Make or the last pick left it (Deck.follow)."""
    return d.follow(_basis(d))


def _prefer_deck() -> prefer.Deck | None:
    """The cards for the video on screen: gone when another project is open,
    or the Make they came from was undone or made again. Under LOCK."""
    d, pr = PREFER["deck"], PROJECT["p"]
    if d is None or pr is None or d.project != pr.id:
        return None
    mk = next((t for t in SESSION.turns if t.id == d.make_turn), None)
    if mk is None or mk.undone or any(t.text == MAKE_TEXT and t.id > d.make_turn and not t.undone for t in SESSION.turns):
        return None
    return d


def _prefer_public() -> dict | None:
    d = _prefer_deck()
    # `on`: the turn the video's version is read from; when it moves (an Undo) the card is fetched again
    return None if d is None or d.done() else {"at": min(d.i + 1, len(d.kinds)), "of": len(d.kinds),
                                               "deck": d.make_turn, "on": _basis(d)}


def _card_public(card: dict) -> dict:
    sides = []
    for side, win in zip(card["sides"], card["windows"]):
        m = side.board.get("music") or {}
        t = musiclib.find(m["track"]) if m.get("track") else None
        out = prefer.side_public(side, win)
        sp = _mix_spec(side.board, timeline.layout(side.board), track=t)
        out["audio"] = f"/api/mix/{_keep_mix(sp)}.wav" if sp else None
        # its first shot's still, shown until it plays (as the player holds a frame while loading)
        first = next((CATALOG["cat"].shots.get(it["shot_id"]) for it in out["items"] if it["kind"] == "shot"), None)
        out["poster"] = first.thumb if first else None
        sides.append(out)
    return {"id": card["id"], "ask": card["ask"], "at": card["at"], "of": card["of"], "sides": sides}


@app.get("/api/prefer")
def api_prefer() -> dict:
    """The card on show: two versions of the video that differ in one part,
    each as the shots that play and the sound they play with."""
    with PREFER_LOCK:
        with LOCK:
            d = _prefer_deck()
            if d is not None:
                _follow(d)
            frame = export.frame_size(timeline.layout(SESSION.board), CLIPS, _want()) if d is not None else None
        card = d.next_card() if d is not None else None
        with LOCK:
            return {"card": _card_public(card) if card else None, "frame": frame}


class PreferReq(BaseModel):
    pick: int | None = None      # 0 / 1 = the left / right version; None = can't tell


@app.post("/api/prefer/{cid}")
def api_prefer_pick(cid: int, req: PreferReq) -> dict:
    """Her pick: kept as a pair for her layer of the taste model, and the
    picked version put on the video while it is as Make (or the last pick)
    left it, as one undoable turn."""
    if req.pick not in (None, 0, 1):
        raise HTTPException(400, "pick is 0, 1 or nothing")
    with PREFER_LOCK:
        with LOCK:
            d = _prefer_deck()
            if d is None:
                raise HTTPException(409, "These versions are for a video that has changed since.")
            last = SESSION.last_active()
            as_made = _follow(d)
            redress = list(dict.fromkeys(t.text for t in SESSION.turns
                                         if not t.undone and t.ops and t.id > d.make_turn and t.text in REDRESS))
        try:
            got = d.answer(cid, req.pick)
        except KeyError as e:
            raise HTTPException(409, "That card has gone; here is the next one.") from e
        with LOCK:
            side, words = got["side"], got["words"]
            landed = False
            if side is None:
                said = "Skipped."
            elif not got["change"]:
                said = "Noted. Your video already has that one."
            elif as_made and _prefer_deck() is d and SESSION.last_active() is last:
                t = SESSION.add({"kind": "direct", "text": prefer.TURN_TEXT,
                                 "ops": copy.deepcopy(side.ops) + copy.deepcopy(d.extra),
                                 "reply": f"Your video now has {words}."}, CATALOG["cat"], _make_proposals)
                for text in redress:
                    n = len(SESSION.turns)
                    REDRESS[text](d)
                    for x in SESSION.turns[n:]:        # into the pick's turn: one Undo takes it all back
                        t.ops += x.ops
                    del SESSION.turns[n:]
                if redress:
                    SESSION.replay(CATALOG["cat"], _make_proposals)
                d.landed(t.id, side)
                landed = True
                said = f"Your video now has {words}."
            elif last is not None and last.kind == "check":
                said = "Noted for your next videos. This one keeps the fixes from the check."
            else:
                said = "Noted for your next videos. This one keeps the changes you made."
            if PROJECT["p"] is not None:
                PROJECT["p"].events.append({"kind": "prefer", "at": time.time(), "ask": d.answers[-1]["kind"],
                                            "pick": req.pick, "versions": d.answers[-1]["names"],
                                            "video": d.answers[-1]["video"], "landed": landed})
            out = {**_session(), "prefer_said": said, "prefer_landed": landed}
    _save()
    return out


# --------------------------------------------------------------------------
# the AI checks its own edit (selfcheck.py; sarah, 2026-10-18)
# --------------------------------------------------------------------------

CHECK_TEXT = "Checked its own edit"
CHECK_SHOTS = 48


def _music_period(board: dict | None) -> float | None:
    """The beat of the edit's music, when its tempo is known: shortening keeps it."""
    t = musiclib.find(((board or {}).get("music") or {}).get("track"))
    return 60.0 / t.bpm if t is not None and t.bpm else None


def _check(board: dict | None, cat, clips: dict[str, dict], fmt: str, target: float | None,
           period: float | None) -> dict:
    """One look at the cut, outside the lock. -> selfcheck.review's answer, or
    {error, usage} (a failed answer can still have cost something)."""
    try:
        return selfcheck.review(board, cat, clips, fmt, target, period)
    except Exception as e:  # noqa: BLE001 -- the edit stands as it is, and the turn says so
        return {"error": str(e)[:200], "usage": getattr(e, "usage", None) or {}}


def _check_cost(res: dict, pr, where: str) -> float | None:
    """What a check cost goes with the video it was asked about."""
    u = res.get("usage") or {}
    if "cost" not in u:
        return None
    if pr is not None:
        pr.events.append({"kind": "check", "at": time.time(), "where": where, "model": u.get("model"),
                          "cost": u["cost"], "tokens_in": u.get("prompt_tokens"),
                          "tokens_out": u.get("completion_tokens"), "fixes": len(res.get("ops") or []),
                          "error": res.get("error")})
    return u["cost"]


def _check_landed(res: dict, pr, where: str) -> bd.Turn:
    """Under LOCK: the check as one turn (its fixes undo together), with what it cost."""
    cost = _check_cost(res, pr, where)
    if res.get("error"):
        said = f"I couldn't check the finished cut ({res['error']}), so your edit is as it was."
        if cost:
            said += f" That try cost {_cents(cost)}."
        return SESSION.add({"kind": "check", "text": CHECK_TEXT, "ops": [], "reply": said, "cost": cost},
                           CATALOG["cat"], _make_proposals)
    return SESSION.add({"kind": "check", "text": CHECK_TEXT, "ops": res["ops"], "reply": res["reply"],
                        "cost": cost, "sheets": res.get("sheets") or []}, CATALOG["cat"], _make_proposals)


@app.get("/api/check/estimate")
def api_check_estimate() -> dict:
    """What one check of the edit as it stands would cost, before it's sent. Never calls a model."""
    with LOCK:
        n = len(selfcheck.shots_of(SESSION.board))
        spent = _ai_spent()
    on = oai.enabled() and n >= 3
    return {"on": on, "available": oai.has_key(), "model": oai.model(), "shots": n,
            "dollars": round(selfcheck.estimate(n), 3) if on else 0.0, "spent": spent}


class CheckReq(BaseModel):
    ai_ok: float | None = None    # the price the button showed
    rid: str | None = None        # so Stop can find it


@app.post("/api/check")
def api_check(req: CheckReq) -> dict:
    """Check my edit: the AI looks at the cut as it stands (a contact sheet of
    every shot) and fixes what's clearly wrong, as one undoable turn. Only with
    the AI switch on and the price shown on the button. Asked outside the
    lock, like the chat; applied to the edit as it is when it lands."""
    if not oai.enabled():
        raise HTTPException(409, "Checking the edit needs AI: turn AI on in the top bar." if oai.has_key()
                            else "Checking the edit needs AI, and there's no AI key on this Mac.")
    if req.ai_ok is None:
        raise HTTPException(409, "Press Check my edit, which shows what it costs before it goes.")
    with LOCK:
        if len(selfcheck.shots_of(SESSION.board)) < 3:
            raise HTTPException(409, "Make your video first: there's nothing to check yet.")
        board, cat, clips = copy.deepcopy(SESSION.board), CATALOG["cat"], dict(CLIPS)
        pr, asked_on = PROJECT["p"], SESSION
        style = ((pr.brief or {}).get("style") or {}) if pr else {}
        period = _music_period(board)
    res = _check(board, cat, clips, style.get("format") or "tall", style.get("seconds"), period)
    rid = req.rid or ""
    with LOCK:
        if rid in STOPPED or asked_on is not SESSION:
            # Stop was pressed, or another video opened: nothing changes; what it cost is kept
            STOPPED.discard(rid)
            cost = _check_cost(res, pr, "button")
            if asked_on is not SESSION:
                if cost and pr is not None:
                    pj.save(pr)     # an error isn't saved by the middleware; what it cost must be
                raise HTTPException(409, "Another video was opened while the AI looked, so nothing was changed.")
            return {**_session(), "stopped": True, "stop_cost": cost}
        _check_landed(res, pr, "button")
        return _session()


@app.get("/api/check/sheet/{name}")
def api_check_sheet(name: str):
    """A contact sheet the AI looked at, so the creator can see it too."""
    p = selfcheck.sheet_path(name)
    if p is None:
        raise HTTPException(404, "no such sheet")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


class FormatReq(BaseModel):
    format: str


@app.post("/api/format")
def api_format(req: FormatReq) -> dict:
    """The frame, changed in Frames: short / tall (vertical) or wide. Not a
    board op (nothing in the cut moves), so not in the log; the preview's
    stage and the export follow it at once."""
    if req.format not in brief.FORMATS:
        raise HTTPException(422, "format is short, tall or wide")
    pr = PROJECT["p"]
    if pr is None:
        raise HTTPException(409, "Open a project first.")
    with LOCK:
        pr.brief = {**(pr.brief or {"message": "", "said": "", "at": time.time()}),
                    "style": {**((pr.brief or {}).get("style") or {}), "format": req.format}}
        defaults.note(format=req.format)
        return _session()


class PaceReq(BaseModel):
    pace: str


@app.post("/api/pace")
def api_pace(req: PaceReq) -> dict:
    """Quick / steady / calm cuts in Frames, as one undoable turn: every shot
    back to its rough-trim window, at most the pace's longest shot around its
    best frame. Talking keeps its whole window."""
    if req.pace not in brief.PACE_CAP_S:
        raise HTTPException(422, "pace is fast, balanced or calm")
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Pick a story first.")
        cat = CATALOG["cat"]
        _, windows = cut.for_story(PLAN["plan"])
        talk = tempo.talking(list(CLIPS.values()), _pool())
        pr = PROJECT["p"]
        ops = tempo.pace_ops(SESSION.board, cat, windows, req.pace, talk,
                             ((pr.brief or {}).get("style") if pr is not None else None))
        name = tempo.NAMES[req.pace]
        if ops:
            SESSION.add({"kind": "direct", "text": name, "ops": ops,
                         "reply": f"{name} now. Talking keeps its whole sentence. Undo puts it back."},
                        cat, _make_proposals)
        pr = PROJECT["p"]
        if pr is not None and pr.brief:
            pr.brief = {**pr.brief, "style": {**(pr.brief.get("style") or {}), "pace": req.pace},
                        "tempo": f"{name}, as you chose."}
        return _session()


class CaptionsReq(BaseModel):
    on: bool


@app.post("/api/captions")
def api_captions(req: CaptionsReq) -> dict:
    """Captions on or off in Frames, as one undoable turn. Off takes every
    caption away; on puts back what the style asked for (else the time and
    place of each moment)."""
    with LOCK:
        b = SESSION.board
        if not b:
            raise HTTPException(409, "Choose a story first.")
        if not req.on:
            ops = [{"op": "drop_overlay", "overlay": o["id"]} for o in b.get("overlays", [])]
            if ops:
                SESSION.add({"kind": "direct", "text": "Captions off", "ops": ops,
                             "reply": "Captions off. Undo puts them back."}, CATALOG["cat"], _make_proposals)
            return _session()
        if not b.get("overlays"):
            _words_as_asked(force=True)
        return _session()


@app.get("/api/brief/guess")
def api_brief_guess() -> dict:
    """What the video is, read from the footage (no model, no cost)."""
    with LOCK:
        clips = list(CLIPS.values())
    return {"about": pitch.guess(clips)}


@app.get("/api/brief/suggestions")
def api_brief_suggestions() -> dict:
    """Three one-line descriptions read from the footage, to click instead of typing."""
    with LOCK:
        clips = list(CLIPS.values())
    if not clips:
        return {"suggestions": [], "source": "none"}
    key = ",".join(sorted(c["id"] for c in clips))
    if key not in SUGGESTED:
        SUGGESTED.clear()
        SUGGESTED[key] = pitch.suggest(clips)
    return SUGGESTED[key]


def _pool() -> list:
    """Every shot an edit may use: kept by the rough cut, as its window."""
    shots, _ = storyboard.usable(storyboard.shots_from_clips(list(CLIPS.values()), cut.for_story(PLAN["plan"])))
    return shots


def _usable_s() -> float:
    """The good footage an edit can actually use: look-alikes count once."""
    if not CLIPS:
        return 0.0
    return brief.reachable_s(SESSION.board, CATALOG["cat"], _pool(), VISION_USED["value"])


def _vlog_reach() -> float:
    """How long a vlog Make can run on this footage (vlog.reach): what the setup may promise."""
    return vlog.reach(_pool(), VISION_USED["value"]) if CLIPS else 0.0


def _about() -> str:
    """What the creator said the video is, for the length marks."""
    text = (_direction() or {}).get("text") or ""
    if not text and PROJECT["p"] is not None:
        text = (PROJECT["p"].brief or {}).get("message", "")
    return text.split("\n")[0]


class LengthReq(BaseModel):
    seconds: float


@app.get("/api/length")
def api_length() -> dict:
    """The length slider in Frames: the same marks the questions showed, and
    how long the edit is now. Free; nothing leaves the Mac."""
    with LOCK:
        b = SESSION.board
        now = sum(bd.seq_dur(e) for bt in (b or {}).get("beats", []) for e in bt["shots"])
        return {**brief.length_marks(_usable_s(), _about()), "current": round(now, 1)}


@app.post("/api/length")
def api_length_set(req: LengthReq) -> dict:
    """Bring the edit to about this long, as one undoable turn."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Pick a story first.")
        target = max(5.0, float(req.seconds))
        ops, said = brief.length_ops(SESSION.board, CATALOG["cat"], _pool(), target, VISION_USED["value"])
        if ops:
            SESSION.add({"kind": "direct", "text": f"Make it about {brief.say_length(target)}", "ops": ops,
                         "reply": said}, CATALOG["cat"], _make_proposals)
        return {**_session(), "length_note": said}


class PileReq(BaseModel):
    clip: str
    into: bool


@app.post("/api/pile")
def api_pile(req: PileReq) -> dict:
    """A clip moved between Frames' two piles, Kept (in the video) and Left
    out: in or out of the edit as one undoable turn. The rough cut's call is
    set to match, so Footage's stacks agree and the length slider never puts
    back a clip the creator took out."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Pick a story first.")
        c = CLIPS.get(req.clip)
        if c is None:
            raise HTTPException(404, "no such clip")
        d = PLAN["plan"].clips.get(req.clip) if PLAN["plan"] else None
        if d and d["rejected"] == req.into:
            action = ("keep" if d["auto_rejected"] else "auto") if req.into else ("auto" if d["auto_rejected"] else "reject")
            PLAN["plan"] = cut.override(PLAN["plan"], req.clip, action, CLIPS)
            WORKFLOW.revise("user", f"{action} {req.clip}")
            SESSION.replay(CATALOG["cat"], _make_proposals)
        windows = [s for s in _pool() if s.clip_id == req.clip]
        ops = brief.clip_ops(SESSION.board, CATALOG["cat"], req.clip, req.into, windows)
        if ops:
            SESSION.add({"kind": "direct", "ops": ops,
                         "text": f"You {'put' if req.into else 'left'} {c['name']} {'in the video' if req.into else 'out'}"},
                        CATALOG["cat"], _make_proposals)
        return _session()


@app.post("/api/brief/questions")
def api_brief_questions(req: QuestionsReq) -> dict:
    """The style questions asked once, after the first description."""
    with LOCK:
        shots, _ = storyboard.usable(storyboard.shots_from_clips(list(CLIPS.values())))
        qs = brief.fixed_questions(brief.theme_counts(shots), _usable_s(), req.message)
    tailored = False
    if llm.available() and req.message.strip():
        try:
            extra = llm.tailor_questions(req.message.strip(), qs)
            qs += extra
            tailored = bool(extra)
        except llm.LLMError:
            pass  # the fixed questions are enough on their own
    return {"questions": qs, "tailored": tailored}


# --------------------------------------------------------------------------
# the creator's voiceover as the spine (opt-in)
# --------------------------------------------------------------------------

class VoiceoverReq(BaseModel):
    text: str


@app.post("/api/voiceover")
def api_voiceover(req: VoiceoverReq) -> dict:
    """Subtitles or a script -> a fourth proposal that follows it. Recorded
    as a turn, so Undo takes it away again."""
    if not CLIPS:
        raise HTTPException(400, "drop some clips in first")
    if WORKFLOW.state not in ("story", "styling"):
        raise HTTPException(409, "Look over what was cut first — approve it, then we’ll build the story.")
    script = voiceover.parse(req.text)
    if not script["lines"]:
        raise HTTPException(400, "no lines found — paste subtitles (.srt) or the script itself")
    with LOCK:
        cur = {k: v for k, v in (_direction() or {"text": ""}).items() if k != "voiceover"}
        what = "from subtitles" if script["timing"] == "estimated" else "timed from the words"
        SESSION.add({"kind": "direct", "text": f"Voiceover: {len(script['lines'])} lines, {what}",
                     "ops": [], "direction": {**cur, "voiceover": script}}, CATALOG["cat"], _make_proposals)
        return _session()


# --------------------------------------------------------------------------
# what edits teach: candidates, sorted only by the creator
# --------------------------------------------------------------------------

class ClassifyReq(BaseModel):
    turn: int
    klass: str
    rule: str = ""
    scope: str = ""
    counter: str = ""
    reason: str = ""


@app.post("/api/preferences/classify")
def api_pref_classify(req: ClassifyReq) -> dict:
    with LOCK:
        try:
            PREFS.classify(SESSION, req.turn, req.klass, "user", req.rule, req.scope, req.counter, req.reason)
        except PreferenceError as e:
            raise HTTPException(400, str(e)) from e
        return _session()


class SuggestReq(BaseModel):
    id: str
    klass: str
    rule: str = ""
    scope: str = ""
    counter: str = ""


@app.post("/api/preferences/suggest")
def api_pref_suggest(req: SuggestReq) -> dict:
    """A suggested rule (from an undo or a "no" at export) becomes a rule, or is dismissed."""
    with LOCK:
        try:
            PREFS.take(req.id, req.klass, "user", req.rule, req.scope, req.counter)
        except PreferenceError as e:
            raise HTTPException(400, str(e)) from e
        return _session()


@app.post("/api/preferences/{rid}/{action}")
def api_pref_change(rid: str, action: str) -> dict:
    with LOCK:
        try:
            if action == "forget":
                PREFS.revoke(rid, "user")
            elif action == "narrow":
                PREFS.narrow(rid, "user")
            else:
                raise HTTPException(404)
        except PreferenceError as e:
            raise HTTPException(400, str(e)) from e
        return _session()


# --------------------------------------------------------------------------
# the rough cut and its gate
# --------------------------------------------------------------------------

@app.get("/api/cut")
def api_cut() -> dict:
    with LOCK:
        p = PLAN["plan"]
        return {"workflow": WORKFLOW.public(), "summary": cut.summary(p) if p else None,
                "clips": list(p.clips.values()) if p else []}


class OverrideReq(BaseModel):
    target: str          # clip id, or shot id "clip:index"
    action: str          # keep | reject | full | longer | shorter | set | auto
    start: float | None = None   # set: the creator's in and out points
    end: float | None = None


@app.post("/api/cut/override")
def api_cut_override(req: OverrideReq) -> dict:
    with LOCK:
        if not PLAN["plan"]:
            raise HTTPException(400, "nothing to override yet")
        try:
            PLAN["plan"] = cut.override(PLAN["plan"], req.target, req.action, CLIPS, req.start, req.end)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e)) from e
        WORKFLOW.revise("user", f"{req.action} {req.target}")
        SESSION.replay(CATALOG["cat"], _make_proposals)
    return api_cut()


@app.post("/api/cut/approve")
def api_cut_approve() -> dict:
    with LOCK:
        try:
            WORKFLOW.approve("user", cut.summary(PLAN["plan"])["line_en"] if PLAN["plan"] else "")
        except WorkflowError as e:
            raise HTTPException(409, str(e)) from e
        SESSION.replay(CATALOG["cat"], _make_proposals)
        return _session()


CAPTION_KINDS = ("caption", "part", "title")      # the words VibeCut writes for a stop or the video


def _caption_memory(ops: list[dict], before: dict[str, dict]) -> None:
    """Her hand edits of captions, kept with what they sat over
    (captionmem.py): a retype, a deletion, a line written over a
    placeholder. Kept on this Mac only. Never raises into the request."""
    try:
        board = SESSION.board or {}
        now = {o["id"]: o for o in board.get("overlays", [])}
        for op in ops:
            oid = op.get("overlay")
            if op.get("op") not in ("edit_overlay", "drop_overlay") or oid not in before:
                continue
            old = before[oid]
            if old.get("kind") not in CAPTION_KINDS:
                continue
            if op["op"] == "edit_overlay" and "text" not in op and "sub" not in op:
                continue                  # moved, restyled: not her words
            new = now.get(oid) if op["op"] == "edit_overlay" else None
            captionmem.record(old.get("text"), (new or {}).get("text", ""), _caption_ctx(old),
                              old.get("sub"), (new or {}).get("sub", ""),
                              project=getattr(PROJECT["p"], "id", None))
    except Exception as e:  # noqa: BLE001 -- memory is a nicety; the edit itself already landed
        print(f"caption memory: {e!r}", file=sys.stderr)


def _caption_ctx(o: dict) -> dict:
    """The moment under a caption, read the way make.plain_lines chose its
    line: the stop (beat) it sits in -- its first shots' labels together,
    its first time and place -- not only the shot under its first frame
    (shots inside a stop are reordered after the lines are written)."""
    where = "title" if o.get("kind") == "title" else "stop"
    entries = overlays._entries(SESSION.board or {})
    beat = next((bid for bid, _k, a, z in entries if a <= float(o.get("start", 0.0)) < z), None)
    cat = CATALOG["cat"]
    shots = [cat.shots.get(k.split("~")[0]) for bid, k, _a, _z in entries if bid == beat] if cat and beat else []
    shots = [s_ for s_ in shots if s_ is not None]
    if not shots:
        return captionmem.context([], None, None, where)
    labels: dict[str, float] = {}
    for s_ in shots[:4]:
        for k, v in (s_.labels or {}).items():
            labels[k] = max(labels.get(k, 0.0), float(v))
    when = min((s_.when for s_ in shots if s_.when), default=None)
    gps = next((s_.gps for s_ in shots if s_.gps), None)
    place = places.name_at(gps, places.cached([gps])) if gps else None
    fmt = ((PROJECT["p"].brief or {}).get("style") or {}).get("format") if PROJECT["p"] is not None else None
    return captionmem.context(labels, when, place, where, fmt)


class OpsReq(BaseModel):
    ops: list[dict]
    label: str


@app.post("/api/ops")
def api_ops(req: OpsReq) -> dict:
    """Direct manipulation (Apply, timeline drag/delete) -- same log, same undo."""
    with LOCK:
        before = {o["id"]: o for o in overlays.resolve(SESSION.board)} if SESSION.board else {}
        SESSION.add({"kind": "direct", "text": req.label, "ops": req.ops},
                    CATALOG["cat"], _make_proposals)
        _caption_memory(req.ops, before)
        for o in req.ops:   # picks made by hand follow the creator to the next video
            if o.get("op") == "set_look" and o.get("look"):
                defaults.note(look=o["look"])
            if o.get("op") == "edit_overlay" and isinstance(o.get("text"), str) and o["text"].strip():
                habits.remember_phrase(o["text"])   # how they phrase things, for the writer
            if o.get("op") == "overlay_style" and o.get("source") != "defaults":
                defaults.note(**{f"caption_{k}": o[k] for k in ("template", "enter") if k in o})
        if [o.get("op") for o in req.ops] == ["choose_option"]:
            _drop_repeats()
            _words_as_asked()
            _bed_start()
        return _session()


# --------------------------------------------------------------------------
# the bed: music by default, cuts on its beat (bed.py)
# --------------------------------------------------------------------------

BED: dict = {"job": None}
BED_TEXT = "Music and the beat"


def _bed_start(force: bool = False) -> None:
    """A story was just chosen: find a track and put the cuts on its beat, as
    one undoable turn that lands when the pick is ready (online it can take
    a minute). Not for a Remix (has its own), a talking-head cut or a
    voiceover story (the voice sets time), nor when music is already under
    the edit -- unless the Music switch asks (`force`)."""
    b = SESSION.board
    if not b or os.environ.get("VIBECUT_BED", "1") == "0":   # VIBECUT_BED=0: tests that must not go online
        return
    if not force:
        if b.get("option") in ("remix", "talk") or b.get("music") is not None:
            return
        if any(bt.get("line") for bt in b["beats"]):
            return
    job = BED["job"]
    if job and job.stage == "looking":
        return
    pr = PROJECT["p"]
    pace = ((pr.brief or {}).get("style") or {}).get("pace") if pr else None
    own = musiclib.STATE["tracks"] if musiclib.STATE["status"] == "ready" else None
    need_s = timeline.build(b, CLIPS, None)["total"]
    talking = tempo.talking(list(CLIPS.values()), _pool())
    board = copy.deepcopy(b)

    def on_done(job: bed.Job) -> None:
        with LOCK:
            if PROJECT["p"] is pr and pr is not None:
                pr.events.append({"kind": "bed", "at": time.time(), "stage": job.stage, "why": job.why,
                                  "source": job.source, "elapsed": round(time.time() - job.started, 1)})
        if job.stage != "done" or not job.result:
            _save()
            return
        with LOCK:
            if BED["job"] is not job or SESSION.board is None:
                return
            if SESSION.board.get("music") is not None and not force:
                job.stage, job.why = "nothing", "Music was put under the edit meanwhile; kept yours."
                return
            mx = job.result["music"]
            t = mx["track"]
            if not any(x.id == t.id for x in musiclib.STATE["tracks"]):
                musiclib.STATE["tracks"].append(t)
            musiclib.use(t.id)
            SESSION.add({"kind": "direct", "text": BED_TEXT, "ops": job.result["ops"],
                         "reply": job.result["reply"]}, CATALOG["cat"], _make_proposals)
            _songs_set(mx, None, None, SESSION.board.get("look") if SESSION.board else None, None)
        _save()

    BED["job"] = bed.start(board, CATALOG["cat"], pace, own, need_s, talking, on_done)


class BedReq(BaseModel):
    on: bool


@app.post("/api/bed")
def api_bed(req: BedReq) -> dict:
    """The Music switch in Frames. Off: one undoable turn that takes the bed
    away (the cuts stay where the beat put them). On: find a track again."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Choose a story first.")
        defaults.note(music="on" if req.on else "off")
        if req.on:
            _bed_start(force=True)
        else:
            musiclib.use(None)
            SESSION.add({"kind": "direct", "text": "No music",
                         "ops": [{"op": "set_music", "track": None}],
                         "reply": "Music off — the edit plays with its own sound. Undo puts the track back."},
                        CATALOG["cat"], _make_proposals)
        return _session()


def _words_as_asked(force: bool = False) -> None:
    """A story was just chosen: put on screen the words the style questions
    asked for, as their own turn so Undo takes only the words away. `force`
    (the Captions switch in Frames) puts captions on even if none were asked."""
    b = SESSION.board
    d = _direction() or {}
    style = d.get("style") or {}
    answer = style.get("captions")
    if force and answer not in ("describe", "transcribe"):
        answer = "describe"
    if not b or b.get("overlays") or (b.get("look") and not force) or not (d or force):
        return
    said = (d.get("text") or "").split("\n")[0].strip()
    found = places.lookup([c.get("gps") for c in CLIPS.values()]) if answer in ("describe", None, "day") else {}
    ops, notes = brief.caption_ops(b, CATALOG["cat"], answer, said if len(said) <= 48 else None, said,
                                   look=style.get("look") or style.get("caption_look"), clips=CLIPS, places=found)
    if not ops:
        return
    n = sum(o["op"] == "add_overlay" for o in ops)
    what = {"transcribe": "subtitles of what's said", "none": "words"}.get(answer or "", "captions: the time, the place and what's happening")
    reply = (f"Added {n} caption{'s' * (n != 1)} — {what}. Click one to retype it." if n
             else f"The {looks.get(ops[0]['look'])['name']} look, as you picked.")
    if notes:
        reply += " " + " ".join(notes)
    SESSION.add({"kind": "direct", "text": "Captions, as you asked", "ops": ops, "reply": reply},
                CATALOG["cat"], _make_proposals)


@app.post("/api/turns/{tid}/toggle")
def api_toggle(tid: int) -> dict:
    with LOCK:
        SESSION.toggle(tid, CATALOG["cat"], _make_proposals)
        return _session()


# --------------------------------------------------------------------------
# talking-head mode (口播): transcribe on this Mac, cut pauses and retakes,
# a gate to review every cut, then a storyboard with subtitles
# --------------------------------------------------------------------------

TALK: dict = {"plan": None, "job": None}


class TalkReq(BaseModel):
    locale: str = "zh-CN"
    script: str = ""
    clips: list[str] | None = None


def _talk_clips(ids: list[str] | None) -> list[dict]:
    rejected, _ = cut.for_story(PLAN["plan"])
    pool = [c for c in CLIPS.values() if (c["id"] in ids if ids else c["id"] not in rejected)]
    return sorted(pool, key=lambda c: (storyboard.parse_when(c.get("capture_time")) or storyboard.datetime.max, c["name"]))


@app.post("/api/talk")
def api_talk(req: TalkReq) -> dict:
    if not CLIPS:
        raise HTTPException(400, "drop some clips in first")
    if req.locale not in speech.LOCALES:
        raise HTTPException(400, f"language must be one of {', '.join(speech.LOCALES)}")
    job = TALK["job"]
    if job and job["stage"] in ("transcribing", "reviewing"):
        raise HTTPException(409, "already transcribing")
    clips = _talk_clips(req.clips)
    job = {"stage": "transcribing", "done": 0, "total": len(clips), "current": "", "error": None, "silent": []}
    TALK["job"] = job

    def work() -> None:
        try:
            transcripts, levels, used = {}, {}, {}
            for c in clips:
                job["current"] = c["name"]
                try:
                    res = speech.transcribe(c, req.locale)
                except speech.SpeechError as e:
                    if "no sound" in str(e):
                        res = []
                    else:
                        raise
                if res:
                    transcripts[c["id"]] = res
                    levels[c["id"]] = talk.active(speech.audio(c))
                    used[c["id"]] = c
                else:
                    job["silent"].append(c["name"])
                job["done"] += 1
            if not transcripts:
                raise speech.SpeechError("No speech found in these clips — is the language right?")
            job["stage"] = "reviewing"
            agent = llm.review_talk if llm.available() else None
            plan = talk.build(transcripts, used, req.locale, levels, req.script, agent)
            with LOCK:
                TALK["plan"] = plan
            job["stage"] = "done"
        except Exception as e:  # noqa: BLE001 -- shown at the gate
            job["stage"], job["error"] = "error", str(e)

    threading.Thread(target=work, daemon=True).start()
    return {"job": job, "plan": None, "llm": llm.available()}


@app.get("/api/talk")
def api_talk_state() -> dict:
    with LOCK:
        p = TALK["plan"]
        return {"job": TALK["job"], "plan": talk.public(p) if p else None, "llm": llm.available()}


class TalkToggleReq(BaseModel):
    id: str


@app.post("/api/talk/toggle")
def api_talk_toggle(req: TalkToggleReq) -> dict:
    """Put a cut back, or take something out -- the creator's call at the gate."""
    with LOCK:
        if not TALK["plan"]:
            raise HTTPException(400, "nothing transcribed yet")
        try:
            talk.toggle(TALK["plan"], req.id)
        except KeyError as e:
            raise HTTPException(404, f"no item {req.id}") from e
        return {"job": TALK["job"], "plan": talk.public(TALK["plan"]), "llm": llm.available()}


class TalkApplyReq(BaseModel):
    captions: bool = True
    profile: dict = {}


@app.post("/api/talk/apply")
def api_talk_apply(req: TalkApplyReq) -> dict:
    """The reviewed cut becomes the working storyboard -- one turn, undoable."""
    with LOCK:
        p = TALK["plan"]
        if not p:
            raise HTTPException(400, "nothing transcribed yet")
        snap = talk.board(p, captions=req.captions, style=overlays.style_from_profile(req.profile) or None)
        if not snap["beats"]:
            raise HTTPException(409, "Everything was cut — put something back first.")
        s = talk.public(p)["summary"]
        SESSION.add({"kind": "direct", "text": "You used the talking-head cut",
                     "ops": [{"op": "choose_option", "option": "talk", "snapshot": snap}],
                     "reply": s["line_en"] + (" · subtitles added" if req.captions else "")},
                    CATALOG["cat"], _make_proposals)
        return _session()


# --------------------------------------------------------------------------
# words on screen: suggested from what the edit knows, then edited like shots
# --------------------------------------------------------------------------

class SuggestReq(BaseModel):
    profile: dict = {}
    title: str | None = None
    kinds: list[str] | None = None


@app.post("/api/overlays/suggest")
def api_overlays_suggest(req: SuggestReq) -> dict:
    """Fill in the overlays the edit is missing. One turn: Undo takes them all away."""
    with LOCK:
        b = SESSION.board
        if not b:
            raise HTTPException(409, "Choose a story first — titles hang off its parts and shots.")
        ops, notes = overlays.suggest(b, CATALOG["cat"], req.profile, req.title, req.kinds)
        style = overlays.style_from_profile(req.profile)
        if style and not b.get("overlay_style"):
            ops.insert(0, {"op": "overlay_style", **style, "source": "profile"})
        if not ops:
            raise HTTPException(409, "Nothing to add — " + (notes[0][0].lower() + notes[0][1:] if notes
                                                              else "every part already has its words."))
        n = sum(o["op"] == "add_overlay" for o in ops)
        reply = f"Added {n} overlay{'s' * (n != 1)} from what the edit already knows."
        if notes:
            reply += " " + " ".join(notes)
        SESSION.add({"kind": "direct", "text": "You asked for titles and labels", "ops": ops, "reply": reply},
                    CATALOG["cat"], _make_proposals)
        return _session()


# --------------------------------------------------------------------------
# export: the edit + its words on screen + music, as one file
# --------------------------------------------------------------------------

class ExportReq(BaseModel):
    music: bool = True
    # "tall" / "wide": the same edit in the other frame, for the other
    # platforms (the Share box's "make a vertical version too"); the
    # project's own frame is unchanged. None = the frame picked up front.
    frame: str | None = None


@app.post("/api/export")
def api_export(req: ExportReq) -> dict:
    """Create an export. The browser then uploads its overlay frames and starts it."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Choose a story first — there's nothing to export yet.")
        tl = timeline.build(SESSION.board, CLIPS, _track())
        track = _track() if req.music else None
        if req.frame not in (None, "tall", "wide"):
            raise HTTPException(400, "frame is tall or wide")
        try:
            # Named after what the video says it is: its title, else the story.
            title = next((o["text"] for o in SESSION.board.get("overlays", []) if o["kind"] == "title"), None) \
                or SESSION.board.get("name", "")
            if req.frame:
                title += " · " + ("vertical" if req.frame == "tall" else "wide")
            job = export.create(looks.camera(tl["items"], SESSION.board), dict(CLIPS), title or SESSION.board.get("name", ""),
                                track.path if track else None, _style(SESSION.board, for_export=True),
                                mix=SESSION.board.get("music"), joins=SESSION.board.get("joins"),
                                want=req.frame or _want(), sound=audiomix.strips_of(SESSION.board),
                                crop=bool(req.frame))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return job.public()


def _job(jid: str) -> export.Job:
    job = export.JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such export")
    return job


@app.post("/api/export/{jid}/frames/{n}")
async def api_export_frame(jid: str, n: int, request: Request) -> dict:
    job = _job(jid)
    try:
        export.save_frame(job, n, await request.body())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


class ExportStartReq(BaseModel):
    schedule: list[dict] = []
    moved: int = 0      # captions the browser moved off faces (a version in the other frame)


@app.post("/api/export/{jid}/start")
def api_export_start(jid: str, req: ExportStartReq) -> dict:
    job = _job(jid)
    if req.moved > 0 and job.stage == "waiting":
        job.notes.append(f"{req.moved} caption{'s' * (req.moved != 1)} moved so {'they don’t' if req.moved != 1 else 'it doesn’t'} "
                         "sit on anyone’s face in this frame.")
    try:
        export.start(job, req.schedule)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
    return job.public()


@app.get("/api/export/{jid}/faces")
def api_export_faces(jid: str) -> dict:
    """Where faces sit in a version's frame, for laying its captions out
    again off them; none for an export in the edit's own frame, whose
    captions are where the creator saw them in the preview."""
    job = _job(jid)
    if not job.alt:
        return {"faces": []}
    return {"faces": export.face_areas(job)}


@app.get("/api/export/{jid}")
def api_export_status(jid: str) -> dict:
    job = _job(jid)
    pub = job.public()
    # A finished export is part of the project's record: the dashboard and
    # the Export stage list it, and it is how "done" is known after a restart.
    pr = PROJECT["p"]
    if pub["stage"] == "done" and pr is not None and not any(e.get("job") == jid for e in pr.exports):
        live = [t for t in SESSION.turns if not t.undone]
        pr.exports.append({"job": jid, "file": pub["file"], "path": pub["path"], "at": time.time(),
                           "seconds": pub["total"], "size": pub["size"], "music": pub["music"],
                           "overlays": pub["overlays"], "bytes": os.path.getsize(pub["path"]) if pub["path"] and os.path.isfile(pub["path"]) else None,
                           # for launchlog.py: how it was made and what it cost
                           "elapsed": pub["elapsed"], "style": pub.get("style"), "alt": pub.get("alt", False),
                           "turns": len(live), "undone": sum(t.undone for t in SESSION.turns),
                           "chat_turns": sum(1 for t in live if t.kind == "chat" and t.ops),
                           "default_path": not any(t.kind == "chat" and t.ops for t in live)})
        # what this video's edits say, for the next one (habits.py)
        habits.record(pr, SESSION.turns, CATALOG["cat"])
        _save()
    return pub


class VerdictReq(BaseModel):
    post: bool
    note: str = ""


@app.post("/api/exports/{n}/verdict")
def api_export_verdict(n: int, req: VerdictReq) -> dict:
    """The one question after an export -- would you post this? -- kept on
    the export's record. It is the launch metric (launchlog.py): a
    completion is an export, a success is a yes."""
    pr = PROJECT["p"]
    if pr is None or not (0 <= n < len(pr.exports)):
        raise HTTPException(404, "no such export")
    with LOCK:
        pr.exports[n]["verdict"] = {"post": req.post, "note": req.note.strip()[:500], "at": time.time()}
        pr.events.append({"kind": "verdict", "at": time.time(), "export": n, "post": req.post})
        return _session()


class SceneReq(BaseModel):
    word: str


@app.post("/api/scenes/{beat}/verdict")
def api_scene_verdict(beat: str, req: SceneReq) -> dict:
    """One word per scene after watching -- keep, cut, longer (vlog.py step
    8). Cut and longer are one undoable turn each, so habits.py hears them
    as removed / held; every word is kept on the project's record."""
    pr = PROJECT["p"]
    with LOCK:
        if SESSION.board is None:
            raise HTTPException(409, "Make a video first.")
        try:
            ops, text, rec = vlog.verdict_ops(SESSION.board, CATALOG["cat"], beat, req.word.strip().lower())
        except ValueError as e:
            raise HTTPException(400, str(e))
        if ops:
            SESSION.add({"kind": "direct", "text": text, "ops": ops, "reply": text + "."}, CATALOG["cat"], _make_proposals)
        if pr is not None:
            pr.events = [e for e in pr.events if not (e.get("kind") == "scene_verdict" and e.get("beat") == beat)]
            pr.events.append({**rec, "at": time.time()})
        return _session()


@app.get("/api/exports/{n}/file")
def api_export_saved_file(n: int) -> FileResponse:
    """A past export of the open project, by its index in the list."""
    pr = PROJECT["p"]
    if pr is None or n < 0 or n >= len(pr.exports):
        raise HTTPException(404)
    path = pr.exports[n].get("path")
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "that file is no longer where it was saved")
    return FileResponse(path, media_type="video/mp4", filename=Path(path).name)


@app.post("/api/export/{jid}/cancel")
def api_export_cancel(jid: str) -> dict:
    job = _job(jid)
    job.cancel = True
    if job.stage == "waiting":
        job.stage = "cancelled"
    return job.public()


@app.get("/api/export/{jid}/file")
def api_export_file(jid: str) -> FileResponse:
    job = _job(jid)
    if job.stage != "done" or not job.path or not os.path.isfile(job.path):
        raise HTTPException(404, "not finished")
    return FileResponse(job.path, media_type="video/mp4", filename=Path(job.path).name)


@app.post("/api/export/{jid}/photos")
def api_export_photos(jid: str) -> dict:
    """Save to Photos (macOS): the file goes into the Photos library through
    AppleScript, where AirDrop and the phone find it. Elsewhere: 409 and why."""
    job = _job(jid)
    if job.stage != "done" or not job.path:
        raise HTTPException(404, "not finished")
    if sys.platform != "darwin":
        raise HTTPException(409, "Save to Photos needs a Mac; the file is in your exports folder.")
    script = f'tell application "Photos" to import POSIX file "{job.path}"'
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise HTTPException(500, "Photos didn't take it: " + (p.stderr.strip()[-200:] or "unknown error"))
    _shared(jid, "photos")
    return {"ok": True}


@app.post("/api/export/{jid}/reveal")
def api_export_reveal(jid: str) -> Response:
    job = _job(jid)
    if job.stage != "done" or not job.path:
        raise HTTPException(404, "not finished")
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", job.path])
        _shared(jid, "finder")
    return Response(status_code=204)


def _shared(jid: str, how: str) -> None:
    """A share is on the project's record (kind "share"), against the export
    it moved on, so launchlog.py counts shares next to "would you post this?"."""
    pr = PROJECT["p"]
    if pr is None:
        return
    with LOCK:
        n = next((k for k, e in enumerate(pr.exports) if e.get("job") == jid), None)
        pr.events.append({"kind": "share", "how": how, "export": n, "at": time.time()})
    _save()


@app.get("/api/export/{jid}/share")
def api_export_share(jid: str) -> dict:
    """Where this file can go next: one button per platform, each checked
    against the file's frame and length (share.py). Nothing is posted --
    a button copies the caption and opens the platform's own upload page."""
    job = _job(jid)
    if job.stage != "done" or not job.path:
        raise HTTPException(404, "not finished")
    w, h = (job.size or {}).get("w", 0), (job.size or {}).get("h", 0)
    rec = _export_rec(jid)
    return {"shape": share.shape(w, h), "seconds": round(job.total, 2), "platforms": share.targets(w, h, job.total),
            "mac": sys.platform == "darwin",
            # words to post with it (postcopy.py) and the licence's credit, kept apart
            "post": _post_words(job), "credit": _credit(job),
            "covers": [{"t": t, "url": f"/api/export/{jid}/still/{int(round(t * 1000))}"} for t in covers.candidates(job.items)],
            # the same edit in the other frame, one click away
            "other": share.other_version(w, h, job.total, job.alt),
            "cover": _cover_public(jid, rec)}


def _export_rec(jid: str) -> dict | None:
    pr = PROJECT["p"]
    return next((e for e in pr.exports if e.get("job") == jid), None) if pr else None


def _is_short(job: export.Job) -> bool:
    w, h = (job.size or {}).get("w", 0), (job.size or {}).get("h", 0)
    return share.fit("youtube", w, h, job.total)["name"] == "YouTube Shorts"


def _post_words(job: export.Job) -> dict:
    with LOCK:
        ovs = overlays.resolve(SESSION.board)
    return postcopy.draft(job.items, job.clips, ovs, job.total, _is_short(job))


def _credit(job: export.Job) -> str | None:
    return (_music_public() or {}).get("credit") if job.music else None   # the licence asks for it


def _cover_public(jid: str, rec: dict | None) -> dict | None:
    c = (rec or {}).get("cover")
    if not c or not os.path.isfile(c.get("path") or ""):
        return None
    return {"t": c["t"], "file": Path(c["path"]).name, "url": f"/api/export/{jid}/cover?v={int(c['t'] * 1000)}"}


@app.get("/api/export/{jid}/still/{ms}")
def api_export_still(jid: str, ms: int) -> FileResponse:
    """A small frame of the exported file, for the cover picker."""
    job = _job(jid)
    if job.stage != "done" or not job.path or not 0 <= ms <= job.total * 1000:
        raise HTTPException(404)
    try:
        return FileResponse(covers.still(job.path, jid, ms / 1000), media_type="image/jpeg")
    except ValueError as e:
        raise HTTPException(500, str(e)) from e


class CoverReq(BaseModel):
    t: float


@app.post("/api/export/{jid}/cover")
def api_export_cover(jid: str, req: CoverReq) -> dict:
    """The creator's cover: that frame of the file, full size, saved beside
    it (covers.py) and kept on the export's record for YouTube."""
    job = _job(jid)
    if job.stage != "done" or not job.path:
        raise HTTPException(404, "not finished")
    if not 0 <= req.t <= job.total:
        raise HTTPException(400, "That moment isn't in the video.")
    try:
        dest = covers.save(job.path, jid, req.t)
    except (ValueError, OSError) as e:
        raise HTTPException(500, str(e)) from e
    rec = _export_rec(jid)
    if rec is not None:
        with LOCK:
            rec["cover"] = {"t": round(req.t, 3), "path": str(dest)}
    else:
        rec = {"cover": {"t": round(req.t, 3), "path": str(dest)}}
    return _cover_public(jid, rec)


@app.get("/api/export/{jid}/cover")
def api_export_cover_file(jid: str) -> FileResponse:
    c = (_export_rec(jid) or {}).get("cover")
    if not c or not os.path.isfile(c.get("path") or ""):
        raise HTTPException(404, "no cover chosen")
    return FileResponse(c["path"], media_type="image/jpeg", filename=Path(c["path"]).name)


class SharedReq(BaseModel):
    how: str


@app.post("/api/export/{jid}/shared")
def api_export_shared(jid: str, req: SharedReq) -> dict:
    """What the browser did with the file (download, the share sheet, a
    platform's page, the caption copied), for the record only."""
    job = _job(jid)
    if job.stage != "done" or not job.path:
        raise HTTPException(404, "not finished")
    if req.how not in share.HOWS or req.how in share.SERVER_HOWS:
        raise HTTPException(400, f"unknown share: {req.how}")
    _shared(jid, req.how)
    return {"ok": True}


# --------------------------------------------------------------------------
# posting to YouTube: the creator's own channel, one confirmed post at a time
# --------------------------------------------------------------------------

# Single-use codes from the confirm screen: code -> (export job, when).
# A post must carry one, so nothing reaches YouTube that the creator didn't
# see (title, channel, who can see it) and press Post on.
YT_CONFIRMS: dict[str, tuple[str, float]] = {}
YT_CONFIRM_S = 60 * 60


def _yt(fn, *a):
    try:
        return fn(*a)
    except youtube.YouTubeError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/youtube")
def api_youtube() -> dict:
    return youtube.status()


@app.post("/api/youtube/connect")
def api_youtube_connect() -> dict:
    """Google's sign-in page for the creator to open; the answer comes back
    to a one-time listener on this Mac (youtube.py)."""
    return {"url": _yt(youtube.connect)}


@app.post("/api/youtube/disconnect")
def api_youtube_disconnect() -> dict:
    youtube.disconnect()
    return youtube.status()


@app.post("/api/export/{jid}/youtube/prepare")
def api_youtube_prepare(jid: str) -> dict:
    """What the confirm screen shows -- the channel it would land on, the
    title and description to start from, whether it will be a Short -- and
    the single-use code its Post button carries."""
    job = _job(jid)
    if job.stage != "done" or not job.path:
        raise HTTPException(404, "not finished")
    if not youtube.status()["connected"]:
        raise HTTPException(409, "Connect your YouTube channel first.")
    ch = _yt(youtube.channel)
    if not ch:
        raise HTTPException(409, "This Google account has no YouTube channel yet. Make one on youtube.com, then connect again.")
    now = time.time()
    for k, (_, at) in list(YT_CONFIRMS.items()):
        if now - at > YT_CONFIRM_S:
            YT_CONFIRMS.pop(k, None)
    code = secrets.token_urlsafe(16)
    YT_CONFIRMS[code] = (jid, now)
    w, h = (job.size or {}).get("w", 0), (job.size or {}).get("h", 0)
    yt = _post_words(job)["youtube"]
    credit = _credit(job)
    clean = lambda x: x.replace("<", "").replace(">", "")  # noqa: E731 -- YouTube refuses both
    short = _is_short(job)
    cover = _cover_public(jid, _export_rec(jid))
    return {"confirm": code, "channel": ch, "title": clean(yt["title"])[:youtube.TITLE_MAX],
            "description": clean(yt["description"] + (f"\n\nMusic: {credit}" if credit else "")),
            "fit": share.fit("youtube", w, h, job.total), "seconds": round(job.total, 2), "file": Path(job.path).name,
            # the cover goes with the post (not for a Short: YouTube picks those in its app)
            "cover": {**cover, "sent": not short} if cover else None}


class YouTubePostReq(BaseModel):
    confirm: str
    title: str
    description: str = ""
    privacy: str
    made_for_kids: bool | None = None
    cover_t: float | None = None      # the cover the confirm screen showed; None = none


@app.post("/api/export/{jid}/youtube")
def api_youtube_post(jid: str, req: YouTubePostReq) -> dict:
    """Post this export to the creator's channel. Only with the code from
    this export's confirm screen, once."""
    job = _job(jid)
    if job.stage != "done" or not job.path:
        raise HTTPException(404, "not finished")
    held = YT_CONFIRMS.get(req.confirm)
    if not held or held[0] != jid or time.time() - held[1] > YT_CONFIRM_S:
        raise HTTPException(409, "Open the YouTube confirm screen for this video and press Post there.")
    try:
        meta = youtube.check_meta(req.title, req.description, req.privacy, req.made_for_kids)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    YT_CONFIRMS.pop(req.confirm, None)
    pr = PROJECT["p"]
    w, h = (job.size or {}).get("w", 0), (job.size or {}).get("h", 0)
    short = share.fit("youtube", w, h, job.total)["name"] == "YouTube Shorts"

    def landed(post: youtube.Post) -> None:
        # on the project's record: a share event, and the post on its export
        if pr is None or post.stage != "done":
            return
        with LOCK:
            n = next((k for k, e in enumerate(pr.exports) if e.get("job") == jid), None)
            rec = {"platform": "youtube", "video": post.video, "privacy": post.privacy, "asked": req.privacy,
                   "short": short, "cover": post.cover_state, "at": time.time()}
            pr.events.append({"kind": "share", "how": "youtube_post", "export": n, "at": rec["at"],
                              "video": post.video, "privacy": post.privacy})
            if n is not None:
                pr.exports[n].setdefault("posted", []).append(rec)
        if PROJECT["p"] is pr:
            _save()
        else:
            pj.save(pr)

    # only the cover the creator saw on the confirm screen goes with the post
    c = (_export_rec(jid) or {}).get("cover")
    if not c or req.cover_t is None or abs(c["t"] - req.cover_t) > 0.01:
        c = None
    post = _yt(youtube.start, job.path, meta, short, landed, c["path"] if c and os.path.isfile(c["path"]) else None)
    return post.public()


@app.get("/api/youtube/posts/{pid}")
def api_youtube_post_status(pid: str) -> dict:
    post = youtube.POSTS.get(pid)
    if not post:
        raise HTTPException(404, "no such post")
    return post.public()


@app.post("/api/youtube/posts/{pid}/stop")
def api_youtube_post_stop(pid: str) -> dict:
    """Stop between chunks; an upload that never finishes leaves nothing on YouTube."""
    post = youtube.POSTS.get(pid)
    if not post:
        raise HTTPException(404, "no such post")
    if post.stage == "uploading":
        post.stop = True
    return post.public()


# --------------------------------------------------------------------------
# music: tracks from the creator's own folder that fit the storyboard's shape
# --------------------------------------------------------------------------

class MusicFolderReq(BaseModel):
    folder: str | None


@app.post("/api/music/folder")
def api_music_folder(req: MusicFolderReq) -> dict:
    try:
        return musiclib.set_folder(req.folder)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class MusicUseReq(BaseModel):
    track_id: str | None


@app.post("/api/music/use")
def api_music_use(req: MusicUseReq) -> dict:
    """Put a track under the edit -- its beat grid becomes snap targets."""
    try:
        musiclib.use(req.track_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    with LOCK:
        if SESSION.board is not None:
            # On the board, so it's in the log: undoable, and a Remix's own
            # mix (in-point, levels) is replaced rather than silently kept.
            t = musiclib.current()
            SESSION.add({"kind": "direct", "text": f"Music: {t.title}" if t else "No music",
                         "ops": [{"op": "set_music", "track": req.track_id}]}, CATALOG["cat"], _make_proposals)
        return _session()


@app.get("/api/music/suggest")
def api_music_suggest() -> dict:
    with LOCK:
        return musiclib.suggest(SESSION.board, CATALOG["cat"])


@app.get("/api/music/audio/{track_id}")
def api_music_audio(track_id: str) -> FileResponse:
    p = musiclib.path_for(track_id)  # only known tracks: the chosen folder, or VibeCut's own music cache
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


# --------------------------------------------------------------------------
# songs to swap between, transition sounds, a trending sound (songs.py,
# sfx.py, trend.py; the user, 2026-10-24)
# --------------------------------------------------------------------------

SONGS: dict = {"list": [], "remake": None, "make_turn": None, "look": None, "fmt": None, "extra": [],
               "project": None, "job": None, "why": None, "trend": None}
SONG_TEXT = "Song: "


def _songs_set(mx: dict | None, remake: dict | None, make_turn: int | None, look: str | None, fmt: str | None,
               extra: list[dict] | None = None) -> None:
    """Keep the ranked songs a Make or the bed found, best first."""
    lst = ([mx] + list(mx.get("others") or [])) if mx else []
    for x in lst:
        if not any(t.id == x["track"].id for t in musiclib.STATE["tracks"]):
            musiclib.STATE["tracks"].append(x["track"])     # so the panel can play it (/api/music/audio)
    SONGS.update(list=lst, remake=remake, make_turn=make_turn, look=look, fmt=fmt, extra=list(extra or []),
                 project=getattr(PROJECT["p"], "id", None), why=None)


def _fmt_now() -> str:
    pr = PROJECT["p"]
    return (((pr.brief or {}).get("style") or {}).get("format") if pr else None) or SONGS.get("fmt") or "tall"


def _made_untouched() -> bool:
    """The video is as Make left it: since its turn only the app's own turns
    (a profile's redress, the vlog's nudge, earlier song swaps)."""
    mt = SONGS.get("make_turn")
    if mt is None or not SESSION.board or SESSION.board.get("option") != "made":
        return False
    make_turn = next((t for t in SESSION.turns if t.id == mt), None)
    if make_turn is None or make_turn.undone:
        return False
    return all(t.undone or not t.ops or t.text in REDRESS or t.text == "Smoother cuts" or t.text.startswith(SONG_TEXT)
               for t in SESSION.turns if t.id > mt)


def _vlog_board() -> bool:
    """A made vlog: its cuts follow the action, so a new song only moves the music."""
    b = SESSION.board or {}
    fp = (SONGS.get("remake") or {}).get("fp") or {}
    return b.get("option") == "made" and _fmt_now() != "short" and not fp.get("refs_used")


def _rank_now() -> None:
    """Rank songs for the board as it is (no Make or bed result to read from)."""
    b = copy.deepcopy(SESSION.board)
    pr = PROJECT["p"]
    pace = ((pr.brief or {}).get("style") or {}).get("pace") if pr else None
    own = musiclib.STATE["tracks"] if musiclib.STATE["status"] == "ready" else None
    need_s = timeline.build(b, CLIPS, None)["total"]
    cat, look = CATALOG["cat"], b.get("look")

    def run() -> None:
        try:
            fp = bed.fingerprint(b, cat, pace)
            pool, source = bed.candidates(fp["pace"], own)
            mx = bed.pick(fp, pool, need_s, look)
            with LOCK:
                _songs_set(mx, SONGS.get("remake"), SONGS.get("make_turn"), look, SONGS.get("fmt"), SONGS.get("extra"))
                SONGS["why"] = None if mx else f"None of the {len(pool)} songs fits this edit's length with a steady beat."
        except Exception as e:  # noqa: BLE001 -- the panel says so
            SONGS["why"] = f"Couldn't look for songs: {str(e)[:160]}"
        finally:
            SONGS["job"] = None

    SONGS["job"] = "looking"
    threading.Thread(target=run, daemon=True).start()


@app.get("/api/music/options")
def api_music_options() -> dict:
    """The songs that fit this edit, best first, to listen to and swap; the
    one under the video marked. Looked for in the background when there's
    no list for this video yet."""
    with LOCK:
        if not SESSION.board:
            return {"status": "none", "songs": []}
        cur = ((SESSION.board.get("music") or {}).get("track"))
        mine = SONGS.get("project") == getattr(PROJECT["p"], "id", None)
        if (not SONGS["list"] or not mine) and SONGS.get("job") is None and SESSION.board.get("music") is not None:
            SONGS["list"] = []
            _rank_now()
        taste = songs.load()
        return {"status": "looking" if SONGS.get("job") else "ready" if SONGS["list"] else "none",
                "songs": [songs.public(x, SONGS.get("look"), cur, taste) for x in SONGS["list"]] if mine or SONGS["list"] else [],
                "why": SONGS.get("why"), "rebuilds": _made_untouched() and not _vlog_board(),
                "sfx": len((SESSION.board.get("music") or {}).get("sfx") or []),
                "sounds": sfxpack_public(), "trend": SONGS.get("trend"),
                "can_link": bool(trend.ytdlp())}


def sfxpack_public() -> list[dict]:
    from cutgrammar import sfxpack
    return sfxpack.public()


def _swap_ops(mx: dict, guide: bool = False) -> tuple[list[dict], str]:
    """The ops that put `mx` under the video, and what changed. Untouched
    since Make and not a vlog: the video is made again on the new song's
    beat (the same moments, the same changes the taste model kept). A made
    vlog: only the music moves (its cuts follow the action). Otherwise: the
    cuts move onto the new beat, as the Music switch does."""
    b = SESSION.board
    cur = dict(b.get("music") or {})
    fmt = _fmt_now()
    rk = SONGS.get("remake")
    if rk and _made_untouched() and not _vlog_board() and mx.get("drop") is not None:
        from . import tastepick
        made = tastepick.build(rk.get("chosen") or [{"name": "today"}], rk["raw"], rk["clips"], rk["fp"], mx, fmt,
                               rk["look"], rk["about"], rk["talking"], rk.get("lines"))
        if made is not None:
            plan, vmx, ops = made
            if cur.get("sfx") and not guide:
                make.with_sounds(ops, rk["clips"], vmx, fmt, rk["fp"])
            if guide:
                for op in ops:
                    if op.get("op") == "set_music":
                        op["guide"], op["sfx"] = True, []
            return ops + copy.deepcopy(SONGS.get("extra") or []), "made again on its beat"
    if _vlog_board():
        op = {"op": "set_music", **{k: v for k, v in cur.items() if k in bd.MUSIC_KEYS}, "track": mx["track"].id,
              "in": mx["in"]}
        if guide:
            op["guide"], op["sfx"] = True, []
        else:
            op.pop("guide", None)
        return [op], "the cuts stay where they are"
    talking = tempo.talking(list(CLIPS.values()), _pool())
    ops, _rep = bed.ops(copy.deepcopy(b), CATALOG["cat"], mx, talking)
    for op in ops:
        if op.get("op") == "set_music":
            for k in ("gain", "original", "level"):
                if k in cur:
                    op[k] = cur[k]
            if guide:
                op["guide"], op["sfx"] = True, []
    if not guide and cur.get("sfx"):
        trial = copy.deepcopy(b)
        for op in ops:
            trial, _ = bd.apply(trial, op, CATALOG["cat"], None, new_id=lambda: "trial")
        m = next(op for op in ops if op.get("op") == "set_music")
        m["sfx"] = sfx.place(trial, CLIPS, mx, False)
    return ops, "the cuts moved onto its beat"


class SwapReq(BaseModel):
    track_id: str


@app.post("/api/music/swap")
def api_music_swap(req: SwapReq) -> dict:
    """Put another of the suggested songs under the video, as one undoable
    turn; the pick teaches the music taste (songs.remember)."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Choose a story first.")
        mx = next((x for x in SONGS["list"] if x["track"].id == req.track_id), None)
        if mx is None:
            raise HTTPException(404, "That song isn't one of the suggestions any more — look again.")
        before = _track()
        ops, how = _swap_ops(mx)
        musiclib.use(mx["track"].id)
        t = mx["track"]
        SESSION.add({"kind": "direct", "text": SONG_TEXT + t.title, "ops": ops,
                     "reply": f"Now playing {t.title} ({round(mx['bpm'])} BPM): {how}."
                              + (f" Undo brings back {before.title}." if before else "")},
                    CATALOG["cat"], _make_proposals)
        if ops and ops[0].get("op") == "choose_option":
            PREFER["deck"] = None          # the cards were cut on the old song
        songs.remember(t, [x["track"] for x in SONGS["list"]])
        if PROJECT["p"] is not None:
            PROJECT["p"].events.append({"kind": "song_swap", "at": time.time(), "to": t.id,
                                        "from": before.id if before else None, "rank": SONGS["list"].index(mx),
                                        "of": len(SONGS["list"]), "remade": how.startswith("made")})
        return _session()


class SfxReq(BaseModel):
    on: bool


@app.post("/api/sfx")
def api_sfx(req: SfxReq) -> dict:
    """Transition sounds on or off (sfx.py), as one undoable turn; remembered
    for the next video."""
    with LOCK:
        b = SESSION.board
        if not b or not (b.get("music") or {}).get("track"):
            raise HTTPException(409, "Transition sounds ride on the music — put a song under the video first.")
        cur = dict(b["music"])
        if cur.get("guide") and req.on:
            raise HTTPException(409, "With a trending sound the file goes out without music, so there are no transition sounds.")
        defaults.note(sfx="on" if req.on else "off")
        mx = next((x for x in SONGS["list"] if x["track"].id == cur["track"]), None)
        items = sfx.place(b, CLIPS, mx, _vlog_board()) if req.on else []
        op = {"op": "set_music", **{k: v for k, v in cur.items() if k in bd.MUSIC_KEYS}, "sfx": items}
        SESSION.add({"kind": "direct", "text": "Transition sounds" if req.on else "No transition sounds", "ops": [op],
                     "reply": sfx.say(items) if req.on else "Transition sounds off. Undo puts them back."},
                    CATALOG["cat"], _make_proposals)
        return _session()


class TrendReq(BaseModel):
    source: str


@app.post("/api/music/trend")
def api_music_trend(req: TrendReq) -> dict:
    """Cut to a trending sound (trend.py): read it, then fit the video to it
    as one undoable turn. The sound plays in the preview to cut by; the
    export goes out without it, saying which sound to add in the app."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Choose a story first.")
        need_s = timeline.build(SESSION.board, CLIPS, None)["total"]
        pid = getattr(PROJECT["p"], "id", None)

    def on_done(job: trend.Job) -> None:
        with LOCK:
            SONGS["trend"] = job.public()
            if job.stage != "done" or job.track is None or getattr(PROJECT["p"], "id", None) != pid or not SESSION.board:
                return
            t = job.track
            if not any(x.id == t.id for x in musiclib.STATE["tracks"]):
                musiclib.STATE["tracks"].append(t)
            items = SESSION.board.get("beats", [])
            hook_s = next((float(e["end"]) - float(e["start"]) for bt in items for e in bt.get("shots", []) if not e.get("gap")), 2.0)
            fp = bed.fingerprint(copy.deepcopy(SESSION.board), CATALOG["cat"], None)
            fp = {**fp, "bpm": (float(t.bpm) * 0.8, float(t.bpm) * 1.25)}
            got = remix.rank_from([t], fp, min(need_s, max(4.0, t.duration - 9.0)), hook_s, 1)
            if got:
                mx = got[0]
            else:
                bpm = float(t.bpm)
                mx = {"track": t, "in": 0.0, "drop": None, "bpm": bpm, "period": 60.0 / bpm, "score": 0.0, "credit": None}
            ops, how = _swap_ops(mx, guide=True)
            musiclib.use(t.id)
            short = t.duration < need_s - 1
            SESSION.add({"kind": "direct", "text": SONG_TEXT + t.title, "ops": ops,
                         "reply": f"Cut to {t.title} ({round(mx['bpm'])} BPM): {how}. It plays here so you can cut by ear; "
                                  f"the export goes out without it — add it in TikTok or Instagram when you post, starting at "
                                  f"{int(mx['in']) // 60}:{int(mx['in']) % 60:02d}."
                                  + (f" The sound is {t.duration:.0f} s and the video {need_s:.0f} s." if short else "")},
                        CATALOG["cat"], _make_proposals)
            if PROJECT["p"] is not None:
                PROJECT["p"].events.append({"kind": "trend_sound", "at": time.time(), "bpm": round(mx["bpm"]),
                                            "source": "link" if trend.is_url(req.source) else "file"})
        _save()

    try:
        job = trend.start(req.source, on_done)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    SONGS["trend"] = job.public()
    return job.public()


@app.get("/api/music/trend/{jid}")
def api_music_trend_job(jid: str) -> dict:
    job = trend.JOBS.get(jid)
    if job is None:
        raise HTTPException(404)
    return {**job.public(), "session": _session() if job.stage in ("done", "error") else None}


# --------------------------------------------------------------------------
# borrow a feeling: learn a reference video's style, apply it as one turn
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# remix: reference reels + the shelf -> one finished short, then the board
# --------------------------------------------------------------------------

class RemixReq(BaseModel):
    refs: list[str]                 # links, or paths on this Mac
    title: str | None = None
    sub: str | None = None
    length: float | None = None
    name: str | None = None


@app.post("/api/remix")
def api_remix_start(req: RemixReq) -> dict:
    with LOCK:
        if not CLIPS:
            raise HTTPException(409, "Drop your clips in first — the remix is made from them.")
        refs = [r.strip() for r in req.refs if r.strip()]
        if not refs:
            raise HTTPException(400, "Paste at least one reference link.")
        clips = dict(CLIPS)
        cut_now = cut.for_story(PLAN["plan"]) if PLAN["plan"] else None

    def on_done(job: remix.Job) -> None:
        # the finished remix becomes the working storyboard, one undoable turn,
        # and its track joins the music list so the timeline knows the beat
        with LOCK:
            r = job.result or {}
            if not r:
                return
            mx = r.get("music")
            if mx and not any(t.id == mx["track"].id for t in musiclib.STATE["tracks"]):
                musiclib.STATE["tracks"].append(mx["track"])
            if mx:
                musiclib.use(mx["track"].id)
            # From the home page (the front door, plan step 4) the remix *is*
            # the edit: "Make it" was the creator's decision on the footage, so
            # the gate is passed in their name, and the brief is the reels'
            # own frame and length so the stage reads "story" and the export
            # matches the file they just watched.
            if WORKFLOW.state == GATE:
                WORKFLOW.approve("user", f"remix made from {len(job.refs)} reference(s)")
            pr = PROJECT["p"]
            fp = r.get("fingerprint") or {}
            if pr is not None and not pr.brief:
                pr.brief = {"message": f"A short in the style of {len(job.refs)} reel{'s' * (len(job.refs) != 1)}",
                            "style": {"format": "short" if fp.get("vertical", True) else "wide",
                                      "seconds": float(fp.get("duration") or 30.0), "captions": "none"},
                            "said": f"Remix · {remix.describe(fp)}" if fp else "Remix", "at": time.time()}
            SESSION.add({"kind": "direct", "text": f"Remix in the style of {len(job.refs)} reference(s)",
                         "ops": remix.session_ops(r),
                         "reply": f"{r['plan'].duration:.0f} s, {len(r['plan'].picks)} shots" if r.get("plan") else ""},
                        CATALOG["cat"], _make_proposals)
        _save()

    job = remix.start(refs, clips, cut_now, req.model_dump(), on_done)
    return job.public()


def _remix_job(jid: str) -> remix.Job:
    job = remix.JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such remix")
    return job


@app.get("/api/remix/{jid}")
def api_remix_status(jid: str) -> dict:
    return _remix_job(jid).public()


@app.get("/api/remix/{jid}/file")
def api_remix_file(jid: str) -> FileResponse:
    job = _remix_job(jid)
    if not job.result or not job.result.get("path"):
        raise HTTPException(409, "not finished yet")
    return FileResponse(job.result["path"], media_type="video/mp4", filename=Path(job.result["path"]).name)


@app.get("/api/remix/{jid}/credits")
def api_remix_credits(jid: str) -> FileResponse:
    job = _remix_job(jid)
    if not job.result or not job.result.get("credits"):
        raise HTTPException(409, "not finished yet")
    return FileResponse(job.result["credits"], media_type="text/plain", filename=Path(job.result["credits"]).name)


class RefReq(BaseModel):
    source: str             # a path on this Mac (from /api/locate or /api/upload), or a link


@app.post("/api/references")
def api_ref_start(req: RefReq) -> dict:
    try:
        return reference.start(req.source).public()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/references")
def api_ref_library() -> dict:
    return {"references": reference.library(), "links": reference.ytdlp() is not None}


@app.get("/api/references/jobs/{jid}")
def api_ref_job(jid: str) -> dict:
    job = reference.JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    return job.public()


def _grid() -> dict | None:
    return timeline.build(SESSION.board, CLIPS, _track()).get("grid")


@app.get("/api/references/{rid}")
def api_ref_card(rid: str) -> dict:
    with LOCK:
        b = SESSION.board
        landscape = None
        if b:
            fr = export.frame_size(timeline.layout(b), CLIPS, _want())
            landscape = fr["w"] > fr["h"]
        try:
            out = reference.card(rid, _grid(), landscape)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        out["music"] = reference.music_matches(rid, musiclib.STATE["tracks"])
        out["music_folder"] = musiclib.STATE["status"] == "ready"
        out["has_story"] = b is not None
        return out


class LookReq(BaseModel):
    strength: str = "full"


@app.post("/api/references/{rid}/look")
def api_ref_look(rid: str, req: LookReq) -> dict:
    """Fit the look to the shots in this story; before/after stills to judge it by."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Choose a story first — the look is fitted to its shots.")
        try:
            return reference.fit_look(rid, SESSION.board, CATALOG["cat"], req.strength)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e


class RefApplyReq(BaseModel):
    traits: list[str]
    strength: str = "full"


@app.post("/api/references/{rid}/apply")
def api_ref_apply(rid: str, req: RefApplyReq) -> dict:
    """One direct turn: the diff says what changed, Undo takes all of it back."""
    with LOCK:
        if not SESSION.board:
            raise HTTPException(409, "Choose a story first — a style is applied to an edit.")
        try:
            look = reference.fit_look(rid, SESSION.board, CATALOG["cat"], req.strength) if "look" in req.traits else None
            op = reference.make_op(rid, req.traits, _grid(), look)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        t = SESSION.add({"kind": "direct", "text": f"Borrow the feel of “{op['name']}”", "ops": [op]},
                        CATALOG["cat"], _make_proposals)
        if t.skipped:
            SESSION.turns.remove(t)
            SESSION.replay(CATALOG["cat"], _make_proposals)
            raise HTTPException(400, t.skipped[0])
        return _session()


@app.delete("/api/references/{rid}")
def api_ref_forget(rid: str) -> dict:
    try:
        reference.forget(rid)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return api_ref_library()


@app.get("/api/references/{rid}/files/{name}")
def api_ref_file(rid: str, name: str) -> FileResponse:
    try:
        p = reference.file_path(rid, name)
    except ValueError:
        p = None
    if not p:
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


# --------------------------------------------------------------------------
# local media -- only files that are in the index, nothing else on disk
# --------------------------------------------------------------------------

@app.get("/api/video/{clip_id}")
def api_video(clip_id: str) -> FileResponse:
    c = CLIPS.get(clip_id)
    if not c:
        raise HTTPException(404)
    # Chrome plays HEVC/H.264 .mov happily when told it's mp4.
    return FileResponse(c["path"], media_type="video/mp4")


@app.get("/api/thumbs/{clip_id}/{name}")
def api_thumb(clip_id: str, name: str) -> FileResponse:
    if clip_id not in CLIPS or "/" in name or not name.endswith(".jpg"):
        raise HTTPException(404)
    p = indexer.clip_dir(clip_id) / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/samples/{clip_id}/{i}")
def api_sample(clip_id: str, i: int) -> FileResponse:
    files = (CLIPS.get(clip_id) or {}).get("samples", {}).get("files", [])
    if not 0 <= i < len(files):
        raise HTTPException(404)
    p = indexer.clip_dir(clip_id) / files[i]
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


# polish: a finished video, the creator pointing at it (polish_api.py)
from . import polish_api  # noqa: E402

app.include_router(polish_api.router)

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


class _UI(StaticFiles):
    """The page always asks again (sarah kept seeing a page removed two
    builds earlier); the hashed assets it names can be cached for good."""

    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        if r.headers.get("content-type", "").startswith("text/html"):
            r.headers["Cache-Control"] = "no-cache"
        return r


if DIST.exists():
    app.mount("/", _UI(directory=DIST, html=True), name="ui")
