"""The house style per group, from the measured good vlogs.

Each trait becomes a range: the middle half of the good videos (25th–75th
percentile) and their median, so "how VibeCut should cut a long vlog" reads
as "shots of 1.9–2.6 s, median 2.2 s", not one video's habit. A trait that
was pending on a video (no Vision, no beat) is left out of that trait only.
The ending is skipped for long vlogs measured on their first minutes:
where the download stopped isn't where the creator ended.

    python -m taste.fingerprint            # writes fingerprints/<group>.json
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from . import collect

HERE = Path(__file__).parent
OUT = HERE / "fingerprints"

# A video whose typical shot is held this long is someone sitting and talking
# (Emma's "ugg season" 12 s, a channel update 29 s), not a vlog cut through a
# day. Those keep their time for words, which VibeCut leaves to talk.py; the
# house style is taken from the ones cut like vlogs, and the held ones are
# listed so a person can see what was left out. Set on the first 33 (2026-10-21).
TALK_SHOT_S = 6.0

# (name, path into the record, what it means)
TRAITS = [
    ("shot_s", ("pace", "median_s"), "typical shot length, seconds"),
    ("shot_short_s", ("pace", "p10_s"), "the quick shots (10th percentile), seconds"),
    ("shot_long_s", ("pace", "p90_s"), "the held shots (90th percentile), seconds"),
    ("cuts_per_min", ("pace", "per_min"), "cuts per minute"),
    ("rhythm_cv", ("pace", "cv"), "how uneven shot lengths are (0 = metronome)"),
    ("pace_trend", ("pace", "trend"), "shots getting shorter (<0) or longer (>0) towards the end"),
    ("first_cut_s", ("opening", "first_cut_s"), "when the first cut comes, seconds"),
    ("open_motion", ("opening", "motion_ratio"), "movement in the first 2 s vs the rest"),
    ("last_shot_s", ("ending", "last_s"), "how long the last shot is held, seconds"),
    ("cut_share", ("transitions", "share", "cut"), "share of joins that are hard cuts"),
    ("dissolve_share", ("transitions", "share", "dissolve"), "share of joins that are dissolves"),
    ("beat_hit", ("beat", "onset_hit"), "share of cuts on a sound onset"),
    ("lufs", ("lufs",), "loudness, LUFS (social ~ -14)"),
    ("warmth", ("look", "warmth"), "colour warmth (>0 warm)"),
    ("saturation", ("look", "sat"), "saturation"),
    ("contrast", ("look", "contrast"), "contrast (white minus black level)"),
    ("black", ("look", "black"), "black level (0 = deep)"),
    ("words_share", ("words", "share"), "share of time with words on screen"),
    ("words_first_s", ("words", "first_s"), "when the first words appear, seconds"),
    ("words_hold_s", ("words", "hold_s"), "how long a caption stays, seconds"),
]


def _get(rec: dict, path: tuple) -> float | None:
    v = rec
    for k in path:
        if not isinstance(v, dict) or k not in v:
            return None
        v = v[k]
    if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v):
        return float(v)
    return None


def _pending(rec: dict, path: tuple) -> bool:
    top = rec.get(path[0])
    return isinstance(top, dict) and bool(top.get("pending"))


def good_records(group: str) -> list[dict]:
    path = collect.GROUPS[group]
    rows = list(csv.DictReader(path.open())) if path.exists() else []
    ids = [r["id"] for r in rows if r.get("verdict") in ("good", "sarah") and r.get("status") == "measured"]
    out = []
    for i in ids:
        p = HERE / "measurements" / f"{i}.json"
        if p.exists():
            out.append(json.loads(p.read_text()))
    return out


def fingerprint(recs: list[dict], group: str) -> dict:
    held = [r.get("id") for r in recs if (_get(r, ("pace", "median_s")) or 0) > TALK_SHOT_S]
    recs = [r for r in recs if r.get("id") not in held]
    traits = {}
    for name, path, means in TRAITS:
        vals = []
        for r in recs:
            if _pending(r, path):
                continue
            if path[0] == "ending" and (r.get("ending_is_cutoff") or (group == "long" and r.get("measured_s", 0) >= collect.LONG_S - 1)):
                continue
            v = _get(r, path)
            if v is not None:
                vals.append(v)
        if not vals:
            continue
        a = np.array(vals)
        traits[name] = {"median": round(float(np.median(a)), 3),
                        "low": round(float(np.percentile(a, 25)), 3),
                        "high": round(float(np.percentile(a, 75)), 3),
                        "n": len(vals), "means": means}
    bands = [r["words"].get("band") for r in recs if isinstance(r.get("words"), dict) and r["words"].get("band")]
    if bands:
        traits["words_band"] = {"most": max(set(bands), key=bands.count), "n": len(bands),
                                "means": "where captions sit: bottom / middle / top"}
    return {"group": group, "videos": [r.get("id") for r in recs], "n": len(recs), "held_out": held,
            "thin": len(recs) < 8, "traits": traits}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for group in collect.GROUPS:
        fp = fingerprint(good_records(group), group)
        (OUT / f"{group}.json").write_text(json.dumps(fp, indent=1, ensure_ascii=False))
        print(group, fp["n"], "videos", "(thin)" if fp["thin"] else "")
        for k, t in fp["traits"].items():
            if "median" in t:
                print(f"  {k:15s} {t['low']:>9} – {t['high']:<9} median {t['median']:<9} n={t['n']}  {t['means']}")
            else:
                print(f"  {k:15s} {t['most']}  n={t['n']}  {t['means']}")


if __name__ == "__main__":
    main()
