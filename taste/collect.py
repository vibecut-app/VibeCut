"""Fill the taste set in one run: counts, downloads, measurements, deletes.

Run on sarah's Mac (yt-dlp, ffmpeg, Vision for the words on screen), from
the repo root:

    .venv/bin/python -m taste.collect            # discover, then measure
    .venv/bin/python -m taste.collect --only measure

Two passes, both resumable (a row's status says how far it got), and
three options:

- discover: for every creator in data/candidate-creators.csv still marked
  `candidate`, list their recent videos of the group's kind (long uploads,
  or Shorts / TikToks), keep the vlogs, read views and likes, and add their
  PER_CREATOR most-watched as good examples. The list is vloggers only, and
  a popular vlogger's vlogs are all worth learning from (sarah, 2026-10-20).
- measure: every row with a link, a verdict and status `listed` is
  downloaded at 480p (long: the first LONG_S seconds), measured
  (taste.measure + words on screen through Vision), and deleted. Only the
  numbers stay, in measurements/<id>.json.

- describe (`--describe`): every measured row is also written down shot
  by shot (taste.describe: lengths, joins, faces, voice, labels, where the
  words sit) in descriptions/<id>.json, from the same download when it is
  measured now, else downloaded once more. Accurate OCR reads Korean,
  Japanese and Chinese captions too; the words are counted and dropped.
- `--ai --cap 2.50`: while a video's frames exist, the AI editor
  (taste.editor) names each shot's job and the chapters. Its estimate is
  printed before every call, the running total after, and nothing is sent
  unless the most it could cost still fits under the cap. The cap is for
  the whole set: every paid call goes into descriptions/spend.jsonl, and
  what earlier runs spent counts, so running the same line again never
  spends past it. What's said (English only, the
  Mac's own recogniser) goes into that one call and nowhere else.
- `--train`: retrain the taste model (taste.model) at the end.

Nothing of anyone's video is kept, and nothing here calls a paid model
unless --ai is given with a cap.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cutgrammar import media, style
from . import measure as measure_mod

HERE = Path(__file__).parent
DATA = HERE / "data"
DESCRIPTIONS = HERE / "descriptions"
GROUPS = {"long": DATA / "long-youtube.csv", "short": DATA / "short-reels.csv"}
CREATORS = DATA / "candidate-creators.csv"
PREFIX = {"long": "L", "short": "S"}

RECENT = 12            # vlogs looked at per creator
PER_CREATOR = 3        # ...of which the most watched are learnt from
LONG_S = 300.0         # a long vlog is measured on its first five minutes (100+ shots;
                       # sarah, 2026-10-20: ten took ~7 min a video on her connection)
LONG_RANGE = (300, 2700)   # what counts as a long vlog, seconds
SHORT_MAX = 180            # ...and a short one
DOWNLOAD_S = 600       # give up on one video's download after this long
FORMAT = "bv*[height<=480]+ba/b[height<=480]/b"
BRANCH = "origin/claude/vlog-taste-model-i4z3mi"
TRANSCRIBE_S = 900     # give up on hearing one video's words after this long (it's only a hint)
AI_FAILS = 2           # this many paid calls failing in a row (a rejected key, no budget) stop the AI

# sarah, 2026-10-20: "filter mainly for vlogs". A creator's channel also
# carries hauls, get-ready-with-me, Q&As and podcasts; those are cut by
# other rules (talking to a mirror, a product on a table) and would teach
# the wrong rhythm. A title has to say it is a vlog, and must not say it
# is one of those.
VLOG = ("vlog", "day in my life", "day in the life", "diml", "a day ", "spend the day", "week in",
        "weekend in", "days in", "trip", "travel", "a week", "24 hours", "morning routine",
        "come with me", "life in", "living in", "college", "uni ", "semester", "study with me")
NOT_VLOG = ("grwm", "get ready with me", "haul", "q&a", "q & a", "podcast", "reaction", "review",
            "unboxing", "makeup tutorial", "storytime", "try on", "try-on", "ranking", "challenge")


def is_vlog(d: dict) -> bool:
    text = " ".join([d.get("title") or "", " ".join(d.get("tags") or []),
                     (d.get("description") or "")[:400]]).lower() + " "
    return any(w in text for w in VLOG) and not any(w in text for w in NOT_VLOG)


def ytdlp() -> str:
    exe = shutil.which("yt-dlp") or "/usr/local/bin/yt-dlp"
    if not Path(exe).exists():
        raise SystemExit("yt-dlp isn't installed")
    return exe


def _run(cmd: list[str], timeout: float, capture: bool = False) -> subprocess.CompletedProcess:
    """yt-dlp in a process group of its own, so giving up on it stops all of
    it: the Mac's yt-dlp is a bundled app whose real work, and the ffmpeg it
    starts, run in child processes that killing yt-dlp alone leaves behind
    (one such download ran on for 18 hours on her Mac, 2026-10-21)."""
    pipe = subprocess.PIPE if capture else None
    p = subprocess.Popen(cmd, stdout=pipe, stderr=pipe, text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except BaseException:      # given up on, or her Ctrl-C: none of it keeps running
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.wait()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _json(args: list[str], timeout: int = 120) -> list[dict]:
    p = _run([ytdlp(), "-j", "--skip-download", "--no-warnings", *args], timeout, capture=True)
    out = []
    for line in p.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def info(url: str) -> dict | None:
    got = _json(["--no-playlist", url])
    return got[0] if got else None


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def _save(path: Path, head: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=head)
        w.writeheader()
        w.writerows(rows)


def _next_id(group: str, rows: list[dict]) -> str:
    n = max([int(r["id"][1:]) for r in rows if r.get("id", "")[1:].isdigit()] or [0])
    return f"{PREFIX[group]}{n + 1:03d}"


def _counts(row: dict, d: dict) -> None:
    row["creator"] = row.get("creator") or d.get("channel") or d.get("uploader") or ""
    row["title"] = row.get("title") or (d.get("title") or "")[:120]
    row["length_s"] = str(d.get("duration") or "")
    row["views"] = str(d.get("view_count") or "")
    row["likes"] = str(d.get("like_count") or "")
    row["counts_read_on"] = time.strftime("%Y-%m-%d")


def _ratio(d: dict) -> float | None:
    v, l = d.get("view_count"), d.get("like_count")
    return l / v if v and l is not None else None


# --- what Claude added on the branch -----------------------------------------

def _origin_rows(path: Path) -> list[dict]:
    """The branch's copy of a list: links sarah sent in the thread, strikes."""
    try:
        rel = path.relative_to(HERE.parent).as_posix()
    except ValueError:
        return []
    p = subprocess.run(["git", "show", f"{BRANCH}:{rel}"], capture_output=True, text=True, cwd=HERE.parent)
    return list(csv.DictReader(p.stdout.splitlines())) if p.returncode == 0 else []


STAGE = {"": 0, "listed": 1, "failed": 1, "not a vlog": 2, "measured": 3}


def sync(log) -> None:
    """Bring in what the branch has without losing what this Mac measured."""
    for path in [*GROUPS.values()]:
        head, rows = _rows(path)
        by_url = {r["url_or_file"]: r for r in rows}
        for o in _origin_rows(path):
            mine = by_url.get(o["url_or_file"])
            if mine is None:
                o = {k: o.get(k, "") for k in head}
                if any(r["id"] == o["id"] for r in rows):
                    o["id"] = _next_id(o["group"], rows)
                rows.append(o)
                log(f"new from the thread: {o['id']} {o['url_or_file']}")
            elif o.get("status") == "not a vlog" and mine.get("status") != "not a vlog":
                # judged in the thread once its reading was seen (a sports clip, an interview)
                mine.update(status="not a vlog", notes=o.get("notes") or mine.get("notes", ""))
            elif STAGE.get(o.get("status", ""), 0) > STAGE.get(mine.get("status", ""), 0):
                mine.update({k: o.get(k, "") for k in head})
            elif o.get("verdict") and o["verdict"] != mine.get("verdict"):
                mine["verdict"] = o["verdict"]     # sarah's call, made in the thread
        _save(path, head, rows)
    head, creators = _rows(CREATORS)
    known = {(c["group"], c["creator"]): c for c in creators}
    for o in _origin_rows(CREATORS):
        c = known.get((o["group"], o["creator"]))
        if c is None:
            creators.append({k: o.get(k, "") for k in head})
        elif o["status"].startswith(("struck", "dropped", "skip")):
            c["status"] = o["status"]          # struck or skipped in the thread
        elif o["status"] != "candidate" and c["status"] == "candidate":
            c["status"] = o["status"]
    # a creator whose picks all turned out not to be vlogs is looked at again
    kept = [(r["creator"], r.get("url_or_file", "").lower()) for path in GROUPS.values() for r in _rows(path)[1]
            if r.get("source") == "web" and r.get("status") != "not a vlog"]
    for c in creators:
        handle = "/@" + c["creator"].strip().lstrip("@").lower() + "/"   # a TikTok link names its handle
        if c["status"] == "discovered" and not any(_same(c["creator"], k) or handle in u for k, u in kept):
            c["status"] = "candidate"
    _save(CREATORS, head, creators)


# --- discover ---------------------------------------------------------------

def _channel(name: str, platform: str, group: str) -> str | None:
    """Where a creator's recent videos of this kind are listed."""
    tab = "/videos" if group == "long" else "/shorts"
    if platform.lower() == "tiktok" and " " not in name.strip():
        return f"https://www.tiktok.com/@{name.strip().lstrip('@')}"
    if platform.lower() == "youtube" and name.strip().startswith("@") and " " not in name.strip():
        return f"https://www.youtube.com/{name.strip()}{tab}"   # a checked handle beats a search by name
    hit = _json(["--flat-playlist", "--playlist-items", "1", f"ytsearch1:{name} vlog"])
    url = hit[0].get("channel_url") if hit else None
    if not url and hit and hit[0].get("url"):
        url = (info(hit[0]["url"]) or {}).get("channel_url")
    if not url:
        return None
    return url.rstrip("/") + tab


def _fits(group: str, d: dict) -> bool:
    s = d.get("duration") or 0
    return LONG_RANGE[0] <= s <= LONG_RANGE[1] if group == "long" else 0 < s <= SHORT_MAX


def _discover_one(c: dict, head: list[str], creators: list[dict], log) -> None:
    """One candidate creator's most-watched recent vlogs, listed as rows."""
    group, name = c["group"], c["creator"]
    where = _channel(name, c.get("platform", ""), group)
    if not where:
        c["status"] = "not found"
        log(f"{name}: channel not found")
        return
    flat = _json(["--flat-playlist", "--playlist-items", f"1:{RECENT * 4}", where], timeout=300)
    vids = []
    for e in flat:
        u = e.get("url") or e.get("webpage_url")
        if not u:
            continue
        d = info(u)
        if d and _fits(group, d) and is_vlog(d) and _ratio(d) is not None:
            vids.append(d)
        if len(vids) >= RECENT:
            break
    if not vids:
        c["status"] = "no vlogs"
        log(f"{name}: no vlogs among the recent videos at {where}")
        return
    # sarah, 2026-10-20: a big vlogger's vlogs are all good examples, so
    # learn from their most-watched recent ones rather than pick a weak one.
    picks = sorted(vids, key=lambda d: d["view_count"], reverse=True)[:PER_CREATOR]
    hd, rows = _rows(GROUPS[group])
    have = {r["url_or_file"] for r in rows}
    for d in picks:
        url = d.get("webpage_url")
        if url in have:
            continue
        row = {k: "" for k in hd}
        row.update(id=_next_id(group, rows), group=group, platform=d.get("extractor_key", "").lower(),
                   url_or_file=url, source="web", verdict="good", status="listed",
                   notes=f"top {PER_CREATOR} by views of {len(vids)} recent vlogs; channel {d.get('channel_follower_count') or '?'}")
        _counts(row, d)
        rows.append(row)
    _save(GROUPS[group], hd, rows)
    c["status"] = "discovered"
    log(f"{name}: " + "; ".join(repr((d.get('title') or '')[:40]) for d in picks))
    _save(CREATORS, head, creators)


def discover(log) -> None:
    head, creators = _rows(CREATORS)
    for c in creators:
        if c.get("status") != "candidate":
            continue
        try:
            _discover_one(c, head, creators, log)
        except Exception as e:   # a lookup that timed out: this creator is tried again next run
            log(f"{c['creator']}: skipped this run ({_why(e)})")
    _save(CREATORS, head, creators)


# --- measure ----------------------------------------------------------------

def _words(path: str, tmp: Path, limit_s: float):
    """Words on screen through the Mac's Vision; None elsewhere."""
    try:
        from web.backend import reference
        return reference.text_events(path, tmp / "text", limit_s)
    except Exception:
        return None


def _download(row: dict, tmp: Path) -> str:
    """The row's video on disk: a link fetched into `tmp` (deleted by the
    caller), or the creator's own file where it is."""
    url = row["url_or_file"]
    if not url.startswith("http"):
        return url
    cmd = [ytdlp(), "-q", "--no-warnings", "--no-playlist", "--socket-timeout", "30", "--retries", "3",
           "-f", FORMAT, "-o", str(tmp / "v.%(ext)s")]
    if row["group"] == "long":
        cmd += ["--download-sections", f"*0-{int(LONG_S)}"]
    # a stalled download (one stuck for hours on her Mac, 2026-10-20) is given up on, not waited for
    r = _run(cmd + [url], DOWNLOAD_S)
    if r.returncode:
        raise subprocess.CalledProcessError(r.returncode, cmd + [url])
    return str(next(p for p in tmp.iterdir() if p.name.startswith("v.")))


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().split("(")[0])   # "Casey Neistat" = "CaseyNeistat"


def _same(listed: str, channel: str) -> bool:
    """A creator as listed and the channel name their videos carry: "Her
    86m2 (Thuy Dao)" / "Her 86m2", "sueddu (슛뚜)" / "슛뚜sueddu", "Alisha
    Marie" / "AlishaMarieVlogs", "Catherine Manning" / "Cathrin Manning".
    Read as different, a creator already learnt from was looked up again on
    every run (2026-10-21)."""
    a, b = _key(listed), _key(channel)
    if not a or not b:
        return False
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def _struck() -> set[str]:
    return {_key(c["creator"]) for c in _rows(CREATORS)[1]
            if c["status"].startswith(("struck", "dropped", "skip"))}


def _off(row: dict, off: set[str]) -> bool:
    """A web pick of a creator she struck: neither measured nor described."""
    return row.get("source") == "web" and any(_same(s, row.get("creator", "")) for s in off)


def measure_one(row: dict, log, describe: bool = False, ai: "AIRun | None" = None) -> None:
    url = row["url_or_file"]
    group = row["group"]
    d = None
    tmp = Path(tempfile.mkdtemp(prefix="taste-"))
    try:
        if url.startswith("http") and (not row.get("views") or row.get("source") == "web"):
            d = info(url)
            if d:
                if not row.get("views"):
                    _counts(row, d)
                # picked before the vlog filter, or by a loose title: checked with its tags and description
                if row.get("source") == "web" and not is_vlog(d):
                    row["status"] = "not a vlog"
                    log(f"{row['id']}: not a vlog ({row['title'][:40]!r}), skipped")
                    return
        path = _download(row, tmp)
        limit = LONG_S if group == "long" else None
        m = media.load(path, limit_s=limit)
        s = style.learn(m, text=_words(path, tmp, min(m.duration, limit or m.duration)))
        s["transitions"].pop("list", None)
        if isinstance(s.get("words"), dict):
            s["words"].pop("samples", None)   # the creator's own lines: numbers only leave this run
        rec = {"id": row["id"], "source_name": Path(path).name, "group": group, **s,
               "lufs": media.loudness_lufs(path), "measured_s": round(m.duration, 2),
               "ending_is_cutoff": bool(limit and m.duration >= limit - 1)}
        measure_mod.OUT.mkdir(exist_ok=True)
        (measure_mod.OUT / f"{row['id']}.json").write_text(json.dumps(rec, indent=1, default=float))
        row["status"] = "measured"
        log(f"{row['id']}: {s['pace']['shots'] if s.get('pace') else '?'} shots, "
            f"{(s.get('pace') or {}).get('median_s', '?')} s median, {rec['lufs']} LUFS")
        if describe:
            # from the same download: one fetch a video, however much is read from it
            describe_one(row, path, log, ai=ai, lang=_lang(row, d, ai), loaded=m)
    except Exception as e:   # one bad link (private, login-only) must not stop the batch
        row["status"] = "failed"
        row["notes"] = (row.get("notes", "") + f"; failed {time.strftime('%Y-%m-%d')}: {type(e).__name__}").strip("; ")
        log(f"{row['id']}: failed ({_why(e)})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def measure_all(log, describe: bool = False, ai: "AIRun | None" = None) -> None:
    off = _struck()
    for group, path in GROUPS.items():
        head, rows = _rows(path)
        for row in rows:
            if _off(row, off):
                continue
            if row.get("status") == "listed" and row.get("verdict") in ("good", "ordinary") and row.get("url_or_file"):
                measure_one(row, log, describe=describe, ai=ai)
                _save(path, head, rows)    # after each, so a stop loses one video at most


# --- describe ---------------------------------------------------------------

def _no_words(x) -> None:
    """Belt and braces: whatever a reader hands back, no line anyone wrote
    on screen or said is kept in a description -- only counts and places."""
    if isinstance(x, dict):
        for k in ("text", "transcript", "samples"):
            x.pop(k, None)
        for v in x.values():
            _no_words(v)
    elif isinstance(x, list):
        for v in x:
            _no_words(v)


def _english(lang) -> bool:
    # the Mac's recogniser is asked for en-US; any English reads well enough
    # through it, any other language would come back as nonsense
    return bool(lang) and str(lang).lower().replace("_", "-").split("-")[0] == "en"


def _lang(row: dict, d: dict | None, ai: "AIRun | None") -> str | None:
    """The video's spoken language as the platform reports it -- asked only
    when the AI editor is about to run, since that's all it is for. A
    creator's own file says nothing, so it gets no transcript."""
    if ai is None or ai.stopped or not row["url_or_file"].startswith("http"):
        return None
    try:
        d = d or info(row["url_or_file"])
    except Exception:          # a slow lookup costs the hint, never the video
        return None
    return (d or {}).get("language")


def _transcript(path: str, work: Path, limit_s: float | None, log) -> str | None:
    """What's said, read by the Mac's own recogniser (speech helper), for
    the AI editor's one call. Held in memory only: the sound goes to the
    run's work folder and is deleted, and nothing is cached (the app's
    speech.transcribe would keep it next to a clip)."""
    try:
        from web.backend import speech
        binary = speech.ensure_built()
    except Exception:          # not macOS 26, no toolchain: the editor works from the pictures
        return None
    wav = work / "said.wav"
    head = ["-t", f"{limit_s:.3f}"] if limit_s else []
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", *head, "-i", path, "-vn", "-ac", "1",
                            "-ar", str(speech.SR), "-c:a", "pcm_s16le", str(wav)], capture_output=True)
        if p.returncode:
            return None
        p = subprocess.run([str(binary), str(wav), "en-US"], capture_output=True, text=True, timeout=TRANSCRIBE_S)
    except subprocess.TimeoutExpired:
        log("  what's said wasn't read in time: the editor works from the pictures")
        return None
    finally:
        wav.unlink(missing_ok=True)
    said = []
    for line in p.stdout.splitlines():
        try:
            said.append(str(json.loads(line).get("text") or "").strip())
        except (json.JSONDecodeError, AttributeError):
            pass
    return " ".join(x for x in said if x) or None


def _ledger() -> Path:
    """Every paid call on the set, one line each, kept beside the
    descriptions: what it could cost at most is written before it is sent,
    what it did cost once that's known. A call that dies with the run (a
    closed window, a dropped connection) still counts, at its most."""
    return DESCRIPTIONS / "spend.jsonl"


def _note(rec: dict) -> None:
    DESCRIPTIONS.mkdir(parents=True, exist_ok=True)
    with _ledger().open("a") as f:
        f.write(json.dumps(rec) + "\n")


def spent_so_far() -> float:
    """What the AI editor has cost this set over every earlier run: each
    call at its real cost, or at its most when that never came back. Calls
    from before the ledger (the first run, 2026-10-21) are read from the
    cost their descriptions record."""
    calls: dict[str, float] = {}
    ids = set()
    try:
        lines = _ledger().read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            r = json.loads(line)
            ids.add(r["id"])
            if "cost" in r:
                calls[r["call"]] = float(r["cost"])
            else:
                calls.setdefault(r["call"], float(r["upto"]))
        except (ValueError, KeyError, TypeError):
            continue
    total = sum(calls.values())
    for f in sorted(DESCRIPTIONS.glob("*.json")) if DESCRIPTIONS.is_dir() else []:
        if f.stem in ids:
            continue
        try:
            c = (json.loads(f.read_text()).get("editor") or {}).get("cost")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(c, (int, float)) and c > 0:
            total += float(c)
    return round(total, 4)


class AIRun:
    """The AI editor over one collect run (--ai --cap): the estimate is
    printed before each call, the real cost counted after, and no call is
    made unless the most it could cost still fits under the cap, which is
    for the whole set (earlier runs' calls count). One video is asked at
    most once a run. `post` stands in for the network in tests."""

    def __init__(self, cap: float, post=None, log=print, spent: float = 0.0) -> None:
        from . import editor
        self.budget = editor.Budget(cap)
        self.budget.spent = float(spent)     # earlier runs' calls on this set count against the cap
        self.post = post
        self.log = log
        self.stopped = False
        self.fails = 0
        self.asked: set[str] = set()

    def affords(self, n_shots: int) -> bool:
        from . import editor
        return self.budget.can(editor.worst(n_shots))

    def stop(self, why: str) -> None:
        self.stopped = True
        self.log(f"AI editor stopped: {why} (${self.budget.spent:.3f} of ${self.budget.cap:.2f} spent, "
                 f"{self.budget.calls} call{'s' * (self.budget.calls != 1)})")

    def edit(self, desc: dict, stills: list, path: str, work: Path, limit_s: float | None,
             lang: str | None) -> dict:
        """desc with the editor's roles and chapters, or as it was when the
        cap is reached or the call fails (the description is kept either way)."""
        from web.backend import oai
        from . import editor
        vid, n = desc.get("id") or "?", len(desc.get("shots") or [])
        if self.stopped or vid in self.asked:
            return desc
        if not self.budget.can(editor.worst(n)):
            self.stop(f"{vid} could cost up to ${editor.worst(n):.3f}, past the cap")
            return desc
        said = _transcript(path, work, limit_s, self.log) if _english(lang) else None
        if not (said and self.budget.can(editor.worst(n, len(said)))):
            said = None        # what's said is a hint: dropped before the cap is
        chars = len(said) if said else 0
        est, most = editor.estimate(n, chars), editor.worst(n, chars)
        self.log(f"{vid}: AI editor on {n} shots{' and what is said' if said else ''}, about ${est:.3f} "
                 f"(${self.budget.spent:.3f} of ${self.budget.cap:.2f} spent so far)")
        self.asked.add(vid)
        call = f"{vid} {time.strftime('%Y-%m-%dT%H:%M:%S')} {len(self.asked)}"
        try:
            _note({"call": call, "id": vid, "upto": round(most, 4)})
            answer, usage = editor.breakdown(desc, stills, transcript=said, post=self.post)
        except editor.EditorError as e:      # nothing was sent
            _note({"call": call, "id": vid, "cost": 0.0})
            self.log(f"{vid}: AI editor not asked ({e})")
            return desc
        except oai.OAIError as e:
            # an answer that came back says what it cost; a lost one counts at its most
            known = isinstance(e.usage, dict) and e.usage.get("cost") is not None
            cost = self.budget.spend(e.usage if known else most)
            if known:
                _note({"call": call, "id": vid, "cost": round(cost, 6)})
            self.fails += 1
            self.log(f"{vid}: AI editor failed ({e}), cost ${cost:.3f}")
            if self.fails >= AI_FAILS:
                self.stop(f"{self.fails} calls failed in a row")
            return desc
        except Exception as e:               # sent, maybe paid for, never answered: counted at its most
            self.budget.spend(most)
            self.fails += 1
            self.log(f"{vid}: AI editor failed ({type(e).__name__}: {str(e)[:120]}), counted at ${most:.3f}")
            if self.fails >= AI_FAILS:
                self.stop(f"{self.fails} calls failed in a row")
            return desc
        self.fails = 0
        known = isinstance(usage, dict) and usage.get("cost") is not None
        cost = self.budget.spend(usage if known else most)
        if known:
            _note({"call": call, "id": vid, "cost": round(cost, 6)})
        out = editor.apply(desc, answer, usage)
        self.log(f"{vid}: {out['editor'].get('roles_given', 0)} shots given a job, "
                 f"{len(out['editor'].get('chapters') or [])} chapter(s); cost ${cost:.3f}, "
                 f"${self.budget.spent:.3f} of ${self.budget.cap:.2f} spent")
        return out


def describe_one(row: dict, path: str, log, ai: AIRun | None = None, lang: str | None = None,
                 loaded=None) -> bool:
    """descriptions/<id>.json from a video on disk. Its frames (2 fps, for
    Vision and the AI editor) live in a work folder deleted here; only the
    description's numbers and labels are written. -> written or not; a
    failure is logged and never stops the batch. `loaded`: the video as
    measure_one already read it (same limit), so it isn't decoded twice."""
    from web.backend import vision
    from . import describe
    if sys.platform == "darwin" and vision.ensure_built() is None:
        # a Vision helper that didn't build would leave descriptions with no
        # faces, labels or words, and a written description is never redone
        log(f"{row['id']}: not described: the Vision helper didn't build on this Mac ({vision.status()})")
        return False
    work = Path(tempfile.mkdtemp(prefix="taste-describe-"))
    try:
        limit = LONG_S if row["group"] == "long" else None
        # frames only where something reads them: Vision on the Mac, the editor's stills
        frames = work / "frames" if (vision.ensure_built() is not None or ai is not None) else None
        desc, extras = describe.from_video(path, id=row["id"], group=row["group"], limit_s=limit,
                                           workdir=frames, mac=True, log=log, loaded=loaded)
        if ai is not None:
            desc = ai.edit(desc, extras.get("stills") or [], path, work, limit, lang)
        _no_words(desc)
        DESCRIPTIONS.mkdir(parents=True, exist_ok=True)
        describe.save(desc, DESCRIPTIONS / f"{row['id']}.json")
        log(f"{row['id']}: described, {len(desc['shots'])} shots ({', '.join(desc['have']) or 'nothing read'})")
        return True
    except Exception as e:   # the measurement stands; the next --describe run tries again
        log(f"{row['id']}: not described ({type(e).__name__}: {str(e)[:120]})")
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _needs(row: dict, ai: AIRun | None) -> bool:
    """A measured row still to describe: no description yet, or (with the
    AI editor) one the editor hasn't read and the cap can still pay for."""
    from . import describe
    out = DESCRIPTIONS / f"{row['id']}.json"
    if not out.exists():
        return True
    if ai is None or ai.stopped or row["id"] in ai.asked:
        return False           # one paid look a video a run
    try:
        old = describe.load(out)
    except (OSError, ValueError):
        return True
    from . import editor
    n = len(old.get("shots") or [])
    if "roles" in (old.get("have") or []) or old.get("editor") or n < editor.MIN_SHOTS:
        return False           # read already (if it named no jobs, asking again won't help), or too few shots
    if not ai.affords(n):
        ai.stop(f"{row['id']} could cost up to ${editor.worst(n):.3f}, past the cap")
        return False
    return True


def _why(e: Exception) -> str:
    """A failed fetch in words: yt-dlp's own error is already on screen above."""
    if isinstance(e, subprocess.TimeoutExpired):
        return f"the download stalled, given up after {int(e.timeout or 0)} s"
    if isinstance(e, subprocess.CalledProcessError):
        return f"the download failed, yt-dlp exit {e.returncode}"
    return f"{type(e).__name__}: {str(e)[:120]}"


def _fetch_and_describe(row: dict, log, ai: AIRun | None) -> bool:
    """One measured row fetched again, described and deleted. -> False
    when the fetch itself failed, which is worth another try."""
    tmp = Path(tempfile.mkdtemp(prefix="taste-"))
    try:
        lang = _lang(row, None, ai)
        try:
            path = _download(row, tmp)
        except Exception as e:   # a link gone private, a dropped connection: tried again
            log(f"{row['id']}: not described ({_why(e)})")
            return False
        describe_one(row, path, log, ai=ai, lang=lang)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def describe_all(log, ai: AIRun | None = None) -> None:
    """Every measured row without a description (or without the editor's
    roles, under --ai) is fetched again, described and deleted. Resumable:
    the description file is the record that it's done. A fetch that fails
    is tried once more at the end of the run: a connection that dropped
    mid-download (her Mac, 2026-10-21) is usually back by then."""
    off = _struck()
    todo = []
    for group, path in GROUPS.items():
        _, rows = _rows(path)
        todo += [r for r in rows if r.get("status") == "measured" and r.get("url_or_file") and not _off(r, off)]
    again = [r for r in todo if _needs(r, ai) and not _fetch_and_describe(r, log, ai)]
    for row in again:
        if _needs(row, ai):
            log(f"{row['id']}: trying the download once more")
            _fetch_and_describe(row, log, ai)


def _quit(signum, frame) -> None:
    # a closed Terminal window or a kill stops the run the way Ctrl-C does:
    # yt-dlp runs in its own group (_run), so it is stopped from here, and
    # every temp folder is removed on the way out
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m taste.collect")
    ap.add_argument("--only", choices=["discover", "measure"])
    ap.add_argument("--describe", action="store_true",
                    help="also write each measured video down shot by shot (descriptions/<id>.json)")
    ap.add_argument("--ai", action="store_true",
                    help="the paid AI editor names each shot's job while the frames exist (needs --cap)")
    ap.add_argument("--cap", type=float,
                    help="the most the AI editor may have spent on the set, in dollars, earlier runs included")
    ap.add_argument("--train", action="store_true", help="retrain the taste model at the end")
    a = ap.parse_args(argv)
    if argv is None:           # the command line, not a test calling in
        for sig in (signal.SIGHUP, signal.SIGTERM):
            signal.signal(sig, _quit)
    log = lambda s: print(s, flush=True)
    ai = None
    if a.ai:
        # no paid call without a yes: the flag is the yes, the cap its limit
        if a.cap is None or a.cap <= 0:
            ap.error("--ai needs --cap <dollars>, the most the AI editor may spend on the set")
        from web.backend import oai
        if not oai.has_key():
            ap.error("--ai needs OPENAI_API_KEY in web/.env")
        before = spent_so_far()
        ai = AIRun(a.cap, log=log, spent=before)
        log(f"AI editor on {oai.model()}, up to ${a.cap:.2f} in all"
            + (f"; ${before:.3f} of it spent by earlier runs" if before else ""))
    describe = a.describe or a.ai
    sync(log)
    if a.only != "measure":
        discover(log)
    if a.only != "discover":
        measure_all(log, describe=describe, ai=ai)
        if describe:
            describe_all(log, ai=ai)
    if ai is not None:
        log(f"AI editor: {ai.budget.calls} call{'s' * (ai.budget.calls != 1)} this run, "
            f"${ai.budget.spent:.3f} of ${ai.budget.cap:.2f} spent on the set")
    if a.train:
        from . import model
        model.main(["train"])
    log("done")


if __name__ == "__main__":
    main()
