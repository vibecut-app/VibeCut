"""The bed under the edit: music by default, and cuts that land on its beat.

Why this exists, in editing terms: until 2026-10-10 the default path handed
over a silent edit. Every amateur tell the sound layer fixes -- the room
tone snapping off at every cut, the pile-of-clips feel -- was fixed only
for a Remix. A finished vlog has a bed under it, and its cuts sit on that
bed's beat; that is most of what "this feels edited" means to a viewer.

What happens, once a story is chosen (one undoable turn, like any edit):

1. **A fingerprint of the edit itself**, not of a reference: the tempo
   range the footage's pace asks for (PACE_BPM), the edit's own energy arc
   (how much each part moves and how fast it cuts), the first shot as the
   hook.
2. **A track**: the creator's own folder when one is set and read; else
   Openverse (Jamendo / Freesound, commercial licences only -- see
   cutgrammar/openverse.py), by moods the pace suggests. Only when that
   search hands back nothing that fits (offline, blocked, no certificates)
   does VibeCut's own pack step in (cutgrammar/songpack.py): never
   preferred, only so the edit is never left silent. Scored like a
   Remix (tempo, energy shape, the catalogue's own words, continuity); the
   track starts so its drop lands at the end of the hook.
3. **Cuts on the beat** (restyle.retime with the grid): each cut moves to
   the nearest beat within MAX_SNAP_S. Shots where someone talks keep
   their window -- a beat never cuts a sentence.
4. **The mix**: music under the original sound at MUSIC_GAIN (a vlog's
   own sounds stay up front), ducked to TALK_DUCK where someone talks,
   faded out at the end.

Nothing here is calibrated: PACE_BPM, MOODS, TALK_DUCK and the hook hold
are priors, like every threshold in cutgrammar. The pick has no model
behind it. Music never comes from a platform library (CLAUDE.md).
"""

from __future__ import annotations

import copy
import threading
import time

import numpy as np

from cutgrammar import music as mu
from cutgrammar import openverse as ov
from cutgrammar import songpack

from . import audiomix, musiclib, remix, restyle, timeline

# The tempo a cutting pace asks for [prior]. Fast is the Remix range; calm is
# a walking tempo; balanced sits between.
PACE_BPM = {"fast": (110.0, 140.0), "balanced": (85.0, 120.0), "calm": (60.0, 100.0)}
# What to ask Openverse for, by pace [prior]. One word each: the commercial-
# licence slice of the catalogue is thin, and on 2026-10-10 phrases like
# "feel good indie pop" or "chillhop" returned nothing while "happy",
# "ukulele", "calm" each returned a full page. These are tags the people who
# uploaded the tracks used; the waveform can't tell a ballad from a pop bed.
MOODS = {
    "fast": ["upbeat", "pop", "funk", "electronic", "happy", "summer"],
    "balanced": ["happy", "ukulele", "indie", "folk", "travel", "uplifting"],
    "calm": ["calm", "acoustic", "piano", "ambient", "relax", "folk"],
}
PER_MOOD = 6          # tracks fetched per mood: a first pick, not a catalogue crawl
HOOK_S = (1.0, 8.0)   # the drop lands at the end of the first shot, or this far in at most [prior]
TALK_DUCK = 0.35      # music under talking drops to this share of its gain [prior]
MIN_TALK_S = 0.8      # a duck shorter than this would be heard as a wobble, not a duck [prior]
ENERGY_POINTS = 32    # the arc, as pick_from wants it
MUSIC_GAIN = audiomix.MUSIC_GAIN
FADE_OUT_S = 2.0


# --------------------------------------------------------------------------
# what the edit asks for
# --------------------------------------------------------------------------

def fingerprint(board: dict, cat, pace: str | None) -> dict:
    """The edit's own shape, in the form remix.pick_from scores against."""
    pace = pace if pace in PACE_BPM else "balanced"
    sections = musiclib.sections(board, cat)
    e = mu.section_energy(sections)
    if len(e) >= 2:
        x = np.linspace(0, 1, len(e))
        energy = np.interp(np.linspace(0, 1, ENERGY_POINTS), x, e)
    else:
        energy = np.linspace(0.3, 1.0, ENERGY_POINTS)   # one part: assume it builds, as music does
    from . import board as bd
    first = bd.opening_s(board) or 1.5      # a teaser, else the first shot: where the drop lands
    rise = float(energy[-ENERGY_POINTS // 4:].mean() - energy[:ENERGY_POINTS // 4].mean())
    return {
        "bpm": PACE_BPM[pace], "pace": pace,
        "energy": [round(float(v), 3) for v in energy],
        "arc": "builds" if rise > 0.1 else "falls" if rise < -0.1 else "steady",
        "hook_s": round(float(np.clip(first, *HOOK_S)), 2),
        "duration": round(float(sum(s.duration for s in sections)), 1),
    }


ONLINE = "Openverse (free, credited)"
PACK = "VibeCut's own songs"


def candidates(pace: str, own: list[mu.Track] | None, progress=None) -> tuple[list[mu.Track], str]:
    """Where the track comes from: the creator's folder first, else Openverse.
    An empty Openverse answer (offline, blocked) hands over the pack instead."""
    if own:
        return list(own), "your music folder"
    moods = MOODS.get(pace if pace in MOODS else "balanced")
    try:
        pool = ov.OpenverseSource(moods, per_query=PER_MOOD, progress=progress).list()
    except Exception:  # noqa: BLE001 -- a failed search is what the pack is for
        pool = []
    if pool:
        return pool, ONLINE
    return fallback(pace, progress), PACK


def fallback(pace: str | None, progress=None) -> list[mu.Track]:
    """The built-in songs for this pace (rendered once, a few seconds each)."""
    return songpack.PackSource(pace, progress=progress).list()


_warming: set[str] = set()
_warm_lock = threading.Lock()


def prefetch(pace: str | None) -> None:
    """Warm the online catalogue for this pace while the creator is still
    looking at their footage: a cold fetch of ~36 tracks took 195 s on
    2026-10-10, a warm one is seconds. Fire and forget; one at a time per
    pace; nothing is chosen here."""
    pace = pace if pace in MOODS else "balanced"
    with _warm_lock:
        if pace in _warming:
            return
        _warming.add(pace)

    def run() -> None:
        try:
            candidates(pace, None)
        except Exception:  # noqa: BLE001 -- offline is fine; the pick will say so
            pass
        finally:
            with _warm_lock:
                _warming.discard(pace)

    threading.Thread(target=run, daemon=True).start()


def pick(fp: dict, pool: list[mu.Track], need_s: float, look: str | None = None) -> dict | None:
    """The best fit, carrying the next few as `others` (the Music panel's
    swaps, songs.py), leaned by the look and the creator's past picks."""
    from . import songs
    ranked = remix.rank_from(pool, fp, need_s + 4.0, fp["hook_s"], songs.N, songs.lean_for(look))
    if not ranked:
        return None
    mx = ranked[0]
    mx["others"] = ranked[1:]
    return mx


# --------------------------------------------------------------------------
# the turn
# --------------------------------------------------------------------------

def ducks(board: dict, talking: set[str]) -> list[list[float]]:
    """[start, end, gain] in edit seconds for every talking stretch; touching
    stretches merge so the duck doesn't pump between two sentences."""
    out: list[list[float]] = []
    for it in timeline.layout(board):
        if it["kind"] != "shot" or it["shot_id"] not in talking:
            continue
        a, b = float(it["seq_start"]), float(it["seq_end"])
        if out and a - out[-1][1] < 1e-3:
            out[-1][1] = b
        else:
            out.append([a, b, TALK_DUCK])
    return [[round(a, 3), round(b, 3), g] for a, b, g in out if b - a >= MIN_TALK_S]


def ops(board: dict, cat, mx: dict, talking: set[str]) -> tuple[list[dict], dict]:
    """The two ops of the turn: cuts onto the beat, then the bed under them.
    Returns (ops, report). Everything the ops need is decided here, so
    replay is exact (restyle's rule)."""
    track: mu.Track = mx["track"]
    out: list[dict] = []
    trial = copy.deepcopy(board)
    report = {"on_beat": 0, "shots": 0}
    phase = (track.meta.get("tempo") or {}).get("phase")
    if track.bpm and phase is not None:
        # In edit time: the track starts `in` seconds in. mx["bpm"] may be the
        # track's tempo doubled (a half-time track cut on its eighths), so the
        # grid is built from the pick, not from timeline.grid_of.
        grid = {"bpm": mx["bpm"], "phase": round((float(phase) - mx["in"]) % mx["period"], 4)}
        op = {"op": "apply_style", "traits": ["beat"], "name": "the beat", "ref": None,
              "style": {}, "grid": grid, "keep": sorted(talking)}
        report = restyle.retime(trial, cat, None, grid, talking)
        out.append(op)
    # Levelled to social volume (-14 LUFS, audiomix.write_wav), preview and
    # export alike: unlevelled, the Oct 14 school-day edit came out at -20
    # LUFS against the creator's own -15, and phones play it quiet.
    out.append({"op": "set_music", "track": track.id, "in": mx["in"], "gain": MUSIC_GAIN, "original": 1.0,
                "fade_out": FADE_OUT_S, "duck": ducks(trial, talking), "sfx": [], "level": True})
    return out, report


def say(mx: dict, report: dict, source: str, talking: int) -> str:
    """The turn's reply: what was done and what it rests on."""
    t: mu.Track = mx["track"]
    parts = [f"Music: {t.title} ({mx['bpm']:.0f} BPM, from {source}), starting so its drop lands at the end of the first shot."]
    if source == PACK:
        parts.append("The free music library couldn't be reached, so this is one of VibeCut's own songs.")
    if report.get("shots"):
        parts.append(f"{report['on_beat']} of {report['shots']} cuts moved onto the beat.")
    if talking:
        parts.append(f"{talking} shot{'s' * (talking != 1)} with someone talking kept their timing, the music dips under them.")
    parts.append("The track's a first pick, not a judgement. Undo takes the music and the beat away together.")
    return " ".join(parts)


# --------------------------------------------------------------------------
# the job: a pick can take a minute online, so it lands when it's ready
# --------------------------------------------------------------------------

class Job:
    def __init__(self) -> None:
        self.stage = "looking"     # looking | done | nothing | error
        self.why = ""
        self.source = ""
        self.done, self.total = 0, 0   # tracks read so far (online: fetched + analysed)
        self.started = time.time()
        self.result: dict | None = None

    def public(self) -> dict:
        return {"stage": self.stage, "why": self.why, "source": self.source,
                "done": self.done, "total": self.total,
                "elapsed": round(time.time() - self.started, 1)}


def start(board: dict, cat, pace: str | None, own: list[mu.Track] | None, need_s: float,
          talking: set[str], on_done) -> Job:
    """Pick in the background; `on_done(job)` gets the ops to add as a turn.
    The board passed in is a copy: the pick must not depend on later edits."""
    job = Job()
    fp = fingerprint(board, cat, pace)

    def progress(done: int, total: int) -> None:
        job.done, job.total = done, total

    def run() -> None:
        try:
            pool, job.source = candidates(fp["pace"], own, progress)
            if not pool:
                job.stage, job.why = "nothing", ("No tracks could be read from your music folder." if own
                                                 else "No free track could be found — no music this time.")
                return
            look = (board.get("look") or {}).get("id") if isinstance(board.get("look"), dict) else board.get("look")
            mx = pick(fp, pool, need_s, look)
            if mx is None and job.source == ONLINE:
                # online answered, but nothing it had fits this edit: the pack, not silence
                pool, job.source = fallback(fp["pace"], progress), PACK
                mx = pick(fp, pool, need_s, look)
            if mx is None:
                job.stage, job.why = "nothing", (f"None of the {len(pool)} tracks is long enough for this edit "
                                                 f"({need_s:.0f} s) with a steady beat — no music this time.")
                return
            turn_ops, report = ops(board, cat, mx, talking)
            job.result = {"music": mx, "ops": turn_ops, "report": report,
                          "reply": say(mx, report, job.source, len(talking))}
            job.stage = "done"
        except Exception as e:  # noqa: BLE001 -- the bed is optional; the edit stands without it
            job.stage, job.why = "error", f"Music skipped: {str(e)[:200]}"
        finally:
            on_done(job)

    threading.Thread(target=run, daemon=True).start()
    return job
