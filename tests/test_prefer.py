"""Which do you like better? The cards after Make (web/backend/prefer.py).

Same synthetic shoot, track and tiny trained model as test_tastepick. Then:

1. the window a card plays: from the shot before the first difference, the
   end kept for an ending, never longer than WINDOW_S or shorter than
   MIN_WINDOW_S, nothing when the pictures are the same;
2. Make keeps at most one change per part of the video, and a model that
   likes a held opening and a held ending gets both in one cut;
3. the cards: at most MAX_CARDS, in the order the video plays, two versions
   each that differ in that card's part only, one of them the video's;
4. her pick is kept as a pair and moves the score her way on that very
   comparison by a real step (the one-respect pair: before vs after one
   pick), "can't tell" keeps nothing; the next card starts from the
   version she picked;
5. a user who turns the same thing down video after video: the gap Make
   sees shrinks every time;
6. through the API on real files: the card, its sound, a pick that lands
   as one undoable turn, undo, a pick after a hand edit that only teaches,
   a stale card, Make again.

    python tests/test_prefer.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def _load() -> None:
    """The imports, only when run: the index pool's workers re-import this
    script, and test_tastepick would point them at a cache of their own."""
    global tt, mu, tm, BPM, _track, bed, prefer, tastepick, timeline
    # the shoot, the track and the tiny model (it points VIBECUT_CACHE at its own temp dir)
    from tests import test_tastepick as tt
    from cutgrammar import music as mu
    from taste import model as tm
    from tests.test_bed import BPM, _track
    from web.backend import bed, prefer, tastepick, timeline


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def items(lengths: list[float], clips: list[str] | None = None) -> list[dict]:
    """A laid-out edit: one shot per length, each from its own clip unless named."""
    out, t = [], 0.0
    for k, d in enumerate(lengths):
        c = (clips or [])[k] if clips else f"c{k}"
        out.append({"key": f"k{k}", "kind": "shot", "clip_id": c, "src_start": 1.0, "src_end": 1.0 + d,
                    "seq_start": round(t, 4), "seq_end": round(t + d, 4)})
        t += d
    return out


def windows() -> None:
    print("the window a card plays")
    a = items([1.5] * 12)
    check("the same pictures: nothing to compare", prefer.windows(a, items([1.5] * 12)) is None)
    b = items([3.0] + [1.5] * 11)
    w = prefer.windows(a, b)
    check("a different opening: both from the start", w and w[0][0] == 0 and w[1][0] == 0, str(w))
    check("…and at least MIN_WINDOW_S", w and all(e - s >= prefer.MIN_WINDOW_S - 1e-6 for s, e in w), str(w))
    c = items([1.5] * 11 + [4.5])
    w = prefer.windows(a, c)
    check("a different ending: both run to their own end", w and w[0][1] == a[-1]["seq_end"]
          and w[1][1] == c[-1]["seq_end"], str(w))
    check("…from a cut, no longer than WINDOW_S", w and all(e - s <= prefer.WINDOW_S + 1e-6 for s, e in w)
          and w[1][0] in [x["seq_start"] for x in c], str(w))
    d = items([1.5] * 12, [f"c{k}" for k in range(5)] + ["c6", "c5"] + [f"c{k}" for k in range(7, 12)])
    w = prefer.windows(a, d)
    check("two stops' shots swapped in the middle: from the shot before them", w and w[0][0] == a[4]["seq_start"], str(w))
    e = items([1.5] * 6 + [9.0] + [1.5] * 5)
    w = prefer.windows(a, e)
    check("a long change in the middle is cut to WINDOW_S", w and all(x1 - x0 <= prefer.WINDOW_S + 1e-6 for x0, x1 in w), str(w))


def deck_from(job) -> prefer.Deck:
    return prefer.Deck(job.result["deck"], job.result["taste_pick"], 1, "p1")


def main() -> int:
    _load()
    windows()

    clips = tt.shoot()
    d = tt.TMP / "music"
    d.mkdir(parents=True, exist_ok=True)
    _track(str(d / "beat.wav"), 240.0, BPM, loud_from=24.0)
    pool = mu.LocalFolderSource(str(d)).list()
    real_candidates = bed.candidates
    bed.candidates = lambda pace, own, progress=None: (pool, "a test track")
    tm.MODEL_DIR = tt.TMP / "model"
    model = tt.train()
    tm.save(model, tm.MODEL_DIR / "short.json")

    print("Make keeps one change per part")
    job = tt.run(clips, pool, "cozy")
    rep = job.result["taste_pick"]
    parts = [tastepick.PART.get(c["name"]) for c in rep["chosen"]]
    check("Make is done, and keeps what the cards need", job.stage == "done" and job.result.get("deck")
          and rep.get("chosen"), str(job.error or rep))
    check("at most one change per part", len(parts) == len(set(parts)), str(rep["chosen"]))
    board, skipped = tt.applies(job.result["ops"], clips)
    check("its ops apply with nothing skipped", bool(board) and not skipped, str(skipped))
    real = tastepick._MODELS.copy()
    both = tt.only(model, {"opening_hold": 1.0, "ending_hold": 1.0})
    tastepick._MODELS["short"] = (tastepick._stamp("short"), both)
    j2 = tt.run(clips, pool, "cozy")
    r2 = j2.result["taste_pick"]
    got = {tastepick.PART.get(c["name"]) for c in r2["chosen"]}
    check("a model that likes a held opening and a held ending gets both in one cut", {"opening", "ending"} <= got
          and r2["score"] > max(v["score"] for v in r2["variants"]), str([c["name"] for c in r2["chosen"]]))
    check("…and the reply names both", " and " in tastepick.sentence(r2), tastepick.sentence(r2))
    b2, sk2 = tt.applies(j2.result["ops"], clips)
    check("…whose ops apply with nothing skipped", bool(b2) and not sk2, str(sk2))
    tastepick._MODELS.clear()
    tastepick._MODELS.update(real)

    print("the cards")
    dk = deck_from(job)
    check(f"at most {prefer.MAX_CARDS}, in the order the video plays", 1 <= len(dk.kinds) <= prefer.MAX_CARDS
          and dk.kinds == [k for k in prefer.PLAYS if k in dk.kinds], str(dk.kinds))
    card = dk.next_card()
    check("a card has two versions, one of them the video", card is not None and len(card["sides"]) == 2
          and card["sides"][card["video"]].ops == job.result["ops"])
    if card is None:
        return 1
    va, vb = card["sides"]
    check("…that differ", va.ops != vb.ops)
    diff = {k for k in set(va.now) | set(vb.now) if va.now.get(k, {}).get("name") != vb.now.get(k, {}).get("name")}
    check("…in that card's part only", diff == {card["kind"]}, f"{card['kind']}: {va.names()} vs {vb.names()}")
    for side, (s, e) in zip(card["sides"], card["windows"]):
        total = timeline.layout(side.board)[-1]["seq_end"]
        pub = prefer.side_public(side, (s, e))
        check(f"window {s:.2f}–{e:.2f} lies in its edit ({total:.2f}) and has shots", 0 <= s < e <= total + 1e-6
              and pub["items"] and pub["items"][0]["seq_start"] <= s + 1e-6)
    check("the same card until it is answered", dk.next_card() is card)

    print("her pick")
    other = 1 - card["video"]
    better, worse = card["sides"][other], card["sides"][card["video"]]
    m0 = tastepick.model_for("short")
    gap0 = m0.score(better.desc) - m0.score(worse.desc)
    out = dk.answer(card["id"], other)
    stored = json.loads(tm._personal_path().read_text())
    check("kept as a pair: the version she picked above the other", len(stored["pairs"]) == 1
          and stored["pairs"][0]["kind"] == "pick" and stored["pairs"][0]["better"] == better.desc)
    m1 = tastepick.model_for("short")
    gap1 = m1.score(better.desc) - m1.score(worse.desc)
    check("one pick moves that very comparison her way by a real step", gap1 - gap0 >= 0.1,
          f"{gap0:+.3f} -> {gap1:+.3f}")
    check("…but no further than one step", gap1 - gap0 <= tm.PICK_STEP / tm.PERSONAL_L2 + 0.05, f"{gap1 - gap0:+.3f}")
    check("…and the group's model without her is untouched", tm.load("short", personal=False).score(better.desc)
          == model.score(better.desc))
    check("it says what she picked, and that the video changes", out["change"] and out["words"] and out["side"] is better,
          out["words"])
    dk.landed(7, better)
    check("the video's version follows the turn it landed with", dk.follow(7) and dk.now == better.now
          and not dk.follow(99))
    dk.follow(7)
    nxt = dk.next_card()
    if nxt is not None:
        check("the next card starts from the version she picked", nxt["sides"][nxt["video"]].ops == better.ops)
        made_ops = dk._side(dk.turns[dk.make_turn]).ops
        dk.follow(dk.make_turn)        # she undid that pick
        again = dk.next_card()
        check("…and after an Undo it's built again from the made version, so a pick can't bring the undone one back",
              again is not nxt and again["kind"] == nxt["kind"] and again["sides"][again["video"]].ops == made_ops
              and all(s.ops != better.ops for s in again["sides"]))
        dk.follow(7)
        nxt = dk.next_card()
        n0 = len(json.loads(tm._personal_path().read_text())["pairs"])
        dk.answer(nxt["id"], None)
        check("can't tell: nothing kept", len(json.loads(tm._personal_path().read_text())["pairs"]) == n0)
    while (c := dk.next_card()) is not None:
        dk.answer(c["id"], c["video"])
    check("every card answered: done", dk.done() and dk.next_card() is None)

    print("turning the same thing down, video after video")
    tm._personal_path().unlink()
    tastepick._MODELS.clear()
    gaps = []
    for _ in range(3):
        j = tt.run(clips, pool, "cozy")
        r = j.result["taste_pick"]
        sc = {v["name"]: v["score"] for v in r["variants"]}
        gaps.append(sc["held_open"] - sc["today"])
        dk = deck_from(j)
        while (c := dk.next_card()) is not None:
            has = ["held_open" in s.names() for s in c["sides"]]
            pick = has.index(False) if has.count(False) == 1 else None
            got = dk.answer(c["id"], pick)
            if got["side"] is not None:
                dk.landed(100 + c["id"], got["side"])
    check("the held opening's lead shrinks every video", gaps[0] > gaps[1] > gaps[2] and gaps[0] - gaps[2] > 0.5,
          " -> ".join(f"{g:+.2f}" for g in gaps))

    api(clips_dir=tt.TMP / "api", model=model)
    bed.candidates = real_candidates
    print(f"\n{'all passed' if not failures else f'{len(failures)} FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


# --------------------------------------------------------------------------
# through the API, on real files
# --------------------------------------------------------------------------

SRCS = ["testsrc2", "mandelbrot", "life=size=640x360:rate=30:mold=10:ratio=0.1", "smptebars", "rgbtestsrc",
        "gradients=size=640x360:rate=30:speed=0.05", "testsrc", "cellauto=size=640x360:rate=30",
        "mandelbrot=size=640x360:rate=30:start_scale=1.5", "testsrc2=size=640x360:rate=30:alpha=128"]


def _clip(path: Path, d: float, src: str, when: str) -> str:
    src = src if "=" in src else f"{src}=size=640x360:rate=30"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi",
                    "-i", f"anoisesrc=d={d}:c=pink:r=16000:a=0.02", "-t", str(d), "-metadata", f"creation_time={when}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(path)], check=True)
    return str(path)


def api(clips_dir: Path, model: tm.Model) -> None:
    print("through the API")
    from fastapi.testclient import TestClient
    from web.backend import app as backend

    def wait(client: TestClient, job: dict) -> dict:
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                return job
            time.sleep(0.2)
            job = client.get(f"/api/jobs/{job['id']}").json()
        raise RuntimeError("import never finished")
    clips_dir.mkdir(parents=True, exist_ok=True)
    paths = [_clip(clips_dir / f"p{i}.mp4", 6 + i % 4, SRCS[i],
                   f"2026-09-20T{(9, 13, 18)[i * 3 // len(SRCS)]:02d}:{(7 * i) % 60:02d}:00") for i in range(len(SRCS))]
    tm._personal_path().unlink(missing_ok=True)
    tastepick._MODELS.clear()

    def made(c) -> dict:
        job = c.post("/api/make", json={"format": "short", "look": "cozy", "music": False}).json()
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                break
            time.sleep(0.2)
            job = c.get(f"/api/make/{job['id']}").json()
        return job

    with TestClient(backend.app) as c:
        c.post("/api/projects", json={"name": "Prefer"})
        wait(c, c.post("/api/import", json={"paths": paths}).json())
        for rec in backend.CLIPS.values():
            for sh in rec.get("shots", []):
                sh["utility"] = False
        job = made(c)
        s = c.get("/api/session").json()
        check("Make lands, and the cards are waiting", job["stage"] == "done" and s.get("prefer")
              and s["prefer"]["at"] == 1, str(job.get("error") or s.get("prefer")))
        if not s.get("prefer"):
            backend._close_project()
            return
        r = c.get("/api/prefer").json()
        card = r["card"]
        check("a card: a question, two versions with shots and a window", card and card["ask"].startswith("Which")
              and len(card["sides"]) == 2 and all(x["items"] and x["start"] < x["end"] for x in card["sides"])
              and r["frame"]["w"] > 0, str(card and card["ask"]))
        snd = c.get(card["sides"][0]["audio"]) if card and card["sides"][0]["audio"] else None
        check("…each with the sound export would write", snd is not None and snd.status_code == 200
              and snd.headers["content-type"].startswith("audio/wav"), str(snd and snd.status_code))
        dk = backend.PREFER["deck"]
        video = dk.card["video"]
        before = s["timeline"]["items"]
        turns = len(s["turns"])
        r = c.post(f"/api/prefer/{card['id']}", json={"pick": 1 - video}).json()
        check("picking the other version lands it as one turn of its own", r["prefer_landed"]
              and len(r["turns"]) == turns + 1 and r["turns"][-1]["text"] == prefer.TURN_TEXT
              and r["timeline"]["items"] != before, r.get("prefer_said", ""))
        check("…and says so in plain words", r["prefer_said"].startswith("Your video now has"), r["prefer_said"])
        stored = json.loads(tm._personal_path().read_text())
        check("…and her pick is kept for the taste model", len(stored["pairs"]) == 1)
        check("the project's record has it", any(e.get("kind") == "prefer" and e.get("landed")
                                                 for e in backend.PROJECT["p"].events))
        on_pick = (r.get("prefer") or {}).get("on")
        s = c.post(f"/api/turns/{r['turns'][-1]['id']}/toggle").json()
        check("Undo puts the made version back", s["timeline"]["items"] == before)
        check("…and the cards are told the video moved, so the next one is fetched again",
              on_pick == r["turns"][-1]["id"] and (s.get("prefer") or {}).get("on") == dk.make_turn,
              f"{on_pick} -> {(s.get('prefer') or {}).get('on')}")
        if s.get("prefer"):
            r = c.get("/api/prefer").json()
            dk = backend.PREFER["deck"]
            check("…and the next card starts from it", dk.card["sides"][dk.card["video"]].ops == dk.ctx["base"][2]
                  or dk.now == dk.turns[dk.make_turn])
            c.post("/api/ops", json={"ops": [{"op": "set_look", "look": "hype"}], "label": "You chose the Hype look"})
            n = len(c.get("/api/session").json()["turns"])
            r = c.post(f"/api/prefer/{r['card']['id']}", json={"pick": 1 - dk.card["video"]}).json()
            check("after a hand edit a pick only teaches: no turn, and it says so", not r["prefer_landed"]
                  and len(r["turns"]) == n and "keeps the changes you made" in r["prefer_said"], r["prefer_said"])
        stale = c.post(f"/api/prefer/{card['id']}", json={"pick": 0})
        check("an old card is refused", stale.status_code == 409, str(stale.status_code))
        check("a pick that isn't 0, 1 or nothing is refused", c.post(f"/api/prefer/{card['id']}", json={"pick": 3}).status_code == 400)
        old = backend.PREFER["deck"]
        made(c)
        s = c.get("/api/session").json()
        check("Make again: the old cards are gone", backend.PREFER["deck"] is not old
              and (s.get("prefer") is None or s["prefer"]["deck"] != old.make_turn), str(s.get("prefer")))
        # what the app puts on a made video by itself (a profile's "no captions" and a dissolve at
        # every cut, as #47 does after Make) doesn't stop a pick landing, and the picked
        # version gets it too, in the same turn
        def dressing(_d=None) -> None:
            b = backend.SESSION.board
            backend.SESSION.add({"kind": "direct", "text": "From your profile",
                                 "ops": [{"op": "drop_overlay", "overlay": o["id"]} for o in b.get("overlays") or []]
                                 + [{"op": "set_transition", "all": True, "kind": "dissolve"}]},
                                backend.CATALOG["cat"], backend._make_proposals)
        backend.REDRESS["From your profile"] = dressing
        try:
            if s.get("prefer"):
                with backend.LOCK:
                    dressing()
                s = c.get("/api/session").json()
                made_items = s["timeline"]["items"]
                r = c.get("/api/prefer").json()
                dk = backend.PREFER["deck"]
                n = len(s["turns"])
                r = c.post(f"/api/prefer/{r['card']['id']}", json={"pick": 1 - dk.card["video"]}).json()
                b = backend.SESSION.board
                check("a profile's own turn after Make: the pick still lands, as one turn", r["prefer_landed"]
                      and len(r["turns"]) == n + 1 and r["turns"][-1]["text"] == prefer.TURN_TEXT, r["prefer_said"])
                check("…and the picked version is dressed the same (no captions, a dissolve at every cut)",
                      not b.get("overlays") and (b.get("picture_all") or {}).get("kind") == "dissolve", str(b.get("picture_all")))
                s = c.post(f"/api/turns/{r['turns'][-1]['id']}/toggle").json()
                check("…and one Undo brings the made version back, still dressed", s["timeline"]["items"] == made_items
                      and not backend.SESSION.board.get("overlays"))
        finally:
            backend.REDRESS.pop("From your profile", None)
        backend._close_project()
        check("another project: no cards", c.get("/api/prefer").json()["card"] is None)


if __name__ == "__main__":
    sys.exit(main())
