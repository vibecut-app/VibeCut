"""The taste model: what good editors do, learnt from what they did.

An edit described shot by shot (taste/describe.py: numbers and labels only)
is read the way an editor reads a cut -- how the shot lengths move (a quick
run landing on a held payoff, an opening held long enough to take in), how
one shot becomes the next (straight cuts; a jump cut inside a take), where
the words sit and how long they stay, how long someone talks before a
cutaway, whether a laugh is kept. None of it is a target: the model learns
it from the good vlogs themselves, in three parts.

1. Grammar. Each shot becomes a token -- what it is (talking to the lens, a
   face, a voice over b-roll, movement, a still), how long against the
   video's own typical shot, how it joins the next -- and a trigram model
   with Kneser-Ney smoothing learns which runs of tokens good edits use. A
   reading one side lacks is left out of the token on both sides, so a
   board read without faces meets a grammar learnt without faces.
2. Scorer. Named features, each with a plain meaning, weighed by a
   logistic regression on pairs: a real edit against a copy the computer
   damaged in one way (the breakers: shuffled, every shot the same length,
   flashes on the joins, the words moved to the top, the cutaways taken
   out of the talk...). A damage that pushes a reading one way has its
   other side where the creator has the habit (their flashes cut out,
   their capitals in lower case), so which way is good comes from the
   creators, not from the list of damages. What tells real from damaged
   is what the model learns to value. Leaving a creator out says whether that holds for
   someone it never saw; leaving a breaker out says whether it learnt
   editing or only the damages it was shown.
3. Roles. Where the AI editor named each shot's job in a reference (hook,
   setup, step, payoff, talk...), a small classifier learns to name them
   from the readings, so a board on the rules path can be read for its
   story beats too -- only once it names the jobs of a creator it never
   saw better than always guessing the commonest job.

Her own layer sits on top: pairs from her projects (the board she exported
against the one Make made, a pick between two versions, an export she
wouldn't post against one she would) move the weights by an offset held close to zero, so a
handful of picks move it a little and many picks more, except that a pick on
a close call between two versions decides it (PICK_STEP)
($VIBECUT_CACHE/taste/personal.json).

numpy only, deterministic for a seed, and nothing here calls a model.

    python -m taste.model train [--group long|short|all]
    python -m taste.model score <desc.json> [--group long|short]
    python -m taste.model personal        # refit her layer from the stored picks
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import os
import time
import zlib
from collections import Counter
from pathlib import Path

import numpy as np

try:
    from .describe import JOIN_KINDS, READINGS, ROLES, validate
except ImportError:      # the describer is built alongside; the schema (v1) is what's shared
    ROLES = ("hook", "setup", "step", "payoff", "talk", "reaction", "transit", "detail", "title", "outro", "other")
    JOIN_KINDS = ("cut", "jump", "dissolve", "dip_black", "flash", "swipe", "other")
    READINGS = ("motion", "faces", "sound", "words", "labels", "roles", "music")
    validate = None

HERE = Path(__file__).parent
DESCRIPTIONS = HERE / "descriptions"
MODEL_DIR = HERE / "model"
DATA = HERE / "data"
FILE_KIND = "vibecut-taste-model"
VERSION = 1
GROUPS = ("long", "short")
GROUP_OF_ID = {"L": "long", "S": "short"}
GROUP_WORDS = {"long": "long vlogs", "short": "shorts"}
NAN = float("nan")

# --- what a shot is ----------------------------------------------------------
# Lengths against the video's own typical (median) shot, so a short at 1 s a
# shot and a long vlog at 3 s read alike: under 0.6x is a quick step, over
# 1.6x a held beat, over 3x a long hold. [prior]
QUICK, HELD, HELD_LONG = 0.6, 1.6, 3.0
FACE_ON = 0.5        # the largest face is there for at least half the shot
LOOKING = 0.5        # ...looking into the lens (|yaw| <= 25) at least half of that
VOICE_ON = 0.45      # signals.VOICE_HI: a voice is heard, not only room sound
MOVING, STILL = 0.67, 0.33   # motion rank inside the video: its busiest / stillest third
LAUGH_ON = 0.3       # mean laughter over a shot that says a laugh was kept in [prior]
RUN = 2              # a quick run: at least this many shots in a row shorter than typical [prior]
GRID_TOL = 0.04      # a length this close to a whole number of half-beats sits on the grid (s)
NO_BEAT_GRID = 0.5   # no tempo known: the half-second grid a metronome edit falls on (s)
FLAT = 0.05          # shot lengths this even (spread of their logs) have no rhythm to read
MIN_D = 0.01         # shorter than this is a reading error, not a shot (s)
MAX_CUTAWAY = 4      # more b-roll than this between two talks is a montage, not a cutaway [prior]
INNER_Q = 0.9        # the longest shot inside the edit is read against this quantile of the other
                     # shots inside it, so one take left running stands out from the edit's ordinary
                     # long shots and a few outliers don't swamp the reading [prior]
MIN_INNER = 6        # shots an edit needs before its longest inner shot can stand out [prior]
# A reel's shot shorter than this has no frame of its own in a reading at
# two frames a second (describe.FRAME_FPS): the still its labels and look
# were read from may belong to the shot beside it, so it says nothing about
# how one shot follows another. A board's readings are each shot's own. [prior]
OWN_FRAME_S = 0.5

# Amounts where too much and too little both read as amateur -- every shot
# one length and lengths all over the place, no words at all and words over
# every shot, an opening cut short and one that drags -- so the model also
# weighs how far an edit is from the good edits' middle. (Weighed one way
# only, a damage that stretches one shot teaches "less spread is better",
# and a metronome edit it was never shown would then read as good.)
# The joins and the words' look are weighed both ways too, so how many
# effects, top-band words or capitals is right comes from the real edits'
# middle, not from which way the damages happen to push them.
# One take left running inside the edit, one talking shot far longer than
# the others and music under the talk are weighed both ways too: some good
# edits do each, so how much of it is right comes from their middle, not
# from which way a damage pushes it.
FAR = ("rhythm_spread", "opening_hold", "ending_hold", "words_share", "words_shots", "words_per_min",
       "joins_effect", "joins_flash", "joins_dissolve", "words_top", "words_caps", "music_on",
       "longest_hold", "talk_longest", "music_under_talk")
FAR_SAYS = {"rhythm_spread": "shot lengths more even or more uneven than the good edits'",
            "opening_hold": "an opening held shorter or longer than the good edits'",
            "ending_hold": "an ending held shorter or longer than the good edits'",
            "words_share": "words on screen less or more of the time than in the good edits",
            "words_shots": "words on fewer or more shots than in the good edits",
            "words_per_min": "fewer or more words a minute than in the good edits",
            "joins_effect": "fewer or more effects between shots than in the good edits",
            "joins_flash": "fewer or more white flashes than in the good edits",
            "joins_dissolve": "fewer or more dissolves than in the good edits",
            "words_top": "words at the top more or less often than in the good edits",
            "words_caps": "more or fewer capitals than in the good edits",
            "music_on": "music under less or more of it than in the good edits",
            "longest_hold": "the longest shot inside standing out less or more than in the good edits",
            "talk_longest": "the longest talk standing out less or more than in the good edits",
            "music_under_talk": "less or more talk over music than in the good edits"}

# A join the reference reader (style.transitions) can't tell from a cut is
# read as one on every edit, so a board's swipe and a reel's swipe -- which
# that reader calls a cut -- are the same thing to the model. Kept apart,
# every board's swipes would count against it for something no real edit
# could be seen to have.
READ_AS_CUT = ("swipe", "other")

# --- learning ----------------------------------------------------------------
KN_D = 0.75          # Kneser-Ney discount (the usual value)
MIN_GRAMMAR = 3      # videos a grammar needs before its reading counts
MIN_VIDEOS = 3       # real edits a group needs before anything is learnt
L2 = 1.0             # pull on the scorer's weights over standardised features [prior]
Z_CLIP = 8.0         # past this many spreads a reading is off the scale the model learnt on
TIE = 1e-9
SWAP_SHARE = 0.25    # swap_neighbours moves about this share of the shots [prior]
EFFECT_SHARE = 0.3   # an effect breaker covers at least this share of the joins, up to all [prior]
HABIT = 0.15         # a look that covers this share of the joins (or of the words' time) is the
                     # creator's habit, not a one-off (style: a soft transition counts above 15%)
MIN_REST = 0.25      # a hold that leaves the other shots less than this of their time is another edit
FLASH_S, DISSOLVE_S = 0.2, 0.8   # make.FLASH_S, the film dissolve
ROLE_MIN = 30        # labelled shots before the role model is trained
ROLE_CREATORS = 3    # ...from at least this many creators, so it can be checked on one it never saw
ROLE_MARGIN = 0.1    # ...and it must name jobs this much more often than always guessing the commonest [prior]
ROLE_L2 = 1.0
# Her layer: the offset is pulled to zero this hard, so a few picks move the
# score a little and many move it clearly (on the test's fake creators,
# three picks for flashes closed a sixth of the gap, thirty-three all of
# it). [prior]
PERSONAL_L2 = 150.0
# A pick between two versions one change apart (the cards after Make,
# web/backend/prefer.py) is weighted by how subtle that change is: PICK_STEP
# over the squared size of the pair's difference (at least PICK_FLOOR), so
# each pick moves the score on its own comparison by about the same step
# (up to PICK_STEP / PERSONAL_L2 = 0.6 of a point on the model's scale)
# however small the change. Unweighted, a card's pair differs in one part of
# the video only and twelve identical picks moved its gap by 0.02 (measured
# on the test shoot, 2026-10-21): her picks counted for nothing. Now a close
# call goes her way after one pick, and the test model's strongest
# conviction (the held opening, 2.7 points ahead) was down to 0.9 after six
# videos of her turning it down. A tiny difference counts as PICK_FLOOR:
# the offset a pick learns grows as its pair shrinks, and a bigger
# comparison sharing those features moves with it. The cards' pairs on the
# test shoot measure 0.75 to 24 (median 8.5); with a floor of 0.25, one pick
# on a near-identical pair could move a 24 one about ten times the 0.6 step,
# at 4 about twice. [prior]
PICK_STEP = 90.0
PICK_FLOOR = 4.0
WEAK = 0.3           # an export she wouldn't post vs the exports she would: says something is
                     # wrong, not what [prior]
MAX_PAIRS = 400      # her newest pairs kept
MAX_YES = 50         # her newest exports she'd post, kept to weigh a "no" against

KINDS = ("talk", "face", "voice", "move", "still", "plain")
LENS = ("q", "n", "h", "H")
KIND_READINGS = ("faces", "motion", "sound")
# The kind grammar is learnt once per set of readings, fullest first; a
# board read without faces or sound meets the one learnt without them.
KIND_SETS = (("faces", "motion", "sound"), ("faces", "motion"), ("motion", "sound"), ("motion",))
BOS = "<s>"
VOCAB = {"dur": len(LENS) * (len(JOIN_KINDS) + 1),
         "kind": len(KINDS) * len(LENS) * (len(JOIN_KINDS) + 1),
         "role": (len(ROLES) + 1) * len(LENS) * (len(JOIN_KINDS) + 1)}

# What each feature reads, in plain words: (name, how its value is said,
# what it means, said when it is high, said when it is low).
FEATURES = [
    ("rhythm_spread", "num", "how uneven the shot lengths are (0: all alike)",
     "shot lengths vary a lot", "shot lengths are all alike"),
    ("rhythm_alternation", "num", "how much neighbouring shots differ in length, against chance (1: as if in any order)",
     "neighbouring shots swing between quick and held", "shot lengths change only gradually"),
    ("run_then_hold", "share", "share of held shots that land after a quick run",
     "held shots land after a quick run", "held shots come without a quick run into them"),
    ("opening_hold", "x", "how long the first shot is held, against the video's typical shot",
     "the first shot is held", "the first shot is cut quickly"),
    ("ending_hold", "x", "how long the last shot is held, against the typical shot",
     "the last shot is held", "the last shot is cut short"),
    ("longest_hold", "x", "how much longer the longest shot inside the edit runs than its other long shots",
     "one shot inside runs far longer than the rest", "no shot inside stands out for its length"),
    ("lengths_on_grid", "share", "share of shot lengths in whole beats, as a metronome cuts",
     "shot lengths are whole beats, like a metronome", "shot lengths follow the action, not a grid"),
    ("joins_effect", "share", "share of joins that are an effect, not a straight cut",
     "many joins are effects rather than straight cuts", "the joins are straight cuts"),
    ("joins_flash", "share", "share of joins that flash white",
     "white flashes between shots", "no white flashes"),
    ("joins_dissolve", "share", "share of joins that dissolve",
     "dissolves between shots", "few dissolves"),
    ("joins_jump", "share", "share of joins that are jump cuts inside a take",
     "jump cuts inside takes", "few jump cuts"),
    ("fade_open", "yes", "fades in from black at the start",
     "it fades in from black", "it opens straight on a picture"),
    ("fade_close", "yes", "fades out to black at the end",
     "it fades out to black", "it ends on a cut"),
    ("words_share", "share", "share of the time with words on screen",
     "words are on screen much of the time", "words are rare"),
    ("words_top", "share", "share of the words' time at the top of the frame",
     "the words sit at the top", "the words stay off the top"),
    ("words_caps", "share", "how much of the words is in capitals",
     "the words are in capitals", "the words are in lower or sentence case"),
    ("words_per_min", "rate", "words shown a minute",
     "lots of words a minute", "few words a minute"),
    ("words_hold", "s", "how long a caption stays up",
     "each caption stays up long", "captions come and go quickly"),
    ("words_shots", "share", "share of shots that carry words",
     "most shots carry words", "few shots carry words"),
    ("face_share", "share", "share of the time a face fills the picture",
     "a face is on screen much of the time", "faces are on screen little of the time"),
    ("facing_share", "share", "share of the face time looking into the lens",
     "faces look into the lens", "faces look away from the lens"),
    ("talk_vs_other", "x", "how much longer talking shots run than the rest",
     "talking shots run longer than the rest", "talking shots are cut as short as the rest"),
    ("talk_stretch", "share", "the longest talk with no cutaway, as a share of the video",
     "one stretch of talk runs long with no cutaway", "talk is broken up by cutaways"),
    ("talk_longest", "x", "how much longer the longest talking shot runs than the other talking shots' middle "
     "(the last shot is the ending's)",
     "one talking shot runs far longer than the others", "the talking shots run about alike"),
    ("flow_seen", "num", "how much what's in the picture changes from one shot to the next, "
     "against chance (1: as if in any order)",
     "the picture jumps between subjects from shot to shot", "shots of the same things sit together"),
    ("laugh_held", "x", "how long laughing shots are held, against the typical shot",
     "laughs are held", "laughs are cut short"),
    ("music_on", "share", "share of the time with music under it",
     "music runs under it", "little or no music"),
    ("music_under_talk", "share", "how much of the time a voice is heard over music "
     "(the share with a voice, times the share with music)",
     "music runs under the talk", "little talk with music under it"),
    ("cuts_on_beat", "share", "share of cuts on the music's beat",
     "the cuts land on the beat", "the cuts follow the action, not the beat"),
    ("repeats", "share", "share of shots that are a shot shown earlier",
     "a shot is shown twice", "no shot is shown twice"),
    ("continuity", "num", "how much each shot follows on from the one before -- what it shows, how it looks, "
     "how it moves -- against two of its shots taken at random (0: as if in any order)",
     "each shot follows on from the one before", "shots jump between unrelated things"),
    ("payoff_held", "x", "how much longer payoffs are held than the set-up and steps into them",
     "payoffs are held longer than the steps into them", "payoffs are cut as short as the steps"),
    ("hook_first", "yes", "opens on a hook",
     "it opens on a hook", "it doesn't open on a hook"),
    ("chapters_per_min", "rate", "parts a minute",
     "many parts a minute", "few parts"),
    ("grammar_dur", "num", "how much the run of quick and held shots reads like the good edits",
     "the rhythm reads like the good edits", "the rhythm reads unlike the good edits"),
    ("order_dur", "num", "how much the order of quick and held shots follows the good edits, beyond the lengths",
     "quick and held shots come in the good edits' order", "quick and held shots come in an unusual order"),
    ("grammar_kind", "num", "how much the run of talk, faces, b-roll and movement reads like the good edits",
     "talk, faces and b-roll run like the good edits", "talk, faces and b-roll run unlike the good edits"),
    ("order_kind", "num", "how much the order of talk, faces and b-roll follows the good edits, beyond what's in it",
     "talk and b-roll come in the good edits' order", "talk and b-roll come in an unusual order"),
    ("grammar_role", "num", "how much the story beats (hook, set-up, steps, payoff) run like the good edits",
     "the story beats run like the good edits", "the story beats run unlike the good edits"),
]
NAMES = [f[0] for f in FEATURES]
FAR_NAMES = [f"far_{x}" for x in FAR]
_SAYS = {f[0]: f[1:] for f in FEATURES}
# The grammar's readings and the token level each one reads.
GRAMMAR_LEVEL = {"grammar_dur": "dur", "order_dur": "dur", "grammar_kind": "kind", "order_kind": "kind",
                 "grammar_role": "role"}

# A grammar line that counts against an edit also names the part of its
# shots the good edits use least like it -- the white flashes, every shot
# one length -- so the note says what to change, not only that the run
# reads wrong. A part this much more common here than there is named. [prior]
NOTE_GAP = 0.1
PART_WORDS = {
    "cut": "straight cuts", "jump": "jump cuts", "dissolve": "dissolves", "dip_black": "dips to black",
    "flash": "white flashes", "swipe": "swipes", "other": "unusual joins",
    "q": "quick shots", "n": "shots of a typical length", "h": "held shots", "H": "long holds",
    "talk": "shots talking to the lens", "face": "faces not talking to the lens",
    "voice": "voice over other pictures", "move": "busy, moving shots", "still": "still shots",
    "plain": "in-between shots",
    "R:hook": "hooks", "R:setup": "set-ups", "R:step": "steps", "R:payoff": "payoffs", "R:talk": "talk",
    "R:reaction": "reactions", "R:transit": "shots getting from place to place", "R:detail": "details",
    "R:title": "title cards", "R:outro": "outros", "R:other": "other shots", "R:-": "shots with no job named",
}


# --------------------------------------------------------------------------
# reading an edit
# --------------------------------------------------------------------------

def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _v(x) -> float:
    """A reading as a number; NaN when it wasn't taken."""
    return float(x) if _num(x) else NAN


def _lengths(desc: dict) -> np.ndarray:
    return np.array([max(float(s["d"]), MIN_D) if _num(s.get("d")) else MIN_D
                     for s in desc.get("shots") or []], dtype=float)


def _edges(desc: dict) -> list[float]:
    shots = desc["shots"]
    return [float(s["t"]) for s in shots] + [float(shots[-1]["t"]) + float(shots[-1]["d"])] if shots else [0.0]


def motion_ranks(desc: dict) -> list[float | None]:
    """Each shot's motion as its rank inside the video, 0 the stillest and 1
    the busiest. References and boards measure motion on different scales;
    an edit's own order of busy and calm is what an editor sees."""
    shots = desc.get("shots") or []
    out: list[float | None] = [None] * len(shots)
    if "motion" not in (desc.get("have") or []):
        return out
    idx = [k for k, s in enumerate(shots) if _num(s.get("motion"))]
    if len(idx) == 1:
        out[idx[0]] = 0.5
    if len(idx) < 2:
        return out
    v = np.array([float(shots[k]["motion"]) for k in idx])
    r = np.empty(len(v))
    r[np.argsort(v, kind="stable")] = np.arange(len(v), dtype=float)
    for x in np.unique(v):          # ties share their middle rank
        m = v == x
        r[m] = r[m].mean()
    for k, x in zip(idx, r / (len(v) - 1)):
        out[k] = float(x)
    return out


def kind_of(shot: dict, rank: float | None, use) -> str:
    """What a shot is, from the readings in `use` only, so a comparison reads
    both sides the same way: without faces, talking to the lens and a voice
    over b-roll are both just a voice."""
    face = _v(shot.get("face")) if "faces" in use else NAN
    voice = _v(shot.get("voice")) if "sound" in use else NAN
    seen, heard = face >= FACE_ON, voice >= VOICE_ON
    if seen and heard:
        facing = _v(shot.get("facing"))
        # no direction read: one person talking is taken as talking to us,
        # two or more as people talking to each other
        looking = facing >= LOOKING if not math.isnan(facing) else (shot.get("people") or 1) <= 1
        if looking:
            return "talk"
    if seen:
        return "face"
    if heard:
        return "voice"
    if "motion" in use and rank is not None:
        if rank >= MOVING:
            return "move"
        if rank <= STILL:
            return "still"
    return "plain"


def _len_class(rel: float) -> str:
    return "q" if rel < QUICK else "H" if rel > HELD_LONG else "h" if rel > HELD else "n"


def join_kinds(desc: dict) -> list[str]:
    """Each join's kind as the reference reader would see it (READ_AS_CUT)."""
    out = []
    for j in desc.get("joins") or []:
        k = j.get("kind")
        out.append("cut" if k not in JOIN_KINDS or k in READ_AS_CUT else k)
    return out


def tokens(desc: dict, level: str = "dur", use=()) -> list[str] | None:
    """The edit as a run of tokens, one a shot: `dur` = length|join; `kind` =
    what|length|join from the readings in `use`; `role` = R:job|length|join
    (None when the shots carry no jobs). The join is the one into the next
    shot, "end" on the last."""
    shots = desc.get("shots") or []
    if not shots:
        return None
    d = _lengths(desc)
    med = float(np.median(d))
    joins = (join_kinds(desc) + ["cut"] * len(shots))[:len(shots) - 1] + ["end"]
    tail = [f"{_len_class(x / med)}|{j}" for x, j in zip(d, joins)]
    if level == "dur":
        return tail
    if level == "kind":
        return [f"{kind_of(s, r, use)}|{t}" for s, r, t in zip(shots, motion_ranks(desc), tail)]
    if level == "role":
        if "roles" not in (desc.get("have") or []):
            return None
        return [f"R:{s.get('role') if s.get('role') in ROLES else '-'}|{t}" for s, t in zip(shots, tail)]
    raise ValueError(f"no token level {level!r}")


# --------------------------------------------------------------------------
# the grammar
# --------------------------------------------------------------------------

class Grammar:
    """Which runs of shot tokens good edits use: a trigram model with
    interpolated Kneser-Ney smoothing, so a run never seen still gets a
    share from the pairs and single tokens it is made of, and a token never
    seen gets a little from the whole alphabet (`vocab`)."""

    def __init__(self, counts: dict, vocab: int, ref: tuple = (0.0, 0.0), videos: int = 0):
        self.counts, self.vocab, self.videos = counts, vocab, videos
        self.ref = (float(ref[0]), float(ref[1]))
        c_ctx: dict = {}
        t_ctx: dict = {}
        n_vw: dict = {}
        self.uni: dict = {}
        for (u, v, w), c in counts.items():
            c_ctx[(u, v)] = c_ctx.get((u, v), 0) + c
            t_ctx[(u, v)] = t_ctx.get((u, v), 0) + 1
            n_vw[(v, w)] = n_vw.get((v, w), 0) + 1
            self.uni[w] = self.uni.get(w, 0) + c
        n_v: dict = {}
        t_v: dict = {}
        n_w: dict = {}
        for (v, w), c in n_vw.items():
            n_v[v] = n_v.get(v, 0) + c
            t_v[v] = t_v.get(v, 0) + 1
            n_w[w] = n_w.get(w, 0) + 1
        self._c_ctx, self._t_ctx, self._n_vw, self._n_v, self._t_v, self._n_w = c_ctx, t_ctx, n_vw, n_v, t_v, n_w
        self._n_dot, self._t1 = sum(n_w.values()), len(n_w)
        self._total = sum(self.uni.values())

    @classmethod
    def learn(cls, seqs: list[list[str]], vocab: int) -> Grammar:
        counts: dict = {}
        for seq in seqs:
            ctx = [BOS, BOS, *seq]
            for i in range(2, len(ctx)):
                key = (ctx[i - 2], ctx[i - 1], ctx[i])
                counts[key] = counts.get(key, 0) + 1
        return cls(counts, vocab, videos=len(seqs))

    def _p1(self, w: str) -> float:
        if not self._n_dot:
            return 1.0 / self.vocab
        return (max(self._n_w.get(w, 0) - KN_D, 0.0) + KN_D * self._t1 / self.vocab) / self._n_dot

    def _p2(self, w: str, v: str) -> float:
        n = self._n_v.get(v, 0)
        if not n:
            return self._p1(w)
        return (max(self._n_vw.get((v, w), 0) - KN_D, 0.0) + KN_D * self._t_v[v] * self._p1(w)) / n

    def _p3(self, w: str, u: str, v: str) -> float:
        c = self._c_ctx.get((u, v), 0)
        if not c:
            return self._p2(w, v)
        return (max(self.counts.get((u, v, w), 0) - KN_D, 0.0) + KN_D * self._t_ctx[(u, v)] * self._p2(w, v)) / c

    def raw(self, seq: list[str]) -> tuple[float, float]:
        """Mean log-probability a shot, and how much the order adds over the
        tokens alone (the trigram against plain token counts, on the tokens
        the good edits use at all -- a token never seen is the first number's
        news, not the order's): shuffling an edit keeps its tokens and loses
        the second."""
        ctx = [BOS, BOS, *seq]
        lp = gain = 0.0
        seen = 0
        for i in range(2, len(ctx)):
            p = math.log(self._p3(ctx[i], ctx[i - 2], ctx[i - 1]))
            lp += p
            if self.uni.get(ctx[i]):
                gain += p - math.log(self.uni[ctx[i]] / self._total)
                seen += 1
        return lp / max(1, len(seq)), gain / seen if seen else NAN

    def shares(self, slot: int) -> dict[str, float]:
        """How often the good edits use each value of one part of the token
        (`slot` indexes its parts: -1 the join, -2 the length, 0 what the
        shot is or its job)."""
        out: Counter = Counter()
        for tok, c in self.uni.items():
            out[tok.split("|")[slot]] += c
        return _shares(out)

    def read(self, seq: list[str]) -> tuple[float, float]:
        """`raw`, centred on the good edits' own reading (`ref`), so grammars
        on coarser tokens -- which find every edit likelier -- read alike."""
        a, b = self.raw(seq)
        return a - self.ref[0], b - self.ref[1]

    def to_json(self) -> dict:
        toks = sorted({x for key in self.counts for x in key} - {BOS})
        at = {t: i + 1 for i, t in enumerate(toks)}
        at[BOS] = 0
        tri = ",".join(f"{at[u]} {at[v]} {at[w]} {c}" for (u, v, w), c in sorted(self.counts.items()))
        return {"vocab": self.vocab, "videos": self.videos, "ref": list(self.ref), "tokens": toks, "trigrams": tri}

    @classmethod
    def from_json(cls, d: dict) -> Grammar:
        toks = [BOS, *d["tokens"]]
        counts = {}
        for part in filter(None, d["trigrams"].split(",")):
            i, j, k, c = (int(x) for x in part.split())
            counts[(toks[i], toks[j], toks[k])] = c
        ref = tuple(float(x or 0.0) for x in d.get("ref") or (0.0, 0.0))
        return cls(counts, int(d["vocab"]), ref, int(d.get("videos") or 0))


def _shares(counts: dict) -> dict[str, float]:
    """Each value's share of a token part; the last shot's "end" is no join."""
    counts = {k: c for k, c in counts.items() if k != "end"}
    total = sum(counts.values())
    return {k: c / total for k, c in counts.items()} if total else {}


def learn_grammars(descs: list[dict]) -> dict:
    """The three token levels learnt on these edits; the kind level once per
    set of readings, from the edits that have them all."""
    out: dict = {"dur": None, "kind": {}, "role": None}
    seqs = [t for t in (tokens(d, "dur") for d in descs) if t]
    if len(seqs) >= MIN_GRAMMAR:
        out["dur"] = Grammar.learn(seqs, VOCAB["dur"])
    for use in KIND_SETS:
        seqs = [t for t in (tokens(d, "kind", use) for d in descs if set(use) <= set(d.get("have") or [])) if t]
        if len(seqs) >= MIN_GRAMMAR:
            out["kind"]["+".join(use)] = Grammar.learn(seqs, VOCAB["kind"])
    seqs = [t for t in (tokens(d, "role") for d in descs) if t]
    if len(seqs) >= MIN_GRAMMAR:
        out["role"] = Grammar.learn(seqs, VOCAB["role"])
    return out


def _levels(grammars: dict):
    if grammars.get("dur") is not None:
        yield ("dur",), grammars["dur"]
    for key, g in (grammars.get("kind") or {}).items():
        yield ("kind", key), g
    if grammars.get("role") is not None:
        yield ("role",), grammars["role"]


def _at(grammars: dict, path: tuple):
    return grammars.get("kind", {}).get(path[1]) if path[0] == "kind" else grammars.get(path[0])


def _tokens_at(desc: dict, path: tuple) -> list[str] | None:
    if path[0] == "kind":
        use = path[1].split("+")
        return tokens(desc, "kind", use) if set(use) <= set(desc.get("have") or []) else None
    return tokens(desc, path[0])


def _kind_key(desc: dict, kinds: dict) -> str | None:
    """The fullest set of readings both this edit and a learnt grammar have."""
    have = set(desc.get("have") or [])
    for use in KIND_SETS:
        key = "+".join(use)
        if key in kinds and set(use) <= have:
            return key
    return None


def _grammar_reads(desc: dict, grammars: dict) -> dict[str, float]:
    out = {}
    g = grammars.get("dur")
    seq = tokens(desc, "dur")
    if g is not None and seq:
        out["grammar_dur"], out["order_dur"] = g.read(seq)
    key = _kind_key(desc, grammars.get("kind") or {})
    if key is not None and seq:
        out["grammar_kind"], out["order_kind"] = grammars["kind"][key].read(tokens(desc, "kind", key.split("+")))
    g = grammars.get("role")
    seq = tokens(desc, "role") if g is not None else None
    if seq:
        out["grammar_role"] = g.read(seq)[0]
    return out


# --------------------------------------------------------------------------
# the features
# --------------------------------------------------------------------------

def _union(events: list[dict], total: float) -> float:
    """Seconds with any of these events on screen, inside the edit."""
    spans = sorted((max(0.0, float(w["t"])), min(total, float(w["t"]) + float(w["d"]))) for w in events)
    out, a0, b0 = 0.0, None, None
    for a, b in spans:
        if b <= a:
            continue
        if b0 is None or a > b0:
            out += (b0 - a0) if b0 is not None else 0.0
            a0, b0 = a, b
        else:
            b0 = max(b0, b)
    return out + ((b0 - a0) if b0 is not None else 0.0)


def _longest_run(d: np.ndarray, on: np.ndarray) -> float:
    best = cur = 0.0
    for x, o in zip(d, on):
        cur = cur + x if o else 0.0
        best = max(best, cur)
    return best


def _labels_alternation(shots: list[dict]) -> float:
    """How unlike neighbouring shots' labels are (1 - shared / all of the
    two) against any two shots' (1: as if in any order; low: the edit stays
    with a thing before moving on). NaN with fewer than three neighbours read."""
    sets = [set(s["labels"]) if isinstance(s.get("labels"), list) and s["labels"] else None for s in shots]
    idx = [k for k, x in enumerate(sets) if x]
    if len(idx) < 2:
        return NAN
    vocab = {lb: i for i, lb in enumerate(sorted(set().union(*(sets[k] for k in idx))))}
    B = np.zeros((len(idx), len(vocab)))
    for r, k in enumerate(idx):
        B[r, [vocab[lb] for lb in sets[k]]] = 1.0
    inter = B @ B.T
    size = B.sum(1)
    apart = 1 - inter / (size[:, None] + size[None, :] - inter)
    pos = {k: r for r, k in enumerate(idx)}
    near = [apart[pos[k], pos[k + 1]] for k in idx if k + 1 in pos]
    anyp = apart[np.triu_indices(len(idx), 1)].mean()
    if len(near) < 3 or anyp < 1e-9:
        return NAN
    return float(np.mean(near) / anyp)


def _own(desc: dict) -> np.ndarray:
    """The shots whose stills are their own (OWN_FRAME_S): a shot too
    short to have one carries its neighbour's labels and look, and would
    make the shots beside it look alike."""
    d = _lengths(desc)
    return np.ones(len(d), bool) if desc.get("source") == "board" else d >= OWN_FRAME_S


def _flow(desc: dict) -> float:
    """How unlike neighbouring shots' labels are, against any two shots."""
    if "labels" not in set(desc.get("have") or []):
        return NAN
    return _labels_alternation([s if ok else {} for s, ok in zip(desc["shots"], _own(desc))])


def _rank01(vals) -> np.ndarray:
    """Each reading's rank among the ones taken, 0 the lowest and 1 the
    highest, ties sharing their middle rank; NaN where none was taken. A
    reel's motion and a board's come on different scales; their order
    inside one edit is what both can say."""
    v = np.asarray(vals, dtype=float)
    out = np.full(len(v), NAN)
    ok = np.isfinite(v)
    if ok.sum() < 2:
        return out
    x = v[ok]
    r = np.empty(len(x))
    r[np.argsort(x, kind="stable")] = np.arange(len(x), dtype=float)
    for u in np.unique(x):
        m = x == u
        r[m] = r[m].mean()
    out[ok] = r / (len(x) - 1)
    return out


def _against_any(pairs: np.ndarray) -> np.ndarray | None:
    """A reading of every pair of shots, in its spread over all of them: 0
    is two shots of this edit taken at random. None when it can't be read."""
    off = ~np.eye(len(pairs), dtype=bool) & np.isfinite(pairs)
    if off.sum() < 3:
        return None
    v = pairs[off]
    sd = float(v.std())
    return (pairs - float(v.mean())) / sd if sd > 1e-9 else None


def continuity(desc: dict) -> float:
    """How much each shot follows on from the one before, from what each
    shot holds: an editor stays with a place or a thing before moving on,
    keeps the look and the energy together, and cuts on action -- the
    movement leaving one shot carried into the next. Each is weighed
    against two shots of the same edit taken at random, so a video filmed
    all in one room doesn't read as more continuous than a trip, and the
    same shots in a random order read 0 on average. Only each shot's own
    readings: never the joins' kinds, which don't move with the shots.
    NaN with fewer than four shots or nothing to read."""
    shots = desc.get("shots") or []
    n = len(shots)
    if n < 4:
        return NAN
    have = set(desc.get("have") or [])
    own = _own(desc)
    pairs = []
    if "labels" in have:
        # what it shows: the labels two shots share, those the whole video
        # carries ("people", "indoor") counting least
        rows = [sorted(set(s["labels"])) if ok and isinstance(s.get("labels"), list) and s["labels"] else None
                for s, ok in zip(shots, own)]
        vocab = {x: i for i, x in enumerate(sorted({x for r in rows if r for x in r}))}
        if vocab:
            X = np.zeros((n, len(vocab)))
            for i, r in enumerate(rows):
                for x in r or ():
                    X[i, vocab[x]] = 1.0
            read = np.array([r is not None for r in rows])
            W = X * np.log((read.sum() + 1.0) / (X.sum(0) + 0.5))
            W /= np.maximum(np.linalg.norm(W, axis=1), 1e-12)[:, None]
            shared = W @ W.T
            shared[~read, :] = NAN
            shared[:, ~read] = NAN
            pairs.append(shared)
        # how it looks (Apple's aesthetics score of the same still)
        look = np.array([_v(s.get("aesthetic")) if ok else NAN for s, ok in zip(shots, own)])
        pairs.append(-np.abs(look[:, None] - look[None, :]))
    if "motion" in have:
        # the movement out of one shot against the movement into the next
        edge = _rank01([_v(s.get("motion_out")) for s in shots] + [_v(s.get("motion_in")) for s in shots])
        pairs.append(-np.abs(edge[:n, None] - edge[None, n:]))
        # and how busy each shot is
        busy = _rank01([_v(s.get("motion")) for s in shots])
        pairs.append(-np.abs(busy[:, None] - busy[None, :]))
    weighed = [z for z in map(_against_any, pairs) if z is not None]
    if not weighed:
        return NAN
    st = np.stack(weighed)
    cnt = np.isfinite(st).sum(0)
    alike = np.where(cnt > 0, np.nansum(st, 0) / np.maximum(cnt, 1), NAN)
    nxt = alike[np.arange(n - 1), np.arange(1, n)]
    nxt = nxt[np.isfinite(nxt)]
    return float(nxt.mean()) if len(nxt) >= 3 else NAN


def features_of(desc: dict, grammars: dict | None = None) -> dict[str, float]:
    """Every base feature of an edit (NAMES), NaN where the description has
    no reading for it: a reading that wasn't taken is no evidence either way.
    `grammars` (learn_grammars) adds the grammar's reading of the edit."""
    out = dict.fromkeys(NAMES, NAN)
    shots = desc.get("shots") or []
    n = len(shots)
    if not n:
        return out
    have = set(desc.get("have") or [])
    d = _lengths(desc)
    total = float(d.sum())
    med = float(np.median(d))
    ld, rel = np.log(d), d / med
    cutoff = bool(desc.get("cutoff"))

    # rhythm: how lengths move, against the video's own typical shot
    if n >= 3:
        out["rhythm_spread"] = float(ld.std())
    if n >= 4 and ld.std() >= FLAT:
        # neighbouring shots against two drawn at random (E|x - y| = 2s/sqrt(pi))
        out["rhythm_alternation"] = float(np.abs(np.diff(ld)).mean() / (ld.std() * 2 / math.sqrt(math.pi)))
    holds = [k for k in range(1, n) if rel[k] > HELD]
    if holds:
        out["run_then_hold"] = float(np.mean([k >= RUN and all(rel[k - j] < 1 for j in range(1, RUN + 1))
                                              for k in holds]))
    if n >= 2:
        out["opening_hold"] = float(np.log(rel[0]))
        if not cutoff:          # where measuring stopped isn't how the creator ended
            out["ending_hold"] = float(np.log(rel[-1]))
    if n >= MIN_INNER:
        # One take left running in the middle -- a chat that held, a view the
        # editor couldn't leave -- against the edit's ordinary long shots,
        # not its typical one, so an edit of quick steps and held beats
        # isn't read as dragging. The first and last are the opening's and
        # ending's own.
        inner = d[1:-1]
        k = int(np.argmax(inner))
        out["longest_hold"] = float(np.log(inner[k] / np.quantile(np.delete(inner, k), INNER_Q)))
    mus = desc.get("music") or {}
    bpm = _v(mus.get("bpm"))
    unit = 30.0 / bpm if bpm > 0 else NO_BEAT_GRID      # a half-beat, as remix.quantise cuts filler
    whole = d[:-1] if cutoff and n > 1 else d
    k = np.round(whole / unit)
    out["lengths_on_grid"] = float(np.mean((k >= 1) & (np.abs(whole - k * unit) <= GRID_TOL)))

    # joins
    kinds = join_kinds(desc)
    if kinds:
        out["joins_effect"] = sum(x not in ("cut", "jump") for x in kinds) / len(kinds)
        for name, kind in (("joins_flash", "flash"), ("joins_dissolve", "dissolve"),
                           ("joins_jump", "jump")):
            out[name] = kinds.count(kind) / len(kinds)
    out["fade_open"] = 1.0 if desc.get("open") else 0.0
    if not cutoff:
        out["fade_close"] = 1.0 if desc.get("close") else 0.0

    # words on screen (None: not read; []: read, and there were none)
    words = desc.get("words")
    if isinstance(words, list):
        ev = [w for w in words if _num(w.get("t")) and _num(w.get("d")) and w["d"] > 0]
        out["words_share"] = _union(ev, total) / total
        out["words_per_min"] = sum(int(w.get("n") or 0) for w in ev) / (total / 60)
        t0 = float(shots[0]["t"]) if _num(shots[0].get("t")) else 0.0
        starts = t0 + np.concatenate([[0.0], np.cumsum(d)[:-1]])
        carry = []
        for a, x in zip(starts, d):
            need = min(0.25, x / 2)
            carry.append(any(min(a + x, w["t"] + w["d"]) - max(a, w["t"]) >= need for w in ev))
        out["words_shots"] = float(np.mean(carry))
        if ev:
            dd = np.array([float(w["d"]) for w in ev])
            out["words_top"] = float(dd[[w.get("band") == "top" for w in ev]].sum() / dd.sum())
            up = [(float(w["d"]), float(w["upper"])) for w in ev if _num(w.get("upper"))]
            if up:
                out["words_caps"] = sum(a * b for a, b in up) / sum(a for a, _ in up)
            out["words_hold"] = float(dd.mean())

    # people: faces, talk and its cutaways, laughs
    use = have & set(KIND_READINGS)
    if "faces" in have:
        face = np.array([_v(s.get("face")) for s in shots])
        on = face >= FACE_ON
        out["face_share"] = float(d[on].sum() / total)
        facing = np.array([_v(s.get("facing")) for s in shots])
        known = on & np.isfinite(facing)
        if known.any():
            out["facing_share"] = float(d[known & (facing >= LOOKING)].sum() / d[known].sum())
    if {"faces", "sound"} <= have:
        talk = np.array([kind_of(s, r, use) == "talk" for s, r in zip(shots, motion_ranks(desc))])
        if talk.any() and (~talk).any():
            out["talk_vs_other"] = float(ld[talk].mean() - ld[~talk].mean())
        out["talk_stretch"] = _longest_run(d, talk) / total
        # Talk is cut to its sentences: one talking shot that runs far past
        # the others is a take nobody broke up with what was being talked
        # about. Against the other talking shots, so a vlog that talks in
        # long takes throughout reads as itself. The last shot is left to
        # the ending: held there, it is landing the video (ending_hold reads
        # that), and on a long vlog it is where measuring stopped.
        said = d[:-1][talk[:-1]]
        if len(said) >= 2:
            k = int(np.argmax(said))
            out["talk_longest"] = float(np.log(said[k] / np.median(np.delete(said, k))))
    # What's in the shots runs in stretches: an editor stays with a scene's
    # things before moving on, so neighbouring shots share more than any two
    # do. A careless drag on the timeline breaks a stretch, and the shots
    # beside it stop matching. Read against the edit's own chance, so a
    # video filmed in one room isn't read as flowing for having nothing to
    # change. (Only the stills: sound and faces are read a second at a
    # time, which blurs a short shot into its neighbours, and a swap would
    # be read by what it blurred.)
    out["flow_seen"] = _flow(desc)
    if "sound" in have:
        laugh = np.array([_v(s.get("laugh")) for s in shots]) >= LAUGH_ON
        if laugh.any():
            out["laugh_held"] = float(np.log(rel[laugh]).mean())

    # sound
    out["music_on"] = _v(mus.get("on"))
    out["cuts_on_beat"] = _v(mus.get("beat"))
    # Music under a vlog that talks fights the voice; under a montage it is
    # the voice. How much music is right depends on how much is said, so
    # the two are read together as well as apart.
    if "sound" in have and math.isfinite(out["music_on"]):
        voice = np.array([_v(s.get("voice")) for s in shots])
        out["music_under_talk"] = float(out["music_on"] * d[voice >= VOICE_ON].sum() / total)

    # the same shot twice (a board's repeat carries its catalogue labels and
    # aesthetics exactly; the two touching halves of a split don't count)
    keyed = [(tuple(s["labels"]), round(float(s["aesthetic"]), 3))
             if s.get("labels") and _num(s.get("aesthetic")) else None for s in shots]
    if any(keyed):
        out["repeats"] = sum(1 for k, x in enumerate(keyed) if x is not None and x in set(keyed[:max(0, k - 1)])) / n

    # how each shot follows on from the one before
    out["continuity"] = continuity(desc)

    # story: jobs and parts
    # Jobs the role model guessed (a board) aren't the AI editor's: the
    # holds and the opening those weights were learnt on stay unread, so a
    # guess from a shot's length doesn't count as the editor's word.
    if "roles" in have and not desc.get("roles_filled"):
        roles = [s.get("role") for s in shots]
        pay = np.array([r == "payoff" for r in roles])
        build = np.array([r in ("setup", "step") for r in roles])
        if pay.any() and build.any():
            out["payoff_held"] = float(ld[pay].mean() - ld[build].mean())
        out["hook_first"] = 1.0 if roles[0] == "hook" else 0.0
    chs = [s.get("chapter") for s in shots if isinstance(s.get("chapter"), int) and not isinstance(s.get("chapter"), bool)]
    if chs:
        out["chapters_per_min"] = len(set(chs)) / (total / 60)

    if grammars:
        out.update(_grammar_reads(desc, grammars))
    return out


def _matrix(rows: list[dict]) -> np.ndarray:
    return np.array([[r.get(k, NAN) for k in NAMES] for r in rows], dtype=float).reshape(len(rows), len(NAMES))


def _expand(X: np.ndarray, centre: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """The base features, then for each of FAR the squared distance from the
    good edits' middle in their own spreads."""
    idx = [NAMES.index(x) for x in FAR]
    return np.hstack([X, ((X[:, idx] - centre) / scale) ** 2])


def _col_median(X: np.ndarray) -> np.ndarray:
    out = []
    for j in range(X.shape[1]):
        col = X[:, j][np.isfinite(X[:, j])]
        out.append(float(np.median(col)) if col.size else NAN)
    return np.array(out)


def _centres(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sub = X[:, [NAMES.index(x) for x in FAR]]
    scale = []
    for j in range(sub.shape[1]):
        col = sub[:, j][np.isfinite(sub[:, j])]
        scale.append(max(float(col.std()), 1e-3) if col.size > 1 else 1.0)
    return _col_median(sub), np.array(scale)


def _standardise(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ok = np.isfinite(X)
    cnt = np.maximum(ok.sum(0), 1)
    mean = np.where(ok, X, 0.0).sum(0) / cnt
    std = np.sqrt((np.where(ok, X - mean, 0.0) ** 2).sum(0) / cnt)
    std[std < 1e-9] = 1.0
    return mean, std


def _zs(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    Z = (X - mean) / std
    Z[~np.isfinite(Z)] = 0.0         # no reading: the middle, no evidence either way
    return np.clip(Z, -Z_CLIP, Z_CLIP)


# --------------------------------------------------------------------------
# the breakers: a real edit damaged in one way
# --------------------------------------------------------------------------

def _same_flags(desc: dict) -> None:
    joins = desc["joins"]
    for k, s in enumerate(desc["shots"]):
        s["same"] = bool(k and joins[k - 1]["kind"] == "jump")


def _retime(desc: dict) -> dict:
    """Lay the shots end to end again after their lengths or order changed:
    each join at its new boundary, the jump flag from the join into a shot,
    the duration the sum of the shots."""
    shots, joins = desc["shots"], desc["joins"]
    t = float(shots[0]["t"])
    for s in shots:
        s["d"] = round(float(s["d"]), 4)
        s["t"] = round(t, 4)
        t += s["d"]
    del joins[len(shots) - 1:]
    for k, j in enumerate(joins):
        j["t"] = shots[k + 1]["t"]
    _same_flags(desc)
    desc["duration"] = round(sum(s["d"] for s in shots), 4)
    return desc


def _warp_words(desc: dict, before: list[float]) -> None:
    """Words stay over the shots they were on when shots grow or shrink."""
    if not desc.get("words"):
        return
    xp, fp = np.array(before), np.array(_edges(desc))
    kept = []
    for w in desc["words"]:
        a, b = float(np.interp(w["t"], xp, fp)), float(np.interp(w["t"] + w["d"], xp, fp))
        if b - a > 1e-3:
            w["t"], w["d"] = round(a, 4), round(b - a, 4)
            kept.append(w)
    desc["words"] = kept


def _relength(desc: dict, d) -> dict:
    out = copy.deepcopy(desc)
    before = _edges(out)
    for s, x in zip(out["shots"], d):
        s["d"] = float(x)
    _retime(out)
    _warp_words(out, before)
    return out


def shuffle_all(desc: dict, rng) -> dict | None:
    """Every shot in a random order: what's in each and how long it runs
    kept, the story and the shape of the rhythm gone."""
    n = len(desc["shots"])
    if n < 3:
        return None
    for _ in range(20):
        p = rng.permutation(n)
        if (p != np.arange(n)).sum() >= max(2, n // 2):
            break
    else:
        return None
    out = copy.deepcopy(desc)
    out["shots"] = [copy.deepcopy(desc["shots"][int(i)]) for i in p]
    return _retime(out)


def swap_neighbours(desc: dict, rng) -> dict | None:
    """A few shots swapped with the next one: the order slightly off, as a
    careless drag on a timeline leaves it."""
    n = len(desc["shots"])
    if n < 3:
        return None
    want = max(1, int(round(n * SWAP_SHARE / 2)))
    out = copy.deepcopy(desc)
    used: set = set()
    done = 0
    for k in map(int, rng.permutation(n - 1)):
        if done >= want:
            break
        if k in used or k + 1 in used:
            continue
        out["shots"][k], out["shots"][k + 1] = out["shots"][k + 1], out["shots"][k]
        used |= {k, k + 1}
        done += 1
    return _retime(out)


def even_rhythm(desc: dict, rng) -> dict | None:
    """Every shot the same length, the total kept: the edit as a metronome."""
    d = _lengths(desc)
    if len(d) < 3 or np.log(d).std() < FLAT:
        return None
    return _relength(desc, [float(d.mean())] * len(d))


def permute_durations(desc: dict, rng) -> dict | None:
    """The shots in their order, each given another one's length: a talk cut
    to a b-roll's length, a payoff to a step's."""
    d = _lengths(desc)
    if len(d) < 3:
        return None
    for _ in range(20):
        p = rng.permutation(len(d))
        if np.abs(d[p] - d).max() > 0.05:
            return _relength(desc, d[p])
    return None


def _effects(kind: str, dur: float, doc: str):
    def breaker(desc: dict, rng) -> dict | None:
        joins = desc["joins"]
        idx = [k for k, j in enumerate(joins) if j["kind"] != kind]
        if not idx:
            return None
        m = max(1, int(round(rng.uniform(EFFECT_SHARE, 1.0) * len(joins))))
        out = copy.deepcopy(desc)
        for i in rng.choice(len(idx), size=min(m, len(idx)), replace=False):
            out["joins"][idx[int(i)]].update(kind=kind, dur=dur)
        _same_flags(out)
        return out
    breaker.__name__ = f"add_{kind}es" if kind.endswith("sh") else f"add_{kind}s"
    breaker.__doc__ = doc
    return breaker


add_flashes = _effects("flash", FLASH_S, "White flashes on many of the joins (VibeCut's playful look).")
add_dissolves = _effects("dissolve", DISSOLVE_S, "Dissolves on many of the joins, where time hasn't passed.")


def strip_effects(desc: dict, rng) -> dict | None:
    """Some or all of the creator's effects between shots (flashes,
    dissolves, dips) turned into straight cuts. The add_ breakers' other
    side: shown only effects added, the model would learn that fewer is
    always better, whatever the real edits did."""
    idx = [k for k, x in enumerate(join_kinds(desc)) if x not in ("cut", "jump")]
    if not idx or len(idx) < HABIT * len(desc["joins"]):
        return None
    m = max(1, int(round(rng.uniform(EFFECT_SHARE, 1.0) * len(idx))))
    out = copy.deepcopy(desc)
    for i in rng.choice(len(idx), size=min(m, len(idx)), replace=False):
        out["joins"][idx[int(i)]].update(kind="cut", dur=0.0)
        out["joins"][idx[int(i)]].pop("drawn", None)
    _same_flags(out)
    return out


def quantise_to_beat(desc: dict, rng) -> dict | None:
    """Every cut moved onto the beat grid (a half-second grid when no tempo
    is known): lengths in whole half-beats, the way a beat-locked edit
    cuts, whatever the action is doing."""
    mus = desc.get("music") or {}
    bpm = _v(mus.get("bpm"))
    unit = 30.0 / bpm if bpm > 0 else NO_BEAT_GRID
    d = _lengths(desc)
    if len(d) < 2:
        return None
    new, prev = [], 0.0
    for e in np.cumsum(d):
        prev = max(prev + unit, round(e / unit) * unit)
        new.append(prev)
    nd = np.diff([0.0, *new])
    if np.abs(nd - d).max() < 1e-3:
        return None
    out = _relength(desc, nd)
    if bpm > 0:
        out["music"] = {**mus, "beat": 1.0}
    return out


def _resize(desc: dict, k: int, new_d: float) -> dict | None:
    """One shot given a new length, the others scaled to keep the whole: the
    time an opening drags comes out of the rest, so the edit's length (and
    every rate a minute) stays the creator's and only the hold changes.
    None when the rest would be squeezed past recognition."""
    d = _lengths(desc)
    rest = float(d.sum() - d[k])
    left = float(d.sum()) - new_d
    if rest <= 0 or left < MIN_REST * rest:
        return None
    d = d * (left / rest)
    d[k] = new_d
    return _relength(desc, d)


def cold_open(desc: dict, rng) -> dict | None:
    """The held first shot cut to the video's typical length: the opening
    loses its moment to take the place in."""
    d = _lengths(desc)
    if len(d) < 3 or d[0] <= float(np.median(d)) * 1.2:
        return None
    return _resize(desc, 0, float(np.median(d)))


def long_open(desc: dict, rng) -> dict | None:
    """The first shot held three times as long: the opening drags."""
    if len(desc["shots"]) < 3:
        return None
    return _resize(desc, 0, float(_lengths(desc)[0]) * 3)


def stretch_ending(desc: dict, rng) -> dict | None:
    """The last shot held three times as long (only where the ending is the
    creator's, not where measuring stopped)."""
    if desc.get("cutoff") or len(desc["shots"]) < 3:
        return None
    return _resize(desc, len(desc["shots"]) - 1, float(_lengths(desc)[-1]) * 3)


def cold_ending(desc: dict, rng) -> dict | None:
    """The held last shot cut to the video's typical length: the edit stops
    instead of landing. The ending's other side, as cold_open is the
    opening's -- shown only a stretched ending, the model would learn that
    the shorter an ending, the better."""
    d = _lengths(desc)
    if desc.get("cutoff") or len(d) < 3 or d[-1] <= float(np.median(d)) * 1.2:
        return None
    return _resize(desc, len(d) - 1, float(np.median(d)))


def fade_in_out(desc: dict, rng) -> dict | None:
    """A fade from black at the start and to black at the end."""
    cut = bool(desc.get("cutoff"))
    if desc.get("open") and (desc.get("close") or cut):
        return None
    out = copy.deepcopy(desc)
    out["open"] = True
    if not cut:
        out["close"] = True
    return out


def no_fades(desc: dict, rng) -> dict | None:
    """The creator's fade from or to black taken off (fade_in_out's other side)."""
    cut = bool(desc.get("cutoff"))
    if not desc.get("open") and (cut or not desc.get("close")):
        return None
    out = copy.deepcopy(desc)
    out["open"] = False
    if not cut:
        out["close"] = False
    return out


def words_top(desc: dict, rng) -> dict | None:
    """Every caption moved to the top of the frame."""
    if not desc.get("words") or all(w.get("band") == "top" for w in desc["words"]):
        return None
    out = copy.deepcopy(desc)
    for w in out["words"]:
        w["band"] = "top"
    return out


def words_caps(desc: dict, rng) -> dict | None:
    """Every caption in capitals."""
    if not desc.get("words") or all(_v(w.get("upper")) >= 0.9 for w in desc["words"]):
        return None
    out = copy.deepcopy(desc)
    for w in out["words"]:
        w["upper"] = 1.0
    return out


def words_off_top(desc: dict, rng) -> dict | None:
    """The creator's top-of-frame words moved to the bottom (words_top's
    other side)."""
    ev = [w for w in desc.get("words") or [] if _num(w.get("d")) and w["d"] > 0]
    top = sum(float(w["d"]) for w in ev if w.get("band") == "top")
    if not ev or top < HABIT * sum(float(w["d"]) for w in ev):
        return None
    out = copy.deepcopy(desc)
    for w in out["words"]:
        if w.get("band") == "top":
            w["band"] = "bottom"
    return out


def words_lower(desc: dict, rng) -> dict | None:
    """The creator's capitals written in lower case (words_caps' other side)."""
    ups = [_v(w.get("upper")) for w in desc.get("words") or []]
    ups = [x for x in ups if math.isfinite(x)]
    if not ups or float(np.mean(ups)) < 0.5:
        return None
    out = copy.deepcopy(desc)
    for w in out["words"]:
        if _num(w.get("upper")):
            w["upper"] = 0.0
    return out


def words_everywhere(desc: dict, rng) -> dict | None:
    """Words over every shot from start to end, where the edit had a few:
    a running subtitle on a video that didn't need one."""
    words = desc.get("words")
    if words is None:
        return None
    total = float(_lengths(desc).sum())
    ev = [w for w in words if _num(w.get("d")) and w["d"] > 0]
    if ev and _union(ev, total) / total >= 0.9:
        return None
    bands = Counter()
    for w in ev:
        bands[w.get("band")] += float(w["d"])
    sizes = [float(w["size"]) for w in ev if _num(w.get("size"))]
    ups = [float(w["upper"]) for w in ev if _num(w.get("upper"))]
    ns = [int(w.get("n") or 0) for w in ev]
    kind = Counter(w.get("kind") for w in ev).most_common(1)[0][0] if ev else None
    out = copy.deepcopy(desc)
    out["words"] = [{"t": s["t"], "d": s["d"], "band": bands.most_common(1)[0][0] if bands else "bottom",
                     "size": round(float(np.median(sizes)), 3) if sizes else 0.05,
                     "upper": round(float(np.mean(ups)), 2) if ups else 0.0,
                     "n": int(np.median(ns)) if ns else 4, "kind": kind} for s in out["shots"]]
    return out


def words_none(desc: dict, rng) -> dict | None:
    """The captions taken out."""
    if not desc.get("words"):
        return None
    out = copy.deepcopy(desc)
    out["words"] = []
    return out


def long_talk(desc: dict, rng) -> dict | None:
    """The cutaways between talking shots taken out and their time given to
    the talk: one long take of someone talking where the edit broke it up
    with what they were talking about."""
    have = set(desc.get("have") or [])
    if not {"faces", "sound"} <= have:
        return None
    shots, n = desc["shots"], len(desc["shots"])
    use = have & set(KIND_READINGS)
    talk = [kind_of(s, r, use) == "talk" for s, r in zip(shots, motion_ranks(desc))]
    new_shots, new_joins, merged, k = [], [], False, 0
    while k < n:
        end = k
        if talk[k]:
            j = k + 1
            while True:
                m = j
                while m < n and not talk[m] and m - j < MAX_CUTAWAY:
                    m += 1
                if m < n and talk[m] and m > j:
                    end, j, merged = m, m + 1, True
                else:
                    break
        s = copy.deepcopy(shots[k])
        s["d"] = sum(float(x["d"]) for x in shots[k:end + 1])
        new_shots.append(s)
        if end < n - 1:
            new_joins.append(copy.deepcopy(desc["joins"][end]))
        k = end + 1
    if not merged:
        return None
    out = copy.deepcopy(desc)
    out["shots"], out["joins"] = new_shots, new_joins
    return _retime(out)


CONTENT = ("motion", "motion_in", "motion_out", "face", "facing", "people", "voice", "music", "laugh",
           "labels", "aesthetic", "role")


def repeat_shot(desc: dict, rng) -> dict | None:
    """A shot shown a second time further on, in another shot's place: the
    edit repeats itself."""
    shots = desc["shots"]
    n = len(shots)
    src = [k for k in range(n - 2) if shots[k].get("labels") and _num(shots[k].get("aesthetic"))]
    if n < 4 or not src:
        return None
    i = int(rng.choice(src))
    j = int(rng.integers(i + 2, n))
    out = copy.deepcopy(desc)
    for key in CONTENT:
        out["shots"][j][key] = copy.deepcopy(shots[i].get(key))
    return out


def music_off(desc: dict, rng) -> dict | None:
    """The music taken away."""
    mus = desc.get("music")
    if not mus or not _v(mus.get("on")) > 0:
        return None
    out = copy.deepcopy(desc)
    out["music"] = {"bpm": None, "on": 0.0, "beat": None}
    for s in out["shots"]:
        if s.get("music") is not None:
            s["music"] = 0.0
    return out


def add_music(desc: dict, rng) -> dict | None:
    """Music under all of an edit the creator left mostly without
    (music_off's other side)."""
    mus = desc.get("music")
    if not mus or not math.isfinite(_v(mus.get("on"))) or _v(mus.get("on")) >= 0.5:
        return None
    out = copy.deepcopy(desc)
    out["music"] = {**mus, "on": 1.0}
    return out


# Every damage that moves a reading one way has its other side here
# (add_flashes / strip_effects, words_top / words_off_top, words_caps /
# words_lower, fade_in_out / no_fades, music_off / add_music), the other
# side used only where the real edit has the trait, so which way is good
# comes from what the creators did, not from the list of damages.
# The other sides: whether one is a damage depends on the corpus (a reel
# full of flashes is told apart from its cut-only copy only when other
# creators flash too), so they're judged on a corpus with the habit.
MIRRORS = ("strip_effects", "no_fades", "words_off_top", "words_lower", "add_music")

BREAKERS = {
    "shuffle_all": shuffle_all, "swap_neighbours": swap_neighbours, "even_rhythm": even_rhythm,
    "permute_durations": permute_durations, "add_flashes": add_flashes,
    "add_dissolves": add_dissolves, "strip_effects": strip_effects, "quantise_to_beat": quantise_to_beat,
    "cold_open": cold_open, "long_open": long_open, "fade_in_out": fade_in_out, "no_fades": no_fades,
    "words_top": words_top, "words_off_top": words_off_top, "words_caps": words_caps,
    "words_lower": words_lower, "words_everywhere": words_everywhere, "words_none": words_none,
    "long_talk": long_talk, "repeat_shot": repeat_shot, "stretch_ending": stretch_ending,
    "cold_ending": cold_ending, "music_off": music_off, "add_music": add_music,
}
BREAKER_SAYS = {
    "shuffle_all": "every shot in a random order",
    "swap_neighbours": "a few shots swapped with the next one",
    "even_rhythm": "every shot the same length",
    "permute_durations": "the shots in order, their lengths handed out at random",
    "add_flashes": "white flashes on many joins",
    "add_dissolves": "dissolves on many joins",
    "strip_effects": "the creator's effects between shots turned into straight cuts",
    "quantise_to_beat": "every cut moved onto the beat (or a half-second grid)",
    "cold_open": "the held first shot cut to a typical length",
    "long_open": "the first shot held three times as long",
    "fade_in_out": "a fade from black at the start and to black at the end",
    "no_fades": "the creator's fades from or to black taken off",
    "words_top": "the words moved to the top of the frame",
    "words_off_top": "the creator's top-of-frame words moved to the bottom",
    "words_caps": "the words in capitals",
    "words_lower": "the creator's capitals in lower case",
    "words_everywhere": "words over every shot",
    "words_none": "the words taken out",
    "long_talk": "the cutaways between talking shots taken out",
    "repeat_shot": "a shot shown again later on",
    "stretch_ending": "the last shot held three times as long",
    "cold_ending": "the held last shot cut to a typical length",
    "music_off": "the music taken away",
    "add_music": "music under all of it",
}


def _rng(seed: int, did: str, name: str) -> np.random.Generator:
    """One stream per (seed, edit, breaker): the same damage whatever else is
    in the set, and a stable one (crc32, not Python's salted hash)."""
    return np.random.default_rng([int(seed), zlib.crc32(str(did).encode()), zlib.crc32(name.encode())])


# --------------------------------------------------------------------------
# fitting
# --------------------------------------------------------------------------

def _sig(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def _fit_pairs(D: np.ndarray, a: np.ndarray, l2: float, base: np.ndarray | None = None,
               iters: int = 100) -> np.ndarray:
    """Weights w that put the first of every pair above the second: minimise
    sum a log(1 + exp(-(base + w).D)) + l2/2 |w|^2 by Newton steps. Convex,
    so the same pairs always give the same weights."""
    n, k = D.shape
    b = np.zeros(k) if base is None else np.asarray(base, float)
    w = np.zeros(k)
    if not n:
        return w

    def obj(w):
        return float((a * np.logaddexp(0.0, -(D @ (b + w)))).sum() + 0.5 * l2 * w @ w)

    f = obj(w)
    for _ in range(iters):
        p = _sig(-(D @ (b + w)))            # the chance of getting each pair wrong
        g = -(D.T @ (a * p)) + l2 * w
        h = (D * (a * p * (1.0 - p))[:, None]).T @ D + l2 * np.eye(k)
        step = np.linalg.solve(h, g)
        t = 1.0
        while True:
            w1 = w - t * step
            f1 = obj(w1)
            if f1 <= f - 1e-4 * t * float(g @ step) or t < 1e-8:
                break
            t *= 0.5
        moved = float(np.abs(w1 - w).max())
        w, f = w1, f1
        if moved < 1e-10:
            break
    return w


def _fit_softmax(X: np.ndarray, y: np.ndarray, k: int, l2: float, iters: int = 60) -> np.ndarray:
    """Multinomial logistic regression by Newton steps: a weight row per
    class over the features plus a constant."""
    n = len(X)
    Xb = np.hstack([X, np.ones((n, 1))])
    p_ = Xb.shape[1]
    Y = np.zeros((n, k))
    Y[np.arange(n), y] = 1.0
    W = np.zeros((k, p_))

    def probs(W):
        L = Xb @ W.T
        L -= L.max(1, keepdims=True)
        E = np.exp(L)
        return E / E.sum(1, keepdims=True)

    def obj(W):
        L = Xb @ W.T
        m = L.max(1, keepdims=True)
        lse = (m + np.log(np.exp(L - m).sum(1, keepdims=True)))[:, 0]
        return float(lse.sum() - (Y * L).sum() + 0.5 * l2 * (W * W).sum())

    f = obj(W)
    for _ in range(iters):
        P = probs(W)
        G = (P - Y).T @ Xb + l2 * W
        M = (P[:, :, None] * Xb[:, None, :]).reshape(n, k * p_)
        H = -(M.T @ M)
        for c in range(k):
            sl = slice(c * p_, (c + 1) * p_)
            H[sl, sl] += (Xb * P[:, c:c + 1]).T @ Xb
        H += l2 * np.eye(k * p_)
        step = np.linalg.solve(H, G.ravel()).reshape(k, p_)
        t = 1.0
        while True:
            W1 = W - t * step
            f1 = obj(W1)
            if f1 <= f - 1e-4 * t * float((G * step).sum()) or t < 1e-8:
                break
            t *= 0.5
        moved = float(np.abs(W1 - W).max())
        W, f = W1, f1
        if moved < 1e-9:
            break
    return W


def _hits(m: np.ndarray) -> np.ndarray:
    """Right, wrong, or a tie that counts half."""
    return np.where(m > TIE, 1.0, np.where(m < -TIE, 0.0, 0.5))


# --------------------------------------------------------------------------
# roles: each shot's job in the story
# --------------------------------------------------------------------------

# Apple's label ids folded into what a shot is of, so a job can be read
# from "food" and "plate" alike. [prior, hand-written]
LABEL_GROUPS = {
    "people": ("people", "adult", "child", "baby", "crowd", "selfie", "portrait", "face", "person", "teen"),
    "food": ("food", "drink", "beverage", "cup", "coffee", "espresso", "latte", "tea", "plate", "tableware",
             "utensil", "kitchen", "restaurant", "cooking", "dessert", "cake", "bread", "pastry", "fruit",
             "sushi", "ramen", "noodle", "pizza", "burger", "breakfast", "wine", "beer", "cocktail"),
    "outdoors": ("sky", "outdoor", "landscape", "mountain", "beach", "ocean", "water", "tree", "plant", "flower",
                 "park", "forest", "sunset", "sunrise", "lake", "river", "field", "snow", "garden", "cloud",
                 "shore", "waterfall"),
    "city": ("street", "building", "structure", "city", "cityscape", "skyline", "skyscraper", "road", "crosswalk",
             "bridge", "alley", "store", "shop", "market", "shopping", "tower", "night"),
    "transit": ("vehicle", "car", "train", "subway", "bus", "airplane", "airport", "taxi", "bicycle", "boat",
                "aircraft", "path", "stairs"),
    "work": ("laptop", "computer", "keyboard", "desk", "office", "whiteboard", "classroom", "book", "document",
             "screen", "text", "paper", "monitor", "library"),
    "home": ("bed", "bedroom", "sofa", "couch", "room", "interior_room", "television", "bathroom", "mirror",
             "clothing", "cosmetics", "furniture"),
}
# Not where a shot sits (first, how far in): a job read from "it's first"
# would make every opening a hook, and hook_first would then read the
# order, not what the first shot holds.
ROLE_FEATURES = ("face", "facing", "voice", "laugh", "motion", "length", "last",
                 "part_start", *LABEL_GROUPS)


def _shot_rows(desc: dict) -> np.ndarray:
    """Per shot, what the role model reads: who is in it and heard, how it
    moves, how long it is against the video, whether it ends the video or
    opens a part, what it's of."""
    shots = desc.get("shots") or []
    n = len(shots)
    if not n:
        return np.zeros((0, len(ROLE_FEATURES)))
    have = set(desc.get("have") or [])
    d = _lengths(desc)
    med = float(np.median(d))
    rows = []
    for k, (s, r) in enumerate(zip(shots, motion_ranks(desc))):
        labels = set(s["labels"]) if isinstance(s.get("labels"), list) else None
        prev = shots[k - 1].get("chapter") if k else None
        rows.append([
            _v(s.get("face")) if "faces" in have else NAN,
            _v(s.get("facing")) if "faces" in have else NAN,
            _v(s.get("voice")) if "sound" in have else NAN,
            _v(s.get("laugh")) if "sound" in have else NAN,
            NAN if r is None else r,
            math.log(d[k] / med),
            1.0 if k == n - 1 and not desc.get("cutoff") else 0.0,
            # an unknown part is no new part
            1.0 if k and _num(s.get("chapter")) and s.get("chapter") != prev else 0.0,
            *[NAN if labels is None else float(bool(labels & set(g))) for g in LABEL_GROUPS.values()],
        ])
    return np.array(rows, dtype=float)


def _role_fit(X: np.ndarray, y: np.ndarray, k: int) -> dict:
    mean, std = _standardise(X)
    W = _fit_softmax(_zs(X, mean, std), y, k, ROLE_L2)
    return {"mean": mean, "std": std, "W": W}


def _role_predict(m: dict, X: np.ndarray) -> np.ndarray:
    Z = _zs(X, np.asarray(m["mean"]), np.asarray(m["std"]))
    return (np.hstack([Z, np.ones((len(Z), 1))]) @ np.asarray(m["W"]).T).argmax(1)


def _train_roles(reals: list[dict], who: dict) -> tuple[dict | None, dict]:
    """The role model on the shots whose job the AI editor named, and how
    often it names a creator's shots right when it never saw that creator."""
    X, y, f = [], [], []
    for d in reals:
        if "roles" not in (d.get("have") or []):
            continue
        rows = _shot_rows(d)
        for k, s in enumerate(d["shots"]):
            if s.get("role") in ROLES:
                X.append(rows[k])
                y.append(s["role"])
                f.append(who[d["id"]])
    rep: dict = {"shots": len(y), "trained": False, "needs": ROLE_MIN, "creators": len(set(f)),
                 "majority_baseline": round(max(Counter(y).values()) / len(y), 3) if y else None}
    if len(y) < ROLE_MIN:
        rep["why"] = f"{len(y)} shots carry a job from the AI editor (it needs {ROLE_MIN})"
        return None, rep
    if len(set(f)) < ROLE_CREATORS:
        rep["why"] = (f"the named shots come from {len(set(f))} creator{'s' * (len(set(f)) != 1)}; "
                      f"it needs {ROLE_CREATORS} to be checked on one it never saw")
        return None, rep
    X, f = np.array(X), np.array(f)
    classes = [r for r in ROLES if r in set(y)]
    yi = np.array([classes.index(r) for r in y])
    hits = []
    for g in sorted(set(f)):
        te = f == g
        if te.all():
            continue
        m = _role_fit(X[~te], yi[~te], len(classes))
        hits += list((_role_predict(m, X[te]) == yi[te]).astype(float))
    loco = round(float(np.mean(hits)), 3) if hits else None
    rep.update(classes=dict(sorted(Counter(y).items())), loco=loco)
    if loco is None or loco < rep["majority_baseline"] + ROLE_MARGIN:
        rep["why"] = (f"on a creator it never saw it names {_pct(loco)} of jobs right, against "
                      f"{_pct(rep['majority_baseline'])} for always guessing the commonest")
        return None, rep
    m = _role_fit(X, yi, len(classes))
    rep["trained"] = True
    return {"classes": classes, "features": list(ROLE_FEATURES), "mean": m["mean"].tolist(),
            "std": m["std"].tolist(), "W": m["W"].tolist(), "shots": len(y), "loco": rep["loco"]}, rep


# --------------------------------------------------------------------------
# the model
# --------------------------------------------------------------------------

def _fmt(unit: str, v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "unknown"
    if unit == "share":
        return f"{v * 100:.0f}%"
    if unit == "x":
        return f"{math.exp(v):.1f}×"
    if unit == "s":
        return f"{v:.1f} s"
    if unit == "rate":
        return f"{v:.1f} a minute"
    if unit == "yes":
        return "yes" if v >= 0.5 else "no"
    return f"{v:+.2f}"


def _clean(x):
    """JSON without NaN: a missing number is None."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    return x


def _arr(xs) -> np.ndarray:
    return np.array([NAN if x is None else float(x) for x in xs], dtype=float)


class Model:
    """A group's learnt taste. `score` puts a real edit above its damaged
    copies; `explain` says why, in plain words. Loaded from
    taste/model/<group>.json (`load`)."""

    def __init__(self, group: str, *, w, mean, std, centre, scale, typical, real_z, grammars: dict,
                 roles: dict | None = None, report: dict | None = None, trained_on=(), date: str = "",
                 seed: int = 0):
        self.group = group
        self.names = NAMES + FAR_NAMES
        self.w = np.asarray(w, float)
        self.mean, self.std = np.asarray(mean, float), np.asarray(std, float)
        self.centre, self.scale = np.asarray(centre, float), np.asarray(scale, float)
        self.typical = np.asarray(typical, float)          # the real edits' median, base features
        self.real_z = np.asarray(real_z, float)            # the real edits' mean, standardised
        self.grammars = grammars
        self.roles = roles
        self.report = report or {}
        self.trained_on = list(trained_on)
        self.date, self.seed = date, seed
        self.u = np.zeros(len(self.names))                 # her offset (personal_fit); zero until she picks

    # -- reading ---------------------------------------------------------
    def fill_roles(self, desc: dict) -> dict:
        """A copy with each shot's job named by the role model, when the
        edit carries none and the model has learnt to name them."""
        if not self.roles or "roles" in (desc.get("have") or []) or not desc.get("shots"):
            return desc
        out = copy.deepcopy(desc)
        for s, i in zip(out["shots"], _role_predict(self.roles, _shot_rows(desc))):
            s["role"] = self.roles["classes"][int(i)]
        have = set(out.get("have") or []) | {"roles"}
        out["have"] = [x for x in READINGS if x in have]
        out["roles_filled"] = True
        return out

    def _vector(self, desc: dict) -> np.ndarray:
        phi = features_of(self.fill_roles(desc), self.grammars)
        return _expand(np.array([[phi[k] for k in NAMES]], dtype=float), self.centre, self.scale)[0]

    def features(self, desc: dict) -> dict[str, float]:
        """Every feature the score weighs, by name (NaN: no reading)."""
        return dict(zip(self.names, map(float, self._vector(desc))))

    def _z(self, x: np.ndarray) -> np.ndarray:
        return _zs(x[None, :], self.mean, self.std)[0]

    def score(self, desc: dict) -> float:
        """How much this edit reads like the group's real edits (higher is
        better; only differences between edits mean anything)."""
        return float(self._z(self._vector(desc)) @ (self.w + self.u))

    def explain(self, desc: dict, top: int = 3, against: dict | None = None) -> list[dict]:
        """What moves this edit's score most, each in plain words against the
        good edits' typical value: [{feature, says, value, typical, effect}],
        effect > 0 helping -- what the edit gains or loses on a typical good
        edit, so all the lines add up to the gap between the two scores. A
        feature and its distance from the middle are one line. With `against`
        (another version of the same video): the same against that version."""
        filled = self.fill_roles(desc)
        x = self._vector(filled)
        if against is None:
            ref, gw = self.typical, f"the good {GROUP_WORDS.get(self.group, 'edits')}"
            y = _expand(ref[None, :], self.centre, self.scale)[0]
        else:
            y = self._vector(against)
            ref, gw = y[:len(NAMES)], "the other version"
        eff = (self._z(x) - self._z(y)) * (self.w + self.u)
        rows = []
        for i, name in enumerate(NAMES):
            e = float(eff[i])
            if name in FAR:
                e += float(eff[len(NAMES) + FAR.index(name)])
            v, typ = float(x[i]), float(ref[i])
            if abs(e) < 1e-6 or not math.isfinite(v):
                continue
            rows.append((-abs(e), name, e, v, typ if math.isfinite(typ) else None))
        out = []
        for _, name, e, v, typ in sorted(rows)[:max(0, top)]:
            unit, _, more, less = _SAYS[name]
            up = v > typ if typ is not None and v != typ else (v - self.mean[NAMES.index(name)]) > 0
            phrase = more if up else less
            where = f"{_fmt(unit, v)} here, {_fmt(unit, typ)} in {gw}" if typ is not None else f"{_fmt(unit, v)} here"
            says = f"{phrase[0].upper()}{phrase[1:]} ({where}), which {'helps' if e > 0 else 'counts against it'}"
            note = self._unusual(filled, name) if e < 0 and not up else None
            out.append({"feature": name, "says": f"{says}, most of all {note}." if note else f"{says}.",
                        "value": round(v, 3), "typical": None if typ is None else round(typ, 3),
                        "effect": round(e, 3)})
        return out

    def _unusual(self, desc: dict, name: str) -> str | None:
        """For a grammar line: the part of the edit's shots the good edits use
        least like it ("the white flashes (64% of the joins here, none in the
        good shorts)"); None for any other line, or when no part stands out
        (a shuffle keeps every part: only its order is off)."""
        level = GRAMMAR_LEVEL.get(name)
        key = _kind_key(desc, self.grammars.get("kind") or {}) if level == "kind" else None
        path = ("kind", key) if key else (level,) if level and level != "kind" else None
        g = _at(self.grammars, path) if path else None
        seq = _tokens_at(desc, path) if g is not None else None
        if not seq:
            return None
        best = None
        for slot in (-1, -2) if level == "dur" else (-1, -2, 0):
            good = g.shares(slot)
            for val, here in _shares(Counter(t.split("|")[slot] for t in seq)).items():
                gap = here - good.get(val, 0.0)
                if gap >= NOTE_GAP and (best is None or gap > best[0]):
                    best = (gap, slot, val, here, good.get(val, 0.0))
        if best is None:
            return None
        _, slot, val, here, there = best
        return (f"the {PART_WORDS.get(val, val.replace('R:', '').replace('_', ' '))} "
                f"({here * 100:.0f}% of the {'joins' if slot == -1 else 'shots'} here, "
                f"{'none' if there == 0 else f'{there * 100:.0f}%'} in the good "
                f"{GROUP_WORDS.get(self.group, 'edits')})")

    # -- files -----------------------------------------------------------
    def to_json(self) -> dict:
        g = self.grammars
        return _clean({
            "kind": FILE_KIND, "version": VERSION, "group": self.group, "date": self.date, "seed": self.seed,
            "features": self.names, "far": list(FAR),
            "w": self.w.tolist(), "mean": self.mean.tolist(), "std": self.std.tolist(),
            "centre": self.centre.tolist(), "scale": self.scale.tolist(),
            "typical": self.typical.tolist(), "real_z": self.real_z.tolist(),
            "grammar": {"dur": g["dur"].to_json() if g.get("dur") else None,
                        "kind": {k: x.to_json() for k, x in (g.get("kind") or {}).items()},
                        "role": g["role"].to_json() if g.get("role") else None},
            "roles": self.roles, "report": self.report, "trained_on": self.trained_on,
        })

    @classmethod
    def from_json(cls, d: dict) -> Model:
        if d.get("features") != NAMES + FAR_NAMES:
            raise ValueError("the model file was trained on other features; train it again")
        g = d.get("grammar") or {}
        grammars = {"dur": Grammar.from_json(g["dur"]) if g.get("dur") else None,
                    "kind": {k: Grammar.from_json(x) for k, x in (g.get("kind") or {}).items()},
                    "role": Grammar.from_json(g["role"]) if g.get("role") else None}
        return cls(d["group"], w=_arr(d["w"]), mean=_arr(d["mean"]), std=_arr(d["std"]),
                   centre=_arr(d["centre"]), scale=_arr(d["scale"]), typical=_arr(d["typical"]),
                   real_z=_arr(d["real_z"]), grammars=grammars, roles=d.get("roles"),
                   report=d.get("report"), trained_on=d.get("trained_on") or [], date=d.get("date") or "",
                   seed=int(d.get("seed") or 0))


# --------------------------------------------------------------------------
# training
# --------------------------------------------------------------------------

def _usable(descs: list[dict], group: str) -> tuple[list[dict], list[str]]:
    reals, skipped = [], []
    for k, d in enumerate(descs):
        did = d.get("id") or f"#{k + 1}"
        if group in GROUPS and d.get("group") not in (group, None):
            continue
        bad = validate(d) if validate else ([] if d.get("shots") else ["no shots"])
        if bad:
            skipped.append(did)
            continue
        reals.append({**d, "id": did})
    return sorted(reals, key=lambda d: str(d["id"])), skipped


def _finite_mean(xs) -> float:
    xs = [x for x in xs if math.isfinite(x)]
    return float(np.mean(xs)) if xs else 0.0


def _centre(full: dict, held: dict, reals: list[dict], who: dict) -> None:
    """Centre every grammar on the real edits' own reading, each edit read
    by a grammar that never saw its creator."""
    for path, g in _levels(full):
        lp, order = [], []
        for d in reals:
            gl = _at(held[who[d["id"]]], path)
            seq = _tokens_at(d, path)
            if gl is not None and seq:
                a, b = gl.raw(seq)
                lp.append(a)
                order.append(b)
        if not lp:       # a single creator: read by the grammar that saw them (says so in the report)
            for d in reals:
                seq = _tokens_at(d, path)
                if seq:
                    a, b = g.raw(seq)
                    lp.append(a)
                    order.append(b)
        ref = (_finite_mean(lp), _finite_mean(order))
        g.ref = ref
        for f in held.values():
            gl = _at(f, path)
            if gl is not None:
                gl.ref = ref


def train(descs: list[dict], group: str, creators: dict[str, str], seed: int = 0) -> tuple[Model, dict]:
    """Learn a group's taste from its real edits: the grammar, the scorer on
    real-vs-damaged pairs, the role model, and a report of how well it tells
    real from damaged on a creator it never saw and on a damage it was never
    shown. `creators` = {description id: creator}; an edit with no creator is
    its own. The same edits and seed give the same model."""
    reals, skipped = _usable(descs, group)
    if len(reals) < MIN_VIDEOS:
        raise ValueError(f"{len(reals)} usable {group} edits; the model needs {MIN_VIDEOS}")
    # one creator spelt two ways in the sheets would sit on both sides of a fold
    who = {d["id"]: str(creators.get(d["id"]) or d.get("creator") or d["id"]).strip().casefold() for d in reals}
    by = "creator" if len(set(who.values())) >= 2 else "video"
    if by == "video":     # one creator: each video stands for itself
        who = {i: i for i in who}
    folds = sorted(set(who.values()))

    # 1. grammars: one on everything for scoring, one per creator without them
    #    for the training features, so no edit is read by a grammar that saw it
    full = learn_grammars(reals)
    held = {f: learn_grammars([d for d in reals if who[d["id"]] != f]) for f in folds}
    _centre(full, held, reals, who)

    # 2. the pairs: each real edit against each damaged copy of it
    xr, xb, P = [], [], {"real": [], "broken": [], "name": [], "fold": []}
    for i, d in enumerate(reals):
        f = who[d["id"]]
        xr.append(features_of(d, held[f]))
        for name, br in BREAKERS.items():
            b = br(d, _rng(seed, d["id"], name))
            if b is None:
                continue
            xb.append(features_of(b, held[f]))
            for key, v in (("real", i), ("broken", len(xb) - 1), ("name", name), ("fold", f)):
                P[key].append(v)
    if not xb:
        raise ValueError("no damaged copy could be made of these edits")
    Xr, Xb = _matrix(xr), _matrix(xb)
    real, broken = np.array(P["real"]), np.array(P["broken"])
    names, fold = np.array(P["name"]), np.array(P["fold"])
    # every creator counts the same, however many videos they gave
    per = Counter(who.values())
    a = np.array([1.0 / per[f] for f in fold])
    a *= len(a) / a.sum()

    def fit(mask):
        rs = np.unique(real[mask])
        centre, scale = _centres(Xr[rs])
        Er, Eb = _expand(Xr, centre, scale), _expand(Xb, centre, scale)
        mean, std = _standardise(np.vstack([Er[rs], Eb[broken[mask]]]))
        Zr, Zb = _zs(Er, mean, std), _zs(Eb, mean, std)
        w = _fit_pairs(Zr[real[mask]] - Zb[broken[mask]], a[mask], L2)
        return w, centre, scale, mean, std, Zr, Zb

    def hits(params, mask):
        w, *_, Zr, Zb = params
        return _hits((Zr[real[mask]] - Zb[broken[mask]]) @ w)

    # 3. leave one creator out: real against damaged for someone it never saw
    #    The real edits' own scores the same way: the full model's grammar
    #    saw every one of them, so its reading of them is flattering, and an
    #    edit it never saw (VibeCut's export) would look worse beside them
    #    than it is.
    hit = np.full(len(real), NAN)
    real_loco = np.full(len(reals), NAN)
    for f in folds:
        te = fold == f
        if te.any() and (~te).any():
            params = fit(~te)
            hit[te] = hits(params, te)
            mine = [i for i, d in enumerate(reals) if who[d["id"]] == f]
            real_loco[mine] = params[5][mine] @ params[0]
    # 4. leave a damage out too: did it learn editing, or the damages it saw?
    held_out = {}
    for name in BREAKERS:
        sel = names == name
        got: list = []
        for f in folds:
            te, tr = sel & (fold == f), ~sel & (fold != f)
            if te.any() and tr.any():
                got += list(hits(fit(tr), te))
        if got:
            held_out[name] = round(float(np.mean(got)), 3)

    # 5. the model: every pair
    w, centre, scale, mean, std, Zr, _ = fit(np.ones(len(real), bool))
    roles, role_rep = _train_roles(reals, who)
    ok = np.isfinite(hit)
    report = _clean({
        "group": group, "date": time.strftime("%Y-%m-%d"), "seed": seed, "videos": len(reals),
        "creators": len(set(who.values())) if by == "creator" else 1, "grouped_by": by,
        "skipped": skipped, "pairs": int(len(real)),
        "breakers": {k: int((names == k).sum()) for k in BREAKERS if (names == k).any()},
        "loco": round(float(hit[ok].mean()), 3) if ok.any() else None,
        "loco_by_breaker": {k: round(float(hit[ok & (names == k)].mean()), 3)
                            for k in BREAKERS if (ok & (names == k)).any()},
        "loco_by_creator": {f: round(float(hit[ok & (fold == f)].mean()), 3) for f in folds if (ok & (fold == f)).any()},
        "held_out_breaker": held_out,
        "held_out_mean": round(float(np.mean(list(held_out.values()))), 3) if held_out else None,
        "real_scores_loco": {d["id"]: round(float(x), 4) for d, x in zip(reals, real_loco) if math.isfinite(x)},
        "weights": {k: round(float(x), 3) for k, x in sorted(zip(NAMES + FAR_NAMES, w), key=lambda kv: -abs(kv[1]))},
        "roles": role_rep,
        "grammar": {"dur": full["dur"].videos if full["dur"] else 0,
                    "kind": {k: g.videos for k, g in full["kind"].items()},
                    "role": full["role"].videos if full["role"] else 0},
    })
    model = Model(group, w=w, mean=mean, std=std, centre=centre, scale=scale, typical=_col_median(Xr),
                  real_z=Zr.mean(0), grammars=full, roles=roles, report=report,
                  trained_on=[d["id"] for d in reals], date=report["date"], seed=seed)
    return model, report


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------

def save(model: Model, path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(model.to_json(), indent=1, ensure_ascii=False, allow_nan=False))
    tmp.replace(p)


def load(group: str, personal: bool = True) -> Model | None:
    """The group's trained model (taste/model/<group>.json) with her offset
    on it; None when nothing has been trained yet."""
    try:
        d = json.loads((MODEL_DIR / f"{group}.json").read_text())
    except (OSError, ValueError):
        return None
    if d.get("kind") != FILE_KIND or d.get("version") != VERSION:
        return None
    try:
        m = Model.from_json(d)
    except (KeyError, ValueError, TypeError):
        return None
    if personal:
        fit = (_personal().get("fit") or {}).get(group) or {}
        # her offset was fitted against one model's weights and spreads; on
        # a model trained since, it would push in directions that no longer
        # mean the same thing -- none until personal_fit runs again
        if fit.get("model") == model_stamp(m):
            u = dict(zip(fit.get("features") or [], fit.get("u") or []))
            m.u = np.array([float(u.get(k) or 0.0) for k in m.names])
    return m


def model_stamp(m: Model) -> str:
    """Which trained model this is: its day, seed and weights."""
    w = json.dumps([round(float(x), 6) for x in m.w])
    return f"{m.group}|{m.date}|{m.seed}|{zlib.crc32(w.encode()):08x}"


# --------------------------------------------------------------------------
# her layer
# --------------------------------------------------------------------------

def _personal_path() -> Path:
    return Path(os.environ.get("VIBECUT_CACHE", "~/.cache/vibecut")).expanduser() / "taste" / "personal.json"


def _personal() -> dict:
    try:
        data = json.loads(_personal_path().read_text())
    except (OSError, ValueError):
        data = {}
    return {"v": 1, "pairs": [], "fit": {}, "yes": [], **data}


def _write_personal(data: dict) -> None:
    p = _personal_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(data), ensure_ascii=False))
    tmp.replace(p)


def _record(kind: str, better: dict | None, worse: dict, why: str, weight: float) -> None:
    group = (better or {}).get("group") or worse.get("group")
    data = _personal()
    data["pairs"] = (data["pairs"] + [{"kind": kind, "group": group, "better": better, "worse": worse,
                                       "why": str(why or "")[:200], "weight": weight,
                                       "at": round(time.time(), 1)}])[-MAX_PAIRS:]
    _write_personal(data)


def record_pick(better: dict, worse: dict, why: str = "") -> None:
    """She chose `better` over `worse` (two versions of one video)."""
    _record("pick", better, worse, why, 1.0)


def record_edit(made: dict, exported: dict, why: str = "") -> None:
    """The board she exported against the one Make made: what she changed
    says what she prefers. Nothing is kept when she changed nothing."""
    if json.dumps(_clean(made), sort_keys=True) == json.dumps(_clean(exported), sort_keys=True):
        return
    _record("edit", exported, made, why, 1.0)


def record_verdict(desc: dict, post: bool, why: str = "") -> None:
    """"Would you post this?" -- a no puts the export below the exports she
    said yes to, weakly: it says something is wrong, not what. Against
    another of her exports, not the reels: a board and a reel differ most
    in where they come from (fades, caption bands), which isn't her taste.
    A yes is kept as that yardstick; a no with no yes yet waits for one."""
    if post:
        group = desc.get("group")
        data = _personal()
        data["yes"] = (list(data.get("yes") or []) + [{"group": group, "desc": desc,
                                                        "at": round(time.time(), 1)}])[-MAX_YES:]
        _write_personal(data)
    else:
        _record("verdict", None, desc, why, WEAK)


def personal_fit(models: dict | None = None) -> dict:
    """Refit her offset u from every stored pair, per group with a trained
    model (`models` = {group: Model} to use instead of the files): the score
    becomes (w + u).z, u pulled to zero by PERSONAL_L2 so a handful of picks
    move it a little. Returns what moved, per group."""
    data = _personal()
    out = {}
    for group in sorted({p.get("group") for p in data["pairs"] if p.get("group")}):
        m = (models or {}).get(group) or load(group, personal=False)
        if m is None:
            out[group] = {"pairs": 0, "why": "no trained model for this group yet"}
            continue
        yes = [m._z(m._vector(y["desc"])) for y in data.get("yes") or []
               if y.get("group") == group and y.get("desc")]
        yes_z = np.mean(yes, axis=0) if yes else None
        rows, a, waiting = [], [], 0
        for p in data["pairs"]:
            if p.get("group") != group or not p.get("worse"):
                continue
            if p.get("better") is None:
                if yes_z is None:           # a no with nothing of hers to weigh it against
                    waiting += 1
                    continue
                hi = yes_z
            else:
                hi = m._z(m._vector(p["better"]))
            rows.append(hi - m._z(m._vector(p["worse"])))
            wt = float(p.get("weight") or 1.0)
            if p.get("kind") == "pick":
                d2 = float(np.nansum(rows[-1] ** 2))
                wt *= PICK_STEP / max(d2, PICK_FLOOR)
            a.append(wt)
        u = _fit_pairs(np.array(rows), np.array(a), PERSONAL_L2, base=m.w) if rows else np.zeros(len(m.names))
        data["fit"][group] = {"features": m.names, "u": [round(float(x), 6) for x in u], "pairs": len(rows),
                              "model": model_stamp(m), "at": round(time.time(), 1)}
        top = sorted(zip(m.names, u), key=lambda kv: -abs(kv[1]))[:3]
        out[group] = {"pairs": len(rows), "waiting": waiting,
                      "moved": round(float(np.linalg.norm(u) / max(np.linalg.norm(m.w), 1e-9)), 3),
                      "top": [{"feature": k, "u": round(float(x), 3)} for k, x in top if abs(x) > 1e-6]}
    _write_personal(data)
    return out


# --------------------------------------------------------------------------
# the report, the command line
# --------------------------------------------------------------------------

def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _means(name: str) -> str:
    return FAR_SAYS[name[4:]] if name.startswith("far_") else _SAYS[name][1]


def report_md(model: Model, rep: dict, others: list[tuple[str, float, list[str]]] = ()) -> str:
    """The training report in plain words. `others` = (id, score, why) of
    edits that were scored and not learnt from (VibeCut's own exports)."""
    gw = GROUP_WORDS.get(model.group, model.group)
    unit = rep.get("grouped_by") or "creator"
    n_c = rep.get("creators") or 0
    lines = [f"# The taste model: {gw}", "",
             f"Learnt {rep['date']} from {rep['videos']} {gw} by {n_c} creator{'s' if n_c != 1 else ''} "
             f"(seed {rep['seed']}): {rep['pairs']} pairs, each a real edit against a copy the computer damaged "
             f"in one way. Only numbers and labels went in; none of anyone's video, frames or words.", "",
             "## Can it tell a real edit from a damaged one?", "",
             f"- On a {unit} it never saw (leave one {unit} out): **{_pct(rep.get('loco'))}** of pairs.",
             f"- On a damage it was never shown (that damage and that {unit} both left out): "
             f"**{_pct(rep.get('held_out_mean'))}** on average.",
             "- 50% is a coin toss; a tie counts half.", "",
             f"| Damage | What the computer did | {unit.capitalize()} never seen | Damage never shown |",
             "| --- | --- | --- | --- |"]
    for name in BREAKERS:
        if name in (rep.get("loco_by_breaker") or {}):
            lines.append(f"| {name} | {BREAKER_SAYS[name]} | {_pct(rep['loco_by_breaker'][name])} | "
                         f"{_pct((rep.get('held_out_breaker') or {}).get(name))} |")
    lines += ["", "A damage the second column can't see is one only that damage teaches; a high first column "
              "with a low second one means the model learnt that damage, not editing.", "",
              "## What it weighs", "",
              "The strongest signals; a + means the real edits have more of it than the damaged ones.", ""]
    for name, wt in list((rep.get("weights") or {}).items())[:12]:
        if abs(wt) >= 0.01:
            lines.append(f"- {wt:+.2f}  {_means(name)}")
    r = rep.get("roles") or {}
    lines += ["", "## Story jobs (the role model)", ""]
    if r.get("trained"):
        lines.append(f"Trained on {r['shots']} shots whose job the AI editor named; names a creator's shots "
                     f"right {_pct(r.get('loco'))} of the time when it never saw that creator, against "
                     f"{_pct(r.get('majority_baseline'))} for always guessing the commonest job. "
                     f"Jobs seen: {', '.join(f'{k} {v}' for k, v in (r.get('classes') or {}).items())}.")
    else:
        why = r.get("why") or f"{r.get('shots', 0)} shots carry a job from the AI editor (it needs {ROLE_MIN})"
        lines.append(f"Not trained: {why}.")
    g = rep.get("grammar") or {}
    kinds = ", ".join(f"{k.replace('+', ', ')} ({v})" for k, v in (g.get("kind") or {}).items()) or "none"
    lines += ["", "## Grammar", "",
              f"Shot lengths and joins learnt from {g.get('dur', 0)} videos; what each shot is, by the readings "
              f"there were: {kinds}; story jobs from {g.get('role', 0)}.", ""]
    if others:
        lines += ["## Scored, not learnt from", ""]
        for oid, sc, why in others:
            lines.append(f"- {oid}: {sc}")
            lines += [f"  - {x}" for x in why]
        lines.append("")
    lines += ["## Read with care", "",
              "- The real side is what these creators did, not proof of what is good; the damaged side is the "
              "computer's idea of a mistake. The model learns what separates the two.",
              f"- The sample is the creators, not the videos: {n_c} here. Each creator counts the same however "
              "many videos they gave.",
              "- A reading that wasn't taken (no faces off the Mac, no words when Vision didn't run) counts as "
              "neither good nor bad.",
              "- Every threshold that turns readings into tokens (quick, held, talking, moving) is a prior."]
    if rep.get("skipped"):
        lines.append(f"- Left out as unreadable: {', '.join(rep['skipped'])}.")
    return "\n".join(lines) + "\n"


def _csv_rows() -> list[dict]:
    rows = []
    for p in sorted(DATA.glob("*.csv")):
        with p.open(newline="") as f:
            rows += [r for r in csv.DictReader(f) if r.get("id")]
    return rows


def _read_descriptions(folder: Path) -> list[dict]:
    out = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            print(f"  {p.name}: not readable, left out")
            continue
        d.setdefault("id", p.stem)
        d["id"] = d["id"] or p.stem
        out.append(d)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m taste.model", description="The taste model: train, score.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="learn from taste/descriptions/*.json")
    t.add_argument("--group", choices=["long", "short", "all"], default="all", help="all = each group in turn")
    t.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("score", help="score one description")
    s.add_argument("desc")
    s.add_argument("--group", choices=list(GROUPS))
    sub.add_parser("personal", help="refit her layer from the stored picks")
    a = ap.parse_args(argv)

    if a.cmd == "personal":
        print(json.dumps(personal_fit(), indent=1))
        return 0
    if a.cmd == "score":
        desc = json.loads(Path(a.desc).read_text())
        group = a.group or desc.get("group") or GROUP_OF_ID.get(str(desc.get("id") or "")[:1]) or "short"
        m = load(group)
        if m is None:
            print(f"no {group} model yet: python -m taste.model train --group {group}")
            return 1
        print(f"{m.score(desc):+.2f}  ({GROUP_WORDS[group]} model of {m.date}, learnt from {len(m.trained_on)} videos)")
        for e in m.explain(desc, top=5):
            print(f"  {e['says']}")
        return 0

    descs = _read_descriptions(DESCRIPTIONS)
    rows = _csv_rows()
    in_csv = {r["id"]: r for r in rows}
    good = {r["id"] for r in rows if r.get("verdict") in ("good", "sarah")}
    creators = {r["id"]: r.get("creator") or "" for r in rows}
    for d in descs:
        d["group"] = d.get("group") or (in_csv.get(d["id"]) or {}).get("group") or GROUP_OF_ID.get(d["id"][:1])
    groups = GROUPS if a.group == "all" else (a.group,)
    done = 0
    for g in groups:
        mine = [d for d in descs if d.get("group") == g
                and (in_csv.get(d["id"]) or {}).get("status") != "not a vlog"]
        # real = a good row of the set, or one carrying its own creator; the
        # rest (VibeCut's own exports, rows not judged good) are scored in the
        # report, never learnt from
        reals = [d for d in mine if d["id"] in good or (d["id"] not in in_csv and d.get("creator"))]
        others = [d for d in mine if d not in reals]
        if len(reals) < MIN_VIDEOS:
            print(f"{g}: {len(reals)} described, too few to learn from (needs {MIN_VIDEOS})")
            continue
        model, rep = train(reals, g, creators, seed=a.seed)
        save(model, MODEL_DIR / f"{g}.json")
        if any(p.get("group") == g for p in _personal()["pairs"]):
            personal_fit()          # her layer, refitted against the new weights
        # each real edit as scored by a model that never saw its creator, the
        # way the others (never learnt from) are seen
        real_scores = list((rep.get("real_scores_loco") or {}).values()) or [model.score(d) for d in reals]
        scored = []
        for d in others:
            sc = model.score(d)
            below = sum(x > sc for x in real_scores)
            scored.append((d["id"], f"{sc:+.2f}, below {below} of {len(real_scores)} real {GROUP_WORDS[g]}",
                           [e["says"] for e in model.explain(d)]))
        (MODEL_DIR / f"{g}-report.md").write_text(report_md(model, rep, scored))
        print(f"{g}: {rep['videos']} videos by {rep['creators']} {rep['grouped_by']}s, {rep['pairs']} pairs; "
              f"real beats damaged {_pct(rep['loco'])} on an unseen {rep['grouped_by']}, "
              f"{_pct(rep['held_out_mean'])} on an unseen damage -> {MODEL_DIR / f'{g}.json'}")
        done += 1
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
