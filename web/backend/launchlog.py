"""The launch log: completions, failures, costs and feedback, from the
project records alone.

The one workflow that counts (launch checklist, 2026-10-11): drop a day's
clips, make the two picks, watch, export. **Completion** = an export made
without a typed chat edit (the default path). **Success** = the creator
answered the one question after it, "Would you post this?", with yes. The
rest is what the record already keeps: what failed (unreadable files, a
bed that found nothing, exports judged not postable, with the words), what
it cost (model calls = chat turns, render seconds, seconds hunting music),
and how much was undone (the strongest signal a step was wrong). **Shares**
= what the creator did with a finished file (downloaded, Photos, Finder, the
share sheet, a platform's upload page; share.py), counted per way and as
projects with any share -- the nearest thing to "posted" we can see --
and **posted** = videos VibeCut put on YouTube itself, each confirmed.

    python -m web.backend.launchlog            # a short page
    python -m web.backend.launchlog --json     # the numbers
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import projects as pj


def summary(records: list[dict] | None = None) -> dict:
    recs = records if records is not None else [json.loads(p.read_text()) for p in sorted(pj.DIR.glob("*.json"))]
    out = {"projects": len(recs), "with_clips": 0, "completions": 0, "successes": 0, "judged": 0,
           "exports": 0, "undone_turns": 0, "turns": 0,
           "failures": {"unreadable_files": 0, "bed_nothing": 0, "bed_error": 0, "not_postable": 0},
           "costs": {"model_calls": 0, "render_seconds": 0.0, "music_hunt_seconds": 0.0},
           "scenes": {"keep": 0, "cut": 0, "longer": 0}, "shared": 0, "shares": {}, "posted": 0, "feedback": [], "per_project": []}
    for r in recs:
        exps = r.get("exports") or []
        events = r.get("events") or []
        turns = r.get("turns") or []
        live = [t for t in turns if not t.get("undone")]
        if r.get("clips"):
            out["with_clips"] += 1
        default = [e for e in exps if e.get("default_path", True)]
        done = bool(default)
        yes = sum(1 for e in exps if (e.get("verdict") or {}).get("post") is True)
        judged = sum(1 for e in exps if e.get("verdict"))
        out["completions"] += done
        out["successes"] += 1 if yes else 0
        out["judged"] += 1 if judged else 0
        out["exports"] += len(exps)
        out["turns"] += len(live)
        out["undone_turns"] += sum(1 for t in turns if t.get("undone"))
        out["failures"]["unreadable_files"] += len(r.get("import_errors") or [])
        out["failures"]["bed_nothing"] += sum(1 for e in events if e.get("kind") == "bed" and e.get("stage") == "nothing")
        out["failures"]["bed_error"] += sum(1 for e in events if e.get("kind") == "bed" and e.get("stage") == "error")
        out["failures"]["not_postable"] += sum(1 for e in exps if (e.get("verdict") or {}).get("post") is False)
        out["costs"]["model_calls"] += sum(1 for t in live if t.get("kind") == "chat" and t.get("ops")) \
            + sum(e.get("chat_turns", 0) for e in exps[:0])
        out["costs"]["render_seconds"] += sum(float(e.get("elapsed") or 0) for e in exps)
        out["costs"]["music_hunt_seconds"] += sum(float(e.get("elapsed") or 0) for e in events if e.get("kind") == "bed")
        for e in exps:
            v = e.get("verdict")
            if v and v.get("note"):
                out["feedback"].append({"project": r.get("name"), "post": v["post"], "note": v["note"]})
        shares = [e for e in events if e.get("kind") == "share"]
        out["shared"] += 1 if shares else 0
        out["posted"] += sum(1 for e in shares if e.get("how") == "youtube_post")
        for e in shares:
            out["shares"][e.get("how") or "?"] = out["shares"].get(e.get("how") or "?", 0) + 1
        for e in events:
            if e.get("kind") == "scene_verdict" and e.get("word") in out["scenes"]:
                out["scenes"][e["word"]] += 1
            if e.get("kind") == "bed" and e.get("why"):
                out["feedback"].append({"project": r.get("name"), "post": None, "note": "bed: " + e["why"]})
        out["per_project"].append({"name": r.get("name"), "clips": len(r.get("clips") or {}), "exports": len(exps),
                                   "completion": done, "success": bool(yes), "shares": len(shares), "undone": sum(1 for t in turns if t.get("undone")),
                                   "style": ((r.get("brief") or {}).get("style") or {})})
    return out


def page(s: dict) -> str:
    f, c = s["failures"], s["costs"]
    lines = [f"Projects {s['projects']} · with clips {s['with_clips']} · completions (exported from the default path) {s['completions']}"
             f" · judged {s['judged']} · successes (would post) {s['successes']}",
             f"Turns {s['turns']} · undone {s['undone_turns']} · exports {s['exports']}",
             f"Failures: unreadable files {f['unreadable_files']}, music found nothing {f['bed_nothing']}, music errors {f['bed_error']}, "
             f"exports judged not postable {f['not_postable']}",
             f"Shared {s['shared']} · posted from VibeCut {s['posted']} · " + (", ".join(f"{k} {v}" for k, v in sorted(s["shares"].items())) or "no shares yet"),
             f"Costs: model calls {c['model_calls']}, render {c['render_seconds']:.0f} s, music hunts {c['music_hunt_seconds']:.0f} s"]
    if s["feedback"]:
        lines += ["Feedback:"] + [f"  - [{p['project']}] {'yes' if p['post'] else 'no' if p['post'] is False else '—'}: {p['note']}" for p in s["feedback"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    s = summary()
    print(json.dumps(s, indent=1, ensure_ascii=False) if "--json" in (argv or sys.argv[1:]) else page(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
