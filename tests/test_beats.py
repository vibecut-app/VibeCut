"""The beat sheet (beats.py): the spine first, then the moments that fit it.

A synthetic day of four stops a kilometre apart (home 8:00, café 10:00,
park 13:00, dinner 19:00), each opening on an arrival filmed wide and
weaker than the shots after it. The café has a laugh in it; the dinner
ends with someone saying goodnight to the lens. One respect changes per
pair:

1. the spine is read from the pros' vlogs (taste/descriptions), and stands
   on its fallback when they aren't there;
2. stops filmed close together join before far ones; a thin stop joins its
   nearest neighbour;
3. the chapter with the strongest moment is the peak and gets the most
   moments; move the laugh and the peak moves; the last chapter winds down;
4. a chapter opens on its arrival even though the shot after it scores
   higher (without the wide arrival, the best of the first moments opens);
5. a chapter ends on its strongest moment (raise another and that one
   ends it);
6. the video ends on the goodnight to the lens (without it, on the payoff);
7. the plan: every chapter a setup ... payoff, and the cut-smoothing
   (vlog.flow) moves only the steps; the reason to watch held
   back (never in a chapter), no shot twice; through make.moments a tall
   Make plans this way, VIBECUT_BEATS=0 and a short don't;
8. a payoff holds at least as long as the pros hold theirs;
9. the taste model's one-change cuts (tastepick.py) reorder only the steps:
   filming order, strongest last, wide first and another opening leave every
   chapter opening on its setup and ending on its payoff (a plan without a
   sheet is reordered whole, as before);
10. each chapter is held to its share of the seconds: squash the last
   chapter's shots and it comes back to its share, the total unchanged;
   without a sheet nothing moves.

    python tests/test_beats.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-beats-"))
os.environ["VIBECUT_BED"] = "0"
os.environ["VIBECUT_REMIX_JUDGE"] = "0"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


T0 = datetime(2026, 9, 22, 8, 0)
STOPS = {"home": (0, (40.800, -73.960)), "cafe": (2, (40.810, -73.960)), "park": (5, (40.820, -73.960)),
         "dinner": (11, (40.830, -73.960))}
# per stop: (labels, face area, faces, quality, talk, laugh); the first is the arrival
SHOTS = {
    "home": [(["interior_room", "window"], 0.0, 0, 0.55, False, False),
             (["people", "adult"], 0.03, 1, 0.85, False, False),
             (["cup", "tableware"], 0.0, 0, 0.75, False, False),
             (["people", "kitchen"], 0.03, 1, 0.7, False, False),
             (["book", "desk"], 0.0, 0, 0.65, False, False)],
    "cafe": [(["structure", "outdoor"], 0.0, 0, 0.55, False, False),
             (["people", "adult"], 0.03, 1, 0.85, False, False),
             (["plate", "food"], 0.0, 0, 0.8, False, False),
             (["people", "crowd"], 0.04, 2, 0.75, False, True),
             (["coffee", "cup"], 0.0, 0, 0.7, False, False),
             (["people", "adult"], 0.2, 1, 0.7, True, False)],
    "park": [(["grass", "sky"], 0.0, 0, 0.55, False, False),
             (["people", "tree"], 0.03, 1, 0.8, False, False),
             (["flower", "plant"], 0.0, 0, 0.7, False, False),
             (["dog", "grass"], 0.0, 0, 0.7, False, False),
             (["people", "path"], 0.03, 1, 0.65, False, False)],
    "dinner": [(["structure", "night_sky"], 0.0, 0, 0.55, False, False),
               (["people", "restaurant"], 0.03, 1, 0.85, False, False),
               (["plate", "dessert"], 0.0, 0, 0.8, False, False),
               (["people", "adult"], 0.03, 1, 0.7, False, False),
               (["people", "adult"], 0.2, 1, 0.65, True, False)],
}


def _clip(stop: str, k: int, spec: tuple, seed: int) -> dict:
    labels, area, faces, q, talk, laugh = spec
    hour, gps = STOPS[stop]
    when = T0 + timedelta(hours=hour, minutes=2 * k)
    dur = 8.0
    n = int(dur)
    rng = np.random.default_rng(seed)
    cid = f"{stop}{k:02d}"
    return {
        "id": cid, "name": f"IMG_{cid}.MOV", "duration": dur,
        "capture_time": when.strftime("%Y-%m-%dT%H:%M:%S") + "-0400", "gps": list(gps),
        "shots": [{"index": 0, "start": 0.0, "end": dur, "thumb": "shot000.jpg", "best_t": dur / 2,
                   "quality": q, "aesthetic": None, "utility": False, "labels": [[l, 0.8] for l in labels],
                   "faces": faces, "face_area": area, "embedding": [float(x) for x in rng.normal(size=32)],
                   "activity": 10.0 if not talk else 20.0}],
        "signals": {"duration": dur, "quality": [q] * n, "sharpness": [0.6] * n, "luma": [0.5] * n,
                    "contrast": [0.5] * n, "motion": [8.0] * n, "subject": [0.5] * n, "edge": [0.3] * n,
                    "speech": [0.8 if talk else 0.0] * n, "voiced": [[0.0, dur]] if talk else [], "thumb": [0.5] * 144},
        "faces": [[0.85, 0.0, 1, 0.9] if talk else ([0.6, 0.0, faces, 0.0] if faces else [0.0, 0.0, 0, 0.0])
                  for _ in range(n)],
        "sound": {"voice": [0.8 if talk else 0.05] * n, "music": [0.1] * n,
                  "laughter": [0.9 if (laugh and 2 <= t < 5) else 0.0 for t in range(n)]},
    }


def day(shots: dict | None = None) -> dict[str, dict]:
    out, seed = {}, 0
    for stop, specs in (shots or SHOTS).items():
        for k, spec in enumerate(specs):
            c = _clip(stop, k, spec, seed)
            out[c["id"]] = c
            seed += 1
    return out


def pool_of(clips):
    from web.backend import select as sel, storyboard as sb
    shots, _ = sb.usable(sb.shots_from_clips(list(clips.values()), (set(), {})))
    pool, _ = sel.dedupe([s for s in shots if not s.utility])
    return pool


def values(clips, pool):
    from web.backend import select as sel
    w = sel.idf(pool)
    return {s.id: sel.hero_score(s, clips, w)[0] for s in pool}


def talking_of(clips):
    from web.backend import storyboard as sb, tempo
    shots, _ = sb.usable(sb.shots_from_clips(list(clips.values()), (set(), {})))
    return tempo.talking(list(clips.values()), shots)


def main() -> int:
    from web.backend import beats, make, select as sel, vlog

    print("1. the spine, from the pros")
    long_, short = beats.measured("long"), beats.measured("short")
    check("read from the pros' vlogs, not the fallback", long_["videos"] >= 30 and short["videos"] >= 20
          and long_["creators"] >= 10, f"long {long_['videos']}/{long_['creators']}, short {short['videos']}/{short['creators']}")
    check("a peak chapter runs longer than a typical one, the last shorter",
          short["peak"] > 1.2 and long_["peak"] > 1.2 and short["last"] < 1.0, f"{short['peak']}, {short['last']}")
    check("most chapters open on where we are", short["opens_setup"] > 0.5 and long_["opens_setup"] > 0.5)
    check("a payoff holds longer than a typical shot", long_["payoff_hold"] > 1.0)
    old = beats.ROOT
    beats.ROOT = Path(tempfile.mkdtemp())
    beats.measured.cache_clear()
    fb = beats.measured("long")
    check("control: with no files, the fallback, saying it learnt from none",
          fb["videos"] == 0 and fb["peak"] == beats.FALLBACK["long"]["peak"])
    beats.ROOT = old
    beats.measured.cache_clear()

    print("2. chapters from the day's stops")
    clips = day()
    pool = pool_of(clips)
    four = beats.chapters_of(pool, 4)
    check("four stops, four chapters, in the day's order", [c[0].clip_id[:-2] for c in four] == ["home", "cafe", "park", "dinner"],
          str([c[0].clip_id for c in four]))
    three = beats.chapters_of(pool, 3)
    check("asked for three, the two filmed closest together join (home at 8, the café at 10)",
          len(three) == 3 and {s.clip_id[:-2] for s in three[0]} == {"home", "cafe"}, str([[s.clip_id for s in c] for c in three]))
    thin = {**SHOTS, "park": SHOTS["park"][:1]}
    tc = beats.chapters_of(pool_of(day(thin)), 7)
    check("a stop of one shot joins the neighbour filmed nearest (the café, not dinner)",
          len(tc) == 3 and any({"cafe", "park"} <= {s.clip_id[:-2] for s in c} for c in tc), str([[s.clip_id for s in c] for c in tc]))

    print("3. the peak and the wind-down")
    val = values(clips, pool)
    w, peak = beats.shares(four, val, short)
    check("the café, with the laugh, is the peak", peak == 1, f"{peak}, {w}")
    k = beats.seats(four, w, 16)
    check("the peak gets the most moments, the last fewer than the peak", k[1] == max(k) and k[3] < k[1], str(k))
    check("seats add up and never pass what a chapter has", sum(k) == 16 and all(a <= len(c) for a, c in zip(k, four)), str(k))
    moved = {**SHOTS, "cafe": [s[:5] + (False,) for s in SHOTS["cafe"]],
             "park": [SHOTS["park"][0], (["people", "crowd"], 0.04, 2, 0.75, False, True), *SHOTS["park"][2:]]}
    mc = day(moved)
    mp = pool_of(mc)
    _, peak2 = beats.shares(beats.chapters_of(mp, 4), values(mc, mp), short)
    check("move the laugh to the park and the park is the peak", peak2 == 2, str(peak2))

    print("4. the setup")
    talking = talking_of(clips)
    cafe = four[1]
    got = beats.fill(cafe, 4, val, clips, talking)
    check("the café opens on its arrival, though the shot after it scores higher",
          got[0][0].clip_id == "cafe00" and got[0][1] == "setup" and val["cafe00:0"] < val["cafe01:0"],
          str([(s.clip_id, j) for s, j in got]))
    no_wide = [s for s in cafe if s.clip_id != "cafe00"]
    got2 = beats.fill(no_wide, 4, val, clips, talking)
    check("control: without the wide arrival, the best of the first moments opens",
          got2[0][0].clip_id == max(no_wide[:beats.SETUP_LOOK], key=lambda s: val[s.id]).clip_id, str([(s.clip_id, j) for s, j in got2]))

    print("5. the payoff")
    check("the café ends on its strongest moment, the laugh", got[-1][0].clip_id == "cafe03" and got[-1][1] == "payoff",
          str([(s.clip_id, j) for s, j in got]))
    park = four[2]
    pg = beats.fill(park, 4, val, clips, talking)
    top = max(beats._worth(s, val) for s in park if s is not pg[0][0])
    check("the park ends on its strongest moment", pg[-1][1] == "payoff" and beats._worth(pg[-1][0], val) >= top - beats.PAYOFF_LATE,
          str([(s.clip_id, j, round(beats._worth(s, val), 3)) for s, j in pg]))
    raised = {**SHOTS, "park": [*SHOTS["park"][:2], (["flower", "plant"], 0.0, 0, 0.98, False, False), *SHOTS["park"][3:]]}
    rc = day(raised)
    rp = pool_of(rc)
    rpark = beats.chapters_of(rp, 4)[2]
    rg = beats.fill(rpark, 4, values(rc, rp), rc, talking_of(rc))
    check("raise the flowers and the flowers end the park instead", pg[-1][0].clip_id != "park02" and rg[-1][0].clip_id == "park02",
          str([(s.clip_id, j) for s, j in rg]))
    from web.backend import vlog as vg
    rank = {"wide": 0, "medium": 1, "close": 2}
    sizes = [rank[vg.shot_size(s)] for s, j in pg[1:-1]]
    check("the steps between run wide -> medium -> close", sizes == sorted(sizes), str(sizes))

    print("6. the sign-off")
    dinner = four[3]
    dg = beats.fill(dinner, 4, val, clips, talking, last=True)
    check("the day ends on the goodnight to the lens, the payoff just before it",
          dg[-1][0].clip_id == "dinner04" and dg[-1][1] == "signoff" and dg[-2][1] == "payoff", str([(s.clip_id, j) for s, j in dg]))
    quiet = {**SHOTS, "dinner": SHOTS["dinner"][:4]}
    qc = day(quiet)
    qp = pool_of(qc)
    qd = beats.chapters_of(qp, 4)[3]
    qg = beats.fill(qd, 4, values(qc, qp), qc, talking_of(qc), last=True)
    check("control: no one talking at the end, the payoff ends it", qg[-1][1] == "payoff", str([(s.clip_id, j) for s, j in qg]))
    check("control: not the last chapter, no sign-off", "signoff" not in [j for _, j in beats.fill(dinner, 4, val, clips, talking)])

    print("7. the plan")
    fp = make.fingerprint("tall", "balanced", 60.0)
    plan = beats.plan(clips, (set(), {}), fp, talking)
    jobs = [[p.job for p in s] for s in plan.sessions]
    check("every chapter opens on its setup", all(j[0] == "setup" for j in jobs if len(j) > 1), str(jobs))
    check("every chapter ends on its payoff, the last on its sign-off",
          all(j[-1] == "payoff" for j in jobs[:-1] if len(j) > 1) and jobs[-1][-1] == "signoff", str(jobs))
    ids = [p.shot.id for p in plan.picks]
    check("the reason to watch is held back: in no chapter, and no shot twice",
          plan.hook and plan.hook[0].shot.id not in [p.shot.id for s in plan.sessions for p in s] and len(ids) == len(set(ids)))
    check("the plan says its spine", any(n.startswith("Planned as") for n in plan.notes) and beats.say(plan), plan.notes[-1])
    check("a title per chapter", len(plan.titles) == len(plan.sessions))
    talking = talking_of(clips)
    made = make.moments(clips, (set(), {}), fp, judge=False, fmt="tall", talking=talking)
    check("a tall Make plans from the spine", any(p.job == "setup" for p in made.picks) and getattr(made, "sheet", None))
    mj = [[p.job for p in s] for s in made.sessions]
    check("after the cuts are smoothed, every chapter still opens on its setup and ends on its payoff or sign-off",
          all(j[0] == "setup" and j[-1] in ("payoff", "signoff") for j in mj if len(j) > 1), str(mj))
    os.environ["VIBECUT_BEATS"] = "0"
    try:
        off = make.moments(clips, (set(), {}), fp, judge=False, fmt="tall", talking=talking)
    finally:
        os.environ.pop("VIBECUT_BEATS")
    check("control: VIBECUT_BEATS=0 cuts the scene grammar of before", not any(p.job for p in off.picks)
          and not getattr(off, "sheet", None))
    sfp = make.fingerprint("short", "balanced", 30.0)
    sh = make.moments(clips, (set(), {}), sfp, judge=False, fmt="short", talking=talking)
    check("control: a short is cut as before", not any(p.job for p in sh.picks))

    print("8. the payoff's hold")
    pays = [p for p in made.picks if p.job == "payoff" and p.shot.id not in talking]
    need = fp["median_s"] * beats.measured("long")["payoff_hold"] * 0.9   # the arc's curve dips the median a touch
    check("a payoff holds at least the pros' payoff length, where it was filmed long enough",
          pays and all(p.duration >= min(need, p.shot.end - p.shot.start) - 1e-3 for p in pays),
          str([round(p.duration, 2) for p in pays]) + f" vs {need:.2f}")

    print("9. the taste pick's order changes keep the spine")
    from web.backend import tastepick as tp
    ok = lambda pl: all(j[0] == "setup" and j[-1] in ("payoff", "signoff")  # noqa: E731
                        for j in ([p.job for p in s] for s in pl.sessions) if len(j) > 1)
    check("the test bites: sorting whole chapters by filming time would move a chapter's ending",
          any(sorted(s, key=lambda p: p.shot.order)[-1] is not s[-1] for s in made.sessions if len(s) > 1))
    for name, how in (("filming order", tp._filming_order), ("strongest last", tp._strongest_last),
                      ("wide first", tp._wide_first), ("another opening", lambda pl: tp._swap_hook(pl, clips))):
        trial = tp.copy_plan(made)
        how(trial)
        check(f"{name}: every chapter still opens on its setup and ends on its payoff or sign-off", ok(trial),
              str([[p.job for p in s] for s in trial.sessions]))
    trial = tp.copy_plan(made)
    tp._filming_order(trial)
    mids = [[p.shot.order for p in s[slice(*tp._pinned(s))]] for s in trial.sessions]
    check("filming order still sorts the steps between", all(m == sorted(m) for m in mids), str(mids))
    check("a copy keeps the beat sheet, so the reply says the spine of whichever cut wins",
          beats.say(tp.copy_plan(made)) == beats.say(made) != "")
    loose = tp.copy_plan(made)
    for s in loose.sessions:
        s.sort(key=lambda p: p.shot.order)
    check("the reply says only what the cut does: chapters put back in filming order say so, not 'best moment'",
          "best moment" not in beats.say(loose) and "order it was filmed" in beats.say(loose), beats.say(loose))
    check("...and the planned cut says each opens on where you are and ends on its best moment",
          "ends on its best moment" in beats.say(made) and " · " in beats.say(made), beats.say(made))
    from types import SimpleNamespace
    mx = {"track": SimpleNamespace(title="Song"), "bpm": 100.0}
    check("a vlog's reply doesn't promise a short's speed-up into the drop",
          "speeds into the drop" not in make.say(made, fp, mx, "your folder", False, fmt="tall")
          and "speeds into the drop" in make.say(made, sfp, mx, "your folder", False, fmt="short"))
    ctrl = tp.copy_plan(off)
    tp._filming_order(ctrl)
    check("control: a plan without a sheet goes into filming order whole",
          all([p.shot.order for p in s] == sorted(p.shot.order for p in s) for s in ctrl.sessions))

    print("10. each chapter its share of the time")
    from web.backend import select as sel2
    sq = tp.copy_plan(made)
    for p in sq.sessions[-1]:
        if p.shot.id not in talking:
            p.start, p.end, p.short = sel2.window(clips, p.shot, beats.SHARE_FLOOR_S)
    before = [sum(p.duration for p in s) for s in sq.sessions]
    w = sq.sheet["weights"]
    aim = sum(before) * w[-1] / sum(w)
    after = beats.hold_shares(sq, clips, talking)
    check("a last chapter of quick shots is held to its share again", abs(after[-1] - aim) < 0.5 and before[-1] < aim - 2,
          f"{before[-1]:.1f} s -> {after[-1]:.1f} s, its share {aim:.1f} s")
    check("the seconds overall stay what they were", abs(sum(after) - sum(before)) < 0.5, f"{sum(before):.1f} -> {sum(after):.1f}")
    check("the peak runs longest", after[sq.sheet["peak"]] == max(after), str(after))
    check("talk keeps its sentence", all(abs(p.duration - q.duration) < 1e-6 for s, r in zip(made.sessions, sq.sessions)
                                         for p, q in zip(s, r) if p.shot.id in talking))
    bare = tp.copy_plan(made)
    for p in bare.sessions[-1]:
        if p.shot.id not in talking:
            p.start, p.end, p.short = sel2.window(clips, p.shot, beats.SHARE_FLOOR_S)
    del bare.sheet
    held = [round(sum(p.duration for p in s), 2) for s in bare.sessions]
    check("control: without a sheet nothing moves", beats.hold_shares(bare, clips, talking) == held)

    print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
