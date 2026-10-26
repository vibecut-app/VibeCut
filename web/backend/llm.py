"""Turn a chat message into storyboard operations -- never into a new storyboard.

The model reads a text rendering of the storyboard (beat ids, titles, shot
ids, durations, on-device labels) and answers with JSON constrained to a
schema: a one-line reply, at most one clarifying question, and a list of
operations for board.py to apply. It never sees pixels; what leaves the
machine is the storyboard text and the conversation.

Credentials: ANTHROPIC_API_KEY in the environment, or in web/.env. The chat
(interpret) also runs on OpenAI with the course key when the AI switch is on
(oai.py; sarah, 2026-10-18), and then that is who answers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import board as bd
from . import oai
from . import overlays as ov
from . import storyboard as sb

MODEL = "claude-opus-5"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> None:
    if os.environ.get("ANTHROPIC_API_KEY") or not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        k, _, v = line.strip().partition("=")
        if k and v and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def chat_provider() -> str | None:
    """Who answers the chat: OpenAI on the course key while the AI switch is
    on (sarah, 2026-10-18: the chat should show when AI is on), else Claude
    if its key is set, else nobody. Only the chat moves: the other calls in
    this file stay on Claude's key."""
    if oai.enabled():
        return "openai"
    return "claude" if available() else None


# Claude Opus 5 list prices, $ per million tokens (MODEL), for the chat's
# estimate and its bill when Claude answers.
CLAUDE_PRICE_IN, CLAUDE_PRICE_OUT = 5.0, 25.0
# What one answer costs to write, with its thinking: JSON ops + a sentence
# or two. A range, because thinking length varies. [prior]
OUT_TOKENS = (600, 2500)
CHARS_PER_TOKEN = 3.5


def chat_prices() -> tuple[str | None, float, float, float]:
    """(model, $ per 1M input tokens, per 1M output, tokens one small frame
    costs) for whoever answers the chat now."""
    if chat_provider() == "openai":
        name = oai.model()
        p_in, _, p_out = oai.PRICES.get(name, oai.DEAREST)
        return name, p_in, p_out, 85.0          # a "low" detail image is a flat small charge
    return MODEL, CLAUDE_PRICE_IN, CLAUDE_PRICE_OUT, 384 * 216 / 750


def estimate(prompt_chars: int, with_image: bool = False) -> dict:
    """Dollars for one chat message before it is sent: input from the
    prompt's size, output as a range. Never calls a model."""
    name, p_in, p_out, img = chat_prices()
    tin = prompt_chars / CHARS_PER_TOKEN + (img if with_image else 0)
    lo, hi = (tin * p_in + o * p_out for o in OUT_TOKENS)
    return {"provider": chat_provider(), "model": name, "tokens_in": int(tin),
            "usd": [round(lo / 1e6, 4), round(hi / 1e6, 4)]}


def prompt_chars(cat: bd.Catalog, session: bd.Session, rules: str = "") -> int:
    """How long the chat's prompt is before the creator's own words: the
    instructions, the edit as text and the conversation so far."""
    return (len(SYSTEM) + len(render_state(cat, session, rules))
            + sum(len(m["content"]) for m in _history(session)))


_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


SYSTEM = """You are the editing assistant inside VibeCut, a tool that helps a vlogger turn a shoot into a storyboard. You do not write prose edits and you never rebuild the storyboard: each user message becomes a short list of operations on the storyboard that exists now. Everything you don't touch stays exactly as it is — that is the whole point, so change only what the user asked for.

## What you see
Each user message comes with the current state:
- FOOTAGE: a summary of what was filmed (on-device image labels, dates, places).
- PROPOSALS: three storyboards built from the footage (keys: time, place, subject). They are suggestions; the user picks one with choose_option. If the creator gave a voiceover there is a fourth, key voice: one beat per spoken line, titled with the line. Its gaps are lines nothing on the shelf shows; they are deliberate — don't fill one with an unrelated shot unless the user asks, and then prefer a shot that shows what the line says.
- CREATOR RULES (only if the creator has confirmed any): preferences they asked to keep. Follow them where they apply; the current message wins if it says otherwise. Never invent a rule from one edit.
- STORYBOARD: the working storyboard — beats in order, each with an id (like t1, s3), a title, and its shots (id like 3f2a9c01be44:0, duration, time filmed, labels, quality 0–1, "cam" if the creator is talking to camera).
- SHELF: shots that are not in the storyboard, available to add or swap in.

Labels come from Apple's on-device classifier, so they are generic ("food", "structure", "people", "outdoor"). Map the user's words onto them sensibly: a "market section" is the beat whose title or shots are about food stalls, shops, crowds, produce; "the opening" is the first beat (or its first few shots); "the ending" is the last beat.

## Operations
Use only ids that appear in the state. Fields you don't need are null (option and amount: unused).
- choose_option {option}: start from one of the proposals. Only when the user picks one (or asks you to), or when they ask for an edit and no storyboard exists yet and one proposal clearly fits.
- move_beat {beat, to_index}: reorder a beat (0 = first).
- drop_beat {beat}: cut a whole section.
- drop_shot {shot}: cut one shot.
- swap_shot {shot, with_shot}: replace a shot with a shelf shot, keeping its slot and length. with_shot null = let VibeCut pick the best-made similar shelf shot.
- add_shot {shot, beat, to_index}: bring a shelf shot into a beat.
- move_shot {shot, beat, to_index}: move a shot within or between beats.
- retitle_beat {beat, title}
- set_pace {beat, direction: tighter|looser, amount: a_little|a_lot}: trims (or relaxes) every shot in the beat around its best moment. "Punchier", "too slow", "drags" → tighter. "Let it breathe", "too rushed" → looser. "A lot", "way", "much" → a_lot.
- open_with {shot} / end_with {shot}: make a specific shot the very first / very last. To open or end on a whole section, use move_beat instead.

Words on screen (OVERLAYS in the state). They hang off a beat or a shot and move with it. Every caption (kind caption) shares one look (CAPTION STYLE in the state, set with caption_style below), so a font or colour can't differ between two captions; part labels, name tags, dates and titles are lettered by the video's look (set_look).
- add_overlay {kind, text, sub, beat | shot, placement}: kind is title (big opening words), part (a part/place label, sub = small line above it), name (a person's name tag, sub = handle or role), caption (a spoken line or short remark), date, end (end card). Give beat or shot to say where it goes; both null = the start of the video (for end: the last seconds). Use the user's own words when they give them, or words already in the storyboard (beat titles). When they ask for a caption and leave the words to you, write it in their voice, as if they typed it over their own clip: a thought in first person about what is in the shot ("this matcha is so good", "why is it so cold") or what they are doing ("walk to class", "quick grocery run"); 3 to 5 words, lowercase, at most one emoji, no clock time. Never describe the picture or list what is in it ("green spaces, a green drink, and sunny streets" reads as a machine). Never invent names, places or quotes — ask instead. placement (as for edit_overlay; null = its usual spot) puts it somewhere else on the picture.
- edit_overlay {overlay, text, sub, placement, kind: null}: change an existing overlay (id from OVERLAYS): its words (text, sub), or give beat or shot to move it to another moment. For a placement change to many at once, overlay all_captions means every caption (kind caption) and all_titles every chapter title (kind heading); their words and timing stay their own. Part labels, name tags, dates, the opening title and the end card are changed one at a time by their id.
  placement moves or sizes it on the picture (null = leave it as it is):
  - mode set: x, y are where its centre sits (0 to 1 across and down the frame; 0.5, 0.5 is the middle; captions usually sit around y 0.8, a title around 0.45) and scale is how big (0.4 to 3, 1 = its usual size). Any of x, y and scale you aren't changing: -1 (as it is now; for one at its usual spot, where OVERLAYS says a set starts from, so a set moves words drawn low on the left or in a corner to that point and centres them). It may go right up to the frame's edge. To make words bigger or smaller where they are, use size, not scale.
  - mode usual: back where it usually sits, at scale 1 (it doesn't change size: to undo an S or L give size M too). mode keep: leave where it is (x, y and scale are then ignored).
  - size: S, M or L, its size without moving it; keep = as it is.
  - title_look, for a chapter title only: spaced (thin, white, widely spaced capitals, the default), script, bold or serif; keep = as it is.
- drop_overlay {overlay}: overlay all_captions removes every caption, all_titles every chapter title.

How every caption looks, as in the Captions tab (CAPTION STYLE in the state is what's set now):
- caption_style {captions}: every field is keep (leave it as it is) unless the user asked about it. Picking a different word art starts it fresh, with its own outline, shadow, background and boldness, unless those are asked for in the same answer:
  - word_art: soft (the default: small lowercase words with a soft shadow, low on the left), outlined (serif letters with a black edge, the time on its own line), bold (big heavy capitals), label (dark words on a white box), highlight (dark words on a yellow marker), handwritten (handwriting, lowercase), tape (typewriter words on a strip), pop (white chunky letters, the longest word or two in yellow or blue), quiet (tiny widely spaced capitals), neon (pink glowing script), glow (bold letters with a blue glow), gradient (yellow fading to pink), extrude (3D letters with dark sides), retro (white capitals with a solid pink drop behind them). Extrude's sides and retro's drop are part of the word art, not its shadow: shadow none won't remove them; to lose them, pick another word art.
  - font: own (the word art's or the look's own font), or one of the fonts that come with VibeCut: tiktok-sans, montserrat, poppins, bebas-neue (tall capitals), anton (condensed and heavy), archivo-black, luckiest-guy (cartoon), bangers (comic), fredoka (rounded), permanent-marker, caveat (handwriting), pacifico (script), lobster (script), playfair-display (serif), courier-prime (typewriter). Only these: for any other font, say it isn't in VibeCut and offer the nearest.
  - colour: auto or "#rrggbb". Under soft, auto means VibeCut picks, for each caption, a colour that stands out from the picture behind it (under the playful look it is the look's own colour); "readable" or "contrasting" means auto when a #rrggbb is set now, and when colour is already auto, captions are made easier to read with outline, shadow or background. Under any other word art, auto is that word art's own colours, which read by its own edge, box or glow and never change with the picture; there, making captions stand out is better done with outline, shadow or background (or a #rrggbb). Under label, tape and highlight a colour fills the box or marker and the words turn black or white, whichever reads; to colour those words instead, also set background on with the box's own colour (label #ffffff, tape #f4efe3; a background replaces highlight's marker). Under gradient the letters keep their yellow-to-pink fill whatever colour is picked (only the edge changes); under pop the longest word or two keep pop's yellow and blue.
  - outline, shadow, background: set is keep, none (take it away), own (the word art's own) or on, with its colour ("#rrggbb", or keep) and numbers: outline width 0.05 (thin) to 0.25 (thick), at most 0.4; shadow strength 0 to 1 (usually 0.7), softness 0 to 1.5 (usually 0.4), distance 0 to 0.4 (usually 0.06); background opacity 0 to 1, round 0 (square) to 0.5 (pill). Any number you aren't changing: -1 (as it is now, which CAPTION STYLE shows).
  - boldness: set keep, own or on, with amount 0 (regular) to 0.15 (heaviest); 0.06 reads as bolder.
  - animation, how captions come in: own (the look's own), fade, pop, slide, stamp, type (typewriter) or word (word by word).
  - position: bottom or center, where captions sit when nobody has placed them by hand.
  Case: soft and handwritten show captions in lowercase; bold and quiet in capitals; retro and extrude in their own font, and the fonts bebas-neue, luckiest-guy and bangers, only have capitals whatever is typed; every other word art (and retro or extrude with another font) shows the words as typed. The look never changes a caption's case. Under every word art except soft, a caption's place name (its sub, the small line above) shows in capitals. To change the words themselves (lowercase them, say), use edit_overlay with the new text; where letters will still show as capitals, say so.

The look (vibe) of the words on screen, for the whole video — font, colours and how words move:
- set_look {look}: one of clean (crisp, simple), cozy (warm, soft, a lowercase serif), quiet (still, spare), cinematic (slow, wide, small caps), film (old camera, typewriter), playful (bright, bouncy, on the beat), hype (fast, loud, slams on the beat). "Make it feel cozier" → set_look cozy. Anything the creator set by hand (a font, a colour) is kept.

How the sound crosses a cut. Between parts the place's sound already carries a beat past the cut; inside a part the sound cuts with the picture.
- set_join {shot, sound}: the cut *after* that shot. sound is carry_out (the sound runs on under the next shot — "let the sound flow into the next part", "don't let it cut off"), carry_in (the next shot's sound starts early — "hear the next place before we see it"), cut (hard — "a clean break"), or default (back to the automatic choice).

## How to decide
- One user request → the smallest set of operations that does it. "Make the opening punchier and cut the market section" is exactly two operations: set_pace on the first beat, drop_beat on the market beat. Do not also reorder, retitle or tidy anything else.
- If the target is ambiguous (two beats could be "the market", or none looks like it), don't guess: ask one short question and return no operations.
- If the user describes the video itself rather than an edit (e.g. the first message, "it's a trip to Tokyo"), set `direction`: the themes to lean into, mapped to labels that exist in FOOTAGE. VibeCut then rebuilds the three proposals — this never touches the working storyboard.
- If that description is too vague to know what to lean into, and the footage has clearly different threads (e.g. lots of food and lots of people), ask exactly one question offering two or three concrete choices grounded in the footage ("Is this more about the food or the people you were with?"), put those choices in `choices`, and set nothing else. Don't ask when the footage only supports one reading or the user already said.
- If the request, or part of it, needs something these operations can't do, do the part you can and say in `reply`, in one short sentence, what's left and where in VibeCut it's done. Where things are: video effects (shake, glow, VHS, zoom…) are under Effects on the right after clicking a shot, and transitions there after clicking the dot between two shots; speed, turning, mirroring, cropping and trimming are under Edit after clicking a shot; a different song, or the music on or off, is Music in the left rail (or Audio on the right with nothing clicked); a shot's own sound is Audio after clicking the shot. New or generated footage isn't possible at all. Never pretend to have done something.
- Never ask more than one question at a time. Never ask when the request is clear.
- `reply` is one short sentence saying what you did (or empty if you asked a question). No lists, no restating the whole storyboard."""


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


# What the chat may set on the captions' one look (caption_style -> the
# overlay_style op, as the Captions tab sets it) and on one overlay's place
# (edit_overlay placement). "keep" leaves a field alone, so the strict schema
# can ask for every field without each answer resetting the rest. Numbers are
# clamped in code: structured outputs take no minimum / maximum.
WORD_ARTS = ("soft",) + tuple(ov.TEMPLATES)
_SET = {"type": "string", "enum": ["keep", "none", "own", "on"]}
_NUM = {"type": "number"}
_HEX = {"type": "string"}
CAPTIONS_SCHEMA = _obj({
    "word_art": {"type": "string", "enum": ["keep", *WORD_ARTS]},
    "font": {"type": "string", "enum": ["keep", "own", *ov.TYPEFACES]},
    "colour": {"type": "string", "description": "keep, auto, or #rrggbb"},
    "outline": _obj({"set": _SET, "color": _HEX, "width": _NUM}),
    "shadow": _obj({"set": _SET, "color": _HEX, "strength": _NUM, "softness": _NUM, "distance": _NUM}),
    "background": _obj({"set": _SET, "color": _HEX, "opacity": _NUM, "round": _NUM}),
    "boldness": _obj({"set": {"type": "string", "enum": ["keep", "own", "on"]}, "amount": _NUM}),
    "animation": {"type": "string", "enum": ["keep", "own", *ov.ENTERS]},
    "position": {"type": "string", "enum": ["keep", "bottom", "center"]},
})
PLACEMENT_SCHEMA = _obj({
    "mode": {"type": "string", "enum": ["keep", "set", "usual"]},
    "x": _NUM, "y": _NUM, "scale": _NUM,
    "size": {"type": "string", "enum": ["keep", *ov.SIZES]},
    "title_look": {"type": "string", "enum": ["keep", *ov.HEADING_LOOKS]},
})
# Every caption, or every chapter title, at once (expand): the kinds the
# Captions tab's "Same place for all captions" and its style reach. Part
# labels, name tags, dates and the opening title share moments on screen
# with them, so placing them all on one point would stack them.
ALL_OF = {"all_captions": "caption", "all_titles": "heading"}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "question", "choices", "direction", "ops"],
    "properties": {
        "reply": {"type": "string"},
        "question": _nullable({"type": "string"}),
        "choices": {"type": "array", "items": {"type": "string"}},
        "direction": _nullable({
            "type": "object", "additionalProperties": False,
            "required": ["themes", "labels"],
            "properties": {
                "themes": {"type": "array", "items": {"type": "string"},
                           "description": "Short names shown to the user, e.g. ['food']"},
                "labels": {"type": "array", "items": {"type": "string"},
                           "description": "Label identifiers from FOOTAGE that count as a match"},
            },
        }),
        "ops": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["op", "option", "beat", "shot", "with_shot", "to_index",
                             "title", "direction", "amount", "overlay", "kind", "text", "sub", "sound", "look",
                             "placement", "captions"],
                "properties": {
                    "op": {"type": "string", "enum": [*bd.LLM_OPS, "caption_style"]},
                    # "unused", not null: Claude's structured outputs take at most 16
                    # nullable fields in a schema, and this one is at that limit
                    "option": {"type": "string", "enum": ["unused", "time", "place", "subject", "voice"]},
                    "beat": _nullable({"type": "string"}),
                    "shot": _nullable({"type": "string"}),
                    "with_shot": _nullable({"type": "string"}),
                    "to_index": _nullable({"type": "integer"}),
                    "title": _nullable({"type": "string"}),
                    "direction": _nullable({"type": "string", "enum": ["tighter", "looser"]}),
                    "amount": {"type": "string", "enum": ["unused", "a_little", "a_lot"]},
                    "overlay": _nullable({"type": "string"}),
                    "kind": _nullable({"type": "string", "enum": ["title", "part", "name", "caption", "date", "end"]}),
                    "text": _nullable({"type": "string"}),
                    "sub": _nullable({"type": "string"}),
                    "sound": _nullable({"type": "string", "enum": ["cut", "carry_out", "carry_in", "default"]}),
                    "look": _nullable({"type": "string", "enum": ["clean", "cozy", "quiet", "cinematic", "film",
                                                                   "playful", "hype"]}),
                    "placement": _nullable(PLACEMENT_SCHEMA),
                    "captions": _nullable(CAPTIONS_SCHEMA),
                },
            },
        },
    },
}


# --------------------------------------------------------------------------
# state as text
# --------------------------------------------------------------------------

def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def _shot_line(cat: bd.Catalog, sid: str, start: float | None = None, end: float | None = None,
               key: str | None = None) -> str:
    s = cat.shots.get(sid)
    if s is None:
        return f"{key or sid} (missing)"
    d = (end - start) if start is not None else s.duration
    labels = ",".join(l for l, _ in sorted(s.labels.items(), key=lambda kv: -kv[1])[:4])
    when = s.when.strftime("%a %-I:%M%p").lower() if s.when else "undated"
    cam = " cam" if s.face_area >= 0.04 else ""
    return f"{key or sid} {d:.1f}s {when} q{s.score:.2f}{cam} [{labels}]"


def _placement(o: dict, st: dict) -> str:
    """Where an overlay sits, in edit_overlay's placement terms."""
    if o["kind"] == "chapters":
        return "a fixed strip across the top, can't be moved or sized"
    p = o.get("place")
    u = _usual(o, st)
    where = (f"placed x {p['x']:.2f} y {p['y']:.2f} scale {p.get('scale', 1.0):.2f}" if p
             else f"usual spot, {_drawn(o, st).replace('-', ' ')} (a set starts from x {u['x']:.2f} y {u['y']:.2f})")
    look = f", title look {o.get('look') or 'spaced'}" if o["kind"] == "heading" else ""
    return f"{where}, size {o.get('size', 'M')}{look}"


def _caption_style_line(b: dict) -> str:
    """The captions' one look, in caption_style's terms."""
    st = ov.style_of(b)
    shows = _dress_of(st)

    def dress(field: str) -> str:
        d = shows[field]
        now = "none" if not d.get(DRESS_OFF[field]) else d["color"] + "".join(
            f" {DRESS_ARGS[field][n]} {d[n]:g}" for n in ov.DRESS[field])
        return now if st.get(field) is not None else f"own ({now})"

    parts = [f"word_art {st.get('template') or 'soft'}", f"font {st.get('typeface') or 'own'}",
             f"colour {st.get('text_color') or 'auto'}", f"outline {dress('outline')}",
             f"shadow {dress('shadow')}", f"background {dress('backdrop')}",
             f"boldness {'own' if st.get('thick') is None else format(st['thick'], 'g')}",
             f"animation {st.get('enter') or 'own'}", f"position {st.get('captions') or 'bottom'}"]
    look = f" (look {st['look']})" if st.get("look") else ""
    return f"CAPTION STYLE{look}: " + "; ".join(parts)


def render_state(cat: bd.Catalog, session: bd.Session, rules: str = "") -> str:
    shots = list(cat.shots.values())
    counts: dict[str, int] = {}
    for s in shots:
        for l, v in s.labels.items():
            if v >= 0.3:
                counts[l] = counts.get(l, 0) + 1
    days = sorted({s.when.date() for s in shots if s.when})
    places = len({s.gps for s in shots if s.gps})
    top = ", ".join(f"{l}×{n}" for l, n in sorted(counts.items(), key=lambda kv: -kv[1])[:30])
    out = [f"FOOTAGE: {len(shots)} shots, {len(days)} filming day(s), {places} distinct GPS points, "
           f"{sum(s.face_area >= 0.04 for s in shots)} talking-to-camera shots.",
           f"Labels: {top or 'none (Vision unavailable)'}", ""]

    if session.proposals:
        out.append("PROPOSALS:")
        for o in session.proposals["options"]:
            beats = " | ".join(f"{b['title']} ({len(b['shots'])})" for b in o["beats"])
            out.append(f"- {o['key']}: {o['name']} — {o['summary']} Beats: {beats}")
        out.append("")

    b = session.board
    used = set()
    if b:
        total = sum(s["end"] - s["start"] for bt in b["beats"] for s in bt["shots"])
        out.append(f"STORYBOARD (from '{b['name']}', {_mmss(total)} total):")
        for i, bt in enumerate(b["beats"]):
            d = sum(s["end"] - s["start"] for s in bt["shots"])
            out.append(f"beat {bt['id']} #{i + 1} \"{bt['title']}\" — {len(bt['shots'])} shots, {_mmss(d)}")
            for s in bt["shots"]:
                if bd.is_gap(s):
                    out.append(f"  {bd.key(s)} (gap, {s['end'] - s['start']:.1f}s of black)")
                    continue
                used.add(s["id"])
                out.append("  " + _shot_line(cat, s["id"], s["start"], s["end"], key=bd.key(s)))
        items = ov.resolve(b)
        if items:
            where = {bt["id"]: bt["title"] for bt in b["beats"]}
            out.append("")
            out.append(f"OVERLAYS ({len(items)}):")
            st = ov.style_of(b)
            for o in items:
                a = o["anchor"]
                on = {"edit": "the video", "end": "the end", "beat": f"beat {a.get('id')} “{where.get(a.get('id'), '')}”",
                      "shot": f"shot {a.get('id')}"}[a["to"]]
                sub = f" / {o['sub']}" if o.get("sub") else ""
                out.append(f"  {o['id']} {o['kind']} “{o['text']}{sub}” on {on}, {_mmss(o['start'])}–{_mmss(o['end'])}"
                           f"; {_placement(o, st)}")
        out.append(_caption_style_line(b))
    else:
        out.append("STORYBOARD: none yet — the user hasn't chosen a proposal.")
    out.append("")

    shelf = sorted((s for s in shots if s.id not in used and not s.utility), key=lambda s: -s.score)
    out.append(f"SHELF ({len(shelf)} shots not in the storyboard, best first):")
    out += ["  " + _shot_line(cat, s.id) for s in shelf[:150]]
    if rules:
        out += ["", rules]
    return "\n".join(out)


def _history(session: bd.Session, limit: int = 12) -> list[dict]:
    msgs = []
    for t in [t for t in session.turns if t.kind == "chat"][-limit:]:
        msgs.append({"role": "user", "content": t.text})
        said = t.question or t.reply or "Done."
        done = "; ".join(l["text"] for l in t.lines) if t.lines else "no change"
        state = " (the user later undid this)" if t.undone else ""
        msgs.append({"role": "assistant", "content": f"{said}\n[applied: {done}{state}]"})
    return msgs


# --------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------

class LLMError(Exception):
    def __init__(self, msg: str, usage: dict | None = None) -> None:
        super().__init__(msg)
        self.usage = usage    # a failed answer can still have cost something


def interpret(message: str, cat: bd.Catalog, session: bd.Session, rules: str = "",
              moment: str = "", image_b64: str | None = None, who: str | None = None) -> dict:
    """-> {"reply", "question", "choices", "direction", "ops", "usage"}. `rules`
    are the creator's confirmed preferences (preferences.py), never candidates.
    `moment` / `image_b64`: the paused moment the message is about (moment.py).
    `usage` says who answered and what it cost ({"model", "cost", ...}). `who`:
    the answerer the caller already checked (app._chat_gate), so a switch
    flipped meanwhile can't send an unpriced message to the course key."""
    return ask(prepare(message, cat, session, rules, moment), image_b64, who)


def prepare(message: str, cat: bd.Catalog, session: bd.Session, rules: str = "", moment: str = "") -> dict:
    """Everything a chat turn sends, read off the edit as it is now (under the
    app's lock), so the call itself can wait outside it."""
    text = f"{render_state(cat, session, rules)}\n\n{moment + chr(10) + chr(10) if moment else ''}USER: {message}"
    return {"text": text, "history": _history(session)}


def ask(prepared: dict, image_b64: str | None = None, who: str | None = None) -> dict:
    """One chat turn from `prepare`, answered by `who` (default: whoever
    answers now, chat_provider)."""
    if (who or chat_provider()) == "openai":
        return _interpret_openai(prepared["text"], prepared["history"], image_b64)
    import anthropic

    content: str | list = prepared["text"]
    if image_b64:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                   {"type": "text", "text": prepared["text"]}]
    messages = prepared["history"] + [{"role": "user", "content": content}]
    try:
        resp = client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except anthropic.AuthenticationError as e:
        raise LLMError("The Anthropic key was rejected — check ANTHROPIC_API_KEY in web/.env.") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Rate-limited by the Anthropic API — try again in a moment.") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Couldn't reach the Anthropic API — check the connection.") from e

    if resp.stop_reason == "refusal":
        raise LLMError("The model declined that request.")
    if resp.stop_reason == "max_tokens":
        raise LLMError("The model's answer was cut off; try a shorter request.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        out = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError("The model's answer wasn't valid JSON.") from e
    u = getattr(resp, "usage", None)
    tin = sum(int(getattr(u, k, 0) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    tout = int(getattr(u, "output_tokens", 0) or 0)
    out["usage"] = {"model": MODEL, "prompt_tokens": tin, "completion_tokens": tout,
                    "cost": round((tin * CLAUDE_PRICE_IN + tout * CLAUDE_PRICE_OUT) / 1e6, 4)}
    return _tidy(out)


UNUSED = ("option", "amount")     # fields that say "unused" instead of null (SCHEMA)


def _tidy(out: dict) -> dict:
    out.setdefault("choices", [])
    out["ops"] = [_overlay_op(op) for op in out.get("ops") or [] if isinstance(op, dict)]
    for op in out["ops"]:
        for k in UNUSED:
            if op.get(k) == "unused":
                op[k] = None
    return out


def _interpret_openai(text: str, history: list[dict], image_b64: str | None) -> dict:
    """The same turn on OpenAI's course key: same instructions, same state as
    text, same schema (strict), the paused frame at low detail. Only a chat
    request the creator sent with its cost shown gets here (app.py)."""
    content = ([oai.image_b64(image_b64)] if image_b64 else []) + [{"type": "text", "text": text}]
    try:
        out, usage = oai.ask_json(SYSTEM, content, SCHEMA, "storyboard_ops", max_tokens=8000, history=history)
    except oai.OAIError as e:
        raise LLMError(str(e)[:1].upper() + str(e)[1:] + ".", e.usage) from e
    out["usage"] = usage
    return _tidy(out)


def _overlay_op(op: dict) -> dict:
    """The schema's flat fields -> what overlays.py expects."""
    if op.get("op") == "edit_overlay":
        for k in ("beat", "shot"):
            if op.get(k):
                op["anchor"], op["at"] = {"to": k, "id": op.pop(k)}, 0.3
        op.pop("kind", None)
        op.pop("look", None)     # the flat field is set_look's; a title's look comes from placement
        for k in ("text", "sub"):
            if op.get(k) is None:
                op.pop(k, None)
    return op


# Each word art's own edge, box or band and shadow, as overlayDraw.ts's
# TEMPLATES and softTpl (None = Soft) have them -- only what dressOf reads --
# so a switch the chat turns on starts where the Captions tab's would.
ART_DRESS: dict = {
    None: {"shadow": (0.35, 0.04)}, "outlined": {"stroke": ("#000000", 0.13)}, "bold": {"stroke": ("#000000", 0.2)},
    "label": {"box": ("#ffffff", 0.5)}, "highlight": {"marker": True}, "handwritten": {"shadow": True},
    "tape": {"box": ("#f4efe3", 0.08)}, "pop": {"stroke": ("#1a1a1a", 0.18)}, "quiet": {"shadow": True},
    "neon": {"stroke": ("#ff7ae6", 0.04)}, "glow": {}, "gradient": {"stroke": ("#1a1a1a", 0.14)},
    "extrude": {"stroke": ("#1a1a1a", 0.08)}, "retro": {},
}
# The chat's names for the tab's sliders, the slider that turns each one off,
# and where the tab puts it when its switch is turned on.
DRESS_ARGS = {"outline": {"width": "width"},
              "shadow": {"opacity": "strength", "blur": "softness", "dist": "distance"},
              "backdrop": {"opacity": "opacity", "round": "round"}}
DRESS_OFF = {"outline": "width", "shadow": "opacity", "backdrop": "opacity"}
TURN_ON = {"outline": 0.12, "shadow": 0.7, "backdrop": 0.85}
COLOURS = {"white": "#ffffff", "black": "#000000", "red": "#e53935", "yellow": "#ffd400", "pink": "#ff6fae",
           "blue": "#2f80ed", "green": "#2e9e5b", "orange": "#ff8a00", "purple": "#8e5cf7",
           "grey": "#9e9e9e", "gray": "#9e9e9e"}


def _colour(v: object) -> str | None:
    """#rrggbb, #rgb or a plain colour name -> #rrggbb; anything else None."""
    if not isinstance(v, str):
        return None
    s = COLOURS.get(v.strip().lower(), v.strip().lower())
    s = s if s.startswith("#") else "#" + s
    if len(s) == 4:
        s = "#" + "".join(c * 2 for c in s[1:])
    return ov._hex(s)


def _dark(hex_: str) -> bool:
    """overlayDraw's test for a dark colour (relative luminance under 0.35)."""
    n = int(hex_[1:], 16)
    lin = [(x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4)
           for x in (((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] < 0.35


def _dress_of(st: dict) -> dict:
    """The outline, shadow and background the captions show now, set by hand
    or the word art's own, as overlayDraw.ts's dressOf reads them (a picked
    colour tints the word art's box or edge first, as `tinted` does)."""
    art = dict(ART_DRESS.get(st.get("template"), {}))
    c = _colour(st.get("text_color"))
    if c and not st.get("backdrop"):
        if "box" in art:
            art["box"] = (c, art["box"][1])
        elif "marker" in art:
            pass
        elif "stroke" in art:
            art["stroke"] = ("#ffffff" if _dark(c) else "#000000", art["stroke"][1])
        elif _dark(c):
            art["stroke"], art["shadow"] = ("#ffffff", 0.1), False
    stroke, box, shadow = art.get("stroke"), art.get("box"), art.get("shadow")
    return {
        "outline": st.get("outline") or ({"color": "#000000" if stroke[0] == "#1a1a1a" else stroke[0], "width": stroke[1]}
                                         if stroke else {"color": "#000000", "width": 0.0}),
        "shadow": st.get("shadow") or ({"color": "#000000", "opacity": 0.7, "blur": shadow[0], "dist": shadow[1]}
                                       if isinstance(shadow, tuple) else
                                       {"color": "#000000", "opacity": 0.7 if shadow else 0.0, "blur": 0.4, "dist": 0.06}),
        "backdrop": st.get("backdrop") or ({"color": box[0], "opacity": 1.0, "round": box[1]} if box
                                           else {"color": "#000000", "opacity": 0.0, "round": 0.25}),
    }


def _num(v: object, lo: float, hi: float, fallback: float, zero_ok: bool = True) -> float:
    """A number the model gave, inside the slider's range. Not a number or
    below zero (-1 = as it is), or zero where that contradicts "on" ->
    `fallback`; a percentage like 12 for 0.12 or 150 for a 1.5 scale, as the
    tab's sliders read, is taken as meant."""
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v or v < 0 or (v == 0 and not zero_ok):
        return fallback
    if v >= 2 and v > hi and lo <= v / 100 <= hi:
        v = v / 100
    return round(min(hi, max(lo, float(v))), 3)


def _dress(field: str, ask: object, now: dict) -> tuple[bool, dict | None]:
    """(asked, value) for one of outline / shadow / backdrop: own = the word
    art's own (None), none = switched off, on = these numbers, starting from
    what the captions show now (`now`, from _dress_of) for any left as -1."""
    ask = ask if isinstance(ask, dict) else {}
    how = ask.get("set")
    if how == "own":
        return True, None
    off = DRESS_OFF[field]
    if how == "none":
        return True, {**now, off: 0.0}
    if how != "on":
        return False, None
    d = {"color": _colour(ask.get("color")) or now["color"]}
    for n, (lo, hi) in ov.DRESS[field].items():
        fb = TURN_ON[field] if n == off and now[n] <= 0 else now[n]
        d[n] = _num(ask.get(DRESS_ARGS[field][n]), lo, hi, fb, zero_ok=n != off)
    return True, d


DRESSED = ("outline", "shadow", "backdrop", "thick")
SET_ASKS = ("on", "none", "own")     # a dress switch actually asked about (not keep)
DRESS_FIELDS = (("outline", "outline"), ("shadow", "shadow"), ("backdrop", "background"))   # overlay_style's, caption_style's


def _caption_style(c: dict, now: dict, kept: set | frozenset = frozenset()) -> dict:
    """caption_style -> the overlay_style fields the Captions tab would send.
    Only what was asked becomes a field ("keep" adds nothing), so one answer
    never resets the rest; own / soft / auto are the tab's None. `kept`: dress
    fields an earlier caption_style in the same answer asked for."""
    out: dict = {}
    art = c.get("word_art")
    if art == "soft" or art in ov.TEMPLATES:
        out["template"] = None if art == "soft" else art
        if out["template"] != now.get("template"):
            # a new word art starts fresh, as the tab's tile does (StyleBars PLAIN)
            out.update(dict.fromkeys(f for f in DRESSED if f not in kept))
    font = c.get("font")
    if font == "own":
        out["typeface"] = None
    elif font in ov.TYPEFACES:
        out["typeface"] = font
    colour = str(c.get("colour") or "").strip().lower()
    if colour in ("auto", "automatic"):
        out["text_color"] = None
    elif _colour(colour):
        out["text_color"] = _colour(colour)
    cur = {**now, **out}
    shows = _dress_of(cur)
    for field, arg in DRESS_FIELDS:
        asked, v = _dress(field, c.get(arg), shows[field])
        # the tab ignores a click on the state it already shows: nothing to change, nothing pinned
        if asked and not (v is not None and v == shows[field] and cur.get(field) in (None, v)):
            out[field] = v
    bold = c.get("boldness") if isinstance(c.get("boldness"), dict) else {}
    if bold.get("set") == "own":
        out["thick"] = None
    elif bold.get("set") == "on":
        out["thick"] = _num(bold.get("amount"), 0.0, ov.THICK_MAX, now.get("thick") or 0.06)
    if c.get("animation") == "own":
        out["enter"] = None
    elif c.get("animation") in ov.ENTERS:
        out["enter"] = c["animation"]
    if c.get("position") in ("bottom", "center"):
        out["captions"] = c["position"]
    return out


def _lowered(d: object) -> dict:
    """An answer's words without case: structured outputs may change a letter's case in an enum."""
    if not isinstance(d, dict):
        return {}
    return {k: v.strip().lower() if isinstance(v, str) else _lowered(v) if isinstance(v, dict) else v
            for k, v in d.items()}


def _drawn(o: dict, st: dict) -> str:
    """Where overlayDraw draws an overlay nobody has placed: Soft captions low
    on the left, a word art's in the middle of the captions' line."""
    if o.get("kind") == "caption":
        return "center" if st.get("captions") == "center" else "bottom" if st.get("template") else "bottom-left"
    return str(o.get("pos") or ov.KINDS.get(o.get("kind"), {}).get("pos") or "bottom")


def _usual(o: dict, st: dict) -> dict:
    """Where an overlay nobody has placed sits, as the Captions tab reckons it
    (CaptionWords): a caption on the captions' line, others by their spot."""
    pos = ("center" if st.get("captions") == "center" else "bottom") if o.get("kind") == "caption" \
        else str(o.get("pos") or ov.KINDS.get(o.get("kind"), {}).get("pos") or "bottom")
    return {"x": 0.5, "y": 0.2 if pos.startswith("top") else 0.5 if pos == "center" else 0.8, "scale": 1.0}


def _placed(p: dict, o: dict | None, st: dict) -> dict:
    """A placement -> the overlay's place / size / title look, as dragging it
    on the picture or the Captions tab would set them. -1 = as it is."""
    o = o or {}
    if o.get("kind") == "chapters":
        return {}          # the bar is drawn in its own strip; the tab offers it no place or size
    out: dict = {}
    now = o.get("place") or _usual(o, st)
    if p.get("mode") == "usual":
        out["place"] = None
    elif p.get("mode") == "set":
        out["place"] = {"x": _num(p.get("x"), 0.0, 1.0, now["x"]), "y": _num(p.get("y"), 0.0, 1.0, now["y"]),
                        "scale": _num(p.get("scale"), ov.SCALE_MIN, ov.SCALE_MAX, now.get("scale", 1.0),
                                      zero_ok=False)}
    if str(p.get("size")).upper() in ov.SIZES:
        out["size"] = str(p["size"]).upper()
    if p.get("title_look") in ov.HEADING_LOOKS and o.get("kind") in (None, "heading"):
        out["look"] = p["title_look"]
    return out


def expand(ops: list[dict], board: dict | None, cat: bd.Catalog | None = None,
           proposals: dict | None = None) -> list[dict]:
    """The model's ops as board ops, read against the edit as it is now:
    caption_style becomes the overlay_style op the Captions tab sends, a
    placement becomes the overlay's place / size / title look, and an edit of
    all_captions / all_titles one edit per overlay of that kind (their words
    and timing stay each one's own). What can't be done still reaches the
    board, so the turn reports it skipped rather than saying nothing. With
    `cat`, each op reads the edit as the ops before it in the answer leave it
    (a part cut takes its captions with it, a story chosen has none)."""
    # the overlays and style as each op will find them: earlier ops in the
    # same answer (a caption dropped or moved, a style set) count
    overlays = {o["id"]: dict(o) for o in (board or {}).get("overlays") or []}
    first = set(overlays)
    st = ov.style_of(board)
    kept: set = set()
    asks: dict = {}       # caption_style's dress asks so far in this answer, by its field name
    out: list[dict] = []
    trial, done = board, 0
    for op in ops:
        op = dict(op)
        if cat is not None and len(out) > done:
            # only the ops added since the last look, each applied once (under the app's lock)
            trial, done = bd.applied(trial, out[done:], cat, proposals, first_id=done), len(out)
            # the board's own overlays as they are now; ones added in this answer have no id yet
            overlays = {o["id"]: dict(o) for o in (trial or {}).get("overlays") or [] if o["id"] in first}
            st = ov.style_of(trial)
        captions, placement = _lowered(op.pop("captions", None)), _lowered(op.pop("placement", None))
        if op.get("op") == "caption_style":
            art = captions.get("word_art")
            fresh = kept
            if (art == "soft" or art in ov.TEMPLATES) and (None if art == "soft" else art) != st.get("template"):
                # a new word art: what was asked earlier in this answer still holds (on the
                # old one it may have been what it showed anyway, so nothing was pinned)
                captions = {**asks, **{a: v for a, v in captions.items()
                                       if not (a in asks and not (isinstance(v, dict) and v.get("set") in SET_ASKS))}}
                # read on the new word art, as if asked after it: the order in the answer doesn't matter
                fresh = kept - {f for f, a in (*DRESS_FIELDS, ("thick", "boldness"))
                                if isinstance(captions.get(a), dict) and captions[a].get("set") in SET_ASKS}
            patch = _caption_style(captions, st, fresh)
            st = {**st, **patch}
            for f, a in (*DRESS_FIELDS, ("thick", "boldness")):
                if isinstance(captions.get(a), dict) and captions[a].get("set") in SET_ASKS:
                    kept.add(f)
                    asks[a] = captions[a]
            out.append({"op": "overlay_style", **patch})   # empty: "nothing to change"
            continue
        if op.get("op") == "add_overlay":
            out.append({**op, **{k: v for k, v in _placed(placement, {"kind": op.get("kind")}, st).items()
                                 if v is not None}})
            continue
        kind = ALL_OF.get(op.get("overlay"))
        if kind is None and op.get("op") in ("drop_overlay", "edit_overlay") and op.get("overlay") in first - set(overlays):
            continue    # gone with what it hung off, earlier in this answer: the diff says so
        if op.get("op") == "drop_overlay":
            gone = [o["id"] for o in overlays.values() if o["kind"] == kind] if kind else [op.get("overlay")]
            for oid in gone:
                overlays.pop(oid, None)
            out += [{"op": "drop_overlay", "overlay": oid} for oid in gone] or [op]   # none: the board says so
            continue
        if op.get("op") != "edit_overlay":
            out.append(op)
            continue
        if kind is None:
            one = _placed(placement, overlays.get(op.get("overlay")), st)
            overlays.get(op.get("overlay"), {}).update(one)
            out.append({**op, **one})
            continue
        targets = [o for o in overlays.values() if o["kind"] == kind]
        many = []
        for o in targets:
            one = _placed(placement, o, st)
            if one:
                o.update(one)
                many.append({"op": "edit_overlay", "overlay": o["id"], **one})
        added = [a for a in out if a.get("op") == "add_overlay" and a.get("kind") == kind]
        for a in added:      # added earlier in this answer: no id yet, so placed where it's added
            for k, v in _placed(placement, {"kind": kind, "place": a.get("place")}, st).items():
                if v is None:
                    a.pop(k, None)      # back to its usual spot: an add with no place
                else:
                    a[k] = v
        # nothing it could do: the board says why (none of them, or only moved / sized / removed at once)
        out += many or ([] if added else [{"op": "edit_overlay", "overlay": op["overlay"]}])
    return out


def interpret_offline(message: str, cat: bd.Catalog, session: bd.Session, rules: str = "") -> dict:
    """No key: the first message still works (keyword lean), edits need the model."""
    if session.board is None:
        d = sb.read_direction(message, list(cat.shots.values()))
        return {"reply": "", "question": None, "choices": [], "ops": [],
                "direction": {"themes": d.themes, "labels": sorted(d.labels), "keywords": True}}
    why = ("Editing by chat needs AI: turn AI on in the top bar. Each message shows what it costs before "
           "it's sent." if oai.has_key() else
           "Editing by chat needs AI, and there's no AI key on this Mac (OPENAI_API_KEY in web/.env).")
    return {"reply": "", "question": None, "choices": [], "direction": None, "ops": [],
            "error": why + " Timeline edits and Undo still work."}


# --------------------------------------------------------------------------
# talking-head mode: which sentences to cut (talk.py)
# --------------------------------------------------------------------------

TALK_SYSTEM = """You review the transcript of a creator talking to camera (口播), sentence by sentence, and decide which sentences a careful editor would cut. You only see text; timing and pauses are handled elsewhere.

Cut:
- retake: a sentence the speaker says again shortly after (usually better). Cut the EARLIER take, keep the last complete one.
- false_start: a sentence started and abandoned ("So the first thing — actually, let me start with…").
- mistake: a sentence that is immediately corrected ("…it's 30 — sorry, 40 minutes").
- off_script: only when a SCRIPT is given and the sentence is clearly an aside that isn't part of what they meant to record ("wait, is this recording?", "let me try that again").
- filler: a sentence that is nothing but filler.

Never cut a sentence just because it's informal, a joke, or not in the script but on topic. When unsure, keep it. The creator reviews every cut, so give a short note in English saying why (e.g. "Same as sentence 7 — keeping the later take").

Each sentence has an id, its text, its length in seconds, `rule` (what VibeCut's simple rules suggested: retake / script_retake / stumble / filler, or null) and, with a script, the script line it matched. You may agree or disagree with the rules. `reply` is one short English sentence summarising what you cut."""

TALK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["reply", "drops"],
    "properties": {
        "reply": {"type": "string"},
        "drops": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "reason", "note"],
            "properties": {
                "id": {"type": "string"},
                "reason": {"type": "string", "enum": ["retake", "false_start", "mistake", "off_script", "filler"]},
                "note": {"type": "string"},
            }}},
    },
}


def review_talk(sentences: list[dict], script: list[str]) -> dict:
    """-> {"reply", "drops": [{id, reason, note}]}. Only text leaves the machine."""
    import anthropic

    body = "SENTENCES:\n" + "\n".join(
        f"{s['id']} ({s['seconds']}s{', rule: ' + s['rule'] if s.get('rule') else ''}"
        f"{', script line ' + str(s['script_line']) if s.get('script_line') else ''}): {s['text']}" for s in sentences)
    if script:
        body = "SCRIPT:\n" + "\n".join(f"{k + 1}. {ln}" for k, ln in enumerate(script)) + "\n\n" + body
    try:
        resp = client().messages.create(
            model=MODEL, max_tokens=16000,
            system=[{"type": "text", "text": TALK_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": body}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": TALK_SCHEMA}},
        )
    except anthropic.APIError as e:
        raise LLMError(str(e)) from e
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


# --------------------------------------------------------------------------
# style questions (brief.py): one or two more, tailored to the description
# --------------------------------------------------------------------------

QUESTIONS_SYSTEM = """A vlogger has just dropped their clips into VibeCut and described the video in one line. Before anything is cut they answer a few multiple-choice style questions. These are already asked (don't repeat or rephrase them): {asked}.

Add at most two more questions that are specific to THIS description and would change which moments the edit keeps or how it's ordered — for example, for "my trip to Tokyo" you might ask which part of the trip matters most. Each question is short and friendly, with 2–4 short choices (a few words each). No questions about music, fonts, colour, captions or length — those are handled elsewhere. If the description is too vague for a useful extra question, return none."""

QUESTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["question", "choices"],
        "properties": {
            "question": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}},
        }}}},
}


def tailor_questions(message: str, asked: list[dict]) -> list[dict]:
    """-> extra questions in brief.py's shape. Only the description leaves the machine."""
    import anthropic

    try:
        resp = client().messages.create(
            model=MODEL, max_tokens=2000,
            system=QUESTIONS_SYSTEM.format(asked="; ".join(q["question"] for q in asked)),
            messages=[{"role": "user", "content": message[:1000]}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": QUESTIONS_SCHEMA}},
        )
    except anthropic.APIError as e:
        raise LLMError(str(e)) from e
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        raw = json.loads(text).get("questions", [])
    except (json.JSONDecodeError, AttributeError) as e:
        raise LLMError("unreadable questions") from e
    out = []
    for i, q in enumerate(raw[:2]):
        choices = [c.strip()[:60] for c in q.get("choices", []) if c.strip()][:4]
        if q.get("question", "").strip() and len(choices) >= 2:
            out.append({"id": f"extra{i + 1}", "question": q["question"].strip()[:140], "multi": False,
                        "choices": [{"key": c, "label": c} for c in choices]})
    return out


DAY_SYSTEM = """You write the small captions of a "day in my life" vlog: after the clock time, a few words saying what is happening, the way creators write them on Reels and TikTok ("coffee run", "class time", "golden hour walk", "packing up"). You are given, for each moment, its time and the on-device image labels of that shot (the only thing you know about the picture), plus the creator's one-line description of the video.

Rules: 1 to 4 words, all lowercase, no emoji, no hashtags, no full stop, no time. Write it the way the creator would type it over their own clip, what they are doing ("walk to class", "grocery run"), never a description or a list of what is in the picture ("green spaces and sunny streets" reads as a machine). Say only what the labels and the time support; lean on the time for meals and routines (8 am + cup = "morning coffee"). Don't repeat the same phrase for neighbouring moments unless it really is the same thing. If the labels don't tell you what is happening, return an empty string for that moment rather than guessing."""

DAY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["phrases"],
    "properties": {"phrases": {"type": "array", "items": {"type": "string"}}},
}


def day_phrases(items: list[dict], about: str = "", taste: str = "") -> list[str]:
    """[{time, labels}] -> one short phrase per item ('' = time only).
    Only times and label words leave the machine -- never a frame. `taste`:
    the creator's own words about their videos and their confirmed rules
    (make.taste_text), appended to the system prompt."""
    import anthropic

    lines = [f"{i + 1}. {it['time']} — labels: {', '.join(it['labels']) or 'none'}" for i, it in enumerate(items)]
    try:
        resp = client().messages.create(
            model=MODEL, max_tokens=1500, system=DAY_SYSTEM + (f"\n\n{taste}" if taste else ""),
            messages=[{"role": "user", "content": f"The video: {about[:300] or '(no description)'}\n\n"
                                                  + "\n".join(lines)
                                                  + f"\n\nReturn exactly {len(items)} phrases, in order."}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": DAY_SCHEMA}},
        )
    except anthropic.APIError as e:
        raise LLMError(str(e)) from e
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        raw = json.loads(text).get("phrases", [])
    except (json.JSONDecodeError, AttributeError) as e:
        raise LLMError("unreadable phrases") from e
    out = [" ".join(str(p).strip().lower().rstrip(".").split()[:4])[:40] for p in raw[:len(items)]]
    return out + [""] * (len(items) - len(out))


BRIEFS_SYSTEM = """A creator has just dropped their clips into a vlog editor, and the next screen asks "What's this video about?". Suggest three one-line answers they could click instead of typing, written the way a creator would describe their own video ("a weekend in Lisbon, mostly the food", "my first week at uni", "slow Sunday reset").

You only get facts read from the footage: counts, dates and times, on-device image labels, whether people and talking are in it, and rough coordinates. If the coordinates clearly point at a city or area you know, you may name it; otherwise don't name places. Don't invent people, events or feelings the facts don't support. Each line: 3 to 9 words, sentence case, no emoji, no hashtags, no full stop. Make the three genuinely different angles (for example: the whole day, the main thing in it, the mood)."""

BRIEFS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lines"],
    "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
}


def suggest_briefs(facts_text: str) -> list[str]:
    """Facts about the shoot (text) -> three suggested descriptions."""
    import anthropic

    try:
        resp = client().messages.create(
            model=MODEL, max_tokens=800, system=BRIEFS_SYSTEM,
            messages=[{"role": "user", "content": facts_text[:2000]}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": BRIEFS_SCHEMA}},
        )
    except anthropic.APIError as e:
        raise LLMError(str(e)) from e
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        raw = json.loads(text).get("lines", [])
    except (json.JSONDecodeError, AttributeError) as e:
        raise LLMError("unreadable suggestions") from e
    return [" ".join(str(x).split()).rstrip(".")[:70] for x in raw if str(x).strip()][:3]


MOMENT_MODEL = "claude-opus-5-5"
MOMENT_SYSTEM = """You are helping a vlogger with the first rough cut of their footage. From one clip, the editor has already found a few windows that are well made (sharp, steady, something in frame). For each window you see a few frames from its start, middle and end. Pick the one a good vlog editor would keep: the moment itself — something happening, a reaction, a reveal, the view opening up, the subject clearly the point — and a first frame that reads as intentional rather than the camera still finding its subject. Prefer what a viewer would want to see over what is merely tidy. Answer with the option number and a reason of at most 10 plain words a creator would understand (no camera jargon)."""

MOMENT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["best", "why"],
    "properties": {"best": {"type": "integer"}, "why": {"type": "string"}},
}


def best_moment(options: list[dict]) -> tuple[int, str]:
    """[{span: "0:03–0:08", frames: [jpeg bytes, ...]}] -> (0-based index, why).

    Unlike the rest of this module, this one sends pictures: a few small
    index frames (384 px wide) per option, nothing else of the clip."""
    import anthropic
    import base64

    content: list[dict] = []
    for i, o in enumerate(options):
        content.append({"type": "text", "text": f"Option {i + 1} ({o['span']}): start, middle, end"})
        for b in o["frames"]:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.standard_b64encode(b).decode()}})
    content.append({"type": "text", "text": f"Which option, 1 to {len(options)}, is the moment to keep?"})
    try:
        resp = client().messages.create(
            model=MOMENT_MODEL, max_tokens=2000, system=MOMENT_SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": MOMENT_SCHEMA}},
        )
    except anthropic.APIError as e:
        raise LLMError(str(e)) from e
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        d = json.loads(text)
        best = int(d["best"]) - 1
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise LLMError("unreadable choice") from e
    if not 0 <= best < len(options):
        raise LLMError(f"choice {best + 1} is not one of the options")
    return best, " ".join(str(d.get("why", "")).split())[:80]


# --------------------------------------------------------------------------
# the remix's shot picker, judged (plan step 4): which of these moments
# would a short like the references keep? One index frame per candidate.
# --------------------------------------------------------------------------

RANK_SYSTEM = (
    "You are choosing shots for a short-form vlog cut in the style of reference reels. "
    "You see one frame per candidate moment from one filming session, with the rules' score. "
    "Keep the moments that are distinctive, well made (sharp, framed, lit), varied, and tell "
    "the session as a viewer would want it: a place, a person, a thing happening. Prefer faces "
    "and action over empty views; never keep two near-identical frames. Answer with the "
    "numbers of exactly the moments to keep, in the order they should play (filming order unless "
    "a swap clearly helps), and ten words on why."
)
RANK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["keep", "why"],
               "properties": {"keep": {"type": "array", "items": {"type": "integer"}}, "why": {"type": "string"}}}


def rank_shots(options: list[dict], keep: int, taste: str = "") -> tuple[list[int], str]:
    """[{label, frame: jpeg bytes}] -> (0-based indices to keep, in play order; why).
    `taste` (make.taste_text) rides on the system prompt: who this creator is
    and what they've said they want, so the pick is theirs, not generic."""
    import anthropic
    import base64

    content: list[dict] = []
    for i, o in enumerate(options):
        content.append({"type": "text", "text": f"Moment {i + 1}: {o['label']}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(o["frame"]).decode()}})
    content.append({"type": "text", "text": f"Keep exactly {keep} of these {len(options)} moments."})
    try:
        resp = client().messages.create(
            model=MOMENT_MODEL, max_tokens=1500, system=RANK_SYSTEM + (f"\n\n{taste}" if taste else ""),
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": RANK_SCHEMA}},
        )
    except anthropic.APIError as e:
        raise LLMError(str(e)) from e
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        d = json.loads(text)
        idx = [int(k) - 1 for k in d["keep"]]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise LLMError("unreadable choice") from e
    seen: list[int] = []
    for i in idx:
        if 0 <= i < len(options) and i not in seen:
            seen.append(i)
    if len(seen) != keep:
        raise LLMError(f"kept {len(seen)} moments, asked for {keep}")
    return seen, " ".join(str(d.get("why", "")).split())[:80]
