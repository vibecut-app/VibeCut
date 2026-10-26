"""The viral library: a vibe is what a set of reels has in common.

The user's vision (2026-10-18): learn from viral vlogs how viral vlogs are
cut, and let a creator pick that as the shape of their video. One reel
gives a fingerprint (reference.py, style.learn); a *set* of reels in one
niche -- twenty day-in-my-life shorts that did well -- gives a vibe: the
median shot length and arc, the hook hold, the tempo range, how long the
words hold and where, how the ending lands (remix.fingerprint over all of
them). A vibe is a dated JSON record under $VIBECUT_CACHE/vibes/, mirrored
to Supabase as kind "vibe" (cloud.py), and offered in the Setup dialog as
"Cut it like …". Picking one hands its fingerprint to make.py instead of
the frame's prior.

Only numbers leave a reel. The reels are read once and deleted unless they
were the creator's own references. Popularity is a proxy for "well cut",
as the calibration record says; a vibe names its sources so that can be
judged.

    python -m web.backend.vibes --niche "day in my life" --links links.txt
    python -m web.backend.vibes --niche "cinematic travel" --files a.mp4 b.mp4
    python -m web.backend.vibes --list
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from . import cloud, recipes, reference, remix, recipe, deep_learn
from .indexer import CACHE

DIR = CACHE / "vibes"
MIN_REELS = 3        # fewer than this is a reference, not a vibe


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "vibe"


def learn_one(source: str, say=print, timeout_s: float = 900.0) -> dict | None:
    """A reel (link or file) -> its learnt record, through reference.py's job."""
    try:
        job = reference.start(source)
    except ValueError as e:
        say(f"  skipped {source}: {e}")
        return None
    t0 = time.time()
    while job.stage not in ("done", "error") and time.time() - t0 < timeout_s:
        time.sleep(0.5)
    if job.stage != "done":
        say(f"  skipped {source}: {job.error or 'timed out'}")
        return None
    r = reference.load(job.rid)
    if r:
        say(f"  learnt {r['title'][:50]} ({r['duration']:.0f} s)")
    return r


def learn_set(niche: str, sources: list[str], name: str | None = None, say=print) -> dict:
    """Learn every reel, merge them, save the vibe. Returns the record."""
    recs = [r for r in (learn_one(s, say) for s in sources) if r]
    styles = [r["style"] for r in recs]
    if len(styles) < MIN_REELS:
        raise ValueError(f"a vibe needs at least {MIN_REELS} reels that could be read; got {len(styles)}")
    fp = remix.fingerprint(styles)

    # Extract enhanced recipe for visual preview and adjustment
    vibe_recipe = recipe.from_styles(styles)

    # Deep learning: Extract EVERYTHING about how the vlogs are made
    say("  analyzing style in depth...")
    # Merge all styles for comprehensive analysis
    merged_style = {
        "transitions": styles[0].get("transitions", {}),
        "beat": styles[0].get("beat", {}),
        "music": styles[0].get("music", {}),
        "pace": styles[0].get("pace", {}),
        "look": styles[0].get("look", {}),
        "frame": styles[0].get("frame", {}),
        "words": styles[0].get("words", {}),
    }
    blueprint = deep_learn.from_style(merged_style)
    blueprint_data = deep_learn.blueprint_to_dict(blueprint)

    rec = {
        "id": _slug(name or niche) + "-" + time.strftime("%Y%m%d"),
        "niche": niche, "name": name or niche.title(), "n": len(styles),
        "sources": [{"rid": r["rid"], "title": r["title"], "url": r.get("url")} for r in recs],
        "fingerprint": fp, "learnt_at": time.time(), "version": 2,
        "recipe": recipe.recipe_to_dict(vibe_recipe),
        "blueprint": blueprint_data,  # Everything learned about the vlogs
        "words": [remix.describe(fp)] + ([f"words at the {fp['text']['band']}, held {fp['text']['hold_s']:.1f} s"]
                                         if fp.get("text") and fp["text"].get("band") else []),
    }
    save(rec)
    cloud.push("vibe", "lib:" + rec["id"], rec, rec["learnt_at"])
    say(f"vibe {rec['id']}: {blueprint_data['style_one_liner']}")
    say(f"  key techniques: {', '.join(blueprint_data['key_techniques'][:3])}")
    return rec


def save(rec: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))


def list_all() -> list[dict]:
    out = []
    if DIR.exists():
        for p in sorted(DIR.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except ValueError:
                continue
    return sorted(out, key=lambda r: -r.get("learnt_at", 0))


def get(vid: str | None) -> dict | None:
    if not vid:
        return None
    p = DIR / f"{vid}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def choices() -> list[dict]:
    """What the Setup dialog offers under "Cut it like": the creator's own
    recipes (recipes.py, edits they saved), the library's vibes, then their
    learnt reels, each as a one-reel vibe."""
    out = [recipes.public(r) for r in recipes.list_all()]
    out += [{"id": v["id"], "name": v["name"], "line": f"{v['n']} reels · " + v["words"][0][:60], "kind": "library"}
            for v in list_all()]
    for r in reference.library():
        out.append({"id": "ref:" + r["rid"], "name": r["title"][:40], "line": "your reel · " + ", ".join(r["summary"][:1])[:60], "kind": "reference"})
    return out


def fingerprint_for(choice: str | None) -> dict | None:
    """The fingerprint behind a Setup choice: a recipe's, a library vibe's,
    or one reel's."""
    if not choice:
        return None
    if choice.startswith(recipes.PREFIX):
        r = recipes.get(choice)
        return recipes.fingerprint(r) if r else None
    if choice.startswith("ref:"):
        r = reference.load(choice[4:])
        return remix.fingerprint([r["style"]]) if r else None
    v = get(choice)
    return dict(v["fingerprint"]) if v else None


# --------------------------------------------------------------------------
# from inside the app: a job, polled, like a Remix
# --------------------------------------------------------------------------

class Job:
    def __init__(self, niche: str, name: str | None, sources: list[str]) -> None:
        import uuid
        self.id = uuid.uuid4().hex[:10]
        self.niche, self.name, self.sources = niche, name, sources
        self.stage = "learning"      # learning | done | error
        self.lines: list[str] = []
        self.error: str | None = None
        self.result: dict | None = None
        self.started = time.time()

    def public(self) -> dict:
        return {"id": self.id, "stage": self.stage, "lines": self.lines[-4:], "error": self.error,
                "done": sum(1 for l in self.lines if l.startswith("  learnt")), "total": len(self.sources),
                "vibe": self.result["id"] if self.result else None, "elapsed": round(time.time() - self.started, 1)}


JOBS: dict[str, Job] = {}


def start(niche: str, name: str | None, sources: list[str], limit_s: float = 120.0) -> Job:
    import threading
    job = Job(niche, name, sources)
    JOBS[job.id] = job

    def run() -> None:
        try:
            reference.LIMIT_S = min(reference.LIMIT_S, limit_s)
            job.result = learn_set(niche, sources, name, say=job.lines.append)
            job.stage = "done"
        except Exception as e:  # noqa: BLE001 -- shown in the dialog
            job.stage, job.error = "error", str(e)[:300]

    threading.Thread(target=run, daemon=True).start()
    return job


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--niche", help="what these reels have in common, e.g. 'day in my life'")
    ap.add_argument("--name", help="what to call the vibe (default: the niche)")
    ap.add_argument("--links", help="a file of links, one a line")
    ap.add_argument("--files", nargs="*", default=[], help="reels on this Mac")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=float, default=120.0,
                    help="seconds of each reel to learn from (default 120: a reel's style shows in its first two minutes)")
    a = ap.parse_args(argv)
    reference.LIMIT_S = float(a.limit)
    if a.list:
        for v in list_all():
            print(f"{v['id']:40} {v['n']:3} reels  {v['words'][0]}")
        return 0
    if not a.niche:
        ap.error("--niche is needed")
    sources = list(a.files)
    if a.links:
        sources += [l.strip() for l in Path(a.links).read_text().splitlines() if l.strip() and not l.startswith("#")]
    if not sources:
        ap.error("give --links or --files")
    learn_set(a.niche, sources, a.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
