"""Does the taste model learn editing -- and only as much as her picks say?

"Real" edits come from a small generator that cuts the way the good vlogs
do: talking shots held long with b-roll cutaways under the voice, quick
runs that land on a held payoff, a held opening on a short, straight cuts
(jump cuts inside a take), a few lower-case words at the bottom. Several
fake creators, each with their own pace and habits. Then:

1. trained per group, real beats damaged on > 80% of pairs with each
   creator left out;
2. the accuracy on a damage never shown (held-out breaker) is reported;
3. discrimination: for each feature, two edits differing in that one
   respect move it the right way;
4. on creators it never saw, the score ranks a real edit above its
   damaged copies;
5. explain() says why in plain words and names the damage, against the
   good edits or against the real version;
6. save / load gives the same scores;
7. her picks move the score her way: a little for a handful, more for
   many; an export she wouldn't post ends up further under the real edits;
8. an edit with no faces, sound or words still gets a finite score;
9. on creators with loud habits (flashes, capitals at the top, a fade in)
   the model learns those are theirs: a real edit beats its copy with the
   habits taken off, where the plain creators' model says the opposite --
   the data sets the sign, not the list of damages.

Also: every breaker gives a valid description or None, leaves its input
alone and does the same thing for the same seed; training is the same
twice; the role model learns the jobs when enough shots carry them; the
command line writes the model and a plain-words report. No network, no
model calls.

    python tests/test_taste_model.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import tempfile
import time
import zlib
from pathlib import Path

os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-taste-model-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from taste import model as M  # noqa: E402

try:
    from taste.describe import validate  # noqa: E402
except ImportError:      # the describer is built alongside: the few checks the model relies on
    def validate(desc: dict) -> list[str]:
        bad = []
        shots = desc.get("shots") or []
        if not shots:
            bad.append("no shots")
        if len(desc.get("joins") or []) != max(0, len(shots) - 1):
            bad.append("joins don't match shots")
        end = 0.0
        for s in shots:
            if not s.get("d") or s["d"] <= 0:
                bad.append("a shot has no length")
            elif s["t"] < end - 0.05:
                bad.append("shots overlap")
            else:
                end = s["t"] + s["d"]
        return bad

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


# --------------------------------------------------------------------------
# the generator: edits cut the way the good vlogs cut
# --------------------------------------------------------------------------

LABELS = {
    "talk": [["people", "adult", "room"], ["people", "adult", "kitchen"], ["people", "selfie", "street"],
             ["people", "adult", "car"]],
    "broll": [["food", "plate", "table"], ["laptop", "desk", "book"], ["coffee", "cup", "table"],
              ["street", "building", "sky"], ["plant", "flower", "garden"], ["clothing", "mirror", "room"]],
    "quick": [["street", "crosswalk", "people"], ["train", "vehicle", "window"], ["food", "kitchen", "cooking"],
              ["sky", "tree", "park"], ["store", "shopping", "market"], ["stairs", "path", "building"]],
    "payoff": [["sunset", "sky", "ocean"], ["food", "dessert", "plate"], ["cityscape", "skyline", "night"],
               ["mountain", "landscape", "sky"], ["friends", "people", "laughing"]],
    "open": [["cityscape", "skyline", "sky"], ["beach", "ocean", "sky"], ["coffee", "cup", "table"]],
}
# (face, facing, voice, laugh, motion) ranges per kind of shot, and its job
READ = {
    "talk": ((0.75, 0.95), (0.8, 1.0), (0.65, 0.9), (0.0, 0.1), (1.0, 3.0), "talk"),
    "broll": ((0.0, 0.1), None, (0.5, 0.8), (0.0, 0.05), (4.0, 8.0), "detail"),
    "quick": ((0.0, 0.2), None, (0.0, 0.2), (0.0, 0.05), (9.0, 15.0), "step"),
    "payoff": ((0.0, 0.3), None, (0.0, 0.25), (0.0, 0.6), (2.0, 5.0), "payoff"),
    "open": ((0.1, 0.4), None, (0.1, 0.3), (0.0, 0.05), (5.0, 9.0), "hook"),
}
# how likely a shot of each kind carries words: the b-roll and the payoffs, rarely a quick step
WORDS_ON = {"talk": 0.3, "broll": 1.0, "quick": 0.15, "payoff": 1.0, "open": 0.9}


def creator(k: int, group: str) -> dict:
    """A fake creator: their own pace and habits inside the shared grammar."""
    r = np.random.default_rng([7, k, 1 if group == "short" else 2])
    short = group == "short"
    return {"name": f"{group}-creator-{k}",
            "med": float(r.uniform(0.9, 1.3) if short else r.uniform(1.8, 2.8)),
            "talk": float(r.uniform(0.15, 0.35) if short else r.uniform(0.35, 0.55)),
            "words": float(r.uniform(0.35, 0.65)),
            "bpm": (None, 96.0, 120.0, 108.0)[k % 4],
            "music": float(r.uniform(0.6, 0.95) if short else r.uniform(0.3, 0.6)),
            "run": int(r.integers(2, 4)),
            "size": float(r.uniform(0.035, 0.06)),
            "soft": 0.05 if k % 3 == 0 else 0.0}     # an occasional dissolve between parts


def edit(cs: dict, vid: str, group: str, roles: bool = True, seed: int = 0) -> dict:
    rng = np.random.default_rng([seed, zlib.crc32(vid.encode())])
    short = group == "short"
    target = 50.0 if short else 200.0
    shots, joins, words = [], [], []
    state = {"t": 0.0, "chapter": 0}

    def add(kind: str, rel: float, join: str = "cut", role: str | None = None) -> None:
        d = round(rel * cs["med"] * math.exp(rng.normal(0, 0.08)), 3)
        face, facing, voice, laugh, motion, job = READ[kind]
        u = lambda lohi: round(float(rng.uniform(*lohi)), 3)  # noqa: E731
        if shots:
            joins.append({"t": round(state["t"], 3), "kind": join, "dur": 0.8 if join == "dissolve" else 0.0})
        lab = LABELS[kind][int(rng.integers(len(LABELS[kind])))]
        shots.append({"t": round(state["t"], 3), "d": d, "motion": u(motion), "motion_in": u(motion),
                      "motion_out": u(motion), "face": u(face), "facing": u(facing) if facing else None,
                      "people": 1 if kind == "talk" else 0, "voice": u(voice), "music": u((0.2, 0.9)),
                      "laugh": u(laugh), "labels": list(lab), "aesthetic": round(float(rng.uniform(-0.3, 0.8)), 3),
                      "same": join == "jump", "speed": 1.0, "role": (role or job) if roles else None,
                      "chapter": state["chapter"]})
        if d > 0.4 and rng.random() < WORDS_ON[kind] * cs["words"] * 1.6:
            words.append({"t": round(state["t"] + 0.1, 3), "d": round(min(d - 0.1, 2.5), 3), "band": "bottom",
                          "size": round(cs["size"] * float(rng.uniform(0.9, 1.1)), 3),
                          "upper": round(float(rng.uniform(0.0, 0.1)), 2), "n": int(rng.integers(2, 7)),
                          "kind": None})
        state["t"] += d

    # a short holds its first look; a long vlog opens on her talking
    if short:
        add("open", float(rng.uniform(2.3, 3.0)))
    else:
        add("talk", float(rng.uniform(2.6, 3.4)))
    while state["t"] < target:
        state["chapter"] += 1
        soft = "dissolve" if rng.random() < cs["soft"] else "cut"
        if rng.random() < cs["talk"]:
            # talk, carried over b-roll of what she means, and back to her
            add("talk", float(rng.uniform(2.4, 3.4)), join=soft)
            if rng.random() < 0.4:
                add("talk", float(rng.uniform(1.6, 2.4)), join="jump")
            for _ in range(int(rng.integers(1, 3))):
                add("broll", float(rng.uniform(0.7, 1.0)))
            if rng.random() < 0.5:
                add("talk", float(rng.uniform(1.8, 2.8)))
        else:
            # a quick run that lands on a held payoff
            for i in range(cs["run"] + int(rng.integers(0, 2))):
                add("quick", float(rng.uniform(0.45, 0.7)), join=soft if i == 0 else "cut",
                    role="setup" if i == 0 else None)
            add("payoff", float(rng.uniform(1.9, 2.6)))
    cutoff = not short          # a long vlog was measured on its first minutes
    if cutoff:
        shots[-1]["d"] = round(shots[-1]["d"] * float(rng.uniform(0.3, 1.0)), 3)
    total = round(sum(s["d"] for s in shots), 3)
    words = [w for w in words if w["t"] < total]
    for w in words:
        w["d"] = round(min(w["d"], total - w["t"]), 3)
    bpm = cs["bpm"]
    return {"v": 1, "id": vid, "source": "reference", "group": group, "vertical": short, "duration": total,
            "cutoff": cutoff,
            "have": [x for x in ("motion", "faces", "sound", "words", "labels", "roles", "music")
                     if x != "roles" or roles],
            "shots": shots, "joins": joins, "open": False, "close": False, "words": words,
            "music": {"bpm": bpm, "on": round(cs["music"] + float(rng.normal(0, 0.03)), 3),
                      "beat": round(float(rng.uniform(0.15, 0.35)), 3) if bpm else None},
            "lufs": round(-16 + float(rng.normal(0, 1.5)), 1)}


def shoot(group: str, ks, per: int = 4, roles_every: int = 2) -> tuple[list[dict], dict]:
    descs, who = [], {}
    for k in ks:
        cs = creator(k, group)
        for v in range(per):
            vid = f"{group[0].upper()}{k:02d}{v}"
            descs.append(edit(cs, vid, group, roles=(v % roles_every == 0)))
            who[vid] = cs["name"]
    return descs, who


def strip(desc: dict, keep=("motion",)) -> dict:
    """The same edit read with fewer readings: what isn't kept is None."""
    out = json.loads(json.dumps(desc))
    have = [x for x in out["have"] if x in keep]
    for s in out["shots"]:
        if "faces" not in have:
            s["face"] = s["facing"] = s["people"] = None
        if "sound" not in have:
            s["voice"] = s["music"] = s["laugh"] = None
        if "labels" not in have:
            s["labels"] = s["aesthetic"] = None
        if "motion" not in have:
            s["motion"] = s["motion_in"] = s["motion_out"] = None
        if "roles" not in have:
            s["role"] = None
    if "words" not in have:
        out["words"] = None
    if "music" not in have:
        out["music"] = None
    out["have"] = have
    return out


def restyle(desc: dict, seed: int = 0) -> dict:
    """The same edit by a creator with loud habits: white flashes on most
    joins, words in capitals at the top, a fade in from black."""
    rng = np.random.default_rng([seed, zlib.crc32(desc["id"].encode())])
    out = json.loads(json.dumps(desc))
    for j in out["joins"]:
        if j["kind"] == "cut" and rng.random() < 0.6:
            j.update(kind="flash", dur=0.2)
    for w in out["words"] or []:
        w["upper"], w["band"] = 0.85, "top"
    out["open"] = True
    return out


# --------------------------------------------------------------------------
# hand-made pairs for the discrimination checks
# --------------------------------------------------------------------------

def plain(lengths=None, **kw) -> dict:
    """A plain edit: nine one-second shots, straight cuts, no words."""
    lengths = lengths or [1.0] * 9
    shots, t = [], 0.0
    for k, d in enumerate(lengths):
        shots.append({"t": round(t, 4), "d": d, "motion": float(k % 3), "motion_in": 1.0, "motion_out": 1.0,
                      "face": 0.0, "facing": None, "people": 0, "voice": 0.1, "music": 0.5, "laugh": 0.0,
                      "labels": [f"thing{k}", "table", "room"], "aesthetic": round(0.1 * k, 3), "same": False,
                      "speed": 1.0, "role": "step", "chapter": 1})
        t += d
    desc = {"v": 1, "id": "P", "source": "reference", "group": "short", "vertical": True,
            "duration": round(t, 4), "cutoff": False,
            "have": ["motion", "faces", "sound", "words", "labels", "roles", "music"],
            "shots": shots, "joins": [{"t": s["t"], "kind": "cut", "dur": 0.0} for s in shots[1:]],
            "open": False, "close": False, "words": [], "music": {"bpm": None, "on": 0.5, "beat": None},
            "lufs": -14.0}
    desc.update(kw)
    return desc


def _set(desc: dict, k: int, **kw) -> dict:
    desc["shots"][k].update(kw)
    return desc


def _word(t: float, d: float, band: str = "bottom", upper: float = 0.0, n: int = 4) -> dict:
    return {"t": t, "d": d, "band": band, "size": 0.05, "upper": upper, "n": n, "kind": None}


def discrimination_tests() -> None:
    print("discrimination: two edits differing in one respect move the feature, by what was built in")
    f = M.features_of

    def moves(name: str, lo: dict, hi: dict, by: float | None = None) -> None:
        a, b = f(lo)[name], f(hi)[name]
        ok = math.isfinite(a) and math.isfinite(b) and b > a and (by is None or abs((b - a) - by) < 1e-6)
        check(f"{name} rises" + ("" if by is None else f" by {by:.3f}"), ok, f"{a:.3f} -> {b:.3f}")

    moves("opening_hold", plain(), plain([3.0] + [1.0] * 8), by=math.log(3))
    moves("ending_hold", plain(), plain([1.0] * 8 + [3.0]), by=math.log(3))
    moves("rhythm_spread", plain([1.0, 1.1, 0.9, 1.0, 1.1, 0.9, 1.0, 1.1, 0.9]),
          plain([0.6, 1.8, 0.6, 1.8, 0.6, 1.8, 0.6, 1.8, 0.6]))
    # the same nine lengths, sorted (they change gradually) or swinging quick-held
    moves("rhythm_alternation", plain([0.5, 0.5, 0.5, 0.5, 1.0, 2.0, 2.0, 2.0, 2.0]),
          plain([0.5, 2.0, 0.5, 2.0, 0.5, 2.0, 0.5, 2.0, 1.0]))
    # the same nine lengths; held shots after a quick run, or not
    moves("run_then_hold", plain([0.5, 2.0, 0.5, 1.0, 1.0, 1.0, 2.0, 0.5, 0.5]),
          plain([0.5, 0.5, 2.0, 1.0, 1.0, 1.0, 0.5, 0.5, 2.0]), by=1.0)
    moves("lengths_on_grid", plain([1.13, 1.37, 0.71, 1.82, 1.19, 0.93, 1.27, 1.61, 0.88]),
          plain([1.0, 1.5, 0.5, 2.0, 1.0, 1.0, 1.5, 1.5, 1.0]), by=1.0)
    fl = plain()          # one of the eight joins a flash
    fl["joins"][3]["kind"], fl["joins"][3]["dur"] = "flash", 0.2
    moves("joins_effect", plain(), fl, by=1 / 8)
    moves("joins_flash", plain(), fl, by=1 / 8)
    ds_ = plain()
    ds_["joins"][3]["kind"], ds_["joins"][3]["dur"] = "dissolve", 0.8
    moves("joins_dissolve", plain(), ds_, by=1 / 8)
    # a swipe is what a reel's reader can't see: it reads as the cut it looks like there
    sw = plain()
    sw["joins"][3]["kind"], sw["joins"][3]["dur"] = "swipe", 0.3
    same = all((f(sw)[k] == f(plain())[k]) or (math.isnan(f(sw)[k]) and math.isnan(f(plain())[k])) for k in M.NAMES)
    check("a swipe reads as a cut, in every feature and token", same
          and M.tokens(sw) == M.tokens(plain()) and "joins_swipe" not in M.NAMES)
    jp = plain()
    jp["joins"][3]["kind"] = "jump"
    moves("joins_jump", plain(), jp, by=1 / 8)
    moves("fade_open", plain(), plain(open=True), by=1.0)
    moves("fade_close", plain(), plain(close=True), by=1.0)
    # nine seconds: words over two of them, or six
    moves("words_share", plain(words=[_word(1.0, 2.0)]), plain(words=[_word(1.0, 6.0)]), by=4 / 9)
    moves("words_top", plain(words=[_word(1.0, 2.0)]), plain(words=[_word(1.0, 2.0, band="top")]), by=1.0)
    moves("words_caps", plain(words=[_word(1.0, 2.0)]), plain(words=[_word(1.0, 2.0, upper=1.0)]), by=1.0)
    moves("words_hold", plain(words=[_word(1.0, 1.0), _word(5.0, 1.0)]),
          plain(words=[_word(1.0, 2.5), _word(5.0, 2.5)]), by=1.5)
    moves("words_per_min", plain(words=[_word(1.0, 2.0, n=3)]), plain(words=[_word(1.0, 2.0, n=9)]), by=40.0)
    moves("words_shots", plain(words=[_word(1.0, 1.0)]), plain(words=[_word(1.0, 1.0), _word(4.0, 1.0)]),
          by=1 / 9)
    faced = plain()
    for k in (2, 3, 4):
        _set(faced, k, face=0.9, facing=0.0, people=1)
    moves("face_share", plain(), faced, by=1 / 3)
    looking = json.loads(json.dumps(faced))
    for k in (2, 3, 4):
        _set(looking, k, facing=1.0)
    moves("facing_share", faced, looking, by=1.0)
    # talking shots apart, each broken by a cutaway, or one after another
    apart, together = plain(), plain()
    for k in (2, 4, 6):
        _set(apart, k, face=0.9, facing=1.0, voice=0.8, people=1)
    for k in (2, 3, 4):
        _set(together, k, face=0.9, facing=1.0, voice=0.8, people=1)
    moves("talk_stretch", apart, together, by=2 / 9)
    long_talk = plain([1.0, 1.0, 2.5, 1.0, 2.5, 1.0, 2.5, 1.0, 1.0])
    for k in (2, 4, 6):
        _set(long_talk, k, face=0.9, facing=1.0, voice=0.8, people=1)
    moves("talk_vs_other", apart, long_talk, by=math.log(2.5))
    short_laugh, held_laugh = plain(), plain([1.0, 1.0, 1.0, 1.0, 2.5, 1.0, 1.0, 1.0, 1.0])
    _set(short_laugh, 4, laugh=0.8)
    _set(held_laugh, 4, laugh=0.8)
    moves("laugh_held", short_laugh, held_laugh, by=math.log(2.5))
    moves("music_on", plain(music={"bpm": None, "on": 0.0, "beat": None}),
          plain(music={"bpm": None, "on": 1.0, "beat": None}), by=1.0)
    moves("cuts_on_beat", plain(music={"bpm": 120.0, "on": 1.0, "beat": 0.1}),
          plain(music={"bpm": 120.0, "on": 1.0, "beat": 0.9}), by=0.8)
    rep = plain()
    _set(rep, 6, labels=list(rep["shots"][1]["labels"]), aesthetic=rep["shots"][1]["aesthetic"])
    moves("repeats", plain(), rep, by=1 / 9)
    paid = plain([1.0, 1.0, 1.0, 1.0, 2.5, 1.0, 1.0, 1.0, 1.0])
    flat = plain()
    for d in (paid, flat):
        _set(d, 4, role="payoff")
    moves("payoff_held", flat, paid, by=math.log(2.5))
    hooked = plain()
    _set(hooked, 0, role="hook")
    moves("hook_first", plain(), hooked, by=1.0)
    parts = plain()           # nine seconds in one part, or in three
    for k in range(9):
        _set(parts, k, chapter=k // 3)
    moves("chapters_per_min", plain(), parts, by=2 / (9 / 60))

    # thirteen even shots, or one inside held three times as long; a held
    # opening is the opening's, not a take left running
    moves("longest_hold", plain([1.0] * 13), plain([1.0] * 6 + [3.0] + [1.0] * 6), by=math.log(3))
    check("longest_hold: a held first shot isn't read as one inside",
          f(plain([3.0] + [1.0] * 12))["longest_hold"] == 0.0)
    # in a short edit too: the held shot is read against the others, not itself
    moves("longest_hold", plain([1.0] * 8), plain([1.0] * 3 + [3.0] + [1.0] * 4), by=math.log(3))
    # three talking shots alike, or one of them held 2.5x
    talk_held = plain([1.0, 1.0, 2.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    for k in (2, 4, 6):
        _set(talk_held, k, face=0.9, facing=1.0, voice=0.8, people=1)
    moves("talk_longest", apart, talk_held, by=math.log(2.5))
    # two talking shots: the held one against the other, not their middle
    two_talk = json.loads(json.dumps(talk_held))
    _set(two_talk, 6, face=0.0, facing=None, voice=0.1, people=0)
    check("talk_longest: with two talking shots, the held one reads against the other",
          abs(f(two_talk)["talk_longest"] - math.log(2.5)) < 1e-9, f"{f(two_talk)['talk_longest']:.3f}")
    end_talk = plain([1.0] * 8 + [2.5])
    for k in (2, 4, 8):
        _set(end_talk, k, face=0.9, facing=1.0, voice=0.8, people=1)
    check("talk_longest: a talking last shot held is the ending's, not a long take",
          f(end_talk)["talk_longest"] == 0.0, f"{f(end_talk)['talk_longest']:.3f}")
    # five beach shots and four street shots, as two scenes or alternating:
    # neighbours differ at one join of eight or all eight, against 20 of 36 pairs
    scenes, mixed = plain(), plain()
    for k in range(9):
        _set(scenes, k, labels=["beach", "sand", "sea"] if k < 5 else ["street", "car", "shop"])
        _set(mixed, k, labels=["beach", "sand", "sea"] if k % 2 == 0 else ["street", "car", "shop"])
    moves("flow_seen", scenes, mixed, by=(1 - 1 / 8) * 36 / 20)
    # the talk (three of nine seconds) with no music under it, or all of it
    moves("music_under_talk", plain(music={"bpm": None, "on": 0.0, "beat": None}) | {"shots": apart["shots"]},
          plain(music={"bpm": None, "on": 1.0, "beat": None}) | {"shots": apart["shots"]}, by=1 / 3)
    blind = f(plain(have=["motion"]) | {"shots": apart["shots"]})
    check("the shot-by-shot readings are no evidence where they weren't taken",
          all(math.isnan(blind[k]) for k in ("talk_longest", "flow_seen", "music_under_talk")))
    # a shot too short to have a frame of its own (two frames a second)
    # carries its neighbour's readings: its labels don't make the shots
    # beside it look alike or unalike
    short_a, short_b = json.loads(json.dumps(scenes)), json.loads(json.dumps(scenes))
    for x in (short_a, short_b):
        x["shots"][2]["d"] = 0.3
    _set(short_b, 2, labels=["street", "car", "shop"])
    check("flow_seen: the labels of a shot too short for a frame of its own aren't read",
          f(short_a)["flow_seen"] == f(short_b)["flow_seen"]
          and f(scenes)["flow_seen"] != f(_set(json.loads(json.dumps(scenes)), 2, labels=["street", "car", "shop"]))
          ["flow_seen"])
    # a board's readings are each shot's own however short: a frame more or
    # less on one shot (Make's cuts sit near the half-second) changes nothing
    board_a, board_b = (json.loads(json.dumps(x)) | {"source": "board"} for x in (short_a, short_b))
    nudged = json.loads(json.dumps(board_a))
    nudged["shots"][2]["d"] = 0.5 + 1 / 30
    check("flow_seen and continuity: on a board, a shot's labels count however short it is",
          f(board_a)["flow_seen"] != f(board_b)["flow_seen"]
          and all(f(board_a)[k] == f(nudged)[k] for k in ("flow_seen", "continuity")))
    # the same nine shots of three places, each place kept together or the
    # edit hopping between them: what they show, how they look, how they move
    places = (("beach", "sand", "ocean", 0.6, 1.0), ("kitchen", "plate", "food", 0.1, 5.0),
              ("street", "car", "building", -0.2, 10.0))

    def visit(order) -> dict:
        out = plain()
        for k, p in enumerate(order):
            a, b, c, look, mo = places[p]
            _set(out, k, labels=[a, b, c], aesthetic=look, motion=mo + 0.1 * k, motion_in=mo, motion_out=mo)
        return out

    hopping, kept = visit([0, 1, 2, 0, 1, 2, 0, 1, 2]), visit([0, 0, 0, 1, 1, 1, 2, 2, 2])
    moves("continuity", hopping, kept)
    check("...above two shots taken at random when kept together, below when hopping",
          f(kept)["continuity"] > 0 > f(hopping)["continuity"],
          f"{f(kept)['continuity']:+.2f} / {f(hopping)['continuity']:+.2f}")
    # cut on action: the same eight shots alike in all but how they move in
    # and out, in the order where each one's movement out meets the next
    # one's movement in, or reversed so that it never does
    chain = plain([1.0] * 8)
    for k in range(8):
        _set(chain, k, labels=["room", "table", "cup"], aesthetic=0.3, motion=2.0,
             motion_in=float(2 ** k), motion_out=float(2 ** (k + 1)))
    rev = json.loads(json.dumps(chain))
    for sh, src in zip(rev["shots"], reversed(chain["shots"])):
        sh.update({k: src[k] for k in ("motion_in", "motion_out")})
    moves("continuity", rev, chain)
    check("continuity reads no join: a jump cut or a dissolve between the same shots changes nothing",
          f(chain)["continuity"] == f(dict(chain, joins=[dict(j, kind="dissolve", dur=0.8) for j in chain["joins"]]))
          ["continuity"])
    tiny, other = visit([0, 0, 0, 1, 1, 1, 2, 2, 2]), visit([0, 0, 0, 1, 1, 1, 2, 2, 2])
    for x in (tiny, other):
        x["shots"][4]["d"] = 0.3
    _set(other, 4, labels=["beach", "sand", "ocean"], aesthetic=0.6)
    check("...nor the labels and look of a shot too short to have a still of its own",
          f(tiny)["continuity"] == f(other)["continuity"] and f(kept)["continuity"] != f(
              _set(json.loads(json.dumps(kept)), 4, labels=["beach", "sand", "ocean"], aesthetic=0.6))["continuity"])

    # the grammar, learnt on three creators and read on a fourth: a real edit's
    # order reads likelier than the same shots shuffled, its run of tokens
    # likelier than with flashes on the joins, its story beats likelier than
    # the same jobs handed out at random
    reals, _ = shoot("short", range(4))
    g = M.learn_grammars(reals[4:])
    test = reals[:4]
    rng = np.random.default_rng(3)

    def mix_roles(d: dict) -> dict:
        out = json.loads(json.dumps(d))
        for s, r in zip(out["shots"], rng.permutation([s["role"] for s in d["shots"]])):
            s["role"] = r
        return out

    for name, damage in (("order_kind", M.shuffle_all), ("order_dur", M.shuffle_all),
                         ("grammar_kind", M.add_flashes), ("grammar_dur", M.add_flashes),
                         ("grammar_role", lambda d, _: mix_roles(d))):
        pairs = [(f(d, g)[name], f(damage(d, rng), g)[name]) for d in test]
        pairs = [(a, b) for a, b in pairs if math.isfinite(a) and math.isfinite(b)]
        real, bad = np.mean([a for a, _ in pairs]), np.mean([b for _, b in pairs])
        check(f"{name}: the real edit reads likelier than its damaged copy", bool(pairs) and real > bad,
              f"{real:.3f} vs {bad:.3f} over {len(pairs)}")


# --------------------------------------------------------------------------
# the rest
# --------------------------------------------------------------------------

def breaker_tests(descs: list[dict]) -> None:
    print("breakers: valid, pure, the same for the same seed")
    made, bad, impure, unstable = 0, [], [], []
    for d in descs:
        before = json.dumps(d, sort_keys=True)
        for name, br in M.BREAKERS.items():
            out = br(d, M._rng(0, d["id"], name))
            if json.dumps(d, sort_keys=True) != before:
                impure.append(name)
            if out is None:
                continue
            made += 1
            problems = validate(out)
            if problems:
                bad.append(f"{name}: {problems[:2]}")
            again = br(d, M._rng(0, d["id"], name))
            if json.dumps(again, sort_keys=True) != json.dumps(out, sort_keys=True):
                unstable.append(name)
    check("every damaged copy is a valid description", not bad, "; ".join(bad[:3]) or f"{made} copies")
    check("no breaker touches the edit it damages", not impure, ", ".join(sorted(set(impure))))
    check("the same seed gives the same damage", not unstable, ", ".join(sorted(set(unstable))))
    names = {n for d in descs for n, br in M.BREAKERS.items() if br(d, M._rng(0, d["id"], n)) is not None}
    check("every breaker applies to some real edit", names == set(M.BREAKERS), str(set(M.BREAKERS) - names))
    long_ = [d for d in descs if d["cutoff"]]
    check("the ending isn't stretched where measuring stopped",
          all(M.stretch_ending(d, M._rng(0, d["id"], "x")) is None for d in long_) and bool(long_))
    d = descs[0]
    sh = M.shuffle_all(d, M._rng(0, d["id"], "shuffle_all"))
    check("a shuffle keeps every shot and the whole length",
          sorted(s["d"] for s in sh["shots"]) == sorted(s["d"] for s in d["shots"])
          and abs(sh["duration"] - d["duration"]) < 1e-3)
    ev = M.even_rhythm(d, M._rng(0, d["id"], "even_rhythm"))
    check("even rhythm: every shot one length, the total kept",
          np.ptp([s["d"] for s in ev["shots"]]) < 1e-3 and abs(ev["duration"] - d["duration"]) < 1e-2)
    lt = M.long_talk(d, M._rng(0, d["id"], "long_talk")) or M.long_talk(descs[1], M._rng(0, "b", "long_talk"))
    check("long talk merges the cutaways into the talk", lt is not None and len(lt["shots"]) < len(d["shots"]))


def main() -> int:
    t0 = time.time()
    discrimination_tests()

    print("training on six fake creators per group")
    short, who_s = shoot("short", range(6))
    long_, who_l = shoot("long", range(6))
    breaker_tests(short[:6] + long_[:6] + [restyle(d) for d in short[:2]])
    models, reports = {}, {}
    for group, descs, who in (("short", short, who_s), ("long", long_, who_l)):
        m, rep = M.train(descs, group, who, seed=0)
        models[group], reports[group] = m, rep
        check(f"{group}: real beats damaged on > 80% with each creator left out",
              rep["loco"] is not None and rep["loco"] > 0.8 and rep["grouped_by"] == "creator",
              f"{M._pct(rep['loco'])} of {rep['pairs']} pairs, {rep['creators']} creators")
        ho = rep["held_out_breaker"]
        check(f"{group}: the accuracy on a damage never shown is reported, per damage",
              set(ho) == set(rep["loco_by_breaker"]) and all(0 <= x <= 1 for x in ho.values())
              and rep["held_out_mean"] is not None,
              f"mean {M._pct(rep['held_out_mean'])}; lowest {min(ho, key=ho.get)} {M._pct(min(ho.values()))}")
        # the other sides (MIRRORS) are a matter of the corpus: judged below, on one with the habits
        weak = {k: v for k, v in rep["loco_by_breaker"].items() if v < 0.7 and k not in M.MIRRORS}
        check(f"{group}: no damage goes unseen with the creator left out", not weak, str(weak))
    print("  per damage (short):", ", ".join(f"{k} {v:.2f}/{reports['short']['held_out_breaker'][k]:.2f}"
                                            for k, v in reports["short"]["loco_by_breaker"].items()))

    m2, rep2 = M.train(short, "short", who_s, seed=0)
    check("the same edits and seed give the same model",
          np.array_equal(m2.w, models["short"].w) and rep2["loco"] == reports["short"]["loco"])

    print("creators with loud habits: the data, not the list of damages, says which way is good")
    loud, who_loud = shoot("short", range(6))
    loud = [restyle(d) for d in loud]
    ml_, rl_ = M.train(loud, "short", who_loud, seed=0)
    test_loud = [restyle(d, 1) for d in shoot("short", range(10, 13), per=2)[0]]

    def all_cuts(d: dict) -> dict:
        out = json.loads(json.dumps(d))
        for j in out["joins"]:
            if j["kind"] != "jump":
                j.update(kind="cut", dur=0.0)
        return out

    for name, other in (("every join a straight cut", all_cuts),
                        ("strip_effects", lambda d: M.strip_effects(d, M._rng(4, d["id"], "s"))),
                        ("words_lower", lambda d: M.words_lower(d, M._rng(4, d["id"], "l"))),
                        ("words_off_top", lambda d: M.words_off_top(d, M._rng(4, d["id"], "t"))),
                        ("no_fades", lambda d: M.no_fades(d, M._rng(4, d["id"], "f")))):
        got = [ml_.score(d) > ml_.score(o) for d in test_loud if (o := other(d)) is not None]
        check(f"the loud edit beats its copy with {name}, on creators it never saw",
              len(got) == len(test_loud) and np.mean(got) > 0.8, f"{sum(got)} of {len(got)}")
    for k in ("joins_flash", "words_caps", "words_top", "fade_open"):
        check(f"...and the plain model still finds {k} against it",
              models["short"].score(test_loud[0]) < models["short"].score(
                  {"joins_flash": all_cuts, "words_caps": lambda d: M.words_lower(d, None),
                   "words_top": lambda d: M.words_off_top(d, None),
                   "fade_open": lambda d: M.no_fades(d, None)}[k](test_loud[0])))

    print("unseen creators")
    m = models["short"]
    new, _ = shoot("short", range(10, 13), per=2)
    right, total, wrong = 0, 0, []
    for d in new:
        s = m.score(d)
        for name, br in M.BREAKERS.items():
            b = br(d, M._rng(5, d["id"], name))
            if b is None:
                continue
            total += 1
            if s > m.score(b):
                right += 1
            else:
                wrong.append(name)
    check("a real edit scores above its damaged copies on creators it never saw", right / total > 0.85,
          f"{right} of {total}; missed {sorted(set(wrong))}")
    newl, _ = shoot("long", range(10, 12), per=2)
    ml = models["long"]
    pairs = [(d, b) for d in newl for n, br in M.BREAKERS.items() if (b := br(d, M._rng(5, d["id"], n)))]
    got = np.mean([ml.score(d) > ml.score(b) for d, b in pairs])
    check("...and for long vlogs", got > 0.85, f"{got:.0%} of {len(pairs)}")

    print("explain")
    d = new[0]

    def plain_words(ex: list[dict], n: int) -> bool:
        return (1 <= len(ex) <= n and all(set(e) == {"feature", "says", "value", "typical", "effect"} for e in ex)
                and all(isinstance(e["says"], str) and e["says"][0].isupper() and e["says"].endswith(".")
                        and "_" not in e["says"] and "nan" not in e["says"].lower() for e in ex))

    # the damage named, by the feature that reads it or in the words of a grammar line
    for name, feats, words in (("add_flashes", {"joins_effect", "joins_flash"}, ("white flashes",)),
                               ("words_top", {"words_top"}, ("top",)),
                               ("even_rhythm", {"rhythm_spread", "rhythm_alternation", "run_then_hold"},
                                ("all alike", "typical length"))):
        b = M.BREAKERS[name](d, M._rng(1, d["id"], name))
        ex = m.explain(b, top=3)
        check(f"{name}: plain-words lines", plain_words(ex, 3) and len(ex) == 3, ex[0]["says"] if ex else "none")
        check(f"{name}: the damage is among what it names",
              any(e["feature"] in feats or any(w in e["says"] for w in words) for e in ex),
              " | ".join(e["says"] for e in ex))
        vs = m.explain(b, top=3, against=d)
        check(f"{name}: against the real version, the strongest line counts against it",
              plain_words(vs, 3) and vs[0]["effect"] < 0 and all("the other version" in e["says"] for e in vs),
              vs[0]["says"] if vs else "none")
    ex = m.explain(d, top=5)
    check("the lines come strongest first", [abs(e["effect"]) for e in ex] == sorted((abs(e["effect"]) for e in ex),
                                                                                       reverse=True))
    check("an edit against itself has nothing to say", m.explain(d, against=d) == [])

    print("files")
    tmp = Path(tempfile.mkdtemp(prefix="vibecut-taste-files-"))
    M.MODEL_DIR = tmp / "model"
    for g, mm in models.items():
        M.save(mm, M.MODEL_DIR / f"{g}.json")
    back = M.load("short")
    some = new + [M.BREAKERS[n](new[0], M._rng(2, "x", n)) for n in ("shuffle_all", "add_flashes", "words_none")]
    same = back is not None and all(back.score(x) == m.score(x) for x in some if x)
    check("save / load round-trips and scores identically", same)
    check("the file is JSON with no NaN in it", "NaN" not in (M.MODEL_DIR / "short.json").read_text())
    check("load says None when nothing was trained", M.load("nothing") is None)
    check("the role model is in the file", back is not None and back.roles is not None
          and back.roles["classes"] == m.roles["classes"])

    print("roles")
    rr = reports["short"]["roles"]
    check("trained on the shots whose job is named", rr["trained"] and rr["shots"] >= M.ROLE_MIN, str(rr["shots"]))
    check("names a creator's jobs it never saw", (rr["loco"] or 0) > 0.6, M._pct(rr["loco"]))
    named = new[2]          # one cut with its jobs named (every other one is cut without)
    bare = strip(named, keep=("motion", "faces", "sound", "words", "labels", "music"))
    filled = m.fill_roles(bare)
    truth = [s["role"] for s in named["shots"]]
    hit = np.mean([s["role"] == r for s, r in zip(filled["shots"], truth)])
    check("fills the jobs of an edit without them", "roles" in filled["have"] and hit > 0.6
          and "roles" not in bare["have"], f"{hit:.0%} right")
    check("...so its story beats are read", math.isfinite(m.features(bare)["grammar_role"]))
    few = [edit(creator(k, "short"), f"S9{k}", "short", roles=False) for k in range(3)]
    few_who = {d["id"]: f"few-{k}" for k, d in enumerate(few)}
    some = json.loads(json.dumps(edit(creator(0, "short"), "S99", "short", roles=True)))
    for s in some["shots"][12:]:        # the AI editor named only the first dozen shots of one edit
        s["role"] = None
    few.append(some)
    few_who["S99"] = "few-0"
    mf, rf = M.train(few, "short", few_who)
    check("too few named shots: no role model", mf.roles is None and not rf["roles"]["trained"],
          f"{rf['roles']['shots']} shots")
    one = [edit(creator(k, "short"), f"S8{k}{v}", "short", roles=(k == 0)) for k in range(4) for v in range(3)]
    mo, ro = M.train(one, "short", {d["id"]: f"one-{d['id'][2]}" for d in one})
    check("named shots from one creator only: no role model, it can't be checked",
          mo.roles is None and not ro["roles"]["trained"] and ro["roles"]["shots"] >= M.ROLE_MIN
          and "creator" in ro["roles"]["why"], ro["roles"].get("why", ""))
    check("the role report carries the always-the-commonest-job baseline",
          0 < (rr.get("majority_baseline") or 0) < (rr["loco"] or 0) - M.ROLE_MARGIN + 1e-9,
          f"{M._pct(rr.get('majority_baseline'))} vs {M._pct(rr['loco'])}")
    filled_bare = m.fill_roles(bare)
    fb = M.features_of(filled_bare)
    check("jobs the role model guessed leave the editor's holds and opening unread",
          math.isnan(fb["hook_first"]) and math.isnan(fb["payoff_held"]))

    print("missing readings")
    d = new[2]
    for keep in (("motion",), (), ("motion", "words"), ("faces", "motion")):
        x = strip(d, keep)
        ok = validate(x) == [] and math.isfinite(m.score(x)) and isinstance(m.explain(x), list)
        check(f"read with only {', '.join(keep) or 'nothing'}: a finite score", ok, f"{m.score(x):+.2f}")
    one = plain([2.0])
    check("one shot: a finite score", math.isfinite(m.score(one)) and math.isfinite(models["long"].score(one)))
    board = strip(d, ("motion",))
    board["source"], board["id"] = "board", None
    check("a board read without the Mac's readers is scored", math.isfinite(m.score(board)))

    print("her layer")
    real_new, _ = shoot("short", range(20, 26), per=1)
    probe = real_new[-1]
    flashy = M.add_flashes(probe, M._rng(0, "probe", "f"))
    base = m.score(flashy) - m.score(probe)
    for d in real_new[:3]:          # a handful of picks: flashes over the clean cut
        M.record_pick(M.add_flashes(d, M._rng(0, d["id"], "f")), d, why="likes the flash")
    fit = M.personal_fit()
    after = M.load("short")
    gap3 = after.score(flashy) - after.score(probe)
    check("three picks move the score her way", gap3 > base, f"{base:+.2f} -> {gap3:+.2f}")
    check("...but only a little", gap3 < 0 and (gap3 - base) < 0.5 * abs(base) and fit["short"]["moved"] < 0.3,
          f"moved {fit['short']['moved']:.2f} of the weights")
    for k in range(30):
        d = edit(creator(30 + k, "short"), f"P{k:02d}", "short")
        M.record_pick(M.add_flashes(d, M._rng(0, d["id"], "f")), d)
    M.personal_fit()
    gap33 = M.load("short").score(flashy) - M.load("short").score(probe)
    check("many picks move it more", gap33 > gap3 + 0.1 * abs(base), f"{gap3:+.2f} -> {gap33:+.2f}")
    check("the group's model without her layer is unchanged", M.load("short", personal=False).score(probe) == m.score(probe))
    stored = json.loads(M._personal_path().read_text())
    check("pairs and her offset kept in the cache", len(stored["pairs"]) == 33 and stored["fit"]["short"]["pairs"] == 33)
    M._personal_path().unlink()
    M.record_edit(probe, json.loads(json.dumps(probe)))
    check("an export she didn't change records nothing", not M._personal_path().exists())
    meh = real_new[0]           # an export the model finds fine; her no is news to it
    liked = real_new[1]         # one she said yes to: the yardstick for her no

    def below(mm: M.Model) -> float:
        """How far the export sits under the one she would post (only
        differences between scores mean anything)."""
        return mm.score(liked) - mm.score(meh)

    g0 = below(M.load("short"))
    M.record_verdict(meh, post=False, why="too slow")
    nofit = M.personal_fit()
    check("a no with no yes to weigh it against moves nothing yet",
          nofit["short"]["pairs"] == 0 and nofit["short"]["waiting"] == 1
          and abs(below(M.load("short")) - g0) < 1e-9)
    M.record_verdict(liked, post=True)
    M.personal_fit()
    g1 = below(M.load("short"))
    check("an export she wouldn't post sits further under one she would, weakly", 0 < g1 - g0 < 1.0,
          f"{g0:+.3f} -> {g1:+.3f}")
    stored = json.loads(M._personal_path().read_text())
    check("a yes adds no pair, only the yardstick", len(stored["pairs"]) == 1 and len(stored["yes"]) == 1)
    retrained = M.Model.from_json(m.to_json())
    retrained.w = retrained.w * 1.01
    M.save(retrained, M.MODEL_DIR / "short.json")
    check("her offset is not put on a model trained since", not M.load("short").u.any())
    M.personal_fit()
    check("...until it is fitted again, against the new weights", M.load("short").u.any())
    M.save(m, M.MODEL_DIR / "short.json")

    print("command line")
    root = Path(tempfile.mkdtemp(prefix="vibecut-taste-cli-"))
    M.DESCRIPTIONS, M.DATA, M.MODEL_DIR = root / "descriptions", root / "data", root / "model"
    M.DESCRIPTIONS.mkdir()
    M.DATA.mkdir()
    head = ["id", "group", "creator", "verdict", "status"]
    with (M.DATA / "short-reels.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=head)
        w.writeheader()
        for d in short:
            w.writerow({"id": d["id"], "group": "short", "creator": who_s[d["id"]], "verdict": "good",
                        "status": "measured"})
        w.writerow({"id": "S900", "group": "short", "creator": "someone", "verdict": "good", "status": "not a vlog"})
    for d in short + [dict(new[1], id="S900")]:
        (M.DESCRIPTIONS / f"{d['id']}.json").write_text(json.dumps(d))
    ours = dict(new[0], id="V001")          # one of VibeCut's own: scored, not learnt from
    (M.DESCRIPTIONS / "V001.json").write_text(json.dumps(ours))
    code = M.main(["train", "--group", "short"])
    md = (M.MODEL_DIR / "short-report.md").read_text() if (M.MODEL_DIR / "short-report.md").exists() else ""
    check("train writes the model and the report", code == 0 and (M.MODEL_DIR / "short.json").exists() and bool(md))
    trained_on = json.loads((M.MODEL_DIR / "short.json").read_text())["trained_on"]
    check("the report is plain words with the numbers",
          "Can it tell a real edit" in md and "never shown" in md and "V001" in md and "nan" not in md.lower()
          and "V001" not in trained_on, md[:120])
    check("a row that isn't a vlog is neither learnt from nor scored", "S900" not in trained_on and "S900" not in md)
    check("score prints a line", M.main(["score", str(M.DESCRIPTIONS / "V001.json")]) == 0)
    check("too few edits: says so, writes nothing", M.main(["train", "--group", "long"]) == 1
          and not (M.MODEL_DIR / "long.json").exists())

    print(f"\n{time.time() - t0:.1f} s")
    if failures:
        print(f"{len(failures)} failed: {failures}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
