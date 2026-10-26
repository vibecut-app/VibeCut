"""Remix: reference reels + the creator's own shoot -> one finished short.

The creator points at a few videos and says "like that". Everything those
videos share is measurable (cutgrammar.style) and becomes one fingerprint:
how long shots run and how that changes over the video, how long the first
shot is held, the tempo range and arc of the music, the grade. Their frames
and sound never appear here -- only the habits.

Then, in order:

1. **Choose** (select.py): the shoot's 40-odd clips become the number of
   moments the reference's pace allows in the reference's length, spread
   across the day, hero shots first, with the strongest moment as the hook.
2. **Music** (cutgrammar.openverse): a commercially usable track near the
   reference tempo whose energy builds like the reference's. Its drop is
   found from the waveform and placed exactly where the hook ends, so the
   day starts on the downbeat.
3. **Beat**: every shot is a whole number of beats and the music is
   trimmed to start on one, so every cut lands on the grid without moving
   the moments the selector chose.
4. **Words**: the references keep a small tag at the top and drop a few
   words per scene ("9:15 a.m. coffee run"). Ours are built only from what
   the edit knows -- capture times and the strongest labels -- and any
   phrase the creator gives on the command line.
5. **Render** (export.py): server-side, no browser: shots, a punch-in on
   each scene's first shot, caption frames drawn by a small AppKit helper
   (this ffmpeg has no text renderer), music at its in-point, a riser into
   the drop, and the whole thing levelled to -14 LUFS.

It also leaves a board on the session (`option: "remix"`) so the result
can be edited by chat or timeline like any other proposal. Every number in
this file is a guess until it has been checked against real posts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from cutgrammar import music as mu
from cutgrammar import openverse as ov
from cutgrammar.media import AUDIO_SR, load_audio

from . import board as bd
from . import export
from . import indexer
from . import reference as ref
from . import select as sel
from . import storyboard as sb
from . import timeline as tlm
from .cut import compute as rough_cut, for_story

DEFAULT_LEN = (15.0, 90.0)          # a short lives here; a reference outside is clipped
HOOK_HOLD = (1.0, 4.0)              # how long the first shot may be held
BPM_DEFAULT = (100.0, 130.0)
MOODS = ["upbeat pop", "indie dance pop", "feel good electronic pop", "summer pop", "energetic indie pop",
         "pop instrumental", "synth pop", "disco funk", "upbeat electronic", "indie rock upbeat"]
ORIGINAL_GAIN = 0.12                # the phone's own sound stays as texture; the references have none
MUSIC_GAIN = 0.85
PUNCH = 0.05                        # slow push over every shot, alternating in and out; a scene's first shot pushes harder
PUNCH_SCENE = 0.09
SPREAD = [1.0, 0.6, 1.4, 1.0, 0.6, 1.0, 1.4, 0.6]   # shot-to-shot variety around the pace, the references' p10..p90
TAG_TEXT = "a day in my life"
PHRASES = {                         # a caption the reference would write, from a label the edit has
    "plate": "lunch", "tableware": "lunch", "utensil": "lunch", "cup": "coffee run",
    "beverage": "coffee run", "laptop": "work work work", "computer": "work work work",
    "crosswalk": "heading home", "path": "walking", "stairs": "up we go", "sky": "look up",
    "whiteboard": "class time", "podium": "lecture", "document": "study time", "car": "on the way",
}


# --------------------------------------------------------------------------
# fingerprint: what the references agree on
# --------------------------------------------------------------------------

def fingerprint(styles: list[dict]) -> dict:
    paces = [s["pace"] for s in styles if s.get("pace")]
    med = float(np.median([p["median_s"] for p in paces])) if paces else 0.8
    # median per bin, not mean: one reference holding a single shot for eight
    # seconds must not stretch every shot in that fifth of ours
    curve = np.clip(np.median([p["curve"] for p in paces], axis=0), 0.5, 2.5).tolist() if paces else [1.0] * 5
    first = float(np.median([p["first_s"] for p in paces])) if paces else 1.5
    p10 = float(np.median([p.get("p10_s", med * 0.6) for p in paces])) if paces else med * 0.6
    p90 = float(np.median([p.get("p90_s", med * 1.6) for p in paces])) if paces else med * 1.6
    bpms = [float(x) for s in styles for x in [(s.get("music") or {}).get("bpm")] if x]
    lo, hi = (min(bpms) * 0.92, max(bpms) * 1.08) if bpms else BPM_DEFAULT
    arcs = [(s.get("music") or {}).get("arc") for s in styles if s.get("music")]
    arc = max(set(arcs), key=arcs.count) if arcs else "builds"
    curves = [s["music"]["energy"] for s in styles if (s.get("music") or {}).get("energy")]
    energy = np.mean(curves, axis=0) if curves else None     # a reference may know its arc but not its curve
    durs = [float(s["duration"]) for s in styles if s.get("duration")]
    dur = float(np.clip(np.median(durs) if durs else 30.0, *DEFAULT_LEN))
    # the reels' ideas (style.words / ending): where words sit, how long they
    # hold, whether there are any; how long the last shot is held
    ws = [s["words"] for s in styles if (s.get("words") or {}).get("share") is not None]
    text = None
    if ws:
        bands = [w["band"] for w in ws if w.get("band")]
        text = {"share": round(float(np.median([w["share"] for w in ws])), 3),
                "band": max(set(bands), key=bands.count) if bands else None,
                "hold_s": round(float(np.median([w["hold_s"] for w in ws if w.get("hold_s")])), 2) if any(w.get("hold_s") for w in ws) else None,
                "upper": bool(np.median([w.get("upper") or 0 for w in ws]) > 0.8),
                "samples": [x for w in ws for x in (w.get("samples") or [])][:12],
                "first_s": round(float(np.median([w["first_s"] for w in ws if w.get("first_s") is not None])), 2) if any(w.get("first_s") is not None for w in ws) else None}
    ends = [s["ending"]["last_s"] for s in styles if (s.get("ending") or {}).get("last_s")]
    brights = [float(s["music"]["bright"]) for s in styles if (s.get("music") or {}).get("bright")]
    return {
        "bright": round(float(np.median(brights)), 1) if brights else None,
        "text": text, "last_s": round(float(np.median(ends)), 2) if ends else None,
        "median_s": round(med, 3), "curve": [round(float(c), 3) for c in curve],
        "spread": (round(p10 / med, 2), round(p90 / med, 2)),
        "hook_s": round(float(np.clip(first, *HOOK_HOLD)), 2),
        "bpm": (round(lo, 1), round(hi, 1)), "arc": arc,
        "energy": [round(float(e), 3) for e in energy] if energy is not None else None,
        "duration": round(dur, 1), "vertical": all((s.get("frame") or {}).get("vertical", True) for s in styles),
        "refs": len(styles),
    }


def describe(fp: dict) -> str:
    return (f"{fp['duration']:.0f} s, about {fp['median_s']:.2f} s a shot, first shot held {fp['hook_s']:.1f} s, "
            f"music {fp['bpm'][0]:.0f}–{fp['bpm'][1]:.0f} BPM that {fp['arc']}; from {fp['refs']} reference(s)")


# --------------------------------------------------------------------------
# shots
# --------------------------------------------------------------------------

def load_shoot(folder: str) -> dict[str, dict]:
    paths = indexer.find_videos(folder)
    if not paths:
        raise SystemExit(f"no .mp4/.mov files in {folder}")
    recs = [indexer.index_clip(p) for p in paths]
    indexer.add_vision(recs)
    return {r["id"]: r for r in recs}


def plan_shots(clips: dict[str, dict], fp: dict, length: float | None = None, hook_n: int = 1,
               cut: tuple[set, dict] | None = None, judge=None, taste: str = "",
               bias: dict[str, float] | None = None, min_s: float = sel.MIN_SHOT_S) -> sel.Plan:
    """Pick the moments and give each its window, before any beat is known.
    `judge`: None = Claude when there is a key (select.judge), False = the
    rules alone, or a stand-in `ask(options, keep)` for tests."""
    rejected, windows = cut if cut is not None else for_story(rough_cut(clips, None))
    shots = sb.shots_from_clips(list(clips.values()), (rejected, windows))
    shots, notes = sb.usable(shots)
    total = length or fp["duration"]
    body = max(1.0, total - fp["hook_s"] * hook_n)
    n = max(4, int(round(body / fp["median_s"])))
    plan = sel.choose(shots, clips, n, hook_n, bias, min_s)
    if judge is not False and os.environ.get("VIBECUT_REMIX_JUDGE", "1") != "0":
        plan = sel.judge(plan, shots, clips, ask=judge if callable(judge) else None, taste=taste)
    plan.notes = notes + plan.notes
    n_body = sum(len(s) for s in plan.sessions)
    targets = [fp["median_s"] * _curve_at(fp["curve"], (k + 0.5) / max(n_body, 1)) * _spread(fp, k)
               for k in range(n_body)]
    sel.time_windows(plan, clips, targets, fp["hook_s"])
    return plan


def _spread(fp: dict, k: int) -> float:
    """Shot k's share of the references' variety: a fixed pattern, so a re-run is the same edit.
    A metronome of equal shots reads as a pause at every cut; the references never do that."""
    lo, hi = fp.get("spread", (0.6, 1.6))
    x = SPREAD[k % len(SPREAD)]
    return lo if x < 1 else (hi if x > 1 else 1.0)


def _curve_at(curve: list[float], pos: float) -> float:
    n = len(curve)
    x = np.clip(pos * n - 0.5, 0, n - 1)
    return float(np.interp(x, np.arange(n), curve))


# --------------------------------------------------------------------------
# music: the track, its drop, the grid
# --------------------------------------------------------------------------

def find_drop(path: str, bpm: float, phase: float, need_s: float, hook_s: float) -> float | None:
    """Track time of the beat where the music jumps up most -- the drop.

    Compares loudness over the bar before each beat with the two bars after
    it. Only beats the edit can start from (hook_s before, need_s after)
    count. None when nothing jumps: the track is flat, so any bar will do.
    """
    m = load_audio(path)
    a = m.audio
    if a.size == 0:
        return None
    period = 60.0 / bpm
    dur = a.size / AUDIO_SR

    def rms(t0: float, t1: float) -> float:
        s = a[int(max(0, t0) * AUDIO_SR):int(min(dur, t1) * AUDIO_SR)]
        return float(np.sqrt(np.mean(s * s))) if s.size else 0.0

    peak = max(rms(x, x + 2.0) for x in np.arange(0, max(dur - 2.0, 0.1), 2.0)) or 1e-4
    best, best_t = 0.0, None
    t = phase
    while t + need_s <= dur:
        if t - hook_s >= 0 and t - 4 * period >= 0:
            before, after = rms(t - 4 * period, t), rms(t, t + 8 * period)
            ratio = after / (before + 1e-4)
            # the bar before must already be music (a fade-in's silence would make
            # every track's first bar look like a drop), and the jump must be real
            if before >= 0.15 * peak and after > 0.02 and ratio > best:
                best, best_t = ratio, t
        t += period
    return best_t if best >= 1.6 else None


DRIVING = ("pop", "dance", "disco", "electronic", "upbeat", "energetic", "speed_high", "funk", "groove",
           "house", "synth", "action")
SLOW = ("acoustic", "ballad", "meditation", "piano", "ambient", "sad", "peaceful", "speed_low", "lullaby",
        "relax", "chill", "folk", "classical")


def vibe(t: mu.Track) -> float:
    """0..1 from the catalogue's own words (tags and title). The waveform features
    below can't tell an acoustic ballad from a pop bed on a pool this small; the
    people who tagged the track could."""
    rec = t.meta.get("licence") or {}
    words = " ".join([rec.get("title", ""), t.title, *rec.get("tags", []), *rec.get("genres", [])]).lower()
    up = sum(w in words for w in DRIVING)
    down = sum(w in words for w in SLOW)
    return float(np.clip(0.5 + 0.2 * up - 0.3 * down, 0, 1))


_CONT: dict[str, float] = {}


def continuity(path: str) -> float:
    """0..1: how much of the track's loud part is *filled*. A plucked guitar with air
    between notes scores low; a driving pop bed scores high. Under quick cuts the
    gaps read as pauses, so the references' kind of track is the filled kind."""
    if path in _CONT:
        return _CONT[path]
    m = load_audio(path)
    a = m.audio
    if a.size < AUDIO_SR:
        return 0.0
    hop = AUDIO_SR // 4                        # 250 ms: long enough that a drum hit and its
    n = a.size // hop                          # decay read as one filled window, not a gap
    rms = np.sqrt(np.mean(a[:n * hop].reshape(n, hop) ** 2, axis=1))
    # the local ceiling: the loudest window within two seconds either side
    k = 8
    ceil = np.array([rms[max(0, i - k):i + k + 1].max() for i in range(n)])
    playing = ceil >= 0.3 * rms.max()          # sections of the track that are on, gaps included
    if playing.sum() < 8:
        return 0.0
    filled = float(np.mean(rms[playing] >= 0.35 * ceil[playing]))
    _CONT[path] = filled
    return filled


def pick_music(fp: dict, need_s: float, hook_s: float, moods: list[str] | None = None,
               progress=None) -> dict | None:
    """The best commercially usable track for this edit, with its in-point and beat grid."""
    src = ov.OpenverseSource(moods or MOODS, progress=progress)
    return pick_from(src.list(), fp, need_s, hook_s)


def pick_from(pool: list[mu.Track], fp: dict, need_s: float, hook_s: float, lean=None) -> dict | None:
    """The best of `pool` for this edit (any source: Openverse, the creator's
    own folder), with its in-point and beat grid. None when nothing is long
    enough or has a steady tempo. `lean(track) -> float` adds to a track's
    score (the creator's own picks, songs.lean)."""
    got = rank_from(pool, fp, need_s, hook_s, 1, lean)
    return got[0] if got else None


def rank_from(pool: list[mu.Track], fp: dict, need_s: float, hook_s: float, n: int = 5, lean=None) -> list[dict]:
    """Up to `n` tracks that fit, best first, each as pick_from returns it
    (2026-10-24, the user: several suggestions to swap between; before, the
    ranking past the first fit was thrown away). The same title twice (a
    mix and its radio edit) counts once."""
    tracks = [t for t in pool if t.duration >= need_s + 8]
    if not tracks:
        return []
    lo, hi = fp["bpm"]
    mid = float(np.sqrt(lo * hi))
    want = np.asarray(fp["energy"] or np.linspace(0.2, 1.0, 32), dtype=np.float32)
    scored = []
    for t in tracks:
        if not t.bpm or (t.meta.get("tempo") or {}).get("phase") is None:
            continue
        # tempo on a log scale, the track's own tempo: a 60 BPM ballad cut on its
        # eighths is still a ballad, so half-time doesn't count as near here
        tempo = float(np.clip(1 - abs(np.log2(t.bpm / mid)) / 0.5, 0, 1))
        shape = max(mu.shape_score(t.energy[s:s + int(need_s)], want)
                    for s in range(0, max(1, int(t.duration - need_s)), 4))
        # timbre: how far the track's weight sits from the references' (an
        # octave off is a different kind of music); only when both are known
        tb, fb = t.meta.get("bright"), fp.get("bright")
        if tb and fb:
            timbre = float(np.clip(1 - abs(np.log2(float(tb) / float(fb))), 0, 1))
            score = 0.35 * tempo + 0.2 * shape + 0.2 * vibe(t) + 0.1 * continuity(t.path) + 0.15 * timbre
        else:
            score = 0.4 * tempo + 0.25 * shape + 0.25 * vibe(t) + 0.1 * continuity(t.path)
        if lean is not None:
            score += float(lean(t))
        scored.append((score, t))
    if not scored:
        return []
    scored.sort(key=lambda x: -x[0])
    out: list[dict] = []
    titles: set[str] = set()
    for score, t in scored[:max(5, 3 * n)]:
        if len(out) >= n:
            break
        key = (t.title or t.id).lower().split("(")[0].strip()
        if key in titles:
            continue
        phase = float(t.meta["tempo"]["phase"])
        bpm = float(t.bpm)
        if bpm < lo * 0.8 and 2 * bpm <= hi * 1.25:
            bpm *= 2          # cut on the half-time track's eighths
        drop = find_drop(t.path, bpm, phase, need_s, hook_s)
        if drop is None:
            # flat track: start it on the first beat the hook can sit before
            drop = phase + np.ceil(hook_s / (60 / bpm)) * (60 / bpm)
        start = drop - hook_s
        if start < 0 or start + need_s > t.duration:
            continue
        titles.add(key)
        out.append({"track": t, "in": round(float(start), 3), "drop": round(float(drop), 3), "bpm": bpm,
                    "period": 60.0 / bpm, "score": round(float(score), 3),
                    "credit": ov.credit(t.meta["licence"]) if t.meta.get("licence") else t.title})
    return out


def quantise(plan: sel.Plan, clips: dict[str, dict], period: float) -> None:
    """Every window becomes a whole number of half-beats, re-cut on its busiest second.

    Hero shots and the hook sit on whole beats, so the strong cuts land on
    the downbeats; filler may end on the off-beat, which keeps the grid
    without the march of equal shots.
    """
    for p in plan.picks:
        unit = period if p.role in ("hook", "hero") else period / 2
        beats = max(1, int(round(p.duration / unit)))
        if p.role == "hook":
            beats = max(2, beats)
        want = beats * unit
        p.start, p.end, p.short = sel.window(clips, p.shot, want)
        if p.short:
            # filmed shorter than the beat count: shave to the last whole beat it can fill
            k = max(1, int(p.duration / period))
            p.end = round(p.start + k * period, 3) if p.duration >= period else p.end


# --------------------------------------------------------------------------
# the board and its words
# --------------------------------------------------------------------------

def board_of(plan: sel.Plan, fp: dict, name: str) -> dict:
    beats = []
    if plan.hook:
        beats.append({"id": "r0", "title": "Hook", "detail": "the day's strongest moment, first",
                      "shots": [{"id": p.shot.id, "start": p.start, "end": p.end} for p in plan.hook]})
    for i, (title, picks) in enumerate(zip(plan.titles, plan.sessions), 1):
        if not picks:
            continue
        beats.append({"id": f"r{i}", "title": title, "detail": sb.fmt_span([p.shot for p in picks]),
                      "shots": [{"id": p.shot.id, "start": p.start, "end": p.end} for p in picks]})
    return {"option": "remix", "name": name,
            "structure": f"Remix in the style of your references — {describe(fp)}", "beats": beats}


def _clock(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'a.m.' if dt.hour < 12 else 'p.m.'}"


def captions(plan: sel.Plan, title: str | None, sub: str | None, hold_s: float | None = None,
             with_title: bool = True, phrases: list[str] | None = None, clock: bool = True) -> list[dict]:
    """What goes on screen, in sequence seconds. Built only from what the edit
    knows. `hold_s`: how long a stop's line stays (a reference's own hold);
    `with_title`: a reel with no words at the top gets no title."""
    out = []
    t = 0.0
    hook_end = sum(p.duration for p in plan.hook)
    first = next((p.shot.when for p in plan.picks if p.shot.when), None)
    if plan.hook and with_title:
        out.append({"kind": "title", "text": title or TAG_TEXT,
                    "sub": sub or (first.strftime("%A, %B %-d") if first else ""),
                    "start": 0.0, "end": hook_end, "anim": "pop"})
        t = hook_end
    total = plan.duration
    if total > hook_end + 1:
        out.append({"kind": "tag", "text": title or TAG_TEXT, "start": hook_end, "end": total, "anim": "fade"})
    for n_, picks in enumerate(plan.sessions):
        if not picks:
            continue
        p0 = picks[0]
        words = _clock(p0.shot.when) if (p0.shot.when and clock) else ""
        # a written line for this stop (make.words, the model with the creator's taste) beats the label table
        # an empty written line means the stop has nothing new to say (make.plain_lines), not "use the table"
        phrase = (phrases[n_] or None) if phrases is not None and n_ < len(phrases) else _phrase(picks)
        if not clock and not phrase:
            # no clock stamps on their own (2026-10-18): a stop with nothing to say says nothing --
            # but its seconds still pass, or every later line lands a stop early (2026-10-25)
            t += sum(p.duration for p in picks)
            continue
        if phrase:
            words = f"{words} · {phrase}" if words else phrase
        if words:
            hold = hold_s if hold_s else min(2.2, max(1.2, sum(p.duration for p in picks[:3])))
            hold = min(hold, max(0.8, sum(p.duration for p in picks)))   # never past the stop itself
            out.append({"kind": "scene", "text": words, "start": round(t, 3), "end": round(t + hold, 3),
                        "anim": "pop"})
        t += sum(p.duration for p in picks)
    return out


def _phrase(picks: list[sel.Pick]) -> str | None:
    for p in picks:
        for k, v in sorted(p.shot.labels.items(), key=lambda kv: -kv[1]):
            if v >= 0.4 and k in PHRASES:
                return PHRASES[k]
    return None


# --------------------------------------------------------------------------
# caption frames (AppKit; this ffmpeg has no text renderer)
# --------------------------------------------------------------------------

SWIFT = r'''
import AppKit
// vibetext <out.png> <W> <H> <json spec>   spec: {"lines":[{"text","size","weight","y","font","alpha"}]}
let a = CommandLine.arguments
let W = Int(a[2])!, H = Int(a[3])!
let spec = try! JSONSerialization.jsonObject(with: a[4].data(using: .utf8)!) as! [String: Any]
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: W, pixelsHigh: H, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
let ctx = NSGraphicsContext(bitmapImageRep: rep)!
NSGraphicsContext.current = ctx
let para = NSMutableParagraphStyle(); para.alignment = .center
for l in spec["lines"] as! [[String: Any]] {
    let size = CGFloat(l["size"] as! Double)
    let y = CGFloat(l["y"] as! Double)
    let alpha = CGFloat((l["alpha"] as? Double) ?? 1)
    let shadow = NSShadow(); shadow.shadowColor = NSColor.black.withAlphaComponent(0.5 * alpha)
    shadow.shadowBlurRadius = 10; shadow.shadowOffset = NSSize(width: 0, height: -2)
    let weight: NSFont.Weight = (l["weight"] as? String) == "bold" ? .bold : ((l["weight"] as? String) == "light" ? .light : .medium)
    var font = NSFont.systemFont(ofSize: size, weight: weight)
    if (l["font"] as? String) == "serif" {
        font = NSFont(name: "Georgia-Italic", size: size) ?? NSFont(name: "Times-Italic", size: size) ?? font
    }
    let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor.white.withAlphaComponent(alpha),
                                                .shadow: shadow, .paragraphStyle: para]
    let s = NSAttributedString(string: l["text"] as! String, attributes: attrs)
    let margin: CGFloat = CGFloat(W) * 0.08
    let box = s.boundingRect(with: NSSize(width: CGFloat(W) - 2 * margin, height: 4000), options: [.usesLineFragmentOrigin])
    s.draw(with: NSRect(x: margin, y: CGFloat(H) - y - box.height, width: CGFloat(W) - 2 * margin, height: box.height),
           options: [.usesLineFragmentOrigin])
}
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[1]))
'''


def text_tool() -> Path:
    d = indexer.CACHE / "bin"
    d.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(SWIFT.encode()).hexdigest()[:10]
    exe = d / f"vibetext-{h}"
    if not exe.exists():
        src = d / f"vibetext-{h}.swift"
        src.write_text(SWIFT)
        p = subprocess.run(["swiftc", "-O", str(src), "-o", str(exe)], capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError("couldn't build the caption renderer: " + p.stderr[-400:])
    return exe


def _layout(c: dict, w: int, h: int) -> list[dict]:
    """Where each caption kind sits. Everything inside the TikTok / Reels safe area
    (top 14%, bottom 35%, sides 8% kept clear)."""
    u = min(w, h)
    if c["kind"] == "title":
        lines = [{"text": c["text"], "size": u * 0.085, "weight": "bold", "y": h * 0.40, "font": "serif"}]
        if c.get("sub"):
            lines.append({"text": c["sub"], "size": u * 0.032, "weight": "medium", "y": h * 0.40 + u * 0.115})
        return lines
    if c["kind"] == "tag":
        return [{"text": c["text"], "size": u * 0.028, "weight": "medium", "y": h * 0.16}]
    return [{"text": c["text"], "size": u * 0.036, "weight": "medium", "y": h * 0.30}]


POP_FRAMES = 6   # a pop-in over 6 frames: scale 0.92 -> 1, alpha 0 -> 1


def _state(c: dict, t: float, fps: int) -> tuple[float, float] | None:
    """(scale, alpha) of caption c at time t, or None when it isn't on screen."""
    if not (c["start"] - 1e-6 <= t < c["end"] - 1e-6):
        return None
    steps = POP_FRAMES if c.get("anim") == "pop" else 3
    k = (t - c["start"]) * fps
    if k >= steps:
        return 1.0, 1.0
    ease = 1 - (1 - (int(k) + 1) / steps) ** 3
    return (0.92 + 0.08 * ease if c.get("anim") == "pop" else 1.0), ease


def render_captions(caps: list[dict], size: dict, fps: int, job) -> list[dict]:
    """Draw the captions into the export job as one PNG per distinct picture.

    The overlay track shows one frame at a time, so where two captions
    overlap (the tag at the top under a scene's words) they are drawn
    together. A change point is any caption's start or end, plus one per
    frame during a pop-in; between change points the picture holds.
    """
    exe = text_tool()
    w, h = size["w"], size["h"]
    points = set()
    for c in caps:
        # a caption that ends on a cut must be gone on the cut's own frame,
        # so it ends a frame early rather than flash over the next shot
        c["end"] = max(c["start"] + 1 / fps, c["end"] - 1 / fps)
        points.add(c["start"])
        points.add(c["end"])
        steps = POP_FRAMES if c.get("anim") == "pop" else 3
        for k in range(1, steps + 1):
            points.add(c["start"] + k / fps)
    times = sorted(p for p in points if p >= 0)
    tmp = job.dir / "caps"
    tmp.mkdir(exist_ok=True)
    schedule, n = [], 0
    for a, b in zip(times, times[1:]):
        if b - a < 0.5 / fps:
            continue
        lines = []
        for c in caps:
            st = _state(c, a + 0.25 / fps, fps)
            if st:
                sc, al = st
                for ln in _layout(c, w, h):
                    lines.append({**ln, "size": ln["size"] * sc, "alpha": al})
        if not lines:
            continue
        out = tmp / f"{n:05d}.png"
        subprocess.run([str(exe), str(out), str(w), str(h), json.dumps({"lines": lines})], check=True)
        export.save_frame(job, n, out.read_bytes())
        out.unlink()
        schedule.append({"frame": n, "start": round(a, 4), "end": round(b, 4)})
        n += 1
    return schedule


# --------------------------------------------------------------------------
# the whole thing
# --------------------------------------------------------------------------

def make(refs: list[str], footage: str | None = None, name: str = "Remix", length: float | None = None,
         title: str | None = None, sub: str | None = None, moods: list[str] | None = None,
         look: bool = True, sfx: bool = True, say=print, clips: dict[str, dict] | None = None,
         cut: tuple[set, dict] | None = None, stage=lambda s, p: None, judge=None) -> dict:
    """The whole thing. `stage(name, progress)` reports where it is; `say` explains."""
    t0 = time.time()
    styles, rids = [], []
    stage("references", 0.02)
    for k, src in enumerate(refs):
        job = ref.start(src)
        while job.stage not in ("done", "error"):
            time.sleep(1)
            stage("references", 0.02 + 0.18 * (k + job.progress) / max(1, len(refs)))
        if job.stage == "error":
            say(f"reference skipped: {src} — {job.error}")
            continue
        r = ref.load(job.rid)
        styles.append(r["style"])
        rids.append(job.rid)
        say(f"reference: {r['title'][:60]} ({r['duration']:.0f} s)")
    if not styles:
        raise ValueError("none of the references could be read")
    fp = fingerprint(styles)
    say("fingerprint: " + describe(fp))

    stage("choosing", 0.22)
    if clips is None:
        if not footage:
            raise ValueError("no footage")
        clips = load_shoot(footage)
    plan = plan_shots(clips, fp, length, cut=cut, judge=judge)
    say(f"shots: {len(plan.picks)} moments from {len(clips)} clips ({plan.duration:.1f} s before the beat)")
    for n_ in [x for x in plan.notes if x.startswith("Claude judged")]:
        say(n_)
    stage("music", 0.3)

    hook_s = sum(p.duration for p in plan.hook) or fp["hook_s"]
    mx = pick_music(fp, plan.duration + 4, hook_s, moods)
    period = mx["period"] if mx else None
    if mx:
        quantise(plan, clips, period)
        hook_s = sum(p.duration for p in plan.hook)
        mx["in"] = round(mx["drop"] - hook_s, 3)   # the hook may have grown to whole beats
        say(f"music: {mx['track'].title} — {mx['bpm']:.0f} BPM, drop at {mx['drop']:.2f} s, "
            f"starts {mx['in']:.2f} s in")
    else:
        say("music: nothing usable found online — exporting without a track")

    board = board_of(plan, fp, name)
    cat = bd.Catalog.from_clips(list(clips.values()))
    style = None
    if look and rids:
        try:
            fit = ref.fit_look(rids[0], board, cat, "subtle")
            style = {"ref": rids[0], "name": "remix", "traits": ["look"],
                     "look": {"lut": fit["lut"], "strength": fit["strength"], "words": fit["look_words"]},
                     "transitions": None, "letterbox": None}
            say("look: " + ", ".join(fit["look_words"]))
        except Exception as e:  # noqa: BLE001 -- the grade is optional
            say(f"look: skipped ({e})")

    items = tlm.build(board, clips, None)["items"]
    starts = {b["shots"][0]["id"] for b in board["beats"][1:] if b["shots"]}
    for k, it in enumerate(it for it in items if it["kind"] == "shot"):
        # a slow push on every shot, alternating in and out, so nothing sits still;
        # the first shot of a scene pushes harder, as a pattern interrupt
        z = PUNCH_SCENE if it["shot_id"] in starts else PUNCH
        it["punch"] = z if k % 2 == 0 else -z
    mix = None
    if mx:
        mix = {"in": mx["in"], "gain": MUSIC_GAIN, "original": ORIGINAL_GAIN, "level": True,
               "fade_out": min(3.0, max(1.5, 4 * period)), "duck": [], "sfx": []}
        if sfx:
            riser = ov.sfx("swoosh riser whoosh")
            if riser:
                mix["sfx"].append({"path": str(riser), "at": max(0.0, hook_s - 0.9), "gain": 0.45})
    stage("rendering", 0.45)
    job = export.create(items, clips, name, mx["track"].path if mx else None, style, mix)
    caps = captions(plan, title, sub)
    schedule = render_captions(caps, job.size, export.FPS, job)
    job.overlays = len(schedule)
    job.schedule = schedule
    job.stage = "shots"
    watcher = threading.Thread(target=_watch, args=(job, stage), daemon=True)
    watcher.start()
    export._run(job)
    if job.stage != "done":
        raise RuntimeError(f"export failed: {job.error}")

    out = Path(job.path)
    credits = out.with_suffix(".credits.txt")
    lines = [f"Remix of {footage or f'{len(clips)} clips'}", "References: " + ", ".join(refs),
             f"Fingerprint: {describe(fp)}", ""]
    if mx:
        lines += ["Music (paste in the caption — the licence asks for it):", "  " + mx["credit"], ""]
    lines += ["Shots:"] + [f"  {p.role:6} {p.shot.clip_name} {p.start:6.2f}–{p.end:6.2f}  {p.why}" for p in plan.picks]
    credits.write_text("\n".join(lines) + "\n")
    say(f"done in {time.time() - t0:.0f} s → {out}")
    stage("done", 1.0)
    return {"path": str(out), "credits": str(credits), "board": board, "plan": plan, "music": mx, "mix": mix,
            "fingerprint": fp, "captions": caps, "style": style, "seconds": round(time.time() - t0, 1)}


def _watch(job, stage) -> None:
    while job.stage not in ("done", "error", "cancelled"):
        stage("rendering", 0.45 + 0.55 * job.progress)
        time.sleep(0.5)


# --------------------------------------------------------------------------
# as a job, for the web: one thread, polled; the result lands on the session
# --------------------------------------------------------------------------

class Job:
    def __init__(self, refs: list[str], opts: dict) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.refs = refs
        self.opts = opts
        self.stage = "queued"          # queued | references | choosing | music | rendering | done | error
        self.progress = 0.0
        self.error: str | None = None
        self.lines: list[str] = []
        self.result: dict | None = None
        self.started = time.time()

    def public(self) -> dict:
        r = self.result or {}
        mx = r.get("music")
        return {"id": self.id, "stage": self.stage, "progress": round(self.progress, 3), "error": self.error,
                "lines": self.lines[-6:], "elapsed": round(time.time() - self.started, 1),
                "file": Path(r["path"]).name if r.get("path") else None,
                "seconds": r.get("seconds"),
                "music": {"title": mx["track"].title, "bpm": mx["bpm"], "credit": mx["credit"]} if mx else None,
                "fingerprint": describe(r["fingerprint"]) if r.get("fingerprint") else None,
                "shots": len(r["plan"].picks) if r.get("plan") else None}


JOBS: dict[str, Job] = {}


def start(refs: list[str], clips: dict[str, dict], cut: tuple[set, dict] | None, opts: dict,
          on_done=None) -> Job:
    """Run make() in a thread. `on_done(job)` is called with the lock-free result;
    the caller puts it on the session."""
    job = Job(refs, opts)
    JOBS[job.id] = job

    def stage(name: str, p: float) -> None:
        job.stage, job.progress = name, max(job.progress, p) if name == job.stage else p

    def run() -> None:
        try:
            job.result = make(refs, None, opts.get("name") or "Remix", opts.get("length"), opts.get("title"),
                              opts.get("sub"), opts.get("moods"), opts.get("look", True), opts.get("sfx", True),
                              say=job.lines.append, clips=clips, cut=cut, stage=stage, judge=opts.get("judge"))
            if on_done:
                on_done(job)
            job.stage, job.progress = "done", 1.0
        except Exception as e:  # noqa: BLE001 -- shown to the creator verbatim
            job.stage, job.error = "error", str(e)

    threading.Thread(target=run, daemon=True).start()
    return job


def session_ops(result: dict) -> list[dict]:
    """The finished remix as ops on the working storyboard: the board itself,
    and its words as overlays, so the editor shows what the file shows."""
    ops: list[dict] = [{"op": "choose_option", "option": "remix", "snapshot": result["board"]}]
    # The sound and the grade go onto the board too, so editing the remix
    # and exporting again gives the same film, not a quieter, ungraded one.
    mx, mix = result.get("music"), result.get("mix")
    if mx and mix:
        ops.append({"op": "set_music", "track": mx["track"].id,
                    **{k: mix[k] for k in ("in", "gain", "original", "level", "fade_out", "duck", "sfx") if k in mix}})
    look = (result.get("style") or {}).get("look")
    if look:
        ops.append({"op": "apply_style", "traits": ["look"], "name": "remix", "ref": result["style"].get("ref"),
                    "lut": look["lut"], "strength": look.get("strength", 1.0), "look_words": look.get("words", [])})
    for c in result.get("captions", []):
        if c["kind"] == "title":
            ops.append({"op": "add_overlay", "kind": "title", "text": c["text"], "sub": c.get("sub", ""),
                        "anchor": {"to": "edit"}, "at": 0.0, "dur": round(c["end"] - c["start"], 2), "anim": "rise"})
        elif c["kind"] == "scene":
            ops.append({"op": "add_overlay", "kind": "part", "text": c["text"], "pos": "top", "size": "S",
                        "start": c["start"], "dur": round(c["end"] - c["start"], 2), "anim": "rise"})
    return ops


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="reference reels + your shoot -> one short, in their style")
    ap.add_argument("--ref", action="append", required=True, help="reference video: a link or a file (repeat)")
    ap.add_argument("--footage", required=True, help="folder of your clips")
    ap.add_argument("--name", default="Remix")
    ap.add_argument("--length", type=float, help="seconds; default: the references' length")
    ap.add_argument("--title", help="the words over the hook, e.g. 'a day in my life at Columbia'")
    ap.add_argument("--sub", help="a line under the title")
    ap.add_argument("--mood", action="append", help="music search words (repeat)")
    ap.add_argument("--no-look", action="store_true", help="don't borrow the references' grade")
    ap.add_argument("--no-sfx", action="store_true")
    a = ap.parse_args(argv)
    try:
        make(a.ref, a.footage, a.name, a.length, a.title, a.sub, a.mood, not a.no_look, not a.no_sfx)
    except (ValueError, RuntimeError) as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
