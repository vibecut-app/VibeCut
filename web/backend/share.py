"""Where a finished video goes next: the creator's own apps, not ours.

VibeCut never posts. A platform button copies the caption + credit and
opens that platform's own upload page; the creator picks the file and
presses post there. Before that, the export is checked against what the
platform takes -- its frame and its length -- and a mismatch is said in
plain words ("too long for a Short") instead of hiding the button, so the
creator can still post it knowing what will happen.

Every limit here is the platform's published number as of 2026-10; they
change, so they're kept in one table. A share is a `Project.events` entry
(kind "share"), counted by launchlog.py next to "would you post this?".
"""

from __future__ import annotations

# How a creator can move the file on, as recorded. photos / finder /
# youtube_post (posted from VibeCut, youtube.py) are recorded by their own
# endpoints; the rest are clicks in the browser.
HOWS = ("download", "photos", "finder", "sheet", "caption", "tiktok", "youtube", "instagram", "youtube_post")
SERVER_HOWS = ("photos", "finder", "youtube_post")

# name, upload page, longest it takes (s), the frame it is made for
PLATFORMS = {
    "tiktok": {"name": "TikTok", "url": "https://www.tiktok.com/upload", "max_s": 60 * 60, "frame": "tall",
               "where": "TikTok's upload page"},
    # YouTube decides Shorts itself: vertical (or square) and ≤ 3 min.
    "youtube": {"name": "YouTube", "url": "https://www.youtube.com/upload", "max_s": 12 * 3600, "frame": None,
                "short_s": 3 * 60, "where": "YouTube Studio's upload"},
    # Instagram's web has no upload address of its own: the + Create button.
    "instagram": {"name": "Instagram", "url": "https://www.instagram.com/", "max_s": 3 * 60, "frame": "tall",
                  "where": "Instagram (press + Create)"},
}
# An unverified YouTube account can't upload past 15 min.
YT_UNVERIFIED_S = 15 * 60


def shape(w: int, h: int) -> str:
    if not w or not h:
        return "unknown"
    r = w / h
    return "tall" if r < 0.9 else "wide" if r > 1.1 else "square"


def _mins(s: float) -> str:
    m = s / 60
    return f"{m:.0f} min" if m >= 1 else f"{s:.0f} s"


def fit(platform: str, w: int, h: int, seconds: float) -> dict:
    """One platform's button for this export: its label, where it goes, and
    whether the file fits -- `ok` False means it won't post as meant, with
    `why` saying what will happen; `note` is advice that isn't a problem."""
    p = PLATFORMS[platform]
    sh = shape(w, h)
    out = {"id": platform, "name": p["name"], "url": p["url"], "where": p["where"], "ok": True, "why": None, "note": None}
    if platform == "youtube":
        if sh in ("tall", "square") and seconds <= p["short_s"]:
            out["name"] = "YouTube Shorts"
        elif sh in ("tall", "square"):
            out.update(ok=False, why=f"Too long for a Short ({_mins(seconds)}; Shorts are {_mins(p['short_s'])} at most) — "
                                     "it will post as a normal video, tall in a wide player.")
        elif seconds > YT_UNVERIFIED_S:
            out["note"] = f"Over {_mins(YT_UNVERIFIED_S)}: YouTube asks you to verify your account first."
        return out
    if seconds > p["max_s"]:
        what = "a Reel" if platform == "instagram" else p["name"]
        out.update(ok=False, why=f"Too long for {what} ({_mins(seconds)}; {_mins(p['max_s'])} at most). Make it shorter with Length first.")
    elif sh == "wide":
        out.update(ok=False, why=f"Wide — {p['name']} shows it small with bars above and below. "
                                 "A vertical frame fills the phone.")
    elif sh == "square":
        out["note"] = "Square — it will show with bars above and below."
    return out


def targets(w: int, h: int, seconds: float) -> list[dict]:
    return [fit(k, w, h, seconds) for k in PLATFORMS]
