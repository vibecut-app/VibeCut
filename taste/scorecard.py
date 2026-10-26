"""One of VibeCut's own videos against a group's house style.

For every trait the house style has, the video's number is inside the good
vlogs' middle half, or below / above it, with how far. Report only: what to
change is a person's call until the set is no longer thin.

    python -m taste.scorecard measurements/V001.json --group short
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import fingerprint as fp_mod

HERE = Path(__file__).parent


def score(rec: dict, fp: dict) -> list[dict]:
    out = []
    for name, path, means in fp_mod.TRAITS:
        t = fp["traits"].get(name)
        if not t or fp_mod._pending(rec, path):
            continue
        v = fp_mod._get(rec, path)
        if v is None:
            continue
        where = "inside" if t["low"] <= v <= t["high"] else ("below" if v < t["low"] else "above")
        out.append({"trait": name, "value": round(v, 3), "low": t["low"], "high": t["high"],
                    "median": t["median"], "where": where, "means": means})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--group", required=True, choices=["long", "short"])
    a = ap.parse_args()
    rec = json.loads(Path(a.record).read_text())
    fp = json.loads((HERE / "fingerprints" / f"{a.group}.json").read_text())
    rows = score(rec, fp)
    for r in rows:
        print(f"{r['where']:6s} {r['trait']:15s} {r['value']:>9}  good: {r['low']} – {r['high']}  {r['means']}")
    print(f"{sum(r['where'] == 'inside' for r in rows)} of {len(rows)} inside")


if __name__ == "__main__":
    main()
