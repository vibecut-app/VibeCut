"""Subtitles on the Captions switch, with the words the recogniser doubted.

The helper reports how sure it is of each word; subtitles.py marks the
words under UNSURE on the subtitle (`unsure`) and every subtitle as `heard`;
the overlay keeps both, and a retype or "sounds right" clears the doubt.
The switch in Frames (`/api/captions {on, mode}`) is Off / Describe /
Subtitles: switching kinds is one undoable turn that replaces the other
kind's captions and keeps a title; the same kind again is no turn; where
there's no recogniser or nobody talks it says so and changes nothing. A
fixed subtitle is never taken as a line of the creator's caption voice.

    python tests/test_subtitles_switch.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-subs-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def main() -> int:
    from tests.test_board import session
    from web.backend import speech, subtitles

    print("the helper's confidence")
    out = speech.parse("\n".join([
        json.dumps({"text": "we took the ferry", "words": [
            {"t": "we", "s": 0.0, "e": 0.2, "c": 0.97}, {"t": "took", "s": 0.2, "e": 0.4, "c": 0.9},
            {"t": "the", "s": 0.4, "e": 0.5, "c": 1.4}, {"t": "ferry", "s": 0.5, "e": 0.9, "c": 0.31}], "segs": ["we", "took", "the", "ferry"]}),
        "not json",
        json.dumps({"text": "old", "words": [{"t": "old", "s": 2.0, "e": 2.3, "c": None}, {"t": "cache", "s": 2.3, "e": 2.6}]}),
    ]))
    ws = [w for r in out for w in r["words"]]
    check("each word carries its confidence, clamped to 0..1", [w["c"] for w in ws[:4]] == [0.97, 0.9, 1.0, 0.31], str([w["c"] for w in ws]))
    check("none given (an older helper) is None, not a number", [w["c"] for w in ws[4:]] == [None, None])
    check("results in time order, a bad line skipped", [r["text"] for r in out] == ["we took the ferry", "old"])

    print("marking")
    line = [{"t": "we", "c": 0.97}, {"t": "took", "c": 0.9}, {"t": "the", "c": 0.2}, {"t": " ferry,", "c": 0.31},
            {"t": "the", "c": 0.1}, {"t": "cache", "c": None}, {"t": " ，", "c": 0.2}]
    check("the words under UNSURE are marked, once each, in order, bare of punctuation; unknown isn't uncertain, nor is punctuation",
          subtitles.unsure(line) == ["the", "ferry"], str(subtitles.unsure(line)))

    s, cat = session()
    clips = {sh.clip_id: {"id": sh.clip_id, "name": sh.clip_name, "sound": {"voice": [0.9] * 10}} for sh in cat.shots.values()}
    first = next(iter(clips))

    def hear(rec, loc):
        out = []
        for sh in cat.shots.values():
            if sh.clip_id == rec["id"]:
                t0 = sh.start + 0.4
                sure = 0.95 if rec["id"] != first else 0.3
                out.append({"text": "we took the ferry", "words": [
                    {"t": w, "s": round(t0 + 0.3 * k, 2), "e": round(t0 + 0.3 * k + 0.25, 2), "c": sure if w == "ferry" else 0.98}
                    for k, w in enumerate(["we", "took", "the", "ferry"])]})
        return out
    ops, notes = subtitles.caption_ops(s.board, cat, clips, "A day in Tokyo", transcribe=hear)
    caps = [o for o in ops if o["op"] == "add_overlay"]
    doubted = [o for o in caps if o.get("unsure")]
    check("every subtitle is marked heard", caps and all(o.get("heard") for o in caps))
    check("only the lines with a doubted word carry it, naming the word", doubted and all(o["unsure"] == ["ferry"] for o in doubted)
          and len(doubted) < len(caps), f"{len(doubted)} of {len(caps)}")
    check("the note says how many words to check", any("weren't heard clearly" in n for n in notes), str(notes))
    sure_ops, sure_notes = subtitles.caption_ops(s.board, cat, clips, "A day in Tokyo",
                                                 transcribe=lambda rec, loc: [{**r, "words": [{**w, "c": 0.99} for w in r["words"]]} for r in hear(rec, loc)])
    check("all heard clearly: no mark, no note", not any("unsure" in o for o in sure_ops) and not sure_notes)

    print("on the overlay")
    mk = lambda d: {"options": []}  # noqa: E731
    s, cat = session()
    shot = s.board["beats"][0]["shots"][0]
    t = s.add({"kind": "direct", "text": "subs", "ops": [
        {"op": "add_overlay", "kind": "caption", "text": "we took the ferry", "heard": True, "unsure": ["ferry"],
         "anchor": {"to": "shot", "id": shot.get("key") or shot["id"]}, "at": 0.3, "dur": 1.2},
        {"op": "add_overlay", "kind": "caption", "text": "and walked", "heard": True,
         "anchor": {"to": "shot", "id": shot.get("key") or shot["id"]}, "at": 1.6, "dur": 1.0}]}, cat, mk)
    a, b = s.board["overlays"][-2:]
    check("the record keeps heard and the doubted words", a.get("heard") is True and a.get("unsure") == ["ferry"], json.dumps(a))
    check("a subtitle with nothing doubted has no mark", b.get("heard") is True and "unsure" not in b)
    s.add({"kind": "direct", "text": "fix", "ops": [{"op": "edit_overlay", "overlay": a["id"], "text": "we took the fairy"}]}, cat, mk)
    a2 = next(o for o in s.board["overlays"] if o["id"] == a["id"])
    check("retyping the words clears the doubt, heard stays", "unsure" not in a2 and a2.get("heard") is True, json.dumps(a2))
    s.add({"kind": "direct", "text": "subs", "ops": [
        {"op": "add_overlay", "kind": "caption", "text": "the sea", "heard": True, "unsure": ["sea"],
         "anchor": {"to": "shot", "id": shot.get("key") or shot["id"]}, "at": 2.8, "dur": 1.0}]}, cat, mk)
    c_ = s.board["overlays"][-1]
    s.add({"kind": "direct", "text": "ok", "ops": [{"op": "edit_overlay", "overlay": c_["id"], "unsure": []}]}, cat, mk)
    c2 = next(o for o in s.board["overlays"] if o["id"] == c_["id"])
    check("'sounds right' clears it without touching the words", "unsure" not in c2 and c2["text"] == "the sea")
    t = s.add({"kind": "direct", "text": "bad", "ops": [{"op": "edit_overlay", "overlay": c_["id"], "unsure": "ferry"}]}, cat, mk)
    check("unsure must be a list of words", bool(t.skipped) and "list" in t.skipped[0], t.skipped[0] if t.skipped else "accepted")

    print("through the API")
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend, bed, captionmem
    clips_ = [clip(PTMP / f"ss-{i}.mp4", 6 + i % 3, ["white", "red", "blue", "green", "yellow", "gray"][i], "black", "40",
                   f"2026-09-20T{8 + 2 * i:02d}:00:00") for i in range(6)]
    real_bed, real_hear = bed.candidates, speech.transcribe
    bed.candidates = lambda pace, own, progress=None: ([], "nothing")

    def hear_api(rec, loc):
        d = float(rec.get("duration") or 6.0)
        n = max(2, int(d / 1.5))
        return [{"text": "we took the ferry", "start": 0.3 + 1.5 * k, "end": 1.5 + 1.5 * k, "words": [
            {"t": w, "s": round(0.3 + 1.5 * k + 0.3 * j, 2), "e": round(0.3 + 1.5 * k + 0.3 * j + 0.25, 2),
             "c": 0.3 if w == "ferry" else 0.98} for j, w in enumerate(["we", "took", "the", "ferry"])]}
            for k in range(n)]
    speech.transcribe = hear_api
    try:
        with TestClient(backend.app) as c:
            c.post("/api/projects", json={"name": "Subtitles"})
            wait(c, c.post("/api/import", json={"paths": clips_}).json())
            for rec in backend.CLIPS.values():
                rec["sound"] = {"voice": [0.9] * int(rec.get("duration") or 6)}
            job = c.post("/api/make", json={"format": "short", "look": "cozy", "music": False}).json()
            for _ in range(400):
                j = c.get(f"/api/make/{job['id']}").json()
                if j["stage"] in ("done", "error"):
                    break
                time.sleep(0.1)
            s = c.get("/api/session").json()
            n_turns = len(s["turns"])
            titles = [o for o in s["overlays"]["items"] if o["kind"] == "title"]
            check("after Make the switch reads describe (or off), never subtitles", s["overlays"]["mode"] in ("describe", "off"), s["overlays"]["mode"])

            r = c.post("/api/captions", json={"on": True, "mode": "subtitles"})
            s = r.json()
            caps = [o for o in s["overlays"]["items"] if o["kind"] == "caption"]
            check("Subtitles: one turn, every caption heard, the switch reads subtitles",
                  r.status_code == 200 and len(s["turns"]) == n_turns + 1 and caps and all(o.get("heard") for o in caps)
                  and s["overlays"]["mode"] == "subtitles", f"{r.status_code} {len(s['turns']) - n_turns} turns, {len(caps)} captions")
            check("a title from Make stays, its stop lines go", len([o for o in s["overlays"]["items"] if o["kind"] == "title"]) == len(titles)
                  and not any(o["kind"] == "part" for o in s["overlays"]["items"]), str([(o["kind"], o["text"]) for o in s["overlays"]["items"]][:5]))
            to_check = [o for o in caps if o.get("unsure")]
            check("the doubted words ride to the UI", to_check and all(o["unsure"] == ["ferry"] for o in to_check), str([o.get("unsure") for o in caps][:4]))
            check("the turn says how many words to check", "weren't heard clearly" in (s["turns"][-1]["reply"] or ""), s["turns"][-1]["reply"])
            sub_turn = s["turns"][-1]["id"]

            r = c.post("/api/captions", json={"on": True, "mode": "subtitles"})
            check("the same kind again is no turn", r.status_code == 200 and len(r.json()["turns"]) == n_turns + 1)

            before = len(captionmem.events())
            c.post("/api/ops", json={"ops": [{"op": "edit_overlay", "overlay": to_check[0]["id"], "text": "we took the fairy"}], "label": "fix"})
            s = c.get("/api/session").json()
            fixed = next(o for o in s["overlays"]["items"] if o["id"] == to_check[0]["id"])
            check("fixing a word clears its mark", fixed["text"] == "we took the fairy" and not fixed.get("unsure"))
            check("a fixed subtitle isn't taken as a line of her caption voice", len(captionmem.events()) == before)

            r = c.post("/api/captions", json={"on": True, "mode": "describe"})
            s = r.json()
            check("Describe: the subtitles go, the time-and-place lines come, one turn, switch reads describe",
                  r.status_code == 200 and not any(o.get("heard") for o in s["overlays"]["items"])
                  and s["overlays"]["mode"] == "describe", f"{s['overlays']['mode']} {[o['text'] for o in s['overlays']['items']][:3]}")
            c.post(f"/api/turns/{s['turns'][-1]['id']}/toggle")
            s = c.get("/api/session").json()
            check("Undo brings the subtitles back and the switch follows", s["overlays"]["mode"] == "subtitles")

            c.post(f"/api/turns/{sub_turn}/toggle")
            s = c.get("/api/session").json()
            check("undoing the subtitles turn too: back to what Make put on", s["overlays"]["mode"] in ("describe", "off"), s["overlays"]["mode"])

            r = c.post("/api/captions", json={"on": True, "mode": "karaoke"})
            check("an unknown kind is refused", r.status_code == 422)

            def no_mac(rec, loc):
                raise speech.SpeechError("Transcribing needs macOS 26 or later with the Xcode command-line tools.")
            speech.transcribe = no_mac
            turns = len(c.get("/api/session").json()["turns"])
            r = c.post("/api/captions", json={"on": True, "mode": "subtitles"})
            check("no recogniser: it says so where the switch is, nothing changes",
                  r.status_code == 409 and "macOS" in r.json()["detail"] and len(c.get("/api/session").json()["turns"]) == turns, str(r.json()))
            speech.transcribe = hear_api
            for rec in backend.CLIPS.values():
                rec["sound"] = {"voice": [0.0] * int(rec.get("duration") or 6), "music": [0.9] * int(rec.get("duration") or 6)}
            r = c.post("/api/captions", json={"on": True, "mode": "subtitles"})
            check("nobody talking: it says so, nothing changes", r.status_code == 409 and "talking" in r.json()["detail"], str(r.json()))
            backend._close_project()
    finally:
        bed.candidates, speech.transcribe = real_bed, real_hear

    print()
    if failures:
        print(f"{len(failures)} failed: {failures}")
        return 1
    print("all passed")
    return 0


def test_subtitles_switch() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
