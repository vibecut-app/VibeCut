"""Does the jump-cut reading tell a jump from movement?

A jump cut keeps the camera and the room and moves the person in one frame.
The fixtures share that room and that person and differ only in how the
person gets from one place to the other: in one frame (a jump), smoothly
walking to and fro, or in quick real movements. Only the first may be
read as a jump, and it must be found on the frame it was made.

    python tests/test_jump_cuts.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cutgrammar import media, shots  # noqa: E402

W, H, FPS, SECONDS = 320, 180, 30, 4.0
N = int(FPS * SECONDS)
JUMP_AT = 61          # first frame after the jump (t = 2.03 s)
LEFT, RIGHT = 70, 190  # where the person stands before / after


def _room(seed: int = 3) -> np.ndarray:
    """A still, textured background: blocks of light and dark, softened."""
    rng = np.random.default_rng(seed)
    small = rng.integers(40, 220, size=(9, 16, 3)).astype(np.float32)
    big = np.repeat(np.repeat(small, 20, axis=0), 20, axis=1)
    k = np.ones(9) / 9
    for ax in (0, 1):
        big = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), ax, big)
    return big


def _frames(xs: list[float], rate: int = FPS, seed: int = 3) -> np.ndarray:
    """The room with a person (a tall dark figure with a light face) at x,
    bobbing a little as someone talking does, plus a touch of sensor noise."""
    room = _room(seed)
    rng = np.random.default_rng(seed + 1)
    out = np.empty((len(xs), H, W, 3), dtype=np.uint8)
    for i, x in enumerate(xs):
        f = room.copy()
        x0 = int(round(x))
        y0 = 50 + int(round(2 * np.sin(2 * np.pi * i / rate)))
        f[y0:y0 + 120, x0:x0 + 60] = (35, 30, 60)
        f[y0 + 5:y0 + 40, x0 + 15:x0 + 45] = (225, 190, 170)
        f += rng.normal(0, 1.5, f.shape)
        out[i] = np.clip(f, 0, 255).astype(np.uint8)
    return out


def _write(frames: np.ndarray, path: str, rate: int = FPS) -> str:
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(rate), "-i", "-",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
         "-pix_fmt", "yuv420p", path],
        input=frames.tobytes(), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[:400])
    return path


def fixtures(d: str) -> dict[str, str]:
    jump = [LEFT if i < JUMP_AT else RIGHT for i in range(N)]
    # Pacing: the same room, the person walking to and fro the whole shot.
    glide = [LEFT + (RIGHT - LEFT) * abs(((i / (N / 8)) % 2) - 1) for i in range(N)]
    # Real movement: stands, crosses the room in a third of a second, stands.
    burst = [LEFT + (RIGHT - LEFT) * min(max((i - 55) / 10, 0), 1) for i in range(N)]
    # Fidgeting: three quick sideways steps and back.
    fidget = [LEFT + 30 * abs(np.sin(np.pi * i / 8)) if 20 <= i < 44 or 70 <= i < 94
              else LEFT for i in range(N)]
    # A 30 fps crossing conformed into a 60 fps file: each picture twice, so
    # the movement is every other frame changing.
    walk = [LEFT + (RIGHT - LEFT) * min(max((i - 40) / 20, 0), 1) for i in range(N)]
    doubled = [x for x in walk for _ in range(2)]
    return {
        "jump": _write(_frames(jump), os.path.join(d, "jump.mp4")),
        "glide": _write(_frames(glide), os.path.join(d, "glide.mp4")),
        "burst": _write(_frames(burst), os.path.join(d, "burst.mp4")),
        "fidget": _write(_frames(fidget), os.path.join(d, "fidget.mp4")),
        "doubled": _write(_frames(doubled, rate=2 * FPS), os.path.join(d, "doubled.mp4"),
                          rate=2 * FPS),
    }


def main() -> int:
    failures = []

    def check(name: str, cond: bool, got: str) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}: {got}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as d:
        print("building fixtures...")
        found = {}
        for name, path in fixtures(d).items():
            m = media.load(path)
            sh = shots.detect(m)
            found[name] = (m, sh, shots.jump_cuts(m, sh))

        m, sh, j = found["jump"]
        check("the histogram doesn't call the jump a cut", len(sh) == 1, f"{len(sh)} shots")
        check("one jump in the jump-cut take", len(j) == 1, f"frames {j}")
        if j:
            check("found on the frame it was made (within 1)", abs(j[0] - JUMP_AT) <= 1,
                  f"frame {j[0]} ({m.t(j[0]):.2f} s) vs {JUMP_AT} ({JUMP_AT / FPS:.2f} s)")

        for name, what in (("glide", "walking to and fro"),
                           ("burst", "a quick real crossing"),
                           ("fidget", "fidgeting"),
                           ("doubled", "movement at half the file's rate")):
            _, sh, j = found[name]
            check(f"no jump in {what}", j == [], f"{len(sh)} shots, jumps at {j}")

        # Keyframe samples can't show a jump; the reading says nothing there.
        idx = media.load_index(os.path.join(d, "jump.mp4"), audio=False)
        check("index media gives no reading", shots.jump_cuts(idx, shots.detect(idx)) == [],
              f"{idx.n_frames} samples")

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
