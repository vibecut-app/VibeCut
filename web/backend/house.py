"""The house style: what the good vlogs measured, as Make's default recipe.

Why this exists (2026-10-24, the user: the competitors' videos, and ours,
are "not what I wanted" -- "how can we make that kind of vlog that people
love?"). taste/ had already measured it: 25 long vlogs by 8 creators and 34
shorts (taste/fingerprints/, taste/descriptions/). But Make cut to numbers
guessed before any of that existed (make.PRIOR), and on the creator's own
shoot a wide Make scored below every one of the good vlogs on the taste
model (design/eval/house_style.py). Four things set ours apart:

1. **Rhythm.** Good vlogs are uneven: quick shots of about a second, a
   typical one of 2.5 s, and long holds -- the 90th percentile is 5–16 s.
   Ours held every shot between 1.5 and 3.2 s, which reads as a slideshow.
2. **The beat.** About a third of their cuts land on a sound onset; the rest
   follow the action. A cut on every beat is the machine's tell.
3. **Music in parts.** They come in two kinds: a talking vlog (talk to the
   lens most of the time, music under a tenth of it) and a montage (music
   under nine-tenths, almost no talk). Either way, when someone talks to the
   lens the music steps out (a median 6% of talking time has music under it).
4. **The person.** Talk to the lens is held (3–6 s a shot), and broken up by
   quick cutaways (b-roll between talk runs at about 1.7–2 s a shot).

Every number below is read from those files when first asked for (nothing
is downloaded or decoded); the constants beside them are only what is used
when the files aren't there. Pace stretches the house median a little
either way. All of it is "better than a guess", not calibrated: popularity
stood in for "well cut" when the set was chosen (taste/README.md).
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2] / "taste"
GROUP = {"short": "short", "tall": "long", "wide": "long"}
PACE = {"fast": 0.85, "balanced": 1.0, "calm": 1.2}      # how far a pace word moves the house median [prior]

# talk to the lens, as the descriptions read it (taste/describe.py): a voice
# most of the shot, a face, looking in
VOICE_ON, FACING_ON = 0.45, 0.5
TALKING_VLOG = 0.5          # a video talking more than this share is a talking vlog
MONTAGE = 0.1               # ...less than this, a montage

# used only when taste/ has no files (a fresh checkout without the data): the
# 2026-10-24 readings of the same files, rounded
FALLBACK = {
    "long": {"shot_s": 2.48, "quick_s": 1.03, "held_s": 12.7, "rhythm_cv": 1.24, "first_cut_s": 2.97,
             "pace_trend": 0.17, "beat_hit": 0.36, "broll_s": 1.9, "talk_s": 3.7, "music_under_talk": 0.06,
             "montage_music": 0.88, "talking_music": 0.12, "n": 0},
    "short": {"shot_s": 1.07, "quick_s": 0.57, "held_s": 2.36, "rhythm_cv": 0.8, "first_cut_s": 2.43,
              "pace_trend": 0.0, "beat_hit": 0.4, "broll_s": 1.0, "talk_s": 2.4, "music_under_talk": 0.15,
              "montage_music": 0.87, "talking_music": 0.15, "n": 0},
}


def _talk(s: dict) -> bool:
    return ((s.get("voice") or 0) >= VOICE_ON and (s.get("face") or 0) > 0
            and (s.get("facing") or 0) >= FACING_ON)


@functools.lru_cache(maxsize=4)
def measured(group: str) -> dict:
    """The house numbers for 'long' or 'short', from taste/fingerprints/ (one
    number per trait over the good side) and taste/descriptions/ (shot by
    shot: what talk to the lens and music do). Falls back per number."""
    out = dict(FALLBACK[group])
    try:
        fp = json.loads((ROOT / "fingerprints" / f"{group}.json").read_text())["traits"]
    except (OSError, ValueError, KeyError):
        fp = {}
    for key, trait in (("shot_s", "shot_s"), ("quick_s", "shot_short_s"), ("held_s", "shot_long_s"),
                       ("rhythm_cv", "rhythm_cv"), ("first_cut_s", "first_cut_s"), ("pace_trend", "pace_trend"),
                       ("beat_hit", "beat_hit")):
        if trait in fp and fp[trait].get("median") is not None:
            out[key] = float(fp[trait]["median"])
    broll, talk_s, under, montage, talking = [], [], [], [], []
    for f in sorted((ROOT / "descriptions").glob("*.json")) if (ROOT / "descriptions").is_dir() else []:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        sh = d.get("shots") or []
        if d.get("group") != group or not sh or any(s.get("music") is None for s in sh):
            continue
        dur = np.array([float(s["d"]) for s in sh])
        tk = np.array([_talk(s) for s in sh])
        T = float(dur.sum()) or 1.0
        share = float(dur[tk].sum() / T)
        music = float(sum(x for x, s in zip(dur, sh) if s["music"] >= 0.5) / T)
        if (~tk).any():
            broll.append(float(np.median(dur[~tk])))
        if tk.any():
            talk_s.append(float(np.median(dur[tk])))
            under.append(float(sum(x for x, s, t in zip(dur, sh, tk) if t and s["music"] >= 0.5) / dur[tk].sum()))
        if share < MONTAGE:
            montage.append(music)
        elif share > TALKING_VLOG:
            talking.append(music)
    for key, xs in (("broll_s", broll), ("talk_s", talk_s), ("music_under_talk", under),
                    ("montage_music", montage), ("talking_music", talking)):
        if len(xs) >= 3:
            out[key] = round(float(np.median(xs)), 3)
    out["n"] = len(broll)
    return out


def recipe(fmt: str, pace: str = "balanced") -> dict:
    """The shape Make cuts to when no reel or vibe is being copied, in the
    keys make.fingerprint returns, plus `house` (the numbers above) for the
    vlog grammar. The spread is the good side's own: quick shots at p10 /
    median, held ones at p90 / median."""
    group = GROUP.get(fmt, "long")
    h = measured(group)
    med = h["shot_s"] * PACE.get(pace, 1.0)
    lo = h["quick_s"] / h["shot_s"]
    hi = h["held_s"] / h["shot_s"]
    trend = float(np.clip(h["pace_trend"], -0.3, 0.3))
    # the good vlogs' shots get a little longer towards the end (pace_trend > 0):
    # a gentle rise, still breathing a touch at the very end
    curve = [round(1.0 - trend / 2 + trend * k / 4, 3) for k in range(5)]
    curve[-1] = round(curve[-1] + 0.05, 3)
    return {"median_s": round(med, 3), "curve": curve, "spread": (round(lo, 3), round(hi, 3)),
            "hook_s": round(h["first_cut_s"], 2), "house": {**h, "group": group}}
