"""Make picks with the taste model: does it keep the cut that reads best,
and never lose the video?

Synthetic shoot (40 clips over a morning, noon and evening; some talk to
the lens, the rest is the day) and a synthetic 123 BPM track with a drop,
as in test_bed. The model is trained here on the synthetic "real" edits of
test_taste_model (straight cuts, held openings) and saved to a temp model
folder. Then:

1. off until a model exists, and VIBECUT_TASTE=0 turns it off;
2. the variants are the same twice, today's edit first, at most 8, and the
   picker's own rebuild of today's edit is today's ops exactly (its re-fit
   to the track is make.music's);
3. Make with the model lands a report and ops that apply with nothing
   skipped; every variant is a different cut;
4. the one-respect pair: a model that only likes a held opening picks the
   held-opening cut and says so in the reply; the look's joins are never a
   variant (a machine "straight cuts" would be kept as the creator's own
   pick through a later look change), and a board's swipe reads as a cut;
   a model with no opinion keeps today's edit;
5. VIBECUT_TASTE=0 and a picker that raises both give today's edit, made;
6. the picker's added time for ~40 shots is measured (target < 3 s).

    python tests/test_tastepick.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# the synthetic "real" edits; that module points VIBECUT_CACHE at its own temp dir on import,
# so it goes first and this test's own folders are set after it
from tests import test_taste_model as gen  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vibecut-tastepick-"))
os.environ["VIBECUT_CACHE"] = str(TMP / "cache")
os.environ["VIBECUT_EXPORTS"] = str(TMP / "out")
os.environ["VIBECUT_BED"] = "0"
os.environ["VIBECUT_REMIX_JUDGE"] = "0"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ.pop("VIBECUT_TASTE", None)

import numpy as np  # noqa: E402

from cutgrammar import music as mu  # noqa: E402
from taste import describe as ds, model as tm  # noqa: E402
from tests.test_bed import BPM, _track  # noqa: E402
from web.backend import board as bd, make, oai, tastepick  # noqa: E402

oai.ENV_FILE = TMP / "no.env"       # a real key in web/.env on her Mac must never be found here

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


# --------------------------------------------------------------------------
# the shoot
# --------------------------------------------------------------------------

LABELS = [["food", "plate"], ["street", "building"], ["coffee", "cup"], ["train", "window"], ["sky", "tree"],
          ["laptop", "desk"], ["market", "crowd"], ["stairs", "path"], ["sunset", "ocean"], ["flower", "garden"]]
T0 = datetime(2026, 9, 20, 8, 0)


def _clip(i: int, of: int, rng: np.random.Generator) -> dict:
    """One 8 s clip, one shot. Every fourth is someone talking into the lens."""
    dur = 8.0
    n = int(dur)
    talk = i % 4 == 1
    when = T0 + timedelta(hours=(0, 4, 10)[i * 3 // of], minutes=i % 20)
    emb = rng.normal(size=32)
    cid = f"clip{i:07d}"
    return {
        "id": cid, "name": f"IMG_{4400 + i}.MOV", "duration": dur,
        "capture_time": when.strftime("%Y-%m-%dT%H:%M:%S") + "+0900", "gps": None,
        "shots": [{"index": 0, "start": 0.0, "end": dur, "thumb": "shot000.jpg", "best_t": dur / 2,
                   "quality": round(float(rng.uniform(0.5, 0.95)), 3), "aesthetic": round(float(rng.uniform(-0.2, 0.7)), 3),
                   "utility": False, "labels": [[l, 0.8] for l in (["people", "adult"] if talk else LABELS[i % 10])],
                   "faces": 1 if talk else 0, "face_area": 0.2 if talk else 0.0,
                   "embedding": [float(x) for x in emb], "activity": float(rng.uniform(5, 30))}],
        "signals": {"duration": dur, "quality": [0.7] * n, "sharpness": [0.6] * n, "luma": [0.5] * n,
                    "contrast": [0.5] * n, "motion": [float(x) for x in rng.uniform(2, 20, n)],
                    "subject": [float(x) for x in rng.uniform(0.1, 0.9, n)], "edge": [0.3] * n,
                    "speech": [0.8 if talk else 0.0] * n, "voiced": [[0.0, dur]] if talk else [], "thumb": [0.5] * 144},
        "faces": [[0.85, 0.0, 1, 0.9] if talk else [0.0, 0.0, 0, 0.0] for _ in range(n)],
        "sound": {"voice": [0.8 if talk else 0.05] * n, "music": [0.1] * n, "laughter": [0.0] * n},
    }


def shoot(n: int = 40) -> dict[str, dict]:
    rng = np.random.default_rng(5)
    clips = [_clip(i, n, rng) for i in range(n)]
    return {c["id"]: c for c in clips}


def train() -> tm.Model:
    descs, who = gen.shoot("short", range(4), per=3)
    model, _ = tm.train(descs, "short", who, seed=0)
    return model


def only(model: tm.Model, weights: dict[str, float]) -> tm.Model:
    """The same model with an opinion on these features alone."""
    m = tm.Model.from_json(model.to_json())
    m.w = np.zeros_like(m.w)
    for k, v in weights.items():
        m.w[m.names.index(k)] = v
    m.u = np.zeros_like(m.w)
    return m


def run(clips: dict, pool: list, look: str, fmt: str = "short", music: bool = True) -> make.Job:
    done = threading.Event()
    job = make.start(clips, (set(), {}), fmt, "fast", look, "A day in Tokyo", 60.0, None, None, False,
                     lambda j: done.set(), want_music=music)
    done.wait(120)
    return job


def applies(ops: list[dict], clips: dict) -> tuple[dict, list]:
    s = bd.Session()
    t = s.add({"kind": "direct", "text": "Made your video", "ops": ops}, bd.Catalog.from_clips(list(clips.values())),
              lambda d: None)
    return s.board, t.skipped


def main() -> int:
    clips = shoot()
    d = TMP / "music"
    d.mkdir(parents=True)
    _track(str(d / "beat.wav"), 240.0, BPM, loud_from=24.0)
    pool = mu.LocalFolderSource(str(d)).list()
    from web.backend import bed
    bed.candidates = lambda pace, own, progress=None: (pool, "a test track")
    tm.MODEL_DIR = TMP / "model"

    print("off until a model is trained")
    check("no model file: off", not tastepick.enabled("short"))
    base_job = run(clips, pool, "cozy")
    check("…and Make is today's Make", base_job.stage == "done" and base_job.result["taste_pick"] is None,
          str(base_job.error))
    base_ops = base_job.result["ops"]

    t0 = time.time()
    model = train()
    tm.save(model, tm.MODEL_DIR / "short.json")
    print(f"  (trained the tiny model in {time.time() - t0:.1f} s)")
    check("a trained short model turns it on for shorts", tastepick.enabled("short"),
          f"leave-one-creator-out {model.report.get('loco')}")
    weak = tm.Model.from_json(model.to_json())
    weak.report = {**weak.report, "loco": tastepick.MIN_LOCO - 0.1}
    tm.save(weak, tm.MODEL_DIR / "short.json")
    check("…not one that can't yet tell real from damaged on unseen creators", not tastepick.enabled("short"))
    tm.save(model, tm.MODEL_DIR / "short.json")
    check("…and on again with the better one", tastepick.enabled("short"))
    check("…not for a vlog, whose group has none", not tastepick.enabled("tall"))
    os.environ["VIBECUT_TASTE"] = "0"
    check("VIBECUT_TASTE=0 turns it off", not tastepick.enabled("short"))
    os.environ.pop("VIBECUT_TASTE")

    print("the variants")
    fp = make.fingerprint("short", "fast", 60.0)
    plan = make.moments(clips, (set(), {}), fp, judge=False)
    make.end_strong(plan)
    raw = tastepick.copy_plan(plan)

    def snap(p) -> list:
        return [[(x.shot.id, x.start, x.end, x.role) for x in p.hook]] + \
            [[(x.shot.id, x.start, x.end, x.role) for x in s] for s in p.sessions]
    raw_before = snap(raw)
    mx, _ = make.music(clips, plan, fp, "fast", None, pool=pool)
    v1 = tastepick.variants(raw, fp, "short", "hype", mx)
    v2 = tastepick.variants(tastepick.copy_plan(raw), fp, "short", "hype", mx)
    names = [v["name"] for v in v1]
    check("the same plan gives the same variants", v1 == v2, str(names))
    check("today's edit first, at most 8", names[0] == "today" and 2 <= len(v1) <= tastepick.MAX_VARIANTS, str(names))
    check("every variant says what it changes", all(v.get("says") for v in v1))
    check("the look's joins are never a variant: they'd outlive a later look change", not any(
        "straight" in v["name"] for look in ("hype", "cozy", "clean") for v in tastepick.variants(raw, fp, "short", look, mx)))
    talking = make.tempo.talking(list(clips.values()), make.sb.usable(make.sb.shots_from_clips(list(clips.values()), (set(), {})))[0])
    lines = make.words(plan, "A day in Tokyo", fp=fp)
    base_ops2 = make.ops(plan, fp, mx, "short", "hype", "A day in Tokyo", talking, lines=lines)
    today = tastepick.build({"name": "today"}, raw, clips, fp, mx, "short", "hype", "A day in Tokyo", talking, lines)
    check("the picker's rebuild of today's edit is today's ops exactly", today is not None and today[2] == base_ops2)
    for v in v1:
        tastepick.build(v, raw, clips, fp, mx, "short", "hype", "A day in Tokyo", talking, lines)
    check("…and building every variant leaves the plan it was given alone", snap(raw) == raw_before)
    swapped = tastepick.build({"name": "runner_up_hook"}, raw, clips, fp, mx, "short", "hype", "A day in Tokyo", talking, lines)
    if swapped:
        ids = [p.shot.id for p in swapped[0].picks]
        check("another hook: still never the same shot twice", len(ids) == len(set(ids))
              and swapped[0].hook[0].shot.id != plan.hook[0].shot.id and plan.hook[0].shot.id in ids)
    # the hook alone changes: the old one goes back where it was filmed, the
    # others (and the ending make.end_strong chose) keep their order
    alone = tastepick.copy_plan(raw)
    if tastepick._swap_hook(alone, clips):
        new_id, old_id = alone.hook[0].shot.id, raw.hook[0].shot.id
        kept = [[i for i in s if i not in (new_id, old_id)] for s in tastepick._ids(alone)]
        was = [[i for i in s if i not in (new_id, old_id)] for s in tastepick._ids(raw)]
        check("another hook: every other shot keeps its order, the ending too", kept == was
              and tastepick._ids(alone)[-1][-1] == tastepick._ids(raw)[-1][-1], str(tastepick._ids(alone)[-1]))

    print("Make with the model")
    job = run(clips, pool, "cozy")
    rep = job.result["taste_pick"] if job.result else None
    check("Make is done and carries the report", job.stage == "done" and rep and "picked" in rep, str(job.error or rep))
    if rep and "picked" in rep:
        board, skipped = applies(job.result["ops"], clips)
        check("its ops apply with nothing skipped", board and board.get("beats") and not skipped, str(skipped))
        check("every variant was scored (and any cut with a second part changed counted too)",
              rep["of"] >= len(rep["variants"]) >= 2 and all(np.isfinite(v["score"]) for v in rep["variants"]),
              str(rep["variants"]))
        check("the winner is today's or beats it by the margin", rep["picked"] == 0
              or rep["score"] >= rep["base_score"] + tastepick.MIN_GAIN, f"{rep['name']}: {rep['score']} vs {rep['base_score']}")
        check("the picked plan is the one the ops were made from", job.result["plan"].hook[0].shot.id
              == job.result["ops"][0]["snapshot"]["beats"][0]["shots"][0]["id"])
        print(f"  (picked {rep['name']}; {rep['variants']}; {rep['elapsed']} s)")

    job = run(clips, pool, "cozy", music=False)
    rep = (job.result or {}).get("taste_pick") or {}
    board, skipped = applies(job.result["ops"], clips) if job.result else (None, ["no result"])
    check("music off: still weighed, made, nothing skipped", job.stage == "done" and "picked" in rep
          and not board.get("music") and not skipped, str(job.error or rep.get("variants")))
    check("…and no ending in beats is tried without a beat", not any(v["name"].startswith("end_") for v in rep.get("variants", [])))

    print("a model that wants a held opening")
    real = tastepick._MODELS.copy()
    held = only(model, {"opening_hold": 1.0})
    tastepick._MODELS["short"] = (tastepick._stamp("short"), held)
    for look in ("cozy", "hype"):
        job = run(clips, pool, look)
        rep = (job.result or {}).get("taste_pick") or {}
        board, skipped = applies(job.result["ops"], clips) if job.result else (None, ["no result"])
        check(f"{look}: the held opening wins, nothing skipped", rep.get("name") == "held_open" and bool(board)
              and not skipped, str(rep.get("variants")))
        check(f"{look}: the reply says so", "The taste model chose a longer-held opening" in job.result["reply"],
              job.result["reply"][-120:])
        check(f"{look}: why, in plain words", rep.get("why") and all(isinstance(w, str) and w for w in rep["why"]),
              str(rep.get("why")))
        check(f"{look}: the look's own joins are kept (no machine pick over every join)",
              not any(o.get("op") == "set_transition" and o.get("all") for o in job.result["ops"]))
        joins = ds.from_board(board, clips, None, "short")["joins"] if board else []
        check(f"{look}: a swipe is described as the cut a reel's reader would see",
              not any(j["kind"] == "swipe" for j in joins), str([(j["kind"], j.get("drawn")) for j in joins][:6]))

    print("a model with no opinion keeps today's edit")
    tastepick._MODELS["short"] = (tastepick._stamp("short"), only(model, {}))
    job = run(clips, pool, "cozy")
    rep = job.result["taste_pick"]
    check("picked today's, ops unchanged, no sentence", rep["picked"] == 0 and job.result["ops"] == base_ops
          and "taste model" not in job.result["reply"], str(rep))
    tastepick._MODELS.clear()
    tastepick._MODELS.update(real)

    print("today's edit whenever the picker can't")
    os.environ["VIBECUT_TASTE"] = "0"
    job = run(clips, pool, "cozy")
    os.environ.pop("VIBECUT_TASTE")
    check("VIBECUT_TASTE=0: today's edit, no report", job.stage == "done" and job.result["ops"] == base_ops
          and job.result["taste_pick"] is None)
    real_choose = tastepick.choose

    def broken(*a, **k):
        raise RuntimeError("the model file is corrupt")
    tastepick.choose = broken
    try:
        job = run(clips, pool, "cozy")
    finally:
        tastepick.choose = real_choose
    check("a picker that raises: the video is still made, as today", job.stage == "done"
          and job.result["ops"] == base_ops, str(job.error))
    check("…and the report says what went wrong", "corrupt" in (job.result["taste_pick"] or {}).get("error", ""))
    tm.MODEL_DIR = TMP / "nowhere"
    check("the model file going away turns it off again", not tastepick.enabled("short"))
    tm.MODEL_DIR = TMP / "model"

    print("time")
    plan = make.moments(clips, (set(), {}), fp, judge=False)
    make.end_strong(plan)
    raw = tastepick.copy_plan(plan)
    mx, _ = make.music(clips, plan, fp, "fast", None, pool=pool)
    base = make.ops(plan, fp, mx, "short", "hype", "A day in Tokyo", talking, lines=lines)
    cat = bd.Catalog.from_clips(list(clips.values()))
    t0 = time.time()
    _, _, _, rep = tastepick.choose(clips, raw, fp, mx, "short", "hype", "A day in Tokyo", talking, lines,
                                    (plan, mx, base))
    took = time.time() - t0
    t1 = time.time()
    tastepick.choose(clips, raw, fp, mx, "short", "hype", "A day in Tokyo", talking, lines, (plan, mx, base), cat=cat)
    warm = time.time() - t1
    n = len(plan.picks)
    check(f"{n} shots, {rep['of']} variants: under 3 s", took < 3.0, f"{took:.2f} s ({warm:.2f} s with the catalogue passed in)")

    print(f"\n{'all passed' if not failures else f'{len(failures)} FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
