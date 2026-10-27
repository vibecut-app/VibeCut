"""Follow the voiceover: the creator's own narration as the spine of the edit.

Adapted from the semantic-anchor method in montage-vlog-compiler (MIT; see
NOTICE). It is opt-in: VibeCut's default path needs no transcript, because
most vlog footage has none. But when the creator has recorded narration --
or written one -- the words decide what is on screen and for how long, and
footage that matches nothing said is decoration.

What is taken from the method, and why:

- **The voice sets the time.** Each line holds the screen from when it
  starts until the next begins. Picture is cut to the words, not the other
  way round.
- **What is said decides what is shown.** A line that names something
  filmable (food, the sea, a temple, people) is matched to shots whose
  on-device labels say so. The labels only *recall* candidates; which one
  is used is decided by how well it is made, never by the label's own
  confidence -- a confident label is still a guess about the picture.
- **A gap is a gap.** A line nothing on the shelf shows -- or an abstract
  line ("I finally felt free") that needs an action, a reaction or a place
  to stand for it -- is left as a gap of the right length and listed, not
  covered with a pretty unrelated shot. Covering it hides the problem in
  the film; listing it lets the creator film one or choose one.
- **The same clip doesn't play twice in a row**, and a long line is split
  across a few shots rather than chopped into fragments.
- **Timing says where it came from.** A subtitle file gives `estimated`
  timing (it was never checked against the recording); a plain script
  gives `text_only` (lengths guessed from word counts). Nothing here ever
  claims the picture is locked to the voice -- only watching it can.
"""

from __future__ import annotations

import re

from . import storyboard as sb

MIN_SHOT_S = 1.5        # shorter than this is a flash, not a shot
SHOT_EVERY_S = 3.0      # a long line gets roughly one shot per this much
CJK_PER_S = 4.0         # spoken Mandarin, characters per second
WORDS_PER_S = 2.5       # spoken English, words per second

# Chinese words for the same themes the direction line understands.
ZH = {
    "吃": "food", "美食": "food", "饭": "food", "餐": "food", "咖啡": "food", "早餐": "food",
    "甜品": "food", "面": "food", "小吃": "food", "市场": "food", "菜": "food",
    "海": "sea", "沙滩": "sea", "海边": "sea", "船": "sea",
    "夜": "night", "晚上": "night", "灯": "night", "烟花": "night",
    "寺": "temple", "神社": "temple", "庙": "temple", "教堂": "temple",
    "猫": "animal", "狗": "animal", "鸟": "animal", "动物": "animal",
    "朋友": "people", "家人": "people", "宝宝": "people", "孩子": "people", "妈妈": "people",
    "爸爸": "people", "人群": "people",
    "山": "nature", "花": "nature", "树": "nature", "公园": "nature", "湖": "nature", "河": "nature",
    "街": "city", "城市": "city", "地铁": "city", "车站": "city", "楼": "city",
    "音乐": "music", "演出": "music", "唱": "music", "跳舞": "dance",
}

TC = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
CUE = re.compile(rf"{TC}\s*-->\s*{TC}")


def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def _speak_time(text: str) -> float:
    cjk = len(re.findall(r"[㐀-鿿]", text))
    words = len(re.findall(r"[A-Za-z0-9']+", text))
    return max(MIN_SHOT_S, cjk / CJK_PER_S + words / WORDS_PER_S)


def parse(text: str) -> dict:
    """Subtitles (SRT / WebVTT) or a plain script -> timed lines."""
    lines: list[dict] = []
    if CUE.search(text):
        for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
            rows = block.strip().split("\n")
            for k, row in enumerate(rows):
                m = CUE.search(row)
                if m:
                    words = " ".join(r.strip() for r in rows[k + 1:] if r.strip())
                    words = re.sub(r"<[^>]+>", "", words).strip()
                    if words:
                        g = m.groups()
                        lines.append({"text": words, "start": _secs(*g[:4]), "end": _secs(*g[4:])})
                    break
        lines.sort(key=lambda x: x["start"])
        timing, source = "estimated", "subtitles"
    else:
        t = 0.0
        for chunk in re.split(r"(?<=[。！？!?；;])|(?<=\.)\s+|\n+", text):
            chunk = (chunk or "").strip()
            if not chunk:
                continue
            d = _speak_time(chunk)
            lines.append({"text": chunk, "start": round(t, 3), "end": round(t + d, 3)})
            t += d
        timing, source = "text_only", "script"
    for i, ln in enumerate(lines):
        # A line holds the screen until the next one starts; the first from 0.
        ln["i"] = i
        ln["from"] = 0.0 if i == 0 else ln["start"]
        ln["to"] = lines[i + 1]["start"] if i + 1 < len(lines) else ln["end"]
    return {"source": source, "timing": timing, "lines": lines,
            "total": round(lines[-1]["to"], 3) if lines else 0.0}


def _labels(text: str, shots: list[sb.Shot]) -> tuple[list[str], set[str]]:
    d = sb.read_direction(text, shots)
    themes, labels = list(d.themes), set(d.labels)
    for zh, theme in ZH.items():
        if zh in text and theme not in themes:
            themes.append(theme)
            labels |= sb.THEMES[theme]
    return themes, labels


def _window(s: sb.Shot, best: float, dur: float) -> tuple[float, float]:
    dur = min(dur, s.duration)
    c = min(max(best, s.start), s.end)
    a = min(max(s.start, c - dur / 2), s.end - dur)
    return round(a, 3), round(a + dur, 3)


def _gap(i: int, k: int, dur: float, why: str) -> dict:
    return {"id": None, "key": f"gap~vo{i}.{k}", "gap": True, "start": 0.0, "end": round(dur, 3),
            "clip_id": None, "thumb": "", "lean": False, "why": why}


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def propose(script: dict, shots: list[sb.Shot], best_t: dict[str, float]) -> dict:
    """The fourth proposal: one part per spoken line."""
    used: set[str] = set()
    prev_clip = None
    beats, gaps, matched = [], [], 0
    for ln in script["lines"]:
        dur = ln["to"] - ln["from"]
        themes, labels = _labels(ln["text"], shots)
        entries, why = [], ""
        if not labels:
            why = "nothing filmable is named — show it with an action, a reaction or a place"
        else:
            recall = [s for s in shots if s.id not in used and any(s.labels.get(l, 0) >= 0.2 for l in labels)]
            pool = sorted((s for s in recall if s.clip_id != prev_clip), key=lambda s: (-s.score, s.order))
            if not recall:
                why = f"nothing on the shelf shows {' / '.join(themes)}"
            elif not pool:
                why = "only the clip just used shows this — film another angle, or accept the repeat"
            else:
                k = max(1, min(len(pool), int(dur // SHOT_EVERY_S) or 1, int(dur // MIN_SHOT_S) or 1))
                picks, left = pool[:k], dur
                for n, s in enumerate(picks):
                    want = left / (len(picks) - n)
                    a, b = _window(s, best_t.get(s.id, (s.start + s.end) / 2), want)
                    entries.append({"id": s.id, "clip_id": s.clip_id, "start": a, "end": b,
                                    "thumb": s.thumb, "lean": True})
                    used.add(s.id)
                    left -= b - a
                prev_clip = picks[-1].clip_id
                if left > 0.05:
                    # the footage that matches runs out before the line does
                    entries.append(_gap(ln["i"], len(entries), left, "the matching footage is shorter than the line"))
                    gaps.append({"line": ln["i"] + 1, "text": ln["text"], "at": ln["from"],
                                 "dur": round(left, 2), "reason": "the matching footage is shorter than the line"})
                matched += 1
        if not entries:
            entries = [_gap(ln["i"], 0, dur, why)]
            gaps.append({"line": ln["i"] + 1, "text": ln["text"], "at": ln["from"], "dur": round(dur, 2),
                         "reason": why})
            prev_clip = None
        title = ln["text"] if len(ln["text"]) <= 48 else ln["text"][:47] + "…"
        detail = f"{_mmss(ln['from'])}–{_mmss(ln['to'])} · " + (
            f"shows {' / '.join(themes)}" if not why else f"gap: {why}")
        beats.append({"title": title, "detail": detail, "lean": not why, "line": ln["text"],
                      "shots": entries})

    n, short = len(script["lines"]), len({g["line"] for g in gaps})
    notes = [{
        "estimated": "Timed from your subtitle file, not from the recording itself — play it "
                     "against the voice before trusting a cut.",
        "text_only": "No recording yet, so each line's length is guessed from its words "
                     "(expect it to be off by 15% or so). Record it and bring the subtitles.",
        "measured": "Timed from a measurement of the recording — trust it.",
    }.get(script["timing"], "No timing information available.")]
    if gaps:
        notes.append(f"{short} of {n} lines aren't (fully) shown by anything on the shelf. They're "
                     "left as gaps of the right length — not covered with something unrelated.")
    return {
        "key": "voice", "name": "Follow the voiceover", "axis": "voice",
        "summary": f"One part per line of your voiceover: {n} lines, {_mmss(script['total'])}; "
                   f"{matched} matched to footage.",
        "notes": notes, "degraded": False, "same_order_as_time": None,
        "timing": script["timing"], "gaps": gaps, "beats": beats,
    }
