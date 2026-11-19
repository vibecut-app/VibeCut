"""Does the cut scorer learn where pros cut, and only that?

Made-up edits built to differ in one respect (taste/cuts.py):

- nothing marks the cuts (talking and movement run on regardless): the
  scorer, tested on creators it never saw, must rank the pro's moment at
  chance -- if it beat chance here it would be reading where the shot
  ends, which a phone clip in Make never shows. Every reading alone too.
- the pros cut out a quarter second after a sentence and cut in just
  before one: the scorer must find that and beat the rule, which can't
  hear words; and it is then trusted on both sides.
- the pros cut out on a burst of movement: the rule finds that as well,
  so the scorer, no better, must not be trusted.

A clip in Make and a pro's shot with the same numbers read the same; the
scorer in Make only moves the rule's window within NUDGE, only on a side
it's trusted on, and keeps the rule's choice when it can't tell. A real
file made with ffmpeg is read into a record of numbers (its cuts where
they were built, its talking where the tone was), and the collector's
`--only cuts` fetches, reads, deletes and trains.

    python tests/test_cuts.py
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-cuts-test-")

import numpy as np  # noqa: E402

from taste import collect, cuts as C  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


# --------------------------------------------------------------------------
# made-up edits
# --------------------------------------------------------------------------

def _talk(rng: random.Random, a: float, b: float) -> list[list[float]]:
    """Sentences of words over a..b, regardless of any cut."""
    out, t = [], a + rng.uniform(0, 1.5)
    while t < b:
        end = t + rng.uniform(1.0, 4.0)
        while t < min(end, b):
            w = rng.uniform(0.15, 0.6)
            out.append([round(t, 2), round(min(t + w, b), 2)])
            t += w + rng.uniform(0.05, 0.25)
        t += rng.uniform(0.6, 2.0)
    return [x for x in out if x[1] - x[0] >= 0.08]


def _grid(rng: random.Random, lo: float, hi: float, hot: int | None = None) -> dict:
    g = {}
    for k in C.grid_keys(lo, hi):
        mo = rng.uniform(25, 40) if k == hot else rng.uniform(2, 10)
        g[str(k)] = [round(mo, 3), round(rng.uniform(0.2, 0.8), 3), round(rng.uniform(0, 0.5), 3)]
    return g


def record(rng: random.Random, vid: str, creator: str, mode: str, n_shots: int = 30) -> dict:
    t, shots, voiced = 0.0, [], []
    for i in range(n_shots):
        a, b = t, t + rng.uniform(2.5, 7.0)
        if mode == "words":
            # a sentence starts 0.1 s after the cut in; the last word ends 0.25 s before the cut out
            v, s = [], a + 0.1
            while s < b - 0.6:
                w = rng.uniform(0.15, 0.5)
                v.append([round(s, 2), round(s + w, 2)])
                s += w + rng.uniform(0.05, 0.2) + (rng.uniform(0.6, 1.2) if rng.random() < 0.15 else 0.0)
            v = [x for x in v if x[1] <= b - 0.25]
            if v:
                v[-1][1] = round(b - 0.25, 2)
            voiced += [x for x in v if x[1] - x[0] >= 0.08]
        hot = C._second(b - C.GAP, "out") if mode == "motion" else None
        shots.append({"a": round(a, 3), "b": round(b, 3), "lo": round(a, 3), "hi": round(b, 3),
                      "into": "cut" if i else None, "out": "cut" if i < n_shots - 1 else None,
                      "grid": _grid(rng, a, b, hot)})
        t = b
    if mode != "words":
        voiced = _talk(rng, 0.0, t)
    return {"v": C.VERSION, "id": vid, "group": "short" if rng.random() < 0.5 else "long", "creator": creator,
            "duration": round(t, 3), "shots": shots, "voiced": voiced, "laugh": None}


def made(mode: str, seed: int, creators: int = 10, each: int = 3) -> list[dict]:
    rng = random.Random(seed)
    return [record(rng, f"{c}-{v}", f"Creator {c}", mode) for c in range(creators) for v in range(each)]


def _say(p: dict) -> str:
    return (f"{p['cuts']} cuts, scorer {p['rank']['model']:.3f}, rule {p['rank']['rule']:.3f}, "
            f"rule+words {p['rank']['words']:.3f}, gain {p['gain']:+.3f} [{p['gain_low']:+.3f}, {p['gain_high']:+.3f}]")


def learning_tests() -> None:
    print("nothing marks the cuts")
    rep = C.evaluate(made("control", 1))
    for side in ("out", "in"):
        p = rep[side]
        check(f"{side}: the scorer ranks the pro's moment at chance", abs(p["rank"]["model"] - 0.5) < 0.04, _say(p))
        check(f"{side}: not trusted", not C.wins(p))
    gs = [g for r in made("control", 2, creators=12) for g in C.groups(r)]
    worst = max(abs(np.mean([x for g in gs if g["side"] == side
                             if (x := C.rank(g["X"][:, j], g["ts"], g["true"])) is not None]) - 0.5)
                for side in ("out", "in") for j in range(len(C.NAMES)))
    check("no reading alone gives the cut away", worst < 0.04, f"worst {worst:.3f} off chance")
    check("readings of movement are there to be read",
          np.mean([np.any(g["X"][:, C.NAMES.index("motion")]) for g in gs]) > 0.3)

    print("the pros cut on the words")
    rep = C.evaluate(made("words", 3))
    for side in ("out", "in"):
        p = rep[side]
        check(f"{side}: the scorer finds the pros' moment", p["rank"]["model"] > 0.85, _say(p))
        check(f"{side}: the rule can't hear it", abs(p["rank"]["rule"] - 0.5) < 0.05)
        check(f"{side}: trusted (beats the better rule on unseen creators)", C.wins(p))

    print("the pros cut out on movement")
    rep = C.evaluate(made("motion", 4))
    p = rep["out"]
    check("the rule finds it", p["rank"]["rule"] > 0.58, _say(p))
    check("the scorer finds it too", p["rank"]["model"] > 0.58)
    check("no better than the rule: not trusted", not C.wins(p))


# --------------------------------------------------------------------------
# a clip in Make reads as a pro's shot does
# --------------------------------------------------------------------------

def make_tests() -> None:
    print("in Make")
    rng = random.Random(9)
    n = 12
    mo = [round(rng.uniform(1, 30), 3) for _ in range(n)]
    su = [round(rng.uniform(0, 1), 3) for _ in range(n)]
    ed = [round(rng.uniform(0, 0.6), 3) for _ in range(n)]
    voiced = _talk(rng, 0.0, 11.6)
    laugh = [round(rng.uniform(0, 1), 3) for _ in range(n)]
    clip = {"signals": {"motion": mo, "subject": su, "edge": ed, "voiced": voiced, "quality": [0.5] * n},
            "sound": {"laughter": laugh}}
    lo, hi = 0.0, 11.6
    a = C.clip_track(clip, lo, hi)
    shot = {"a": lo, "b": hi, "grid": {str(k): [mo[k], su[k], ed[k]] for k in C.grid_keys(lo, hi)}}
    b = C._track({"voiced": voiced, "laugh": laugh}, shot, lo, hi)
    same = all(C.features(a, t, side) == C.features(b, t, side)
               for side in ("out", "in") for t in np.arange(1.2, 10.4, 0.1))
    check("a clip and a pro's shot with the same numbers read the same", same)
    check("the clip's readings include movement and laughter",
          any(C.features(a, 6.0, "out")[j] is not None for j in (C.NAMES.index("motion"), C.NAMES.index("laugh"))))

    # a scorer that learnt "never cut out mid-word", trusted on the cut out only
    w = [0.0] * len(C.NAMES)
    w[C.NAMES.index("word")] = -5.0
    flat = {"mean": [0.0] * len(C.NAMES), "std": [1.0] * len(C.NAMES)}
    model = {"v": C.VERSION, "out": {**flat, "w": w}, "in": {**flat, "w": [0.0] * len(C.NAMES)},
             "trusted": {"out": True, "in": False}}
    word = [[3.0, 4.6]]
    clip2 = {"signals": {"motion": [5.0] * n, "subject": [0.5] * n, "edge": [0.1] * n, "voiced": word}}
    rule_a, want = 2.0, 2.2          # the rule's window ends at 4.2, mid-word
    got = C.place(clip2, 0.0, 11.6, want, 0.6, 11.6, around=rule_a, model=model)
    check("the cut out moves off the word", got is not None and not (3.0 < got + want - C.GAP < 4.6), f"start {got}")
    check("by no more than NUDGE", got is not None and abs(got - rule_a) <= C.NUDGE + 1e-6)
    still = C.place(clip2, 0.0, 11.6, 1.5, 0.6, 11.6, around=5.5, model=model)    # ends at 7.0: nothing to fix
    check("a tie keeps the rule's choice", still == 5.5, f"start {still}")
    check("an untrusted scorer changes nothing",
          C.place(clip2, 0.0, 11.6, want, 0.6, 11.6, around=rule_a, model={**model, "trusted": {}}) is None)
    with tempfile.TemporaryDirectory() as t:
        missing = Path(t) / "none.json"
        check("no scorer on disk: not trusted", not C.trusted(missing))
        (Path(t) / "m.json").write_text(json.dumps({**model, "trusted": {"out": False, "in": False}}))
        check("a scorer that lost: not trusted", not C.trusted(Path(t) / "m.json"))
        (Path(t) / "w.json").write_text(json.dumps(model))
        check("a scorer that won: trusted", C.trusted(Path(t) / "w.json"))


# --------------------------------------------------------------------------
# a real file
# --------------------------------------------------------------------------

SOURCES = ["smptebars", "testsrc2", "color=c=navy", "rgbtestsrc", "color=c=crimson"]
FPS = 30


def _ff(args: list[str]) -> None:
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-600:])


def build(path: str, lens: list[float]) -> None:
    """Shots of `lens` seconds, hard cuts, a 300 Hz tone 0.4 s on / 0.6 s
    off as the talking (the level is all the reader hears off the Mac)."""
    inputs = []
    for i, L in enumerate(lens):
        src = SOURCES[i % len(SOURCES)]
        inputs += ["-f", "lavfi", "-i", f"{src}{':' if '=' in src else '='}size=320x180:rate={FPS}:duration={L:.3f}"]
    n = len(lens)
    chain = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,noise=alls=6:allf=t,format=yuv420p[v]"
    total = sum(lens)
    tone = f"aevalsrc=0.5*sin(2*PI*300*t)*lt(mod(t\\,1)\\,0.4):s=16000:d={total:.3f}"
    _ff([*inputs, "-f", "lavfi", "-i", tone, "-filter_complex", chain, "-map", "[v]", "-map", f"{n}:a",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "aac", path])


def _keys(x) -> set[str]:
    if isinstance(x, dict):
        return set(x) | {k for v in x.values() for k in _keys(v)}
    if isinstance(x, list):
        return {k for v in x for k in _keys(v)}
    return set()


def video_tests(d: str) -> str:
    print("a real file")
    lens = [3.5, 4.0, 3.2, 4.5]
    path = str(Path(d) / "edit.mp4")
    build(path, lens)
    rec = C.read_video(path, id="S900", group="short", creator="Some One", mac=False, log=lambda s: None)
    built = np.cumsum(lens)[:-1]
    found = [s["b"] for s in rec["shots"][:-1]]
    check("the cuts are where they were built", len(found) == len(built)
          and all(abs(f - b) <= 1.5 / FPS for f, b in zip(found, built)), f"{found}")
    check("as hard cuts", all(s["out"] == "cut" for s in rec["shots"][:-1]) and rec["shots"][0]["into"] is None)
    starts = [v[0] for v in rec["voiced"]]
    check("the talking is where the tone was", len(starts) >= 12
          and all(abs(s - round(s)) <= 0.05 for s in starts), f"{len(starts)} stretches")
    ok = all(set(map(int, s["grid"])) <= set(C.grid_keys(s["lo"], s["hi"])) for s in rec["shots"])
    check("each shot's seconds are its own", ok and all(s["grid"] for s in rec["shots"]))
    raw = json.dumps(rec)
    check("numbers only", not (_keys(rec) & {"text", "words", "frames", "path"}) and "edit.mp4" not in raw)
    fine = rec["fine"]
    check("a 10 Hz curve of movement and level", abs(len(fine["motion"]) - 10 * sum(lens)) <= 2
          and abs(len(fine["level"]) - 10 * sum(lens)) <= 2)
    gs = C.groups(rec)
    check("its cuts become decisions with candidates", {g["side"] for g in gs} == {"out", "in"}
          and all(len(g["ts"]) >= C.MIN_CANDS for g in gs), f"{len(gs)} decisions")
    return path


def collector_test(d: str, clip: str) -> None:
    print("the collector")
    tmp = Path(d) / "run"
    tmp.mkdir()
    data = tmp / "data"
    data.mkdir()
    head = "id,group,platform,url_or_file,creator,title,length_s,views,likes,counts_read_on,source,verdict,status,notes"
    rows = [f"S00{i},short,youtube,https://y/{i},Some One,a vlog,60,100,5,,web,good,measured," for i in (1, 2)]
    rows.append("S003,short,youtube,/Users/her/own.mov,sarah,her vlog,60,,,,sarah,good,measured,")   # never her own
    (data / "short-reels.csv").write_text(head + "\n" + "\n".join(rows) + "\n")
    (data / "long-youtube.csv").write_text(head + "\n")
    (data / "candidate-creators.csv").write_text("group,creator,platform,status\n")
    exe, calls = tmp / "yt-dlp", tmp / "calls.txt"
    exe.write_text(f"#!{sys.executable}\nimport shutil, sys\na = sys.argv\n"
                   f"open({str(calls)!r}, 'a').write(a[-1] + '\\n')\n"
                   f"shutil.copy({str(clip)!r}, a[a.index('-o') + 1].replace('%(ext)s', 'mp4'))\n")
    exe.chmod(0o755)
    scratch = tmp / "scratch"
    scratch.mkdir()
    real = (collect.GROUPS, collect.CREATORS, collect.ytdlp, C.OUT, C.MODEL, C.REPORT, tempfile.tempdir)
    from web.backend import sound
    real_sound = sound.ensure_built
    log: list[str] = []
    try:
        collect.GROUPS = {"long": data / "long-youtube.csv", "short": data / "short-reels.csv"}
        collect.CREATORS = data / "candidate-creators.csv"
        collect.ytdlp = lambda: str(exe)
        C.OUT, C.MODEL, C.REPORT = tmp / "cuts", tmp / "model" / "cuts.json", tmp / "model" / "cuts-report.md"
        sound.ensure_built = lambda: None
        tempfile.tempdir = str(scratch)
        collect.main(["--only", "cuts"])
        first = calls.read_text().split()
        collect.cuts_all(log.append)                  # resumable: nothing fetched again
    finally:
        (collect.GROUPS, collect.CREATORS, collect.ytdlp, C.OUT, C.MODEL, C.REPORT, tempfile.tempdir) = real
        sound.ensure_built = real_sound
    check("each pro vlog fetched once, never her own file", first == ["https://y/1", "https://y/2"]
          and calls.read_text().split() == first, calls.read_text())
    check("a record each", sorted(p.name for p in (tmp / "cuts").iterdir()) == ["S001.json", "S002.json"])
    check("the scorer tested and written", (tmp / "model" / "cuts.json").exists()
          and (tmp / "model" / "cuts-report.md").exists())
    m = json.loads((tmp / "model" / "cuts.json").read_text())
    check("one creator is too few to trust", not any(m["trusted"].values()), str(m["trusted"]))
    check("no download left behind", not any(scratch.rglob("*")), str(list(scratch.rglob("*"))))
    check("says how far it got", any("2 of 2 vlogs read already" in x for x in log), str(log[:2]))


def main() -> int:
    learning_tests()
    make_tests()
    with tempfile.TemporaryDirectory() as d:
        clip = video_tests(d)
        collector_test(d, clip)
    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
