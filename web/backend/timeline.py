"""The storyboard laid out in sequence time, plus the places a cut belongs.

Snap targets are what make the timeline precise without dragging: the
playhead is pulled to moments that already mean something -- a shot
boundary, where motion starts, where the talking stops, a beat of the
music -- instead of to whatever pixel the mouse landed on.

The list is sorted by time and the UI looks it up by binary search. Each
target has a type (which sets how strongly it pulls) and a label, because
snapping the user can't see reads as a bug.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from cutgrammar import music

from . import board as bd

FPS = 30
FRAME = 1 / FPS
# Tie-break when two targets sit within a frame of each other.
PRIORITY = {"shot": 4, "silence": 3, "beat": 2, "motion": 1, "word": 3}


def layout(board: dict | None) -> list[dict]:
    items, t, n = [], 0.0, 0
    for b in (board or {}).get("beats", []):
        for e in b["shots"]:
            d = bd.seq_dur(e)
            gap = bd.is_gap(e)
            if not gap:
                n += 1
            items.append({
                "key": bd.key(e), "kind": "gap" if gap else "shot",
                "shot_id": e.get("id"), "clip_id": None if gap else e["id"].split(":")[0],
                "src_start": e["start"], "src_end": e["end"],
                "seq_start": round(t, 4), "seq_end": round(t + d, 4),
                "beat_id": b["id"], "beat_title": b["title"], "n": None if gap else n,
                # the shot fixes (board.set_shot), only where set
                **{f: e[f] for f in bd.SHOT_FX if f in e},
                **({"freeze": True} if bd.is_freeze(e) else {}),
            })
            t += d
    return items


# --------------------------------------------------------------------------
# target sources -- each returns [{t, type, label}] in sequence time
# --------------------------------------------------------------------------

def shot_targets(items: list[dict], **_) -> list[dict]:
    out = []
    for it in items:
        label = "gap start" if it["kind"] == "gap" else f"shot {it['n']} start"
        out.append({"t": it["seq_start"], "type": "shot", "label": label})
    if items:
        out.append({"t": items[-1]["seq_end"], "type": "shot", "label": "end of edit"})
    return out


MARK_LABEL = {"motion_on": ("motion", "motion onset"), "motion_off": ("motion", "motion stops"),
              "quiet": ("silence", "silence starts"), "sound": ("silence", "sound returns")}


def mark_targets(items: list[dict], clips: dict[str, dict], **_) -> list[dict]:
    """Silence edges and motion onsets from the index, mapped into the edit."""
    out = []
    for it in items:
        if it["kind"] != "shot" or it["clip_id"] not in clips:
            continue
        for m in clips[it["clip_id"]].get("marks", []):
            if it["src_start"] + FRAME < m["t"] < it["src_end"] - FRAME:
                typ, what = MARK_LABEL[m["kind"]]
                approx = f" (±{m['approx']:.1f}s)" if m.get("approx", 0) >= 0.1 else ""
                out.append({"t": round(it["seq_start"] + m["t"] - it["src_start"], 4), "type": typ,
                            "label": f"{what} · shot {it['n']}{approx}"})
    return out


def grid_of(track: music.Track | None, music_in: float = 0.0) -> dict | None:
    """The track's beat grid in *edit* time: a track that starts `music_in`
    seconds in has its beats that much earlier than its own phase says. Was
    wrong for every Remix (they all start at the drop) until 2026-10-10."""
    if track is None or not track.bpm or (track.meta.get("tempo") or {}).get("phase") is None:
        return None
    period = 60.0 / track.bpm
    phase = (float(track.meta["tempo"]["phase"]) - float(music_in or 0.0)) % period
    return {"bpm": track.bpm, "phase": round(phase, 4)}


def beat_targets(items: list[dict], track: music.Track | None = None, music_in: float = 0.0, **_) -> list[dict]:
    """The music's beat grid, if a track is in use and its tempo is reliable."""
    g = grid_of(track, music_in)
    if g is None or not items:
        return []
    out = []
    period = 60.0 / g["bpm"]
    beats = [round(float(t), 3) for t in np.arange(g["phase"], items[-1]["seq_end"], period)]
    for k, t in enumerate(beats):
        label = f"bar {k // 4 + 1} downbeat" if k % 4 == 0 else f"beat {k % 4 + 1} of 4 · bar {k // 4 + 1}"
        out.append({"t": t, "type": "beat", "label": label})
    return out


# Word boundaries belong here once there's a transcript (a source returning
# {"type": "word", "label": "after “amazing”"}). Transcription isn't built,
# so there is deliberately no word source -- not an empty stub pretending.
SOURCES: list[Callable[..., list[dict]]] = [shot_targets, mark_targets, beat_targets]


def targets(items: list[dict], clips: dict[str, dict], track: music.Track | None, music_in: float = 0.0) -> list[dict]:
    raw = [x for src in SOURCES for x in src(items, clips=clips, track=track, music_in=music_in)]
    raw.sort(key=lambda x: (x["t"], -PRIORITY[x["type"]]))
    out: list[dict] = []
    for x in raw:  # within a frame of each other: keep the stronger one
        if out and x["t"] - out[-1]["t"] < FRAME / 2:
            if PRIORITY[x["type"]] > PRIORITY[out[-1]["type"]]:
                out[-1] = x
            continue
        out.append(x)
    return out


def build(board: dict | None, clips: dict[str, dict], track: music.Track | None) -> dict:
    items = layout(board)
    # How far each shot's ends can be dragged: the whole shot as filmed, not
    # just the rough trim's window (sarah skipped the trim's own page, so
    # "keep the whole clip" is dragging an end all the way out in Frames).
    for it in items:
        if it["kind"] != "shot":
            continue
        cid, idx = it["shot_id"].rsplit(":", 1)
        sh = next((x for x in (clips.get(cid) or {}).get("shots", []) if str(x["index"]) == idx), None)
        it["src_min"], it["src_max"] = (sh["start"], sh["end"]) if sh else (it["src_start"], it["src_end"])
        if it.get("freeze"):   # a held frame's ends only set how long it holds
            it["src_min"], it["src_max"] = it["src_start"] - bd.FREEZE_MAX, it["src_start"] + bd.FREEZE_MAX
    total = items[-1]["seq_end"] if items else 0.0
    music_in = float(((board or {}).get("music") or {}).get("in") or 0.0)
    return {"fps": FPS, "total": round(total, 4), "items": items,
            "targets": targets(items, clips, track, music_in), "grid": grid_of(track, music_in),
            "audio": audio_lane(board, items)}


def audio_lane(board: dict | None, items: list[dict]) -> dict:
    """Sound taken off shots (board.extract_audio), as the timeline draws it:
    a strip under the picture at its place, and which shots now play silent;
    and the creator's recorded voice (board.add_voice), one strip per take."""
    snd = (board or {}).get("sound") or {}
    num = {it["key"]: it["n"] for it in items}
    strips = [{"id": x["id"], "at": x["at"], "dur": round((x["end"] - x["start"]) / (x.get("speed") or 1.0), 4), "gain": x["gain"],
               "mute": x["mute"], "clip_id": x["shot"].split(":")[0], "shot": x["shot"],
               "src_start": x["start"], "n": num.get(x["from"]),
               "fade_in": x.get("fade_in", 0.0), "fade_out": x.get("fade_out", 0.0)}
              for x in snd.get("strips") or []]
    # the creator's recorded voice (mic.py), numbered in the order recorded
    voice = [{"id": x["id"], "at": x["at"], "dur": x["dur"], "gain": x["gain"], "mute": x["mute"], "n": i + 1,
              "voice": True, "fade_in": x.get("fade_in", 0.0), "fade_out": x.get("fade_out", 0.0)}
             for i, x in enumerate(snd.get("voice") or [])]
    return {"strips": strips, "voice": voice, "off": [k for k in snd.get("off") or [] if k in num]}
