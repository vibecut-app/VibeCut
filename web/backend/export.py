"""Export: the working storyboard, with its words on screen, as one video file.

Until now nothing was ever re-encoded -- the timeline played spans of the
original files. Export is the one place pixels are rendered, and it does it
in three steps so each stays simple and bounded:

1. **Shots.** Every span on the timeline becomes its own short file at the
   output size (scaled to fit, padded, 30 fps, audio as PCM so joining can't
   drift -- AAC's priming samples add up to an audible slip over dozens of
   joins). A gap is black and silent for its length. Lengths are counted in
   frames from the timeline's own layout, so a 60-shot edit ends on the same
   frame the timeline says it does.
2. **Join.** Stream copy, no re-encode.
3. **Finish.** Words on screen and music on top, encoded once.

Words on screen are drawn by the browser, not here: the same Canvas code that
draws the preview renders them to transparent PNG frames (only the frames
that change are sent -- a title holding still is one frame with a duration).
This ffmpeg build has no text renderer, and drawing them twice in two
languages would guarantee the export and the preview disagree. The frames
arrive as a schedule -- (frame, start, end) -- and become one ffconcat input
overlaid on the joined edit.

A borrowed style (restyle.py) is rendered here too, and only here: one
LUT over every shot, cinematic bars, and transitions. Dips, flashes and
fades happen inside a shot's own frames; a dissolve needs frames beyond
each cut (handles), so the two shots are rendered longer and overlapped,
which keeps every shot starting on the frame the timeline says. Where a
shot wasn't filmed long enough for handles, the dissolve falls back to a
cut and the export says how many did.

The original footage is only read. Output goes to ~/Movies/VibeCut.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cutgrammar import media

from . import aim, audiomix, effects, indexer
from . import timeline as tlm

FPS = tlm.FPS
OUT_DIR = Path(os.environ.get("VIBECUT_EXPORTS", str(Path.home() / "Movies" / "VibeCut")))
WORK = indexer.CACHE / "exports"
MUSIC_GAIN = audiomix.MUSIC_GAIN   # music under the original sound, not over it
MAX_FRAMES = 20000  # overlay PNGs per export -- far above what titles need

_probe_cache: dict[str, dict] = {}


def _display(path: str) -> dict:
    """Display size (rotation applied, as ffmpeg's autorotate will) and audio."""
    if path not in _probe_cache:
        info = media.probe(path)
        v = next(s for s in info["streams"] if s.get("codec_type") == "video")
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        if media._rotation(v) in (90, 270):
            w, h = h, w
        _probe_cache[path] = {"w": w, "h": h,
                              "audio": any(s.get("codec_type") == "audio" for s in info["streams"])}
    return _probe_cache[path]


def frame_size(items: list[dict], clips: dict[str, dict], want: str | None = None) -> dict:
    """1080p in the frame asked for (short / tall = vertical, wide = 16:9),
    else in the orientation most of the edit was filmed in."""
    if want in ("short", "tall"):
        return {"w": 1080, "h": 1920}
    if want == "wide":
        return {"w": 1920, "h": 1080}
    portrait = landscape = 0.0
    for it in items:
        c = clips.get(it.get("clip_id") or "")
        if not c:
            continue
        w, h = c.get("width", 0), c.get("height", 0)
        try:
            d = _display(c["path"])
            w, h = d["w"], d["h"]
        except Exception:  # noqa: BLE001 -- a file gone missing shouldn't break the session
            pass
        if h > w:
            portrait += it["seq_end"] - it["seq_start"]
        else:
            landscape += it["seq_end"] - it["seq_start"]
    return {"w": 1080, "h": 1920} if portrait > landscape else {"w": 1920, "h": 1080}


def spans(items: list[dict]) -> list[dict]:
    """Timeline items -> frame-exact spans (cumulative rounding, no drift)."""
    out = []
    for it in items:
        f0, f1 = round(it["seq_start"] * FPS), round(it["seq_end"] * FPS)
        if f1 > f0:
            out.append({**it, "frames": f1 - f0})
    return out


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

@dataclass
class Job:
    id: str
    items: list[dict]
    clips: dict[str, dict]
    size: dict
    total: float
    name: str
    music: str | None = None
    overlays: int = 0
    stage: str = "waiting"          # waiting | shots | joining | finishing | done | error | cancelled
    done: int = 0
    of: int = 0
    progress: float = 0.0
    error: str | None = None
    path: str | None = None
    started: float = field(default_factory=time.time)
    elapsed: float = 0.0
    schedule: list[dict] = field(default_factory=list)
    cancel: bool = False
    style: dict | None = None
    notes: list[str] = field(default_factory=list)
    alt: bool = False               # a version in the other frame (cover_mismatched)
    aimed: bool = False             # its crops aimed (aim_refits), once
    # How the music sits under the picture (remix.py): where in the track to
    # start, how loud, where to duck under the original sound, and any sound
    # effects to drop in. None keeps the plain mix.
    mix: dict | None = None
    # How the sound crosses each cut ({entry key: {"sound"}}, board.set_join).
    joins: dict | None = None
    # Sound taken off shots onto their own strips (audiomix.strips_of).
    sound: dict | None = None

    @property
    def dir(self) -> Path:
        return WORK / self.id

    def public(self) -> dict:
        return {"id": self.id, "stage": self.stage, "done": self.done, "of": self.of,
                "progress": round(self.progress, 3), "error": self.error,
                "file": Path(self.path).name if self.path else None, "path": self.path,
                "size": self.size, "total": round(self.total, 2), "overlays": self.overlays,
                "music": bool(self.music), "elapsed": round(self.elapsed, 1),
                "style": (self.style or {}).get("name"), "notes": self.notes, "alt": self.alt}


JOBS: dict[str, Job] = {}


def _safe_name(s: str) -> str:
    s = re.sub(r"[^\w\s\-–·&]+", "", s, flags=re.UNICODE).strip()
    return re.sub(r"\s+", " ", s)[:60] or "VibeCut edit"


def create(items: list[dict], clips: dict[str, dict], name: str, music: str | None,
           style: dict | None = None, mix: dict | None = None, joins: dict | None = None,
           want: str | None = None, sound: dict | None = None, crop: bool = False) -> Job:
    """`crop`: a version in a frame the edit wasn't made for (share.py's
    "vertical version too"): every shot filmed the other way up fills the
    frame instead of sitting small between bars, the crop aimed at the
    people in it (aim.py, when the job runs)."""
    sp = spans(items)
    if not sp:
        raise ValueError("the timeline is empty — choose a story first")
    for it in sp:
        if it["kind"] == "shot":
            c = clips.get(it["clip_id"])
            if not c or not os.path.isfile(c["path"]):
                raise ValueError(f"can't find the file for shot {it['n']} on disk any more")
    look = (style or {}).get("look")
    if look and not os.path.isfile(look.get("lut", "")):
        raise ValueError("the borrowed look's file is gone — apply the style again")
    size = frame_size(sp, clips, want)
    if crop:
        sp = cover_mismatched(sp, clips, size)
    job = Job(id=uuid.uuid4().hex[:10], items=sp, clips=clips, size=size,
              total=sum(s["frames"] for s in sp) / FPS, name=_safe_name(name), music=music, style=style,
              mix=mix, joins=joins, sound=sound)
    job.alt = crop
    job.dir.mkdir(parents=True, exist_ok=True)
    (job.dir / "frames").mkdir(exist_ok=True)
    JOBS[job.id] = job
    return job


def cover_mismatched(items: list[dict], clips: dict[str, dict], size: dict) -> list[dict]:
    """Shots whose picture (after their quarter turns) lies the other way to
    the frame fill it -- cover and crop to the middle -- so a wide shot in a
    vertical version isn't a strip between bars. Shots that already match,
    and gaps, are left alone."""
    tall = size["h"] > size["w"]
    out = []
    for it in items:
        c = clips.get(it.get("clip_id") or "")
        if it.get("kind") != "shot" or not c:
            out.append(it)
            continue
        w, h = c.get("width", 0), c.get("height", 0)
        try:
            d = _display(c["path"])
            w, h = d["w"], d["h"]
        except Exception:  # noqa: BLE001 -- a probe failure keeps the index's size
            pass
        if int(it.get("rotate") or 0) % 180 == 90:
            w, h = h, w
        # `refit`: filled for this version, so its crop is aimed (aim_refits),
        # unlike a shot filled by hand, which keeps the middle the preview shows
        out.append({**it, "fill": True, "refit": True, "shown": [w, h]} if w and h and (h > w) != tall and not it.get("fill") else it)
    return out


def aim_refits(job: "Job") -> str | None:
    """Aim each refitted shot's crop at its people (aim.py); the note that
    says what was done, or None when nothing was cropped. Once per job."""
    if job.aimed:
        return None
    job.aimed = True
    todo = [it for it in job.items if it.get("refit")]
    if not todo:
        return None
    found = aim.boxes([job.clips[i] for i in {it["clip_id"] for it in todo} if i in job.clips])
    W, H = job.size["w"], job.size["h"]
    aimed = 0
    for it in todo:
        dw, dh = it["shown"]
        s = max(W / dw, H / dh)
        faces = found.get(it["clip_id"])
        at = aim.aim(it, job.clips[it["clip_id"]], faces, (W / (s * dw), H / (s * dh))) if faces else None
        if at:
            it["aim"] = list(at)
            aimed += 1
    n = len(todo)
    head = f"{n} shot{'s' * (n != 1)} filmed the other way {'are' if n != 1 else 'is'} cropped to fill the frame"
    if not found:
        return head + ", keeping the middle (finding the people in them needs a Mac)."
    if aimed == n:
        return head + ", kept on the people in them."
    if not aimed:
        return head + ", keeping the middle (nobody in them to keep in frame)."
    return head + f": {aimed} kept on the people in them, {n - aimed} with nobody in them keep the middle."


FACE_MAX = 40   # rects a shot sends at most (one per face per sample; ~1 s apart)


def face_areas(job: "Job") -> list[dict]:
    """Where faces are in this export's frame, shot by shot: [{start, end,
    boxes: [[x, y, w, h], …]}] in shares of the frame, top-left origin, from
    the same boxes the crops aim by. For a version in the other frame,
    whose captions are laid out again for its size: the browser moves any
    caption that would sit on one (overlayDraw.faceShifts). Aims the crops
    first, so the boxes land where the crop will put them."""
    note = aim_refits(job)
    if note:
        job.notes.append(note)
    shots = [it for it in job.items if it.get("kind") == "shot" and it.get("clip_id") in job.clips]
    found = aim.boxes([job.clips[i] for i in {it["clip_id"] for it in shots}])
    W, H = job.size["w"], job.size["h"]
    out, at = [], 0
    for it in job.items:
        start, at = at / FPS, at + it["frames"]
        faces = found.get(it.get("clip_id") or "")
        c = job.clips.get(it.get("clip_id") or "")
        if it.get("kind") != "shot" or not faces or not c:
            continue
        times = (c.get("samples") or {}).get("times") or []
        a, b = float(it.get("src_start", 0)), float(it.get("src_end", 0))
        inside = [i for i, t in enumerate(times) if a <= t <= b and i < len(faces)]
        if not inside and times:
            inside = [min(range(min(len(times), len(faces))), key=lambda i: abs(times[i] - (a + b) / 2))]
        if "shown" in it:
            dw, dh = it["shown"]
        else:
            try:
                d = _display(c["path"])
                dw, dh = d["w"], d["h"]
            except Exception:  # noqa: BLE001
                dw, dh = c.get("width", 0), c.get("height", 0)
            if int(it.get("rotate") or 0) % 180 == 90:
                dw, dh = dh, dw
        if not dw or not dh:
            continue
        # where the picture lands: covered and cropped (at its aim, else the
        # middle) or shown whole between bars -- as _fit does it
        fill = bool(it.get("fill"))
        sc = max(W / dw, H / dh) if fill else min(W / dw, H / dh)
        iw, ih = dw * sc, dh * sc
        if fill:
            ax, ay = it.get("aim") or (0.5, None)
            ox = -min(max(ax * iw - W / 2, 0), iw - W)
            oy = -(min(max(ay * ih - H * aim.HEAD_AT, 0), ih - H) if ay is not None else (ih - H) / 2)
        else:
            ox, oy = (W - iw) / 2, (H - ih) / 2
        boxes = []
        for i in inside:
            for f in faces[i]:
                (x0, y0), (x1, y1) = (aim.turned((f[0], 1 - f[1] - f[3]), it.get("rotate") or 0, bool(it.get("mirror"))),
                                      aim.turned((f[0] + f[2], 1 - f[1]), it.get("rotate") or 0, bool(it.get("mirror"))))
                l, r = (min(x0, x1) * iw + ox) / W, (max(x0, x1) * iw + ox) / W
                t, btm = (min(y0, y1) * ih + oy) / H, (max(y0, y1) * ih + oy) / H
                l, r, t, btm = max(0.0, l), min(1.0, r), max(0.0, t), min(1.0, btm)
                box = [round(l, 4), round(t, 4), round(r - l, 4), round(btm - t, 4)]
                if r > l and btm > t and box not in boxes:   # a still face on every sample is one box
                    boxes.append(box)
        if boxes:
            out.append({"start": round(start, 3), "end": round(at / FPS, 3), "boxes": boxes[:FACE_MAX]})
    return out


def save_frame(job: Job, n: int, data: bytes) -> None:
    if job.stage != "waiting":
        raise ValueError("this export has already started")
    if not (0 <= n < MAX_FRAMES):
        raise ValueError("frame number out of range")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("overlay frames must be PNG")
    (job.dir / "frames" / f"{n:05d}.png").write_bytes(data)


def start(job: Job, schedule: list[dict]) -> None:
    """schedule: [{frame: n | None, start, end}] covering where words are on screen."""
    if job.stage != "waiting":
        raise ValueError("this export has already started")
    clean = []
    for s in schedule:
        n = s.get("frame")
        a, z = float(s["start"]), float(s["end"])
        if z <= a:
            continue
        if n is not None and not (job.dir / "frames" / f"{int(n):05d}.png").exists():
            raise ValueError(f"overlay frame {n} was never uploaded")
        clean.append({"frame": None if n is None else int(n), "start": a, "end": z})
    clean.sort(key=lambda s: s["start"])
    job.schedule = clean
    job.overlays = len({s["frame"] for s in clean if s["frame"] is not None})
    job.stage = "shots"
    threading.Thread(target=_run, args=(job,), daemon=True).start()


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _encoder() -> list[str]:
    if sys.platform == "darwin" and _has_encoder("h264_videotoolbox"):
        return ["-c:v", "h264_videotoolbox", "-b:v", "{rate}", "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "{crf}"]


_encoders: str | None = None


def _has_encoder(name: str) -> bool:
    global _encoders
    if _encoders is None:
        try:
            _encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                       capture_output=True, text=True).stdout
        except OSError:
            _encoders = ""
    return name in _encoders


def _venc(intermediate: bool, size: dict) -> list[str]:
    big = size["w"] * size["h"] >= 1920 * 1080
    rate = ("24M" if big else "12M") if intermediate else ("12M" if big else "6M")
    crf = "14" if intermediate else "18"
    return [x.replace("{rate}", rate).replace("{crf}", crf) for x in _encoder()]


def _ff(args: list[str], job: Job, total_s: float | None = None, base: float = 0.0, weight: float = 0.0) -> None:
    """Run ffmpeg; with total_s, report progress into job.progress."""
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin"]
    if total_s:
        cmd += ["-progress", "pipe:1"]
    p = subprocess.Popen(cmd + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if total_s and p.stdout:
        for line in p.stdout:
            if job.cancel:
                p.kill()
                break
            if line.startswith("out_time_us="):
                try:
                    t = int(line.split("=")[1]) / 1e6
                    job.progress = base + weight * min(1.0, t / total_s)
                except ValueError:
                    pass
    _, err = p.communicate()
    if job.cancel:
        raise InterruptedError
    if p.returncode != 0:
        raise RuntimeError((err or "").strip().splitlines()[-1] if err and err.strip() else "ffmpeg failed")


def _fit(size: dict, style: dict | None = None, fades: str = "", fill: bool = False,
         at: list[float] | None = None) -> str:
    w, h = size["w"], size["h"]
    look = (style or {}).get("look")
    # The grade goes on the picture before padding, so bars stay black, and
    # after any fade, so a dip bottoms out at the grade's black -- a lifted
    # black stays lifted through a dip, as it does under a graded edit.
    grade = f"lut3d=file='{_esc(look['lut'])}':interp=tetrahedral," if look else ""
    # `fill` (the shot menu's crop): cover the frame and cut the edges off,
    # instead of showing the whole picture with bars; `at` (aim.py) moves
    # the window onto a point -- centred across, at HEAD_AT down -- and stops
    # at the picture's edge
    crop = f"crop={w}:{h}"
    if fill and at:
        crop += (f":'clip({at[0]:.4f}*iw-{w / 2:.1f},0,iw-{w})'"
                 f":'clip({at[1]:.4f}*ih-{h * aim.HEAD_AT:.1f},0,ih-{h})'")
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic,{crop}" if fill
           else f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=bicubic")
    chain = (f"{fit},{fades}{grade}"
             f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={FPS}")
    bar = _bar(size, style)
    if bar:
        chain += f",drawbox=x=0:y=0:w={w}:h={bar}:color=black:t=fill,drawbox=x=0:y={h - bar}:w={w}:h={bar}:color=black:t=fill"
    return chain + ",format=yuv420p"


def _esc(path: str) -> str:
    """A path inside '...' in a filtergraph, where everything is literal but '."""
    if "'" in path:
        raise ValueError("the look file's path can't contain a quote")
    return path


def _bar(size: dict, style: dict | None) -> int:
    """Height of each cinematic bar, or 0. Only a horizontal frame gets them."""
    aspect = (style or {}).get("letterbox")
    w, h = size["w"], size["h"]
    if not aspect or h >= w or aspect <= w / h + 0.02:
        return 0
    return int(round((h - w / aspect) / 2 / 2)) * 2


# --------------------------------------------------------------------------
# transitions
# --------------------------------------------------------------------------

def plan_transitions(items: list[dict], clips: dict[str, dict], style: dict | None) -> tuple[list[dict], list[str]]:
    """Per item: handles (blends) and fades (dips, flashes, open, close).

    Returns (per-item dicts, notes). A boundary is "between parts" when the
    two shots belong to different beats of the storyboard. A join the
    creator picked (`at`, transitions.py) wins over the policy. A blend --
    a dissolve, or one of the creator's zoom / slide / blur / light leak --
    needs footage past the cut on both sides; `blend` on the outgoing item
    names the xfade it renders with.
    """
    from .transitions import BLENDS, KINDS
    per = [{"head": 0, "tail": 0, "fade_in": None, "fade_out": None, "blend": None} for _ in items]
    pol = (style or {}).get("transitions")
    notes: list[str] = []
    if not pol or not items:
        return per, notes
    at = pol.get("at") or {}
    fell_back: dict[str, int] = {}
    for k in range(len(items) - 1):
        a, b = items[k], items[k + 1]
        pick = at.get(a.get("key") or "")
        kind = pick["kind"] if pick else pol["between"] if a.get("beat_id") != b.get("beat_id") else pol["within"]
        if kind == "cut" or kind not in KINDS:
            continue
        dur = float(pick["dur"]) if pick else float(pol.get("dur", 0.5))
        half = max(1, int(round(dur / 2 * FPS)))
        n = min(half, a["frames"] // 2, b["frames"] // 2)
        if n < 1:
            continue
        if kind in BLENDS:
            if a["kind"] == "shot" and b["kind"] == "shot" and _room(a, clips, "tail", n) and _room(b, clips, "head", n):
                per[k]["tail"], per[k + 1]["head"] = n, n
                per[k]["blend"] = kind
                if kind == "swipe":
                    per[k]["swipe"] = True
                continue
            if a["kind"] == "shot" and b["kind"] == "shot":
                fell_back[kind] = fell_back.get(kind, 0) + 1
                continue
            if kind == "swipe":
                continue         # next to a gap a swipe is just the cut
            kind = "dip_black"   # next to a gap (already black): fade the shot side
        color = "white" if kind == "flash" else "black"
        if a["kind"] == "shot":
            per[k]["fade_out"] = (n, color)
        if b["kind"] == "shot":
            per[k + 1]["fade_in"] = (n, color)
    if pol.get("open") and items[0]["kind"] == "shot" and not per[0]["fade_in"]:
        per[0]["fade_in"] = (min(FPS, items[0]["frames"] // 2), "black")
    if pol.get("close") and items[-1]["kind"] == "shot" and not per[-1]["fade_out"]:
        per[-1]["fade_out"] = (min(int(1.5 * FPS), items[-1]["frames"] // 2), "black")
    for kind, n in fell_back.items():
        name = KINDS[kind]["name"].lower()
        notes.append(f"{n} {name}{'s' * (n != 1 and not name.endswith('h'))}{'es' * (n != 1 and name.endswith('h'))} "
                     f"became {'a cut' if n == 1 else 'cuts'}: the shot wasn't filmed long enough past the cut to blend")
    return per, notes


def _room(it: dict, clips: dict[str, dict], side: str, n: int) -> bool:
    """Is there footage for n frames beyond this span's edge?"""
    c = clips.get(it.get("clip_id") or "")
    if not c or float(it.get("speed") or 1) != 1:
        return False   # a sped-up or slowed shot has no handle at the edit's speed: it cuts
    need = n / FPS
    if side == "head":
        return it["src_start"] - need >= 0
    return it["src_end"] + need <= float(c.get("duration") or 0) - 1 / FPS


def _shot(job: Job, it: dict, out: Path, tr: dict | None = None) -> None:
    tr = tr or {"head": 0, "tail": 0, "fade_in": None, "fade_out": None}
    n = it["frames"] + tr["head"] + tr["tail"]
    d = n / FPS
    size = job.size
    audio_out = ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]
    common = ["-frames:v", str(n), "-t", f"{d:.6f}", *_venc(True, size), *audio_out, str(out)]
    if it["kind"] == "gap":
        _ff(["-f", "lavfi", "-i", f"color=black:s={size['w']}x{size['h']}:r={FPS}",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-map", "0:v", "-map", "1:a", "-vf", "format=yuv420p", *common], job)
        return
    c = job.clips[it["clip_id"]]
    info = _display(c["path"])
    speed = float(it.get("speed") or 1.0)
    src = ["-ss", f"{it['src_start'] - tr['head'] / FPS:.4f}", "-t", f"{d * speed + 0.5:.4f}", "-i", c["path"]]
    # the shot menu's fixes: a quarter turn, then its speed (frames retimed;
    # its sound comes from the mix, stretched there)
    turn = ("hflip," if it.get("mirror") else "") + \
        {90: "transpose=1,", 180: "hflip,vflip,", 270: "transpose=2,"}.get(int(it.get("rotate") or 0), "")
    retime = f"setpts=PTS/{speed:.6f}," if speed != 1 else ""
    vfade, afade = "", ""
    if tr["fade_in"]:
        k, color = tr["fade_in"]
        vfade += f"fade=t=in:st=0:d={k / FPS:.4f}:color={color},"
        if color == "black":   # a dip takes the sound down with the picture; a flash doesn't
            afade += f",afade=t=in:st=0:d={k / FPS:.4f}"
    if tr["fade_out"]:
        k, color = tr["fade_out"]
        vfade += f"fade=t=out:st={d - k / FPS:.4f}:d={k / FPS:.4f}:color={color},"
        if color == "black":
            afade += f",afade=t=out:st={d - k / FPS:.4f}:d={k / FPS:.4f}"
    if info["audio"]:
        amap = ["-map", "0:a:0", "-af", f"aresample=48000,aformat=channel_layouts=stereo,apad{afade}"]
    else:
        src += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        amap = ["-map", "1:a"]
    # A punch-in: a slow push into the frame over the shot, the short-form
    # editor's way of making a held shot feel like a new one. The picture is
    # already at the output size, so the push is a crop that grows.
    punch = ""
    if it.get("punch"):
        z = float(it["punch"]) if it["punch"] is not True else 0.08
        # positive pushes in over the shot; negative starts pushed in and settles back
        zexpr = f"1+{z:.3f}*in/{max(n, 1)}" if z > 0 else f"{1 - z:.3f}-{-z:.3f}*in/{max(n, 1)}"
        punch = (f",zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                 f":d=1:s={size['w']}x{size['h']}:fps={FPS},format=yuv420p")
    # A span that runs to the very end of its file can decode a frame or two
    # short; hold the last frame so every shot is exactly its frame count.
    args = [*src, "-map", "0:v:0", *amap, "-vf",
            turn + retime + _fit(size, job.style, vfade, bool(it.get("fill")), it.get("aim"))
            + effects.chain(it.get("effect"), float(it.get("effect_amount") or 1.0), size, tr["head"] / FPS, it["frames"], FPS)
            + punch
            + ",tpad=stop_mode=clone:stop_duration=1", *common]
    hw = ["-hwaccel", "videotoolbox"] if sys.platform == "darwin" else []
    try:
        _ff(hw + args, job)
    except RuntimeError:
        if not hw:
            raise
        _ff(args, job)   # a codec the hardware decoder won't take


# A swipe is a whip pan between two stops of the day: the outgoing shot
# slides off, the incoming one slides in, smeared sideways over the middle
# of the move (her own edit used two of these). The preview draws the same
# move and smear (joinView.swipeAt). [prior]
SWIPE_BLUR = 0.03    # sideways smear, share of the frame width
SWIPE_SMEAR = (0.2, 0.8)   # the part of the move that is smeared


def swipe_blur(start_frame: int, frames: int) -> tuple[float, float]:
    """Seconds (inside a run) when a swipe starting at `start_frame` and
    lasting `frames` is smeared."""
    a, b = SWIPE_SMEAR
    return ((start_frame + a * frames) / FPS, (start_frame + b * frames) / FPS)


def _xfade(kind: str | None) -> str:
    """The xfade a blend renders with (transitions.KINDS)."""
    from .transitions import KINDS, LIGHT_LEAK
    x = KINDS.get(kind or "dissolve", KINDS["dissolve"])["xfade"] or "fade"
    if x == "custom":
        return f"transition=custom:expr='{LIGHT_LEAK}'"
    return f"transition={x}"


def _dissolve_runs(job: Job, segs: list[Path], plan: list[dict], seg_dir: Path) -> list[Path]:
    """Overlap each run of shots joined by dissolves into one segment.

    Each shot in a run was rendered with `tail` frames past its out point
    and `head` frames before its in point; overlapping by head + tail puts
    every cut back on its timeline frame, so the run is exactly as long
    as its shots.
    """
    out, k = [], 0
    while k < len(segs):
        j = k
        while j + 1 < len(segs) and plan[j]["tail"]:
            j += 1
        if j == k:
            out.append(segs[k])
            k += 1
            continue
        run = list(range(k, j + 1))
        lens = [job.items[i]["frames"] + plan[i]["head"] + plan[i]["tail"] for i in run]
        args, v, a, parts = [], "[v0]", "[a0]", []
        for n, i in enumerate(run):
            args += ["-i", str(segs[i])]
            parts.append(f"[{n}:v]settb=AVTB,setpts=PTS-STARTPTS[v{n}];[{n}:a]asetpts=PTS-STARTPTS[a{n}]")
        length = lens[0]
        blurs = []
        for n in range(1, len(run)):
            ov = plan[run[n - 1]]["tail"] + plan[run[n]]["head"]
            swipe = plan[run[n - 1]].get("blend") == "swipe"
            parts.append(f"{v}[v{n}]xfade={_xfade(plan[run[n - 1]].get('blend'))}:duration={ov / FPS:.6f}"
                         f":offset={(length - ov) / FPS:.6f}[x{n}]")
            parts.append(f"{a}[a{n}]acrossfade=d={ov / FPS:.6f}:c1=tri:c2=tri[y{n}]")
            v, a = f"[x{n}]", f"[y{n}]"
            if swipe:
                blurs.append(swipe_blur(length - ov, ov))
            length += lens[n] - ov
        for i, (t0, t1) in enumerate(blurs):
            # the whip's smear: sideways only, over the middle of the move
            w = max(2, int(job.size["w"] * SWIPE_BLUR))
            parts.append(f"{v}avgblur=sizeX={w}:sizeY=1:enable='between(t,{t0:.4f},{t1:.4f})'[b{i}]")
            v = f"[b{i}]"
        dest = seg_dir / f"run{k:04d}.mov"
        _ff([*args, "-filter_complex", ";".join(parts), "-map", v, "-map", a,
             "-frames:v", str(length), *_venc(True, job.size),
             "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(dest)], job)
        out.append(dest)
        k = j + 1
    return out


def _overlay_input(job: Job) -> Path | None:
    """The schedule as an ffconcat of PNGs, transparent where nothing shows."""
    if not job.schedule:
        return None
    frames = job.dir / "frames"
    blank = frames / "blank.png"
    _blank_png(blank, job.size)
    lines = ["ffconcat version 1.0"]
    t = 0.0

    def entry(p: Path, dur: float) -> None:
        if dur > 1e-4:
            lines.append(f"file '{p.name}'")
            # without it each PNG is read at the image demuxer's 25 fps and
            # its timestamps snap to a 40 ms grid (research 07: 600 of 1800 wrong)
            lines.append(f"option framerate {FPS}")
            lines.append(f"duration {dur:.6f}")

    for s in job.schedule:
        a, z = max(s["start"], t), min(s["end"], job.total)
        if z <= a:
            continue
        entry(blank, a - t)
        entry(frames / f"{s['frame']:05d}.png" if s["frame"] is not None else blank, z - a)
        t = z
    entry(blank, job.total - t)
    lines.append(f"file '{blank.name}'")   # the last entry's duration needs a successor
    lines.append(f"option framerate {FPS}")
    out = frames / "overlay.ffconcat"
    out.write_text("\n".join(lines) + "\n")
    return out


def _blank_png(path: Path, size: dict) -> None:
    """A fully transparent RGBA PNG, written without an image library."""
    import struct
    import zlib
    w, h = size["w"], size["h"]
    raw = (b"\x00" + b"\x00\x00\x00\x00" * w) * h

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def music_spec(path: str | None, mix: dict | None) -> dict | None:
    """The bed under the edit, as audiomix takes it."""
    if not path:
        return None
    m = mix or {}
    return {"path": path, "in": float(m.get("in") or 0.0), "gain": float(m.get("gain", MUSIC_GAIN)),
            "original": float(m["original"]) if m.get("original") is not None else 1.0,
            "fade_out": float(m.get("fade_out", 2.0)), "duck": m.get("duck") or [],
            "sfx": m.get("sfx") or [], "level": bool(m.get("level"))}


def _run(job: Job) -> None:
    t0 = time.time()
    try:
        seg_dir = job.dir / "shots"
        seg_dir.mkdir(exist_ok=True)
        job.of = len(job.items)
        if job.alt:
            refit = aim_refits(job)
            if refit:
                job.notes.append(refit)
        plan, said = plan_transitions(job.items, job.clips, job.style)
        job.notes += said
        segs = []
        for k, it in enumerate(job.items):
            if job.cancel:
                raise InterruptedError
            out = seg_dir / f"{k:04d}.mov"
            _shot(job, it, out, plan[k])
            segs.append(out)
            job.done = k + 1
            job.progress = 0.65 * (k + 1) / len(job.items)
            job.elapsed = time.time() - t0
        listing = [f"file '{p.name}'" for p in _dissolve_runs(job, segs, plan, seg_dir)]
        job.stage = "joining"
        (seg_dir / "list.ffconcat").write_text("ffconcat version 1.0\n" + "\n".join(listing) + "\n")
        joined = job.dir / "joined.mov"
        _ff(["-f", "concat", "-safe", "0", "-i", str(seg_dir / "list.ffconcat"), "-c", "copy", str(joined)], job)

        job.stage = "finishing"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        dest = OUT_DIR / f"{job.name} {time.strftime('%Y-%m-%d %H.%M')}.mp4"
        k = 2
        while dest.exists():
            dest = OUT_DIR / f"{job.name} {time.strftime('%Y-%m-%d %H.%M')} ({k}).mp4"
            k += 1
        tmp = job.dir / "out.mp4"
        ov = _overlay_input(job)
        args = ["-i", str(joined)]
        filters, vmap, amap = [], "0:v", "0:a"
        if ov:
            args += ["-f", "concat", "-safe", "0", "-i", str(ov)]
            filters.append("[1:v]format=rgba[ov];[0:v][ov]overlay=0:0:eof_action=pass:format=auto,format=yuv420p[v]")
            vmap = "[v]"
        # The sound is the same track the preview plays (audiomix): joins
        # carried or cut, micro-fades at every join, the music bed and its
        # ducks. The shots' own PCM above only keeps the join a valid file.
        music = music_spec(job.music, job.mix)
        buf, sound_notes = audiomix.render(job.items, job.clips,
                                           joins=audiomix.joins_for(job.items, job.joins),
                                           transitions=plan, music=music, sound=job.sound)
        job.notes += sound_notes
        wav = job.dir / "mix.wav"
        audiomix.write_wav(buf, wav, level=bool((music or {}).get("level")))
        args += ["-i", str(wav)]
        amap = f"{2 if ov else 1}:a"
        if filters:
            args += ["-filter_complex", ";".join(filters)]
        venc = _venc(False, job.size) if ov else ["-c:v", "copy"]
        args += ["-map", vmap, "-map", amap, *venc, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                 "-t", f"{job.total:.6f}", "-movflags", "+faststart", str(tmp)]
        _ff(args, job, total_s=job.total, base=0.7, weight=0.3)
        shutil.move(str(tmp), dest)
        job.path = str(dest)
        job.progress = 1.0
        job.stage = "done"
        shutil.rmtree(job.dir, ignore_errors=True)   # intermediates only; the export is in OUT_DIR
    except InterruptedError:
        job.stage = "cancelled"
        shutil.rmtree(job.dir, ignore_errors=True)
    except Exception as e:  # noqa: BLE001 -- surfaced to the creator verbatim
        job.stage = "error"
        job.error = str(e)
    finally:
        job.elapsed = time.time() - t0
