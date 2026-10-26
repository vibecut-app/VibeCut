"""Captions of what's said in a vlog: subtitles from the Mac's own recogniser.

The "Transcribe" answer to the captions question. Only clips where a voice
is heard (sound.py's reading; the level-based talking signal where there is
none) are transcribed, by Apple's SpeechTranscriber on this Mac (speech.py,
cached per clip): no audio leaves it, no key, no cost. Each storyboard shot
gets the words spoken inside its kept range, broken into short lines where
the speaker pauses or a sentence ends, each timed to its own words and
anchored to the shot, so it moves with it.

This is subtitling, not editing by transcript: the words never decide what
is cut (CLAUDE.md, non-goals). Talking-head mode (talk.py) is the one that
cuts by words.
"""

from __future__ import annotations

import re
import threading

import numpy as np

from cutgrammar import trim
from cutgrammar.signals import ClipSignals

LINE_LATIN = 42      # characters per subtitle line [prior]
LINE_CJK = 16
GAP_S = 0.6          # a pause this long starts a new line [prior]
MIN_DUR, MAX_DUR = 0.8, 4.5
VOICE = 0.25         # mean voice probability over a clip for it to be worth transcribing [prior]
UNSURE = 0.5         # a word the recogniser is less sure of than this is marked for the creator to check [prior]
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_WORD = re.compile(r"[\w぀-ヿ㐀-鿿가-힯]")
_PUNCT = " ,.;:!?\"'()，。！？、；：（）「」"


def locale_for(about: str) -> str:
    """The recogniser's language: Chinese when the creator writes in it."""
    return "zh-CN" if _CJK.search(about or "") else "en-US"


def has_voice(rec: dict) -> bool:
    snd = rec.get("sound") or {}
    if snd.get("voice"):
        return float(np.mean(snd["voice"])) >= VOICE
    try:
        return trim.is_talking(ClipSignals.from_json(rec["signals"]))
    except (KeyError, TypeError):
        return False


def lines(words: list[dict], cjk: bool) -> list[list[dict]]:
    """Words ({t, s, e, n: sentence}) -> subtitle lines."""
    out: list[list[dict]] = []
    limit = LINE_CJK if cjk else LINE_LATIN
    for w in words:
        cur = out[-1] if out else None
        if cur and w["n"] == cur[-1]["n"] and w["s"] - cur[-1]["e"] < GAP_S \
                and len(join(cur + [w], cjk)) <= limit:
            cur.append(w)
        else:
            out.append([w])
    return out


def join(ws: list[dict], cjk: bool) -> str:
    return ("".join(w["t"].strip() for w in ws) if cjk else " ".join(w["t"].strip() for w in ws)).strip()


def unsure(ws: list[dict]) -> list[str]:
    """The words of a line the recogniser wasn't sure of, in order, once
    each. A guess shown as a subtitle reads as fact to a viewer; the creator
    knows what they said, so these are pointed out for them to fix. A word
    with no confidence at all (an older cache, another helper) isn't marked:
    unknown is not uncertain."""
    out: list[str] = []
    for w in ws:
        c = w.get("c")
        t = w["t"].strip().strip(_PUNCT)
        # punctuation comes as runs of its own, often doubted: not a word to check
        if c is not None and float(c) < UNSURE and _WORD.search(t) and t not in out:
            out.append(t)
    return out


def caption_ops(board: dict, cat, clips: dict[str, dict], about: str = "",
                transcribe=None) -> tuple[list[dict], list[str]]:
    """-> (add_overlay ops, notes). `transcribe(rec, locale)` stands in for
    speech.transcribe in tests."""
    from . import speech
    transcribe = transcribe or speech.transcribe
    loc = locale_for(about)
    cjk = loc == "zh-CN"
    heard: dict[str, list[dict]] = {}
    failed: list[str] = []
    ops: list[dict] = []
    doubtful = 0
    for bt in board.get("beats", []):
        for e in bt["shots"]:
            if e.get("gap") or not e.get("id"):
                continue
            s = cat.shots.get(e["id"])
            rec = clips.get(s.clip_id) if s else None
            if not rec or not has_voice(rec):
                continue
            if rec["id"] not in heard:
                try:
                    said = transcribe(rec, loc)
                except speech.SpeechError as err:
                    failed.append(f"{rec['name']} ({err})" if "macOS" in str(err) else rec["name"])
                    said = []
                heard[rec["id"]] = [{**w, "n": n} for n, r in enumerate(said) for w in r["words"]]
            a, b = float(e["start"]), float(e["end"])
            inside = [w for w in heard[rec["id"]] if w["s"] >= a - 0.05 and w["e"] <= b + 0.05]
            ls = lines(inside, cjk)
            for i, ln in enumerate(ls):
                at = max(0.0, ln[0]["s"] - a)
                end = min(ln[-1]["e"] + 0.15, b)
                if i + 1 < len(ls):
                    end = min(end, ls[i + 1][0]["s"])
                dur = min(max(end - a - at, MIN_DUR), MAX_DUR, (b - a) - at)
                text = join(ln, cjk)
                if text and dur > 0.2:
                    op = {"op": "add_overlay", "kind": "caption", "text": text[:140], "heard": True,
                          "anchor": {"to": "shot", "id": e.get("key") or e["id"]},
                          "at": round(at, 2), "dur": round(dur, 2)}
                    if (us := unsure(ln)):
                        op["unsure"] = us
                        doubtful += len(us)
                    ops.append(op)
    notes = []
    if failed:
        notes.append(f"Couldn't transcribe {len(failed)} clip{'s' * (len(failed) != 1)}: {', '.join(failed[:3])}.")
    if doubtful:
        notes.append(f"{doubtful} word{'s' * (doubtful != 1)} weren't heard clearly: they're marked in the "
                     "Captions tab for you to check.")
    if not ops and not failed:
        notes.append("Nobody seems to be talking in the shots this story uses, so there's nothing to subtitle.")
    return ops, notes


def prefetch(clips: list[dict], about: str = "") -> threading.Thread:
    """Start transcribing the clips with a voice in the background, so the
    subtitles are ready by the time a story is chosen. Cached per clip."""
    from . import speech
    loc = locale_for(about)

    def run() -> None:
        for rec in clips:
            if has_voice(rec):
                try:
                    speech.transcribe(rec, loc)
                except Exception:  # noqa: BLE001 -- a clip that fails is reported when captions are made
                    pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
