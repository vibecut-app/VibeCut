"""Every cut of the working storyboard, checked (cutgrammar/joins.py), and
what the latest turn made better or worse.

Report only: nothing here edits the storyboard. It turns timeline items and
the index into joins.Side records and hands them over. Sound levels come
from the same cached 48 kHz decode the mix uses (audiomix.decode) -- no
pixel is decoded, and each file's per-second loudness is computed once.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from cutgrammar import joins

from . import audiomix
from . import storyboard as sb

_RMS: dict[str, list[float]] = {}


def _rms_db(path: str) -> list[float]:
    """Per-second loudness of a file's sound, dBFS; [] when it has none."""
    if path not in _RMS:
        snd = audiomix.decode(path)
        if snd is None:
            _RMS[path] = []
        else:
            mono = np.asarray(snd).mean(axis=1)
            n = len(mono) // audiomix.SR
            sec = mono[:n * audiomix.SR].reshape(n, audiomix.SR) if n else mono[None, :]
            rms = np.sqrt((sec.astype(np.float64) ** 2).mean(axis=1))
            _RMS[path] = [round(float(20 * np.log10(r + 1e-9)), 1) for r in rms]
    return _RMS[path]


def side(it: dict, clips: dict) -> joins.Side | None:
    if it["kind"] != "shot":
        return None
    c = clips.get(it["clip_id"])
    if not c:
        return None
    sig = c.get("signals") or {}
    sid = str(it.get("shot_id") or it["key"])           # "clip:index", or "clip:index~ms" after a cut
    idx = int(sid.split(":")[1].split("~")[0].split(".")[0]) if ":" in sid else 0
    shot = next((s for s in c.get("shots", []) if s["index"] == idx), {})
    base = sb.parse_when(c.get("capture_time"))
    try:
        rms = _rms_db(c["path"])
    except OSError:
        rms = []
    return joins.Side(
        clip_id=c["id"], t_in=float(it["src_start"]), t_out=float(it["src_end"]),
        luma=sig.get("luma") or [], motion=sig.get("motion") or [],
        hist=shot.get("hist"), embedding=shot.get("embedding") or None,
        face_area=float(shot.get("face_area") or 0.0),
        when=base + timedelta(seconds=float(it["src_start"])) if base else None,
        rms_db=rms)


def check(items: list[dict], clips: dict) -> list[dict]:
    """One entry per cut: {after, before, at, verdict, findings}. Gaps are skipped."""
    sides = [side(it, clips) for it in items]
    out = []
    for k, r in enumerate(joins.report(sides)):
        if r is None:
            continue
        out.append({"after": items[k]["key"], "before": items[k + 1]["key"], "at": items[k + 1]["seq_start"],
                    "verdict": r["verdict"],
                    "findings": [{"key": f.key, "label": f.label, "value": f.value, "unit": f.unit,
                                  "verdict": f.verdict, "detail": f.detail, "data": f.extra} for f in r["findings"]]})
    return out


RANK = {"ok": 0, "warn": 1, "bad": 2}


def review(before: list[dict], after: list[dict]) -> list[dict]:
    """What a turn did to the cuts: new or worse ones, and ones it fixed.

    A cut is the pair of shots on either side; a cut that already existed
    and got no worse isn't mentioned. The creator reads this under the turn,
    as a second look at what they (or the model) just did.
    """
    was = {(c["after"], c["before"]): c for c in before}
    worse, better = [], 0
    for c in after:
        old = was.pop((c["after"], c["before"]), None)
        if old and RANK[c["verdict"]] < RANK[old["verdict"]]:
            better += 1
        if RANK[c["verdict"]] > RANK[old["verdict"] if old else "ok"]:
            bad = [f for f in c["findings"] if f["verdict"] in ("warn", "bad")]
            worst = max(bad, key=lambda f: RANK[f["verdict"]]) if bad else None
            worse.append({"after": c["after"], "at": c["at"], "verdict": c["verdict"],
                          "text": worst["detail"] if worst else "this cut got rougher"})
    better += sum(1 for c in was.values() if c["verdict"] != "ok")   # rough cuts that no longer exist
    out = [{"kind": "worse", **w} for w in worse]
    if better:
        out.append({"kind": "better", "text": f"{better} rough cut{'s' * (better != 1)} gone"})
    return out
