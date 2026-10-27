"""VibeCut's own songs: there when the search fails, never otherwise.

Four things must hold:

1. Each pack song measures as the tempo it was written at (the bed cuts on
   that grid; a half-time or dotted reading would put cuts off the beat),
   and its chorus is louder than its verse (the picker wants a shape).
2. When the online search hands back tracks, those are used and the pack is
   never touched.
3. When the search is empty or raises, or nothing it had fits the edit, the
   pack is used -- and the bed still lands a turn.
4. A failed Openverse search is not cached as "no songs" (it kept music off
   for a week); a real answer is cached.

    python tests/test_songpack.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

os.environ.setdefault("VIBECUT_CACHE", tempfile.mkdtemp(prefix="vibecut-pack-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cutgrammar import music as mu  # noqa: E402
from cutgrammar import openverse as ov  # noqa: E402
from cutgrammar import songpack as sp  # noqa: E402
from web.backend import bed  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, got: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + got if got else ''}")
    if not cond:
        failures.append(name)


def fake_track(path: str, bpm: float, seconds: float = 300.0) -> mu.Track:
    return mu.Track(path=path, duration=seconds, bpm=bpm, energy=np.linspace(0.2, 1, int(seconds), dtype=np.float32),
                    title=os.path.basename(path), meta={"tempo": {"phase": 0.1}})


def main() -> int:
    print("the songs keep their tempo")
    sp.LENGTH_S = 120.0   # two minutes reach the first chorus at any pace; the app renders the full length
    for s in (sp.songs_for("calm")[0], sp.songs_for("balanced")[0], sp.songs_for("fast")[0]):
        f = sp.ensure(s, sp.cache_dir() / s.pace)
        t = mu.analyse(str(f))
        check(f"{s.title} measures {s.bpm:.0f} BPM", t.bpm is not None and abs(t.bpm - s.bpm) / s.bpm < 0.01, str(t.bpm))
        plan = sp._plan(s)
        bar = 4 * 60.0 / s.bpm
        e = t.energy
        def level(name: str) -> float:
            # each bar of that section, past its first two (the 5 s smoothing still carries the last one)
            bars = [i for i, n in enumerate(plan) if n == name and i >= 2 and plan[i - 2] == name]
            return float(np.mean([e[int(i * bar):int((i + 1) * bar) + 1].mean() for i in bars]))
        ev, ec = level("verse"), level("chorus")
        check(f"{s.title}: the chorus is fuller than the verse", ec > ev + 0.1, f"{ev:.2f} -> {ec:.2f}")
    rendered = sp.cache_dir() / "calm" / f"{sp.songs_for('calm')[0].id}.m4a"
    before = rendered.stat().st_mtime_ns
    sp.ensure(sp.songs_for("calm")[0], sp.cache_dir() / "calm")
    check("a song is rendered once", rendered.stat().st_mtime_ns == before)
    check("every song is CC0 and credited to VibeCut",
          all(sp.record(s)["license"] == "cc0" and sp.record(s)["creator"] == "VibeCut" for s in sp.SONGS))
    check("eight songs per pace", all(len(sp.songs_for(p)) == 8 for p in sp.PACES))
    check("the credit line has no dangling link", not ov.credit(sp.record(sp.SONGS[0])).endswith("— "),
          ov.credit(sp.record(sp.SONGS[0])))

    print("the pack only when the search fails")
    real_list, real_pack = ov.OpenverseSource.list, sp.PackSource.list
    online = [fake_track("/online/a.mp3", 100.0)]
    pack = [fake_track("/pack/b.m4a", 100.0)]
    touched = []
    sp.PackSource.list = lambda self: touched.append(1) or list(pack)
    try:
        ov.OpenverseSource.list = lambda self: list(online)
        pool, source = bed.candidates("balanced", None)
        check("the search answered: its tracks are used", source == bed.ONLINE and pool[0].path == "/online/a.mp3", source)
        check("...and the pack isn't even read", not touched)

        ov.OpenverseSource.list = lambda self: []
        pool, source = bed.candidates("balanced", None)
        check("an empty search falls back to the pack", source == bed.PACK and pool[0].path == "/pack/b.m4a", source)

        def boom(self):
            raise OSError("certificate verify failed")
        ov.OpenverseSource.list = boom
        pool, source = bed.candidates("balanced", None)
        check("a search that raises falls back to the pack", source == bed.PACK, source)

        touched.clear()
        pool, source = bed.candidates("balanced", [fake_track("/mine/c.mp3", 100.0)])
        check("the creator's own folder still comes first", source == "your music folder" and not touched, source)

        # the job: online had a track, but too short for this edit
        ov.OpenverseSource.list = lambda self: [fake_track("/online/short.mp3", 100.0, 30.0)]
        picked = []
        bed.pick = lambda fp, pool, need, look=None: ({"track": pool[0]} if pool[0].duration > need else None)
        bed.ops = lambda board, cat, mx, talking: ([{"op": "set_music", "track": mx["track"].id}], {"shots": 0})
        bed.fingerprint = lambda board, cat, pace: {"pace": "balanced", "hook_s": 2.0}
        bed.say = lambda mx, report, source, talking: source
        import threading
        done = threading.Event()
        job = bed.start({}, None, "balanced", None, 90.0, set(), lambda j: (picked.append(j), done.set()))
        done.wait(10)
        check("nothing online fits: the pack's song lands instead",
              job.stage == "done" and job.source == bed.PACK and job.result["music"]["track"].path == "/pack/b.m4a",
              f"{job.stage} {job.source} {job.why}")
    finally:
        ov.OpenverseSource.list, sp.PackSource.list = real_list, real_pack

    print("a failed search is not cached")
    calls = []

    def offline(params, timeout=20.0):
        calls.append(params["q"])
        raise OSError("certificate verify failed")
    real_get = ov._get
    try:
        ov._get = offline
        check("offline: nothing found", ov.search("sunny", pages=2) == [])
        cache = list((ov.cache_dir() / "search").glob("*sunny*"))
        check("...and nothing written to the cache", cache == [], str(cache))
        ov._get = lambda params, timeout=20.0: {"results": [{"id": "x1", "license": "cc0", "duration": 90000,
                                                             "title": "Sunny", "url": "u"}]}
        rows = ov.search("sunny")
        check("back online: the search is asked again and answers", [r["id"] for r in rows] == ["x1"])
        cache = list((ov.cache_dir() / "search").glob("*sunny*"))
        check("...and the answer is cached", len(cache) == 1 and json.loads(cache[0].read_text())[0]["id"] == "x1")
        ov._get = offline
        check("offline again: the last answer is kept", [r["id"] for r in ov.search("sunny")] == ["x1"])
        f = cache[0]
        os.utime(f, (0, 0))   # older than the week
        check("...even when it's old", [r["id"] for r in ov.search("sunny")] == ["x1"])
        check("...and still not overwritten", json.loads(f.read_text())[0]["id"] == "x1")
    finally:
        ov._get = real_get

    print()
    print("all checks passed" if not failures else f"{len(failures)} failed: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
