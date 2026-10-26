"""Words on screen are part of the edit: do they behave like it?

Overlays are ops in the same turn log as cuts. These checks pin down what
that has to mean in practice, without a browser:

- an overlay follows what it hangs off (a part moves -> its label moves;
  the edit gets shorter -> the end card stays at the end; a shot goes ->
  its name tag goes, and the diff says so);
- a time on the timeline is recorded as an anchor, so undoing an earlier
  turn can't make a later overlay land somewhere else;
- suggestions only fill what's missing and never invent copy;
- each check separates two fixtures that differ in exactly one respect,
  and reports the number it was built on.

    python tests/test_overlays.py
"""

from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_board import CLIPS, PROPOSALS, session  # noqa: E402
from web.backend import board as bd  # noqa: E402
from web.backend import overlays as ov  # noqa: E402

mk = lambda d: PROPOSALS  # noqa: E731


def at(s: bd.Session, oid: str) -> dict:
    return next(o for o in ov.resolve(s.board) if o["id"] == oid)


def add(s, cat, **op):
    return s.add({"kind": "direct", "text": "overlay", "ops": [{"op": "add_overlay", **op}]}, cat, mk)


def rules(board, cat=None, oid=None) -> dict:
    return {f["rule"]: f for f in ov.check(board, cat) if oid is None or f["overlay"] == oid}


def main() -> int:
    failures = []

    def check(name: str, cond: bool, got: str) -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}: {got}")
        if not cond:
            failures.append(name)

    # The fixture board: Morning t1 (0-36), Market t2 (36-84), Temple t3 (84-120), Dinner t4 (120-156).
    s, cat = session()
    t = add(s, cat, kind="part", text="Market", beat="t2", at=0.5)
    oid = s.board["overlays"][0]["id"]
    check("a part label starts where its part does", at(s, oid)["start"] == 36.5, str(at(s, oid)["start"]))
    check("adding it reads as one line", [l["text"] for l in t.lines] == ["Added the part label “Market”"],
          str([l["text"] for l in t.lines]))
    s.add({"kind": "direct", "text": "move", "ops": [{"op": "move_beat", "beat": "t2", "to_index": 3}]}, cat, mk)
    check("…and moves with it", at(s, oid)["start"] == 108.5, str(at(s, oid)["start"]))
    t = s.add({"kind": "direct", "text": "drop", "ops": [{"op": "drop_beat", "beat": "t2"}]}, cat, mk)
    check("…and goes with it, and the diff says so",
          "overlays" not in s.board and any("with what it was on" in l["text"] for l in t.lines),
          " | ".join(l["text"] for l in t.lines))

    # End card stays at the end when the edit gets shorter.
    s, cat = session()
    add(s, cat, kind="end", text="Thanks for watching")
    oid = s.board["overlays"][0]["id"]
    e0 = at(s, oid)
    s.add({"kind": "direct", "text": "lose dinner", "ops": [{"op": "drop_beat", "beat": "t4"}]}, cat, mk)
    e1 = at(s, oid)
    check("the end card ends where the edit ends, before and after a cut",
          (e0["start"], e0["end"]) == (153.0, 156.0) and (e1["start"], e1["end"]) == (117.0, 120.0),
          f"{e0['start']}–{e0['end']} -> {e1['start']}–{e1['end']}")

    # A timeline time becomes an anchor; undoing an earlier turn can't move it.
    s, cat = session()
    a = s.add({"kind": "direct", "text": "shorter morning", "ops": [
        {"op": "trim", "shot": "hotel0000001:0", "edge": "out", "to": 6.0}]}, cat, mk)  # edit now 150s
    t = add(s, cat, kind="name", text="Mika", start=40.0)   # 40s = temple? no: market:0 starts at 30
    rec = t.ops[0]
    check("a dropped time is recorded as an anchor, not a time",
          "start" not in rec and rec["anchor"] == {"to": "shot", "id": "market000001:0"} and rec["at"] == 10.0,
          f"{rec.get('anchor')} +{rec.get('at')}")
    oid = rec["id"]
    s.toggle(a.id, cat, mk)
    check("undoing the earlier trim keeps it on the same frame of the same shot",
          at(s, oid)["start"] == 46.0, f"{at(s, oid)['start']}s (shot now starts at 36)")

    # Timeline move re-anchors; edit changes are one diff line.
    t = s.add({"kind": "direct", "text": "move", "ops": [{"op": "edit_overlay", "overlay": oid, "start": 90.0,
                                                           "text": "Mika & Jun"}]}, cat, mk)
    check("moving on the timeline re-anchors to what's under it",
          t.ops[0]["anchor"] == {"to": "shot", "id": "temple000001:0"} and at(s, oid)["start"] == 90.0,
          f"{t.ops[0]['anchor']} -> {at(s, oid)['start']}")
    check("an edit reads as what changed", [l["text"] for l in t.lines] ==
          ["Changed the words and timing of the name tag “Mika & Jun”"], str([l["text"] for l in t.lines]))
    snap = copy.deepcopy(s.board)
    s.replay(cat, mk)
    check("replay with overlays is exact", snap == s.board, "equal")

    # Style is one per video.
    t = s.add({"kind": "direct", "text": "style", "ops": [{"op": "overlay_style", "font": "Editorial"}]}, cat, mk)
    check("one style for the whole video", ov.style_of(s.board)["font"] == "Editorial" and t.lines[0]["text"] ==
          "Text style: font Editorial", t.lines[0]["text"])
    t = s.add({"kind": "direct", "text": "bad", "ops": [{"op": "overlay_style", "font": "Comic Sans"}]}, cat, mk)
    check("an unknown font is refused, not guessed", bool(t.skipped), t.skipped[0] if t.skipped else "accepted")

    # Suggestions: fill only what's missing, never placeholder copy.
    s, cat = session()
    ops, notes = ov.suggest(s.board, cat, {}, "Tokyo in a day")
    kinds = sorted(o["kind"] for o in ops)
    check("suggests a title, labels for parts 2–4 and an end card — no name without a name",
          kinds == ["end", "part", "part", "part", "title"] and any("name" in n for n in notes),
          f"{kinds}; {notes}")
    s.add({"kind": "direct", "text": "titles", "ops": ops}, cat, mk)
    again, _ = ov.suggest(s.board, cat, {}, "Tokyo in a day")
    check("suggesting again adds nothing that's already there", again == [], str(again))

    faced0 = copy.deepcopy(CLIPS)
    faced0[0]["shots"][0]["face_area"] = 0.1   # talking to camera in the very first shot
    cat0 = bd.Catalog.from_clips(faced0)
    s, _ = session()
    ops, _ = ov.suggest(s.board, cat0, {"name": "Mika", "handle": "mika"}, "Tokyo")
    s.add({"kind": "direct", "text": "titles", "ops": ops}, cat0, mk)
    tn = {o["kind"]: o for o in ov.resolve(s.board)}
    check("a suggested name tag waits for the opening title to go, and gets its @",
          tn["name"]["start"] >= tn["title"]["end"] and tn["name"]["sub"] == "@mika"
          and "collides" not in rules(s.board, cat0),
          f"title {tn['title']['start']}–{tn['title']['end']}, name from {tn['name']['start']}")

    s, cat = session()
    t = add(s, cat, kind="caption", text="We made it", beat="t2", dur=None)
    cap = ov.resolve(s.board)[0]
    check("a caption with no length fills its part", (cap["start"], cap["end"]) == (36.0, 84.0), f"{cap['start']}–{cap['end']}")
    s.add({"kind": "direct", "text": "len", "ops": [{"op": "edit_overlay", "overlay": cap["id"], "dur": 2.5}]}, cat, mk)
    t = s.add({"kind": "direct", "text": "fill", "ops": [{"op": "edit_overlay", "overlay": cap["id"], "dur": None}]}, cat, mk)
    check("…and 'whole part' can be turned back on", not t.skipped and ov.resolve(s.board)[0]["end"] == 84.0,
          t.skipped[0] if t.skipped else str(ov.resolve(s.board)[0]["end"]))

    # --- checks: each separates two fixtures that differ in one respect ---
    def one(**op):
        s, cat = session()
        add(s, cat, **op)
        return s, cat, s.board["overlays"][0]["id"]

    s1, c1, o1 = one(kind="title", text="A long opening title for the whole trip", beat="t1", dur=1.0)
    s2, c2, o2 = one(kind="title", text="A long opening title for the whole trip", beat="t1", dur=4.0)
    r1, r2 = rules(s1.board, c1, o1), rules(s2.board, c2, o2)
    check("read_time: 1 s fires, 4 s doesn't, and the number is the ratio",
          "read_time" in r1 and "read_time" not in r2 and abs(r1["read_time"]["value"] - 1.0 / ov.read_time(
              "A long opening title for the whole trip ")) < 0.01,
          f"{r1.get('read_time', {}).get('value')} ({r1.get('read_time', {}).get('verdict')})")

    s1, c1, o1 = one(kind="end", text="Bye")
    s1.board["overlays"][0]["anchor"], s1.board["overlays"][0]["at"] = {"to": "edit"}, 155.0
    s2, c2, o2 = one(kind="end", text="Bye")
    check("cut_off: 2 s past the end fires with the seconds lost; at the end doesn't",
          abs(rules(s1.board)["cut_off"]["value"] - 2.0) < 0.01 and "cut_off" not in rules(s2.board),
          str(rules(s1.board).get("cut_off", {}).get("value")))

    def two(pos_b):
        s, cat = session()
        add(s, cat, kind="title", text="Tokyo", beat="t1", pos="center")
        add(s, cat, kind="part", text="Morning", beat="t1", at=1.0, pos=pos_b)
        return s
    check("collides: same spot fires with the overlap in seconds; different spots don't",
          abs(rules(two("center").board)["collides"]["value"] - 2.0) < 0.01
          and "collides" not in rules(two("bottom-left").board),
          str(rules(two("center").board).get("collides", {}).get("value")))

    faced = copy.deepcopy(CLIPS)
    faced[2]["shots"][0]["face_area"] = 0.12   # someone talking to camera in temple:0
    cat_face = bd.Catalog.from_clips(faced)
    s, cat = session()
    add(s, cat, kind="caption", text="We made it", beat="t3")
    s.add({"kind": "direct", "text": "mid", "ops": [{"op": "overlay_style", "captions": "center"}]}, cat, mk)
    mid_face = rules(s.board, cat_face).get("over_face")
    mid_none = rules(s.board, cat).get("over_face")
    s.add({"kind": "direct", "text": "low", "ops": [{"op": "overlay_style", "captions": "bottom"}]}, cat, mk)
    low_face = rules(s.board, cat_face).get("over_face")
    check("over_face: centre caption over a talking face warns (from a still); no face or low caption doesn't",
          mid_face is not None and mid_face["basis"] == "still" and mid_face["verdict"] == "warn"
          and mid_none is None and low_face is None,
          f"{mid_face and (mid_face['value'], mid_face['basis'])}")

    # Dragged by hand onto the face: still only a warning, never moved back.
    s.add({"kind": "direct", "text": "drag", "ops": [{"op": "edit_overlay", "overlay": cap["id"],
                                                      "place": {"x": 0.5, "y": 0.5, "scale": 9}}]}, cat_face, mk)
    placed = next(o for o in s.board["overlays"] if o["id"] == cap["id"])
    dragged = rules(s.board, cat_face).get("over_face")
    check("drag: kept where it was dropped, size clamped, still warned over a face, never moved",
          placed["place"] == {"x": 0.5, "y": 0.5, "scale": ov.SCALE_MAX} and dragged is not None
          and dragged["verdict"] == "warn", f"{placed.get('place')} {dragged}")
    t = s.add({"kind": "direct", "text": "reset", "ops": [{"op": "edit_overlay", "overlay": cap["id"], "place": None}]}, cat_face, mk)
    check("drag: reset puts it back in the caption line",
          next(o for o in s.board["overlays"] if o["id"] == cap["id"]).get("place") is None, "")
    s.toggle(t.id, cat_face, mk)
    check("drag: undo brings the hand placement back",
          (next(o for o in s.board["overlays"] if o["id"] == cap["id"]).get("place") or {}).get("x") == 0.5, "")
    try:
        ov.clean_fields({"place": {"x": 1.4, "y": 0.5}}, "caption")
        bad = False
    except ov.OverlayError:
        bad = True
    check("drag: off the picture is refused", bad, "")

    # A title and the line under it are a group, each line tuned on its own
    # (sarah, 2026-10-20): one line's look changes that line only, merges
    # with what it had, undoes, and None puts it back to the group's.
    s, cat = session()
    add(s, cat, kind="title", text="heading in", sub="8:35 am · heading to class", beat="t1")
    oid = s.board["overlays"][0]["id"]
    one_line = lambda: next(o for o in s.board["overlays"] if o["id"] == oid).get("lines")  # noqa: E731
    t = s.add({"kind": "direct", "text": "line", "ops": [{"op": "edit_overlay", "overlay": oid,
               "lines": {"sub": {"text_color": "#ff3366", "scale": 1.4}}}]}, cat, mk)
    s.add({"kind": "direct", "text": "line", "ops": [{"op": "edit_overlay", "overlay": oid,
           "lines": {"sub": {"typeface": "anton", "dy": 0.05}}}]}, cat, mk)
    got = one_line()
    check("group: one line's look, merged, the other line untouched",
          got == {"sub": {"text_color": "#ff3366", "scale": 1.4, "typeface": "anton", "dy": 0.05}},
          str(got))
    check("group: the diff says the look changed", any("look" in l["text"] for l in t.lines), str([l["text"] for l in t.lines]))
    s.add({"kind": "direct", "text": "line", "ops": [{"op": "edit_overlay", "overlay": oid, "lines": {"sub": None}}]}, cat, mk)
    check("group: None puts the line back to the group's", one_line() is None, str(one_line()))
    for bad_lines in ({"under": {}}, {"sub": {"scale": 9}}, {"sub": {"text_color": "red"}}, {"sub": {"template": "bold"}}):
        try:
            ov.clean_fields({"lines": bad_lines}, "title")
            ok = False
        except ov.OverlayError:
            ok = True
        check(f"group: refused {bad_lines}", ok, "")

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
