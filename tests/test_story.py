"""The story editor: a model plans the video as chapters (story.py, oai.py).

No network: OpenAI's reply is played by a stand-in. Unit: nothing is called
without the key, the AI switch on, and that edit's estimate agreed; a call's cost
comes from its usage; an answer is checked against what was offered (unknown
numbers, repeats and the hook inside a chapter are dropped, lengths are held
to their job's range and to what was filmed); payoffs sit on whole beats.
Chapter titles are their own overlay kind with one look for the video (thin
spaced capitals). The words are lines a person would type: a thought or what
they're doing, never a list of what's in the picture (sarah, 2026-10-18);
the clock is the app's, a caption never sits under the title and is held
long enough to read. Through the API: Make with the stand-in lands chapters
as the board's parts, a titled heading per chapter with its line, the
captions on their moments, and the cost in the reply; a broken answer falls
back to the rules' edit and says so.

    python tests/test_story.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

# Its own cache, always: the test flips the AI switch (ai.json), which must
# never be a real one. Empty keys, so web/.env on a dev Mac is never read.
if __name__ == "__main__":   # the indexer's worker processes re-run this file: they keep this cache
    os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-story-")
os.environ["VIBECUT_EXPORTS"] = os.path.join(os.environ["VIBECUT_CACHE"], "out")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ.setdefault("VIBECUT_BED", "0")
os.environ["VIBECUT_REMIX_JUDGE"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def shot(i: int, dur: float):
    from web.backend import storyboard as sb
    return sb.Shot(id=f"c{i}:0", clip_id=f"c{i}", clip_name=f"IMG_{i}", index=0, start=0.0, end=dur, thumb="",
                   quality=0.7, aesthetic=None, utility=False, when=datetime(2026, 10, 14, 9) + timedelta(minutes=10 * i),
                   gps=None, labels={"food": 0.8}, faces=0, face_area=0.0, activity=0.3, vec=np.ones(4) / 2, order=i)


def answer_for(n: int, hook: int | None = None) -> dict:
    half = max(1, (n - 1) // 2)
    nums = [k for k in range(1, n + 1) if k != hook]
    a, b = nums[:half], nums[half:]
    return {"video_title": "A day out", "hook": hook, "chapters": [
        {"title": "Morning Routine", "subtitle": "slow start", "clock": True,
         "shots": [{"n": k, "role": "setup" if j == 0 else "step", "seconds": 1.2, "caption": ""} for j, k in enumerate(a)]},
        {"title": "OOTD", "subtitle": "trying on everything", "clock": False,
         "shots": [{"n": k, "role": "payoff" if j == len(b) - 1 else "step", "seconds": 1.5,
                    "caption": "obsessed with this one" if j == len(b) - 1 else ""} for j, k in enumerate(b)]},
    ]}


def reply(ans: dict, prompt=9000, out=2500) -> dict:
    return {"model": "gpt-6.1-sol", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(ans)}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": out}}


def unit() -> None:
    from web.backend import oai, overlays as ov, story

    print("the AI switch")
    os.environ["OPENAI_API_KEY"] = ""
    os.environ.pop("OPENAI_MODEL", None)
    oai.ENV_FILE = Path(tempfile.mkdtemp()) / ".env"
    oai.switch(True)
    check("no key: off, whatever the switch says", not oai.enabled())
    oai.switch(False)
    oai.ENV_FILE.write_text("ANTHROPIC_API_KEY=x\nOPENAI_API_KEY=sk-test\n")
    check("a key alone is not a yes", oai.has_key() and not oai.enabled())
    oai.switch(True)
    check("key + switch on: on", oai.enabled())
    oai.switch(False)
    check("switched off again", not oai.enabled())
    oai.ENV_FILE.unlink()     # and stays a file that isn't there: never the real web/.env

    print("what a call costs")
    c = oai.cost({"prompt_tokens": 10_000, "completion_tokens": 3000}, "gpt-6.1-sol")
    check("sol: 10k in + 3k out = $0.05", abs(c - 0.05) < 1e-9, f"{c}")
    check("an unknown model is priced at the dearest row", oai.cost({"prompt_tokens": 1e6}, "mystery") == oai.DEAREST[0])
    est = story.estimate(60, "gpt-6.1-sol")
    check("a 60-moment plan is estimated at a few cents", 0.02 < est < 0.15, f"${est:.3f}")

    print("the answer, checked")
    cands = [shot(i, 6.0 if i != 2 else 0.9) for i in range(8)]
    ans = answer_for(8, hook=8)
    ans["chapters"][0]["shots"] += [{"n": 99, "role": "step", "seconds": 1}, {"n": 1, "role": "step", "seconds": 1},
                                    {"n": 8, "role": "step", "seconds": 1}]
    ans["chapters"][1]["shots"][0]["seconds"] = 30.0
    ans["chapters"].append({"title": "Empty", "subtitle": "", "clock": False, "shots": [{"n": 1, "role": "payoff", "seconds": 3, "caption": "x"}]})
    plan, chapters, title = story.plan_from(ans, cands, {}, "tall")
    ids = [p.shot.id for p in plan.picks]
    check("unknown numbers, repeats and the hook twice are dropped", len(ids) == len(set(ids)) == 8 and "c7:0" == ids[0], str(ids))
    check("a chapter left with nothing is dropped", [c["title"] for c in chapters] == ["Morning Routine", "OOTD"])
    lo, hi = story.ROLE_S["tall"]["step"]
    p30 = plan.sessions[1][0]
    check("a length outside its job is held to the range", abs(p30.duration - hi) < 1e-6, f"{p30.duration}")
    short = next(p for p in plan.picks if p.shot.id == "c2:0")
    check("never longer than it was filmed", short.duration <= 0.9 + 1e-6)
    check("payoffs on whole beats (hero), the rest on half-beats",
          plan.sessions[1][-1].role == "hero" and plan.sessions[0][0].role == "filler" and plan.hook[0].role == "hook")
    check("parts are named by the chapters", plan.titles == ["Morning Routine", "OOTD"] and title == "A day out")
    try:
        story.plan_from({"video_title": "", "hook": None, "chapters": []}, cands, {}, "tall")
        check("an empty plan is refused", False)
    except story.StoryError:
        check("an empty plan is refused", True)

    print("the words: a line a person would type")
    lo_ = story.line_of
    check("a list of what's in the picture is dropped (the line sarah called AI)",
          lo_("green spaces, a green drink, and sunny streets") == "" and lo_("coffee, croissant, view") == "")
    check("a thought or what they're doing stands", lo_("this matcha is so good") == "this matcha is so good"
          and lo_("walk to class") == "walk to class")
    check("no clock from the model: the app writes the real one", lo_("7:40 am walk to class") == "walk to class"
          and lo_("walk to class at 7:40 a.m.") == "walk to class", lo_("walk to class at 7:40 a.m."))
    check("at most one emoji", lo_("so good ☕☕ 😍") == "so good ☕", lo_("so good ☕☕ 😍"))
    check("a joined emoji counts once", lo_("girls night 👩‍👩‍👧 💅") == "girls night 👩‍👩‍👧", lo_("girls night 👩‍👩‍👧 💅"))
    check("no full stop, no quotes", lo_('"Finally coffee."') == "Finally coffee" and lo_("why is it so cold?") == "why is it so cold?")
    check("a paragraph is dropped, never cut into a fragment", lo_("we walked all the way across the whole city today") == ""
          and lo_("walk to the station and then grab a coffee") == "")
    check("a list without the last comma is still a list", lo_("green spaces, a green drink and sunny streets") == "")
    check("a clock comes off either end with the word that led to it, keeping the ! or ?",
          lo_("heading out at 7:30am!") == "heading out!" and lo_("7:40 am · walk to class") == "walk to class"
          and lo_("7:40 walk to class") == "walk to class", lo_("heading out at 7:30am!"))
    check("a clock in the middle can't come out cleanly: the line goes", lo_("up at 6am and ready") == "" and lo_("up at 6am!") == "")
    check("no clock, nothing cut: a line may end on at or from", lo_("back at it") == "back at it"
          and lo_("look where we're from") == "look where we're from" and lo_("the 3 of us") == "the 3 of us")
    flag = "🏴\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
    check("a tag flag is one emoji, rare CJK letters aren't emoji", lo_(f"home {flag} 😍") == f"home {flag}"
          and lo_("𠀀𠀁 so good 😍") == "𠀀𠀁 so good 😍", repr(lo_(f"home {flag} 😍")))

    print("the line under a title, and the clock")
    check("clock asked for: the real time from the chapter's first moment goes in front",
          chapters[0]["subtitle"] == "9:00 am · slow start", chapters[0]["subtitle"])
    check("no clock asked for: just the line", chapters[1]["subtitle"] == "trying on everything")
    check("every chapter title wears the one look", {c["look"] for c in chapters} == {"spaced"})
    nowords = story.plan_from({"video_title": "", "hook": None, "chapters": [
        {"title": "Out", "subtitle": "sunny streets, green spaces, a green drink", "clock": False,
         "shots": [{"n": 1, "role": "payoff", "seconds": 3, "caption": ""}]}]}, cands, {}, "tall")[1]
    check("a list under a title leaves the line empty rather than say it", nowords[0]["subtitle"] == "")

    print("captions on their moments")
    cands2 = [shot(i, 8.0) for i in range(8)]
    rich = {"video_title": "", "hook": None, "chapters": [
        {"title": "Coffee Run", "subtitle": "finally coffee", "clock": False, "shots": [
            {"n": 1, "role": "setup", "seconds": 1.2, "caption": "first moment"},         # the title is up: never
            {"n": 2, "role": "step", "seconds": 1.0, "caption": "under the title"},       # starts at 1.2 s, title to 2.4 s: never
            {"n": 3, "role": "step", "seconds": 2.0, "caption": "finally coffee"},        # same as the line: never
            {"n": 4, "role": "payoff", "seconds": 4.0, "caption": "this matcha is so good"},
            {"n": 5, "role": "step", "seconds": 1.5, "caption": "why is it so cold"},
            {"n": 6, "role": "payoff", "seconds": 4.0, "caption": "ok one more"},          # a third: never
        ]}]}
    p2, ch2, _ = story.plan_from(rich, cands2, {}, "tall")
    ops2 = story.heading_ops(p2, ch2)
    caps = [o for o in ops2 if o["kind"] == "caption"]
    check("never on the chapter's first moment, never while its title is up, never repeating its line, at most two",
          [c["text"] for c in caps] == ["this matcha is so good", "why is it so cold"], json.dumps([c["text"] for c in caps]))
    check("each hangs on its own moment, a beat after the cut",
          [c["anchor"] for c in caps] == [{"to": "shot", "id": "c3:0"}, {"to": "shot", "id": "c4:0"}]
          and all(c["at"] == story.CAPTION_AT for c in caps))
    starts = {}
    t_ = 0.0
    for pk in p2.sessions[0]:
        starts[pk.shot.id] = t_
        t_ += pk.duration
    ends = [starts[c["anchor"]["id"]] + c["at"] + c["dur"] for c in caps]
    check("held long enough to read, gone before the next one, inside the chapter",
          all(story.READ_S[0] <= c["dur"] <= story.READ_S[1] for c in caps)
          and ends[0] <= starts["c4:0"] + story.CAPTION_AT + 1e-6 and ends[-1] <= t_ + 1e-6,
          json.dumps([(c["dur"], round(e, 2)) for c, e in zip(caps, ends)]))
    tight = story.heading_ops(*story.plan_from({"video_title": "", "hook": None, "chapters": [
        {"title": "Quick", "subtitle": "", "clock": False, "shots": [
            {"n": 1, "role": "payoff", "seconds": 2.5, "caption": ""},
            {"n": 2, "role": "setup", "seconds": 0.8, "caption": "no time to read this"}]}]}, cands2, {}, "tall")[:2])
    check("no caption where there's no time left to read it", not [o for o in tight if o["kind"] == "caption"])
    late = story.heading_ops(*story.plan_from({"video_title": "", "hook": None, "chapters": [
        {"title": "Lunch", "subtitle": "", "clock": False, "shots": [
            {"n": 1, "role": "setup", "seconds": 1.2, "caption": ""},
            {"n": 2, "role": "payoff", "seconds": 4.0, "caption": "this ramen is unreal"}]}]}, cands2, {}, "tall")[:2])
    lc = [o for o in late if o["kind"] == "caption"]
    check("a payoff that starts under the title gets its caption once the title has gone",
          len(lc) == 1 and abs(lc[0]["at"] - (story.HEADING_S + story.GAP_S - 1.2)) < 0.02 and lc[0]["dur"] >= story.MIN_READ_S,
          json.dumps(lc))

    print("words kept readable when shots move under them (the self-check's fixes)")
    from web.backend import board as bd

    def fixture(lens2: tuple[float, ...] = (1.2, 1.4, 3.0)):
        b = {"beats": [{"id": "r1", "title": "Coffee", "shots": [{"id": f"c{i}:0", "start": 0.0, "end": d} for i, d in enumerate(lens2)]},
                       {"id": "r2", "title": "Home", "shots": [{"id": "c9:0", "start": 0.0, "end": 3.0}]}], "overlays": []}
        for k, op in enumerate([{"op": "add_overlay", "kind": "heading", "text": "Coffee", "look": "spaced", "beat": "r1", "at": 0.0, "dur": 2.4},
                                {"op": "add_overlay", "kind": "caption", "text": "finally coffee", "anchor": {"to": "shot", "id": "c2:0"},
                                 "at": 0.15, "dur": 2.5},
                                {"op": "add_overlay", "kind": "heading", "text": "Home", "look": "spaced", "beat": "r2", "at": 0.0, "dur": 2.4}]):
            b, _ = bd.apply(b, op, None, None, new_id=lambda k=k: f"o{k}")
        return b

    def timed(b):
        return {o["id"]: (o["start"], o["end"]) for o in ov.resolve(b)}

    b0 = fixture()
    check("as made: the caption after the title, inside its chapter", timed(b0)["o1"] == (2.75, 5.25) and not story.fit_captions(b0),
          json.dumps(timed(b0)))
    dropped = fixture()
    dropped["beats"][0]["shots"].pop(1)                    # the self-check drops the step as a repeat
    fixed = bd.applied(dropped, story.fit_captions(dropped), None, None)
    a, z = timed(fixed)["o1"]
    check("a dropped shot pulls the caption under the title: it waits for the title, and ends with its chapter",
          a >= 2.4 + story.GAP_S - 0.01 and z <= 4.2 - 0.05 + 0.01 and z - a >= story.MIN_READ_S, f"{a}–{z}")
    short = fixture((1.2, 1.4, 1.5))                       # …shortens the payoff
    a, z = timed(bd.applied(short, story.fit_captions(short), None, None))["o1"]
    check("a shortened chapter: the caption ends before the next chapter's title", z <= 4.1 - 0.05 + 0.01 and a == 2.75, f"{a}–{z}")
    tiny = fixture((1.2, 1.4, 0.6))
    ops_ = story.fit_captions(tiny)
    check("no room left to read it: the caption goes", {"op": "drop_overlay", "overlay": "o1"} in ops_, json.dumps(ops_))
    small = fixture()
    sh = small["beats"][0]["shots"]
    sh.pop(1)
    sh[0]["end"], sh[1]["end"] = 1.0, 0.9                  # the chapter is 1.9 s now
    ops_ = story.fit_captions(small)
    head = next((o for o in ops_ if o.get("overlay") == "o0"), None)
    check("a chapter title ends with its chapter, not over the next one", head and abs(head["dur"] - 1.85) < 0.02, json.dumps(ops_))

    print("chapter titles have their own look")
    hs = story.heading_ops(plan, chapters)
    check("one heading per chapter, at its start", [h["beat"] for h in hs if h["kind"] == "heading"] == ["r1", "r2"]
          and hs[0]["look"] == "spaced")
    b = {"beats": [{"id": "r1", "title": "x", "shots": [{"id": "c0:0", "start": 0, "end": 3}]}], "overlays": []}
    ov.add(b, dict(hs[0]), lambda: "o1")
    o = b["overlays"][0]
    check("a heading keeps its words, line under it and look", o["kind"] == "heading" and o["sub"] == "9:00 am · slow start"
          and o["look"] == "spaced")
    ov.add(b, {"op": "add_overlay", "kind": "heading", "text": "By hand", "beat": "r1"}, lambda: "o3")
    check("a chapter title added by hand wears the same thin spaced look", b["overlays"][-1]["look"] == "spaced")
    b["overlays"].pop()
    try:
        ov.add(b, {"op": "add_overlay", "kind": "caption", "text": "hi", "look": "script", "beat": "r1"}, lambda: "o2")
        check("only a chapter title takes a look", False)
    except ov.OverlayError:
        check("only a chapter title takes a look", True)
    ov.edit(b, {"overlay": "o1", "look": "serif"})
    check("its look can be changed", b["overlays"][0]["look"] == "serif")

    print("the request")
    os.environ["OPENAI_API_KEY"] = "sk-test"
    seen = {}

    def post(url, body, headers):
        seen.update(body=body, headers=headers)
        return reply(answer_for(3))
    got, usage = oai.ask_json("sys", [{"type": "text", "text": "hi"}], story.SCHEMA, "story_plan", post=post)
    check("strict json schema, low-detail frames, cost read back",
          seen["body"]["response_format"]["json_schema"]["strict"] and usage["cost"] > 0 and got["chapters"])
    check("frames go at low detail", oai.image(b"\xff\xd8")["image_url"]["detail"] == "low")
    try:
        oai.ask_json("s", [], story.SCHEMA, "x", post=lambda *a: {"choices": [{"finish_reason": "length", "message": {"content": "{"}}]})
        check("a cut-off answer is an error", False)
    except oai.OAIError:
        check("a cut-off answer is an error", True)
    os.environ["OPENAI_API_KEY"] = ""


def api() -> None:
    from cutgrammar import music as mu
    from fastapi.testclient import TestClient
    from tests.test_bed import BPM, _track
    from tests.test_projects import TMP as PTMP, clip, wait
    from web.backend import app as backend, bed, oai

    print("through the API, with a stand-in for OpenAI")
    cols = ["0xff8a1e", "0x1ec8ff", "0xd0ff1e", "0xff1e8a", "0x1effa0", "0xffe01e", "0x8a1eff", "0xff4d1e"]
    bgs = ["0x2a3440", "0x203028", "0x302028", "0x282030", "0x203030", "0x303020", "0x202838", "0x382820"]
    xs = ["'325+40*sin(t)'", "'120+30*t'", "'200+20*sin(2*t)'", "'60+50*t'", "'400-30*t'", "'250+60*sin(t/2)'", "'90+25*t'", "'300-40*sin(t)'"]
    clips = [clip(PTMP / f"st-{i}.mp4", 7 + i % 3, cols[i], bgs[i], xs[i], f"2026-09-20T{8 + (16 * i) // 60:02d}:{(16 * i) % 60:02d}:00") for i in range(8)]
    d = Path(tempfile.mkdtemp(prefix="vibecut-story-music-"))
    _track(str(d / "beat.wav"), 240.0, BPM, loud_from=24.0)
    pool = mu.LocalFolderSource(str(d)).list()
    real_cand, real_post = bed.candidates, oai._post
    bed.candidates = lambda pace, own, progress=None: (pool, "a test track")
    calls = []

    looks = []

    def fake(url, body, headers):
        if body["response_format"]["json_schema"]["name"] == "edit_check":
            # then it looks over the finished cut once (selfcheck.py; tests/test_selfcheck.py)
            looks.append(body)
            return reply({"summary": "It holds up.", "issues": [], "fixes": []}, prompt=6000, out=2000)
        n = sum(1 for p in body["messages"][1]["content"] if p["type"] == "text" and p["text"].startswith("#"))
        calls.append(n)
        return reply(answer_for(n, hook=n))
    oai._post = fake
    os.environ["OPENAI_API_KEY"] = "sk-test"

    def make(c, fmt="tall", ai_ok=None):
        job = c.post("/api/make", json={"format": fmt, "look": "cozy", "ai_ok": ai_ok}).json()
        for _ in range(600):
            if job["stage"] in ("done", "error"):
                break
            time.sleep(0.25)
            job = c.get(f"/api/make/{job['id']}").json()
        return job

    try:
        with TestClient(backend.app) as c:
            c.post("/api/projects", json={"name": "Story"})
            wait(c, c.post("/api/import", json={"paths": clips}).json())
            for rec in backend.CLIPS.values():
                for sh in rec.get("shots", []):
                    sh["utility"] = False
            ai = c.get("/api/ai").json()
            check("the switch starts off, the key is there", ai["available"] and not ai["on"], json.dumps(ai))
            est = c.get("/api/make/estimate").json()
            check("off: the estimate is nothing", est["dollars"] == 0 and not est["on"])
            job = make(c, ai_ok=0.05)
            check("switch off: nothing is sent, even with a go-ahead", job["stage"] == "done" and not calls and not looks,
                  job.get("error") or "")
            c.post("/api/undo")
            c.post("/api/ai", json={"on": True})
            est = c.get("/api/make/estimate").json()
            check("on: the edit's cost is shown before anything is sent",
                  est["on"] and est["moments"] >= 3 and 0 < est["dollars"] < 0.25 and not calls, json.dumps(est))
            check("the price covers planning it and one look at the finished cut",
                  est["plan"] > 0 and est["check"] > 0 and abs(est["plan"] + est["check"] - est["dollars"]) < 0.002)
            job = make(c)
            check("on, but this edit's cost not agreed: nothing is sent", job["stage"] == "done" and not calls and not looks)
            c.post("/api/undo")
            job = make(c, ai_ok=est["dollars"])
            check("on and agreed: one plan, then one look at the cut", job["stage"] == "done" and len(calls) == 1
                  and len(looks) == 1, job.get("error") or str(calls))
            sheet = [p for p in looks[0]["messages"][1]["content"] if p["type"] == "image_url"]
            check("it looked at a contact sheet of the real clips", sheet and sheet[0]["image_url"]["detail"] == "high")
            s = c.get("/api/session").json()
            kinds = [t["kind"] for t in s["turns"]][-2:]
            check("the look lands as its own turn after the video", kinds == ["direct", "check"]
                  and s["turns"][-1]["sheets"] and "holds up" in s["turns"][-1]["reply"], str(kinds))
            ev = backend.PROJECT["p"].events
            check("both costs are kept", ev[-1]["kind"] == "make" and ev[-2]["kind"] == "check" and ev[-2]["cost"] > 0,
                  json.dumps(ev[-2:])[:200])
            titles = [b["title"] for b in s["board"]["beats"]]
            check("the parts are the chapters, after the hook", titles == ["Hook", "Morning Routine", "OOTD"], str(titles))
            items = s["overlays"]["items"]
            heads = [o for o in items if o["kind"] == "heading"]
            check("a designed title per chapter in the one look, each with its line under it",
                  [(o["text"], o["look"]) for o in heads] == [("Morning Routine", "spaced"), ("OOTD", "spaced")]
                  and heads[1]["sub"] == "trying on everything", json.dumps(heads)[:200])
            import re as _re
            check("the line asks for the clock: the real filming time in front",
                  bool(_re.fullmatch(r"\d{1,2}:\d\d (am|pm) · slow start", heads[0]["sub"])), heads[0]["sub"])
            caps = [o for o in items if o["kind"] == "caption"]
            check("the payoff's thought is a caption on its moment, after the title",
                  [o["text"] for o in caps] == ["obsessed with this one"]
                  and caps[0]["start"] >= heads[1]["shown_end"] - 1e-6, json.dumps(caps)[:200])
            check("no clock-time stop lines on a planned edit", not any(o["kind"] == "part" for o in items))
            last = s["turns"][-1] if s.get("turns") else {}
            said = json.dumps(s)
            check("the reply names the model and the cost", "planned it as 2 chapters (cost $" in said, last.get("reply", "")[:160])
            ev = backend.PROJECT["p"].events[-1]
            check("the cost is kept with the project", ev.get("ai", {}).get("cost", 0) > 0, json.dumps(ev.get("ai")))
            c.post("/api/undo")
            oai._post = lambda url, body, headers: reply({"video_title": "", "hook": None, "chapters": []})
            job = make(c, ai_ok=est["dollars"])
            s = c.get("/api/session").json()
            check("a useless answer falls back to the rules, and says so",
                  job["stage"] == "done" and "story plan didn't work" in json.dumps(s), job.get("error") or "")
    finally:
        bed.candidates, oai._post = real_cand, real_post
        os.environ["OPENAI_API_KEY"] = ""
        oai.switch(False)


def main() -> int:
    unit()
    api()
    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
