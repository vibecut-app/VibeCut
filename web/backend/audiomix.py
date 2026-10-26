"""The edit's sound, as one track: what the preview plays and export muxes.

Why this exists, in editing terms: an amateur edit is heard before it is
seen. Every cut that also cuts the sound -- a room tone snapping off, a
voice clipped mid-breath, a click where two waveforms meet -- tells the
viewer "this is a pile of clips". Professional edits glue picture with
sound: the music bed runs under everything, a place's sound carries a
beat past the cut into the next part (an L cut) or arrives a beat early
(a J cut), and no join is ever a raw step.

Before this, preview and export disagreed: the browser played each clip's
own sound through one seeking <video> (a hard cut at every shot) with the
music at full volume, while export mixed the music at 0.35 and ducked it
only for Remix. Now both hear the same thing, built once here:

- **Every join gets a micro-fade** (MICRO_S) so waveforms never meet in a
  step -- a step is a click.
- **Joins** are per cut, stored on the storyboard (`set_join` op):
  `cut` (hard, micro-faded), `carry_out` (L: the outgoing sound runs on
  under the next shot), `carry_in` (J: the next shot's sound starts early).
  Between parts the default is `carry_out`; inside a part, `cut`. Carrying
  needs footage past the cut in the source file (a handle); where there
  isn't enough, the join falls back to a cut and says so. No picture
  changes: the frame count of every shot is untouched.
- **Borrowed-style transitions** (export.plan_transitions) are honoured the
  same way the picture honours them: a dissolve crossfades the sound over
  its overlap, a dip to black takes the sound down with it.
- **Music** (the storyboard's `set_music`, or the track in use): from its
  in-point, at its gain, ducked where asked, faded out at the end; sound
  effects dropped in at their times; loudness levelled if asked.

Only sound is decoded (48 kHz stereo, cached per file); pixels are not
touched. CARRY_S and MICRO_S are first guesses, like every threshold in
cutgrammar -- calibrate before trusting.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from .indexer import CACHE

SR = 48000
FPS = 30
MICRO_S = 0.015      # 15 ms: long enough to hide a step, too short to hear as a fade
CARRY_S = 0.5        # how far a place's sound runs past a part boundary (prior: 0.3–1.0 s)
MIN_CARRY_S = 0.12   # less footage than this past the cut: not worth carrying
MUSIC_GAIN = 0.35    # music under the original sound, not over it
DUCK_RAMP_S = 0.25   # attack/release of a duck; a step would be heard
SOUNDS = ("cut", "carry_out", "carry_in")

AUDIO_CACHE = CACHE / "audio"
MIX_CACHE = CACHE / "mix"


# --------------------------------------------------------------------------
# decoding: once per file, 48 kHz stereo float32, memory-mapped
# --------------------------------------------------------------------------

def _file_key(path: str) -> str:
    st = os.stat(path)
    return hashlib.sha1(f"{os.path.realpath(path)}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def decode(path: str) -> np.ndarray | None:
    """(n, 2) float32 at SR, or None when the file has no sound."""
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    k = _file_key(path)
    raw, none = AUDIO_CACHE / f"{k}.f32", AUDIO_CACHE / f"{k}.none"
    if none.exists():
        return None
    if not raw.exists():
        p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn", "-map", "0:a:0?",
                            "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True)
        if p.returncode != 0 or not p.stdout:
            none.touch()
            return None
        tmp = raw.with_suffix(".part")
        tmp.write_bytes(p.stdout)
        tmp.replace(raw)
    if raw.stat().st_size < 8:
        return None
    return np.memmap(raw, dtype=np.float32, mode="r").reshape(-1, 2)


def _tempo(speed: float) -> str:
    """atempo takes 0.5–2 per stage; chain stages for 0.25 or 4."""
    stages, x = [], speed
    while x > 2.0:
        stages.append(2.0)
        x /= 2.0
    while x < 0.5:
        stages.append(0.5)
        x /= 0.5
    stages.append(x)
    return ",".join(f"atempo={v:.6f}" for v in stages)


def stretched(path: str, a: float, b: float, speed: float) -> np.ndarray | None:
    """Source seconds [a, b) played at `speed`, pitch kept: (n, 2) float32 at SR.
    Cached per file, range and speed."""
    AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
    k = hashlib.sha1(f"{_file_key(path)}|{a:.4f}|{b:.4f}|{speed:.4f}".encode()).hexdigest()[:16]
    raw, none = AUDIO_CACHE / f"t{k}.f32", AUDIO_CACHE / f"t{k}.none"
    if none.exists():
        return None
    if not raw.exists():
        p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, a):.4f}", "-t", f"{b - a:.4f}",
                            "-i", path, "-vn", "-map", "0:a:0?", "-af", _tempo(speed),
                            "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True)
        if p.returncode != 0 or not p.stdout:
            none.touch()
            return None
        tmp = raw.with_suffix(".part")
        tmp.write_bytes(p.stdout)
        tmp.replace(raw)
    return np.fromfile(raw, dtype=np.float32).reshape(-1, 2)


# --------------------------------------------------------------------------
# joins
# --------------------------------------------------------------------------

def joins_for(items: list[dict], board_joins: dict | None = None) -> list[dict]:
    """One entry per cut (between items k and k+1): {sound, set}.

    `board_joins` maps the outgoing entry's key to {"sound": ...}, as the
    `set_join` op records it. Unset joins take the default: the sound
    carries across a part boundary (the viewer is moved on by the picture,
    not jolted by the sound), and cuts hard inside a part.
    """
    out = []
    for a, b in zip(items, items[1:]):
        chosen = (board_joins or {}).get(a.get("key"))
        if chosen and chosen.get("sound") in SOUNDS:
            out.append({"sound": chosen["sound"], "set": True})
        elif a["kind"] == "shot" and b["kind"] == "shot" and a.get("beat_id") != b.get("beat_id"):
            out.append({"sound": "carry_out", "set": False})
        else:
            out.append({"sound": "cut", "set": False})
    return out


def _room(it: dict, clips: dict, side: str) -> float:
    """Seconds of footage in the source file beyond this span's edge."""
    c = clips.get(it.get("clip_id") or "") or {}
    if side == "head":
        return max(0.0, float(it["src_start"]))
    dur = float(c.get("duration") or 0.0)
    return max(0.0, dur - float(it["src_end"]) - 1 / FPS)


def fits(items: list[dict], clips: dict, k: int, sound: str) -> bool:
    """Can the join after item k carry its sound? (enough footage past the cut)"""
    a, b = items[k], items[k + 1]
    if sound == "cut" or a["kind"] != "shot" or b["kind"] != "shot":
        return sound == "cut"
    if float(a.get("speed") or 1) != 1 or float(b.get("speed") or 1) != 1:
        return False
    if any(x.get("reverse") or x.get("freeze") for x in (a, b)):
        return False   # backwards or held, the footage past the cut isn't what plays next to it
    if sound == "carry_out":
        room, other = _room(a, clips, "tail"), (b["seq_end"] - b["seq_start"]) / 2
    else:
        room, other = _room(b, clips, "head"), (a["seq_end"] - a["seq_start"]) / 2
    return min(CARRY_S, room, other) >= MIN_CARRY_S


def plan(items: list[dict], clips: dict, joins: list[dict] | None = None,
         transitions: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    """Per shot: which source seconds sound where, and how each edge fades.

    Each span is {clip_id, src, seq, fin, fout} with src/seq as [start, end]
    seconds and fin/fout as (seconds, "micro" | "cross" | "dip"). A carried
    or dissolved join lengthens one or both spans past the cut and
    crossfades them; the picture is unchanged.
    """
    joins = joins if joins is not None else joins_for(items)
    spans: list[dict | None] = []
    for it in items:
        if it["kind"] != "shot" or it.get("freeze"):
            spans.append(None)   # a gap, or a held frame: silent
            continue
        spans.append({"key": it.get("key"), "speed": float(it.get("speed") or 1.0), "reverse": bool(it.get("reverse")),
                      "gain": 0.0 if it.get("mute") else float(1.0 if it.get("gain") is None else it["gain"]),
                      "fades": (float(it.get("fade_in") or 0.0), float(it.get("fade_out") or 0.0)), "clip_id": it["clip_id"], "src": [float(it["src_start"]), float(it["src_end"])],
                      "seq": [float(it["seq_start"]), float(it["seq_end"])],
                      "fin": (MICRO_S, "micro"), "fout": (MICRO_S, "micro")})
    notes: list[str] = []
    fell_back = 0
    tr = transitions or [{} for _ in items]

    for k in range(len(items) - 1):
        a, b, sa, sb = items[k], items[k + 1], spans[k], spans[k + 1]
        tail, head = int(tr[k].get("tail") or 0), int(tr[k + 1].get("head") or 0)
        if sa and sb and (tail or head):
            # a dissolve: the picture overlaps [cut - head, cut + tail]; so does the sound
            sa["src"][1] += tail / FPS
            sa["seq"][1] += tail / FPS
            sb["src"][0] -= head / FPS
            sb["seq"][0] -= head / FPS
            ov = (tail + head) / FPS
            sa["fout"], sb["fin"] = (ov, "cross"), (ov, "cross")
            continue
        sound = joins[k]["sound"] if k < len(joins) else "cut"
        if sound == "cut" or not (sa and sb):
            continue
        if sa["reverse"] or sb["reverse"]:
            continue   # played backwards, the sound past the cut is on the wrong side
        if sa["speed"] != 1 or sb["speed"] != 1:
            continue   # a sped-up or slowed shot's sound isn't carried: its handle would play at the wrong speed
        if sound == "carry_out":
            d = min(CARRY_S, _room(a, clips, "tail"), (b["seq_end"] - b["seq_start"]) / 2)
            if d < MIN_CARRY_S:
                fell_back += 1
                continue
            sa["src"][1] += d
            sa["seq"][1] += d
        else:  # carry_in
            d = min(CARRY_S, _room(b, clips, "head"), (a["seq_end"] - a["seq_start"]) / 2)
            if d < MIN_CARRY_S:
                fell_back += 1
                continue
            sb["src"][0] -= d
            sb["seq"][0] -= d
        sa["fout"], sb["fin"] = (d, "cross"), (d, "cross")

    for k, it in enumerate(items):
        s = spans[k]
        if not s:
            continue
        # a dip to black takes the sound down with the picture; a flash doesn't
        for edge, key in (("fade_in", "fin"), ("fade_out", "fout")):
            f = tr[k].get(edge)
            if f and f[1] == "black":
                s[key] = (max(s[key][0], f[0] / FPS), "dip")
    if fell_back:
        notes.append(f"{fell_back} sound carr{'ies' if fell_back != 1 else 'y'} became a cut: "
                     "the shot wasn't filmed long enough past the cut")
    return [s for s in spans if s], notes


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _ramp(n: int, kind: str, rising: bool) -> np.ndarray:
    x = (np.arange(n, dtype=np.float32) + 0.5) / max(n, 1)
    if kind == "cross":          # equal power: two different sounds don't dip in the middle
        g = np.sin(x * np.pi / 2)
    elif kind == "micro":        # raised cosine: no corner to click on
        g = 0.5 - 0.5 * np.cos(x * np.pi)
    else:                        # a dip follows the picture's linear fade
        g = x
    return g if rising else g[::-1]


def duck_envelope(n: int, ducks: list) -> np.ndarray:
    """1 outside the ducks, `gain` inside, ramped over DUCK_RAMP_S. Overlaps take the quieter."""
    env = np.ones(n, np.float32)
    t = np.arange(n, dtype=np.float32) / SR
    for a, b, g in ducks or []:
        a, b, g = float(a), float(b), float(g)
        if b <= a or not 0 <= g < 1:
            continue
        dist = np.clip(np.maximum(a - t, t - b) / DUCK_RAMP_S, 0, 1)
        env = np.minimum(env, g + (1 - g) * dist)
    return env


def render(items: list[dict], clips: dict, *, joins: list[dict] | None = None,
           transitions: list[dict] | None = None, music: dict | None = None,
           sound: dict | None = None) -> tuple[np.ndarray, list[str]]:
    """The whole edit's sound: (n, 2) float32 at SR, exactly the timeline's length.

    `sound` is `strips_of(board)`: shots whose own sound was taken off, and
    the strips it went to, each placed and levelled on its own."""
    total = float(items[-1]["seq_end"]) if items else 0.0
    n = int(round(total * SR))
    out = np.zeros((n, 2), np.float32)
    spans, notes = plan(items, clips, joins, transitions)
    original = float((music or {}).get("original", 1.0)) if (music or {}).get("path") else 1.0
    off = set((sound or {}).get("off") or [])
    for s in spans:
        if s.get("key") in off:
            continue
        c = clips.get(s["clip_id"])
        if s["gain"] <= 0 or not c:
            continue
        q0 = int(round(s["seq"][0] * SR))
        if s["speed"] != 1:
            # played faster or slower: the same seconds, stretched to the
            # shot's length in the edit, pitch kept (atempo), like any editor
            length = int(round((s["seq"][1] - s["seq"][0]) * SR))
            got = stretched(c["path"], s["src"][0], s["src"][1], s["speed"])
            if got is None or length <= 0:
                continue
            seg = np.zeros((length, 2), np.float32)
            seg[:min(length, len(got))] = got[:length]
        else:
            snd = decode(c["path"])
            if snd is None:
                continue
            s0, s1 = int(round(s["src"][0] * SR)), int(round(s["src"][1] * SR))
            length = s1 - s0
            if length <= 0:
                continue
            seg = np.zeros((length, 2), np.float32)
            lo, hi = max(0, s0), min(len(snd), s1)
            if hi > lo:
                seg[lo - s0:hi - s0] = snd[lo:hi]
        if s.get("reverse"):
            seg = np.ascontiguousarray(seg[::-1])   # backwards, like the picture
        env = np.ones(length, np.float32)
        fi = min(length, int(round(s["fin"][0] * SR)))
        fo = min(length, int(round(s["fout"][0] * SR)))
        if fi:
            env[:fi] *= _ramp(fi, s["fin"][1], True)
        if fo:
            env[length - fo:] *= _ramp(fo, s["fout"][1], False)
        # the shot's own fades (the Sound bar), over its place in the edit
        # (from where its picture starts to where it ends: a carried join's
        # overlap is the crossfade's, not the fade's)
        fa, fz = s["fades"]
        if fa or fz:
            q = s["seq"][0] + np.arange(length, dtype=np.float32) / SR
            start = s["seq"][0] + (s["fin"][0] if s["fin"][1] == "cross" else 0.0)
            end = s["seq"][1] - (s["fout"][0] if s["fout"][1] == "cross" else 0.0)
            if fa:
                env *= np.clip((q - start) / fa, 0, 1)
            if fz:
                env *= np.clip((end - q) / fz, 0, 1)
        seg *= (env * original * s["gain"])[:, None]
        # clip to the edit: a carry before the first frame or after the last is dropped
        a, z = max(0, q0), min(n, q0 + length)
        if z > a:
            out[a:z] += seg[a - q0:z - q0]

    for st in (sound or {}).get("strips") or []:
        _place(out, st, clips, original)

    m = music or {}
    if m.get("path"):
        track = decode(m["path"])
        if track is not None:
            i0 = int(round(float(m.get("in") or 0.0) * SR))
            bed = np.zeros((n, 2), np.float32)
            got = track[i0:i0 + n]
            bed[:len(got)] = got
            gain = float(m.get("gain", MUSIC_GAIN))
            env = np.full(n, gain, np.float32) * duck_envelope(n, m.get("duck") or [])
            fd = int(round(float(m.get("fade_out", 2.0)) * SR))
            if 0 < fd <= n:
                env[n - fd:] *= np.linspace(1, 0, fd, dtype=np.float32)
            out += bed * env[:, None]
        for fx in m.get("sfx") or []:
            snd = decode(fx["path"]) if os.path.isfile(fx.get("path", "")) else None
            if snd is None:
                continue
            at = int(round(float(fx["at"]) * SR))
            z = min(n, at + len(snd))
            if z > at:
                out[at:z] += snd[:z - at] * float(fx.get("gain", 0.5))
    return out, notes


def _place(out: np.ndarray, st: dict, clips: dict, original: float) -> None:
    """One extracted strip into the mix: its own source seconds at its own
    place, micro-faded at both ends (it was cut out of a longer sound)."""
    c = clips.get(st["clip_id"])
    snd = decode(c["path"]) if c else None
    if snd is None or st["gain"] <= 0:
        return
    q0 = int(round(st["at"] * SR))
    speed = float(st.get("speed") or 1.0)
    if abs(speed - 1.0) > 1e-6:
        got = stretched(c["path"], st["src"][0], st["src"][1], speed)
        if got is None or not len(got) or q0 >= len(out):
            return
        seg = np.array(got, np.float32)
    else:
        s0, s1 = int(round(st["src"][0] * SR)), int(round(st["src"][1] * SR))
        s0, s1 = max(0, s0), min(len(snd), s1)
        if s1 <= s0 or q0 >= len(out):
            return
        seg = np.array(snd[s0:s1], np.float32)
    f = min(len(seg) // 2, int(round(MICRO_S * SR)))
    if f:
        seg[:f] *= _ramp(f, "micro", True)[:, None]
        seg[-f:] *= _ramp(f, "micro", False)[:, None]
    fa, fz = st.get("fades") or (0.0, 0.0)
    if fa or fz:
        q = np.arange(len(seg), dtype=np.float32) / SR
        env = np.ones(len(seg), np.float32)
        if fa:
            env *= np.clip(q / fa, 0, 1)
        if fz:
            env *= np.clip((len(seg) / SR - q) / fz, 0, 1)
        seg *= env[:, None]
    z = min(len(out), q0 + len(seg))
    out[q0:z] += seg[:z - q0] * float(st["gain"]) * original


def strips_of(board: dict | None) -> dict | None:
    """The board's extracted sound (board.extract_audio), as the mixer needs
    it: which shots play silent, and each strip's file, seconds, place and
    level. A muted strip is simply left out."""
    snd = (board or {}).get("sound")
    if not snd or not (snd.get("off") or snd.get("strips")):
        return None
    return {"off": list(snd.get("off") or []),
            "strips": [{"clip_id": x["shot"].split(":")[0], "src": [x["start"], x["end"]], "at": x["at"],
                        "speed": float(x.get("speed") or 1.0),
                        "gain": 0.0 if x.get("mute") else float(x.get("gain", 1.0)),
                        "fades": (float(x.get("fade_in") or 0.0), float(x.get("fade_out") or 0.0))}
                       for x in snd.get("strips") or [] if not x.get("mute")]}


def write_wav(buf: np.ndarray, path: Path, level: bool = False) -> None:
    """16-bit WAV. `level` runs the same loudness normalisation export always used."""
    pcm = (np.clip(buf, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.with_suffix(".raw.wav") if level else path
    with wave.open(str(target), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    if level:
        # loudnorm works (and would output) at 192 kHz; players expect 48 kHz
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(target),
                        "-af", f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample={SR}",
                        "-c:a", "pcm_s16le", str(path)], check=True, capture_output=True)
        target.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# the preview's copy, cached by what it's made of
# --------------------------------------------------------------------------

def spec(items: list[dict], clips: dict, board_joins: dict | None, transitions: list[dict] | None,
         music: dict | None, sound: dict | None = None) -> dict:
    """Everything the mix depends on, as plain data -- its hash is the file name."""
    return {
        "items": [{k: it.get(k) for k in ("key", "kind", "clip_id", "src_start", "src_end", "seq_start",
                                          "seq_end", "beat_id", "speed", "gain", "mute", "fade_in", "fade_out",
                                          "reverse", "freeze")}
                  for it in items],
        "files": {cid: [c.get("path"), c.get("duration")] for cid, c in clips.items()
                  if any(it.get("clip_id") == cid for it in items)
                  or any(x["clip_id"] == cid for x in (sound or {}).get("strips") or [])},
        "joins": board_joins or {},
        "transitions": transitions,
        "music": music,
        "sound": sound,
        "v": 1,
    }


def key_of(sp: dict) -> str:
    return hashlib.sha1(json.dumps(sp, sort_keys=True, default=str).encode()).hexdigest()[:16]


def preview_file(sp: dict, clips: dict) -> Path:
    """Render (or reuse) the preview mix for this spec."""
    MIX_CACHE.mkdir(parents=True, exist_ok=True)
    path = MIX_CACHE / f"{key_of(sp)}.wav"
    if not path.exists():
        buf, _ = render(sp["items"], clips, joins=joins_for(sp["items"], sp["joins"]),
                        transitions=sp["transitions"], music=sp["music"], sound=sp.get("sound"))
        with tempfile.NamedTemporaryFile(dir=MIX_CACHE, suffix=".wav", delete=False) as fh:
            tmp = Path(fh.name)
        write_wav(buf, tmp, level=bool((sp["music"] or {}).get("level")))
        tmp.replace(path)
    return path
