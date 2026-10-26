"""Decode a video into the small arrays every later stage works on.

Design rule: touch the pixels exactly once. Everything downstream
(shot detection, motion, grammar) runs on the tiny arrays produced here,
never on the original file. This is the "index once" principle from the
tech plan, at the scale of a single clip.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field

import numpy as np

# Frames are decoded at this size. Big enough for colour histograms and
# frame-difference motion, small enough that a 10-minute video fits in RAM.
FRAME_W, FRAME_H = 48, 27
AUDIO_SR = 16_000


@dataclass
class Media:
    path: str
    fps: float
    duration: float
    width: int
    height: int
    creation_time: str | None
    location: str | None
    # (n_frames, FRAME_H, FRAME_W, 3) uint8
    frames: np.ndarray
    # mono float32 at AUDIO_SR, empty if the file has no audio track
    audio: np.ndarray
    meta: dict = field(default_factory=dict)
    # Set only by load_index(): per-sample timestamps (samples are not
    # evenly spaced there) and the same samples at thumbnail size.
    times: np.ndarray | None = None
    # (n_frames, PREVIEW_H, PREVIEW_W, 3) uint8, display orientation
    preview: np.ndarray | None = None

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    def t(self, frame_idx: int) -> float:
        """Frame index -> seconds."""
        if self.times is not None:
            if frame_idx >= len(self.times):
                return self.duration
            return float(self.times[frame_idx])
        return frame_idx / self.fps

    @property
    def capture_time(self) -> str | None:
        """When it was filmed, in the camera's local time if the file says so.

        Apple writes a zone-aware `creationdate`; the generic `creation_time`
        is UTC, which puts a Tokyo breakfast at 23:00 the night before.
        """
        tags = self.meta.get("tags", {})
        return tags.get("com.apple.quicktime.creationdate") or self.creation_time

    @property
    def gps(self) -> tuple[float, float] | None:
        return parse_iso6709(self.location)

    @property
    def has_audio(self) -> bool:
        return self.audio.size > 0


def _run(cmd: list[str]) -> bytes:
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr.decode()[:500]}")
    return p.stdout


def probe(path: str) -> dict:
    """ffprobe metadata. Free information -- extract it before any ML."""
    raw = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ])
    return json.loads(raw)


def _fraction(val: str) -> float | None:
    try:
        num, den = val.split("/")
        if float(den) > 0 and float(num) > 0:
            return float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        pass
    return None


def _rate(stream: dict) -> str | None:
    """The rate a file is decoded and timed at, as ffmpeg wrote it
    ("30000/1001"): the nominal rate when it is a sane camera rate at or
    above the average, else the average; None when neither reads.

    The nominal grid, not the average: a phone clip at 30 fps with a short
    low-light stall averages 29.2, and resampling the whole file to 29.2
    would drop a frame every second or so -- each one a double step that
    reads as a jump cut and a motion spike. On the nominal grid a stall
    just repeats a frame where it happened.
    """
    nominal = stream.get("r_frame_rate", "0/0")
    average = stream.get("avg_frame_rate", "0/0")
    r, avg = _fraction(nominal), _fraction(average)
    if r is not None and r <= 120 and (avg is None or r >= avg - 1e-6):
        return nominal
    if avg is not None:
        return average
    return nominal if r is not None else None


def _parse_fps(stream: dict) -> float:
    val = _rate(stream)
    if val is None:
        return 30.0
    num, den = val.split("/")
    return float(num) / float(den)


def load(path: str, verbose: bool = False, limit_s: float | None = None) -> Media:
    """Every frame at 48x27 plus mono audio. `limit_s` reads only the start
    (a long reference video is learnt from its first minutes)."""
    info = probe(path)
    head = ["-t", f"{limit_s:.3f}"] if limit_s else []

    vstreams = [s for s in info["streams"] if s.get("codec_type") == "video"]
    if not vstreams:
        raise ValueError(f"no video stream in {path}")
    v = vstreams[0]
    astreams = [s for s in info["streams"] if s.get("codec_type") == "audio"]

    fps = _parse_fps(v)
    duration = float(info["format"].get("duration", 0.0))
    if limit_s:
        duration = min(duration, limit_s) if duration else limit_s
    tags = {**info["format"].get("tags", {}), **v.get("tags", {})}

    if verbose:
        print(f"  decoding {path} ({duration:.1f}s @ {fps:.2f}fps)")

    # --- video: native fps, tiny resolution -------------------------------
    # Phones and screen recorders write variable frame rate. Left to itself,
    # ffmpeg pads such a file out to its *top* rate with repeated frames,
    # while every later stage turns frame index into seconds with `fps`, the
    # average -- a 30 fps-average clip with 60 fps bursts came out twice as
    # long, its cuts landing after the video had ended. Resampling to an even
    # grid at exactly the rate reported here (`_rate`: the nominal one when
    # sane, so a stall repeats frames instead of dropping some all through
    # the file) keeps index / fps = seconds. A
    # constant-rate file already sits on that grid, so it decodes as before.
    # The grid starts at the file's zero, not at the first picture: a picture
    # that starts a frame after the sound (concat's audio priming) is held
    # over that frame, as before, so cuts and sound stay lined up.
    raw = _run([
        "ffmpeg", "-v", "error", "-i", path, *head,
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-vf", f"fps={_rate(v) or f'{fps:.6f}'}:start_time=0,scale={FRAME_W}:{FRAME_H}",
        "-fps_mode", "passthrough",
        "-",
    ])
    stride = FRAME_W * FRAME_H * 3
    n = len(raw) // stride
    frames = np.frombuffer(raw[: n * stride], dtype=np.uint8)
    frames = frames.reshape(n, FRAME_H, FRAME_W, 3)

    # --- audio: mono 16k float ---------------------------------------------
    audio = np.zeros(0, dtype=np.float32)
    if astreams:
        araw = _run([
            "ffmpeg", "-v", "error", "-i", path, *head,
            "-f", "f32le", "-ac", "1", "-ar", str(AUDIO_SR), "-",
        ])
        audio = np.frombuffer(araw, dtype=np.float32).copy()

    return Media(
        path=path,
        fps=fps,
        duration=duration or (n / fps),
        width=int(v.get("width", 0)),
        height=int(v.get("height", 0)),
        creation_time=tags.get("creation_time"),
        location=tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709"),
        frames=frames,
        audio=audio,
        meta={"tags": tags, "codec": v.get("codec_name")},
    )


def load_audio(path: str) -> Media:
    """A sound file as a Media with no pictures: mono 16 kHz, like load()'s audio.

    Lets music reuse the same audio features (frame_audio, spectral_flux)
    the grammar rules are measured with, instead of a second implementation.
    """
    info = probe(path)
    if not any(s.get("codec_type") == "audio" for s in info["streams"]):
        raise ValueError(f"no audio stream in {path}")
    raw = _run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-vn",
                "-f", "f32le", "-ac", "1", "-ar", str(AUDIO_SR), "-"])
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    tags = info["format"].get("tags", {})
    return Media(
        path=path, fps=0.0,
        duration=float(info["format"].get("duration") or len(audio) / AUDIO_SR),
        width=0, height=0, creation_time=None, location=None,
        frames=np.zeros((0, FRAME_H, FRAME_W, 3), dtype=np.uint8),
        audio=audio,
        meta={"tags": {k.lower(): v for k, v in tags.items()}},
    )


def parse_iso6709(s: str | None) -> tuple[float, float] | None:
    """'+35.6595+139.7005+040.805/' -> (35.6595, 139.7005)."""
    if not s:
        return None
    m = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", s)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if lat == 0 and lon == 0:
        return None
    return lat, lon


# --------------------------------------------------------------------------
# index mode
# --------------------------------------------------------------------------
#
# load() decodes every frame, which is what the grammar rules need: a cut
# on motion is a question about individual frames. Indexing a whole shoot
# asks a coarser question -- where are the shots, what is in them, which
# frame is the best -- and a 4K60 iPhone clip decoded frame by frame costs
# ~18s per 100s of footage even on the hardware decoder. So index mode
# decodes keyframes only. iPhones put one every second, which is enough to
# find shots and pick a thumbnail, at ~1% of the cost.
#
# It is still one decode per file: the samples come out at thumbnail size
# and the 48x27 grid is derived from them in memory, so nothing downstream
# goes back to the file.

PREVIEW_BOX = (384, 216)       # max (w, h) of the thumbnail-size samples
MIN_KEYFRAME_RATE = 0.4        # below this, sample decoded frames instead
FALLBACK_SAMPLE_FPS = 2.0


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            return int(round(float(sd["rotation"]))) % 360
    try:
        return -int(stream.get("tags", {}).get("rotate", 0)) % 360
    except ValueError:
        return 0


def _fit(w: int, h: int, box: tuple[int, int]) -> tuple[int, int]:
    scale = min(box[0] / w, box[1] / h, 1.0)
    return max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)


def area_resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Box-filter resize of (n, H, W, 3) uint8, for any ratio."""
    def weights(src: int, dst: int) -> np.ndarray:
        edges = np.linspace(0, src, dst + 1)
        wm = np.zeros((dst, src), dtype=np.float32)
        for i in range(dst):
            a, b = edges[i], edges[i + 1]
            lo, hi = int(np.floor(a)), int(np.ceil(b))
            for j in range(lo, min(hi, src)):
                wm[i, j] = min(b, j + 1) - max(a, j)
            wm[i] /= wm[i].sum()
        return wm
    wy = weights(img.shape[1], h)
    wx = weights(img.shape[2], w)
    out = np.einsum("yh,nhwc,xw->nyxc", wy, img.astype(np.float32), wx, optimize=True)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _decode_samples(path: str, stream: dict, pw: int, ph: int,
                    keyframes: bool, hw: bool) -> tuple[np.ndarray, np.ndarray]:
    """Decode sampled frames at (pw, ph). Returns (frames, pts seconds)."""
    ten_bit = "10" in (stream.get("pix_fmt") or "") or "12" in (stream.get("pix_fmt") or "")
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info"]
    if keyframes:
        cmd += ["-skip_frame", "nokey"]
    if hw:
        cmd += ["-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld"]
    cmd += ["-noautorotate", "-i", path, "-map", "0:v:0", "-an", "-sn", "-dn"]
    chain = []
    if not keyframes:
        chain.append(f"fps={FALLBACK_SAMPLE_FPS}")
    if hw:
        chain += [f"scale_vt=w={pw}:h={ph}",
                  "hwdownload", f"format={'p010le' if ten_bit else 'nv12'}"]
    else:
        chain.append(f"scale={pw}:{ph}:flags=area")
    chain.append("showinfo")
    cmd += ["-vf", ",".join(chain), "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr.decode(errors='ignore')[-500:]}")
    stride = pw * ph * 3
    n = len(p.stdout) // stride
    frames = np.frombuffer(p.stdout[: n * stride], dtype=np.uint8).reshape(n, ph, pw, 3)
    pts = [float(x) for x in re.findall(rb"pts_time:\s*([-\d.]+)", p.stderr)]
    times = np.array(pts[:n] + [np.nan] * (n - len(pts)), dtype=np.float64)
    return frames, times


def load_index(path: str, audio: bool = True, verbose: bool = False) -> Media:
    """Keyframe-sampled Media for indexing a shoot. See the note above."""
    info = probe(path)
    vstreams = [s for s in info["streams"] if s.get("codec_type") == "video"]
    if not vstreams:
        raise ValueError(f"no video stream in {path}")
    v = vstreams[0]
    astreams = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    duration = float(info["format"].get("duration", 0.0) or v.get("duration", 0.0) or 0.0)
    tags = {**info["format"].get("tags", {}), **v.get("tags", {})}
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    pw, ph = _fit(w, h, PREVIEW_BOX)
    rot = _rotation(v)

    def decode(keyframes: bool) -> tuple[np.ndarray, np.ndarray]:
        if sys.platform == "darwin":
            try:
                return _decode_samples(path, v, pw, ph, keyframes, hw=True)
            except RuntimeError:
                pass  # codec the hardware won't take -- fall through
        return _decode_samples(path, v, pw, ph, keyframes, hw=False)

    sampling = "keyframes"
    frames, times = decode(keyframes=True)
    if duration > 0 and len(frames) < max(2, duration * MIN_KEYFRAME_RATE):
        # Screen recordings and some exports put a keyframe every 10s+.
        sampling = f"{FALLBACK_SAMPLE_FPS:g}fps"
        frames, times = decode(keyframes=False)
    if len(frames) == 0:
        raise ValueError(f"no decodable frames in {path}")
    if np.isnan(times).any():
        times = np.linspace(0, duration, len(frames), endpoint=False)
    times = times - times[0]

    # Display orientation: the matrix says how far the stored picture is
    # turned counter-clockwise from upright.
    k = {90: 1, 180: 2, 270: 3}.get(rot, 0)
    if k:
        frames = np.ascontiguousarray(np.rot90(frames, k=k, axes=(1, 2)))
        w, h = (h, w) if k % 2 else (w, h)

    if verbose:
        print(f"  indexed {path}: {len(frames)} samples over {duration:.1f}s")

    snd = np.zeros(0, dtype=np.float32)
    if audio and astreams:
        araw = _run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0",
                     "-f", "f32le", "-ac", "1", "-ar", str(AUDIO_SR), "-"])
        snd = np.frombuffer(araw, dtype=np.float32).copy()

    n = len(frames)
    return Media(
        path=path,
        fps=n / duration if duration > 0 else 1.0,
        duration=duration or float(times[-1]),
        width=w,
        height=h,
        creation_time=tags.get("creation_time"),
        location=tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709"),
        frames=area_resize(frames, FRAME_W, FRAME_H),
        audio=snd,
        meta={"tags": tags, "codec": v.get("codec_name"), "rotation": rot,
              "sampling": sampling, "transfer": v.get("color_transfer"),
              "primaries": v.get("color_primaries")},
        times=times,
        preview=frames,
    )


# iPhones film HDR (HLG, often with Dolby Vision on top) by default. Decoded
# straight to 8-bit RGB with no tone mapping, that signal looks flat and
# milky -- lifted blacks, no highlights, washed-out colour -- which is not
# what the creator saw on their phone. Only pictures a person looks at
# (thumbnails, samples) are mapped; the measurement frames stay as decoded,
# so no threshold moves.
HDR_TRANSFERS = {"arib-std-b67": "hlg", "smpte2084": "pq"}
_HLG_A, _HLG_B, _HLG_C = 0.17883277, 0.28466892, 0.55991073
_REF_WHITE_NITS = 203.0      # BT.2408 HDR reference white -> SDR white
_BT2020_TO_709 = np.array([[1.6605, -0.5876, -0.0728],
                           [-0.1246, 1.1329, -0.0083],
                           [-0.0182, -0.1006, 1.1187]], dtype=np.float32)


def is_hdr(meta: dict) -> bool:
    return meta.get("transfer") in HDR_TRANSFERS


def to_sdr(images: np.ndarray, meta: dict) -> np.ndarray:
    """HDR-coded (..., 3) uint8 RGB -> what an SDR screen should show.
    Anything not flagged HLG or PQ comes back unchanged."""
    kind = HDR_TRANSFERS.get(meta.get("transfer") or "")
    if kind is None:
        return images
    if images.ndim == 4 and len(images) > 16:   # a clip's worth of float32 is too much at once
        return np.concatenate([to_sdr(images[i:i + 16], meta) for i in range(0, len(images), 16)])
    e = images.astype(np.float32) / 255.0
    if kind == "hlg":
        # Inverse OETF to scene light, then the BT.2100 OOTF for a 1000-nit display.
        scene = np.where(e <= 0.5, e * e / 3.0,
                         (np.exp((e - _HLG_C) / _HLG_A) + _HLG_B) / 12.0)
        ys = scene @ np.array([0.2627, 0.6780, 0.0593], dtype=np.float32)
        nits = 1000.0 * scene * np.power(np.maximum(ys, 1e-6), 0.2)[..., None]
    else:
        m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
        p = np.power(e, 1 / m2)
        nits = 10000.0 * np.power(np.maximum(p - c1, 0) / (c2 - c3 * p), 1 / m1)
    lin = nits / _REF_WHITE_NITS
    if (meta.get("primaries") or "bt2020") == "bt2020":
        lin = np.maximum(lin @ _BT2020_TO_709.T, 0.0)
    # Keep everything up to reference white as is; roll the highlights off
    # smoothly into the top of the range instead of clipping them flat.
    # (Extended Reinhard above the knee: the brightest the source can be
    # lands exactly on white.)
    peak = lin.max(axis=-1, keepdims=True)
    knee, top = 0.8, (10000.0 if kind == "pq" else 1000.0) / _REF_WHITE_NITS
    x, w = (peak - knee) / (1 - knee), (top - knee) / (1 - knee)
    rolled = knee + (1 - knee) * x * (1 + x / (w * w)) / (1 + x)
    lin = lin * np.where(peak > knee, rolled / np.maximum(peak, 1e-6), 1.0)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(np.clip(lin, 0, 1), 1 / 2.4) - 0.055)
    return np.clip(srgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def loudness_lufs(path: str) -> float | None:
    """Integrated loudness via ffmpeg's EBU R128 meter.

    YouTube normalises to about -14 LUFS; anything far from that gets
    turned up or down on playback, which is where 'the audio feels off'
    usually comes from.
    """
    p = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path, "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
    )
    err = p.stderr.decode(errors="ignore")
    marker = "Integrated loudness:"
    if marker not in err:
        return None
    tail = err.split(marker)[-1]
    for line in tail.splitlines():
        if "LUFS" in line:
            try:
                return float(line.split()[-2])
            except (ValueError, IndexError):
                return None
    return None
