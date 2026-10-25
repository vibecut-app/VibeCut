"""Does the other frame's crop keep the people in the shot?

A wide shot with someone standing left of centre, cropped to a vertical
version, keeps the middle third of its width: the person is cut out. From
face boxes like Vision's (bottom-left origin, written to the cache so the
test runs anywhere), the crop has to move onto them:

- a person left of centre and one right of centre are both centred in the
  vertical version, where a middle crop loses them both (the same render
  with aiming off is the control);
- a vertical shot in a wide version keeps the face at HEAD_AT of the
  height, with headroom, where the middle crop cuts it off;
- a shot with nobody in it, or a face on too few samples, keeps the
  middle; a shot filled by hand is never moved (the preview shows it
  centred); the note says how many were kept on people;
- two people who fit are kept together, two who don't keep the larger;
- a point is turned the way export._shot turns the picture (checked
  against numpy's own rotation of an image);
- the face areas sent to the browser (export.face_areas, for moving
  captions off faces) sit where the person is in the rendered file, cropped
  or between bars, and only a version sends them; moved captions are noted.

Needs ffmpeg. Takes ~15 s.

    python tests/test_aim.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = Path(tempfile.mkdtemp(prefix="vibecut-aim-"))
os.environ["VIBECUT_EXPORTS"] = str(TMP / "out")
os.environ.setdefault("VIBECUT_CACHE", str(TMP / "cache"))
os.environ.setdefault("VIBECUT_BED", "0")

from web.backend import aim, export  # noqa: E402
from web.backend.indexer import clip_dir  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def clip(cid: str, w: int, h: int, box: tuple[float, float, float, float] | None, seen: int = 3) -> dict:
    """A 3 s clip, black, with a white block where `box` says (x, y, w, h,
    top-left shares) -- the "person" -- and faceboxes.json saying a face is
    there on the first `seen` of its 3 samples."""
    path = TMP / f"{cid}.mp4"
    draw = ""
    if box:
        x, y, bw, bh = box
        draw = f",drawbox=x={int(x * w)}:y={int(y * h)}:w={int(bw * w)}:h={int(bh * h)}:color=white:t=fill"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:r=30:d=3",
                    "-vf", "format=yuv420p" + draw, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    d = clip_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    vb = [[box[0], 1 - box[1] - box[3], box[2], box[3], 0.0]] if box else []
    (d / "faceboxes.json").write_text(json.dumps([vb if i < seen else [] for i in range(3)]))
    return {"id": cid, "path": str(path), "width": w, "height": h, "duration": 3.0,
            "samples": {"times": [0.0, 1.0, 2.0], "files": [f"samples/{i}.jpg" for i in range(3)]}}


def render(items, clips, want):
    job = export.create(items, clips, "aim", None, want=want, crop=True)
    export.start(job, [])
    for _ in range(400):
        if job.stage in ("done", "error"):
            break
        time.sleep(0.1)
    assert job.stage == "done", job.error
    return job


def white(path: str, t: float, w: int, h: int) -> tuple[float, float] | None:
    """Centre (x, y) in pixels of the white block on the frame at t, or None."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    g = np.frombuffer(raw, np.uint8).reshape(h, w) > 128
    if g.sum() < 50:
        return None
    ys, xs = np.nonzero(g)
    return float(xs.mean()), float(ys.mean())


def shots(spec):
    out, at = [], 0.0
    for cid, extra in spec:
        out.append({"kind": "shot", "clip_id": cid, "seq_start": at, "seq_end": at + 2.0,
                    "src_start": 0.5, "src_end": 2.5, **extra})
        at += 2.0
    return out


def rules() -> None:
    one = [[0.15, 0.5, 0.1, 0.2]]
    check("one face: its centre, top-left origin", aim.subject(one, (0.3, 1.0)) == (0.2, 0.4), str(aim.subject(one, (0.3, 1.0))))
    pair = [[0.30, 0.5, 0.08, 0.15], [0.45, 0.5, 0.1, 0.2]]
    x, _ = aim.subject(pair, (0.32, 1.0))
    check("two people who fit together are kept together", abs(x - (0.30 + 0.55) / 2) < 1e-9, f"{x:.3f}")
    apart = [[0.05, 0.5, 0.08, 0.15], [0.80, 0.5, 0.1, 0.2]]
    x, _ = aim.subject(apart, (0.32, 1.0))
    check("two who don't fit: the larger one is kept whole", abs(x - 0.85) < 1e-9, f"{x:.3f}")
    bg = [[0.1, 0.5, 0.2, 0.4], [0.9, 0.5, 0.02, 0.03]]
    x, _ = aim.subject(bg, (0.32, 1.0))
    check("a face in the background doesn't pull the window", abs(x - 0.2) < 1e-9, f"{x:.3f}")

    # a point marked on a 4x6 image, turned as ffmpeg turns it, lands where the point says
    img = np.zeros((4, 6))
    px, py = 1, 0
    img[py, px] = 1
    ok = True
    for rot, mirror in ((0, False), (90, False), (180, False), (270, False), (90, True), (0, True)):
        a = img[:, ::-1] if mirror else img
        a = {0: a, 90: np.rot90(a, -1), 180: np.rot90(a, 2), 270: np.rot90(a, 1)}[rot]   # transpose=1 is clockwise
        yy, xx = np.argwhere(a == 1)[0]
        h, w = a.shape
        tx, ty = aim.turned(((px + 0.5) / 6, (py + 0.5) / 4), rot, mirror)
        ok &= abs(tx * w - (xx + 0.5)) < 1e-9 and abs(ty * h - (yy + 0.5)) < 1e-9
    check("a point is turned and mirrored the way the picture is", ok)

    c = {"samples": {"times": [0.0, 1.0, 2.0, 3.0]}}
    face = [[0.15, 0.5, 0.1, 0.2]]
    check("only the shot's own seconds count", aim.aim({"src_start": 2.5, "src_end": 3.5}, c, [[], [], [], face], (0.3, 1)) is not None
          and aim.aim({"src_start": 0.0, "src_end": 1.5}, c, [[], [], [], face], (0.3, 1)) is None)
    check("a face on too few samples is no subject",
          aim.aim({"src_start": 0.0, "src_end": 3.0}, c, [face, [], [], []], (0.3, 1)) is None
          and aim.aim({"src_start": 0.0, "src_end": 3.0}, c, [face, face, [], []], (0.3, 1)) is not None)


def through_export() -> None:
    clips = {"left": clip("left", 1280, 720, (0.15, 0.3, 0.1, 0.2)),
             "right": clip("right", 1280, 720, (0.78, 0.3, 0.1, 0.2)),
             "empty": clip("empty", 1280, 720, None),
             "flash": clip("flash", 1280, 720, (0.15, 0.3, 0.1, 0.2), seen=1),
             "hand": clip("hand", 1280, 720, (0.15, 0.3, 0.1, 0.2))}
    items = shots([("left", {}), ("right", {}), ("empty", {}), ("flash", {}), ("hand", {"fill": True})])
    tall = render(items, clips, "tall")
    W, H = 1080, 1920
    at = [white(tall.path, 2 * k + 1.0, W, H) for k in range(5)]
    check("someone left of centre is centred in the vertical version", at[0] is not None and abs(at[0][0] - W / 2) < 40, str(at[0]))
    check("… and someone right of centre", at[1] is not None and abs(at[1][0] - W / 2) < 40, str(at[1]))
    check("a face seen only outside the shot's own seconds keeps the middle (and is cut out)", at[3] is None, str(at[3]))
    check("a shot filled by hand keeps the middle the preview shows", at[4] is None and "aim" not in tall.items[4], str(at[4]))
    check("the note says which were kept on people", any("4 shots filmed the other way are cropped to fill the frame: "
                                                         "2 kept on the people in them, 2 with nobody in them keep the middle" in n
                                                         for n in tall.notes), str(tall.notes))

    # the control: the same render with aiming off loses both people
    keep = aim.MIN_SEEN
    aim.MIN_SEEN = 2.0
    try:
        mid = render(items[:2], clips, "tall")
    finally:
        aim.MIN_SEEN = keep
    check("the middle crop loses them both (the control)", white(mid.path, 1.0, W, H) is None and white(mid.path, 3.0, W, H) is None)

    # a vertical shot in a wide version: the face sits at HEAD_AT down, with headroom
    clips["up"] = clip("up", 720, 1280, (0.4, 0.1, 0.2, 0.1))
    wide = render(shots([("up", {})]), clips, "wide")
    p = white(wide.path, 1.0, 1920, 1080)
    check("a face near the top of a vertical shot sits at HEAD_AT of the wide frame",
          p is not None and abs(p[1] - aim.HEAD_AT * 1080) < 30 and abs(p[0] - 960) < 30, str(p))
    check("… and every one was kept on people", any(n.endswith("is cropped to fill the frame, kept on the people in them.")
                                                     for n in wide.notes), str(wide.notes))

    # turned a quarter by hand: the face is found in the filmed picture and turned with it
    clips["side"] = clip("side", 720, 1280, (0.1, 0.1, 0.2, 0.1))   # a tall file, turned to lie wide: the face lands right of centre
    turned = render(shots([("side", {"rotate": 90})]), clips, "tall")
    p = white(turned.path, 1.0, W, H)
    check("a shot turned by hand is aimed in its turned picture", p is not None and abs(p[0] - W / 2) < 40, str(p))


def faces_in_frame() -> None:
    """Where the faces land in the version's frame -- what the browser moves
    captions off -- checked against where the person really is in the file."""
    clips = {"left": clip("left", 1280, 720, (0.15, 0.3, 0.1, 0.2)),
             "boxed": clip("boxed", 720, 960, (0.4, 0.4, 0.2, 0.2))}    # 3:4 in 9:16: shown whole, bars above and below
    job = render(shots([("left", {}), ("boxed", {})]), clips, "tall")
    W, H = 1080, 1920
    areas = export.face_areas(job)
    check("a face area for each shot with a face, timed to the shot", [(a["start"], a["end"]) for a in areas] == [(0.0, 2.0), (2.0, 4.0)],
          json.dumps(areas))
    for k, a in enumerate(areas):
        x, y, w, h = a["boxes"][0]
        got = white(job.path, 2 * k + 1.0, W, H)
        check(f"shot {k + 1}: the face area is where the person is in the file",
              got is not None and abs((x + w / 2) * W - got[0]) < 0.02 * W and abs((y + h / 2) * H - got[1]) < 0.02 * H,
              f"area centre ({(x + w / 2) * W:.0f}, {(y + h / 2) * H:.0f}) vs file {got}")
    x, y, w, h = areas[0]["boxes"][0]
    check("the face the crop centred is in the middle across", abs(x + w / 2 - 0.5) < 0.02, f"{x + w / 2:.3f}")
    bx, by, bw, bh = areas[1]["boxes"][0]
    band = (H - 1440) / 2 / H
    check("a shot shown whole between bars maps inside the picture band", by >= band and by + bh <= 1 - band, f"{by:.3f}–{by + bh:.3f}")
    check("asking again doesn't aim twice or say it twice", export.face_areas(job) == areas
          and sum("cropped to fill the frame" in n for n in job.notes) == 1, str(job.notes))

    from web.backend import app as A
    plain = export.create(shots([("left", {})]), clips, "plain", None, want="tall")
    check("an export in the edit's own frame sends no faces (its captions are as the preview showed)",
          A.api_export_faces(plain.id) == {"faces": []})
    alt = export.create(shots([("left", {})]), clips, "alt", None, want="tall", crop=True)
    check("a version sends its faces", A.api_export_faces(alt.id)["faces"][0]["boxes"])
    started = A.api_export_start(alt.id, A.ExportStartReq(schedule=[], moved=2))
    check("captions the browser moved are said in the export's notes",
          "2 captions moved so they don’t sit on anyone’s face in this frame." in started["notes"], str(started["notes"]))
    one = export.create(shots([("left", {})]), clips, "one", None, want="tall", crop=True)
    check("… one in the singular, none says nothing",
          "1 caption moved so it doesn’t sit on anyone’s face in this frame." in A.api_export_start(one.id, A.ExportStartReq(moved=1))["notes"]
          and not any("moved" in n for n in A.api_export_start(plain.id, A.ExportStartReq())["notes"]))
    for j in (alt, one, plain):
        for _ in range(300):
            if j.stage in ("done", "error"):
                break
            time.sleep(0.1)


def main() -> int:
    rules()
    through_export()
    faces_in_frame()
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
