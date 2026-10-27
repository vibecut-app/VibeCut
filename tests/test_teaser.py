"""A vlog opens on glimpses of what's coming, then the title (make.teaser).

The side-by-side of 2026-10-26: both travel vlogs open on a reason to keep
watching (Seoul on a "preview" of later moments, Tokyo on why she went);
ours opened on "A day in my life" over the first shot. Each fixture differs
from its control in one respect:

- a vlog with five later stops gets one glimpse from each, in the day's
  order, never someone talking; a short (which opens on its hook and drop),
  a copied reel, and a vlog with only two later stops get none;
- a shot filmed with seconds to spare gives a glimpse outside the seconds
  the body shows; one filmed exactly to its body window gives the middle of
  them (control);
- on the beat each glimpse is a whole number of beats inside the seconds it
  was given, and the music's drop lands at the teaser's end, not the hook's;
- on the board the glimpses are their own part, first, with their own keys
  and the teaser mark: the repeat check leaves them alone but still drops a
  real repeat (control);
- the title comes in after the teaser, over the hook, and the first stop's
  line still sits on the first stop.

    python tests/test_teaser.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-teaser-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def shot(sid: str, hour: int, filmed=(0.0, 8.0), worth=0.5, labels=None):
    return SimpleNamespace(id=sid, start=filmed[0], end=filmed[1], clip_id=sid, clip_name=sid, when=datetime(2026, 9, 22, hour, 0),
                           gps=None, labels=labels or {}, worth=worth, score=worth, activity=10.0, vec=None)


def pick(s, a=2.0, b=5.0, role="hero", si=0):
    from web.backend import select as sel
    return sel.Pick(s, role, a, b, s.score, "", si)


def day(n_stops: int, tight: str | None = None):
    """A hook and n stops, two shots each: the second the stronger. `tight`
    names a shot filmed exactly to its body window."""
    from web.backend import select as sel
    sessions = []
    for i in range(n_stops):
        weak = shot(f"s{i}a", 8 + i, worth=0.3)
        strong = shot(f"s{i}b", 8 + i, worth=0.8, filmed=(2.0, 5.0) if tight == f"s{i}b" else (0.0, 8.0))
        sessions.append([pick(weak, si=i), pick(strong, si=i)])
    hook = [pick(shot("hook", 12, worth=0.9), 1.0, 4.0, role="hook")]
    return sel.Plan(hook=hook, sessions=sessions, titles=[f"stop {i}" for i in range(n_stops)])


def main() -> int:
    from web.backend import board as bd, brief, make, remix, select as sel, vlog

    vlog_fp = make.fingerprint("wide", "balanced", 90.0)

    print("who gets a teaser")
    plan = day(6)
    n = make.teaser(plan, "wide", vlog_fp, talking=set())
    ids = [p.shot.id for p in plan.teaser]
    check("a vlog with five later stops: one glimpse from each, the strongest, in the day's order",
          n == 5 and ids == ["s1b", "s2b", "s3b", "s4b", "s5b"], str(ids))
    check("…never from the first stop (it plays straight after the title)", "s0b" not in ids)
    talk = day(6)
    make.teaser(talk, "wide", vlog_fp, talking={"s3b"})
    check("someone talking is never a glimpse: that stop offers its quiet shot", [p.shot.id for p in talk.teaser][2] == "s3a",
          str([p.shot.id for p in talk.teaser]))
    for fmt, fp, why in (("short", make.fingerprint("short", "fast", 30.0), "a short"),
                         ("wide", {**vlog_fp, "refs_used": True}, "a copied reel")):
        p_ = day(6)
        check(f"control: {why} gets none", make.teaser(p_, fmt, fp) == 0 and p_.teaser == [])
    few = day(3)
    check("control: two later stops aren't a preview", make.teaser(few, "wide", vlog_fp) == 0)

    print("its seconds")
    plan = day(6, tight="s3b")
    make.teaser(plan, "wide", vlog_fp)
    body = {p.shot.id: p for s in plan.sessions for p in s}
    g = {p.shot.id: p for p in plan.teaser}
    out = g["s1b"]
    check("a shot with seconds to spare: the glimpse uses seconds the body doesn't show",
          out.end <= body["s1b"].start + 1e-6 or out.start >= body["s1b"].end - 1e-6, f"{out.start}-{out.end} vs body 2.0-5.0")
    inside = g["s3b"]
    check("control: a shot filmed exactly to its window gives the middle of it",
          body["s3b"].start <= inside.start and inside.end <= body["s3b"].end, f"{inside.start}-{inside.end}")

    print("on the beat")
    period = 0.5
    vlog.phrase(plan, {}, period, vlog_fp, set())
    beats = [round(p.duration / period, 3) for p in plan.teaser]
    check("each glimpse is a whole number of beats", all(abs(b - round(b)) < 1e-6 and b >= 1 for b in beats), str(beats))
    check("…inside the seconds it was given", all(p.room[0] - 1e-6 <= p.start and p.end <= p.room[1] + 1e-6 for p in plan.teaser))
    tease = sum(p.duration for p in plan.teaser)
    check("the drop goes at the teaser's end, not the hook's", abs(make.opening_s(plan) - tease) < 1e-6 and tease > 0,
          f"{make.opening_s(plan)} vs {tease}")
    bare = day(6)
    check("control: no teaser, the drop at the hook's end", abs(make.opening_s(bare) - 3.0) < 1e-6)

    print("on the board")
    board = remix.board_of(plan, vlog_fp, "x")
    first = board["beats"][0]
    keys = [bd.key(e) for bt in board["beats"] for e in bt["shots"]]
    check("the glimpses are their own part, first", first["id"] == bd.TEASER_BEAT and len(first["shots"]) == 5, first["title"])
    check("…each with its own key, every key on the board once", len(keys) == len(set(keys)), str([k for k in keys if keys.count(k) > 1]))
    check("…and the teaser mark", all(e.get("teaser") for e in first["shots"]))
    check("the board's opening is the teaser", abs(bd.opening_s(board) - tease) < 1e-3, f"{bd.opening_s(board)} vs {tease}")
    cat = SimpleNamespace(shots={s.id: SimpleNamespace(**{**vars(s), "lean": False}) for s in
                                 [p.shot for p in plan.picks]})
    brief_alike = brief.alike
    brief.alike = lambda a, b: a.id == b.id      # Vision's look-alike, as the same shot always is
    try:
        drops, _ = brief.repeat_ops(board, cat)
        check("the repeat check leaves the glimpses alone", drops == [], str(drops))
        board["beats"][1]["shots"].append({"id": "s4b", "start": 2.0, "end": 5.0})
        drops, _ = brief.repeat_ops(board, cat)
        check("control: a real repeat of a body shot is still dropped", len(drops) == 1, str(drops))
    finally:
        brief.alike = brief_alike

    print("the taste pick's other opening")
    from web.backend import tastepick
    swap = day(6)
    make.teaser(swap, "wide", vlog_fp)
    for sess in swap.sessions:
        for p_ in sess:
            p_.role = "hero"
    ru = tastepick._runner_up(swap)
    check("trying another opening never picks a shot the teaser already glimpses (it would play twice in a row)",
          ru is not None and ru.shot.id not in {p_.shot.id for p_ in swap.teaser}, ru.shot.id if ru else "none")
    plain = day(6)
    for sess in plain.sessions:
        for p_ in sess:
            p_.role = "hero"
    check("control: with no teaser it takes the strongest hero", tastepick._runner_up(plain).shot.id in {"s0b", "s1b", "s2b", "s3b", "s4b", "s5b"})

    print("the title after it")
    caps = remix.captions(plan, "a day in my life", None, phrases=[f"line {i}" for i in range(6)], clock=False)
    title = next(c for c in caps if c["kind"] == "title")
    hook_end = tease + sum(p.duration for p in plan.hook)
    check("the title comes in when the teaser ends, over the hook", abs(title["start"] - tease) < 1e-3 and abs(title["end"] - hook_end) < 1e-3,
          f"{title['start']}–{title['end']}")
    first_line = next(c for c in caps if c["kind"] == "scene")
    check("the first stop's line sits on the first stop", abs(first_line["start"] - hook_end) < 1e-3, f"{first_line['start']} vs {hook_end}")
    ops = make.ops(plan, vlog_fp, None, "wide", "cozy", "A day in my life", set())
    t_op = next(o for o in ops if o.get("kind") == "title")
    check("on the board the title is placed there too", abs(t_op["at"] - round(tease, 2)) < 0.011, str(t_op["at"]))
    swell = vlog.swells(plan)
    check("the music swells at the first scene change after the teaser", swell and swell[0][0] >= hook_end, str(swell[:1]))

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
