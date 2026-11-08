"""A wide Make fills the frame with vertical clips, the crop on the people.

The side-by-side of 2026-10-26: a wide Make of her 41 vertical clips showed
every shot as a strip between black bars, two thirds of the picture empty,
against two filled 16:9 vlogs. The crop that follows people (aim.py) was
only used for the one-click other-frame version. Each fixture differs from
its control in one respect:

- a vertical clip in a wide Make is filled and aimed at its face; a wide
  clip in the same Make is left alone (control); in a vertical Make it's
  the other way round;
- a vertical clip with nobody in it is filled and keeps the middle;
- the aim reaches the board (`set_shot aim`), the laid-out items and the
  export: rendered wide, the face of a vertical shot filmed near its top
  sits at HEAD_AT of the frame, where the same shot filled without the aim
  (the middle) cuts it out;
- turned or mirrored by hand, the point is dropped (it was found on the
  picture as it was); saved to My resources, a shot's settings never carry
  another picture's point.

Needs ffmpeg. Takes ~10 s.

    python tests/test_fill_aim.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = Path(tempfile.mkdtemp(prefix="vibecut-fillaim-"))
os.environ["VIBECUT_EXPORTS"] = str(TMP / "out")
os.environ.setdefault("VIBECUT_CACHE", str(TMP / "cache"))
os.environ.setdefault("VIBECUT_BED", "0")

from web.backend import aim, board as bd, export, make, select as sel, timeline  # noqa: E402
from web.backend.indexer import clip_dir  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def clip(cid: str, w: int, h: int, box: tuple[float, float, float, float] | None, bg: str = "black") -> dict:
    """A 3 s black clip with a white block (the "person") where `box` says
    (x, y, w, h, top-left shares), and faceboxes.json saying a face is there."""
    path = TMP / f"{cid}.mp4"
    draw = ""
    if box:
        x, y, bw, bh = box
        draw = f",drawbox=x={int(x * w)}:y={int(y * h)}:w={int(bw * w)}:h={int(bh * h)}:color=white:t=fill"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={bg}:s={w}x{h}:r=30:d=3",
                    "-vf", "format=yuv420p" + draw, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    d = clip_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    vb = [[box[0], 1 - box[1] - box[3], box[2], box[3], 0.0]] if box else []   # Vision's bottom-left origin
    (d / "faceboxes.json").write_text(json.dumps([vb for _ in range(3)]))
    return {"id": cid, "path": str(path), "width": w, "height": h, "duration": 3.0,
            "samples": {"times": [0.0, 1.0, 2.0], "files": [f"samples/{i}.jpg" for i in range(3)]}}


def pick(cid: str) -> sel.Pick:
    shot = SimpleNamespace(id=f"{cid}:0", start=0.0, end=3.0, clip_id=cid, clip_name=cid, when=None, gps=None, labels={})
    return sel.Pick(shot, "hero", 0.5, 2.5, 0.5, "", 0)


def white(path: str, t: float, w: int, h: int) -> tuple[float, float] | None:
    """Centre (x, y) in pixels of the white block on the frame at t, or None."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    g = np.frombuffer(raw, np.uint8).reshape(h, w) > 128
    if g.sum() < 50:
        return None
    ys, xs = np.nonzero(g)
    return float(xs.mean()), float(ys.mean())


def render(items, clips) -> export.Job:
    job = export.create(items, clips, "fill", None, want="wide")       # the edit's own frame: no other-frame version
    export.start(job, [])
    for _ in range(400):
        if job.stage in ("done", "error"):
            break
        time.sleep(0.1)
    assert job.stage == "done", job.error
    return job


def main() -> int:
    clips = {"up": clip("up", 720, 1280, (0.4, 0.08, 0.2, 0.1)),      # vertical, a face near the top
             "flat": clip("flat", 1280, 720, (0.45, 0.4, 0.1, 0.2)),   # wide
             "nobody": clip("nobody", 720, 1280, None)}               # vertical, no one in it
    plan = sel.Plan(hook=[], sessions=[[pick("up"), pick("flat"), pick("nobody")]], titles=["a"])

    print("which shots a Make fills")
    wide = {op["shot"]: op for op in make.fill_ops(plan, clips, "wide")}
    check("a vertical clip in a wide Make is filled, aimed at its face", "up:0" in wide and wide["up:0"]["fill"] and wide["up:0"].get("aim"),
          json.dumps(wide.get("up:0")))
    check("…at the face's centre (0.5 across, 0.13 down)", "up:0" in wide and abs(wide["up:0"]["aim"][0] - 0.5) < 0.02
          and abs(wide["up:0"]["aim"][1] - 0.13) < 0.02, json.dumps(wide.get("up:0")))
    check("control: a wide clip in the same Make is left alone", "flat:0" not in wide, str(sorted(wide)))
    check("a vertical clip with nobody in it is filled and keeps the middle",
          "nobody:0" in wide and wide["nobody:0"]["fill"] and "aim" not in wide["nobody:0"], json.dumps(wide.get("nobody:0")))
    tall = {op["shot"] for op in make.fill_ops(plan, clips, "tall")}
    check("in a vertical Make it's the other way round", tall == {"flat:0"}, str(tall))
    check("no clips known: nothing", make.fill_ops(plan, None, "wide") == [])

    print("on the board and the timeline")
    cat = None   # these ops read nothing from the catalog
    snap = {"option": "made", "name": "x", "structure": "", "beats": [{"id": "r1", "title": "a", "detail": "", "shots": [
        {"id": "up:0", "start": 0.5, "end": 2.5}, {"id": "flat:0", "start": 0.5, "end": 2.5}]}]}
    b = bd.applied(None, [{"op": "choose_option", "option": "made", "snapshot": snap}] + list(wide.values()), cat, None)
    items = timeline.layout(b)
    up = next(i for i in items if i.get("shot_id") == "up:0")
    check("the fill and the point ride on the laid-out shot", up.get("fill") and up.get("aim") == wide["up:0"]["aim"], json.dumps(up))
    turned = bd.applied(b, [{"op": "set_shot", "shot": "up:0", "rotate": 90}], cat, None)
    e = next(s for bt in turned["beats"] for s in bt["shots"] if s["id"] == "up:0")
    check("turned by hand: the point is dropped, the fill kept", not e.get("aim") and e.get("fill"), json.dumps(e))
    mirrored = bd.applied(b, [{"op": "set_shot", "shot": "up:0", "mirror": True}], cat, None)
    e = next(s for bt in mirrored["beats"] for s in bt["shots"] if s["id"] == "up:0")
    check("mirrored by hand: the point is dropped too", not e.get("aim"), json.dumps(e))
    from web.backend import resources
    kept = resources.capture("shot", b, "up:0")
    check("saved to My resources, a shot's settings keep its fill but not its point", kept.get("fill") and "aim" not in kept, json.dumps(kept))
    put, _ = resources.ops_for({"kind": "shot", "name": "x", "value": {**kept, "aim": [0.1, 0.1]}}, b, "flat:0")
    check("…and putting saved settings on another shot never brings a point with them", all("aim" not in o for o in put), json.dumps(put))

    print("through the export, in the edit's own wide frame")
    W, H = 1920, 1080
    aimed = render([dict(up, seq_start=0.0, seq_end=2.0)], clips)
    p = white(aimed.path, 1.0, W, H)
    check("the face of a vertical shot filmed near its top sits at HEAD_AT of the wide frame",
          p is not None and abs(p[1] - aim.HEAD_AT * H) < 30 and abs(p[0] - W / 2) < 30, str(p))
    middle = render([dict(up, seq_start=0.0, seq_end=2.0, aim=None)], clips)
    check("control: the same shot filled without the point (the middle) cuts the face out", white(middle.path, 1.0, W, H) is None,
          str(white(middle.path, 1.0, W, H)))
    bars = render([dict(up, seq_start=0.0, seq_end=2.0, fill=False, aim=None)], clips)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", bars.path, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    col = np.frombuffer(raw, np.uint8).reshape(H, W)
    check("and before this (not filled), the shot is a strip: the outer thirds are bars",
          col[:, : W // 4].max() < 20 and col[:, -W // 4:].max() < 20 and p is not None)

    print("a crop that would cut a face: the whole picture over a blur of itself instead")
    clips["selfie"] = clip("selfie", 720, 1280, (0.2, 0.3, 0.6, 0.32), bg="gray")   # a close selfie: the head is a third of the picture
    clips["medium"] = clip("medium", 720, 1280, (0.42, 0.3, 0.16, 0.09), bg="gray") # the same person further away
    W_, H_ = 1920, 1080
    k = W_ / 720
    win = (1.0, H_ / (k * 1280))
    found = aim.boxes([clips["selfie"], clips["medium"]])
    sp = {"src_start": 0.5, "src_end": 2.5}
    at_s = aim.aim(sp, clips["selfie"], found["selfie"], win)
    check("a close selfie: even aimed at the face, a wide window cuts the head",
          aim.cuts_face(sp, clips["selfie"], found["selfie"], win, at_s), f"window {win[1]:.2f} of the height, head 0.32 + hair")
    at_m = aim.aim(sp, clips["medium"], found["medium"], win)
    check("control: the same person further away fits, so it fills", not aim.cuts_face(sp, clips["medium"], found["medium"], win, at_m))
    two = sel.Plan(hook=[], sessions=[[pick("selfie"), pick("medium")]], titles=["a"])
    ops2 = {op["shot"]: op for op in make.fill_ops(two, clips, "wide")}
    check("Make puts the selfie over its blur (no fill, no crop) and fills the other",
          ops2.get("selfie:0") == {"op": "set_shot", "shot": "selfie:0", "backdrop": "blur"}
          and ops2.get("medium:0", {}).get("fill") is True, json.dumps(ops2))
    snap2 = {"option": "made", "name": "x", "structure": "", "beats": [{"id": "r1", "title": "a", "detail": "", "shots": [
        {"id": "selfie:0", "start": 0.5, "end": 2.5}]}]}
    b2 = bd.applied(None, [{"op": "choose_option", "option": "made", "snapshot": snap2}, ops2["selfie:0"]], cat, None)
    sitem = timeline.layout(b2)[0]
    check("the backdrop rides on the laid-out shot", sitem.get("backdrop") == "blur" and not sitem.get("fill"), json.dumps(sitem))
    over = render([dict(sitem, seq_start=0.0, seq_end=2.0)], clips)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", over.path, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    g = np.frombuffer(raw, np.uint8).reshape(H_, W_)
    fw = round(720 * H_ / 1280)                      # the whole picture, in front: its own columns
    front = g[:, (W_ - fw) // 2 + 8:(W_ + fw) // 2 - 8]
    ys, xs = np.nonzero(front > 200)
    head_h = (ys.max() - ys.min() + 1) / H_ if len(ys) else 0
    check("through the export the head is whole: its full height on screen, not touching the frame's edge",
          len(ys) and ys.min() > 2 and ys.max() < H_ - 3 and abs(head_h - 0.32) < 0.03, f"{head_h:.3f} of the frame, rows {ys.min() if len(ys) else None}–{ys.max() if len(ys) else None}")
    sides = np.concatenate([g[:, : W_ // 5], g[:, -W_ // 5:]], axis=1)
    check("…and the sides are the picture's own blur, not black bars", sides.mean() > 40, f"side brightness {sides.mean():.0f}")
    cutv = render([dict(sitem, seq_start=0.0, seq_end=2.0, fill=True, backdrop=None, aim=list(at_s) if at_s else None)], clips)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", cutv.path, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    g2 = np.frombuffer(raw, np.uint8).reshape(H_, W_)
    ys2 = np.nonzero(g2 > 200)[0]
    check("control: filled, the same shot loses the head's top or bottom at the frame's edge",
          len(ys2) and (ys2.min() <= 2 or ys2.max() >= H_ - 3), f"rows {ys2.min() if len(ys2) else None}–{ys2.max() if len(ys2) else None}")
    ver = export.cover_mismatched([dict(sitem)], clips, {"w": 1080, "h": 1920})
    check("a version in the other frame leaves it over its blur, never crops it", not ver[0].get("fill") and not ver[0].get("refit"), json.dumps(ver[0]))
    ts = Path(__file__).resolve().parents[1] / "web" / "frontend" / "src" / "aimView.ts"
    import re
    got = dict(re.findall(r"(scale|sigma|dim): ([0-9.]+)", ts.read_text().split("BACKDROP = {")[1].split("}")[0]))
    check("the preview blurs and darkens as the export does",
          float(got["scale"]) == export.BACKDROP_SCALE and float(got["sigma"]) == export.BACKDROP_SIGMA and float(got["dim"]) == export.BACKDROP_DIM, str(got))

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
