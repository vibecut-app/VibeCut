"""The taste collector learns from a creator's most-watched vlogs, measures
a row into numbers only, and (--describe) writes it down shot by shot
without keeping a word or a frame; the AI editor (--ai) stops at its cap.

yt-dlp, the Mac's Vision and OpenAI are stood in for (no network here);
measuring and describing run on a real file made with ffmpeg.

    python tests/test_taste_collect.py
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["VIBECUT_CACHE"] = tempfile.mkdtemp(prefix="vibecut-collect-test-")
os.environ["OPENAI_API_KEY"] = ""      # web/.env on a dev Mac is never read
os.environ.pop("OPENAI_MODEL", None)

from taste import collect, describe, editor, fingerprint, measure  # noqa: E402
from web.backend import oai, sound, vision  # noqa: E402

oai.ENV_FILE = Path(os.environ["VIBECUT_CACHE"]) / "no.env"   # a real key on her Mac must never be found here

HEAD = "id,group,platform,url_or_file,creator,title,length_s,views,likes,counts_read_on,source,verdict,status,notes".split(",")


def _setup(tmp: Path) -> None:
    data = tmp / "data"
    data.mkdir()
    for p in ("long-youtube.csv", "short-reels.csv"):
        (data / p).write_text(",".join(HEAD) + "\n")
    (data / "candidate-creators.csv").write_text(
        "group,creator,platform,size_as_reported,why_listed,where_found,status\n"
        "long,Some One,YouTube,,,,candidate\nlong,Gone,YouTube,,,,struck\n")
    collect.DATA = data
    collect.GROUPS = {"long": data / "long-youtube.csv", "short": data / "short-reels.csv"}
    collect.CREATORS = data / "candidate-creators.csv"
    collect.DESCRIPTIONS = tmp / "descriptions"
    measure.OUT = tmp / "measurements"


def _video(i: int, views: int, likes: int, dur: int = 900, title: str = "") -> dict:
    return {"webpage_url": f"https://y/{i}", "title": title or f"paris vlog {i}", "channel": "Some One", "duration": dur,
            "view_count": views, "like_count": likes, "extractor_key": "Youtube"}


def test_discover_learns_from_the_most_watched_vlogs() -> None:
    with tempfile.TemporaryDirectory() as t:
        _setup(Path(t))
        vids = {f"https://y/{i}": v for i, v in enumerate([
            _video(0, 1000, 10), _video(1, 2000, 100),   # 1: well watched, 5% -> good
            _video(2, 500, 5), _video(3, 400, 2),        # 3: less watched, 0.5% -> ordinary
            _video(4, 3000, 60), _video(5, 100, 50, dur=30),     # 5: too short for long, ignored
            _video(6, 5000, 500, title="fall haul + GRWM")])}    # 6: best ratio, but not a vlog
        def fake_json(args, timeout=120):
            q = args[-1]
            if q.startswith("ytsearch1:"):
                return [{"channel_url": "https://y/@someone"}]
            if q == "https://y/@someone/videos":
                return [{"url": u} for u in vids]
            return [vids[q]] if q in vids else []
        collect._json = fake_json
        collect.discover(lambda s: None)
        rows = list(csv.DictReader(collect.GROUPS["long"].open()))
        got = [r["url_or_file"] for r in rows]
        assert got == ["https://y/4", "https://y/1", "https://y/0"], got   # most watched vlogs, haul and short left out
        assert {r["verdict"] for r in rows} == {"good"}
        assert [r["id"] for r in rows] == ["L001", "L002", "L003"]
        st = {r["creator"]: r["status"] for r in csv.DictReader(collect.CREATORS.open())}
        assert st == {"Some One": "discovered", "Gone": "struck"}, st


def _clip(path: Path) -> Path:
    """Two shots (a busy test pattern, then plain red) under a tone."""
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3",
                    "-f", "lavfi", "-i", "color=c=red:size=320x180:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-map", "2:a",
                    "-shortest", str(path)], check=True)
    return path


def test_measure_keeps_numbers_only() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _setup(tmp)
        clip = _clip(tmp / "clip.mp4")
        row = dict.fromkeys(HEAD, "")
        row.update(id="S001", group="short", url_or_file=str(clip), verdict="good", status="listed")
        collect.measure_one(row, lambda s: None)
        assert row["status"] == "measured", row
        rec = json.loads((measure.OUT / "S001.json").read_text())
        assert rec["pace"]["shots"] == 2, rec["pace"]
        assert "list" not in rec["transitions"] and rec["lufs"] is not None
        assert clip.exists()   # a local file is the creator's own; only downloads are deleted


def test_vlog_filter() -> None:
    assert collect.is_vlog({"title": "a week in tokyo"})
    assert collect.is_vlog({"title": "day in my life as a columbia student"})
    assert not collect.is_vlog({"title": "GRWM for my first day of class"})
    assert not collect.is_vlog({"title": "college haul vlog"})
    assert not collect.is_vlog({"title": "my favourite lip products"})


def test_fingerprint_is_the_good_videos_middle() -> None:
    recs = [{"id": f"L{i}", "pace": {"median_s": m}, "lufs": -14.0 - i, "measured_s": 300,
             "ending": {"last_s": 9.0}, "words": {"pending": ["vision"]}} for i, m in enumerate([1.0, 2.0, 3.0, 4.0, 5.0])]
    fp = fingerprint.fingerprint(recs, "long")
    t = fp["traits"]
    assert t["shot_s"] == {"median": 3.0, "low": 2.0, "high": 4.0, "n": 5, "means": t["shot_s"]["means"]}
    assert t["lufs"]["median"] == -16.0
    assert "last_shot_s" not in t      # the first ten minutes end where the download stopped
    assert "words_share" not in t      # Vision didn't read them
    assert fp["thin"]


# --- describe ---------------------------------------------------------------

def _rows_csv(rows: list[dict]) -> None:
    collect._save(collect.GROUPS["short"], HEAD, rows)


def _row(i: int, url: str, status: str) -> dict:
    row = dict.fromkeys(HEAD, "")
    row.update(id=f"S{i:03d}", group="short", url_or_file=url, source="web", creator="Some One",
               views="100", verdict="good", status=status)
    return row


def _fake_ytdlp(tmp: Path, src: Path) -> tuple[Path, Path]:
    """A yt-dlp that 'downloads' the fixture to the -o template and notes each link."""
    exe, calls = tmp / "bin" / "yt-dlp", tmp / "calls.txt"
    exe.parent.mkdir()
    exe.write_text(f"#!{sys.executable}\nimport shutil, sys\na = sys.argv\n"
                   f"open({str(calls)!r}, 'a').write(a[-1] + '\\n')\n"
                   f"shutil.copy({str(src)!r}, a[a.index('-o') + 1].replace('%(ext)s', 'mp4'))\n")
    exe.chmod(0o755)
    return exe, calls


def _keys(x) -> set[str]:
    if isinstance(x, dict):
        return set(x) | {k for v in x.values() for k in _keys(v)}
    if isinstance(x, list):
        return {k for v in x for k in _keys(v)}
    return set()


def _left(d: Path) -> list[str]:
    return sorted(str(p.relative_to(d)) for p in d.rglob("*"))


def test_describe_keeps_numbers_and_labels_only() -> None:
    real = (vision.ensure_built, vision.text, vision.faces, vision.analyse, sound.ensure_built, collect.ytdlp,
            collect._json, tempfile.tempdir)
    asked = []

    def text(paths, accurate=False):
        asked.append(accurate)
        found = {p: [{"text": "MY SECRET LINE", "box": [0.2, 0.8, 0.6, 0.06], "conf": 0.9}] for p in paths}
        return (found, []) if accurate else found
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _setup(tmp)
        (tmp / "src").mkdir()
        exe, calls = _fake_ytdlp(tmp, _clip(tmp / "src" / "clip.mp4"))
        scratch = tmp / "scratch"
        scratch.mkdir()
        try:
            tempfile.tempdir = str(scratch)          # every work folder the run makes lands here
            collect.ytdlp = lambda: str(exe)
            collect._json = lambda args, timeout=120: []
            vision.ensure_built = lambda: Path("/stand-in")
            vision.text = text
            vision.faces = lambda paths: {p: [[0.3, 0.3, 0.3, 0.3, 5.0]] for p in paths}
            vision.analyse = lambda paths: ([{"path": p, "labels": [["food", 0.9], ["table", 0.5], ["cup", 0.4]],
                                              "aesthetic": 0.2, "error": None} for p in paths], "vision")
            sound.ensure_built = lambda: None
            _rows_csv([_row(1, "https://y/1", "measured"), _row(2, "https://y/2", "listed")])
            log = []
            collect.measure_all(log.append, describe=True)    # S002: measured and described from one download
            collect.describe_all(log.append)                   # S001: measured before, fetched again
            collect.describe_all(log.append)                   # resumable: nothing left to do
        finally:
            (vision.ensure_built, vision.text, vision.faces, vision.analyse, sound.ensure_built, collect.ytdlp,
             collect._json, tempfile.tempdir) = real
        assert sorted(p.name for p in collect.DESCRIPTIONS.iterdir()) == ["S001.json", "S002.json"], log
        assert (measure.OUT / "S002.json").exists()
        assert calls.read_text().split() == ["https://y/2", "https://y/1"], calls.read_text()   # one fetch each
        for name in ("S001", "S002"):
            raw = (collect.DESCRIPTIONS / f"{name}.json").read_text()
            d = json.loads(raw)
            assert not describe.validate(d), describe.validate(d)
            assert "text" not in _keys(d) and "SECRET" not in raw      # counted and placed, never kept
            assert d["have"] == ["motion", "faces", "words", "labels"], d["have"]
            assert len(d["shots"]) == 2 and d["words"] and d["words"][0]["band"] == "top", d
            assert d["shots"][0]["labels"] == ["food", "table", "cup"]
        assert True in asked                                 # the description asked for accurate OCR
        assert _left(scratch) == [], _left(scratch)          # no download, frame or sound left behind
        assert (tmp / "src" / "clip.mp4").exists()


def _answer(n: int) -> dict:
    return {"premise": "A quiet afternoon told in two looks.", "hook": {"shots": [1], "kind": "scene"},
            "chapters": [{"name": "Afternoon", "first": 1, "last": n, "purpose": "the day slows down"}],
            "shots": [{"n": k, "role": "step" if k < n else "payoff"} for k in range(1, n + 1)],
            "captions": {"role": "none", "note": ""}, "music": [{"shot": 1, "event": "start"}],
            "ending": "cut", "techniques": [{"name": "straight_cuts", "shots": [1, 2]}], "notes": ""}


def test_ai_editor_stops_at_the_cap() -> None:
    sent = []

    def post(url, body, headers):
        sent.append(body)
        n = 2                     # the fixture's two shots
        return {"model": "gpt-6.1-sol", "usage": {"prompt_tokens": 3000, "completion_tokens": 900},
                "choices": [{"message": {"content": json.dumps(_answer(n))}, "finish_reason": "stop"}]}
    real_dir = tempfile.tempdir
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _setup(tmp)
        clip = _clip(tmp / "clip.mp4")
        scratch = tmp / "scratch"
        scratch.mkdir()
        # her own files (no download): two measured rows, off the Mac (no Vision, no transcript)
        _rows_csv([_row(1, str(clip), "measured"), _row(2, str(clip), "measured")])
        cap = editor.worst(2) + 0.005      # room for one call at its most, not a second
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            tempfile.tempdir = str(scratch)
            log = []
            ai = collect.AIRun(cap, post=post, log=log.append)
            collect.describe_all(log.append, ai=ai)
            first = len(sent)
            again = collect.AIRun(1.0, post=post, log=log.append)
            collect.describe_all(log.append, ai=again)      # a later run with room pays only for what's left
        finally:
            os.environ["OPENAI_API_KEY"] = ""
            tempfile.tempdir = real_dir
        one, two = (json.loads((collect.DESCRIPTIONS / f"S00{i}.json").read_text()) for i in (1, 2))
        assert first == 1, (first, log)
        assert ai.stopped and ai.budget.spent <= cap, (ai.budget.spent, cap)
        assert "roles" in one["have"] and one["editor"]["cost"] == 0.015, one.get("editor")
        assert [s["role"] for s in one["shots"]] == ["step", "payoff"]
        assert any("about $" in x and "spent so far" in x for x in log), log   # the estimate, before the call
        assert any("past the cap" in x for x in log), log
        assert len(sent) == 2 and "roles" in two["have"], (len(sent), two["have"])   # S001 not paid for twice
        assert any(c.get("type") == "image_url" for c in sent[0]["messages"][1]["content"])
        assert _left(scratch) == [], _left(scratch)
        assert clip.exists()


def test_a_failed_download_is_tried_once_more() -> None:
    """Her Mac, 2026-10-21: yt-dlp died mid-download ("ffmpeg exited with
    code 183") on one vlog. The run goes on, and that vlog is fetched once
    more after the rest; one that fails twice is left for the next run."""
    real = (collect.ytdlp, tempfile.tempdir)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _setup(tmp)
        clip = _clip(tmp / "clip.mp4")
        exe, calls = tmp / "yt-dlp", tmp / "calls.txt"
        # y/1 fails its first fetch, y/3 every fetch, y/2 never
        exe.write_text(f"#!{sys.executable}\nimport shutil, sys\na = sys.argv\n"
                       f"open({str(calls)!r}, 'a').write(a[-1] + '\\n')\n"
                       f"n = open({str(calls)!r}).read().split().count(a[-1])\n"
                       "if a[-1].endswith('/3') or (a[-1].endswith('/1') and n == 1):\n"
                       "    sys.stderr.write('ERROR: ffmpeg exited with code 183\\n'); sys.exit(1)\n"
                       f"shutil.copy({str(clip)!r}, a[a.index('-o') + 1].replace('%(ext)s', 'mp4'))\n")
        exe.chmod(0o755)
        scratch = tmp / "scratch"
        scratch.mkdir()
        _rows_csv([_row(i, f"https://y/{i}", "measured") for i in (1, 2, 3)])
        log = []
        try:
            tempfile.tempdir = str(scratch)
            collect.ytdlp = lambda: str(exe)
            collect.describe_all(log.append)
        finally:
            collect.ytdlp, tempfile.tempdir = real
        assert calls.read_text().split() == ["https://y/1", "https://y/2", "https://y/3",
                                             "https://y/1", "https://y/3"], calls.read_text()
        assert sorted(p.name for p in collect.DESCRIPTIONS.iterdir()) == ["S001.json", "S002.json"], log
        assert sum("trying the download once more" in x for x in log) == 2, log
        assert any(x.startswith("S003: not described (the download failed, yt-dlp exit 1)") for x in log), log
        assert not any("Command '[" in x for x in log), log      # her screen shows yt-dlp's own error above
        assert _left(scratch) == [], _left(scratch)


def _alive(pid: int) -> bool:
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")       # a zombie has stopped; only its exit is unread


def test_a_stalled_download_leaves_nothing_running() -> None:
    """The Mac's yt-dlp is a bundled app: the process the collector starts
    hands the download (and ffmpeg) to a child. Giving up on a stalled one
    killed only the first, and the rest ran on for 18 hours (her Mac,
    2026-10-21). Now the whole group stops."""
    real = (collect.ytdlp, collect.DOWNLOAD_S)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        exe, pidf = tmp / "yt-dlp", tmp / "child.pid"
        exe.write_text(f"#!{sys.executable}\nimport subprocess, sys, time\n"
                       f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                       f"open({str(pidf)!r}, 'w').write(str(c.pid))\n"
                       "time.sleep(60)\n")
        exe.chmod(0o755)
        (tmp / "dl").mkdir()
        try:
            collect.ytdlp = lambda: str(exe)
            collect.DOWNLOAD_S = 2
            try:
                collect._download(_row(1, "https://y/1", "measured"), tmp / "dl")
            except subprocess.TimeoutExpired:
                pass
            else:
                raise AssertionError("a stalled download wasn't given up on")
        finally:
            collect.ytdlp, collect.DOWNLOAD_S = real
        child = int(pidf.read_text())
        for _ in range(20):
            if not _alive(child):
                break
            time.sleep(0.1)
        assert not _alive(child), "the download's child process is still running"


def test_the_cap_counts_earlier_runs() -> None:
    """Running the same line again after a stop never spends past --cap:
    every paid call is in the ledger (at its most until its real cost is
    known), and calls from before the ledger count from their descriptions."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _setup(tmp)
        assert collect.spent_so_far() == 0.0             # nothing yet
        collect.DESCRIPTIONS.mkdir()
        # the first run (no ledger yet): its costs are on the descriptions
        (collect.DESCRIPTIONS / "L001.json").write_text(json.dumps({"editor": {"cost": 0.2}}))
        (collect.DESCRIPTIONS / "L004.json").write_text(json.dumps({"editor": {"cost": 0.05}}))
        (collect.DESCRIPTIONS / "S001.json").write_text(json.dumps({"have": ["motion"]}))   # never read by the AI
        (collect.DESCRIPTIONS / "bad.json").write_text("{")
        assert collect.spent_so_far() == 0.25, collect.spent_so_far()
        with (collect.DESCRIPTIONS / "spend.jsonl").open("w") as f:
            f.write(json.dumps({"call": "a", "id": "L008", "upto": 0.15}) + "\n")
            f.write(json.dumps({"call": "a", "id": "L008", "cost": 0.08}) + "\n")   # answered: its real cost
            f.write(json.dumps({"call": "b", "id": "L009", "upto": 0.12}) + "\n")   # lost with the run: at its most
            f.write("half a line\n")
        assert collect.spent_so_far() == 0.45, collect.spent_so_far()
        ai = collect.AIRun(0.45 + editor.worst(2) * 0.5, post=lambda *a: None, spent=collect.spent_so_far())
        assert not ai.affords(2) and ai.budget.calls == 0
        assert collect.AIRun(0.45 + editor.worst(2) * 1.5, post=lambda *a: None, spent=0.45).affords(2)


def test_a_failed_call_is_counted_and_not_asked_twice() -> None:
    """A paid answer that came back broken (cut off, not a breakdown) still
    costs: it's in the ledger, the next run starts from it, and one run asks
    about a video once, however many times it is described."""
    sent = []

    def post(url, body, headers):
        sent.append(body)
        return {"model": "gpt-6.1-sol", "usage": {"prompt_tokens": 3000, "completion_tokens": 900},
                "choices": [{"message": {"content": "{\"premise\": "}, "finish_reason": "length"}]}
    real_dir = tempfile.tempdir
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _setup(tmp)
        clip = _clip(tmp / "clip.mp4")
        scratch = tmp / "scratch"
        scratch.mkdir()
        _rows_csv([_row(1, str(clip), "listed")])
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            tempfile.tempdir = str(scratch)
            log = []
            ai = collect.AIRun(1.0, post=post, log=log.append)
            collect.measure_all(log.append, describe=True, ai=ai)   # measured, described, asked once
            collect.describe_all(log.append, ai=ai)                  # same run: not asked again
            first = len(sent)
            spent = collect.spent_so_far()
            again = collect.AIRun(spent + editor.worst(2) * 0.5, post=post, log=log.append, spent=spent)
            collect.describe_all(log.append, ai=again)               # next run: no room left for it
        finally:
            os.environ["OPENAI_API_KEY"] = ""
            tempfile.tempdir = real_dir
        assert first == 1, (first, log)
        assert spent == 0.015 and ai.budget.spent == 0.015, (spent, ai.budget.spent)
        assert len(sent) == 1 and again.stopped, (len(sent), log)
        assert _left(scratch) == [], _left(scratch)


def test_a_hangup_stops_the_download_too() -> None:
    """yt-dlp now runs in its own group, so a closed Terminal window no
    longer reaches it directly: the collector turns the hangup into an exit
    that stops yt-dlp's group and removes its temp folder."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        exe, pidf, code = tmp / "yt-dlp", tmp / "child.pid", tmp / "run.py"
        exe.write_text(f"#!{sys.executable}\nimport subprocess, sys, time\n"
                       f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                       f"open({str(pidf)!r}, 'w').write(str(c.pid))\n"
                       "time.sleep(60)\n")
        exe.chmod(0o755)
        root = Path(__file__).resolve().parents[1]
        code.write_text(
            f"import signal, sys, tempfile\nsys.path.insert(0, {str(root)!r})\n"
            f"tempfile.tempdir = {str(tmp)!r}\n"
            "from taste import collect\n"
            f"collect.ytdlp = lambda: {str(exe)!r}\n"
            "for s in (signal.SIGHUP, signal.SIGTERM):\n    signal.signal(s, collect._quit)\n"
            "row = {'id': 'L001', 'group': 'short', 'url_or_file': 'https://y/1'}\n"
            "collect._fetch_and_describe(row, print, None)\n")
        p = subprocess.Popen([sys.executable, str(code)])
        for _ in range(100):
            if pidf.exists() and pidf.read_text():
                break
            time.sleep(0.1)
        child = int(pidf.read_text())
        p.send_signal(__import__("signal").SIGHUP)
        assert p.wait(timeout=10) == 128 + 1, p.returncode
        for _ in range(20):
            if not _alive(child):
                break
            time.sleep(0.1)
        assert not _alive(child), "the download kept running after the hangup"
        assert not [x for x in tmp.iterdir() if x.name.startswith("taste-")], list(tmp.iterdir())


def test_a_creator_learnt_from_is_not_looked_up_again() -> None:
    # channel names differ from the names listed (seen on her Mac, 2026-10-21)
    for listed, channel in [("Her 86m2 (Thuy Dao)", "Her 86m2"), ("sueddu (슛뚜)", "슛뚜sueddu"),
                            ("Alisha Marie", "AlishaMarieVlogs"), ("Catherine Manning", "Cathrin Manning")]:
        assert collect._same(listed, channel), (listed, channel)
    assert not collect._same("Emma Chamberlain", "Emma Watson") and not collect._same("Ann", "Anna Bey")
    with tempfile.TemporaryDirectory() as t:
        _setup(Path(t))
        collect.CREATORS.write_text(
            "group,creator,platform,size_as_reported,why_listed,where_found,status\n"
            "long,Her 86m2 (Thuy Dao),YouTube,,,,discovered\nlong,Some One,YouTube,,,,discovered\n"
            "short,kelwak,TikTok,,,,discovered\n")
        row = dict.fromkeys(HEAD, "")
        row.update(id="L001", group="long", url_or_file="https://y/1", creator="Her 86m2", source="web", status="measured")
        short = dict(row, id="S001", group="short", url_or_file="https://www.tiktok.com/@kelwak/video/1", creator="KELLY WAKASA")
        with collect.GROUPS["long"].open("a") as f:
            csv.DictWriter(f, HEAD).writerow(row)
        with collect.GROUPS["short"].open("a") as f:
            csv.DictWriter(f, HEAD).writerow(short)
        origin, collect._origin_rows = collect._origin_rows, lambda path: []
        try:
            collect.sync(lambda s: None)
        finally:
            collect._origin_rows = origin
        st = {r["creator"]: r["status"] for r in csv.DictReader(collect.CREATORS.open())}
        assert st == {"Her 86m2 (Thuy Dao)": "discovered", "Some One": "candidate", "kelwak": "discovered"}, st
        assert collect._off(row, {"Her 86m2 (Thuy Dao)"}) and not collect._off(row, {"Some One"})


def test_a_handle_is_opened_without_a_search() -> None:
    def no_search(args, timeout=120):
        raise AssertionError(f"searched: {args}")
    real, collect._json = collect._json, no_search
    try:
        assert collect._channel("@KatieFeeney", "YouTube", "short") == "https://www.youtube.com/@KatieFeeney/shorts"
        assert collect._channel("hubs.life", "TikTok", "short") == "https://www.tiktok.com/@hubs.life"
    finally:
        collect._json = real
    assert collect._same("@KatieFeeney", "Katie Feeney")   # her rows carry the channel's name


def test_a_not_a_vlog_call_from_the_thread_wins() -> None:
    with tempfile.TemporaryDirectory() as t:
        _setup(Path(t))
        row = dict.fromkeys(HEAD, "")
        row.update(id="S001", group="short", url_or_file="https://y/9", creator="Some One", source="web",
                   verdict="good", status="measured")
        with collect.GROUPS["short"].open("a") as f:
            csv.DictWriter(f, HEAD).writerow(row)
        judged = dict(row, status="not a vlog", notes="a sports clip")
        origin, collect._origin_rows = collect._origin_rows, (
            lambda path: [judged] if path == collect.GROUPS["short"] else [])
        try:
            collect.sync(lambda s: None)
        finally:
            collect._origin_rows = origin
        got = list(csv.DictReader(collect.GROUPS["short"].open()))[0]
        assert (got["status"], got["notes"]) == ("not a vlog", "a sports clip"), got


def test_accurate_ocr_says_which_frames_went_unread() -> None:
    """--text2 runs in its own chunks; a chunk that hangs comes back as
    unread frames (words unknown), not as frames with no words, and what it
    read before the hang still counts."""
    real = (vision.ensure_built, vision.TEXT2_CHUNK, vision.TEXT2_TIMEOUT_S)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        exe, modes = tmp / "vibevision", tmp / "modes.txt"
        exe.write_text(f"#!{sys.executable}\nimport json, sys, time\n"
                       f"open({str(modes)!r}, 'a').write(sys.argv[1] + '\\n')\n"
                       "for p in sys.argv[2:]:\n"
                       "    if 'hang' in p:\n        time.sleep(30)\n"
                       "    print(json.dumps({'path': p, 'items': [] if 'blank' in p else "
                       "[{'text': 'x', 'box': [0, 0, 1, 0.1], 'conf': 0.9}]}), flush=True)\n")
        exe.chmod(0o755)
        try:
            vision.ensure_built = lambda: exe
            vision.TEXT2_CHUNK, vision.TEXT2_TIMEOUT_S = 2, 2
            paths = ["a.jpg", "blank.jpg", "c.jpg", "hang.jpg", "d.jpg"]
            found, failed = vision.text(paths, accurate=True)
            fast = vision.text(["a.jpg", "blank.jpg"])
        finally:
            vision.ensure_built, vision.TEXT2_CHUNK, vision.TEXT2_TIMEOUT_S = real
        assert failed == ["hang.jpg"], failed
        assert sorted(found) == ["a.jpg", "blank.jpg", "c.jpg", "d.jpg"] and found["blank.jpg"] == [], found
        assert isinstance(fast, dict) and sorted(fast) == ["a.jpg", "blank.jpg"]   # the default reader is as it was
        assert sorted(set(modes.read_text().split())) == ["--text", "--text2"]


def test_ai_needs_a_cap_and_a_key() -> None:
    for argv in (["--ai"], ["--ai", "--cap", "0"], ["--ai", "--cap", "2.5"]):   # the last: no key here
        try:
            collect.main(argv)
        except SystemExit as e:
            assert e.code == 2, (argv, e.code)
        else:
            raise AssertionError(f"{argv} ran")


if __name__ == "__main__":
    test_fingerprint_is_the_good_videos_middle()
    test_vlog_filter()
    test_discover_learns_from_the_most_watched_vlogs()
    test_measure_keeps_numbers_only()
    test_describe_keeps_numbers_and_labels_only()
    test_ai_editor_stops_at_the_cap()
    test_a_failed_download_is_tried_once_more()
    test_a_stalled_download_leaves_nothing_running()
    test_the_cap_counts_earlier_runs()
    test_a_failed_call_is_counted_and_not_asked_twice()
    test_a_hangup_stops_the_download_too()
    test_a_creator_learnt_from_is_not_looked_up_again()
    test_a_handle_is_opened_without_a_search()
    test_a_not_a_vlog_call_from_the_thread_wins()
    test_accurate_ocr_says_which_frames_went_unread()
    test_ai_needs_a_cap_and_a_key()
    print("ok")
