"""Which do you like better? A few cards after Make, each two versions of the
video that differ in one thing, and her pick teaches the taste model her
own taste (taste/model.py, her layer) -- and, while the video is as Make
left it, puts the version she picked on it.

Why (sarah, 2026-10-21: "make a few cards of would you prefer this version
or the other so we can tailor to the users preference and learn their
preferences"): the model learnt what good vlogs do; only she can say what
she likes. Make already weighs a few one-change versions (tastepick.py);
the cards show her the ones it was least sure of, a part of the video at a
time (the opening, the rhythm, the order, the ending), and keep each pick as
a pair: the version she picked above the other. The next Make reads them.

Each card plays the same few seconds of both versions -- from the shot
before the first difference -- with the sound export would write
(audiomix through /api/mix). Nothing is rendered or decoded here, and
nothing is paid: the versions are re-cuts of moments Make already chose.

A pick changes the video only while nothing else has changed since Make (or
since the last pick): it lands as one turn of its own, so Undo brings the
other version back. After a hand edit the picks still teach, and say so.
"""

from __future__ import annotations

import time

from taste import describe as ds
from taste import model as tm

from . import board as bd, tastepick as tp, timeline

TURN_TEXT = "You picked a version"     # the turn a pick lands as (habits.MACHINE_TEXTS: the cut is the machine's)
KIND, PLAYS = tp.PART, tp.PARTS      # one card per part of the video, in the order it plays
ASK = {"opening": "Which opening do you like better?", "rhythm": "Which rhythm feels better?",
       "order": "Which order feels better?", "ending": "Which ending do you like better?"}
# a version in words, for the line after a pick: "Your video now has <this>."
NAMED = {"held_open": "the longer opening", "runner_up_hook": "the other opening moment",
         "rhythm_by_role": "the rhythm that lingers on the best moments",
         "strongest_last": "each stop ending on its best moment", "filming_order": "each stop in filming order",
         "wide_first": "each stop opening wide", "end_1": "the quicker ending", "end_2": "the ending held two beats",
         "end_3": "the ending held longest"}
FIRST = {"opening": "the opening it had at first", "rhythm": "the rhythm it had at first",
         "order": "the order it had at first", "ending": "the ending it had at first"}
MAX_CARDS = 3        # a few, not a survey [prior]
WINDOW_S = 8.0       # how much of each version a card plays [prior]
MIN_WINDOW_S = 5.0   # never less than this, even for a change in one short shot [prior]
LEAD = 1             # shots shown before the first difference, so the change is seen arriving


def _sig(it: dict) -> tuple:
    return (it.get("clip_id"), round(float(it["src_start"]), 2), round(float(it["src_end"]), 2),
            round(float(it.get("speed") or 1.0), 2))


def windows(a: list[dict], b: list[dict]) -> list[tuple[float, float]] | None:
    """Where two versions differ, as (start, end) in each one's own time: from
    LEAD shots before the first different shot to one shot past the last,
    at most WINDOW_S (an ending keeps its end, anything else its start).
    None when the pictures are the same shot for shot."""
    sa, sb = [_sig(x) for x in a], [_sig(x) for x in b]
    if not sa or not sb or sa == sb:
        return None
    n = min(len(sa), len(sb))
    i = next((k for k in range(n) if sa[k] != sb[k]), n)
    j = next((k for k in range(n - i) if sa[-1 - k] != sb[-1 - k]), n - i)
    out = []
    for items in (a, b):
        total = float(items[-1]["seq_end"])
        start = float(items[min(max(i - LEAD, 0), len(items) - 1)]["seq_start"])
        last = max(len(items) - 1 - j, min(i, len(items) - 1))        # the last shot that differs
        end = float(items[min(last + 1, len(items) - 1)]["seq_end"]) if j else total
        if end - start > WINDOW_S:
            if not j:       # the change is how it ends: show the end, from a cut
                start = next((float(x["seq_start"]) for x in items if float(x["seq_start"]) >= end - WINDOW_S),
                             end - WINDOW_S)
            else:
                end = start + WINDOW_S
        if end - start < MIN_WINDOW_S:
            end = min(total, start + MIN_WINDOW_S)
            start = max(0.0, end - MIN_WINDOW_S)
        out.append((round(start, 3), round(end, 3)))
    return out


class Side:
    """One version on a card: the changes it carries ({part: spec}), the ops
    that make it, its board, its reading and the model's score."""

    def __init__(self, now: dict, ops: list[dict], board: dict, desc: dict, score: float):
        self.now, self.ops, self.board, self.desc, self.score = now, ops, board, desc, score

    def names(self) -> list[str]:
        return [s["name"] for _, s in sorted(self.now.items())]


class Deck:
    """The cards for the video one Make made. `ctx` is what tastepick.build
    needs (make.py keeps it on the job), `report` Make's taste_pick report,
    `turn` the Make turn and `extra` the ops Make's turn carried beyond the
    cut (the remembered caption style), so a picked version lands dressed
    the same."""

    def __init__(self, ctx: dict, report: dict, turn: int, project: str | None, extra: list[dict] | None = None):
        self.ctx, self.make_turn, self.project, self.extra = ctx, turn, project, list(extra or [])
        specs = report.get("specs") or []
        scores = [v.get("score") for v in report.get("variants") or []]
        picked = specs[report.get("picked") or 0] if specs else {"name": "today"}
        self.now = {KIND[c["name"]]: c for c in report.get("chosen") or [picked] if c["name"] in KIND}
        self.turns = {turn: dict(self.now)}            # the video's version after each of these turns
        self.by_kind: dict[str, list[dict]] = {}
        score_of = {s["name"]: sc for s, sc in zip(specs, scores) if sc is not None}
        base = score_of.get("today", 0.0)
        mine = score_of.get(picked["name"], base)
        gap: dict[str, float] = {}
        for s in specs:
            k = KIND.get(s["name"])
            if k is None:
                continue
            self.by_kind.setdefault(k, []).append(s)
            if s["name"] not in score_of:
                continue
            # how far the version a card would show is from the video's, on the model's scale: in the
            # picked change's own part it's that version as tried; elsewhere the change on top of the
            # picked one, guessed as the picked score plus what the change did to today's
            if k in self.now:
                far = [abs(base - mine)] + [abs(score_of[s["name"]] - mine)] * (s["name"] != picked["name"])
            else:
                far = [abs(score_of[s["name"]] - base)]
            gap[k] = min([gap.get(k, 1e9)] + far)
        # the parts the model was least sure about, asked in the order the video plays
        ask = sorted(self.by_kind, key=lambda k: (gap.get(k, 1e9), PLAYS.index(k)))[:MAX_CARDS]
        self.kinds = [k for k in PLAYS if k in ask]
        self.i, self.n = 0, 0
        self.card: dict | None = None
        self.answers: list[dict] = []
        self.cat: bd.Catalog | None = None
        self.at = time.time()

    # -- the versions ------------------------------------------------------
    def _side(self, now: dict) -> Side | None:
        c = self.ctx
        if not now:
            made = c["base"]
        else:
            made = tp.build(list(now.values()), c["raw"], c["clips"], c["fp"], c["mx"], c["fmt"], c["look"],
                            c["about"], c["talking"], c["lines"])
            if made is None:
                return None
        _plan, mx, ops = made
        if self.cat is None:
            self.cat = bd.Catalog.from_clips(list(c["clips"].values()))
        board = tp.board_of(ops, self.cat)
        if not board:
            return None
        model = tp.model_for(c["fmt"])
        if model is None:
            return None
        desc = ds.from_board(board, c["clips"], self.cat, c["fmt"], track=mx["track"] if mx else None)
        return Side(dict(now), ops, board, desc, model.score(desc))

    def _others(self, kind: str) -> list[dict]:
        """The versions that differ from the video's in this part only."""
        out = []
        if kind in self.now:
            out.append({k: v for k, v in self.now.items() if k != kind})       # as Make first had it
        for s in self.by_kind.get(kind, []):
            if self.now.get(kind, {}).get("name") != s["name"]:
                out.append({**self.now, kind: s})
        return out

    def next_card(self) -> dict | None:
        """The card on show, built when first asked for; None when every
        card has been answered (or none could be cut)."""
        if self.card is not None:
            return self.card
        while self.i < len(self.kinds):
            kind = self.kinds[self.i]
            cur = self._side(self.now)
            sides = [s for s in (self._side(o) for o in self._others(kind)) if s is not None]
            sides = [s for s in sides if cur is not None and s.ops != cur.ops]
            if cur is None or not sides:
                self.i += 1
                continue
            # the one the model is least sure of against the video's: her pick says the most there
            other = min(sides, key=lambda s: abs(s.score - cur.score))
            win = windows(timeline.layout(cur.board), timeline.layout(other.board))
            if win is None:
                self.i += 1
                continue
            first = self.i % 2 == 0          # the video's version on the left every other card
            self.n += 1
            self.card = {"id": self.n, "kind": kind, "ask": ASK[kind], "at": self.i + 1, "of": len(self.kinds),
                         "sides": [cur, other] if first else [other, cur],
                         "windows": win if first else [win[1], win[0]], "video": 0 if first else 1}
            return self.card
        return None

    # -- her pick ----------------------------------------------------------
    def answer(self, card_id: int, pick: int | None) -> dict:
        """Keep her pick as a pair (picked above the other) and refit her
        layer; `pick` None = she couldn't tell, which teaches nothing.
        Returns {"side": the picked Side or None, "change": whether it isn't
        the video's version, "words": the version in words, "fit": what
        moved}. The caller lands the version on the video, or doesn't."""
        card = self.card
        if card is None or card["id"] != card_id:
            raise KeyError("that card has gone")
        out = {"side": None, "change": False, "words": "", "fit": None}
        if pick in (0, 1):
            better, worse = card["sides"][pick], card["sides"][1 - pick]
            kind = card["kind"]
            tm.record_pick(better.desc, worse.desc,
                           why=f"{kind}: {'+'.join(better.names()) or 'as made'} over {'+'.join(worse.names()) or 'as made'}")
            try:
                out["fit"] = tm.personal_fit()
            except Exception as e:  # noqa: BLE001 -- the pair is kept; the next pick or training refits
                out["fit"] = {"error": str(e)[:160]}
            spec = better.now.get(kind)
            out.update(side=better, change=pick != card["video"],
                       words=NAMED.get(spec["name"], "") if spec else FIRST[kind])
        self.answers.append({"kind": card["kind"], "pick": pick,
                             "names": [s.names() for s in card["sides"]], "video": card["video"]})
        self.i += 1
        self.card = None
        return out

    def landed(self, turn: int, side: Side) -> None:
        """The picked version is on the video now, put there by `turn`."""
        self.now = dict(side.now)
        self.turns[turn] = dict(self.now)

    def follow(self, last_turn: int | None) -> bool:
        """The video's version, read from the session's last live turn: True
        while nothing but Make and the picks has changed it (then a pick may
        land), False after any other edit."""
        if last_turn in self.turns:
            now = self.turns[last_turn]
            if now != self.now:
                # a card built on another version (a pick undone since) would put it back: build it again
                self.now, self.card = dict(now), None
            return True
        return False

    def done(self) -> bool:
        return self.card is None and self.i >= len(self.kinds)


def side_public(side: Side, win: tuple[float, float]) -> dict:
    """What a card's player needs: the shots that play in the window (each as
    the timeline lays it out, times in the version's own edit) and the window."""
    a, b = win
    items = [it for it in timeline.layout(side.board) if it["seq_end"] > a + 1e-3 and it["seq_start"] < b - 1e-3]
    return {"items": items, "start": a, "end": b}
