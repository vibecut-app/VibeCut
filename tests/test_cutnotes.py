"""Check my cut: do the notes move with the edit, and say what was built in?

Two edits that differ in one respect, through the real cut checks
(seams.check over cutgrammar/joins.py): shot B much brighter than shot A
gives one note, at the cut's time, naming the jump with the numbers built
in (40 → 200); the same edit with B lit like A gives none. Moving the
bright shot moves the note to its new cut. A caption on screen too briefly
gets a note at its start, quoting its words. A check the media couldn't
support is listed as not checked, never as fine. Through the API: the
report names the turn it read, keeps a `cut_check` event on the project
and changes nothing in the edit; with no edit it says so.

    python tests/test_cutnotes.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-cutnotes-"))
os.environ.setdefault("VIBECUT_EXPORTS", os.path.join(os.environ["VIBECUT_CACHE"], "out"))
os.environ.setdefault("VIBECUT_BED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def clipd(cid: str, luma: float) -> dict:
    """A 10 s clip the cut checker can read: flat brightness, gentle movement, no sound."""
    from web.backend import seams
    path = f"/nonexistent/{cid}.mov"
    seams._RMS[path] = []          # no sound to compare: the loudness check has nothing to read
    return {"id": cid, "path": path, "capture_time": None,
            "signals": {"luma": [luma] * 10, "motion": [5.0] * 10}, "shots": []}


def timeline(order: list[str], secs: float = 3.0) -> list[dict]:
    out, at = [], 0.0
    for n, cid in enumerate(order, 1):
        out.append({"kind": "shot", "key": f"{cid}:0", "shot_id": f"{cid}:0", "clip_id": cid, "n": n,
                    "src_start": 2.0, "src_end": 2.0 + secs, "seq_start": at, "seq_end": at + secs})
        at += secs
    return out


def rules() -> None:
    from web.backend import cutnotes, seams
    clips = {"a": clipd("a", 40), "b": clipd("b", 200), "c": clipd("c", 45)}
    bright = seams.check(timeline(["a", "b"]), clips)
    even = seams.check(timeline(["a", "c"]), clips)
    rb, re_ = cutnotes.notes(timeline(["a", "b"]), bright, [], []), cutnotes.notes(timeline(["a", "c"]), even, [], [])
    n = rb["notes"]
    check("a bright shot after a dark one: one note, at the cut", len(n) == 1 and n[0]["t"] == 3.0 and n[0]["at"] == "0:03"
          and n[0]["kind"] == "cut" and n[0]["title"] == "Cut from shot 1 to 2", str(n))
    check("… naming the jump with the numbers built in", n and "much brighter at the cut (40 → 200" in n[0]["lines"][0]
          and n[0]["verdict"] == "bad", n[0]["lines"][0] if n else "")
    check("… and what usually helps, in words (nothing is changed)", n and n[0]["helps"] and "fade" in n[0]["helps"][0]
          and "ops" not in n[0])
    check("the same edit lit evenly: no note", rb["notes"] and not re_["notes"]
          and re_["headline"].startswith("Nothing reads as amateur by these checks: 1 cut checked"), re_["headline"])

    moved = cutnotes.notes(timeline(["a", "c", "a", "b"]), seams.check(timeline(["a", "c", "a", "b"]), clips), [], [])
    check("move the bright shot later and the note moves with it", [x["at"] for x in moved["notes"]] == ["0:09"]
          and moved["notes"][0]["title"] == "Cut from shot 3 to 4", str([(x["at"], x["title"]) for x in moved["notes"]]))

    ovs = [{"id": "o1", "kind": "caption", "text": "we walked all the way up the hill to see the sunset over the bay",
            "start": 4.2, "shown_end": 5.0}]
    fs = [{"overlay": "o1", "rule": "read_time", "value": 0.2, "verdict": "bad", "basis": "edit",
           "message": "On screen 0.8s; reading it takes about 4.1s."}]
    cap = cutnotes.notes(timeline(["a", "b"]), bright, ovs, fs)
    cn = [x for x in cap["notes"] if x["kind"] == "caption"]
    check("a caption too quick to read: a note at its start, quoting it", len(cn) == 1 and cn[0]["at"] == "0:04"
          and cn[0]["title"].startswith("Too quick to read: “we walked all the way up") and cn[0]["title"].endswith("…”")
          and "fewer words" in cn[0]["helps"][0], str(cn))
    check("notes are in the order they happen", [x["t"] for x in cap["notes"]] == sorted(x["t"] for x in cap["notes"]))
    check("the headline counts both", cap["headline"] == "1 of 1 cut may feel rough and 1 caption note; 2 stand out most.",
          cap["headline"])

    pend = [{**bright[0], "findings": bright[0]["findings"] + [
        {"key": "join_sound", "label": "Loudness step", "value": None, "unit": "dB", "verdict": "pending", "detail": "", "data": {}}]}]
    p = cutnotes.notes(timeline(["a", "b"]), pend, [], [])
    check("a check the media couldn't support is listed as not checked", p["unchecked"]
          and p["unchecked"][0].startswith("Loudness step: not checked at 1 cut"), str(p["unchecked"]))
    check("the report says its limits are first guesses", "first guess" in p["priors"])
    check("an empty edit says there's nothing to check", cutnotes.notes([], [], [], [])["headline"].startswith("There's nothing to check"))


def through_api() -> None:
    from fastapi.testclient import TestClient
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend
    a = clip(PTMP / "cn-a.mp4", 6, "0x101010", "0x202020", "'325+40*sin(t)'", "2026-09-20T08:10:00")
    b = clip(PTMP / "cn-b.mp4", 7, "0xf0f0f0", "0xe0e0e0", "'120+30*t'", "2026-09-20T11:05:00")
    with TestClient(backend.app) as c:
        c.post("/api/projects", json={"name": "Notes"})
        check("no edit yet: it says so", c.post("/api/cutnotes").status_code == 400)
        wait(c, c.post("/api/import", json={"paths": [a, b]}).json())
        c.post("/api/brief/auto", json={"format": "short", "look": "clean"})
        c.post("/api/cut/approve", json={})
        s = c.get("/api/session").json()
        s = c.post("/api/chat", json={"message": s["brief"]["message"], "style": s["brief"]["style"]}).json()
        c.post("/api/ops", json={"ops": [{"op": "choose_option", "option": s["proposals"]["options"][0]["key"]}], "label": "pick"})
        before = c.get("/api/session").json()
        r = c.post("/api/cutnotes")
        check("a report for the edit as it stands", r.status_code == 200 and r.json()["turn"] == before["last"]["turn"]
              and r.json()["checked"]["cuts"] == len(before["seams"]), r.text[:200])
        after = c.get("/api/session").json()
        check("checking changes nothing in the edit", after["board"] == before["board"] and after["last"]["turn"] == before["last"]["turn"])
        ev = [e for e in backend.PROJECT["p"].events if e.get("kind") == "cut_check"]
        check("the check is kept on the project, with what it found", len(ev) == 1 and ev[0]["notes"] == len(r.json()["notes"])
              and ev[0]["turn"] == before["last"]["turn"], str(ev))


def main() -> int:
    rules()
    through_api()
    print(f"\n{'all passed' if not failures else f'{len(failures)} failed: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
