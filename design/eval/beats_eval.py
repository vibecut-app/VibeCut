"""The beat sheet against the scene grammar, on the real shoot.

2026-11-10, the user: Make "doesnt understand how to develop films like a
filmmaker, it just takes the final taste and turn it into a mashed video".
beats.py plans the spine first. This runs Make on the creator's shoot from
the index cache twice -- the beat sheet on, then off (VIBECUT_BEATS=0, the
scene grammar of 2026-10-24) -- with the cached Openverse tracks as the
music pool, and reports for each:

- the taste model's score of the made board and where it falls among the
  good vlogs' own scores (as house_style.py does), and which cut it chose;
- the spine as made, beside the pros' (beats.measured): chapters and their
  moments, the peak against a typical chapter, the last against it, how
  many chapters open on a wide look, where the strongest moment sits in its
  chapter, what the video ends on.

    .venv/bin/python design/eval/beats_eval.py [--frames tall,wide] [--out file.json] [--synthetic]

Nothing is paid (no key, judge off); nothing is changed. --synthetic runs
it on tests/test_beats.py's made-up day, to check the script itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "design" / "eval"))
os.environ.setdefault("VIBECUT_CACHE", os.path.expanduser("~/.cache/vibecut"))
os.environ.setdefault("VIBECUT_EXPORTS", "/tmp/vibecut-beats-eval")
os.environ.setdefault("VIBECUT_MOMENTS", "0")
os.environ.setdefault("VIBECUT_REMIX_JUDGE", "0")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

import numpy as np  # noqa: E402

from taste import describe as ds, model as tm  # noqa: E402
from web.backend import beats, board as bd, make, tastepick, vlog  # noqa: E402

GROUP = {"wide": "long", "tall": "long", "short": "short"}
SECONDS = {"wide": 90.0, "tall": 90.0, "short": 45.0}


def spine(plan) -> dict:
    """The made video's spine, in the pros' terms."""
    chs = [s for s in plan.sessions if s]
    if not chs:
        return {}
    lens = [sum(p.duration for p in c) for c in chs]
    med = float(np.median(lens))
    worth = lambda p: float(p.shot.worth) if p.shot.worth is not None else p.score  # noqa: E731
    best_at = []
    for c in chs:
        if len(c) > 1:
            k = max(range(len(c)), key=lambda i: worth(c[i]))
            best_at.append(round(k / (len(c) - 1), 2))
    return {"chapters": len(chs), "moments": [len(c) for c in chs],
            "seconds": [round(x, 1) for x in lens],
            "peak_x": round(max(lens) / med, 2) if len(lens) >= 3 else None,
            "last_x": round(lens[-1] / med, 2) if len(lens) >= 3 else None,
            "opens_wide": round(float(np.mean([vlog.shot_size(c[0].shot) == "wide" for c in chs])), 2),
            "strongest_at": best_at, "strongest_last2": round(float(np.mean([x >= 1 - 1.5 / max(len(c) - 1, 1)
                                                                           for x, c in zip(best_at, [c for c in chs if len(c) > 1])])), 2) if best_at else None,
            "ends_on": getattr(chs[-1][-1], "job", None) or ("talk" if chs[-1][-1].shot.faces else "b-roll"),
            "jobs": [[p.job for p in c] for c in chs] if any(p.job for c in chs for p in c) else None}


def made(clips, cut_, fmt, pace, tracks, beats_on: bool) -> dict:
    import threading
    os.environ["VIBECUT_BEATS"] = "1" if beats_on else "0"
    done = threading.Event()
    job = make.start(clips, cut_, fmt, pace, "cozy", "A day", SECONDS[fmt], tracks, None, None, lambda j: done.set())
    done.wait(600)
    if job.error:
        raise RuntimeError(job.error)
    return job.result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="tall,wide")
    ap.add_argument("--out")
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    if a.synthetic:
        os.environ["VIBECUT_BED"] = "0"
        sys.path.insert(0, str(ROOT / "tests"))
        import test_beats
        clips, cut_, pace, tracks = test_beats.day(), (set(), {}), "balanced", []
    else:
        import house_style as hs
        from web.backend import cut, tempo
        clips, rough = hs.shoot()
        cut_ = cut.for_story(rough)
        pace = tempo.read(list(clips.values()), cut_)["pace"]
        tracks = hs.pool()
    cat = bd.Catalog.from_clips(list(clips.values()))
    pros = {g: beats.measured(g) for g in ("long", "short")}
    report = {"clips": len(clips), "pace": pace, "tracks": len(tracks),
              "pros": {k: pros["short"][k] for k in ("chapter_shots", "peak", "last", "opens_setup", "payoff_last2",
                                                     "ends_signoff", "ends_payoff", "videos", "creators")},
              "frames": {}}
    for fmt in a.frames.split(","):
        model = tm.load(GROUP[fmt], personal=False)
        good = []
        if model is not None and not a.synthetic:
            import house_style as hs
            good = hs.good_scores(model, GROUP[fmt])
        out = {}
        descs: dict = {}
        for name, on in (("beat_sheet", True), ("scene_grammar", False)):
            res = made(clips, cut_, fmt, pace, tracks, on)
            board = tastepick.board_of(res["ops"], cat)
            mx = res.get("music")
            desc = ds.from_board(board, clips, cat, fmt, track=mx["track"] if mx else None)
            score = model.score(desc) if model else None
            above = (sum(g < score for g in good) / len(good)) if good and score is not None else None
            if model is not None:
                descs[name] = desc
            out[name] = {"score": None if score is None else round(score, 3),
                         "above_share_of_good": None if above is None else round(above, 2),
                         "taste_pick": (res.get("taste_pick") or {}).get("name"),
                         "seconds": round(res["plan"].duration, 1), "spine": spine(res["plan"]),
                         "reply": res.get("reply")}
            print(f"== {fmt} {name}: score {out[name]['score']}, above {above and round(100 * above)}% of the good vlogs, "
                  f"taste pick {out[name]['taste_pick']}", file=sys.stderr)
            print("   " + json.dumps(out[name]["spine"], default=str)[:600], file=sys.stderr)
        if len(descs) == 2:
            # what the model saw differently: the readings that moved the score most
            out["why"] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in e.items()}
                          for e in model.explain(descs["beat_sheet"], top=6, against=descs["scene_grammar"])]
            print("   why: " + "; ".join(f"{e['feature']} {e['effect']:+.2f} ({e['value']} vs {e['typical']})" for e in out["why"]),
                  file=sys.stderr)
        if good:
            out["good_scores"] = [round(min(good), 2), round(float(np.median(good)), 2), round(max(good), 2)]
        report["frames"][fmt] = out
    text = json.dumps(report, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
