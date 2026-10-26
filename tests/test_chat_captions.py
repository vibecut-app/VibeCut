"""AI Edit sets how the captions look, the way the Captions tab does.

sarah (2026-10-20) asked the chat to "change all captions to lower case,
style's own font with contrasting colours with the background", and it said
it couldn't set fonts or colours. Since then the chat has the Captions tab's
controls (word art, font, colour or automatic, outline, shadow, background,
boldness, animation, where captions sit) and can move or size one caption,
every caption or every title. No network: the course key's reply is played
by a stand-in.

What must hold: an answer changes only what was asked ("keep" leaves the
rest, so a strict schema that asks for every field can't reset any); own /
soft / auto go back to the word art's own and the automatic colour; numbers
are kept inside the tab's sliders; every caption at once is one edit per
caption, never their words or timing, and reads as one line; it is one
undoable turn, its diff computed, not reported; the paused-moment box
proposes the same; and the schema stays valid for strict structured output
(no ranges, every field required, nothing extra).

    python tests/test_chat_captions.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

if __name__ == "__main__":
    os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-chat-captions-")
os.environ["VIBECUT_EXPORTS"] = os.path.join(os.environ["VIBECUT_CACHE"], "out")
os.environ.setdefault("VIBECUT_BED", "0")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_board import CLIPS, PROPOSALS, session  # noqa: E402
from web.backend import app as A  # noqa: E402
from web.backend import board as bd  # noqa: E402
from web.backend import defaults, llm, oai, timeline  # noqa: E402
from web.backend import overlays as ov  # noqa: E402
from web.backend import projects as pj  # noqa: E402

oai.ENV_FILE = llm.ENV_FILE = Path(os.environ["VIBECUT_CACHE"]) / "no.env"

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


KEEP_SET = {"set": "keep", "color": "#000000"}


def captions(**kw) -> dict:
    """caption_style's fields as a strict answer gives them: all of them, "keep" where not asked."""
    c = {"word_art": "keep", "font": "keep", "colour": "keep",
         "outline": {**KEEP_SET, "width": 0}, "shadow": {**KEEP_SET, "strength": 0, "softness": 0, "distance": 0},
         "background": {**KEEP_SET, "opacity": 0, "round": 0}, "boldness": {"set": "keep", "amount": 0},
         "animation": "keep", "position": "keep"}
    return {**c, **kw}


def placement(**kw) -> dict:
    return {"mode": "keep", "x": 0, "y": 0, "scale": 0, "size": "keep", "title_look": "keep", **kw}


def op(**kw) -> dict:
    fields = llm.SCHEMA["properties"]["ops"]["items"]["required"]
    return {k: kw.get(k) for k in fields}


def answer(ops: list[dict], reply: str = "Done.") -> dict:
    return {"model": "gpt-6.1-sol", "usage": {"prompt_tokens": 6000, "completion_tokens": 400},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
                {"reply": reply, "question": None, "choices": [], "direction": None, "ops": ops})}}]}


def strict_problems(node, path="$") -> list[str]:
    """What OpenAI's strict mode or Claude's structured outputs would refuse."""
    out = []
    if isinstance(node, dict):
        for bad in ("minimum", "maximum", "minLength", "maxLength", "pattern", "format", "minItems"):
            if bad in node:
                out.append(f"{path} has {bad}")
        if node.get("type") == "object":
            props = node.get("properties") or {}
            if node.get("additionalProperties") is not False:
                out.append(f"{path} allows extra fields")
            if sorted(node.get("required") or []) != sorted(props):
                out.append(f"{path} doesn't require every field")
        for k, v in node.items():
            out += strict_problems(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += strict_problems(v, f"{path}[{i}]")
    return out


def style() -> dict:
    return A.SESSION.board.get("overlay_style") or {}


def kinds(*ks: str) -> list[dict]:
    return [o for o in A.SESSION.board.get("overlays") or [] if o["kind"] in ks]


def main() -> int:
    s, cat = session()
    A.SESSION = s
    A.CATALOG["cat"] = cat
    A.CLIPS.clear()
    A.CLIPS.update({c["id"]: c for c in CLIPS})
    A._make_proposals = lambda d: PROPOSALS
    A._session = lambda: {}
    A._save = lambda: None
    A.WORKFLOW.state = "story"
    A.PROJECT["p"] = pj.Project(id="chat-captions", name="Chat")
    beats = [b["id"] for b in s.board["beats"]]
    shots = [x for b in s.board["beats"] for x in b["shots"]]
    # a made video's words: a chapter title, an opening title, stop labels and captions
    words = [{"op": "add_overlay", "kind": "heading", "text": "MORNING", "sub": "slow start", "beat": beats[0]},
             {"op": "add_overlay", "kind": "title", "text": "Tokyo", "beat": beats[0]},
             {"op": "add_overlay", "kind": "part", "text": "Columbia University, morning", "beat": beats[0]},
             {"op": "add_overlay", "kind": "part", "text": "Shibuya, night", "beat": beats[-1]}]
    words += [{"op": "add_overlay", "kind": "caption", "text": t, "shot": bd.key(x)}
              for t, x in zip(["This Matcha Is So Good", "Walk To Class", "Why Is It So Cold", "Night Walk Home"],
                              shots[::3])]
    s.add({"kind": "direct", "text": "words", "ops": words}, cat, lambda d: PROPOSALS)
    s.add({"kind": "direct", "text": "picked by hand",
           "ops": [{"op": "overlay_style", "template": "bold", "text_color": "#ff0000"}]}, cat, lambda d: PROPOSALS)
    check("the fixture has its words", len(kinds("caption")) == 4 and len(kinds("part")) == 2
          and len(kinds("heading")) == 1, str(s.turns[-2].skipped))

    sent: list[dict] = []
    replies: list[dict] = []

    def stand_in(url, body, headers):
        sent.append(body)
        return replies.pop(0)
    real_post = oai._post
    oai._post = stand_in
    os.environ["OPENAI_API_KEY"] = "sk-test"
    oai.switch(True)

    def chat(message: str, ops: list[dict]):
        replies.append(answer(ops))
        A.api_chat(A.ChatReq(message=message, ai_ok=A.api_chat_estimate()["usd"][1]))
        return A.SESSION.turns[-1]

    try:
        print("the schema and the instructions")
        probs = strict_problems(llm.SCHEMA)
        check("valid for strict structured output: no ranges, every field required, nothing extra",
              not probs, "; ".join(probs[:4]))
        unions = json.dumps(llm.SCHEMA).count('"anyOf"')
        check("at most 16 nullable fields, Claude's limit for structured outputs", unions <= 16, str(unions))
        items = llm.SCHEMA["properties"]["ops"]["items"]
        check("caption_style is an op, with placement and captions fields",
              "caption_style" in items["properties"]["op"]["enum"]
              and {"placement", "captions"} <= set(items["required"]))
        names = [*ov.TEMPLATES, *ov.TYPEFACES, *ov.ENTERS, "soft", "all_captions", "all_titles"]
        check("the instructions name every word art, font and animation, and all captions / titles",
              all(n in llm.SYSTEM for n in names), str([n for n in names if n not in llm.SYSTEM]))
        check("and where in the app the rest is done",
              all(w in llm.SYSTEM for w in ("under Effects", "under Edit", "Music in the left rail", "Audio")))
        state = llm.render_state(cat, A.SESSION)
        line = next((l for l in state.splitlines() if l.startswith("CAPTION STYLE")), "")
        check("the state says how the captions look now, the word art's own numbers too (a white edge round red)",
              "word_art bold" in line and "colour #ff0000" in line and "font own" in line
              and "outline own (#ffffff width 0.2)" in line and "background own (none)" in line, line)
        check("and where each caption sits, and where a move would start from",
              "usual spot, bottom (a set starts from x 0.50 y 0.80), size M" in state and "title look spaced" in state
              and "usual spot, bottom left (a set starts from x 0.50 y 0.80), size M" in state)

        print("her message: lowercase, the style's own font, colours that stand out")
        A.SESSION.add({"kind": "direct", "text": "a font", "ops": [{"op": "overlay_style", "typeface": "anton"}]},
                      cat, lambda d: PROPOSALS)
        before = json.dumps(style(), sort_keys=True)
        lowered = [op(op="edit_overlay", overlay=o["id"], text=o["text"].lower()) for o in kinds("caption")]
        t = chat("change all captions to lower case style's own font with contrasting colours",
                 [op(op="caption_style", captions=captions(font="own", colour="auto")), *lowered])
        st = style()
        check("one undoable chat turn", t.kind == "chat" and not t.skipped, str(t.skipped))
        check("the style's own font, the automatic colour", st.get("typeface", "x") is None
              and st.get("text_color", "x") is None, json.dumps(st))
        check("what wasn't asked stays (the word art)", st.get("template") == "bold")
        check("the words are lowercase", all(o["text"] == o["text"].lower() for o in kinds("caption")))
        said = [l["text"] for l in t.lines]
        check("the diff says so, computed", "Caption font: back to the look's own" in said
              and "Caption colour: automatic" in said, json.dumps(said))
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)
        check("Undo brings the font, colour and words back", json.dumps(style(), sort_keys=True) == before
              and kinds("caption")[0]["text"] == "This Matcha Is So Good")
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)

        print("everything in the Captions tab")
        t = chat("white outline, montserrat, word by word, in the middle",
                 [op(op="caption_style", option="unused", amount="unused", captions=captions(
                     font="Montserrat", animation="word", position="center",
                     outline={"set": "on", "color": "#FFF", "width": 0.12}))])
        st = style()
        check("font, animation, position", st.get("typeface") == "montserrat" and st.get("enter") == "word"
              and st.get("captions") == "center", json.dumps(st))
        check("an outline in white (#FFF read as #ffffff)", st.get("outline") == {"color": "#ffffff", "width": 0.12})
        said = [l["text"] for l in t.lines]
        check("each named in the diff", "Caption font: Montserrat" in said and "Captions come in: Word by word" in said
              and any("outline" in x for x in said), json.dumps(said))
        check("an entrance asked for in words is remembered like one picked in the tab",
              defaults.get().get("caption_enter") == "word", json.dumps(defaults.get()))

        t = chat("soft shadow, pink box, bolder",
                 [op(op="caption_style", captions=captions(
                     shadow={"set": "on", "color": "#000000", "strength": 70, "softness": -1, "distance": 5},
                     background={"set": "on", "color": "pink", "opacity": 0.9, "round": 0.9},
                     boldness={"set": "on", "amount": 1}))])
        st = style()
        check("a shadow: 70 read as 70%, a bad softness the tab's own, 5 as 5%",
              st.get("shadow") == {"color": "#000000", "opacity": 0.7, "blur": 0.4, "dist": 0.05}, json.dumps(st.get("shadow")))
        check("a pink background, roundness kept inside its slider",
              st.get("backdrop") == {"color": "#ff6fae", "opacity": 0.9, "round": 0.5}, json.dumps(st.get("backdrop")))
        check("bolder, up to the tab's heaviest", st.get("thick") == ov.THICK_MAX)
        check("the outline from before is still there", st.get("outline") == {"color": "#ffffff", "width": 0.12})

        t = chat("no shadow, the word art's own background, sparkly letters",
                 [op(op="caption_style", captions=captions(
                     colour="sparkly", shadow={"set": "none", "color": "", "strength": 0, "softness": 0, "distance": 0},
                     background={"set": "own", "color": "", "opacity": 0, "round": 0}))])
        st = style()
        check("none switches the shadow off, keeping its other numbers",
              st.get("shadow") == {"color": "#000000", "opacity": 0.0, "blur": 0.4, "dist": 0.05}, json.dumps(st.get("shadow")))
        check("own = the word art's own", "backdrop" in st and st["backdrop"] is None)
        check("a colour that isn't one changes nothing", st.get("text_color") is None and not t.skipped)

        t = chat("back to the soft captions", [op(op="caption_style", captions=captions(word_art="soft"))])
        check("soft = no template", style().get("template", "x") is None
              and "Captions: Soft" in [l["text"] for l in t.lines])
        t = chat("hmm", [op(op="caption_style", captions=captions())])
        check("all keep: said as nothing to change, never silently", t.skipped == ["nothing to change"], str(t.skipped))

        print("as the tab does it")
        A.SESSION.add({"kind": "direct", "text": "dressed by hand", "ops": [
            {"op": "overlay_style", "backdrop": {"color": "#000000", "opacity": 0.85, "round": 0.25}, "thick": 0.06}]},
            cat, lambda d: PROPOSALS)
        t = chat("neon captions", [op(op="caption_style", captions=captions(word_art="neon"))])
        st = style()
        check("a new word art starts fresh: its own outline, shadow, background, boldness",
              st.get("template") == "neon" and all(k in st and st[k] is None for k in ("outline", "shadow", "backdrop", "thick")),
              json.dumps(st))
        t = chat("label captions on a pink box", [op(op="caption_style", captions=captions(
            word_art="label", background={"set": "on", "color": "pink", "opacity": -1, "round": -1}))])
        check("unless asked for in the same answer, starting from the word art's own box (pill, solid)",
              style().get("backdrop") == {"color": "#ff6fae", "opacity": 1.0, "round": 0.5}, json.dumps(style().get("backdrop")))
        t = chat("bold, red outline", [op(op="caption_style", captions=captions(
            word_art="bold", outline={"set": "on", "color": "red", "width": -1}))])
        check("a colour alone keeps the word art's own edge width", style().get("outline")
              == {"color": "#e53935", "width": 0.2}, json.dumps(style().get("outline")))
        t = chat("label, rounder", [op(op="caption_style", captions=captions(word_art="label")),
                                    op(op="caption_style", captions=captions(
                                        background={"set": "on", "color": "keep", "opacity": -1, "round": 0.3}))])
        check("keep for a colour keeps the word art's own (white, not black)", style().get("backdrop")
              == {"color": "#ffffff", "opacity": 1.0, "round": 0.3}, json.dumps(style().get("backdrop")))
        A.SESSION.add({"kind": "direct", "text": "a shadow", "ops": [
            {"op": "overlay_style", "shadow": {"color": "#000000", "opacity": 0.7, "blur": 0.4, "dist": 0.06}}]},
            cat, lambda d: PROPOSALS)
        t = chat("stronger shadow", [op(op="caption_style", captions=captions(
            shadow={"set": "on", "color": "keep", "strength": 1, "softness": -1, "distance": -1}))])
        check("-1 keeps a number as it is", style().get("shadow") == {"color": "#000000", "opacity": 1.0,
                                                                     "blur": 0.4, "dist": 0.06}, json.dumps(style().get("shadow")))
        t = chat("bold, with its outline", [op(op="caption_style", captions=captions(word_art="bold")),
                                            op(op="caption_style", captions=captions(
                                                outline={"set": "on", "color": "keep", "width": -1}))])
        check("an outline it already shows isn't pinned (the tab ignores a click on the state it shows)",
              "outline" in style() and style()["outline"] is None and t.skipped == ["nothing to change"],
              json.dumps(style()) + str(t.skipped))
        t = chat("red outline, then neon", [op(op="caption_style", captions=captions(
            outline={"set": "on", "color": "#ff0000", "width": -1})), op(op="caption_style", captions=captions(word_art="neon")),
            op(op="drop_shot", shot="nothere00001:0")])
        check("asked for earlier in the same answer, it survives the new word art, read on it (neon's own width)",
              style().get("template") == "neon" and style().get("outline") == {"color": "#ff0000", "width": 0.04},
              json.dumps(style()))
        check("and the word art is remembered even if something else in the answer couldn't be done",
              t.skipped and defaults.get().get("caption_template") == "neon", json.dumps(defaults.get()) + str(t.skipped))
        A.SESSION.add({"kind": "direct", "text": "bold again", "ops": [{"op": "overlay_style", "template": "bold"}]},
                      cat, lambda d: PROPOSALS)
        t = chat("a black outline, soft captions", [op(op="caption_style", captions=captions(
            outline={"set": "on", "color": "#000000", "width": -1})), op(op="caption_style", captions=captions(word_art="soft"))])
        check("an outline asked before the word art changes is read again on the new one (soft has none: the tab's on)",
              style().get("template", "x") is None and style().get("outline") == {"color": "#000000", "width": 0.12},
              json.dumps(style()))
        A.SESSION.add({"kind": "direct", "text": "bold again", "ops": [{"op": "overlay_style", "template": "bold"}]},
                      cat, lambda d: PROPOSALS)
        t = chat("no shadow, handwritten", [op(op="caption_style", captions=captions(
            shadow={"set": "none", "color": "keep", "strength": -1, "softness": -1, "distance": -1})),
            op(op="caption_style", captions=captions(word_art="handwritten"))])
        check("a shadow switched off before the word art changes stays off on it",
              style().get("template") == "handwritten" and (style().get("shadow") or {}).get("opacity") == 0,
              json.dumps(style()))

        t = chat("tighten the first part a lot", [op(op="set_pace", beat=beats[0], direction="tighter",
                                                     amount="a_lot", option="unused")])
        check("unused means not given; the rest of the op still works", not t.skipped and t.ops
              and t.ops[0].get("amount") == "a_lot" and "option" not in t.ops[0], str(t.skipped))
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)

        print("moving and sizing")
        t = chat("put every caption near the top, bigger",
                 [op(op="edit_overlay", overlay="all_captions", text="ignored", beat=beats[-1],
                     placement=placement(mode="set", x=0.5, y=0.2, scale=0, size="l"))])
        check("every caption placed, at its own scale", all(
            o.get("place") == {"x": 0.5, "y": 0.2, "scale": 1.0} and o["size"] == "L" for o in kinds("caption")),
            json.dumps([o.get("place") for o in kinds("caption")]))
        check("their words and timing are their own", kinds("caption")[0]["text"] == "this matcha is so good"
              and all(o["anchor"]["id"] != beats[-1] for o in kinds("caption")))
        check("stop labels and titles, on screen with them, left where they are (never stacked on one point)",
              all(o.get("place") is None for o in kinds("part", "heading", "title")))
        said = [l["text"] for l in t.lines]
        check("one turn of four edits, read as one line", len(t.ops) == 4
              and said == ["Changed the place and size of 4 captions"], json.dumps(said))
        lines = [{"kind": "retitled", "text": f"Changed the place of the {k} “{w}”"}
                 for k, w in (("caption", "a"), ("caption", "b"), ("part label", "c"), ("caption", "d"))]
        check("a mix of kinds is counted as what it is", ov._fold(lines)[0]["text"]
              == "Changed the place of 3 captions and a part label", ov._fold(lines)[0]["text"])
        check("three or fewer stay one line each", len(ov._fold(lines[:3])) == 3)

        cap = kinds("caption")[0]
        t = chat("that one back where it was", [op(op="edit_overlay", overlay=cap["id"],
                                                    placement=placement(mode="usual"))])
        check("usual = back to its spot", kinds("caption")[0].get("place") is None
              and kinds("caption")[1].get("place") is not None)
        t = chat("bigger, 4x", [op(op="edit_overlay", overlay=cap["id"],
                                   placement=placement(mode="set", x=1.4, y=-2, scale=4))])
        check("kept on the frame and inside the size limits; -1 y stays on the captions' line (center now)",
              kinds("caption")[0].get("place") == {"x": 1.0, "y": 0.5, "scale": ov.SCALE_MAX},
              json.dumps(kinds("caption")[0].get("place")))
        t = chat("size 150%", [op(op="edit_overlay", overlay=cap["id"],
                                  placement=placement(mode="set", x=-1, y=-1, scale=150))])
        check("150 read as the tab's 150%", kinds("caption")[0].get("place") == {"x": 1.0, "y": 0.5, "scale": 1.5},
              json.dumps(kinds("caption")[0].get("place")))
        bottom, top = {"captions": "bottom"}, {"captions": "bottom"}
        check("an unplaced caption's usual spot is its line; a date's is the top",
              llm._usual({"kind": "caption"}, bottom)["y"] == 0.8 and llm._usual({"kind": "caption"}, {"captions": "center"})["y"] == 0.5
              and llm._usual({"kind": "date", "pos": "top-right"}, top)["y"] == 0.2)
        check("the chapter bar takes no place or size (it is drawn in its own strip)",
              llm._placed(placement(mode="set", x=0.5, y=0.5, scale=2, size="L"), {"kind": "chapters"}, bottom) == {})
        t = chat("a caption at the top: see you tomorrow", [op(op="add_overlay", kind="caption", text="see you tomorrow",
                                                              shot=bd.key(shots[1]),
                                                              placement=placement(mode="set", x=-1, y=0.15, scale=-1))])
        new = next(o for o in kinds("caption") if o["text"] == "see you tomorrow")
        check("a new caption can be put somewhere straight away", new.get("place") == {"x": 0.5, "y": 0.15, "scale": 1.0},
              json.dumps(new.get("place")))
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)

        t = chat("script chapter titles", [op(op="edit_overlay", overlay="all_titles",
                                              placement=placement(title_look="script"))])
        check("the chapter title takes the look; the plain title has none to take",
              kinds("heading")[0]["look"] == "script" and "look" not in kinds("title")[0] and not t.skipped,
              str(t.skipped))
        check("said as a change of style", any(l["text"].startswith("Changed the style of the chapter title")
                                               for l in t.lines), json.dumps([l["text"] for l in t.lines]))

        caps = [o["id"] for o in kinds("caption")]
        got = llm.expand([op(op="drop_overlay", overlay=caps[0]),
                          op(op="add_overlay", kind="caption", text="new one", shot=bd.key(shots[2])),
                          op(op="edit_overlay", overlay="all_captions", placement=placement(size="s"))], A.SESSION.board)
        check("one answer reads as it goes: the dropped caption isn't edited, the added one is sized too",
              [g["overlay"] for g in got if g["op"] == "edit_overlay"] == caps[1:]
              and next(g for g in got if g["op"] == "add_overlay").get("size") == "S", json.dumps(got)[:400])
        got = llm.expand([op(op="add_overlay", kind="caption", text="x", shot=bd.key(shots[2]),
                             placement=placement(mode="set", x=-1, y=0.15, scale=-1)),
                          op(op="edit_overlay", overlay="all_captions", placement=placement(mode="usual"))],
                         A.SESSION.board)
        check("all back to their usual spot, the one added in the same answer too", "place" not in got[0], json.dumps(got[0]))
        t = chat("lowercase every caption", [op(op="edit_overlay", overlay="all_captions", text="paris")])
        check("words for every caption at once: says why it couldn't", t.skipped
              == ["every one of the captions at once can only be moved, sized or removed"], str(t.skipped))
        first_beat = next(o["anchor"] for o in kinds("caption") if o["anchor"]["to"] == "shot")
        t = chat("cut the opening, smaller captions", [op(op="drop_beat", beat=beats[0]),
                                                      op(op="edit_overlay", overlay="all_captions", placement=placement(size="s"))])
        check("a part cut in the same answer takes its captions with it, no false Skipped",
              not t.skipped and all(o["size"] == "S" for o in kinds("caption")), str(t.skipped) + json.dumps(first_beat))
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)
        gone = [o["id"] for o in kinds("part", "caption") if o["anchor"]["id"] == beats[0]
                or o["anchor"]["id"] in {bd.key(x) for x in s.board["beats"][0]["shots"]}]
        t = chat("cut the opening and its words", [op(op="drop_beat", beat=beats[0]),
                                                  *[op(op="drop_overlay", overlay=i) for i in gone]])
        check("words removed along with their part in the same answer aren't said as Skipped",
              gone and not t.skipped and not any(o["id"] in gone for o in A.SESSION.board["overlays"]),
              str(t.skipped) + str(gone))
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)
        import time
        many = [op(op="edit_overlay", overlay=o["id"], placement=placement(size="l" if n % 2 else "s"))
                for n in range(25) for o in kinds("caption")]
        t0 = time.perf_counter()
        got = llm.expand(many, A.SESSION.board, cat, PROPOSALS)
        took = time.perf_counter() - t0
        check("a long answer (100 edits) is read in order quickly", len(got) == 100 and took < 1.0, f"{took:.2f}s")
        A.SESSION.add({"kind": "direct", "text": "red edge", "ops": [
            {"op": "overlay_style", "template": None, "outline": {"color": "#ff0000", "width": 0.2}}]}, cat, lambda d: PROPOSALS)
        t = chat("the time story, red outline", [op(op="choose_option", option="time"), op(op="caption_style", captions=captions(
            outline={"set": "on", "color": "#ff0000", "width": 0.2}))])
        check("a story chosen in the same answer starts clean, and the outline lands on it",
              not t.skipped and style().get("outline") == {"color": "#ff0000", "width": 0.2}, str(t.skipped))
        t = chat("the time story, no captions", [op(op="choose_option", option="time"),
                                                op(op="drop_overlay", overlay="all_captions")])
        check("and has no captions to remove", t.skipped == ["there are no captions in this edit"], str(t.skipped))
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)
        A.SESSION.toggle(A.SESSION.turns[-2].id, cat, lambda d: PROPOSALS)
        check("undone, the words are back", len(kinds("caption")) == 4, str(len(kinds("caption"))))
        t = chat("no chapter titles", [op(op="drop_overlay", overlay="all_titles")])
        check("every chapter title removed at once, one undoable turn", not kinds("heading") and not t.skipped
              and kinds("title"), str(t.skipped))
        A.SESSION.toggle(t.id, cat, lambda d: PROPOSALS)
        check("Undo brings it back", len(kinds("heading")) == 1)
        try:
            ov.edit(A.SESSION.board, {"overlay": "all_captions"})
            said_some = ""
        except ov.OverlayError as e:
            said_some = str(e)
        check("with captions there, it never claims there are none", "no captions" not in said_some and said_some, said_some)
        check("every-title edit with none of them in the edit says so", llm.expand(
            [op(op="edit_overlay", overlay="all_titles", placement=placement(size="L"))], {"overlays": []})
            == [{"op": "edit_overlay", "overlay": "all_titles"}])
        try:
            ov.edit({"overlays": []}, {"overlay": "all_titles"})
            said_none = ""
        except ov.OverlayError as e:
            said_none = str(e)
        check("in words", said_none == "there are no chapter titles in this edit", said_none)

        print("the paused box proposes the same")
        at = timeline.layout(A.SESSION.board)[0]["seq_start"] + 0.3
        info = A.api_moment(A.MomentReq(t=at))
        replies.append(answer([op(op="edit_overlay", overlay="all_captions", placement=placement(size="S")),
                               op(op="caption_style", captions=captions(font="caveat"))]))
        n = len(A.SESSION.turns)
        out = A.api_moment_chat(A.MomentReq(t=at, message="smaller, handwriting", ai_ok=info["estimate"]["usd"][1]))
        check("one edit per caption and the overlay_style op, nothing applied yet",
              [o["op"] for o in out["ops"]] == ["edit_overlay"] * 4 + ["overlay_style"]
              and out["ops"][-1].get("typeface") == "caveat" and len(A.SESSION.turns) == n, json.dumps(out["ops"])[:300])
        check("its preview is computed, a resize said as one", out["preview"]
              and "Changed the size of 4 captions" in out["preview"]["lines"], json.dumps(out["preview"]))

        print("with a look")
        A.SESSION.add({"kind": "direct", "text": "cozy", "ops": [{"op": "set_look", "look": "cozy"}]}, cat, lambda d: PROPOSALS)
        t = chat("captions at the bottom", [op(op="caption_style", captions=captions(position="bottom"))])
        said = [l["text"] for l in t.lines]
        check("where captions sit, without claiming the words follow the look again",
              not any("follow" in x for x in said) and said, json.dumps(said))

        print("before there is an edit")
        whole, A.SESSION = A.SESSION, bd.Session()
        A.SESSION.add({"kind": "chat", "text": "a day in Tokyo", "ops": [], "direction": {"text": "a day in Tokyo"}},
                      cat, lambda d: PROPOSALS)
        remembered = defaults.get().get("caption_template")
        t = chat("retro captions", [op(op="caption_style", captions=captions(word_art="retro"))])
        check("a look that couldn't land isn't remembered for the next video", t.skipped
              and defaults.get().get("caption_template") == remembered, json.dumps(defaults.get()))
        A.SESSION = whole
    finally:
        oai._post = real_post
        oai.switch(False)
        os.environ["OPENAI_API_KEY"] = ""

    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
