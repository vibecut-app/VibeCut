"""Day-in-my-life captions: the time on the clock and what's happening.

"7:42 am · coffee run" over the shot it describes is the grammar of the
genre -- the viewer follows the day by the clock, and the phrase tells them
why this moment is in it. Both halves come from the footage, never made up:

- the time is the clip's own recording time (its metadata) plus how far into
  the clip the shot starts, so two shots from one long clip read correctly;
- the phrase is read from the on-device image labels (Vision) of the shot.
  With a key, Claude turns each shot's *labels and time* into a short phrase
  -- text only, no frames leave the Mac; otherwise a fixed table does it.
  A shot whose labels say nothing specific gets the time alone.

A new caption only where the day moves on: the activity changes, or enough
time has passed that the clock alone is news. Every caption is an ordinary
overlay (kind "caption"), so it can be retyped or removed by hand, and the
whole set is one turn that one Undo takes away.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Vision label -> what a creator would write. Most specific first: a shot
# labelled both "food" and "sushi" should say sushi. [prior, hand-written]
PHRASES: list[tuple[str, str]] = [
    ("sushi", "sushi time"), ("ramen", "ramen stop"), ("noodle", "noodles"), ("pizza", "pizza"),
    ("burger", "burger break"), ("dessert", "something sweet"), ("cake", "something sweet"),
    ("ice_cream", "ice cream"), ("bread", "bakery run"), ("pastry", "bakery run"),
    ("coffee", "coffee run"), ("espresso", "coffee run"), ("latte", "coffee run"), ("tea", "tea break"),
    ("cocktail", "drinks"), ("wine", "drinks"), ("beer", "drinks"), ("bar", "drinks"),
    ("breakfast", "breakfast"), ("cooking", "cooking"), ("kitchen", "in the kitchen"),
    ("restaurant", "eating out"), ("plate", "lunch"), ("tableware", "lunch"), ("utensil", "lunch"),
    ("gym", "workout"), ("dumbbell", "workout"), ("yoga", "yoga"), ("running", "a run"),
    ("bicycle", "bike ride"), ("swimming_pool", "pool time"), ("beach", "beach"), ("ocean", "by the sea"),
    ("hiking", "hike"), ("mountain", "up the mountain"), ("forest", "into the woods"), ("park", "park walk"),
    ("flower", "flowers"), ("garden", "garden"),
    ("laptop", "work work work"), ("computer", "work work work"), ("keyboard", "work work work"),
    ("desk", "desk time"), ("office", "at the office"), ("whiteboard", "class time"),
    ("classroom", "class time"), ("podium", "lecture"), ("book", "study time"), ("document", "study time"),
    ("library", "library"), ("store", "shopping"), ("shopping", "shopping"), ("market", "market"),
    ("clothing", "getting ready"), ("mirror", "getting ready"), ("cosmetics", "getting ready"),
    ("bathroom", "getting ready"), ("bed", "slow morning"), ("bedroom", "at home"), ("sofa", "couch time"),
    ("television", "movie night"), ("dog", "dog time"), ("cat", "cat time"),
    ("train", "on the train"), ("subway", "on the train"), ("airplane", "flying"), ("airport", "airport"),
    ("bus", "on the bus"), ("car", "on the way"), ("taxi", "on the way"), ("crosswalk", "heading out"),
    ("street", "out and about"), ("crowd", "out and about"), ("temple", "temple visit"),
    ("museum", "museum"), ("concert", "concert"), ("stage", "show time"), ("fireworks", "fireworks"),
    ("sunset", "sunset"), ("sunrise", "sunrise"), ("night", "night out"),
    ("stairs", "up we go"), ("path", "walking"),
    # scenery: what the place looks like, when nothing is happening in it
    ("waterfall", "waterfall"), ("lake", "by the lake"), ("river", "along the river"), ("shore", "by the water"),
    ("harbor", "harbour views"), ("harbour", "harbour views"), ("boat", "out on the water"), ("bridge", "over the bridge"),
    ("snow", "snow day"), ("desert", "desert"), ("canyon", "canyon views"), ("cliff", "cliffside"),
    ("volcano", "volcano"), ("field", "open fields"), ("vineyard", "vineyard"), ("rainforest", "into the jungle"),
    ("castle", "castle"), ("palace", "palace"), ("church", "old church"), ("cathedral", "cathedral"),
    ("shrine", "shrine visit"), ("pagoda", "temple visit"), ("monument", "sightseeing"), ("statue", "sightseeing"),
    ("skyscraper", "city views"), ("cityscape", "city views"), ("skyline", "city views"), ("tower", "city views"),
    ("alley", "back streets"), ("neon", "neon nights"), ("night_sky", "night sky"), ("rainbow", "rainbow"),
    ("rain", "rainy day"), ("umbrella", "rainy day"), ("hotel", "check-in"), ("pool", "pool time"),
    ("amusement_park", "theme park"), ("roller_coaster", "theme park"), ("zoo", "zoo day"), ("aquarium", "aquarium"),
    ("stadium", "game day"), ("festival", "festival"), ("parade", "parade"), ("wedding", "wedding"),
    ("cake_candles", "birthday"), ("gift", "presents"), ("balloon", "party"),
    # generic last: they speak only when nothing more specific does
    ("cup", "coffee run"), ("beverage", "drinks"), ("food", "food"),
    ("water", "by the water"),
    # no "sky": Vision sees sky in nearly every outdoor shot, so it said nothing ("look up" confused her)
    ("plant", "greenery"), ("tree", "greenery"),
]
_RANK = {k: i for i, (k, _) in enumerate(PHRASES)}
_SAYS = dict(PHRASES)
MIN_LABEL = 0.3        # a label weaker than this doesn't get to speak [prior]
NEW_TIME_S = 20 * 60   # the clock alone is worth a caption again after this long [prior]
MIN_SHOT_S = 1.2       # too short to read a caption over [prior]
HOLD_S = 2.5
AT_S = 0.15


def clock(dt: datetime) -> str:
    """7:42 am -- lowercase, the way the genre writes it."""
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'am' if dt.hour < 12 else 'pm'}"


def phrase(labels: dict[str, float]) -> str | None:
    """The most specific thing the labels are sure of, as a creator would say it."""
    said = phrases(labels)
    return said[0] if said else None


def phrases(labels: dict[str, float]) -> list[str]:
    """Everything the labels are sure of, most specific first, each said once."""
    hits = sorted((k for k, v in labels.items() if v >= MIN_LABEL and k in _SAYS), key=_RANK.__getitem__)
    return list(dict.fromkeys(_SAYS[k] for k in hits))


def moments(board: dict, cat, places: dict | None = None) -> list[dict]:
    """Shots on the board where the day moves on: [{key, len, when, labels, say, place}].

    `places`: {rounded gps: geocoder answer} (places.lookup). A new place is
    always a new moment, and is named once, where it starts."""
    from . import places as pl
    out: list[dict] = []
    last_when: datetime | None = None
    last_say: str | None = None
    last_place: str | None = None
    for bt in board.get("beats", []):
        for e in bt["shots"]:
            if e.get("gap") or not e.get("id") or e["end"] - e["start"] < MIN_SHOT_S:
                continue
            s = cat.shots.get(e["id"])
            if not s or s.when is None:
                continue
            when = s.when + timedelta(seconds=max(0.0, e["start"] - s.start))
            say = phrase(s.labels)
            place = pl.name_at(s.gps, places) if places else None
            moved = last_when is None or abs((when - last_when).total_seconds()) >= NEW_TIME_S
            arrived = place is not None and place != last_place
            if moved or arrived or (say and say != last_say):
                out.append({"key": e.get("key") or e["id"], "len": e["end"] - e["start"], "when": when,
                            "labels": {k: round(v, 2) for k, v in sorted(s.labels.items(), key=lambda kv: -kv[1])[:6]},
                            "say": say, "place": place if arrived else None})
                last_when, last_say = when, say or last_say
                last_place = place or last_place
    return out


def caption_ops(board: dict, cat, about: str = "", ask_model: bool | None = None,
                places: dict | None = None) -> tuple[list[dict], list[str]]:
    """-> (add_overlay ops, notes). One caption per moment the day moves on;
    where a new place starts, its name rides above the time."""
    ms = moments(board, cat, places)
    if not ms:
        return [], ["No time stamps: none of the clips in this story carry a recording time."]
    from . import llm
    if ask_model is None:
        ask_model = llm.available()
    if ask_model:
        try:
            said = llm.day_phrases([{"time": clock(m["when"]), "labels": list(m["labels"])} for m in ms], about)
            for m, p in zip(ms, said):
                if p:
                    m["say"] = p
        except llm.LLMError:
            pass    # the table's phrases stand
    ops = []
    for m in ms:
        text = clock(m["when"]) + (f" · {m['say']}" if m["say"] else "")
        op = {"op": "add_overlay", "kind": "caption", "text": text, "anchor": {"to": "shot", "id": m["key"]},
              "at": AT_S, "dur": round(min(HOLD_S, m["len"] - AT_S), 2)}
        if m.get("place"):
            op["sub"] = m["place"]
        ops.append(op)
    notes = []
    bare = sum(not m["say"] for m in ms)
    if bare:
        notes.append(f"{bare} of them show only the time: nothing in the picture said clearly what was happening. "
                     "Click one to type your own.")
    return ops, notes
