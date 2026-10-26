"""My resources: what the creator saves comes back exactly as it was seen.

Each kind is saved off one edit and put on a second, plain edit, and the
second must end up with what the first had -- in the place it was put
(the clicked shot or cut, else everywhere) and nowhere else:

- caption look: the hand-picked fields (font, word art, colour, outline,
  shadow, background, weight) land as saved, and fields it didn't set go back
  to the look's own; the animation is its own resource and isn't touched;
- transition: at the clicked cut only, else at every cut;
- effect: on the clicked shot only, else on every shot;
- shot settings: the shot ends up with exactly the saved settings (an effect
  it had is gone); a held frame takes only what it can show;
- song: the track and where it starts, at the current levels, or the bed's
  when there was no music; a song no longer on the computer is refused.

Nothing to keep is refused in words (a plain cut, the look's own captions).
Saving the same thing twice is one entry; rename and delete stick; rows from
another computer's mirror are taken when newer, a deleted one removes it.
Through the API: this computer's own browser is signed in; anything relayed
(a tunnel, the public link) or VIBECUT_PUBLIC is signed out and sees no items
and can't save or use; using one is one undoable turn.

    python tests/test_resources.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

if __name__ == "__main__":
    os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-resources-")
os.environ["VIBECUT_EXPORTS"] = os.path.join(os.environ["VIBECUT_CACHE"], "out")
os.environ.setdefault("VIBECUT_BED", "0")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ.pop("VIBECUT_PUBLIC", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_board import PROPOSALS, session  # noqa: E402
from web.backend import audiomix  # noqa: E402
from web.backend import board as bd  # noqa: E402
from web.backend import cloud, resources  # noqa: E402

failures: list[str] = []
A1, A2, B1 = "hotel0000001:0", "hotel0000001:1", "market000001:1"


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def board() -> dict:
    s, _ = session()
    return copy.deepcopy(s.board)


CAT = session()[1]


def apply(b: dict, ops: list[dict]) -> dict:
    n = iter(range(1, 1000))
    for op in ops:
        b, _ = bd.apply(b, op, CAT, PROPOSALS, lambda: f"o{next(n)}")
    return b


def entry(b: dict, k: str) -> dict:
    beat, i = bd._where(b, k)
    return beat["shots"][i]


def fx_of(e: dict) -> dict:
    return {f: e[f] for f in bd.SHOT_FX if f in e}


def refused(fn) -> str | None:
    try:
        fn()
    except resources.ResourceError as e:
        return str(e)
    return None


def main() -> int:
    pushed: list[tuple] = []
    real_push = cloud.push
    cloud.push = lambda kind, key, value, at=None, wait=False: pushed.append((kind, key, value))
    try:
        unit(pushed)
        through_api()
    finally:
        cloud.push = real_push
    print()
    if failures:
        print(f"{len(failures)} failed: {failures}")
        return 1
    print("all passed")
    return 0


def unit(pushed: list) -> None:
    plain = board()
    print("nothing to keep is said, not saved")
    for kind in resources.KINDS:
        why = refused(lambda: resources.capture(kind, plain, shot=A1, after=A1))
        check(f"plain edit: no {kind} to keep", bool(why), why or "")
    check("no video: nothing to save", bool(refused(lambda: resources.capture("caption", None))))
    check("shot settings need a clicked shot", "click a shot" in (refused(lambda: resources.capture("shot", plain)) or ""))
    check("a shot that's gone is said", "any more" in (refused(lambda: resources.capture("shot", plain, shot="nope:9")) or ""))
    a = apply(board(), [{"op": "set_transition", "shot": A1, "kind": "cut"}])
    check("a plain cut is nothing to keep", bool(refused(lambda: resources.capture("transition", a, after=A1))))

    print("caption look")
    look = {"typeface": "montserrat", "template": "tape", "text_color": "#ffcc00",
            "outline": {"color": "#000000", "width": 0.12}, "thick": 0.05}
    a = apply(board(), [{"op": "overlay_style", **look, "enter": "pop"}])
    v = resources.capture("caption", a)
    check("only the hand-picked fields, not the animation", v == look, json.dumps(v))
    item = resources.add("caption", v)
    check("named from what it is", item["name"] == "Montserrat · Typed tape", item["name"])
    b = apply(board(), [{"op": "overlay_style", "template": "neon", "shadow": {"color": "#ffffff", "opacity": 0.5, "blur": 0.3, "dist": 0.1}, "enter": "type"}])
    ops, said = resources.ops_for(item, b)
    b = apply(b, ops)
    st = b["overlay_style"]
    check("lands exactly as saved", all(st.get(k) == look.get(k) for k in resources.CAPTION_KEYS),
          json.dumps({k: st.get(k) for k in resources.CAPTION_KEYS}))
    check("what it didn't set goes back to the look's own", st.get("shadow") is None)
    check("the animation is left alone", st.get("enter") == "type", str(st.get("enter")))
    check("the turn says it in words", "Montserrat" in said, said)

    print("animation")
    an = resources.add("animation", resources.capture("animation", a))
    check("named", an["name"] == "Pop", an["name"])
    b2 = apply(board(), [{"op": "overlay_style", "template": "neon", "enter": "type"}])
    b2 = apply(b2, resources.ops_for(an, b2)[0])
    check("only how the words arrive changes", b2["overlay_style"].get("enter") == "pop" and b2["overlay_style"].get("template") == "neon")

    print("transition")
    a = apply(board(), [{"op": "set_transition", "shot": A1, "kind": "slide_up", "dur": 0.7}])
    tr = resources.add("transition", resources.capture("transition", a, after=A1))
    check("named", tr["name"] == "Slide up · 0.7s", tr["name"])
    b = apply(board(), resources.ops_for(tr, board(), after=B1)[0])
    check("at the clicked cut", (b.get("picture_joins") or {}).get(B1) == {"kind": "slide_up", "dur": 0.7},
          json.dumps(b.get("picture_joins")))
    check("and nowhere else", len(b.get("picture_joins") or {}) == 1 and not b.get("picture_all"))
    b = apply(board(), resources.ops_for(tr, board())[0])
    check("no cut clicked: every cut", (b.get("picture_all") or {}).get("kind") == "slide_up", json.dumps(b.get("picture_all")))
    a = apply(board(), [{"op": "set_transition", "all": True, "kind": "blur", "dur": 0.4}])
    check("every cut's transition can be kept too", resources.capture("transition", a) == {"kind": "blur", "dur": 0.4})

    print("effect")
    a = apply(board(), [{"op": "set_shot", "shot": A1, "effect": "glitch", "effect_amount": 1.5}])
    ef = resources.add("effect", resources.capture("effect", a, shot=A1))
    check("named", ef["name"] == "Glitch · 150%", ef["name"])
    b = apply(board(), resources.ops_for(ef, board(), shot=B1)[0])
    on = [bd.key(e) for bt in b["beats"] for e in bt["shots"] if e.get("effect")]
    check("on the clicked shot only", on == [B1] and entry(b, B1)["effect_amount"] == 1.5, str(on))
    b = apply(board(), resources.ops_for(ef, board())[0])
    every = [e.get("effect") for bt in b["beats"] for e in bt["shots"]]
    check("no shot clicked: every shot", set(every) == {"glitch"}, str(set(every)))

    print("shot settings")
    a = apply(board(), [{"op": "set_shot", "shot": A1, "speed": 2.0, "reverse": True, "mirror": True, "rotate": 90, "gain": 0.5}])
    sh = resources.add("shot", resources.capture("shot", a, shot=A1))
    check("named from what it does", sh["name"] == "2×, backwards, turned 90°", sh["name"])
    b = apply(board(), [{"op": "set_shot", "shot": B1, "effect": "vhs", "fill": True}])
    b = apply(b, resources.ops_for(sh, b, shot=B1)[0])
    check("the shot has exactly the saved settings", fx_of(entry(b, B1)) == fx_of(entry(a, A1)),
          json.dumps(fx_of(entry(b, B1))))
    check("shot settings need a clicked shot to go on", bool(refused(lambda: resources.ops_for(sh, board()))))
    f = apply(board(), [{"op": "freeze_frame", "shot": B1, "at": 13.0, "dur": 2.0}])
    held = next(bd.key(e) for bt in f["beats"] for e in bt["shots"] if bd.is_freeze(e))
    f = apply(f, resources.ops_for(sh, f, shot=held)[0])
    e = entry(f, held)
    check("a held frame takes only what it can show", e.get("mirror") is True and e.get("rotate") == 90
          and "speed" not in e and "reverse" not in e, json.dumps(fx_of(e)))

    print("song")
    a = apply(board(), [{"op": "set_music", "track": "ov:abc", "in": 12.5, "gain": 0.3, "original": 0.4, "level": True}])
    so = resources.add("song", resources.capture("song", a, title_of=lambda t: "Golden Hour"))
    check("named by its title", so["name"] == "Golden Hour" and so["value"] == {"track": "ov:abc", "in": 12.5, "title": "Golden Hour"},
          json.dumps(so))
    b = apply(board(), resources.ops_for(so, board(), have_track=lambda t: True)[0])
    m = b["music"]
    check("no music before: the bed's levels", m["track"] == "ov:abc" and m["in"] == 12.5 and m["gain"] == audiomix.MUSIC_GAIN
          and m.get("level") is True, json.dumps(m))
    c = apply(board(), [{"op": "set_music", "track": "ov:old", "in": 3.0, "gain": 0.2, "original": 0.7, "volume": 1.5}])
    c = apply(c, resources.ops_for(so, c, have_track=lambda t: True)[0])
    check("music before: its levels kept, the song changed", c["music"]["track"] == "ov:abc" and c["music"]["in"] == 12.5
          and c["music"]["gain"] == 0.2 and c["music"]["original"] == 0.7 and c["music"]["volume"] == 1.5, json.dumps(c["music"]))
    check("a song that's gone is said", "any more" in (refused(lambda: resources.ops_for(so, board(), have_track=lambda t: False)) or ""))

    print("the folder")
    n = len(resources.all_items())
    again = resources.add("effect", {"effect": "glitch", "effect_amount": 1.5})
    check("saved twice: one entry", len(resources.all_items()) == n and again["id"] == ef["id"])
    check("moved to the top of its kind", [x["id"] for x in resources.all_items() if x["kind"] == "effect"][0] == ef["id"])
    kinds = [x["kind"] for x in resources.all_items()]
    check("kinds in folder order", kinds == sorted(kinds, key=resources.KINDS.index), str(kinds))
    resources.rename(ef["id"], "  My glitch  ")
    check("renamed", next(x for x in resources.all_items() if x["id"] == ef["id"])["name"] == "My glitch")
    check("a name is needed", bool(refused(lambda: resources.rename(ef["id"], "   "))))
    resources.remove(tr["id"])
    check("deleted", all(x["id"] != tr["id"] for x in resources.all_items()))
    check("kept on disk", json.loads(resources.FILE.read_text())["items"] and resources._read() == json.loads(resources.FILE.read_text())["items"])
    check("every change mirrored, a delete as deleted",
          ("resource", tr["id"], {"deleted": True}) in pushed and any(p[1] == ef["id"] and p[2]["name"] == "My glitch" for p in pushed))
    real_limit = resources.LIMIT
    resources.LIMIT = 2
    for x in (0.5, 0.75, 1.25):
        resources.add("effect", {"effect": "vhs", "effect_amount": x})
    vhs = [x["value"]["effect_amount"] for x in resources.all_items() if x["kind"] == "effect"]
    resources.LIMIT = real_limit
    check("past the limit the oldest of a kind go first", vhs == [1.25, 0.75], str(vhs))

    print("from another computer")
    have = next(x for x in resources.all_items() if x["kind"] == "song")
    new = {"id": "remote000001", "kind": "animation", "name": "Stamp", "value": {"enter": "stamp"}, "at": 1e10}
    resources.absorb([
        {"key": new["id"], "value": new, "at": 1e10},
        {"key": have["id"], "value": {**have, "name": "Older name"}, "at": have["at"] - 100},
        {"key": an["id"], "value": {"deleted": True}, "at": 1e10},
        {"key": "junk", "value": {"kind": "virus", "value": {}}, "at": 1e10},
    ])
    ids = {x["id"]: x for x in resources.all_items()}
    check("a newer one is taken", ids.get("remote000001", {}).get("name") == "Stamp")
    check("an older copy doesn't overwrite", ids[have["id"]]["name"] == have["name"])
    check("a deletion removes it", an["id"] not in ids)
    check("unknown kinds are ignored", "junk" not in ids)


def through_api() -> None:
    print("through the API")
    from fastapi.testclient import TestClient
    from web.backend import app as A
    from web.backend import projects as pj
    s, cat = session()
    A.SESSION = s
    A.CATALOG["cat"] = cat
    A._make_proposals = lambda d: PROPOSALS
    A._session = lambda: {"turns": len(A.SESSION.turns)}
    A._save = lambda: None
    A.PROJECT["p"] = pj.Project(id="res", name="Resources")
    c = TestClient(A.app)   # no lifespan: nothing opened from disk
    away = {"X-Forwarded-For": "203.0.113.9"}

    r = c.get("/api/resources").json()
    check("this computer's browser is signed in and sees its folder", r["signed_in"] and len(r["items"]) > 0
          and [k["id"] for k in r["kinds"]] == list(resources.KINDS))
    r = c.get("/api/resources", headers=away).json()
    check("relayed from elsewhere: signed out, nothing shown", r["signed_in"] is False and r["items"] == [])
    os.environ["VIBECUT_PUBLIC"] = "1"
    check("a public server is signed out", c.get("/api/resources").json()["signed_in"] is False)
    os.environ.pop("VIBECUT_PUBLIC")
    check("who: another host is a visitor", not resources.who("10.0.0.4", {})["signed_in"])
    r = c.get("/api/resources", headers={"x-vibecut-visitor": "1"}).json()
    check("the owner can see the folder as a visitor does", r["signed_in"] is False and r["items"] == [])

    c.post("/api/ops", json={"ops": [{"op": "set_shot", "shot": A2, "effect": "disco", "effect_amount": 0.5}], "label": "fx"})
    r = c.post("/api/resources", json={"kind": "effect", "shot": A2}, headers=away)
    check("signed out: Save leads to logging in", r.status_code == 401 and "log in" in r.json()["detail"], r.text)
    r = c.post("/api/resources", json={"kind": "effect", "shot": A2, "name": "Party"})
    check("signed in: saved off the video", r.status_code == 200 and r.json()["item"]["name"] == "Party"
          and r.json()["item"]["value"] == {"effect": "disco", "effect_amount": 0.5}, r.text)
    rid = r.json()["item"]["id"]
    r = c.post("/api/resources", json={"kind": "transition"})
    check("nothing to keep: said, not saved", r.status_code == 409 and "transition" in r.json()["detail"], r.text)
    r = c.post(f"/api/resources/{rid}/use", json={"shot": B1}, headers=away)
    check("signed out: can't use", r.status_code == 401)
    turns = len(A.SESSION.turns)
    r = c.post(f"/api/resources/{rid}/use", json={"shot": B1})
    check("one click: on the video as one turn", r.status_code == 200 and len(A.SESSION.turns) == turns + 1
          and entry(A.SESSION.board, B1).get("effect") == "disco", r.text)
    A.SESSION.toggle(A.SESSION.turns[-1].id, A.CATALOG["cat"], A._make_proposals)
    check("and undoable", not entry(A.SESSION.board, B1).get("effect"))
    r = c.patch(f"/api/resources/{rid}", json={"name": "Disco night"}, headers=away)
    check("signed out: can't rename", r.status_code == 401)
    r = c.patch(f"/api/resources/{rid}", json={"name": "Disco night"})
    check("renamed", any(x["name"] == "Disco night" for x in r.json()["items"]))
    r = c.delete(f"/api/resources/{rid}")
    check("deleted", all(x["id"] != rid for x in r.json()["items"]))
    r = c.post(f"/api/resources/{rid}/use", json={})
    check("a deleted one can't be used", r.status_code == 404)
    A.PROJECT["p"] = None
    r = c.patch(f"/api/resources/{resources.all_items()[0]['id']}", json={"name": "From the profile"})
    check("the profile page can rename with no video open", r.status_code == 200, r.text)


if __name__ == "__main__":
    sys.exit(main())
