"""Transition sounds: where a whoosh, a riser or a hit goes, and how loud.

Why this exists (2026-10-24, the user: the transition sounds trending edits
use, "how do we add them in"). The sounds are VibeCut's own (cutgrammar/
sfxpack.py); this decides where they sit, from the joins the export will
really draw (export.plan_transitions over the board, with the look's join
policy and the creator's own picks), so a sound never lands on a join that
fell back to a straight cut:

- a swipe or a zoom through: a whoosh, its rush on the cut;
- a slide or a blur: a lighter swish;
- a white flash: a hit;
- a short with music: a riser into the drop and a hit on it (the drop is
  where the edit's energy turns, remix.find_drop).

A vlog rests (vlog.py): only its scene-change swipes get a sound, quieter,
and no riser or hit. Never more than MAX_PER_MIN a minute, and never two
within GAP_S -- a sound on every cut is the amateur tell (design/research/
09). Every gain and spacing is a prior. The sounds ride on the bed's `sfx`
list (audiomix mixes them in preview and export alike), so with the music
off there are none, as a whoosh with nothing under it reads as a mistake.
"""

from __future__ import annotations

from cutgrammar import sfxpack

SOUND_OF = {"swipe": "whoosh", "zoom": "whoosh", "slide_up": "swish", "blur": "swish"}
GAIN = {"whoosh": 0.32, "swish": 0.26, "riser": 0.28, "hit": 0.36}     # [priors]
VLOG_GAIN = 0.6           # a vlog's sounds at this share of a short's [prior]
GAP_S = 1.5               # two sounds never closer than this [prior]
MAX_PER_MIN = 8           # [prior]


def place(board: dict, clips: dict[str, dict], mx: dict | None, vlog: bool) -> list[dict]:
    """The bed's sfx entries for this board: [{"path", "at", "gain", "sound"}]."""
    from . import export, looks, timeline

    if not board:
        return []
    sp = export.spans(timeline.layout(board))
    per, _ = export.plan_transitions(sp, clips, looks.picture(board, None))
    want: list[tuple[float, str, int]] = []      # (where the sound peaks, which, priority)
    for k, it in enumerate(sp[:-1]):
        if it["kind"] != "shot":
            continue
        cut = float(it["seq_end"])
        blend = per[k].get("blend")
        between = sp[k + 1].get("beat_id") != it.get("beat_id")
        if blend in SOUND_OF and (not vlog or between):
            want.append((cut, SOUND_OF[blend], 1))
        elif (per[k].get("fade_out") or (None, None))[1] == "white" and not vlog:
            want.append((cut, "hit", 1))
    if mx and not vlog and mx.get("drop") is not None:
        drop = float(mx["drop"]) - float(mx.get("in") or 0.0)
        if drop > sfxpack.SOUNDS["riser"].dur:
            want.append((drop, "riser", 2))
            want.append((drop, "hit", 2))
    total = float(sp[-1]["seq_end"]) if sp else 0.0
    cap = max(1, int(MAX_PER_MIN * max(total, 1.0) / 60.0))
    out: list[dict] = []
    taken: list[float] = []
    for at, name, _prio in sorted(want, key=lambda w: (-w[2], w[0])):
        same_drop = name == "hit" and any(abs(at - t) < 1e-3 for t in taken)   # the riser and its hit are one moment
        if not same_drop and any(abs(at - t) < GAP_S for t in taken):
            continue
        if not same_drop and len(taken) >= cap:
            break
        snd = sfxpack.SOUNDS[name]
        start = at - snd.peak_s
        if start < 0 or at > total:
            continue
        gain = GAIN[name] * (VLOG_GAIN if vlog else 1.0)
        out.append({"path": sfxpack.path_for(name), "at": round(start, 3), "gain": round(gain, 3), "sound": name})
        if not same_drop:
            taken.append(at)
    return sorted(out, key=lambda x: x["at"])


def say(items: list[dict]) -> str:
    if not items:
        return "No transition sounds: nothing in this edit swipes, zooms, slides or drops."
    n: dict[str, int] = {}
    for x in items:
        n[x.get("sound", "sound")] = n.get(x.get("sound", "sound"), 0) + 1
    words = {"whoosh": "whoosh", "swish": "swish", "riser": "riser into the drop", "hit": "hit"}
    parts = [f"{c} {words.get(k, k)}{'es' if c > 1 and k in ('whoosh', 'swish') else 's' if c > 1 else ''}" for k, c in n.items()]
    return "Transition sounds: " + ", ".join(parts) + "."
