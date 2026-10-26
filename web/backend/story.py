"""The story editor: a model that reads the shoot and plans the video.

Why this exists (sarah, 2026-10-18, comparing VibeCut with a London day
vlog she loves): that vlog is told in named chapters ("Morning Routine",
"OOTD", "Hit the stores"), each cut as a little story -- a quick setup, a
few short steps, one long payoff -- under a designed chapter title with a
plain line beneath it. VibeCut could not do this: on-device AI only
measures (labels, faces, sound), and hand-written rules pick one strong
moment per stop, each about as long as the next, with a clock time on it.
Nothing understood what was happening. "Is it just one action of taking
something, or a storytelling moment?" is a question about meaning, so a
model that can see the frames answers it.

What the model gets: up to MAX_CANDIDATES moments the rough cut kept (one
index frame each at low detail, plus what the device measured: time, stop,
labels, faces, talking, laughter, its worth). What it gives back: chapters
named by what happens, which moments each keeps, in what order, each with a
job (setup / step / payoff) and a length for that job, a line under each
chapter title and a caption on the few moments that want one, all in the
creator's voice (VOICE: a thought, or what they're doing; never a list of
what's in the picture). The rules still make the windows (the busiest
second), the beat grid and the music; the model never invents a frame or a
word the footage doesn't support.

One call per video. No answer, a bad answer, no key, or no yes to spending
it (oai.enabled): the rules' edit, exactly as before, and the reply says why.
Every number below is a prior.
"""

from __future__ import annotations

import re

from . import oai, overlays as ov, select as sel, storyboard as sb

MAX_CANDIDATES = 60          # frames sent; ~85 tokens each at low detail
# Seconds a shot holds for its job in a chapter, by frame [prior; the
# reference vlog: setups ~1-1.5 s, steps ~1-2 s, payoffs 3-4.5 s, a short
# cut about twice as fast].
ROLE_S = {
    "short": {"setup": (0.5, 1.2), "step": (0.6, 1.5), "payoff": (1.4, 3.0)},
    "tall": {"setup": (0.8, 1.6), "step": (1.0, 2.2), "payoff": (2.5, 4.5)},
    "wide": {"setup": (0.8, 1.6), "step": (1.0, 2.2), "payoff": (2.5, 4.5)},
}
# Every chapter title in a video wears one look (sarah, 2026-10-19: titles
# should be "cool and aesthetic"; day vlogs title chapters in thin, white,
# widely spaced capitals with a small italic line under them, the same way
# all through the video). The look can still be changed by hand.
HEADING_LOOK = "spaced"
HEADING_S = 2.4              # how long a chapter title stays up [prior]
MAX_CHAPTERS = 8
# Words on a moment (sarah, 2026-10-18: "captions usually convey 1. a
# thought, this food is good 2. what we're doing at a timestamp"; a list of
# what's in the picture reads as AI). Checked in code, never trusted [priors].
MAX_WORDS = 6
MAX_CHARS = 42
CAPTIONS_PER_CHAPTER = 2
CAPTION_AT = 0.15            # a beat after the cut, so the eye lands on the picture first
GAP_S = 0.15                 # a breath between the title going and a caption coming
MIN_READ_S = 1.0             # a caption up for less can't be read
READ_S = (1.4, 3.0)          # a caption holds long enough to read, never past its chapter

# How a creator writes the words on their own vlog: shared by the chapter
# lines and the captions, so every line the story editor writes sounds the same.
VOICE = """How the words sound. Every line you write is the creator talking, as if they typed it on their phone over their own clip, one of two kinds:
1. a thought, in first person, about what is in the frame: "this matcha is so good", "why is it so cold", "obsessed with this view", "ok one more coffee", "not me buying another tote"
2. what they are doing at that moment, plainly: "walk to class", "quick grocery run", "getting ready for class", "studying till late tonight", "finally back home"
3 to 5 words, lowercase, no full stop, no hashtags, at most one emoji (most lines have none). Never describe the picture or list what is in it: "green spaces, a green drink, and sunny streets", "a cozy café with warm lighting" and "beautiful city views" are what a machine writes, not a person. Never write a clock time (the app adds the real one), and only name a place, shop, food or person when the frame or the labels make it plain; never guess a brand."""

SYSTEM = """You are the editor of a vlog. The creator filmed a day (or a trip) on their phone and wants it cut like the vlogs they love: told in short named chapters, each one a little story.

You get the moments that survived a rough cut, in filming order. Each has a number, what the phone measured (time, which stop of the day, image labels, faces, talking, laughter, a 0-1 worth score) and one frame. Decide the video:

- Chapters: group moments by what is happening, not just by place or hour ("Morning Routine", "Coffee Run", "OOTD", "Hit the Stores", "Night In"). 3 to 8 chapters, in the order they happened. A title is 1 to 3 short words a creator would actually put on screen; it is shown in spaced capitals, so keep it short.
- The line under each title (subtitle): one line in the creator's voice (below) that opens the chapter, a thought or what they're doing ("finally getting my coffee", "walk to class"). Set clock to true when the time of day is part of the story (a day-in-my-life: waking up, heading to class, a late night); the app then puts the real time in front ("7:40 am · walk to class").
- Inside a chapter, cut it like a sequence: one or two quick setup shots (arriving, the outside, a wide view), a few short steps (the actions: pouring, picking, walking in), and one payoff held longer (the reveal, the reaction, the finished thing, the view). A chapter can be only a payoff if there is nothing to build up.
- Choose what to leave out. Prefer moments where something happens, the day rather than the creator's face over and over, variety, and frames that look intended. Never keep two moments that look the same.
- Give each kept moment its job and its length in seconds, within the ranges you are given, and never longer than it was filmed. Make the total land near the target length.
- Captions: most moments have none (an empty string). Give a caption only where a thought or a plain "what I'm doing" adds something the picture alone doesn't say: the payoff, a reaction, a small funny moment. At most 2 in a chapter, never on its first moment (the chapter title is on screen then), and never two that say the same thing.
- The hook: the one moment that should open the video before the first chapter, the most striking of the day (it may come from late in the day). It must not also appear in a chapter. Null if nothing stands out.
- video_title: 2-5 words naming the whole video.

""" + VOICE

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["video_title", "hook", "chapters"],
    "properties": {
        "video_title": {"type": "string"},
        "hook": {"type": ["integer", "null"]},
        "chapters": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "subtitle", "clock", "shots"],
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "clock": {"type": "boolean"},
                "shots": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["n", "role", "seconds", "caption"],
                    "properties": {"n": {"type": "integer"},
                                   "role": {"type": "string", "enum": ["setup", "step", "payoff"]},
                                   "seconds": {"type": "number"},
                                   "caption": {"type": "string"}}}},
            }}},
    },
}


class StoryError(Exception):
    pass


# --------------------------------------------------------------------------
# what the model sees
# --------------------------------------------------------------------------

def candidates(clips: dict[str, dict], cut) -> list[sb.Shot]:
    """The rough cut's usable moments, look-alikes collapsed, the strongest
    MAX_CANDIDATES by worth, back in filming order."""
    shots = sb.shots_from_clips(list(clips.values()), cut)
    shots, _ = sb.usable(shots)
    shots, _ = sel.dedupe([s for s in shots if not s.utility and s.duration >= sel.MIN_SHOT_S])
    if len(shots) > MAX_CANDIDATES:
        best = sorted(shots, key=lambda s: -(s.worth if s.worth is not None else s.score))[:MAX_CANDIDATES]
        keep = {s.id for s in best}
        shots = [s for s in shots if s.id in keep]
    return sorted(shots, key=lambda s: s.order)


def _clock(s: sb.Shot) -> str:
    if not s.when:
        return "time unknown"
    h = s.when.hour % 12 or 12
    return f"{s.when.strftime('%a')} {h}:{s.when.minute:02d} {'am' if s.when.hour < 12 else 'pm'}"


def describe(k: int, s: sb.Shot, stop: int, talking: bool) -> str:
    labels = ", ".join(n for n, v in sorted(s.labels.items(), key=lambda kv: -kv[1])[:4] if v >= 0.2) or "none"
    bits = [f"#{k}", _clock(s), f"stop {stop + 1}", f"{s.duration:.1f} s filmed", f"labels: {labels}"]
    if s.faces:
        bits.append(f"{s.faces} face{'s' * (s.faces != 1)}")
    if talking:
        bits.append("talking to camera")
    bits += [w for w in s.worth_why if "laugh" in w or "sing" in w or "new place" in w]
    if s.worth is not None:
        bits.append(f"worth {s.worth:.2f}")
    return " · ".join(bits)


def content(cands: list[sb.Shot], frames: list[bytes | None], stops: dict[str, int], talking: set[str],
            fmt: str, seconds: float, about: str, phrasing: list[str] | None = None) -> list[dict]:
    r = ROLE_S.get(fmt, ROLE_S["tall"])
    # lines the creator typed over their own clips (habits.phrases): the
    # nearest thing to their voice the app has, so the words sound like them
    own = [" ".join(str(x).split())[:80] for x in (phrasing or []) if str(x).strip()][:8]
    head = (f"Target length: about {seconds:.0f} s. Frame: {'vertical short' if fmt == 'short' else 'vertical vlog' if fmt == 'tall' else 'wide 16:9 vlog'}.\n"
            f"Seconds by job: setup {r['setup'][0]}-{r['setup'][1]}, step {r['step'][0]}-{r['step'][1]}, payoff {r['payoff'][0]}-{r['payoff'][1]}.\n"
            f"What the shoot looks like (guessed from it): {about or 'a day'}.\n"
            + (f"Lines the creator wrote on their own videos (their voice; write new ones that sound like this, never these): {'; '.join(own)}.\n" if own else "")
            + f"{len(cands)} moments follow, in filming order.")
    out: list[dict] = [{"type": "text", "text": head}]
    for k, (s, fr) in enumerate(zip(cands, frames), 1):
        out.append({"type": "text", "text": describe(k, s, stops.get(s.id, 0), s.id in talking)})
        if fr:
            out.append(oai.image(fr))
    return out


def estimate(n: int, model: str | None = None) -> float:
    """Dollars for one plan of `n` candidates, before it's made: ~85 tokens
    a frame, ~45 a line, the instructions, and an answer (a caption field on
    every kept moment) with its thinking [prior; the real cost is read from
    the reply's usage]."""
    p_in, _, p_out = oai.PRICES.get(model or oai.model(), oai.DEAREST)
    tokens_in = 1300 + n * (85 + 45)
    tokens_out = 1200 + n * 35 + 3000
    return (tokens_in * p_in + tokens_out * p_out) / 1e6


# --------------------------------------------------------------------------
# the words, checked
# --------------------------------------------------------------------------

_TIME = r"\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|\d{1,2}:\d{2}"
_EDGE = "\\s·\\-–—,:"
_LEAD = re.compile(rf"^(?:{_TIME})(?=[^\w:]|$)[{_EDGE}]*", re.I)                   # "7:40 am · walk to class"
_TAIL = re.compile(rf"[{_EDGE}]*(?:\b(?:at|around|by|from|until|about)\s+)?(?:{_TIME})(?=[!?.]*$)", re.I)   # "… at 7:40 am"
_ANY = re.compile(rf"(?<![\w:])(?:{_TIME})(?![\w:])", re.I)
_MODS = "\ufe0f\u20e3"                  # emoji presentation, keycap: part of the emoji before them
_ZWJ = "\u200d"                         # joins two emoji into one (a family, a profession)


def _emoji(ch: str) -> bool:
    o = ord(ch)
    return 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF


def _one_emoji(t: str) -> str:
    """Keep the first emoji (with its joins, skin tone, flag pair or tag
    sequence), drop the rest."""
    out, kept, inside, glued, flag = [], 0, False, False, 0
    for ch in t:
        o = ord(ch)
        part = inside and (ch in _MODS or 0x1F3FB <= o <= 0x1F3FF or ch == _ZWJ or glued or 0xE0020 <= o <= 0xE007F
                           or (flag == 1 and 0x1F1E6 <= o <= 0x1F1FF))
        if part:
            glued = ch == _ZWJ
            flag = 2 if flag == 1 and 0x1F1E6 <= o <= 0x1F1FF else flag
        elif _emoji(ch):
            kept += 1
            inside, glued, flag = True, False, 1 if 0x1F1E6 <= o <= 0x1F1FF else 0
        else:
            inside, glued, flag = False, False, 0
        if kept <= 1 or not (part or _emoji(ch)):
            out.append(ch)
    return "".join(out)


def line_of(text) -> str:
    """A line as the creator would type it, or "" when what came back isn't
    one: whitespace and quotes tidied, no full stop, at most one emoji. A
    clock at either end goes (the app puts the real time in front), with
    the "at" that led into it; one in the middle can't come out cleanly, so
    that line goes. So does a list of things in the picture ("green spaces,
    a green drink and sunny streets": the line sarah called AI) and a line
    over MAX_WORDS or MAX_CHARS -- cut short it would be a fragment."""
    t = " ".join(str(text or "").split()).strip().strip("\"'“”‘’")
    timed = bool(_ANY.search(t))
    t = _TAIL.sub("", _LEAD.sub("", t)).strip(" ·-–—,:")
    if _ANY.search(t):
        return ""
    low = t.lower()
    if t.count(",") >= 2 or ("," in t and (" and " in low or " & " in t)):
        return ""
    t = " ".join(_one_emoji(t).split())
    if len(t.split()) > MAX_WORDS or len(t) > MAX_CHARS or (timed and len(t.split()) < 2):
        return ""
    return t.rstrip(" .!,;:·-–—") if not t.endswith(("!", "?")) else t


def time_of(s: sb.Shot) -> str:
    """'7:40 am': how a day vlog writes the time in front of what's happening."""
    if not s.when:
        return ""
    h = s.when.hour % 12 or 12
    return f"{h}:{s.when.minute:02d} {'am' if s.when.hour < 12 else 'pm'}"


# --------------------------------------------------------------------------
# the answer -> a plan
# --------------------------------------------------------------------------

def plan_from(answer: dict, cands: list[sb.Shot], clips: dict[str, dict], fmt: str) -> tuple[sel.Plan, list[dict], str]:
    """Check the answer against what was offered and make the plan: the hook
    first, then one session per chapter. -> (plan, chapters [{title,
    subtitle, look, captions: [{shot, text}]}], video title). Ids that
    weren't offered, repeats, lengths outside a job's range and words that
    aren't a line a person would type are corrected, never trusted."""
    roles = ROLE_S.get(fmt, ROLE_S["tall"])
    used: set[int] = set()

    def take(n) -> sb.Shot | None:
        if not isinstance(n, int) or not 1 <= n <= len(cands) or n in used:
            return None
        used.add(n)
        return cands[n - 1]

    def pick(s: sb.Shot, role: str, secs: float, sess: int) -> sel.Pick:
        lo, hi = roles.get(role, roles["step"])
        try:
            want = float(secs)
        except (TypeError, ValueError):
            want = (lo + hi) / 2
        want = min(max(want, lo), hi)
        a, b, short = sel.window(clips, s, want)
        # the beat grid (remix.quantise) holds payoffs on whole beats, the rest on half-beats
        return sel.Pick(s, "hero" if role == "payoff" else "filler", a, b, s.worth or s.score, role, sess, short)

    hook_shot = take(answer.get("hook"))
    hook = [pick(hook_shot, "payoff", roles["payoff"][0], 0)] if hook_shot else []
    if hook:
        hook[0].role = "hook"
    sessions, chapters = [], []
    for ch in (answer.get("chapters") or [])[:MAX_CHAPTERS]:
        if not isinstance(ch, dict):
            continue
        i = len(sessions)
        picks, said = [], []
        for sh in ch.get("shots") or []:
            if not isinstance(sh, dict):
                continue
            s = take(sh.get("n"))
            if s is not None:
                picks.append(pick(s, sh.get("role") if sh.get("role") in roles else "step", sh.get("seconds"), i))
                said.append(line_of(sh.get("caption")))
        if not picks:
            continue
        sessions.append(picks)
        title = " ".join(str(ch.get("title") or "").split())[:40] or f"Part {i + 1}"
        line = line_of(ch.get("subtitle"))
        when = time_of(picks[0].shot) if ch.get("clock") is True else ""
        captions = [{"shot": p.shot.id, "text": t} for k, (p, t) in enumerate(zip(picks, said))
                    if t and k > 0 and t.lower() != line.lower()]
        chapters.append({"title": title, "subtitle": " · ".join(x for x in (when, line) if x),
                         "look": HEADING_LOOK, "captions": captions})
    if not sessions:
        raise StoryError("the plan kept no moments")
    plan = sel.Plan(hook=hook, sessions=sessions, titles=[c["title"] for c in chapters])
    kept = sum(len(s) for s in sessions) + len(hook)
    plan.notes.append(f"Planned as {len(chapters)} chapters from {len(cands)} moments; kept {kept}.")
    return plan, chapters, " ".join(str(answer.get("video_title") or "").split())[:50]


def heading_ops(plan: sel.Plan, chapters: list[dict]) -> list[dict]:
    """A chapter title with its line under it, at the start of each chapter
    (board beats r1.. as remix.board_of numbers them), held HEADING_S or the
    chapter's length if shorter; then the chapter's captions, each on its
    own moment once the title has gone, long enough to read, never past the
    chapter or over the next one, at most CAPTIONS_PER_CHAPTER."""
    out = []
    seen: set[str] = set()
    for i, (picks, ch) in enumerate(zip(plan.sessions, chapters), 1):
        span = sum(p.duration for p in picks)
        head = round(max(0.8, min(HEADING_S, span - 0.1)), 2)
        out.append({"op": "add_overlay", "kind": "heading", "text": ch["title"], "sub": ch["subtitle"],
                    "look": ch.get("look") or HEADING_LOOK, "beat": f"r{i}", "at": 0.0, "dur": head})
        starts, t = {}, 0.0
        for p in picks:
            starts.setdefault(p.shot.id, (t, p.duration))
            t += p.duration
        free, n = head + GAP_S, 0
        for c in ch.get("captions") or []:
            if n >= CAPTIONS_PER_CHAPTER or c["shot"] not in starts or c["text"].lower() in seen:
                continue
            at0, length = starts[c["shot"]]
            at = max(CAPTION_AT, free - at0)     # once the title (or the last caption) has gone
            if at > length - MIN_READ_S / 2:
                continue            # this moment is nearly over by then
            read = min(READ_S[1], max(READ_S[0], 0.9 + 0.32 * len(c["text"].split())))
            dur = min(read, span - (at0 + at) - 0.05)
            if dur < MIN_READ_S:
                continue            # too close to the chapter's end to read
            out.append({"op": "add_overlay", "kind": "caption", "text": c["text"],
                        "anchor": {"to": "shot", "id": c["shot"]}, "at": round(at, 2), "dur": round(dur, 2)})
            free, n = at0 + at + dur + GAP_S, n + 1
            seen.add(c["text"].lower())
    return out


def fit_captions(board: dict | None) -> list[dict]:
    """The same promises after shots have moved under the words (the
    self-check drops, shortens and moves shots; captions hang off a shot
    with a fixed length): a chapter title ends with its chapter, and each
    caption in a titled chapter starts once the title and the caption
    before it have gone and ends before the chapter does -- moved later
    and shortened to fit, or dropped when it can't be read. Returns the
    edit_overlay / drop_overlay ops."""
    if not board:
        return []
    beats, shots, _ = ov._spans(board)
    beat_of = {k: bid for bid, k, _a, _z in ov._entries(board)}
    out: list[dict] = []
    free: dict[str, float] = {}
    for o in ov.resolve(board):
        anchor = o.get("anchor") or {}
        if o["kind"] == "heading" and anchor.get("to") == "beat" and anchor.get("id") in beats:
            ca, cz = beats[anchor["id"]]
            end = min(o["end"], cz - 0.05)
            if end < o["end"] - 0.01:
                out.append({"op": "edit_overlay", "overlay": o["id"], "dur": round(max(ov.FRAME, end - o["start"]), 2)})
            free[anchor["id"]] = end + GAP_S
        elif o["kind"] == "caption" and anchor.get("to") == "shot" and beat_of.get(anchor.get("id")) in free:
            bid, (a, z) = beat_of[anchor["id"]], shots[anchor["id"]]
            start = max(o["start"], free[bid])
            end = min(start + (o["end"] - o["start"]), beats[bid][1] - 0.05)
            if start > z - MIN_READ_S / 2 or end - start < MIN_READ_S:
                out.append({"op": "drop_overlay", "overlay": o["id"]})
                continue
            if abs(start - o["start"]) > 0.01 or abs(end - o["end"]) > 0.01:
                out.append({"op": "edit_overlay", "overlay": o["id"], "anchor": dict(anchor),
                            "at": round(start - a, 2), "dur": round(end - start, 2)})
            free[bid] = end + GAP_S
    return out


# --------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------

def plan(clips: dict[str, dict], cut, fmt: str, seconds: float, about: str, post=None,
         taste: str = "", phrasing: list[str] | None = None):
    """-> (plan, chapters, video title, usage). Raises StoryError / oai.OAIError.
    `taste`: the creator in their own words and their confirmed rules
    (make.taste_text); `phrasing`: lines they typed on earlier videos."""
    from . import brief, tempo
    cands = candidates(clips, cut)
    if len(cands) < 3:
        raise StoryError("too few moments to plan a story")
    frames = [sel._frame(clips, s) for s in cands]
    stops = brief.spots(cands)
    talking = tempo.talking(list(clips.values()), cands)
    answer, usage = oai.ask_json(SYSTEM + (f"\n\n{taste}" if taste else ""),
                                 content(cands, frames, stops, talking, fmt, seconds, about, phrasing),
                                 SCHEMA, "story_plan", post=post)
    try:
        p, chapters, title = plan_from(answer, cands, clips, fmt)
    except StoryError as e:
        e.usage = usage     # a useless answer was still paid for
        raise
    return p, chapters, title, usage
