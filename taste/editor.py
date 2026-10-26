"""An experienced editor's breakdown of a reference vlog (paid, asked for only).

The taste model learns from what good editors did, but the numbers alone
can't say what a shot is *for*: the same two seconds of a hand on a cup is
a setup in one vlog and the payoff in another. A person who edits vlogs for
a living can say it at a glance -- this opens on a teaser, this part is
"the market", its last shot is the payoff, the music drops out here, the
captions are her thoughts. This asks a model to be that person, once per
reference, while the frames still exist:

- one still per shot (the middle of it), on numbered contact sheets drawn
  as selfcheck draws the AI's own cut, 16 to a sheet at high detail;
- the description's list (each shot's length, the join into it, how much
  moves, a face and where it looks, a voice, music, laughter, labels, how
  many words are on screen and where -- counts, never the words);
- what is said, when a transcript was made (used in this call, never
  stored, and the answer is scrubbed of anything it quotes).

The answer is labels: a role per numbered shot, chapters by shot number,
the hook, what the captions do, where the music starts, changes and drops
out, how it ends, and the techniques it uses. `apply` writes those onto the
description; the role model (taste/model.py) learns from them, so later
boards get roles without a call.

Nothing here runs by itself. taste.collect calls `breakdown` only with
`--ai`, after printing each video's estimate, inside a `Budget` it stops at.
The CLI only estimates. Every number below is a prior.
"""

from __future__ import annotations

import argparse
import copy
import math
import re
import sys
import time
from pathlib import Path

import numpy as np

from web.backend import oai, selfcheck as sc

from .describe import READINGS, ROLES

HERE = Path(__file__).parent
DESCRIPTIONS = HERE / "descriptions"

TILES = sc.TILES          # shots per sheet, as the self-check
MAX_SHEETS = 10           # 160 shots pictured; more are listed but not pictured (and said so)
SHEET_TOKENS = 1500       # one 16-tile sheet at high detail [prior, from selfcheck]
SHOT_TOKENS = 50          # one listed shot
SYSTEM_TOKENS = 1200
OUT_BASE, OUT_PER_SHOT, OUT_THINK = 300, 14, 600
TRANSCRIPT_MAX = 24000    # characters of what's said sent along (~6k tokens); a long vlog's first minutes fit
QUOTE_RUN = 5             # this many words in a row shared with the transcript = a quote, and it goes
STRIP_RGB = (64, 64, 70)  # no chapters yet (that is the question), so one strip colour
JUMP_RGB = (150, 110, 40) # ... except a shot joined by a jump cut: the same framing again, worth seeing
MIN_SHOTS = 2
JOIN_WORDS = {"cut": "cut", "jump": "jump cut", "dissolve": "dissolve", "dip_black": "dip to black",
              "flash": "flash", "swipe": "swipe", "other": "other join"}

HOOK_KINDS = ("teaser", "talk", "scene", "title", "question", "none")
CAPTION_ROLES = ("thought", "subtitle", "title", "signpost", "joke", "mixed", "none")
MUSIC_EVENTS = ("start", "change", "drop_out", "return", "end")
ENDINGS = ("sign_off", "payoff_hold", "loop", "cut", "fade", "cutoff")
# From the research catalogue (taste/techniques-research-2026-10-21.json),
# named the way an editor would tick them off.
TECHNIQUES = ("straight_cuts", "cut_on_motion", "talk_then_show", "jump_cuts", "teaser_open", "held_open",
              "wide_then_close", "hands_and_details", "transit_shot", "sound_across_cut", "ambient_soundtrack",
              "music_drop_out", "song_per_chapter", "written_narration", "thought_captions", "subtitles",
              "signpost_cards", "punch_in", "speed_ramp", "timelapse", "whip_or_match_cut", "keep_the_laughs",
              "freeze_frame", "sound_effects", "split_screen", "sign_off", "loop_ending")
# Word caps on the free text: short enough to be a label, not a retelling.
PREMISE_WORDS, NAME_WORDS, PURPOSE_WORDS, NOTES_WORDS, NOTE_WORDS = 25, 4, 12, 40, 25

SYSTEM = """You are a senior editor who has cut hundreds of vlogs, long YouTube day-in-my-life videos and vertical shorts alike. A junior editor hands you someone else's finished vlog and asks: how is this cut, and why does it work? Break it down the way you would in an edit review, shot by shot, so the junior could cut new footage the same way.

You get contact sheets: one still from the middle of every shot, in playing order, left to right then top to bottom. Under each still is its number and how long it stays on screen; an amber strip means that shot joins the one before it by a jump cut (same framing, time skipped). Captions burned into the video show in the stills. You also get the list of shots with what was measured (lengths, joins, movement, faces and whether they look into the lens, voice, music, laughter, labels, how many words are on screen and where), and sometimes a machine transcript of what is said. The measurements can be wrong; the pictures and your judgement decide.

Work out, in this order:
1. premise: what the video promises the viewer, in your own words (at most 25 words). "A slow Sunday of errands and cooking, told as small rituals."
2. hook: the shots that make up the opening, before the video settles into its first part, and what kind of opening it is: teaser (quick bits from later in the video), talk (talking to the lens straight away), scene (one held shot that sets the place or mood), title (words or a title card carry it), question (it sets up something the viewer waits for), none (it just starts).
3. chapters: the parts an editor would name on the timeline, in order, by what happens ("Market", "Getting ready", "Night walk"; at most 4 words), each with its first and last shot number and its job in the story (at most 12 words). Every shot after the hook belongs to one chapter; chapters don't overlap. A part of the day, a place, or one activity is a chapter; one shot is not.
4. shots: a role for every numbered shot, by what it does in the edit, not what it shows:
   hook - part of the opening that grabs the viewer
   setup - establishes where we are or what is about to happen (a wide of the place, arriving, the ingredients laid out)
   step - moves an action or the day forward (the middle shots of a process or a walk)
   payoff - what a run of shots was building to (the reveal, the finished dish, the view, the bite); usually held longer
   talk - someone speaking to the lens carries the thread here
   reaction - a face or a laugh answering what just happened
   transit - travelling between places (walking, a train window, a car)
   detail - a close insert (hands, an object, texture) that gives the picture life
   title - a card or a shot that is there to carry words (a part title, a time stamp)
   outro - the goodbye, the sign-off, the closing image after the last payoff
   other - none of these
5. captions: what the words on screen do across the video: thought (the creator's inner voice or diary lines), subtitle (what is said, written out), title (a title over the opening), signpost (part names, times, places), joke (punchlines, asides), mixed (more than one of these, none dominant), none (no words). A note of at most 25 words on how they are placed and paced.
6. music: by shot number, where music starts, changes to another song, drops out (for a moment that matters, or for talk), returns, and ends. Use what you hear about in the measurements (music share per shot) and what the edit implies. Leave it empty when there is no music.
7. ending: sign_off (a goodbye to the viewer), payoff_hold (it ends by holding its last payoff), loop (the last shot leads back into the first), cut (it just stops on a cut), fade (a fade out), cutoff (the description stops before the video ends; you are told when).
8. techniques: the editing techniques this video actually uses, each with the shot numbers that show it best (a few, not all):
   straight_cuts - nearly every join a plain cut; soft joins only to say time passed
   cut_on_motion - cuts land during a movement, so the eye is carried across
   talk_then_show - talk to the lens, then quick shots of what she means
   jump_cuts - inside one take the dull bits are cut out, the same framing skips forward
   teaser_open - opens on quick bits from later in the video
   held_open - the first shot is held long enough to read the hook or take in the place, then it goes
   wide_then_close - a place opens on a wide shot, then closer shots of what happens there
   hands_and_details - close shots of hands and objects carry the b-roll
   transit_shot - a short travel shot links one place to the next
   sound_across_cut - talk or sound runs on over the next picture, or arrives before it
   ambient_soundtrack - the day's own sounds carry the video, music soft or absent
   music_drop_out - the music steps back for a moment that matters
   song_per_chapter - the song changes with the part of the day
   written_narration - full diary sentences on screen, held across shots, instead of a voiceover
   thought_captions - short lines of what she thinks or feels
   subtitles - what is said is written out
   signpost_cards - part titles or times of day mark the day moving on
   punch_in - a sudden zoom in the edit on a face or an object
   speed_ramp - footage sped up into or out of normal speed
   timelapse - a long process kept and sped up instead of cut down
   whip_or_match_cut - a fast pan, a hand over the lens or matching shapes carry one place into the next
   keep_the_laughs - laughs, mistakes and asides stay in, often a beat past the line
   freeze_frame - a picture held still
   sound_effects - added sounds (whooshes, pops, dings) on cuts or words
   split_screen - two or more pictures on screen at once
   sign_off - a spoken or written goodbye
   loop_ending - the end runs back into the start
9. notes: anything else a junior editor should copy from this cut, in plain words (at most 40 words): the rhythm, what is held and what is quick, what is left out.

Rules:
- Never quote the creator. Not a line they say, not a caption they wrote, not their title, not even a few words of it; no names of people, channels or brands. Describe in your own words.
- Judge the cut, not the person or the place. No praise, no opinions about how they look.
- Use only the shot numbers you were given. A shot that is listed but not pictured gets its role from the list and its neighbours.
- If you can't tell a shot's role, say other. If the video has no clear chapters, give one chapter after the hook."""

_INT = {"type": "integer"}
_INTS = {"type": "array", "items": _INT}


def _obj(props: dict) -> dict:
    # OpenAI's strict mode: every property required, nothing else allowed
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _enum(values) -> dict:
    return {"type": "string", "enum": list(values)}


SCHEMA = _obj({
    "premise": {"type": "string"},
    "hook": _obj({"shots": _INTS, "kind": _enum(HOOK_KINDS)}),
    "chapters": {"type": "array", "items": _obj({"name": {"type": "string"}, "first": _INT, "last": _INT,
                                                 "purpose": {"type": "string"}})},
    "shots": {"type": "array", "items": _obj({"n": _INT, "role": _enum(ROLES)})},
    "captions": _obj({"role": _enum(CAPTION_ROLES), "note": {"type": "string"}}),
    "music": {"type": "array", "items": _obj({"shot": _INT, "event": _enum(MUSIC_EVENTS)})},
    "ending": _enum(ENDINGS),
    "techniques": {"type": "array", "items": _obj({"name": _enum(TECHNIQUES), "shots": _INTS})},
    "notes": {"type": "string"},
})


class EditorError(Exception):
    pass


# --------------------------------------------------------------------------
# what it costs
# --------------------------------------------------------------------------

def estimate(n_shots: int, transcript_chars: int = 0, model: str | None = None) -> float:
    """Dollars for one breakdown of a video of `n_shots`, before it's sent:
    a sheet per 16 pictured shots, a line per shot, the brief, what's said
    (~4 characters a token), and an answer with a role per shot plus its
    thinking [prior; the real cost is read from the reply's usage]."""
    p_in, _, p_out = oai.PRICES.get(model or oai.model(), oai.DEAREST)
    n = max(1, int(n_shots))
    sheets = math.ceil(min(n, TILES * MAX_SHEETS) / TILES)
    tokens_in = SYSTEM_TOKENS + n * SHOT_TOKENS + sheets * SHEET_TOKENS + min(transcript_chars, TRANSCRIPT_MAX) / 4
    tokens_out = OUT_BASE + OUT_PER_SHOT * n + OUT_THINK
    return (tokens_in * p_in + tokens_out * p_out) / 1e6


def answer_allowance(n_shots: int) -> int:
    """The most a breakdown may answer, thinking included (its max tokens)."""
    return max(8000, 3 * (OUT_BASE + OUT_PER_SHOT * max(1, int(n_shots)) + OUT_THINK))


def worst(n_shots: int, transcript_chars: int = 0, model: str | None = None) -> float:
    """What one breakdown can cost at most: estimate() with the answer at
    its full allowance. The cap is checked against this, so the last call
    of a run can't carry the total past it."""
    p_in, _, p_out = oai.PRICES.get(model or oai.model(), oai.DEAREST)
    n = max(1, int(n_shots))
    extra = answer_allowance(n) - (OUT_BASE + OUT_PER_SHOT * n + OUT_THINK)
    return estimate(n, transcript_chars, model) + extra * p_out / 1e6


class Budget:
    """A spend cap over a run of breakdowns: each call's real cost is
    counted, and the next one is only made when its estimate still fits."""

    def __init__(self, cap_usd: float) -> None:
        self.cap = float(cap_usd)
        self.spent = 0.0
        self.calls = 0

    @property
    def left(self) -> float:
        return max(0.0, self.cap - self.spent)

    def can(self, est: float) -> bool:
        return self.spent + float(est) <= self.cap + 1e-9

    def spend(self, usage) -> float:
        """Count one call (its usage dict, an OAIError's `.usage`, or None
        when it never got an answer). -> what it cost."""
        c = usage.get("cost") if isinstance(usage, dict) else usage
        c = float(c or 0.0)
        self.spent += c
        self.calls += 1
        return c


# --------------------------------------------------------------------------
# what it looks at
# --------------------------------------------------------------------------

def sheets(desc: dict, stills: list[str | None]) -> tuple[list[bytes], set[int]]:
    """Numbered contact sheets of the reference, one mid-shot still per
    tile (selfcheck's drawing). -> (JPEG bytes per sheet, numbers of the
    shots with no picture)."""
    shape = "vertical" if desc.get("vertical") else "wide"
    w, h = sc.TILE[shape]
    cols = sc.COLS[shape]
    shots = desc["shots"]
    out, dark = [], set()
    for first in range(0, min(len(shots), TILES * MAX_SHEETS), TILES):
        page = shots[first:first + TILES]
        pics, none = sc._decode(stills[first:first + TILES], w, h)
        dark |= {first + j + 1 for j in none}
        rows = math.ceil(len(page) / cols)
        ncols = min(cols, len(page)) if rows == 1 else cols
        img = np.zeros((sc.PAD + rows * (h + sc.STRIP_H + sc.PAD), sc.PAD + ncols * (w + sc.PAD), 3), np.uint8)
        img[:] = sc.BG
        for j, s in enumerate(page):
            r, c = divmod(j, cols)
            x, y = sc.PAD + c * (w + sc.PAD), sc.PAD + r * (h + sc.STRIP_H + sc.PAD)
            img[y:y + h, x:x + w] = pics[j]
            img[y + h:y + h + sc.STRIP_H, x:x + w] = JUMP_RGB if s.get("same") else STRIP_RGB
            sc._text(img, f"#{first + j + 1}", x + 6, y + h + 3, 3)
            secs = f"{s['d']:.1f}s" if s["d"] < 100 else f"{s['d']:.0f}s"     # a long talk take still fits the strip
            sc._text(img, secs, x + w - 6 - sc._text_w(secs, 3), y + h + 3, 3)
        try:
            out.append(sc._jpeg(img))
        except sc.CheckError as e:
            raise EditorError(str(e)) from e
    return out, dark


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _ranks(vals: list[float | None]) -> list[float | None]:
    """Each shot's movement as a rank within its own video: the raw level's
    scale depends on the footage, how it compares to the rest doesn't."""
    have = [(i, v) for i, v in enumerate(vals) if v is not None]
    out: list[float | None] = [None] * len(vals)
    if len(have) < 2:
        return out
    order = sorted(have, key=lambda x: x[1])
    for k, (i, _) in enumerate(order):
        out[i] = k / (len(order) - 1)
    return out


def listing(desc: dict, transcript: str | None = None, missing: set[int] = frozenset()) -> str:
    """The text that goes with the sheets: the video, then a line per shot
    of what was measured. Words on screen as counts and places only."""
    shots, joins = desc["shots"], desc.get("joins") or []
    n = len(shots)
    kind = "vertical short" if desc.get("group") == "short" else ("long vlog" if desc.get("group") == "long" else "vlog")
    kind += "" if desc.get("vertical") else ", wide 16:9"
    head = f"The video: a {kind}, {n} shots over {_mmss(float(desc.get('duration') or 0))}."
    if desc.get("cutoff"):
        head += " It was measured on its first minutes only: the video goes on after the last shot listed (its ending is cutoff)."
    lines = [head]
    if desc.get("open"):
        lines.append("It fades in from black.")
    if desc.get("close"):
        lines.append("It fades out at the end.")
    mus = desc.get("music") or {}
    if mus.get("on") is not None:
        lines.append(f"Music is heard under {100 * mus['on']:.0f}% of its seconds" + (f", about {mus['bpm']:.0f} BPM." if mus.get("bpm") else "."))
    words = desc.get("words")
    if words is None:
        lines.append("Words on screen: not read; look at the stills.")
    else:
        lines.append(f"Words on screen: {len(words)} card{'s' * (len(words) != 1)}." if words else "Words on screen: none were read.")
    pictured = min(n, TILES * MAX_SHEETS)
    lines.append(f"{math.ceil(pictured / TILES)} contact sheet(s), {TILES} shots each.")
    if pictured < n:
        lines.append(f"Shots #{pictured + 1}-#{n} are listed but not pictured.")
    lines.append("Shots (number · starts at · on screen · join into it · movement · face · sound · labels · words on screen):")
    moves = _ranks([s.get("motion") for s in shots])
    for i, s in enumerate(shots):
        a, b = s["t"], s["t"] + s["d"]
        bits = [f"#{i + 1}", _mmss(a), f"{s['d']:.1f} s"]
        if i:
            j = joins[i - 1] if i - 1 < len(joins) else {"kind": "cut"}
            bits.append(JOIN_WORDS.get(j["kind"], "other join") + " in" + (f" ({j['dur']:.1f} s)" if j.get("dur") else ""))
        if moves[i] is not None:
            bits.append("lots of movement" if moves[i] >= 0.67 else ("still" if moves[i] <= 0.33 else "some movement"))
        if s.get("face") is not None:
            if s["face"] >= 0.2:
                look = "" if s.get("facing") is None else (", looking in" if s["facing"] >= 0.5 else ", looking away")
                ppl = f", {s['people']} people" if (s.get("people") or 0) > 1 else ""
                bits.append(f"a face {s['face']:.0%} of it{look}{ppl}")
            else:
                bits.append("no face")
        heard = [name for name, k, lo in (("voice", "voice", 0.45), ("music", "music", 0.5), ("laughter", "laugh", 0.3))
                 if s.get(k) is not None and s[k] >= lo]
        if any(s.get(k) is not None for k in ("voice", "music", "laugh")):
            bits.append("hears " + (", ".join(heard) if heard else "nothing marked"))
        if s.get("labels"):
            bits.append("labels: " + ", ".join(s["labels"]))
        if words is not None:
            on = [w for w in words if w["t"] < b and w["t"] + w["d"] > a]
            if on:
                bands = sorted({w["band"] for w in on}, key=("bottom", "middle", "top").index)
                caps = " in capitals" if all((w.get("upper") or 0) >= 0.8 for w in on) else ""
                bits.append(f"words: {len(on)} card{'s' * (len(on) != 1)}, {sum(w['n'] for w in on)} words, "
                            f"{'/'.join(bands)}{caps}")
        if s.get("speed", 1.0) != 1.0:
            bits.append(f"plays at {s['speed']}x")
        if i + 1 in missing:
            bits.append("no picture (its tile is dark)")
        lines.append(" · ".join(bits))
    if transcript:
        said = transcript.strip()
        cut = len(said) > TRANSCRIPT_MAX
        lines.append("What is said, by a machine transcript (to understand the video; never quote it)"
                     + (", its first part only:" if cut else ":"))
        lines.append(said[:TRANSCRIPT_MAX])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------

def _words(s, k: int) -> str:
    return " ".join(str(s or "").split()[:k])


def _grams(text: str) -> set[tuple[str, ...]]:
    w = re.findall(r"\w+", text.lower())
    return {tuple(w[i:i + QUOTE_RUN]) for i in range(len(w) - QUOTE_RUN + 1)}


def scrub(answer: dict, transcript: str | None) -> int:
    """Blank any free text that copies a run of what's said (the brief says
    never quote; this makes sure, since a description is kept and the
    creator's words are not ours to keep). -> how many fields went."""
    said = _grams(transcript or "")
    if not said:
        return 0
    gone = 0

    def clean(text):
        nonlocal gone
        if isinstance(text, str) and _grams(text) & said:
            gone += 1
            return ""
        return text

    answer["premise"] = clean(answer.get("premise"))
    answer["notes"] = clean(answer.get("notes"))
    if isinstance(answer.get("captions"), dict):
        answer["captions"]["note"] = clean(answer["captions"].get("note"))
    for c in answer.get("chapters") or []:
        if isinstance(c, dict):
            c["name"], c["purpose"] = clean(c.get("name")), clean(c.get("purpose"))
    return gone


def breakdown(desc: dict, stills: list[str | None], transcript: str | None = None,
              post=None) -> tuple[dict, dict]:
    """One editor's look at a reference. `stills` = a mid-shot JPEG per
    shot (describe.from_video's extras), `transcript` what's said, if
    anything (in this call only). -> (answer, usage with `cost`). Raises
    EditorError before anything is sent, oai.OAIError (with what a paid
    answer cost on `.usage`) after."""
    shots = (desc or {}).get("shots") or []
    if len(shots) < MIN_SHOTS:
        raise EditorError("there are too few shots to break down")
    if len(stills) != len(shots):
        raise EditorError(f"{len(stills)} stills for {len(shots)} shots")
    pics, missing = sheets(desc, stills)
    pictured = min(len(shots), TILES * MAX_SHEETS)
    if len(missing) > pictured / 2:
        # never ask about pictures it doesn't have
        raise EditorError("most of the shots have no picture to look at")
    text = listing(desc, transcript, missing)
    content = [{"type": "text", "text": text}] + [oai.image(p, detail="high") for p in pics]
    answer, usage = oai.ask_json(SYSTEM, content, SCHEMA, "vlog_breakdown",
                                 max_tokens=answer_allowance(len(shots)), post=post)
    if not isinstance(answer, dict):
        raise oai.OAIError("the model's answer wasn't a breakdown", usage)
    scrub(answer, transcript)
    return answer, usage


def apply(desc: dict, answer: dict, usage: dict | None = None) -> dict:
    """The breakdown written onto a copy of the description: each shot's
    role (shot numbers are 1-based) and chapter, and `editor` with the rest.
    Numbers that aren't shots, unknown names and a second answer for one
    shot are left out; chapters keep playing order and never overlap."""
    out = copy.deepcopy(desc)
    shots = out["shots"]
    n = len(shots)
    a = answer if isinstance(answer, dict) else {}

    def nums(xs) -> list[int]:
        return sorted({x for x in (xs or []) if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= n})

    for s in shots:
        s["role"] = s["chapter"] = None
    given = 0
    for r in a.get("shots") or []:
        if not isinstance(r, dict) or r.get("role") not in ROLES:
            continue
        k = r.get("n")
        if not nums([k]) or shots[k - 1]["role"] is not None:
            continue
        shots[k - 1]["role"] = r["role"]
        given += 1

    chapters = []
    raw = [c for c in a.get("chapters") or [] if isinstance(c, dict) and nums([c.get("first")])]
    for c in sorted(raw, key=lambda c: c["first"]):
        last = c.get("last") if isinstance(c.get("last"), int) else c["first"]
        first, last = c["first"], min(n, max(c["first"], last))
        if chapters and first <= chapters[-1]["last"]:
            first = chapters[-1]["last"] + 1          # overlapping: the earlier chapter keeps its shots
            if first > last:
                continue
        k = len(chapters)
        for i in range(first - 1, last):
            shots[i]["chapter"] = k
        chapters.append({"name": _words(c.get("name"), NAME_WORDS) or f"Part {k + 1}", "first": first,
                         "last": last, "purpose": _words(c.get("purpose"), PURPOSE_WORDS)})

    hook = a.get("hook") if isinstance(a.get("hook"), dict) else {}
    caps = a.get("captions") if isinstance(a.get("captions"), dict) else {}
    music, seen = [], set()
    for m in a.get("music") or []:
        if isinstance(m, dict) and m.get("event") in MUSIC_EVENTS and nums([m.get("shot")]) \
                and (m["shot"], m["event"]) not in seen:
            seen.add((m["shot"], m["event"]))
            music.append({"shot": m["shot"], "event": m["event"]})
    techniques = {}
    for t in a.get("techniques") or []:
        if isinstance(t, dict) and t.get("name") in TECHNIQUES:
            techniques.setdefault(t["name"], set()).update(nums(t.get("shots")))
    ending = a.get("ending") if a.get("ending") in ENDINGS else None
    if out.get("cutoff"):
        ending = "cutoff"          # where measuring stopped isn't where the creator ended
    elif ending == "cutoff":
        ending = None
    usage = usage or {}
    out["editor"] = {
        "premise": _words(a.get("premise"), PREMISE_WORDS),
        "hook": {"shots": nums(hook.get("shots")), "kind": hook.get("kind") if hook.get("kind") in HOOK_KINDS else "none"},
        "chapters": chapters,
        "captions": {"role": caps.get("role") if caps.get("role") in CAPTION_ROLES else None,
                     "note": _words(caps.get("note"), NOTE_WORDS)},
        "music": sorted(music, key=lambda m: (m["shot"], MUSIC_EVENTS.index(m["event"]))),
        "ending": ending,
        "techniques": [{"name": k, "shots": sorted(v)} for k, v in sorted(techniques.items(), key=lambda kv: TECHNIQUES.index(kv[0]))],
        "notes": _words(a.get("notes"), NOTES_WORDS),
        "roles_given": given,
        "model": usage.get("model") or oai.model(),
        "cost": usage.get("cost"),
        "at": time.strftime("%Y-%m-%d"),
    }
    have = [x for x in out.get("have") or [] if x != "roles"]
    if given:
        have.append("roles")
    out["have"] = [x for x in READINGS if x in have]
    return out


# --------------------------------------------------------------------------
# the CLI: estimates only (a run needs the frames, so it lives in taste.collect)
# --------------------------------------------------------------------------

def pending(folder: Path = DESCRIPTIONS) -> list[tuple[str, dict]]:
    """Descriptions with no roles yet: what an --ai run would still pay for."""
    from . import describe
    out = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            d = describe.load(p)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("shots") and "roles" not in (d.get("have") or []):
            out.append((d.get("id") or p.stem, d))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m taste.editor",
                                 description="What the AI editor's breakdowns would cost. Runs happen inside "
                                             "taste.collect --ai, while a video's frames exist.")
    ap.add_argument("--estimate", action="store_true", help="price the descriptions that have no roles yet")
    ap.add_argument("--dir", default=str(DESCRIPTIONS), help="descriptions folder")
    a = ap.parse_args(argv)
    if not a.estimate:
        ap.print_help()
        print("\nThere is no run mode here: use taste.collect --describe --ai --cap <dollars>.")
        return 2
    rows = pending(Path(a.dir))
    name = oai.model()
    total = 0.0
    for vid, d in rows:
        n = len(d["shots"])
        cost = estimate(n, model=name)
        total += cost
        print(f"{vid:8s} {n:4d} shots  ${cost:.3f}")
    print(f"{len(rows)} video{'s' * (len(rows) != 1)} without roles, about ${total:.2f} on {name} "
          f"(plus about ${estimate(1, TRANSCRIPT_MAX, name) - estimate(1, 0, name):.3f} each with a full transcript)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
