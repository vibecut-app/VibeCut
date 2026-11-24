"""Does the aligner find where each shot of an edit came from (taste/pairs.py)?

Raw clips made with ffmpeg (moving patterns, so every moment looks
different), and an edit cut from them the way a pro would: a stretch
graded brighter and punchier, one punched in, one sped up 2x, one from a
clip that wasn't shared, and a second stretch of the first clip. Each
shot must come back with its clip and stretch to a twentieth of a second and
its speed; the shot from the unshared clip must stay unmatched.

    python tests/test_pairs.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cutgrammar import media  # noqa: E402
from taste import pairs as P  # noqa: E402

failures: list[str] = []
FPS = 30
RAW = {"A": "testsrc2", "B": "testsrc", "C": "life=s=640x360:mold=10:r=30:ratio=0.5:death_color=#203040:life_color=#f0c060",
       "D": "cellauto=s=640x360:r=30:rule=110"}


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def _ff(args: list[str]) -> None:
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-600:])


def raw(path: str, src: str, dur: float = 10.0) -> None:
    spec = src if "=" in src and "s=" in src else f"{src}=size=640x360:rate={FPS}"
    _ff(["-f", "lavfi", "-i", f"{spec}", "-t", f"{dur}", "-vf", "format=yuv420p",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", path])


# (clip, in, out, filter) -> the edit, hard cuts
CUTS = [("A", 2.0, 4.0, "eq=brightness=0.08:contrast=1.3:saturation=1.4"),
        ("B", 5.0, 6.5, "crop=iw/1.15:ih/1.15,scale=640:360"),
        ("C", 1.0, 5.0, "setpts=0.5*PTS"),
        ("D", 0.0, 1.5, None),
        ("A", 7.0, 8.2, None)]


def edit(path: str, files: dict[str, str]) -> list[float]:
    inputs, parts, t, cuts = [], [], 0.0, []
    for i, (c, a, b, vf) in enumerate(CUTS):
        inputs += ["-i", files[c]]
        chain = f"[{i}:v]trim={a}:{b},setpts=PTS-STARTPTS"
        if vf:
            chain += f",{vf}"
        parts.append(chain + f",scale=640:360,setsar=1,fps={FPS},format=yuv420p[v{i}]")
        t += (b - a) * (0.5 if vf and "setpts=0.5" in vf else 1.0)
        cuts.append(round(t, 3))
    n = len(CUTS)
    fc = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    _ff([*inputs, "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", path])
    return cuts[:-1]


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        files = {k: str(Path(d) / f"{k}.mp4") for k in RAW}
        for k, src in RAW.items():
            raw(files[k], src)
        cuts = edit(str(Path(d) / "edit.mp4"), files)
        em = media.load(str(Path(d) / "edit.mp4"))
        srcs = [P.source(media.load(files[k]), k) for k in "ABC"]      # D was never shared
        shots = P.align(em, cuts, srcs)
    print("where each shot came from")
    for s, (c, a, b, vf) in zip(shots, CUTS):
        got = f"{s.get('clip')} {s.get('src_in')}..{s.get('src_out')} x{s.get('speed')} (agree {s.get('share')}, sim {s.get('sim')})"
        if c == "D":
            check("a shot from a clip that wasn't shared stays unmatched", s["clip"] is None, got)
            continue
        speed = 2.0 if vf and "setpts=0.5" in vf else 1.0
        what = {"eq": "graded", "crop": "punched in", "setpts": "sped up"}.get((vf or "").split("=")[0], "as filmed")
        check(f"clip {c}, {what}: its clip and stretch",
              s["clip"] == c and abs(s["src_in"] - a) <= 0.05 and abs(s["src_out"] - b) <= 0.05, got)
        check(f"clip {c}, {what}: its speed", s.get("speed") == speed, got)
    k = P.kept(shots)
    check("clip A's two kept stretches, in order", k.get("A") and len(k["A"]) == 2 and k["A"][0][0] < k["A"][1][0], str(k.get("A")))
    cov = P.coverage(shots)
    check("coverage counts only what was placed", abs(cov - (1 - 1.5 / 8.2)) < 0.02, f"{cov:.3f}")
    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
