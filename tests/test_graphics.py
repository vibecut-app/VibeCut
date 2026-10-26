"""Graphic animations: pieces drawn over the video, as edits like any other.

- Each piece goes on where it hangs (the whole edit, a part, the shot under
  the playhead, or from here to the end of the part) and starts with words
  the edit already knows: the video's name and days, the part's title and
  number, the date it was filmed. Nothing is made up.
- Edits change exactly what they say (words, colour, sticker, size, place,
  length, timing), wrong values are refused in words, and every turn undoes.
- A graphic goes with what it hangs off, like a caption; captions never see
  the graphics, and the graphics never see the captions.
- What a piece needs to be true is checked before it's offered: a route
  needs two places with the phone's location, a clock a recording time.
- What the browser draws follows the edit as it stands: the beat under the
  stickers, the camcorder's clock as filmed shot by shot, the clock's time,
  the route's stops on a little map and the one it's at.
- Through the API a tile is one undoable turn, refused with the reason when
  it can't go on; My resources keeps one and puts it back at the playhead.

    python tests/test_graphics.py
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from datetime import datetime

if __name__ == "__main__":
    os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-graphics-")
os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-graphics-"))
os.environ["VIBECUT_EXPORTS"] = os.path.join(os.environ["VIBECUT_CACHE"], "out")
os.environ.setdefault("VIBECUT_BED", "0")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ.pop("VIBECUT_PUBLIC", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_board import CLIPS, PROPOSALS, session  # noqa: E402
from web.backend import board as bd  # noqa: E402
from web.backend import graphics as gx  # noqa: E402
from web.backend import overlays as ov  # noqa: E402

failures: list[str] = []
# the test edit: Morning (hotel, 3 shots of 12 s), Market (4), Temple (3), Dinner (3)
MARKET_AT = 36.0 + 5.0      # 5 s into the market part


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def apply(b: dict, cat, ops: list[dict]) -> dict:
    n = iter(range(1, 1000))
    for op in ops:
        b, _ = bd.apply(b, op, cat, PROPOSALS, lambda: f"o{next(n)}")
    return b


def placed_clips() -> list[dict]:
    """The same day with the phone's location: hotel and temple a few km
    apart, the market and dinner next to them (one stop each)."""
    where = {"hotel0000001": [35.6595, 139.7005], "market000001": [35.6654, 139.7707],
             "temple000001": [35.7148, 139.7967], "dinner000001": [35.6600, 139.7010]}
    out = copy.deepcopy(CLIPS)
    for c in out:
        c["gps"] = where.get(c["id"])
    return out


def main() -> int:
    ops_and_words()
    edits()
    undo_and_prune()
    what_can_show()
    what_is_drawn()
    through_api()
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


def ops_and_words() -> None:
    print("added where it hangs, with words from the edit")
    s, cat = session()
    b = copy.deepcopy(s.board)
    adds = [gx.op_for(p, b, cat, MARKET_AT, "Tokyo trip") for p in ("title", "chapter", "pin", "camcorder", "progress")]
    for k, op in enumerate(adds):
        op["id"] = f"g{k}"
    b = apply(b, cat, adds)
    g = {x["piece"]: x for x in b["graphics"]}
    check("title: the whole edit, at the playhead", g["title"]["anchor"] == {"to": "edit"} and g["title"]["at"] == MARKET_AT,
          str(g["title"]["anchor"]))
    check("title: the video's name over the day it was filmed",
          g["title"]["text"] == "Tokyo trip" and g["title"]["sub"] == "May 2, 2026", f"{g['title']['text']} / {g['title']['sub']}")
    check("chapter opener: opens the part it's in", g["chapter"]["anchor"]["to"] == "beat" and g["chapter"]["at"] == 0.0
          and g["chapter"]["text"] == "Market" and g["chapter"]["sub"] == "02", f"{g['chapter']['text']} {g['chapter']['sub']}")
    check("pin: the shot under the playhead; no place known -> the part's name",
          g["pin"]["anchor"]["to"] == "shot" and g["pin"]["text"] == "Market", g["pin"]["text"])
    check("camcorder: from here to the end of the part, dated as filmed",
          g["camcorder"]["anchor"]["to"] == "beat" and abs(g["camcorder"]["at"] - 5.0) < 1e-6 and g["camcorder"]["dur"] is None
          and g["camcorder"]["text"] == "MAY 02 2026", f"{g['camcorder']['anchor']} +{g['camcorder']['at']} {g['camcorder']['text']}")
    check("progress bar: the whole video from its start", g["progress"]["at"] == 0.0 and g["progress"]["dur"] is None)
    r = {x["piece"]: x for x in ov.resolve(b, b["graphics"])}
    check("the camcorder runs to the end of the market part", abs(r["camcorder"]["shown_end"] - 84.0) < 1e-6,
          str(r["camcorder"]["shown_end"]))
    check("the progress bar runs the whole video", abs(r["progress"]["shown_end"] - 156.0) < 1e-6, str(r["progress"]["shown_end"]))
    w = gx.words("title", b, cat, 0.0, "May 2")
    weekday = f"{datetime(2026, 5, 2):%A}"
    check("a video named for its day: the day stays the title, the weekday goes above",
          w == {"text": "May 2", "sub": weekday}, str(w))
    check("an unknown piece is refused", _raises(lambda: gx.op_for("confetti", b, cat, 0.0, "x")))
    check("captions don't see the graphics", ov.resolve(b) == [] and not b.get("overlays"))
    lines = [x["text"] for x in gx.describe(s.board, b)]
    check("each one added is said", len(lines) == 5 and all(x.startswith("Added the") for x in lines), str(lines[:2]))


def edits() -> None:
    print("edits change what they say")
    s, cat = session()
    b = apply(copy.deepcopy(s.board), cat, [{"op": "add_graphic", "id": "gs", "piece": "stickers", "start": 2.0},
                                            {"op": "add_graphic", "id": "gt", "piece": "title", "start": 0.0, "text": "Hi"}])
    g = next(x for x in b["graphics"] if x["id"] == "gs")
    check("a sticker starts as a heart", g["sticker"] == "heart")
    b2 = apply(copy.deepcopy(b), cat, [{"op": "edit_graphic", "graphic": "gs", "sticker": "star", "tint": "#FFCC00", "size": 9,
                                         "place": {"x": 0.2, "y": 0.3, "scale": 1}, "dur": 4.5}])
    g2 = next(x for x in b2["graphics"] if x["id"] == "gs")
    check("sticker, colour, size (capped), place and length changed",
          g2["sticker"] == "star" and g2["tint"] == "#ffcc00" and g2["size"] == ov.SCALE_MAX and g2["place"]["x"] == 0.2
          and g2["dur"] == 4.5, str({k: g2.get(k) for k in ("sticker", "tint", "size", "place", "dur")}))
    other = next(x for x in b2["graphics"] if x["id"] == "gt")
    check("the other graphic is untouched", other == next(x for x in b["graphics"] if x["id"] == "gt"))
    for name, op in [("a sticker on a title", {"graphic": "gt", "sticker": "star"}),
                     ("a sticker that isn't one", {"graphic": "gs", "sticker": "dragon"}),
                     ("a colour that isn't one", {"graphic": "gs", "tint": "pinkish"}),
                     ("a place off the picture", {"graphic": "gs", "place": {"x": 1.4, "y": 0.5}}),
                     ("too short", {"graphic": "gs", "dur": 0.1}),
                     ("nothing to change", {"graphic": "gs"}),
                     ("a graphic that isn't there", {"graphic": "nope", "text": "x"})]:
        check(f"refused: {name}", _raises(lambda op=op: apply(copy.deepcopy(b), cat, [{"op": "edit_graphic", **op}])))
    b3 = apply(copy.deepcopy(b), cat, [{"op": "edit_graphic", "graphic": "gs", "start": MARKET_AT}])
    r = next(x for x in ov.resolve(b3, b3["graphics"]) if x["id"] == "gs")
    check("moved on the timeline: re-anchored where it landed", abs(r["start"] - MARKET_AT) < 1e-3
          and r["anchor"]["id"].startswith("market"), f"{r['start']} on {r['anchor']}")
    text = " ".join(x["text"] for x in gx.describe(b, b2))
    check("the change is said in words", "sticker" in text and "colour" in text and "size" in text, text)


def undo_and_prune() -> None:
    print("undo, and going with what it hangs off")
    s, cat = session()
    mk = lambda d: PROPOSALS  # noqa: E731
    t = s.add({"kind": "direct", "text": "add", "ops": [{"op": "add_graphic", "id": "gc", "piece": "chapter", "start": MARKET_AT}]}, cat, mk)
    check("added as one turn", any(g["id"] == "gc" for g in s.board.get("graphics", [])))
    s.toggle(t.id, cat, mk)
    check("undone: gone", not s.board.get("graphics"))
    s.toggle(t.id, cat, mk)
    check("redone: back", any(g["id"] == "gc" for g in s.board.get("graphics", [])))
    beat = next(x["anchor"]["id"] for x in s.board["graphics"] if x["id"] == "gc")
    s.add({"kind": "direct", "text": "cut the market", "ops": [{"op": "drop_beat", "beat": beat}]}, cat, mk)
    check("its part removed: the chapter opener goes too", not s.board.get("graphics"))


def what_can_show() -> None:
    print("what a piece needs to be true")
    s, cat = session()
    c = gx.can(s.board, cat)
    check("no locations: the route says why", c["route"] and "two places" in c["route"], str(c["route"]))
    check("recording times known: the clock is offered", c["clock"] is None)
    check("before there's an edit, nothing is offered", all(v for v in gx.can(None, cat).values()))
    cat2 = bd.Catalog.from_clips(placed_clips())
    check("two places or more: the route is offered", gx.can(s.board, cat2)["route"] is None)
    st = gx.stops(s.board, cat2)
    check("dinner next to the hotel is the same stop", len(st) == 3, str([x["start"] for x in st]))
    undated = copy.deepcopy(CLIPS)
    for x in undated:
        x["capture_time"] = None
    cat3 = bd.Catalog.from_clips(undated)
    check("no recording times: the clock says why", gx.can(s.board, cat3)["clock"] == "Needs clips with a recording time")
    check("and the route can't be added through op_for", _raises(lambda: gx.op_for("route", s.board, cat, 0.0, "x")))


def what_is_drawn() -> None:
    print("what the browser draws follows the edit")
    s, cat = session()
    cat2 = bd.Catalog.from_clips(placed_clips())
    b = apply(copy.deepcopy(s.board), cat2, [
        {"op": "add_graphic", "id": "g1", "piece": "stickers", "start": 2.0},
        {"op": "add_graphic", "id": "g2", "piece": "camcorder", "start": 30.0},
        {"op": "add_graphic", "id": "g3", "piece": "clock", "start": MARKET_AT},
        {"op": "add_graphic", "id": "g4", "piece": "route", "start": 100.0},
    ])
    grid = {"bpm": 96.0, "phase": 0.12}
    p = gx.public(b, cat2, grid)
    g = {x["piece"]: x for x in p["items"]}
    check("stickers bounce on the music's beat", g["stickers"]["beat"] == grid)
    check("no music: a steady pulse", {x["piece"]: x for x in gx.public(b, cat2, None)["items"]}["stickers"]["beat"] is None)
    times = g["camcorder"]["times"]
    check("camcorder: the clock as filmed for every shot it's over", len(times) == 1 and times[0][0] == 24.0
          and abs(times[0][2] - (8 * 3600 + 24)) < 1e-6, str(times))
    check("the clock reads when the market was filmed", g["clock"]["clock"] == round((10 * 3600 + 5) / 60, 2),
          str(g["clock"]["clock"]))
    xs = [(x["x"], x["y"]) for x in g["route"]["stops"]]
    check("the route's stops sit on a little map", len(xs) == 3 and all(0 <= a <= 1 and 0 <= c <= 1 for a, c in xs), str(xs))
    check("at 1:40 the route is at the temple (third stop)", g["route"]["here"] == 2, str(g["route"]["here"]))
    check("its own colour until one is picked", g["route"]["tint"] == gx.PIECES["route"]["tint"])
    b2 = apply(copy.deepcopy(b), cat2, [{"op": "drop_shot", "shot": "hotel0000001:0"}])
    times2 = {x["piece"]: x for x in gx.public(b2, cat2, grid)["items"]}["camcorder"]["times"]
    check("a cut before it: the camcorder's clock follows", times2 and times2[0][0] == 12.0, str(times2))


def through_api() -> None:
    print("through the API")
    from fastapi.testclient import TestClient
    from web.backend import app as A
    from web.backend import projects as pj
    from web.backend import resources
    s, cat = session()
    A.SESSION = s
    A.CATALOG["cat"] = cat
    A._make_proposals = lambda d: PROPOSALS
    A._session = lambda: {"turns": len(A.SESSION.turns)}
    A._save = lambda: None
    A.PROJECT["p"] = pj.Project(id="art", name="Tokyo trip")
    A.CLIPS.clear()
    c = TestClient(A.app)   # no lifespan: nothing opened from disk

    turns = len(A.SESSION.turns)
    r = c.post("/api/graphics", json={"piece": "title", "t": 3.0})
    added = r.json().get("added", "")
    check("a tile is one turn, with the new graphic's id", r.status_code == 200 and added.startswith("g")
          and len(A.SESSION.turns) == turns + 1, r.text)
    g = next(x for x in A.SESSION.board["graphics"] if x["id"] == added)
    check("filled from the edit", g["text"] == "Tokyo trip" and g["sub"] == "May 2, 2026", f"{g['text']} / {g['sub']}")
    r = c.post("/api/graphics", json={"piece": "route", "t": 3.0})
    check("a route with no places: refused with the reason, no turn", r.status_code == 409 and "two places" in r.json()["detail"]
          and len(A.SESSION.turns) == turns + 1, r.text)
    r = c.post("/api/graphics", json={"piece": "stickers", "t": 3.0, "sticker": "bolt", "tint": "#00ff88"})
    sid = r.json()["added"]
    g = next(x for x in A.SESSION.board["graphics"] if x["id"] == sid)
    check("picked sticker and colour go on with it", g["sticker"] == "bolt" and g["tint"] == "#00ff88", str(g))
    c.post("/api/ops", json={"ops": [{"op": "edit_graphic", "graphic": sid, "size": 1.5}], "label": "bigger"})
    A.SESSION.toggle(A.SESSION.turns[-1].id, A.CATALOG["cat"], A._make_proposals)
    g = next(x for x in A.SESSION.board["graphics"] if x["id"] == sid)
    check("an edit undoes", g.get("size", 1) == 1, str(g.get("size")))

    r = c.post("/api/resources", json={"kind": "graphic"})
    check("nothing clicked: saving says what to do first", r.status_code == 409 and "click a graphic" in r.json()["detail"], r.text)
    r = c.post("/api/resources", json={"kind": "graphic", "graphic": sid, "name": "Bolt"})
    check("kept: the piece as dressed, not its words", r.status_code == 200
          and r.json()["item"]["value"] == {"piece": "stickers", "tint": "#00ff88", "sticker": "bolt"}, r.text)
    rid = r.json()["item"]["id"]
    turns = len(A.SESSION.turns)
    n = len(A.SESSION.board["graphics"])
    r = c.post(f"/api/resources/{rid}/use", json={"t": MARKET_AT})
    new = [x for x in A.SESSION.board["graphics"] if x["id"] not in {sid, added}]
    check("used: on the video at the playhead, one turn", r.status_code == 200 and len(A.SESSION.board["graphics"]) == n + 1
          and len(A.SESSION.turns) == turns + 1 and new and new[0]["sticker"] == "bolt"
          and new[0]["anchor"]["id"].startswith("market"), r.text)
    c.delete(f"/api/resources/{rid}")
    check("graphics stay out of the resources' other kinds", "graphic" in resources.KINDS)


def _raises(f) -> bool:
    try:
        f()
    except Exception:  # noqa: BLE001 -- refused, in whatever words
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
