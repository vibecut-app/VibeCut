"""A few style questions before the first edit, and what the answers do.

After the clips are in and the creator has said in one line what the video
is about, they get a short multiple-choice round -- how long, how it
should feel, how it opens, what it's mostly about -- the way an editor
would ask before touching anything. The fixed questions work without a
language model; with a key, Claude may add one or two questions tailored
to the description, whose answers only become part of the direction text.

Only questions whose answer changes the edit are asked. Length, pace and
opening reshape each proposal here (`shape`); focus becomes theme words
the storyboard already leans on. The targets below are guesses, like
every threshold in cutgrammar.
"""

from __future__ import annotations

import copy
import re
from collections import Counter

from . import worth

# Rough target lengths. "long" keeps every usable shot. Only for answers
# saved before the slider; the slider sends `seconds` (length_marks).
LENGTH_S = {"short": 60.0, "medium": 180.0, "long": None}
# At or under this a video is a short (Reels, TikTok, Shorts): each moment
# once, as `short` always did. [prior]
SHORT_S = 75.0
# The slider never goes below this: a few shots, still a video.
MIN_LENGTH_S = 15.0
# Longest a single shot may run at each pace, around its best frame.
PACE_CAP_S = {"calm": 8.0, "balanced": 5.0, "fast": 2.5}
MIN_SHOT_S = 1.5
# A short (Reel, TikTok) holds no moment longer than this, whatever the
# pace: her own 45 s day vlog cut every 2.5-3.5 s, where VibeCut's held
# shots 5-14 s and showed half as much of the day. Talking to the audience
# still keeps its sentence. [prior, from one edit of hers]
SHORT_CAP_S = 3.5
# Shots filmed this far apart (or this far away, SAME_PLACE_M) are
# different stops of the day: a short covers every stop once before any
# stop gets a second shot. [prior]
SPOT_GAP_S = 20 * 60
# A short or fast edit shows each moment once: several shots of the same
# clip, or look-alikes (same cosine cut-off as remix's select.py), are one
# moment, and only its strongest shot stays. Longer, calmer edits keep them.
SIMILAR = 0.78
# Look-alikes only count as one moment when filmed close together, as
# retakes are (same window as cutgrammar.reject's duplicate rule): the same
# café in the morning and again at night is two moments, not a stutter.
RETAKE_WINDOW_S = 15 * 60
# Filmed from the same spot (GPS within ~150 m) a lower cut-off already
# means the same view: on her footage two lecture-hall shots from one seat,
# 13 minutes apart, scored 0.766 and read as one shot twice. 0.72 sits at
# the shoot's 95th percentile of shot-pair similarity. [prior]
SAME_PLACE_SIMILAR = 0.72
SAME_PLACE_M = 150.0
OPENINGS = ("hook", "start")
# Captions: what they say (describe / transcribe / none) and how they look
# (looks/*.json). Only words the footage knows: the clock, the place from
# the clip's GPS and what the image labels see (describe, daylog.py), or
# what was said, from the Mac's own recogniser (transcribe, subtitles.py).
# No opening title (sarah, 2026-10-06): a short opens on the footage.
CAPTIONS = ("describe", "transcribe", "none")
CAPTION_LOOKS = {"clean": "clean", "bold": "hype", "cozy": "cozy", "quiet": "quiet"}
DEFAULT_LOOK = {"describe": "cozy", "transcribe": "clean"}
# Answers saved before the question changed: (what they say, how they look).
LEGACY = {"day": ("describe", "cozy"), "simple": ("describe", "clean"), "bold": ("describe", "bold"),
          "key": ("describe", "quiet")}
DAY_IN_LIFE = re.compile(r"\bday in (my|the|a) life\b|\bdaily vlog\b|\bdiml\b", re.I)
# The two picks made up front (plan of 2026-10-10, step 2): the frame the
# video is for, and the look of the whole thing. Short is a Reel / TikTok:
# vertical and under SHORT_MAX_S; Tall a vertical vlog of any length; Wide
# the 16:9 YouTube frame. LOOK_IDS mirrors looks/*.json (test_format pins it).
FORMATS = {"short": "Short · vertical, under a minute and a half", "tall": "Vlog · vertical", "wide": "Wide · 16:9"}
SHORT_MAX_S = 90.0                   # [prior] the long end of a short
LOOK_IDS = ("clean", "cozy", "quiet", "cinematic", "film", "playful", "hype")
STYLE_KEYS = {"length": tuple(LENGTH_S), "pace": tuple(PACE_CAP_S), "opening": OPENINGS,
              "captions": CAPTIONS + tuple(LEGACY), "caption_look": tuple(CAPTION_LOOKS),
              "format": tuple(FORMATS), "look": LOOK_IDS}


def suggest_format(portrait_share: float, usable_s: float) -> str:
    """The frame the footage asks for: what was filmed upright stays upright,
    and a small shoot is a short. Only a default; the creator picks."""
    if portrait_share < 0.5:
        return "wide"
    return "short" if usable_s <= 2 * SHORT_MAX_S else "tall"


def length_for(fmt: str | None, marks: dict, reach: float | None = None) -> float:
    """The length a format asks for: a short is its Short mark, capped; a
    vlog (tall or wide) is the Medium mark when the footage has one, else the
    suggestion -- so the three frames in the setup don't all read "about 1:00".
    `reach` (vlog.reach): how long a vlog Make can really run on this
    footage; a vlog never promises more (2026-10-25: "about 50 seconds"
    promised, 29 made)."""
    by = {m["key"]: m["seconds"] for m in marks["marks"]}
    if fmt == "short":
        return float(min(by.get("short", marks["seconds"]), SHORT_MAX_S))
    want = float(by["medium"]) if fmt in ("tall", "wide") and "medium" in by else float(marks["seconds"])
    if fmt in ("tall", "wide") and reach:
        want = max(MIN_LENGTH_S, min(want, round(reach)))
    return want

# Focus choices, each a storyboard theme (storyboard.THEMES).
FOCUS = [("people", "Me and the people I was with"), ("food", "Food and drinks"),
         ("city", "Streets and places"), ("nature", "Nature and outdoors"),
         ("night", "Evenings and nights"), ("sea", "Beach and water")]
MIN_FOCUS_SHOTS = 3


# What kind of video the description says it is, and how long such a video
# usually runs when made from a lot of material. Social-first kinds want a
# short; a trip or an event earns more time as the footage grows. [priors:
# typical lengths of creator vlogs, not measured on her videos]
KINDS = [
    ("day", re.compile(r"\bday in (my|the|a) life\b|\bdaily\b|\bdiml\b|\bmorning\b.*\bnight\b|\bmy day\b", re.I),
     "a day vlog", 60.0, 180.0),
    ("event", re.compile(r"\bwedding|birthday|party|concert|festival|graduation|game day|show\b", re.I),
     "an event", 90.0, 300.0),
    ("trip", re.compile(r"\btrip\b|travel|holiday|vacation|weekend|\btour\b|road ?trip|\babroad\b|\bdays away\b", re.I),
     "a trip", 60.0, 300.0),
]
OTHER_KIND = ("other", None, "a video like this", 60.0, 180.0)


def kind_of(about: str) -> tuple:
    for k in KINDS:
        if k[1].search(about or ""):
            return k
    return OTHER_KIND


def _clock(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def say_length(s: float) -> str:
    """'45 seconds', '1 minute', '3 minutes', '1:45'."""
    s = int(round(s))
    if s < 60:
        return f"{s} seconds"
    if s % 60 == 0:
        return f"{s // 60} minute{'s' * (s != 60)}"
    return _clock(s)


def length_marks(usable_s: float, about: str = "") -> dict:
    """The length slider: from MIN_LENGTH_S to everything usable, with Short /
    Medium / Long marks read from how much good footage there is and what
    kind of video it is, and one of them suggested, with why.

    Short is the kind's social length; Long keeps every good moment; Medium
    sits between, at the kind's usual full-vlog length when there's that much
    to choose from. The suggestion is Short unless there's plenty more than a
    medium video's worth -- cutting hard is what makes a vlog watchable."""
    top = max(5.0, round(usable_s))
    kind, _, says, short_s, medium_s = kind_of(about)
    short = min(short_s, top)
    # a medium video grows with the material, up to twice the kind's usual
    medium = min(max(medium_s, top * 0.3), 2 * medium_s)
    medium = min(medium, max(short + 30.0, top * 0.5))
    marks = [{"key": "short", "label": "Short", "seconds": round(short)}]
    if medium < top - 15 and medium > short + 15:
        marks.append({"key": "medium", "label": "Medium", "seconds": round(medium)})
    if top > (marks[-1]["seconds"] + 15):
        marks.append({"key": "long", "label": "Long", "seconds": round(top)})
    # Plenty = two and a half medium videos' worth: then a medium one is
    # still a real cut, not everything strung together. Less than that and a
    # short is the edit that will get watched.
    suggest = "medium" if any(m["key"] == "medium" for m in marks) and top >= 2.5 * medium else "short"
    pick = next(m for m in marks if m["key"] == suggest)
    why = (f"You have {_clock(top)} of good footage; for {says} we suggest about {say_length(pick['seconds'])}."
           if top > pick["seconds"] else f"You have {_clock(top)} of good footage, so it all fits.")
    return {"min": round(min(MIN_LENGTH_S, top)), "max": round(top), "marks": marks,
            "suggest": suggest, "seconds": pick["seconds"], "why": why, "kind": kind}


def target_s(style: dict | None) -> float | None:
    """The length the edit should come out at, if one was asked for."""
    style = style or {}
    if style.get("seconds"):
        return float(style["seconds"])
    return LENGTH_S.get(style.get("length", ""))


def fixed_questions(theme_counts: Counter | None = None, usable_s: float | None = None,
                    about: str = "") -> list[dict]:
    """The questions every creator gets. Focus lists only themes the
    footage actually has, so no answer points at nothing. With the usable
    length known, the length question is a slider over it (length_marks)."""
    qs = [
        {"id": "length", "question": "How long should it be?", "multi": False, "choices": [
            {"key": "short", "label": "Short", "hint": "Under a minute, for Reels, TikTok or Shorts"},
            {"key": "medium", "label": "Medium", "hint": "About three minutes"},
            {"key": "long", "label": "Long", "hint": "Keep every good moment, a full vlog"}]},
        # No pace question (sarah, 2026-10-07); `shape` still reads an older
        # project's answer.
        {"id": "opening", "question": "How should it start?", "multi": False, "choices": [
            {"key": "hook", "label": "With the best moment", "hint": "A hook first, then the story"},
            {"key": "start", "label": "From the beginning", "hint": "In the order it happened"}]},
        {"id": "captions", "question": "Captions?", "multi": False, "choices": [
            {"key": "describe", "label": "Describe what's happening",
             "hint": "The time, the place and what's in the shot: “7:42 am · coffee run”"},
            {"key": "transcribe", "label": "Write out what's said", "hint": "Subtitles of the talking, made on this Mac"},
            {"key": "none", "label": "No captions", "hint": "Just the footage"}]},
        {"id": "caption_look", "question": "How should the captions look?", "multi": False,
         "when": {"captions": ["describe", "transcribe"]}, "choices": [
            {"key": "clean", "label": "Clean and simple", "hint": "Small, white, out of the way"},
            {"key": "bold", "label": "Bold, Reels style", "hint": "Big capitals that hit on the beat"},
            {"key": "cozy", "label": "Soft and cozy", "hint": "Warm and rounded, like a diary"},
            {"key": "quiet", "label": "Quiet", "hint": "Thin and calm"}]},
    ]
    if usable_s:
        sl = length_marks(usable_s, about)
        qs[0] = {"id": "length", "question": "How long should it be?", "multi": False, "slider": sl,
                 "choices": [{"key": m["key"], "label": m["label"], "hint": f"About {_clock(m['seconds'])}",
                              "seconds": m["seconds"]} for m in sl["marks"]]}
    counts = theme_counts or Counter()
    focus = [{"key": k, "label": label} for k, label in FOCUS if counts.get(k, 0) >= MIN_FOCUS_SHOTS]
    if len(focus) >= 2:
        qs.append({"id": "focus", "question": "What should it mostly be about?", "multi": True,
                   "hint": "Pick any, or none for a bit of everything", "choices": focus})
    return qs


def theme_counts(shots) -> Counter:
    """How many shots each focus theme would lean on."""
    from . import storyboard as sb
    c: Counter = Counter()
    for k, _ in FOCUS:
        d = sb.Direction(k, [k], [k], [], set(sb.THEMES[k]))
        c[k] = sum(sb.matches(s, d) for s in shots)
    return c


def clean_style(style: dict | None) -> dict | None:
    """Only the keys and values `shape` knows; anything else is dropped."""
    if not style:
        return None
    out = {k: style[k] for k, allowed in STYLE_KEYS.items() if style.get(k) in allowed}
    if isinstance(style.get("vibe"), str) and style["vibe"]:
        out["vibe"] = style["vibe"][:80]      # "Cut it like": a library vibe id or ref:<rid> (vibes.py)
    try:
        sec = float(style.get("seconds") or 0)
    except (TypeError, ValueError):
        sec = 0.0
    if sec > 0:
        out["seconds"] = round(min(max(sec, 5.0), 4 * 3600.0), 1)
    return out or None


def describe(style: dict | None) -> str:
    """A few plain words for the proposal summaries."""
    if not style:
        return ""
    bits = {"short": "short (about a minute)", "medium": "about three minutes", "long": "long"}
    words = []
    if style.get("seconds"):
        words.append(f"about {_clock(style['seconds'])}")
    elif style.get("length"):
        words.append(bits[style["length"]])
    if style.get("pace"):
        words.append({"calm": "calm", "balanced": "steady", "fast": "fast-cut"}[style["pace"]])
    s = ", ".join(words)
    if style.get("opening") == "hook":
        s = f"{s}, opening on the best moment" if s else "opening on the best moment"
    return s


def caption_ops(board: dict, cat, answer: str | None, title: str | None = None,
                about: str = "", look: str | None = None, clips: dict | None = None,
                places: dict | None = None) -> tuple[list[dict], list[str]]:
    """The captions the brief asked for, as ops for a freshly chosen
    storyboard: the look, then the captions themselves. (ops, notes on what
    was left out.) No opening title (sarah, 2026-10-06: a short opens straight
    into the footage); `title` only stands in for `about`."""
    from . import daylog, subtitles
    about = about or title or ""
    if answer in LEGACY:
        answer, look = LEGACY[answer][0], look or LEGACY[answer][1]
    if answer is None and DAY_IN_LIFE.search(about):
        answer = "describe"     # the genre's own captions, unless they said otherwise
    # `look` is a caption-question answer (clean / bold / cozy / quiet) or,
    # since the up-front pick, a look id straight from looks/*.json
    look_id = look if look in LOOK_IDS else CAPTION_LOOKS.get(look or "")
    if answer not in ("describe", "transcribe"):
        # no captions, but the look picked up front still dresses the video
        return ([{"op": "set_look", "look": look_id}] if look_id else []), []
    ops, notes = [], []
    if answer == "describe":
        more, why = daylog.caption_ops(board, cat, about, places=places)
    else:
        more, why = subtitles.caption_ops(board, cat, clips or {}, about)
    ops, notes = ops + more, notes + why
    if not more:
        return [], notes
    return [{"op": "set_look", "look": look_id or DEFAULT_LOOK[answer]}, *ops], notes


def _window(s, cap: float, best: dict[str, float]) -> None:
    """Shorten a shot to `cap` seconds around its best frame."""
    if s.end - s.start <= cap:
        return
    c = best.get(s.id, (s.start + s.end) / 2)
    a = min(max(s.start, c - cap / 2), s.end - cap)
    s.start, s.end = round(a, 3), round(a + cap, 3)


def one_per_moment(shots: list, rank) -> list:
    """Keep the strongest shot of each moment, in story order."""
    keep: list = []
    for s in sorted(shots, key=rank, reverse=True):
        if not any(s.clip_id == k.clip_id or float(s.vec @ k.vec) >= SIMILAR for k in keep):
            keep.append(s)
    return [s for s in shots if s in keep]


def one_per_look(options: list) -> None:
    """Every proposal, whatever the answers: look-alike shots in one part --
    the same view filmed twice, a retake -- keep only their strongest. A
    viewer reads two near-identical shots in a row as a stutter, not a
    story, and it's the most common reason an auto-edit feels like a pile of
    clips. Different shots of one clip are left alone here (a walk filmed in
    one take is several moments); short and fast edits still collapse those
    too (`one_per_moment`). Only for proposals built with on-device Vision:
    the colour-histogram fallback calls far too much "alike"."""
    rank = lambda s: s.score + (0.15 if s.lean else 0.0)  # noqa: E731
    for o in options:
        dropped = 0
        for b in o.beats:
            keep: list = []
            for s in sorted(b.shots, key=rank, reverse=True):
                if not any(alike(s, k) for k in keep):
                    keep.append(s)
            dropped += len(b.shots) - len(keep)
            b.shots = [s for s in b.shots if s in keep]
        o.beats = [b for b in o.beats if b.shots]
        if dropped:
            o.notes.append(f"Kept the best of each look-alike: {dropped} near-repeat shot"
                           f"{'s' * (dropped != 1)} left on the shelf.")


def alike(a, b) -> bool:
    """Two shots a viewer reads as the same shot twice: one view filmed
    again (Vision feature print), close in time."""
    return (a.clip_id != b.clip_id and a.vec.shape == b.vec.shape and _close(a, b)
            and float(a.vec @ b.vec) >= (SAME_PLACE_SIMILAR if _same_place(a, b) else SIMILAR))


def repeat_ops(board: dict | None, cat) -> tuple[list[dict], list[str]]:
    """An edit that already exists: the shots that repeat another shot in it
    -- a look-alike, or the same stretch of one clip twice -- as drop_shot
    ops, keeping the better-made of each group wherever it sits. Returns
    (ops, names of what goes). Vision-only, like `one_per_look`."""
    entries = [e for bt in (board or {}).get("beats", []) for e in bt["shots"]
               if not e.get("gap") and e.get("id") in cat.shots]
    rank = lambda e: cat.shots[e["id"]].score + (0.15 if cat.shots[e["id"]].lean else 0.0)  # noqa: E731
    keep: list[dict] = []
    ops, names = [], []
    for e in sorted(entries, key=rank, reverse=True):
        s = cat.shots[e["id"]]
        same = any(e["id"] == k["id"] and e["start"] < k["end"] and k["start"] < e["end"] for k in keep)
        if same or any(alike(s, cat.shots[k["id"]]) for k in keep):
            ops.append({"op": "drop_shot", "shot": e.get("key") or e["id"]})
            names.append(s.clip_name)
        else:
            keep.append(e)
    return ops, names


def _same_place(a, b) -> bool:
    if not a.gps or not b.gps:
        return False
    import math
    dy = (a.gps[0] - b.gps[0]) * 111_000
    dx = (a.gps[1] - b.gps[1]) * 111_000 * math.cos(math.radians(a.gps[0]))
    return math.hypot(dx, dy) <= SAME_PLACE_M


def _close(a, b) -> bool:
    if a.when is None or b.when is None:
        return True
    return abs((a.when - b.when).total_seconds()) <= RETAKE_WINDOW_S


def spots(shots: list) -> dict[str, int]:
    """Shot id -> which stop of the day it was filmed at: in filming order, a
    new stop when the place moves on (GPS beyond SAME_PLACE_M) or time does
    (SPOT_GAP_S); a clip with neither is a stop of its own."""
    seq = sorted(shots, key=lambda s: (s.when is None, s.when or 0, s.order if hasattr(s, "order") else 0))
    out: dict[str, int] = {}
    n, prev = -1, None
    for s in seq:
        new = prev is None
        if prev is not None:
            far = bool(s.gps and prev.gps) and not _same_place(s, prev)
            late = s.when is not None and prev.when is not None and \
                abs((s.when - prev.when).total_seconds()) > SPOT_GAP_S
            blind = not (s.gps and prev.gps) and (s.when is None or prev.when is None) and s.clip_id != prev.clip_id
            new = far or late or blind
        if new:
            n += 1
        out[s.id] = n
        prev = s
    return out


def weakest(cands: list, ident, spot: dict[str, int], count, imp: dict[int, float] | None = None) -> tuple:
    """Which of `cands` ((rank, part, shot) tuples) to let go first: from the
    stop with the most shots for what it is worth (`imp`, worth.importance:
    its best moment), then the weakest there. Screen time follows what
    happened at a stop, not how much was filmed there. A stop's last shot
    goes only when every stop is down to one (sarah, 2026-10-14: "a lot of
    material was left out ... different locations")."""
    imp = imp or {}

    def key(c):
        k = spot.get(ident(c[2]), -1)
        n = count(k)
        return (n == 1, -n / max(imp.get(k, 1.0), 0.05), c[0])
    return min(cands, key=key)


def cap_for(style: dict | None) -> float | None:
    """The longest a shot may run: the pace's cap, and SHORT_CAP_S on a short."""
    style = style or {}
    cap = PACE_CAP_S.get(style.get("pace", ""))
    target = target_s(style)
    if style.get("format") == "short" or (target is not None and target <= SHORT_S):
        cap = min(cap or SHORT_CAP_S, SHORT_CAP_S)
    return cap


def shape(options: list, style: dict | None, best: dict[str, float], keep: set | frozenset = frozenset()) -> None:
    """Reshape storyboard.Option objects in place to the creator's answers.

    Order within the story is never changed except by the hook, which lifts
    the single strongest shot to the front. Short or fast edits keep one shot
    per moment (`one_per_moment`). Length is met by leaving out the
    weakest shots first, but every part keeps at least its best one.
    """
    from .storyboard import Beat

    style = clean_style(style)
    if not style:
        return
    rank = lambda s: worth.of(s) + (0.15 if s.lean else 0.0)  # noqa: E731
    for o in options:
        # Shots are shared between the proposals (and the voiceover one).
        for b in o.beats:
            b.shots = [copy.copy(s) for s in b.shots]
        cap = cap_for(style)
        if cap:
            for b in o.beats:
                for s in b.shots:
                    if s.id not in keep:  # talking keeps its whole window: never cut mid-sentence
                        _window(s, max(cap, MIN_SHOT_S), best)

        target = target_s(style)
        if (target is not None and target <= SHORT_S) or style.get("pace") == "fast":
            for b in o.beats:
                b.shots = one_per_moment(b.shots, rank)
        if style.get("opening") == "hook":
            everything = [s for b in o.beats for s in b.shots]
            if len(everything) > 1:
                top = max(everything, key=rank)
                for b in o.beats:
                    if top in b.shots:
                        b.shots.remove(top)
                o.beats = [b for b in o.beats if b.shots]
                o.beats.insert(0, Beat("Opening", "The strongest moment first, as a hook.", [top], top.lean))

        if target:
            total = sum(s.end - s.start for b in o.beats for s in b.shots)
            where = spots([s for b in o.beats for s in b.shots])
            imp = worth.importance([s for b in o.beats for s in b.shots], where)
            # Drop the weakest shot that isn't the last one left in its part,
            # from the stop of the day that has the most shots in.
            while total > target:
                spare = [(rank(s), bi, s) for bi, b in enumerate(o.beats) if len(b.shots) > 1 for s in b.shots]
                if not spare:
                    break
                left = Counter(where.get(x.id, -1) for b in o.beats for x in b.shots)
                _, bi, s = weakest(spare, lambda x: x.id, where, lambda k: left[k], imp)
                o.beats[bi].shots.remove(s)
                total -= s.end - s.start
            # Still over: whole parts go, weakest first, never the opening.
            while total > target and len(o.beats) > 1:
                first = 1 if style.get("opening") == "hook" else 0
                pool = range(first, len(o.beats))
                if not pool:
                    break
                bi = min(pool, key=lambda i: max(rank(s) for s in o.beats[i].shots))
                total -= sum(s.end - s.start for s in o.beats[bi].shots)
                del o.beats[bi]

        said = describe(style)
        if said:
            o.summary = f"{o.summary} Shaped to your answers: {said}.".strip()


def length_ops(board: dict | None, cat, pool: list, target: float, vision: bool) -> tuple[list[dict], str]:
    """An edit that already exists, brought to about `target` seconds (the
    length slider in Frames): shorter by the same rule `shape` uses (weakest
    shots first, every part keeps its best; then whole parts, never a hook),
    longer by putting back the best-made usable shots it doesn't have yet,
    each in filming order next to its neighbours and only its rough-cut
    window, never one that repeats a shot already in (`alike`). Returns the
    ops and a sentence saying what happened."""
    from . import board as bd
    beats = [{"id": bt["id"], "title": bt.get("title", ""),
              "shots": [{"key": bd.key(e), "id": e.get("id"), "len": e["end"] - e["start"], "gap": bool(e.get("gap"))}
                        for e in bt["shots"]]} for bt in (board or {}).get("beats", [])]
    rank = lambda sid: worth.of(cat.shots[sid]) + (0.15 if cat.shots[sid].lean else 0.0)  # noqa: E731
    total = sum(e["len"] for bt in beats for e in bt["shots"])
    was = total
    tol = max(2.0, 0.03 * target)
    ops: list[dict] = []
    hook = 1 if beats and beats[0]["title"] == "Opening" and len(beats) > 1 else 0
    where = spots([cat.shots[e["id"]] for bt in beats for e in bt["shots"] if e["id"] in cat.shots]
                  + [s for s in pool if s.id in cat.shots])
    imp = worth.importance([cat.shots[e["id"]] for bt in beats for e in bt["shots"] if e["id"] in cat.shots], where)
    if total > target + tol:
        while total > target + tol:
            spare = [(rank(e["id"]), bi, e) for bi, bt in enumerate(beats) if len(bt["shots"]) > 1
                     for e in bt["shots"] if not e["gap"] and e["id"] in cat.shots]
            if not spare:
                break
            left = Counter(where.get(x["id"], -1) for bt in beats for x in bt["shots"] if x["id"])
            _, bi, e = weakest(spare, lambda x: x["id"], where, lambda k: left[k], imp)
            beats[bi]["shots"].remove(e)
            ops.append({"op": "drop_shot", "shot": e["key"]})
            total -= e["len"]
        while total > target + tol and len(beats) - hook > 1:
            bi = min(range(hook, len(beats)), key=lambda i: max(
                (rank(e["id"]) for e in beats[i]["shots"] if e["id"] in cat.shots), default=-9))
            total -= sum(e["len"] for e in beats[bi]["shots"])
            ops.append({"op": "drop_beat", "beat": beats[bi]["id"]})
            del beats[bi]
        n = sum(o["op"] == "drop_shot" for o in ops)
        parts = sum(o["op"] == "drop_beat" for o in ops)
        what = f"took out {n} of the weaker shot{'s' * (n != 1)}" if n else ""
        if parts:
            what += (" and " if what else "took out ") + f"{parts} part{'s' * (parts != 1)}"
        return ops, f"Now about {say_length(total)} (was {say_length(was)}): {what}. Undo puts them back."

    if total < target - tol:
        on = {e["id"] for bt in beats for e in bt["shots"] if e["id"]}
        kept = [cat.shots[i] for i in on if i in cat.shots]
        added = 0
        # stops of the day the edit doesn't show yet come back first
        shown = {where.get(i, -1) for i in on}
        left = list(pool)
        while left and total < target - tol:
            s = max(left, key=lambda s: (where.get(s.id, -1) not in shown,
                                         rank(s.id) if s.id in cat.shots else worth.of(s)))
            left.remove(s)
            d = s.end - s.start
            if s.id in on or s.id not in cat.shots or d <= 0 or total + d > target + max(tol, d / 2):
                continue
            if vision and any(alike(s, k) for k in kept):
                continue
            op = _put_back(beats, hook, cat, s)
            if op is None:
                break
            ops.append(op)
            on.add(s.id)
            shown.add(where.get(s.id, -1))
            kept.append(s)
            total += d
            added += 1
        if not added:
            return [], f"That's all the good footage there is: the edit stays about {say_length(total)}."
        more = "" if total >= target - tol else " That's all the good footage there is."
        return ops, (f"Now about {say_length(total)} (was {say_length(was)}): put back {added} "
                     f"shot{'s' * (added != 1)}, each where it happened.{more} Undo takes them out again.")
    return [], f"It's already about {say_length(total)}."


def _put_back(beats: list, hook: int, cat, s) -> dict | None:
    """The add_shot that puts `s` (its window) back where it happened: next to
    the shot filmed just before it, else before the first one filmed after it.
    Updates `beats` (length_ops' light copy of the board) to match."""
    when = lambda sid: cat.shots[sid].when if sid in cat.shots else None  # noqa: E731
    spots = [(bi, i, when(e["id"])) for bi, bt in enumerate(beats) for i, e in enumerate(bt["shots"])
             if e["id"] and when(e["id"]) is not None and bi >= hook]
    if s.when is not None and spots:
        before = [t for t in spots if t[2] <= s.when]
        bi, i = (max(before, key=lambda t: t[2])[:2] if before else min(spots, key=lambda t: t[2])[:2])
        at = i + 1 if before else i
    elif beats:
        bi, at = len(beats) - 1, len(beats[-1]["shots"])
    else:
        return None
    beats[bi]["shots"].insert(at, {"key": s.id, "id": s.id, "len": s.end - s.start, "gap": False})
    return {"op": "add_shot", "shot": s.id, "beat": beats[bi]["id"], "to_index": at,
            "start": round(s.start, 3), "end": round(s.end, 3)}


def _light(board: dict | None) -> tuple[list, int]:
    from . import board as bd
    beats = [{"id": bt["id"], "title": bt.get("title", ""),
              "shots": [{"key": bd.key(e), "id": e.get("id"), "len": e["end"] - e["start"], "gap": bool(e.get("gap"))}
                        for e in bt["shots"]]} for bt in (board or {}).get("beats", [])]
    return beats, 1 if beats and beats[0]["title"] == "Opening" and len(beats) > 1 else 0


def clip_ops(board: dict | None, cat, clip_id: str, into: bool, windows: list) -> list[dict]:
    """One clip moved between the piles in Frames (sarah, 2026-10-13: just
    Kept and Left out, like Footage). Out: every shot of it the edit has.
    In: its rough-cut windows (`windows`, the pool's shots of this clip; else
    its best-made shot whole), each where it happened in filming order."""
    beats, hook = _light(board)
    mine = lambda sid: bool(sid) and sid in cat.shots and cat.shots[sid].clip_id == clip_id  # noqa: E731
    if not into:
        return [{"op": "drop_shot", "shot": e["key"]} for bt in beats for e in bt["shots"] if mine(e["id"])]
    on = {e["id"] for bt in beats for e in bt["shots"] if e["id"]}
    shots = [s for s in windows if s.id not in on] or \
        [max((s for sid, s in cat.shots.items() if mine(sid) and sid not in on), key=lambda s: s.score, default=None)]
    ops = []
    for s in sorted((s for s in shots if s is not None), key=lambda s: (s.when is None, s.when or 0, s.start)):
        op = _put_back(beats, hook, cat, s)
        if op:
            ops.append(op)
    return ops


def reachable_s(board: dict | None, cat, pool: list, vision: bool) -> float:
    """How long the edit can get: what the length slider's end really means.
    Not every usable second -- a look-alike of a shot already in the edit, or
    of a better one, is never put back (sarah: no identical shots), so a total
    that counted them promised 2:28 and delivered 1:34. With an edit, it is
    exactly where `length_ops` stops; before one, the pool with look-alikes
    collapsed the same way."""
    if board and board.get("beats"):
        now = sum(e["end"] - e["start"] for bt in board["beats"] for e in bt["shots"])
        ops, _ = length_ops(board, cat, pool, 1e9, vision)
        return now + sum(o["end"] - o["start"] for o in ops if o["op"] == "add_shot")
    kept: list = []
    for s in sorted(pool, key=lambda s: s.score, reverse=True):
        if not (vision and any(alike(s, k) for k in kept)):
            kept.append(s)
    return sum(s.end - s.start for s in kept)
