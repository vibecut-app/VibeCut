"""The AI editor's breakdown of a reference (taste/editor.py).

No network and no key: OpenAI's reply is played by a stand-in `post`, and
with no key nothing is sent at all. Checks: the strict schema OpenAI
enforces (every property required, nothing extra, on every object); the
estimate grows with shots and with what's said, and stops growing in
pictures past the sheets' cap; what is sent (numbered sheets at high
detail, a line per shot, word counts but never words); `apply` copies roles
by 1-based shot number, chapters without overlap, and leaves out numbers
and names that aren't there; an answer that quotes the transcript is
scrubbed; the description stays valid; a Budget stops a run before the
call that would pass the cap; the CLI prices only descriptions without
roles.

    python tests/test_taste_editor.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-editor-")
os.environ["OPENAI_API_KEY"] = ""      # web/.env on a dev Mac is never read
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ.pop("OPENAI_MODEL", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from taste import describe, editor  # noqa: E402
from web.backend import oai  # noqa: E402

# An empty OPENAI_API_KEY reads as unset, and oai then reads web/.env -- where
# her Mac keeps the course key. Point it at a file that isn't there.
oai.ENV_FILE = Path(os.environ["VIBECUT_CACHE"]) / "no.env"

failures: list[str] = []
TMP = Path(os.environ["VIBECUT_CACHE"])
SAID = "okay so today we are going to the farmers market and then I will cook dinner for my friends"


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def stills(n: int) -> list[str]:
    """Small JPEGs, a few colours reused (one decode each is the slow part)."""
    colours = ["red", "green", "blue", "orange"]
    out = []
    for c in colours:
        p = TMP / f"{c}.jpg"
        if not p.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={c}:s=96x170",
                            "-frames:v", "1", str(p)], check=True)
        out.append(str(p))
    return [out[i % len(out)] for i in range(n)]


def desc_of(n: int, cutoff: bool = False) -> dict:
    """A reference of n shots: talk, then quick b-roll, a held payoff; words
    on the first shots (counts only)."""
    shots, t = [], 0.0
    for i in range(n):
        d = 3.0 if i % 5 == 4 else 1.2
        talk = i % 5 == 0
        shots.append(describe._shot(t, d, motion=0.2 + 0.1 * (i % 3), face=0.9 if talk else 0.0,
                                    facing=1.0 if talk else None, people=1 if talk else 0,
                                    voice=0.8 if talk else 0.1, music=0.0 if talk else 0.7, laugh=0.0,
                                    labels=["food", "table"] if not talk else ["people"], same=bool(i == 1)))
        t += d
    joins = [{"t": s["t"], "kind": "jump" if s["same"] else "cut", "dur": 0.0} for s in shots[1:]]
    return {"v": 1, "id": "L999", "source": "reference", "group": "long", "vertical": False,
            "duration": round(t, 3), "cutoff": cutoff, "have": ["motion", "faces", "sound", "words", "labels"],
            "shots": shots, "joins": joins, "open": False, "close": False,
            "words": [{"t": 0.0, "d": 1.0, "band": "top", "size": 0.06, "upper": 1.0, "n": 3, "kind": None}],
            "music": {"bpm": None, "on": 0.6, "beat": None}, "lufs": -15.0}


def answer_for(n: int) -> dict:
    half = n // 2
    return {"premise": "A slow Saturday of shopping and cooking, told as small rituals.",
            "hook": {"shots": [1, 2, 99], "kind": "talk"},
            "chapters": [{"name": "Market", "first": 3, "last": half + 2, "purpose": "she gathers what dinner needs"},
                         {"name": "Kitchen", "first": half, "last": n + 10, "purpose": "the cooking builds to the plate"},
                         {"name": "Nowhere", "first": 0, "last": 2, "purpose": "out of range"}],
            "shots": [{"n": k, "role": ("talk" if k % 5 == 1 else "payoff" if k % 5 == 0 else "step")}
                      for k in range(1, n + 1)] + [{"n": n + 1, "role": "step"}, {"n": 2, "role": "payoff"},
                                                   {"n": 0, "role": "step"}],
            "captions": {"role": "signpost", "note": "a short card up top as each part starts"},
            "music": [{"shot": 2, "event": "start"}, {"shot": n + 5, "event": "end"}],
            "ending": "payoff_hold",
            "techniques": [{"name": "talk_then_show", "shots": [1, 2, 3]}, {"name": "jump_cuts", "shots": [2, 400]},
                           {"name": "not_a_technique", "shots": [1]}],
            "notes": "Quick steps build into one held payoff per part; talk carries the thread."}


def stand_in(answer: dict, seen: list, usage: dict | None = None, **extra):
    def post(url, body, headers):
        seen.append(body)
        msg = {"content": json.dumps(answer)}
        msg.update(extra)
        return {"model": "gpt-6.1-sol", "usage": usage or {"prompt_tokens": 9000, "completion_tokens": 1500},
                "choices": [{"message": msg, "finish_reason": "stop"}]}
    return post


def walk(node, path="schema"):
    """Every object in a schema -> (path, problem) for each strict-mode rule broken."""
    bad = []
    if isinstance(node, dict):
        t = node.get("type")
        if t == "object" or (isinstance(t, list) and "object" in t):
            props = node.get("properties") or {}
            if node.get("additionalProperties") is not False:
                bad.append((path, "additionalProperties is not false"))
            if sorted(node.get("required") or []) != sorted(props):
                bad.append((path, "not every property is required"))
        for k, v in node.items():
            bad += walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad += walk(v, f"{path}[{i}]")
    return bad


def test_schema_is_strict():
    print("the schema follows OpenAI's strict mode")
    bad = walk(editor.SCHEMA)
    check("every object: all properties required, nothing extra", not bad, str(bad[:3]))
    props = editor.SCHEMA["properties"]
    check("the top level has the spec's keys",
          set(props) == {"premise", "hook", "chapters", "shots", "captions", "music", "ending", "techniques", "notes"})
    check("roles are the description's roles",
          props["shots"]["items"]["properties"]["role"]["enum"] == list(describe.ROLES))
    check("27 techniques from the catalogue", len(props["techniques"]["items"]["properties"]["name"]["enum"]) == 27)
    unsupported = [k for k in ("minLength", "maxLength", "minItems", "maxItems", "pattern")
                   if k in json.dumps(editor.SCHEMA)]
    check("no length keywords strict mode might refuse (caps are kept in code)", not unsupported, str(unsupported))


def test_estimate():
    print("the estimate")
    e10, e40, e160, e320 = (editor.estimate(n, model="gpt-6.1-sol") for n in (10, 40, 160, 320))
    check("grows with shots", e10 < e40 < e160 < e320, f"{e10:.4f} {e40:.4f} {e160:.4f} {e320:.4f}")
    check("past 160 shots no more sheets: it grows by listed lines and roles only",
          (e320 - e160) / 160 < (e160 - e40) / 120, f"{(e320 - e160) / 160:.6f} vs {(e160 - e40) / 120:.6f}")
    check("what's said costs more", editor.estimate(40, 8000, "gpt-6.1-sol") > e40)
    check("a long transcript is capped", editor.estimate(40, 10 ** 7, "gpt-6.1-sol")
          == editor.estimate(40, editor.TRANSCRIPT_MAX, "gpt-6.1-sol"))
    check("a cheaper model costs less", editor.estimate(40, model="gpt-6-luna") < e40)
    check("an unknown model is priced at the dearest row", editor.estimate(40, model="who") == e40)
    check("a 40-shot vlog is cents, not dollars", 0.005 < e40 < 0.2, f"${e40:.3f}")


def test_breakdown_sends_sheets_and_counts():
    print("breakdown: what is sent")
    n = 20
    d = desc_of(n)
    seen: list = []
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        ans, usage = editor.breakdown(d, stills(n), transcript=SAID, post=stand_in(answer_for(n), seen))
    finally:
        os.environ["OPENAI_API_KEY"] = ""
    body = seen[0]
    content = body["messages"][1]["content"]
    imgs = [c for c in content if c["type"] == "image_url"]
    text = content[0]["text"]
    check("two sheets for 20 shots, at high detail", len(imgs) == 2 and all(c["image_url"]["detail"] == "high" for c in imgs))
    check("the strict schema rides on the request", body["response_format"]["json_schema"]["strict"] is True
          and body["response_format"]["json_schema"]["schema"] is not None)
    check("a line per shot, numbered", all(f"#{k} " in text for k in range(1, n + 1)))
    check("jump cut named in the list", "jump cut in" in text)
    check("words as counts", "1 card, 3 words, top in capitals" in text, text.splitlines()[6][:120])
    check("what's said is sent, marked not to quote", SAID in text and "never quote" in text)
    check("the system prompt is an editor's brief that forbids quoting",
          "senior editor" in body["messages"][0]["content"] and "Never quote" in body["messages"][0]["content"])
    check("usage carries the cost", usage["cost"] > 0 and usage["model"] == "gpt-6.1-sol", str(usage))
    check("the answer comes back as given", ans["premise"].startswith("A slow Saturday"))

    # past the sheets' cap the rest are listed, not pictured
    big = desc_of(170)
    seen = []
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        editor.breakdown(big, stills(170), post=stand_in(answer_for(170), seen))
    finally:
        os.environ["OPENAI_API_KEY"] = ""
    content = seen[0]["messages"][1]["content"]
    check("170 shots: 10 sheets, the rest listed", sum(c["type"] == "image_url" for c in content) == 10
          and "Shots #161-#170 are listed but not pictured." in content[0]["text"])


def test_breakdown_refuses_bad_input_and_passes_errors():
    print("breakdown: bad input, failures")
    d = desc_of(8)
    for name, args in (("stills don't match the shots", (d, stills(7))),
                       ("most pictures missing", (d, [None] * 6 + stills(2))),
                       ("one shot only", ({**d, "shots": d["shots"][:1], "joins": []}, stills(1)))):
        try:
            editor.breakdown(*args, post=lambda *a: (_ for _ in ()).throw(AssertionError("sent")))
            check(name, False, "no error")
        except editor.EditorError:
            check(name + ": EditorError, nothing sent", True)
    try:
        # a key found anywhere would still never reach the network
        editor.breakdown(d, stills(8), post=lambda *a: (_ for _ in ()).throw(AssertionError("sent")))
        check("no key: nothing sent", False)
    except oai.OAIError as e:
        check("no key: OAIError, nothing sent", "no OpenAI key" in str(e))
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        editor.breakdown(d, stills(8), post=stand_in({}, [], refusal="no"))
        check("a refusal raises", False)
    except oai.OAIError as e:
        check("a refusal passes through with what it cost", e.usage and e.usage["cost"] > 0)
    finally:
        os.environ["OPENAI_API_KEY"] = ""


def test_apply():
    print("apply")
    n = 20
    d = desc_of(n)
    before = json.dumps(d, sort_keys=True)
    out = editor.apply(d, answer_for(n), {"model": "gpt-6.1-sol", "cost": 0.031})
    check("the input is not changed", json.dumps(d, sort_keys=True) == before)
    roles = [s["role"] for s in out["shots"]]
    check("roles by 1-based number", roles[0] == "talk" and roles[4] == "payoff" and roles[2] == "step", str(roles[:6]))
    check("a second answer for a shot is ignored (shot 2 stays step)", roles[1] == "step")
    check("every shot got its role", all(r in describe.ROLES for r in roles))
    chs = out["editor"]["chapters"]
    check("out-of-range chapter dropped, overlap trimmed to playing order",
          [(c["name"], c["first"], c["last"]) for c in chs] == [("Market", 3, 12), ("Kitchen", 13, 20)], str(chs))
    check("chapter index on the shots", [s["chapter"] for s in out["shots"]][:4] == [None, None, 0, 0]
          and out["shots"][12]["chapter"] == 1 and out["shots"][-1]["chapter"] == 1)
    ed = out["editor"]
    check("hook keeps real shots only", ed["hook"] == {"shots": [1, 2], "kind": "talk"})
    check("music events in range only", ed["music"] == [{"shot": 2, "event": "start"}])
    check("techniques: known names, shots in range",
          ed["techniques"] == [{"name": "talk_then_show", "shots": [1, 2, 3]}, {"name": "jump_cuts", "shots": [2]}])
    check("model, cost and date kept", ed["model"] == "gpt-6.1-sol" and ed["cost"] == 0.031 and len(ed["at"]) == 10)
    check("roles is a reading now", "roles" in out["have"] and out["have"].index("roles") > out["have"].index("labels"))
    check("still a valid description", not describe.validate(out), str(describe.validate(out)[:3]))
    check("ending as answered", ed["ending"] == "payoff_hold")

    cut = editor.apply(desc_of(n, cutoff=True), answer_for(n))
    check("a cut-off description ends 'cutoff' whatever was said", cut["editor"]["ending"] == "cutoff")
    wordy = dict(answer_for(n), premise=" ".join(["word"] * 60), notes=" ".join(["n"] * 90))
    ed = editor.apply(d, wordy)["editor"]
    check("free text held to its word caps", len(ed["premise"].split()) == 25 and len(ed["notes"].split()) == 40)
    empty = editor.apply(d, {"shots": [], "chapters": []})
    check("no roles answered: no roles reading", "roles" not in empty["have"] and empty["editor"]["roles_given"] == 0)


def test_quotes_are_scrubbed():
    print("never keep the creator's words")
    n = 10
    quoting = answer_for(n)
    quoting["premise"] = "She says we are going to the farmers market and cooks."
    quoting["chapters"][0]["name"] = "Market"
    quoting["notes"] = "Plain cuts throughout."
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        ans, usage = editor.breakdown(desc_of(n), stills(n), transcript=SAID, post=stand_in(quoting, []))
    finally:
        os.environ["OPENAI_API_KEY"] = ""
    out = editor.apply(desc_of(n), ans, usage)
    check("a premise quoting 5 words in a row is blanked", out["editor"]["premise"] == "")
    check("text that doesn't quote stays", out["editor"]["notes"] == "Plain cuts throughout."
          and out["editor"]["chapters"][0]["name"] == "Market")
    check("the transcript is not in the description", "farmers market" not in json.dumps(out))


def test_budget_stops_a_run():
    print("a Budget stops the run")
    b = editor.Budget(0.10)
    made = 0
    for _ in range(10):                   # as taste.collect runs it: estimate, check, call, count
        est = 0.03
        if not b.can(est):
            break
        b.spend({"cost": 0.04})           # the real call cost more than its estimate
        made += 1
    check("stops before the call that would pass the cap", made == 2 and b.spent <= 0.10 + 1e-9,
          f"{made} calls, ${b.spent:.2f}")
    check("left is what remains", abs(b.left - 0.02) < 1e-9, f"{b.left:.3f}")
    b.spend(oai.OAIError("cut off", {"cost": 0.01}).usage)
    b.spend(None)
    check("a failed call's cost counts, one that never answered costs nothing", abs(b.spent - 0.09) < 1e-9 and b.calls == 4)


def test_cli_estimates_only():
    print("the CLI")
    folder = TMP / "descriptions"
    a, done = desc_of(30), editor.apply(desc_of(12), answer_for(12))
    a["id"], done["id"] = "L001", "L002"
    describe.save(a, folder / "L001.json")
    describe.save(done, folder / "L002.json")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = editor.main(["--estimate", "--dir", str(folder)])
    said = buf.getvalue()
    check("prices only the one without roles", rc == 0 and "L001" in said and "L002" not in said, said)
    check("prints the total", "1 video without roles, about $" in said)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = editor.main([])
    check("no run mode", rc == 2 and "taste.collect" in buf.getvalue())


if __name__ == "__main__":
    for t in (test_schema_is_strict, test_estimate, test_breakdown_sends_sheets_and_counts,
              test_breakdown_refuses_bad_input_and_passes_errors, test_apply, test_quotes_are_scrubbed,
              test_budget_stops_a_run, test_cli_estimates_only):
        t()
    print(f"\n{'FAIL' if failures else 'PASS'}: {len(failures)} failure(s)" + (f": {', '.join(failures)}" if failures else ""))
    sys.exit(1 if failures else 0)
