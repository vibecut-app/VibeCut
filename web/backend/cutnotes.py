"""Check my cut: timestamped notes on the creator's own edit, in plain words.

The checks already run on every turn -- each cut (seams.py over
cutgrammar/joins.py) and each caption (overlays.check) -- but they show as
a "!" between shots and a count on Smoother cuts. A creator who cut the
video by hand wants what an editor friend would give them: a list, in
order, of the moments that read as amateur, what's wrong there with the
number behind it, and what usually helps. (Eddie AI's timestamped
feedback on a cut is the idea; research note 09.)

Report only. Nothing here changes the edit -- the "what usually helps"
line is words, never an op (acting on the checks is cutfix, which waits
for calibration; CLAUDE.md). No model, no cost: the same numbers the
editor already has, written for a person. A check whose reading the media
lacks (no sound in a clip, no Vision here) is listed as not checked,
never as fine. Every threshold behind a note is a prior, and the report
says so.
"""

from __future__ import annotations

RANK = {"ok": 0, "warn": 1, "bad": 2}


def clock(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{int(t % 60):02d}"


# What each cut check means to a viewer, said with its own numbers; and
# what an editor would usually try. Keys are joins.py's.
def _cut_line(f: dict) -> str:
    k, v, d = f["key"], f.get("value") or 0, f.get("data") or {}
    if k == "join_exposure":
        a, b = d.get("from"), d.get("to")
        way = "brighter" if a is not None and b is not None and b > a else "darker"
        return f"The picture gets much {way} at the cut ({a:.0f} → {b:.0f} on a 0–255 scale)." if a is not None and b is not None \
            else f"The picture's brightness jumps by {v:.0f} of 255 at the cut."
    if k == "join_colour":
        return f"The two shots' colours don't match, as if filmed with another camera or light ({v:.0%} different)."
    if k == "join_repeat":
        return f"Nearly the same picture as the shot before it, from another take ({v:.0%} alike): it reads as a jump cut."
    if k == "join_energy":
        a, b = d.get("out"), d.get("in")
        busy_first = a is not None and b is not None and a > b
        return (f"A busy moment cuts straight to a still one ({v:.0f}× less movement)." if busy_first
                else f"A still moment cuts straight to a busy one ({v:.0f}× more movement).")
    if k == "join_sound":
        a, b = d.get("from_db"), d.get("to_db")
        if a is not None and b is not None:
            return f"The sound jumps {'up' if b > a else 'down'} by {v:.0f} dB at the cut ({a:.0f} → {b:.0f} dB)."
        return f"The sound level jumps by {v:.0f} dB at the cut."
    if k == "join_time":
        return f"The next shot was filmed {v:.0f} min earlier: the day runs backwards here."
    if k == "join_size":
        return "The same person at the same size on both sides: the cut twitches instead of moving on."
    return f.get("detail") or f.get("label") or k


HELPS = {
    "join_exposure": "A soft fade or dip hides it, or a shot whose light sits between the two.",
    "join_colour": "One look over the whole video (Adjust) pulls the colours together.",
    "join_repeat": "Keep one of them, or put a different shot between.",
    "join_energy": "Cut while something moves on both sides, or let the busy shot settle first.",
    "join_sound": "Let the sound run over the cut (an L or J cut), or bring the louder side down.",
    "join_time": "Fine if it's on purpose; otherwise move the shot back to where it was filmed.",
    "join_size": "Cut from a wide to a close (or the other way), not same to same.",
    "read_time": "Hold it longer, or say it in fewer words.",
    "cut_off": "Move it earlier, or end the video later.",
    "over_face": "Move it off the face (drag it on the preview).",
    "collides": "Move one of them, or let one finish before the other starts.",
    "crowded": "Fewer words on screen at once.",
}

# A caption check, said for a person (overlays.check writes the message).
CAPTION_TITLE = {"read_time": "Too quick to read", "cut_off": "Cut off by the end", "over_face": "May sit on a face",
                 "collides": "Two captions on top of each other", "crowded": "Too many words at once"}


def _snippet(text: str, n: int = 32) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: text.rfind(" ", 0, n) if " " in text[:n] else n].rstrip() + "…"


def notes(items: list[dict], cuts: list[dict], overlays: list[dict], findings: list[dict]) -> dict:
    """{headline, notes: [{t, at, kind, verdict, title, lines, helps, after | overlay}],
    checked: {cuts, captions}, unchecked: [str], priors}.

    `items` the timeline's, `cuts` seams.check's, `overlays` overlays.resolve's
    (with start / shown_end), `findings` overlays.check's."""
    num = {it["key"]: it.get("n") for it in items}
    out: list[dict] = []
    pending: dict[str, int] = {}
    for c in cuts:
        for f in c["findings"]:
            if f["verdict"] == "pending":
                pending[f["label"]] = pending.get(f["label"], 0) + 1
        bad = [f for f in c["findings"] if f["verdict"] in ("warn", "bad")]
        if not bad:
            continue
        bad.sort(key=lambda f: -RANK[f["verdict"]])
        a, b = num.get(c["after"]), num.get(c["before"])
        out.append({"t": round(float(c["at"]), 2), "at": clock(c["at"]), "kind": "cut", "verdict": c["verdict"],
                    "title": f"Cut from shot {a} to {b}" if a and b else "A cut",
                    "lines": [_cut_line(f) for f in bad],
                    "helps": [HELPS[f["key"]] for f in bad if f["key"] in HELPS][:2],
                    "after": c["after"], "checks": [f["key"] for f in bad]})
    byid = {o["id"]: o for o in overlays}
    for f in findings:
        if f["verdict"] == "pending":
            pending["Captions over faces"] = pending.get("Captions over faces", 0) + 1
        if f["verdict"] not in ("warn", "bad"):
            continue
        o = byid.get(f["overlay"])
        if not o:
            continue
        words = _snippet(o.get("text") or o.get("sub") or "")
        out.append({"t": round(float(o["start"]), 2), "at": clock(o["start"]), "kind": "caption", "verdict": f["verdict"],
                    "title": CAPTION_TITLE.get(f["rule"], "Caption") + (f": “{words}”" if words else ""),
                    "lines": [f["message"]], "helps": [HELPS[f["rule"]]] if f["rule"] in HELPS else [],
                    "overlay": o["id"], "checks": [f["rule"]]})
    out.sort(key=lambda n: (n["t"], n["kind"] != "cut"))

    n_cuts = len(cuts)
    n_caps = len([o for o in overlays if o.get("kind") != "chapters"])
    rough = [n for n in out if n["kind"] == "cut"]
    bad = sum(1 for n in out if n["verdict"] == "bad")
    caps = len(out) - len(rough)
    if not out:
        head = (f"Nothing reads as amateur by these checks: {n_cuts} cut{'s' * (n_cuts != 1)}"
                + (f" and {n_caps} caption{'s' * (n_caps != 1)}" if n_caps else "") + " checked.") if n_cuts or n_caps \
            else "There's nothing to check yet: no cuts and no captions."
    else:
        parts = []
        if rough:
            parts.append(f"{len(rough)} of {n_cuts} cut{'s' * (n_cuts != 1)} may feel rough")
        if caps:
            parts.append(f"{caps} caption note{'s' * (caps != 1)}")
        head = " and ".join(parts) + (f"; {bad} stand{'s' * (bad == 1)} out most." if bad else ".")
    return {"headline": head, "notes": out, "checked": {"cuts": n_cuts, "captions": n_caps},
            "unchecked": [f"{label}: not checked at {k} cut{'s' * (k != 1)} (the clip doesn't carry what it needs)"
                          if label != "Captions over faces" else f"{label}: not checked for {k} caption{'s' * (k != 1)}"
                          for label, k in sorted(pending.items())],
            "priors": "Every limit behind these notes is a first guess, measured on few videos — a note says where "
                      "to look, not that it's wrong."}
