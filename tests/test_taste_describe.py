"""Does the edit description say what the edit is, shot by shot?

From a video: shots of known lengths from different sources, joined by
cuts, one dissolve and one dip to black, must come back as those shots
and those joins -- and the same shots all hard-cut must come back as cuts
only (built to differ in that one respect). The moving source must read
as more motion than the still ones. Off the Mac the Vision and sound
readings are absent from `have`, never guessed; a jump-cut detector (when
the shots module has one) adds a "jump" join.

From a board: synthetic clips with per-second faces, voice and motion, a
Hype look (swipes between parts), a flash after the hook, the same clip
twice further on (a jump cut), captions in three bands: joins come out as
flash / jump / cut / cut (the swipe read as a reel's reader sees it, kept
as `drawn`), words have their bands, each shot's face and
voice are the clip's seconds it uses, and nothing is decoded.

The pure helpers on stand-in data: per-shot means from per-second
tracks, word events from OCR samples (one card per run in a band, a
one-frame miss is the same card, an unread frame neither starts nor ends
one, the text itself never kept), and validate() catching broken
descriptions.

    python tests/test_taste_describe.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

if __name__ == "__main__":
    os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-describe-")
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from cutgrammar import media as media_mod, music, shots as shots_mod  # noqa: E402
from taste import describe as D  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


# --------------------------------------------------------------------------
# a finished video
# --------------------------------------------------------------------------

SOURCES = ["color=c=crimson", "smptebars", "color=c=navy", "testsrc2", "color=c=goldenrod", "rgbtestsrc"]
SIZE, FPS, TDUR = "320x180", 30, 0.6


def _ff(args: list[str]) -> None:
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-600:])


def build(path: str, lens: list[float], joins: list[str]) -> None:
    """Shots of `lens` seconds joined by `joins` ("cut" or an xfade name).
    A soft join is centred on where the hard cut would have been (each side
    made TDUR/2 longer), as tests/test_style.build does, so the shot
    boundaries sit at the same times whatever the joins."""
    n = len(lens)
    inputs, durs = [], []
    for i, L in enumerate(lens):
        pre = TDUR / 2 if i > 0 and joins[i - 1] != "cut" else 0.0
        post = TDUR / 2 if i < n - 1 and joins[i] != "cut" else 0.0
        durs.append(L + pre + post)
        src = SOURCES[i % len(SOURCES)]
        inputs += ["-f", "lavfi", "-i", f"{src}{':' if '=' in src else '='}size={SIZE}:rate={FPS}:duration={durs[-1]:.3f}"]
    parts, prev, length = [], "[0:v]", durs[0]
    for i in range(1, n):
        out = f"[x{i}]"
        if joins[i - 1] == "cut":
            parts.append(f"{prev}[{i}:v]concat=n=2:v=1:a=0,settb=1/{FPS}{out}")
            length += durs[i]
        else:
            parts.append(f"{prev}[{i}:v]xfade=transition={joins[i - 1]}:duration={TDUR:.3f}:offset={length - TDUR:.3f}{out}")
            length += durs[i] - TDUR
        prev = out
    chain = ";".join(parts) + f";{prev}noise=alls=6:allf=t,format=yuv420p[v]"
    total = sum(lens)
    _ff([*inputs, "-f", "lavfi", "-i", f"sine=f=440:d={total:.3f}", "-filter_complex", chain,
         "-map", "[v]", "-map", f"{n}:a", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
         "-c:a", "aac", path])


def video_tests(d: str) -> None:
    print("from a video")
    lens = [2.0, 2.5, 1.8, 2.2, 3.0, 2.0]
    mixed = ["cut", "fade", "cut", "fadeblack", "cut"]
    p = os.path.join(d, "mixed.mp4")
    build(p, lens, mixed)
    desc, extras = D.from_video(p, id="T001", group="short", mac=False, log=lambda *_: None)
    shots = desc["shots"]
    check("valid", D.validate(desc) == [], "; ".join(D.validate(desc)))
    check("six shots", len(shots) == 6, str(len(shots)))
    got = [s["d"] for s in shots]
    check("their lengths are the built ones (±0.1 s)", len(got) == 6 and all(abs(a - b) < 0.1 for a, b in zip(got, lens)),
          str(got))
    kinds = [j["kind"] for j in desc["joins"]]
    check("joins: cut, dissolve, cut, dip to black, cut", kinds == ["cut", "dissolve", "cut", "dip_black", "cut"], str(kinds))
    soft = [j["dur"] for j in desc["joins"] if j["kind"] != "cut"]
    check("soft joins keep their length, cuts take none",
          all(0.3 < x < 1.2 for x in soft) and all(j["dur"] == 0 for j in desc["joins"] if j["kind"] == "cut"), str(soft))
    edges = np.cumsum(lens)[:-1]
    check("each join sits where the cut was built", all(abs(j["t"] - e) < 0.1 for j, e in zip(desc["joins"], edges)),
          str([j["t"] for j in desc["joins"]]))
    mo = [s["motion"] for s in shots]
    still = [mo[i] for i in (0, 2, 4)]
    check("the moving source (testsrc2) moves more than the still colours", mo[3] > 2 * max(still),
          f"{mo[3]} vs {still}")
    check("motion in and out are read", all(s["motion_in"] is not None and s["motion_out"] is not None for s in shots))
    check("off the Mac: only motion is read", desc["have"] == ["motion"], str(desc["have"]))
    check("  and faces, voice, labels, words stay unknown",
          all(s[k] is None for s in shots for k in ("face", "facing", "people", "voice", "music", "laugh", "labels", "aesthetic"))
          and desc["words"] is None, "")
    check("no frames extracted without Vision or a work folder", extras["frames_dir"] is None
          and extras["stills"] == [None] * 6 and extras["times"] == [], str(extras["frames_dir"]))
    check("a reference's numbers: source, id, group, frame", desc["source"] == "reference" and desc["id"] == "T001"
          and desc["group"] == "short" and desc["vertical"] is False and desc["cutoff"] is False, "")
    check("sound measured: loudness, and music has its keys (no beat to read)",
          desc["lufs"] is not None and desc["music"] is not None and desc["music"]["on"] is None, str(desc["music"]))
    check("no jumps, nothing joined as the same picture", not any(s["same"] for s in shots))

    # the one respect: the same shots, all hard cuts
    p2 = os.path.join(d, "cuts.mp4")
    build(p2, lens, ["cut"] * 5)
    cuts, _ = D.from_video(p2, mac=False, log=lambda *_: None)
    kinds = [j["kind"] for j in cuts["joins"]]
    check("the same shots all cut: cuts only, same lengths", kinds == ["cut"] * 5
          and all(abs(s["d"] - L) < 0.1 for s, L in zip(cuts["shots"], lens)), str(kinds))

    # measured only so far: cut off, so the ending is not the creator's
    part, _ = D.from_video(p2, limit_s=6.0, mac=False, log=lambda *_: None)
    check("limit_s: cut off, no close, shots end where measuring stopped",
          part["cutoff"] is True and part["close"] is False and abs(part["duration"] - 6.0) < 0.05
          and len(part["shots"]) == 3, f"{part['cutoff']} {part['duration']} {len(part['shots'])}")

    # a work folder given: frames at 2 fps and a mid-frame still per shot
    wd = Path(d) / "frames"
    desc3, ex = D.from_video(p2, workdir=wd, mac=False, log=lambda *_: None)
    check("with a work folder: frames at 2 fps and one still per shot", len(ex["stills"]) == 6
          and all(s and os.path.exists(s) for s in ex["stills"]) and abs(len(ex["times"]) - 2 * sum(lens)) <= 2
          and ex["frames_dir"] == str(wd), f"{len(ex['times'])} frames")
    mid = [float(Path(s).stem) for s in ex["stills"]]
    check("  the stills are in playing order", mid == sorted(mid), str(mid))

    mac_glue_test(p2, lens)

    # a jump-cut detector, when the shots module has one (piece A)
    had = getattr(shots_mod, "jump_cuts", None)
    shots_mod.jump_cuts = lambda m, sh: [int(round(1.0 * m.fps)), int(round(2.0 * m.fps))]   # 1.0 s, and the 2.0 s cut
    try:
        jd, _ = D.from_video(p2, mac=False, log=lambda *_: None)
    finally:
        if had is None:
            del shots_mod.jump_cuts
        else:
            shots_mod.jump_cuts = had
    kinds = [j["kind"] for j in jd["joins"]]
    check("a jump cut inside a shot becomes a jump join; one on a cut is that cut",
          kinds == ["jump", "cut", "cut", "cut", "cut", "cut"] and jd["shots"][1]["same"] is True
          and abs(jd["shots"][0]["d"] - 1.0) < 0.05, str(kinds))
    check("  still valid", D.validate(jd) == [], "; ".join(D.validate(jd)))


def mac_glue_test(path: str, lens: list[float]) -> None:
    """The Mac's readers can't run here; stand-ins play them, so the glue
    from their answers to each shot is exercised: words timed and placed,
    faces per second to per shot, a label per shot from its mid frame,
    voice and music from the classifier's windows."""
    from web.backend import sound, vision
    real = (vision.ensure_built, vision.text, vision.faces, vision.analyse, sound.ensure_built, sound._classify)
    edges = np.concatenate([[0.0], np.cumsum(lens)])

    def shot_of(p: str) -> int:
        t = (int(Path(p).stem) - 1) / D.FRAME_FPS
        return int(np.searchsorted(edges, t, side="right") - 1)

    def text(paths, accurate=False):
        # the second shot carries a top caption; one frame timed out
        found = {p: ([{"text": "HELLO THERE", "box": [0.2, 0.8, 0.5, 0.06], "conf": 0.9}] if shot_of(p) == 1 else [])
                 for p in paths}
        return found, [paths[-1]]
    vision.ensure_built = sound.ensure_built = lambda: Path("/stand-in")
    vision.text = text
    vision.faces = lambda paths: {p: ([[0.3, 0.3, 0.3, 0.3, 5.0]] if shot_of(p) == 0 else []) for p in paths}
    vision.analyse = lambda paths: ([{"path": p, "labels": [[f"shot{shot_of(p)}", 0.9], ["b", 0.5], ["c", 0.4], ["d", 0.3]],
                                      "aesthetic": 0.25, "error": None} for p in paths], "vision")
    sound._classify = lambda binary, wav: [{"t": k / 2, "d": 1.0, "voice": 0.9 if k / 2 < 2 else 0.0,
                                            "music": 0.8, "singing": 0.0, "laughter": 0.0} for k in range(30)]
    try:
        with tempfile.TemporaryDirectory() as wd:
            desc, ex = D.from_video(path, workdir=wd, log=lambda *_: None)
    finally:
        vision.ensure_built, vision.text, vision.faces, vision.analyse, sound.ensure_built, sound._classify = real
    sh = desc["shots"]
    check("with the Mac's readers: every reading is in have", desc["have"] == ["motion", "faces", "sound", "words",
                                                                              "labels", "music"], str(desc["have"]))
    check("  valid", D.validate(desc) == [], "; ".join(D.validate(desc)))
    w = desc["words"] or []
    check("  the caption on the second shot, at the top, in capitals, text dropped",
          len(w) == 1 and w[0]["band"] == "top" and abs(w[0]["t"] - lens[0]) <= 0.5 and abs(w[0]["d"] - lens[1]) <= 0.6
          and w[0]["upper"] == 1.0 and w[0]["n"] == 2 and "text" not in w[0], str(w))
    check("  a face on the first shot only, looking in", sh[0]["face"] == 1.0 and sh[0]["facing"] == 1.0
          and sh[0]["people"] == 1 and all(s["face"] == 0.0 for s in sh[2:]), str([s["face"] for s in sh]))
    check("  each shot labelled from its own mid frame, top three", [s["labels"][0] for s in sh] == [f"shot{k}" for k in range(6)]
          and all(len(s["labels"]) == 3 and s["aesthetic"] == 0.25 for s in sh), str([s["labels"] for s in sh]))
    check("  voice on the first shot, music all through", sh[0]["voice"] > 0.8 and sh[3]["voice"] == 0.0
          and desc["music"]["on"] == 1.0 and all(s["music"] == 0.8 for s in sh), f"{sh[0]['voice']} {desc['music']}")


# --------------------------------------------------------------------------
# a VibeCut board
# --------------------------------------------------------------------------

def _clip(cid: str, hour: int, labels: list[str], dur: float = 12.0, faces=None, voice=None, motion=None) -> dict:
    n = int(np.ceil(dur))
    c = {"id": cid, "name": f"{cid}.MOV", "duration": dur, "path": f"/nowhere/{cid}.MOV",
         "capture_time": f"2026-05-02T{hour:02d}:00:00+0900", "gps": None,
         "shots": [{"index": 0, "start": 0.0, "end": dur, "thumb": "shot000.jpg", "best_t": dur / 2, "quality": 0.6,
                    "aesthetic": 0.3, "utility": False, "labels": [[lb, 0.9 - 0.1 * i] for i, lb in enumerate(labels)],
                    "faces": 0, "face_area": 0.0, "embedding": [1.0 if j == hour % 8 else 0.0 for j in range(8)]}],
         "signals": {"motion": motion if motion is not None else [1.0] * n, "quality": [0.6] * n},
         "faces": faces if faces is not None else [],
         "marks": []}
    if voice is not None:
        c["sound"] = {"backend": "soundanalysis", "voice": voice, "music": [0.1] * n, "singing": [0.0] * n,
                      "laughter": [0.0] * n}
    return c


def _board_clips() -> dict:
    talk = [[1.0, 0.0, 1, 1.0]] * 4 + [[0.0, 0.0, 0, -1.0]] * 8         # on camera, looking in, for 4 s
    two = [[0.6, 0.0, 2, 0.0]] * 12                                    # two people, turned away
    clips = [
        _clip("hook00000001", 9, ["sky", "structure", "outdoor", "road"], faces=[[0.0, 0.0, 0, -1.0]] * 12,
              voice=[0.0] * 12, motion=[5.0] * 12),
        _clip("talk00000001", 10, ["people", "room"], faces=talk, voice=[0.9] * 4 + [0.05] * 8,
              motion=[0.5] * 4 + [3.0] * 8),
        _clip("cafe00000001", 11, ["food", "cup"], faces=[], voice=None, motion=[2.0] * 12),
        _clip("park00000001", 13, ["grass", "tree"], faces=two, voice=[0.3] * 12, motion=[4.0] * 12),
    ]
    return {c["id"]: c for c in clips}


def _board_ops() -> list[dict]:
    snap = {"option": "made", "name": "Made", "structure": "", "beats": [
        {"id": "r0", "title": "Hook", "detail": "", "shots": [{"id": "hook00000001:0", "start": 2.0, "end": 4.0}]},
        {"id": "r1", "title": "Morning", "detail": "", "shots": [
            {"id": "talk00000001:0", "start": 1.0, "end": 3.0},
            {"id": "talk00000001:0", "key": "talk00000001:0~5000", "start": 5.0, "end": 7.0},
            {"id": "cafe00000001:0", "start": 3.0, "end": 5.0}]},
        {"id": "r2", "title": "Park", "detail": "", "shots": [{"id": "park00000001:0", "start": 2.0, "end": 5.0}]},
    ]}
    return [
        {"op": "choose_option", "option": "made", "snapshot": snap},
        {"op": "set_look", "look": "hype"},
        {"op": "set_transition", "shot": "hook00000001:0", "kind": "flash", "dur": 0.2},
        {"op": "add_overlay", "kind": "title", "text": "Tokyo day", "start": 0.0},
        {"op": "add_overlay", "kind": "part", "text": "morning", "beat": "r1", "pos": "top", "size": "S"},
        {"op": "add_overlay", "kind": "caption", "text": "best coffee in town", "shot": "cafe00000001:0"},
        {"op": "set_music", "track": TRACK.id, "in": 0.0, "gain": 0.85, "original": 0.12},
    ]


def make_board(ops: list[dict], clips: dict):
    from web.backend import board as bd
    cat = bd.Catalog.from_clips(list(clips.values()))
    b, n = None, [0]

    def new_id() -> str:
        n[0] += 1
        return f"o{n[0]}"
    for op in ops:
        b, _ = bd.apply(b, op, cat, None, new_id)
    return b, cat


TRACK = music.Track(path="song1.m4a", duration=60, bpm=120.0, energy=np.zeros(60, np.float32),
                    meta={"tempo": {"phase": 0.0}})


def board_tests() -> None:
    print("from a board")
    clips = _board_clips()
    track = TRACK
    b, cat = make_board(_board_ops(), clips)

    # nothing may be decoded or run: no ffmpeg, no media.load
    real = (subprocess.run, subprocess.Popen, media_mod.load, media_mod.load_index)

    def refuse(*a, **k):
        raise AssertionError("from_board decoded something")
    subprocess.run = subprocess.Popen = media_mod.load = media_mod.load_index = refuse
    try:
        desc = D.from_board(b, clips, cat, "short", roles={"hook00000001:0": "hook", "talk00000001:0~5000": "talk"},
                            track=track)
        bare = D.from_board(b, clips, None, "wide")
        decoded = False
    except AssertionError:
        decoded = True
    finally:
        subprocess.run, subprocess.Popen, media_mod.load, media_mod.load_index = real
    check("nothing decoded, no ffmpeg run", not decoded)
    if decoded:
        return
    check("valid", D.validate(desc) == [], "; ".join(D.validate(desc)))
    shots = desc["shots"]
    check("five shots, in playing order, edit seconds", [s["d"] for s in shots] == [2.0, 2.0, 2.0, 2.0, 3.0]
          and [s["t"] for s in shots] == [0.0, 2.0, 4.0, 6.0, 8.0], str([(s["t"], s["d"]) for s in shots]))
    kinds = [j["kind"] for j in desc["joins"]]
    # a reel's reader sees a swipe as a cut, so the board says so too and keeps what it drew
    check("joins: flash after the hook, jump in the talk, cut inside a part, swipe between parts (read as a cut)",
          kinds == ["flash", "jump", "cut", "cut"] and desc["joins"][3].get("drawn") == "swipe"
          and all("drawn" not in j for j in desc["joins"][:3]), str([(j["kind"], j.get("drawn")) for j in desc["joins"]]))
    check("  the flash lasts what the plan gives it, the swipe read as a cut none", abs(desc["joins"][0]["dur"] - 0.2) < 0.01
          and desc["joins"][3]["dur"] == 0.0, str([j["dur"] for j in desc["joins"]]))
    check("  the jump is marked as the same picture", [s["same"] for s in shots] == [False, False, True, False, False])
    t, c = shots[1], shots[2]
    check("talking to the lens: the clip's own seconds 1-3", t["face"] == 1.0 and t["facing"] == 1.0
          and t["people"] == 1 and t["voice"] == 0.9, f"{t['face']} {t['facing']} {t['people']} {t['voice']}")
    check("the same clip later, nobody there", c["face"] == 0.0 and c["facing"] is None and c["voice"] == 0.05,
          f"{c['face']} {c['facing']} {c['voice']}")
    check("motion from the clip's seconds", t["motion"] == 0.5 and c["motion"] == 3.0 and shots[0]["motion"] == 5.0,
          str([s["motion"] for s in shots]))
    cafe, park = shots[3], shots[4]
    check("a clip with no faces read: unknown, not none", cafe["face"] is None and cafe["voice"] is None)
    check("two people turned away", park["people"] == 2 and park["facing"] == 0.0, f"{park['people']} {park['facing']}")
    check("top three labels from the catalogue", shots[0]["labels"] == ["sky", "structure", "outdoor"]
          and shots[0]["aesthetic"] == 0.3, str(shots[0]["labels"]))
    check("roles by entry key, the rest unknown", [s["role"] for s in shots] == ["hook", None, "talk", None, None])
    check("chapters are the board's parts", [s["chapter"] for s in shots] == [0, 1, 1, 1, 2])
    check("most shots have faces and voice: read", desc["have"] == ["motion", "faces", "sound", "words", "labels",
                                                                     "roles", "music"], str(desc["have"]))
    w = {e["kind"]: e for e in desc["words"]}
    check("words: the title in the middle, the part on top, the caption at the bottom",
          w["title"]["band"] == "middle" and w["part"]["band"] == "top" and w["caption"]["band"] == "bottom",
          str([(e["kind"], e["band"]) for e in desc["words"]]))
    check("  their sizes: title biggest, a small part line", w["title"]["size"] > w["caption"]["size"] > w["part"]["size"],
          str({k: e["size"] for k, e in w.items()}))
    check("  hype caps the title, the soft caption is lowercase", w["title"]["upper"] == 1.0 and w["caption"]["upper"] == 0.0,
          str({k: e["upper"] for k, e in w.items()}))
    check("  word counts, and the text itself not kept", w["caption"]["n"] == 4 and w["title"]["n"] == 2
          and not any("text" in e for e in desc["words"]), "")
    check("  the caption on the cafe shot", abs(w["caption"]["t"] - 6.0) < 0.01, str(w["caption"]["t"]))
    check("music on, its tempo and cuts on its beat", desc["music"]["on"] == 1.0 and desc["music"]["bpm"] == 120.0
          and desc["music"]["beat"] == 1.0, str(desc["music"]))
    check("a board: short, vertical, never cut off, no loudness", desc["group"] == "short" and desc["vertical"]
          and not desc["cutoff"] and desc["lufs"] is None and desc["source"] == "board" and desc["id"] is None, "")
    check("hype neither opens nor closes on black", not desc["open"] and not desc["close"])
    check("no catalogue: labels from the clip's index; wide is long and horizontal",
          bare["shots"][0]["labels"] == ["sky", "structure", "outdoor"] and bare["group"] == "long"
          and not bare["vertical"] and "roles" not in bare["have"], str(bare["shots"][0]["labels"]))
    check("  the track not in hand: tempo unknown, music still on", bare["music"]["on"] == 1.0 and bare["music"]["bpm"] is None)

    # the one respect: a quiet look dips between parts and fades the ends; no music
    ops = [o for o in _board_ops() if o["op"] not in ("set_transition", "set_music")]
    ops[1] = {"op": "set_look", "look": "quiet"}
    q, cat = make_board(ops, clips)
    qd = D.from_board(q, clips, cat, "tall")
    kinds = [j["kind"] for j in qd["joins"]]
    check("a quiet look instead: dips between parts, opens and closes on black, no music",
          kinds == ["dip_black", "jump", "cut", "dip_black"] and qd["open"] and qd["close"]
          and qd["music"]["on"] == 0.0 and qd["group"] == "long", str(kinds))
    check("  still valid", D.validate(qd) == [], "; ".join(D.validate(qd)))

    # save / load round trip; a broken one is refused
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x" / "B1.json"
        D.save(desc, p)
        check("save / load round trip", D.load(p) == desc)
        broken = {**desc, "joins": desc["joins"][:-1]}
        try:
            D.save(broken, Path(d) / "bad.json")
            refused = False
        except ValueError:
            refused = True
        check("a broken description is not saved", refused and not (Path(d) / "bad.json").exists())


# --------------------------------------------------------------------------
# pure helpers, on stand-in data
# --------------------------------------------------------------------------

def helper_tests() -> None:
    print("helpers")
    tr = [0.0, 1.0, 1.0, 0.0]
    check("a span's mean weights each second by how much it covers",
          abs(D.span_mean(tr, 0.5, 2.0) - (0.5 * 0.0 + 1.0 * 1.0) / 1.5) < 1e-3, str(D.span_mean(tr, 0.5, 2.0)))
    check("  a span inside one second is that second", D.span_mean(tr, 1.2, 1.7) == 1.0)
    check("  no track, or past its end: unknown", D.span_mean([], 0, 1) is None and D.span_mean(tr, 5, 6) is None)
    rows = [[1.0, 0, 1, 1.0], [1.0, 0, 2, 0.0], [0.0, 0, 0, -1.0]]
    f, fc, pp = D.face_reading(rows, 0, 3)
    check("faces: mean presence, facing over the face's seconds, most people", abs(f - 2 / 3) < 1e-3 and fc == 0.5
          and pp == 2, f"{f} {fc} {pp}")
    check("  no direction from the OS: facing unknown", D.face_reading([[1.0, 0, 1, -1.0]], 0, 1)[1] is None)
    check("  old two-column rows: people and facing unknown", D.face_reading([[0.8, 0.1]], 0, 1) == (0.8, None, None))

    def it(text, y, h=0.05, conf=0.9):
        return {"text": text, "box": [0.1, y, 0.5, h], "conf": conf}
    low, top = 0.1, 0.8
    samples = [{"t": k / 2, "items": []} for k in range(16)]
    for k in (1, 2, 3, 5):                                 # 4 is the recogniser missing a frame
        samples[k]["items"] = [it("GOOD MORNING", low)]
    for k in (2, 3):
        samples[k]["items"].append(it("day one", top, h=0.03))
    for k in (9, 10, 12):                                  # 11 wasn't read at all
        samples[k]["items"] = [it("coffee time", low)]
    samples[11]["items"] = None
    samples[14]["items"] = [it("noise", low, conf=0.1)]    # too unsure to count
    ev = D.word_events(samples)
    check("one card per run in a band; a missed frame and an unread one bridge",
          [(e["t"], e["d"], e["band"]) for e in ev] == [(0.5, 2.5, "bottom"), (1.0, 1.0, "top"), (4.5, 2.0, "bottom")],
          str([(e["t"], e["d"], e["band"]) for e in ev]))
    check("  caps, size and word count per card", ev[0]["upper"] == 1.0 and ev[1]["upper"] == 0.0
          and ev[0]["size"] == 0.05 and ev[1]["size"] == 0.03 and ev[0]["n"] == 2 and ev[2]["n"] == 2, "")
    check("  the words themselves are dropped", not any("text" in e for e in ev) and all(e["kind"] is None for e in ev))
    check("band from the box centre", D.band_of([0, 0.05, 0.5, 0.1]) == "bottom" and D.band_of([0, 0.45, 0.5, 0.1]) == "middle"
          and D.band_of([0, 0.85, 0.5, 0.1]) == "top")

    # validate: a fine description passes, each break is named
    good = {"v": 1, "id": None, "source": "board", "group": "short", "vertical": True, "duration": 3.0, "cutoff": False,
            "have": ["motion"], "shots": [D._shot(0.0, 1.0), D._shot(1.0, 2.0)],
            "joins": [{"t": 1.0, "kind": "cut", "dur": 0.0}], "open": False, "close": False, "words": [],
            "music": {"bpm": None, "on": 0.0, "beat": None}, "lufs": None}
    check("validate: a fine description has no problems", D.validate(good) == [], "; ".join(D.validate(good)))
    breaks = {
        "an unknown join": {**good, "joins": [{"t": 1.0, "kind": "wipe", "dur": 0.0}]},
        "joins and shots disagree": {**good, "joins": []},
        "an unknown role": {**good, "shots": [D._shot(0.0, 1.0, role="hero"), D._shot(1.0, 2.0)]},
        "a face out of range": {**good, "shots": [D._shot(0.0, 1.0, face=1.7), D._shot(1.0, 2.0)]},
        "shots overlapping": {**good, "shots": [D._shot(0.0, 1.0), D._shot(0.5, 2.0)]},
        "an unknown reading": {**good, "have": ["motion", "smell"]},
        "words keeping their text": {**good, "words": [{"t": 0, "d": 1, "band": "top", "size": 0.1, "upper": 0,
                                                        "n": 1, "kind": None, "text": "hi"}]},
        "a band that isn't one": {**good, "words": [{"t": 0, "d": 1, "band": "side", "size": 0.1, "upper": 0,
                                                     "n": 1, "kind": None}]},
        "the wrong version": {**good, "v": 2},
    }
    caught = [name for name, x in breaks.items() if D.validate(x)]
    check("validate: every break is caught", caught == list(breaks), f"missed {set(breaks) - set(caught)}")


def main() -> int:
    helper_tests()
    board_tests()
    with tempfile.TemporaryDirectory() as d:
        video_tests(d)
    print(f"\n{'FAIL' if failures else 'PASS'}: {len(failures)} failed" + (f" ({', '.join(failures)})" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
