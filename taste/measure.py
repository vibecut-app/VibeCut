"""Measure one vlog for the taste set: numbers only, never the video.

A video in the taste set is someone's finished edit that sarah, or its
likes per view, says is good (or ordinary). What we keep from it is the
editor's habits -- how long shots are held, how it opens and ends, where
the words sit, how loud the music is -- the same traits "Cut it like"
learns from a reference (cutgrammar/style.learn), plus integrated
loudness. Comparing the good side against the ordinary side per group is
what turns those habits into a house style (fingerprint.py).

Screen recordings carry the app's own chrome (TikTok's buttons, a status
bar): they bias the look and the words, so the record says which source
it came from and the fingerprint can weigh it.

    python -m taste.measure <file> --id S001 [--limit 600]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cutgrammar import media, style

OUT = Path(__file__).parent / "measurements"
LIMIT_S = 600.0   # long vlogs: the first ten minutes carry the habits; a full 25 min decode buys little


def measure(path: str, limit_s: float | None = LIMIT_S) -> dict:
    m = media.load(path, limit_s=limit_s)
    s = style.learn(m)
    # The transition list is per cut and long; the shares and counts are the habit.
    s["transitions"].pop("list", None)
    s["lufs"] = media.loudness_lufs(path)
    s["measured_s"] = round(m.duration, 2)
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--id", required=True)
    ap.add_argument("--limit", type=float, default=LIMIT_S)
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    rec = {"id": a.id, "source_name": Path(a.path).name, **measure(a.path, a.limit or None)}
    (OUT / f"{a.id}.json").write_text(json.dumps(rec, indent=1, default=float))
    print(json.dumps({k: rec[k] for k in ("id", "measured_s", "pace", "lufs") if k in rec}, default=float))


if __name__ == "__main__":
    main()
