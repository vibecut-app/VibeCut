"""Where the creator posts sets the default frame (brief.frame_for, /api/post-to).

The side-by-side of 2026-10-26: her day's footage was all upright, so the
setup offered a 60 s vertical Short, while the vlogs she wanted hers to look
like were 15-minute 16:9 YouTube vlogs. Each fixture differs from its
control in one respect:

- posting on YouTube asks for a wide video; on TikTok / Reels only, a
  vertical one (a short when there's little footage, a vertical vlog when
  there's plenty); both, a wide one (the vertical is a click in the Share
  box); nothing said, nothing decided (the footage's suggestion stands);
- through the API on upright footage: before the answer the setup asks and
  offers the footage's vertical frame; after "YouTube" it stops asking and
  the default is wide; "TikTok" instead keeps it vertical; clearing the
  answer (the profile page) asks again; a platform we don't know is refused.

    python tests/test_post_to.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-postto-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def upright(path: Path, d: float, col: str, when: str) -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=360x640:rate=30:duration={d}",
                    "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=16000:a=0.02",
                    "-vf", f"drawbox=x=0:y=0:w=360:h=120:color={col}:t=fill", "-metadata", f"creation_time={when}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return str(path)


def main() -> int:
    from web.backend import brief

    print("the frame where they post asks for")
    yt = brief.frame_for(["YouTube"], 1.0, 300)
    check("YouTube: wide, even for upright footage", yt is not None and yt[0] == "wide", str(yt))
    tt_small, tt_big = brief.frame_for(["TikTok", "Instagram"], 1.0, 60), brief.frame_for(["TikTok"], 1.0, 600)
    check("TikTok / Reels only: a short when there's little footage", tt_small is not None and tt_small[0] == "short", str(tt_small))
    check("…a vertical vlog when there's plenty", tt_big is not None and tt_big[0] == "tall", str(tt_big))
    both = brief.frame_for(["TikTok", "YouTube"], 1.0, 300)
    check("both: wide, with the vertical one a click away", both is not None and both[0] == "wide" and "Share box" in both[1], str(both))
    check("control: nothing said decides nothing", brief.frame_for(None, 1.0, 300) is None and brief.frame_for([], 0.0, 30) is None)

    print("through the API, on upright footage")
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, wait
    from web.backend import app as backend
    clips = [upright(PTMP / f"up-{i}.mp4", 6, ["red", "blue", "green", "yellow"][i], f"2026-09-20T{9 + 2 * i:02d}:00:00") for i in range(4)]
    with TestClient(backend.app) as c:
        c.post("/api/projects", json={"name": "Post to"})
        wait(c, c.post("/api/import", json={"paths": clips}).json())
        s0 = c.get("/api/brief/setup").json()
        check("before the answer: the setup asks, and offers the footage's own vertical frame",
              s0["ask_post"] is True and s0["format"] in ("short", "tall") and s0["format"] == s0["suggested"], str({k: s0[k] for k in ("ask_post", "format", "suggested")}))
        r = c.post("/api/post-to", json={"platforms": ["YouTube"]}).json()
        check("answering YouTube says why and sets wide", r["format"] == "wide" and r["why"] == "as you post on YouTube", str(r))
        s1 = c.get("/api/brief/setup").json()
        check("after it: no more asking, and the default frame is wide", s1["ask_post"] is False and s1["format"] == "wide"
              and s1["post_to"] == ["YouTube"], str({k: s1[k] for k in ("ask_post", "format", "post_to")}))
        check("…while the footage's own suggestion is still shown", s1["suggested"] == s0["suggested"])
        r = c.post("/api/post-to", json={"platforms": ["TikTok"]}).json()
        check("control: TikTok only keeps it vertical", r["format"] in ("short", "tall"), str(r))
        pid = c.get("/api/projects").json()["open"]
        c.post("/api/projects/close")                    # the profile page: no video open
        r = c.post("/api/post-to", json={"platforms": []}).json()
        c.post(f"/api/projects/{pid}/open")
        s2 = c.get("/api/brief/setup").json()
        check("cleared on the profile page: the next setup asks again, from the footage's frame",
              r["post_to"] == [] and s2["ask_post"] is True and s2["format"] == s0["suggested"], str({"r": r, "ask": s2["ask_post"], "format": s2["format"]}))
        c.post("/api/projects/close")
        line = c.post("/api/captions/lines", json={"text": "back at it"})
        check("the profile page's caption voice works with no video open too", line.status_code == 200, str(line.status_code))
        sw = c.post("/api/captions", json={"on": False})
        check("control: the Captions switch, which changes a video, still needs one open", sw.status_code == 409, str(sw.status_code))
        bad = c.post("/api/post-to", json={"platforms": ["MySpace"]})
        check("a platform we don't know is refused", bad.status_code == 422, str(bad.status_code))

    print()
    print("FAILED: " + ", ".join(failures) if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
