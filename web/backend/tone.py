"""A shot's own Brightness, Contrast and Saturation (the Adjust tab).

Every phone editor has these three sliders on a clip: footage filmed in
one light and cut next to footage filmed in another reads as two videos,
and lifting one shot to sit with its neighbours is the most common fix
an amateur makes by hand. Each is -1..1 on the shot (0 = as filmed).

The numbers are those of the browser's own filters, so the player can
draw them with CSS and export can match it exactly: brightness multiplies
each channel, contrast pulls it away from (or towards) middle grey, and
saturation is CSS `saturate()`'s matrix, which keeps the light of each
colour while taking its colour away (-1 = black and white). Each step is
clipped to the 0..255 range before the next, as the browser does. The
sliders' ends are priors: as far as a phone editor's sliders go without
burning white out of a sky in one step.
"""

from __future__ import annotations

FIELDS = ("brightness", "contrast", "saturation")
BRIGHT = 0.4      # the slider's ends: x1.4 / x0.6 light
CONTRAST = 0.5    # x1.5 / x0.5 the distance from middle grey
SATURATE = 1.0    # 2x colour / none


def clamp(v) -> float:
    return round(max(-1.0, min(1.0, float(v))), 3)


def factors(e: dict) -> tuple[float, float, float]:
    """CSS brightness(), contrast() and saturate() for an entry or item."""
    return (1 + BRIGHT * float(e.get("brightness") or 0),
            1 + CONTRAST * float(e.get("contrast") or 0),
            1 + SATURATE * float(e.get("saturation") or 0))


def matrix(s: float) -> list[list[float]]:
    """CSS saturate(s): rows R', G', B' over R, G, B (Rec. 709 weights)."""
    return [[0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
            [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
            [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s]]


def apply(rgb, e: dict):
    """The same on an array of 0..255 RGB values (..., 3): what export's
    filters and the browser's CSS both do. For tests and the sheets."""
    import numpy as np
    k, c, s = factors(e)
    x = np.clip(np.asarray(rgb, dtype=float) * k, 0, 255)
    x = np.clip((x - 127.5) * c + 127.5, 0, 255)
    return np.clip(x @ np.array(matrix(s)).T, 0, 255)


def chain(e: dict) -> str:
    """ffmpeg filters for the entry's adjustment, ending in a comma, or ""."""
    k, c, s = factors(e)
    out = []
    if abs(k - 1) > 1e-6 or abs(c - 1) > 1e-6:
        expr = f"clip((clip(val*{k:.4f},0,255)-127.5)*{c:.4f}+127.5,0,255)"
        out.append(f"lutrgb=r='{expr}':g='{expr}':b='{expr}'")
    if abs(s - 1) > 1e-6:
        m = matrix(s)
        out.append("colorchannelmixer=" + ":".join(
            f"{a}{b}={m[i][j]:.4f}" for i, a in enumerate("rgb") for j, b in enumerate("rgb")))
    return "".join(f + "," for f in out)


def describe(f: str, y: float) -> str:
    name = {"brightness": "brightness", "contrast": "contrast", "saturation": "colour"}[f]
    if not y:
        return f"Shot's {name} back to as filmed"
    return f"Shot's {name} {'+' if y > 0 else '−'}{round(abs(y) * 100)}"
