"""Make against the house style: before / after, on the real shoot.

2026-10-24, the user: make the videos read like the vlogs people love. The
house style is what taste/ measured on the good vlogs (fingerprints/ +
descriptions/); this runs Make on the creator's 42-clip shoot from the index
cache (no decode, no export: the originals are in a folder this shell can't
read) with the cached Openverse tracks as the music pool, and reports

- the taste model's score of the made board, and where it falls among the
  good vlogs' own scores (taste/descriptions/, same model);
- the traits the house style names, made-vs-house, each with the good
  side's range: shot lengths (median, p10, p90, unevenness), the first cut,
  the share of time music is heard, talk to the lens and music under it,
  cuts on the beat.

    .venv/bin/python design/eval/house_style.py [--frames wide,short] [--out file.json]

Nothing is paid (no key, judge off); nothing is changed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VIBECUT_CACHE", os.path.expanduser("~/.cache/vibecut"))
os.environ.setdefault("VIBECUT_EXPORTS", "/tmp/vibecut-house-eval")
os.environ.setdefault("VIBECUT_MOMENTS", "0")
os.environ.setdefault("VIBECUT_REMIX_JUDGE", "0")

import numpy as np  # noqa: E402

from cutgrammar import music as mu, openverse  # noqa: E402
from taste import describe as ds, model as tm  # noqa: E402
from web.backend import board as bd, cut, indexer, make, tastepick, tempo  # noqa: E402

CACHE = Path(os.environ["VIBECUT_CACHE"])
SECONDS = {"wide": 90.0, "tall": 90.0, "short": 45.0}
GROUP = {"wide": "long", "tall": "long", "short": "short"}


def shoot() -> tuple[dict, object]:
    ids = os.listdir(CACHE / "clips")
    recs = [r for r in (indexer.load_indexed(c) for c in ids) if r and "sarah" in r["path"]]
    recs.sort(key=lambda r: r["capture_time"] or "")
    clips = {r["id"]: r for r in recs}
    return clips, cut.compute(clips, ask=False)


def pool() -> list[mu.Track]:
    src = mu.LocalFolderSource(str(openverse.cache_dir() / "tracks"))
    out = []
    for f in src.files():
        try:
            out.append(openverse.dress(src.one(f)))
        except Exception:  # noqa: BLE001 -- an unreadable track is left out
            pass
    return out


def run_make(clips, plan, fmt: str, pace: str, tracks) -> dict:
    done = threading.Event()
    job = make.start(clips, cut.for_story(plan), fmt, pace, "cozy", "A day", SECONDS[fmt], tracks, None, None,
                     lambda j: done.set())
    done.wait(600)
    if job.error:
        raise RuntimeError(job.error)
    return job.result


def heard(board: dict, desc: dict) -> float:
    """Share of the edit's time with music heard: from the description when
    it reads it as a share, else the bed as a yes/no."""
    return float((desc.get("music") or {}).get("on") or 0.0)


def traits(desc: dict) -> dict:
    sh = desc["shots"]
    d = np.array([s["d"] for s in sh])
    T = float(d.sum()) or 1.0
    talk = np.array([(s.get("voice") or 0) >= 0.45 and (s.get("facing") or 0) >= 0.5 and (s.get("face") or 0) > 0
                     for s in sh])
    run = best = 0.0
    for x, t in zip(d, talk):
        run = run + x if t else 0.0
        best = max(best, run)
    return {"shots": len(sh), "seconds": round(T, 1),
            "shot_s": round(float(np.median(d)), 2), "shot_short_s": round(float(np.percentile(d, 10)), 2),
            "shot_long_s": round(float(np.percentile(d, 90)), 2), "rhythm_cv": round(float(d.std() / d.mean()), 2),
            "first_cut_s": round(float(d[0]), 2), "music_heard": round(float((desc.get("music") or {}).get("on") or 0), 2),
            "talk_share": round(float(d[talk].sum() / T), 2), "talk_run_share": round(best / T, 2),
            "cuts_on_beat": (desc.get("music") or {}).get("beat")}


def house(group: str) -> dict:
    fp = json.loads((ROOT / "taste" / "fingerprints" / f"{group}.json").read_text())["traits"]
    out = {k: [fp[k]["low"], fp[k]["high"]] for k in ("shot_s", "shot_short_s", "shot_long_s", "rhythm_cv", "first_cut_s")
           if k in fp}
    out["cuts_on_beat"] = [fp["beat_hit"]["low"], fp["beat_hit"]["high"]]
    return out


def good_scores(model: tm.Model, group: str) -> list[float]:
    out = []
    for f in sorted(glob.glob(str(ROOT / "taste" / "descriptions" / "*.json"))):
        d = ds.load(f)
        if d.get("group") == group:
            try:
                out.append(model.score(d))
            except Exception:  # noqa: BLE001 -- a description the model can't read is skipped
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="wide,short")
    ap.add_argument("--out")
    a = ap.parse_args()
    clips, plan = shoot()
    feel = tempo.read(list(clips.values()), cut.for_story(plan))
    tracks = pool()
    cat = bd.Catalog.from_clips(list(clips.values()))
    report = {"clips": len(clips), "pace": feel["pace"], "tracks": len(tracks), "frames": {}}
    print(f"{len(clips)} clips, pace {feel['pace']}, {len(tracks)} cached tracks", file=sys.stderr)
    for fmt in a.frames.split(","):
        res = run_make(clips, plan, fmt, feel["pace"], tracks)
        board = tastepick.board_of(res["ops"], cat)
        mx = res.get("music")
        desc = ds.from_board(board, clips, cat, fmt, track=mx["track"] if mx else None)
        model = tm.load(GROUP[fmt], personal=False)
        score = model.score(desc) if model else None
        good = good_scores(model, GROUP[fmt]) if model else []
        below = (sum(g < score for g in good) / len(good)) if good and score is not None else None
        t = traits(desc)
        rng = house(GROUP[fmt])
        inside = {k: (rng[k][0] <= t[k] <= rng[k][1]) for k in rng if t.get(k) is not None}
        report["frames"][fmt] = {"traits": t, "house": rng, "inside": inside,
                                 "inside_n": f"{sum(inside.values())} of {len(inside)}",
                                 "score": None if score is None else round(score, 3),
                                 "good_scores": [round(min(good), 2), round(float(np.median(good)), 2), round(max(good), 2)] if good else None,
                                 "above_share_of_good": None if below is None else round(below, 2),
                                 "taste_pick": (res.get("taste_pick") or {}).get("name"),
                                 "reply": res.get("reply")}
        print(f"\n== {fmt}: score {score if score is None else round(score, 2)}"
              f" (good vlogs {report['frames'][fmt]['good_scores']}; above {below and round(100 * below)}% of them),"
              f" inside the house range on {report['frames'][fmt]['inside_n']}", file=sys.stderr)
        for k, v in t.items():
            r = rng.get(k)
            print(f"   {k:16s} {v!s:>8}" + (f"   house {r[0]:.2f}–{r[1]:.2f} {'ok' if inside.get(k) else 'OUT'}" if r else ""),
                  file=sys.stderr)
    text = json.dumps(report, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
