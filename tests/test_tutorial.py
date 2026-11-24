"""Does the tutorial reader find what an editor kept of each clip (taste/tutorial.py)?

A made-up screen recording of someone editing, built with ffmpeg the way
the "edit my vlog with me" videos look: a host talking first (here a
moving gradient), then the editor's screen -- a toolbar, a media panel, a
face cam in the corner, a timeline strip that scrolls sideways under a
fixed playhead the whole time -- and in its preview window five raw clips
played one after another with pauses between, the recording sped up 2x;
then the timeline played through; then the finished vlog full screen.
The finished vlog keeps two stretches of clip A, one of B, one of C sped
up 2x in the edit, and one of E; clip D was played and dropped.

The reader must find the preview window (not the face cam, not the
scrolling strip), the recording's speed, each kept stretch in its clip's
own seconds, the sped-up shot as sped up, and D as played and dropped.
With the finished vlog posted separately it must find the same. Then the
learner: on made-up records where editors cut in as the camera settles,
it must beat Make's rule on creators it never saw, and Make must ask it
only once it's trusted.

    python tests/test_tutorial.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taste import tutorial as T  # noqa: E402

failures: list[str] = []
FPS = 30
W, H = 960, 540


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def _ff(args: list[str]) -> None:
    p = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *args], capture_output=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-800:])


# raw clips: a moving test pattern, and pans across detailed stills (like a walk past a wall)
STILLS = {"C": "mandelbrot=s=1920x1080", "D": "sierpinski=s=1920x1080:type=carpet",
          "E": "mandelbrot=s=1920x1080:start_x=-0.7436438870:start_y=0.1318259042:start_scale=0.02"}
LENGTH = {"A": 14.0, "B": 12.0, "C": 14.0, "D": 8.0, "E": 12.0}
PAN = {"C": ("200+t*70", "100+t*25"), "D": ("900-t*60", "400-t*30"), "E": ("100+t*80", "500-t*20")}
# the finished vlog: (clip, in, out, speed in the edit)
EDIT = [("A", 2.0, 6.0, 1.0), ("B", 3.0, 8.0, 1.0), ("C", 1.0, 7.0, 2.0), ("E", 2.0, 9.0, 1.0), ("A", 9.0, 13.0, 1.0)]
REC_SPEED = 2.0            # the editing part of the recording is shown at 2x


def raw(d: Path) -> dict[str, str]:
    files = {}
    for k, n in LENGTH.items():
        out = str(d / f"{k}.mp4")
        if k == "A":
            src = ["-f", "lavfi", "-i", f"testsrc2=size=480x270:rate={FPS}"]
            vf = "format=yuv420p"
        elif k == "B":
            src = ["-f", "lavfi", "-i", f"testsrc=size=480x270:rate={FPS}"]
            vf = "format=yuv420p"
        else:
            still = str(d / f"{k}.png")
            _ff(["-f", "lavfi", "-i", STILLS[k], "-frames:v", "1", still])
            x, y = PAN[k]
            src = ["-loop", "1", "-framerate", str(FPS), "-i", still]
            vf = f"crop=480:270:x='{x}':y='{y}',format=yuv420p"
        _ff([*src, "-t", f"{n}", "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", out])
        files[k] = out
    return files


def finished(d: Path, files: dict[str, str]) -> str:
    """The editor's finished vlog at 1x, 480 x 270."""
    out = str(d / "final.mp4")
    ins, parts = [], []
    for i, (c, a, b, sp) in enumerate(EDIT):
        ins += ["-i", files[c]]
        parts.append(f"[{i}:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{sp},fps={FPS},setsar=1,format=yuv420p[v{i}]")
    fc = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(EDIT))) + f"concat=n={len(EDIT)}:v=1:a=0[v]"
    _ff([*ins, "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", out])
    return out


def preview(d: Path, files: dict[str, str]) -> tuple[str, float]:
    """What the preview window shows, already sped up REC_SPEED: a held
    first frame, each raw clip whole with a pause after it, then the
    timeline played through and a pause."""
    out = str(d / "preview.mp4")
    ins, parts, n = [], [], 0
    order = ["A", "B", "C", "D", "E"]
    for i, c in enumerate(order):
        ins += ["-i", files[c]]
        lead = ":start_mode=clone:start_duration=2" if i == 0 else ""
        parts.append(f"[{i}:v]setpts=PTS/{REC_SPEED},fps={FPS},tpad=stop_mode=clone:stop_duration=1.5{lead},"
                     f"setsar=1,format=yuv420p[p{n}]")
        n += 1
    for j, (c, a, b, sp) in enumerate(EDIT):
        ins += ["-i", files[c]]
        k = len(order) + j
        tail = ",tpad=stop_mode=clone:stop_duration=2" if j == len(EDIT) - 1 else ""
        parts.append(f"[{k}:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{sp * REC_SPEED},fps={FPS}{tail},"
                     f"setsar=1,format=yuv420p[p{n}]")
        n += 1
    fc = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    _ff([*ins, "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", out])
    dur = sum(LENGTH[c] / REC_SPEED + 1.5 for c in order) + 2 + sum((b - a) / (sp * REC_SPEED) for _, a, b, sp in EDIT) + 2
    return out, dur


MON = (440, 40, 480, 270)


def recording(d: Path, files: dict[str, str], with_final: bool, name: str) -> str:
    prev, pdur = preview(d, files)
    strip = str(d / "strip.png")
    if not (d / "strip.png").exists():
        _ff(["-f", "lavfi", "-i", "cellauto=s=3000x50:rule=90:scroll=0:start_full=1", "-frames:v", "1", strip])
    ui = (f"color=c=0x1e1e1e:s={W}x{H}:r={FPS}:d={pdur},"
          "drawbox=x=0:y=0:w=960:h=28:color=0x2c2c2c:t=fill,"
          "drawbox=x=20:y=40:w=390:h=270:color=0x303030:t=fill,"
          "drawbox=x=36:y=56:w=110:h=62:color=0x5a5048:t=fill,drawbox=x=160:y=56:w=110:h=62:color=0x48505a:t=fill,"
          "drawbox=x=284:y=56:w=110:h=62:color=0x505a48:t=fill,drawbox=x=36:y=132:w=110:h=62:color=0x605858:t=fill,"
          "drawbox=x=0:y=330:w=960:h=210:color=0x262626:t=fill,"
          "drawbox=x=0:y=436:w=760:h=30:color=0x3a4a5a:t=fill")
    host = f"gradients=s={W}x{H}:r={FPS}:speed=0.03:d=20,format=yuv420p"
    fc = (f"{ui}[ui];[0:v]setsar=1[mon];[ui][mon]overlay=x={MON[0]}:y={MON[1]}:shortest=1[s1];"
          f"[1:v]setsar=1[strip];[s1][strip]overlay=x='-mod(t*120\\,1500)':y=370:shortest=1[s2];"
          f"[s2]drawbox=x=480:y=356:w=2:h=110:color=white:t=fill[s3];"
          f"color=c=0x556677:s=160x90:r={FPS}:d={pdur}[cam];color=c=0xd8a888:s=34x40:r={FPS}:d={pdur}[face];"
          f"[cam][face]overlay=x='60+18*sin(t*2)':y='22+8*cos(t*3)'[camf];"
          f"[s3][camf]overlay=x=790:y=440,fps={FPS},format=yuv420p[ed];{host}[host]")
    segs = "[host][ed]"
    n = 2
    ins = ["-i", prev, "-loop", "1", "-framerate", str(FPS), "-t", f"{pdur:.2f}", "-i", strip]
    if with_final:
        ins += ["-i", finished(d, files)]
        fc += f";[2:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p[fin]"
        segs += "[fin]"
        n = 3
    fc += f";{segs}concat=n={n}:v=1:a=0[v]"
    out = str(d / name)
    _ff([*ins, "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", out])
    return out


def kept_of(rec: dict) -> dict[str, list]:
    """The reader's clips named by which raw clip they are (by length and order)."""
    names = {}
    order = [c for c in ["A", "B", "C", "D", "E"]]
    t = 20.0 + 2.0     # host, then the held first frame
    starts = {}
    for c in order:
        starts[c] = t
        t += LENGTH[c] / REC_SPEED + 1.5
    for cl in rec.get("clips") or []:
        c = min(starts, key=lambda k: abs(starts[k] - cl["t0"]))
        names[c] = cl
    return names


def reader(rec: dict, label: str) -> None:
    pv = rec.get("preview") or [0, 0, 0, 0]
    want = [MON[0] / W, MON[1] / H, MON[2] / W, MON[3] / H]
    check(f"{label}: the preview window, not the face cam or the strip",
          all(abs(a - b) <= 0.03 for a, b in zip(pv, want)), f"{pv} vs {[round(x, 3) for x in want]}")
    check(f"{label}: the recording's speed", abs(rec.get("rate", 0) - 1 / REC_SPEED) <= 0.03, str(rec.get("rate")))
    names = kept_of(rec)
    for c, a, b, sp in EDIT:
        cl = names.get(c)
        got = None
        if cl:
            got = min(cl["kept"], key=lambda k: abs(k["in"] - a))
        # the recording's edge may clip the finished vlog's first cut in and last cut out: marked, not trusted
        edge = got is not None and got.get("cut_off")
        ok_in = got is not None and (abs(got["in"] - a) <= 0.3 or (edge and 0 <= got["in"] - a <= 0.6))
        ok_out = got is not None and (abs(got["out"] - b) <= 0.3 or (edge and 0 <= b - got["out"] <= 0.6))
        check(f"{label}: clip {c} {a:g}-{b:g} s kept, in the clip's own seconds", ok_in and ok_out,
              "" if got is None else f"{got['in']}-{got['out']} of {cl['length']} s" + (" (cut off)" if edge else ""))
        if got is not None:
            check(f"{label}: clip {c} {a:g}-{b:g} s {'sped up' if sp != 1 else 'at its own speed'}",
                  got["steady"] == (sp == 1.0), f"x{got['speed']}")
    for c in ("A", "C"):
        cl = names.get(c)
        check(f"{label}: clip {c}'s length", bool(cl) and abs(cl["length"] - LENGTH[c]) <= 0.5,
              "" if not cl else str(cl["length"]))
    drop = rec.get("dropped") or []
    d_ok = len(drop) == 1 and abs(drop[0]["length"] - LENGTH["D"]) <= 0.6
    check(f"{label}: clip D played and dropped, once", d_ok, str([(x["t0"], x["length"]) for x in drop]))
    cl = names.get("A")
    g = (cl or {}).get("grid") or {}
    check(f"{label}: once-a-second readings over the clip", len(g.get("subject") or []) == int(LENGTH["A"])
          and g["motion"][0] is None and all(v is not None for v in g["motion"][1:]),
          str(len(g.get("subject") or [])))


# --------------------------------------------------------------------------
# the learner, on made-up records
# --------------------------------------------------------------------------

def made_record(rng: np.random.Generator, creator: str, n_clips: int, how: str = "settle") -> dict:
    """Clips with random movement and subject. `settle`: each editor's
    window starts just after the camera settles (a calm stretch after a
    swing). `random`: the window sits anywhere, whatever the clip shows.
    `start`: it always starts where the playback did (an editor who
    scrubbed to the part they wanted, then pressed play). `preroll`: it
    starts just past ROOM, the first place a window can be learnt from (an
    editor who pressed play a beat early)."""
    clips = []
    for _ in range(n_clips):
        L = float(rng.integers(8, 16))
        n = int(L)
        mot = rng.uniform(5, 30, n)
        sub = rng.uniform(0.2, 0.8, n)
        edge = rng.uniform(0, 0.5, n)
        w = float(rng.integers(2, 4))
        k = int(rng.integers(2, n - int(w) - 1))
        if how == "settle":
            mot[k - 1] = 60.0                      # a swing...
            mot[k: k + int(w)] = rng.uniform(1, 4, int(w))   # ...then it settles: the editor cuts in here
            a = float(k) + 0.05
        elif how == "random":
            a = float(rng.uniform(0, L - w))
        elif how == "preroll":
            a = T.ROOM[0] + float(rng.uniform(0, 0.2))
        else:
            a = 0.0
        grid = {"motion": [None] + [round(float(x), 2) for x in mot[1:]], "subject": sub.round(3).tolist(),
                "edge": edge.round(3).tolist()}
        clips.append({"length": L, "kept": [{"in": a, "out": a + w, "steady": True}], "grid": grid})
    return {"v": T.VERSION, "id": creator, "creator": creator, "clips": clips, "dropped": []}


def learner() -> None:
    rng = np.random.default_rng(3)
    recs = [made_record(rng, f"creator{i}", 30) for i in range(10)]
    rep = T.evaluate(recs)
    r = rep.get("rank") or {}
    print(f"  ranks: {r}, gain {rep.get('gain')} ({rep.get('gain_low')}..{rep.get('gain_high')})")
    check("learner: finds 'cut in as the camera settles' on unseen creators, past the rule",
          r.get("model", 0) > max(r.get("rule", 1), r.get("middle", 1)) + 0.1 and T.wins(rep))
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d) / "recs"
        for x in recs:
            T.save(x, folder / f"{x['id']}.json")
        mp = Path(d) / "m.json"
        model = T.train(folder, mp, Path(d) / "r.md", log=lambda s: None)
        check("learner: trusted once it wins", bool(model and model["trusted"]))
        # Make: a clip whose camera settles at 6 s; the rule would take the busy second at 2
        mot = [None, 10, 70, 10, 8, 60, 2, 2, 2, 9, 8, 10]
        clip = {"signals": {"motion": [0.0] + mot[1:], "subject": [0.5] * 12, "edge": [0.1] * 12}}
        a = T.place(clip, 0.0, 12.0, 3.0, 0.6, 12.0, model=model)
        check("Make: the window starts as the camera settles", a is not None and 5.5 <= a <= 6.6, str(a))
        untrusted = dict(model, trusted=False)
        check("Make: an untrusted scorer leaves the rule alone",
              T.place(clip, 0.0, 12.0, 3.0, 0.6, 12.0, model=untrusted) is None)
        # select.window asks it, and VIBECUT_CUTS=0 keeps the rule
        from web.backend import select
        from web.backend import storyboard as sb
        old = T.MODEL
        T.MODEL = mp
        T._cache.clear()
        try:
            from datetime import datetime
            s = sb.Shot(id="c1:0", clip_id="c1", clip_name="IMG_1.MOV", index=0, start=0.0, end=12.0, thumb="",
                        quality=0.8, aesthetic=None, utility=False, when=datetime(2026, 11, 1, 12), gps=None,
                        labels={}, faces=0, face_area=0.0, activity=5.0, vec=np.zeros(4, dtype=np.float32))
            clips = {"c1": clip}
            got = select.window(clips, s, 3.0)
            check("Make: select.window takes the editors' window", 5.5 <= got[0] <= 6.6, str(got))
            os.environ["VIBECUT_CUTS"] = "0"
            rule = select.window(clips, s, 3.0)
            check("Make: VIBECUT_CUTS=0 keeps the rule's window", not 5.5 <= rule[0] <= 6.6, str(rule))
        finally:
            os.environ.pop("VIBECUT_CUTS", None)
            T.MODEL = old
            T._cache.clear()
    # windows that say nothing about the clip: never trusted, whatever the rules score
    say = {"random": "at random", "start": "where playback started", "preroll": "a beat after playback started"}
    for how in ("random", "start", "preroll"):
        rep0 = T.evaluate([made_record(rng, f"{how}{i}", 40, how) for i in range(20)])
        r0 = rep0.get("rank") or {}
        check(f"learner: windows placed {say[how]} teach nothing, and aren't trusted",
              (not r0 or abs(r0.get("model", 0) - 0.5) < 0.03) and not T.wins(rep0),
              f"{rep0.get('choices')} choices, {r0}, gain {rep0.get('gain')} ({rep0.get('gain_low')}..)")
    recs2 = [made_record(rng, f"r{i}", 3) for i in range(3)]
    rep2 = T.evaluate(recs2)
    check("learner: too few creators is never trusted", not T.wins(rep2), str(rep2.get("creators")))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        files = raw(d)
        print("a recording with the finished vlog at its end")
        path = recording(d, files, True, "rec.mp4")
        rec = T.read_video(path, id="T900", creator="someone", log=lambda s: print("   ", s))
        check("the finished vlog is the one shown at the end",
              (rec.get("final") or {}).get("source") == "shown" and (rec.get("final") or {}).get("t0", 0) > 50,
              str(rec.get("final") or rec.get("error")))
        reader(rec, "shown")
        print("a recording without it, the vlog posted on its own")
        path2 = recording(d, files, False, "rec2.mp4")
        rec2 = T.read_video(path2, id="T901", creator="someone", final_path=str(d / "final.mp4"),
                            log=lambda s: print("   ", s))
        check("the finished vlog is the posted one", (rec2.get("final") or {}).get("source") == "posted",
              str(rec2.get("final") or rec2.get("error")))
        reader(rec2, "posted")
        print("a video that isn't a screen recording")
        rec3 = T.read_video(files["A"], id="T902", creator="someone", log=lambda s: None)
        check("no editor's screen, no record of moves", "error" in rec3 and not rec3.get("clips"), rec3.get("error", ""))
    print("the learner")
    learner()
    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
