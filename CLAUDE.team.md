# VibeCut — how we work (read first)

This file is for Claude Code running on sarah's Mac (VS Code) or in the
cloud. It carries how the team works, the safety rules and where things
stand. `CLAUDE.md` carries the product's design notes; when the two
disagree about *how to work*, this file wins. When either disagrees with
what sarah says in the session, she wins.

## What VibeCut is

A tool that turns a phone full of footage into a finished video.

**Who it's for** (sarah's words, use them in any copy): people who don't
have time to edit, have a bunch of footage on their phone, and want an
aesthetic video they'd want to share and rewatch. Not "vloggers", not
agencies. (`CLAUDE.md` still says "a vlogger who films 100 clips"; this
wording wins in anything user-facing.)

**The promise:** "no amateur tells", never "beautiful". The machine handles
craft (exposure, loudness, cut grammar, consistency); taste stays with the
creator and is learnt from what she does.

Team: **sarah** (`sarahaiii`, owner, decides) and **barbie** (`bbbarbie`,
teammate, pushes and merges directly). Course project for Columbia COMS
E6998 "Build an Agent Startup" (Fall 2026). Repo:
https://github.com/vibecut-app/VibeCut — **public** (old `bbbarbie/VibeCut`
links redirect).

## How sarah wants Claude to work

- **As simple as possible.** Fewer steps and buttons; infer from the
  footage instead of asking; sliders, not menus; copy CapCut / iMovie
  conventions whole rather than inventing new ones. Quality over cost.
- **A question is only a question.** "What is this?" / "why does X
  happen?" gets an answer and nothing changes. If a change seems worth it,
  mention it in one line and wait. (Once a renamed label became a PR she
  never asked for, and it was reverted.)
- **A bug report is a request for the fix.**
- **A direction is not a go.** A design idea without "build" gets an
  opinion plus a "Build it / Not yet" offer. Start a new area or a new
  branch only after an explicit "build X" / "lets build". A bare number in
  answer to a numbered idea list = build that one idea.
- **Her shorthand:**
  - "push" = push to the open PR branch
  - "merge" = merge the drafts most recently offered (needs a clear
    "merge"; short merge titles in her plain style)
  - "pull" = update the Mac to latest main, rebuild, restart 8766
  - "open" = same, then open the browser
  - "show" = put the latest draft on the Mac
  - "run" = make 8766 run the current version
  - "fix" = yes to the latest offered fix
  - "terminate" = stop whatever is running on the Mac
- **Always put a draft on the Mac** after pushing it, so she can try it.
- **Results in plain readable sentences.** She often reads on her phone:
  no walls of code, no attached .md reports, no jargon.
- **Never invent quotes** from testers or users. Leave honest
  `[fill in]` brackets instead.

## Branches, commits and barbie

- **Few branches.** One branch per area (captions, main UI / editing
  tools / home page, AI story editing, taste model, launch). Small tweaks go
  on the branch that owns the area. After a merge, restart that branch from
  main.
- **Coordinate with barbie.** Before starting, `git fetch` and look at what
  she pushed. Bring branches up to date with main. **Never build on her
  unmerged work.**
- **Conflicts: keep both sides.** A draft clashing with barbie's work is
  fine as long as what she built and the taste model are preserved.
- **Commit author:** `sarahaiii <84511773+sarahaiii@users.noreply.github.com>`
  with the trailer `Co-Authored-By: Claude <noreply@anthropic.com>`. In a
  fresh clone set it at repo level (`git config user.name` / `user.email`).
  On her Mac her own global git identity is already right; leave it.
- **Short commit messages**, in plain words about what changed for the
  user.
- **Never rewrite main.** No force-push to main, no history rewrites, no
  rebasing merged work.
- PRs: draft PRs against `main`, review requested from `sarahaiii`.

## Security and money (non-negotiable)

- **The repo is public.** Nothing key-like goes in any file, commit, PR,
  comment, log or test fixture. Not even a fake-looking real key.
- **The course OpenAI key** (`OPENAI_API_KEY`, $25 for the whole term,
  coursework only) lives **only** in `web/.env` on sarah's Mac. Never
  print it, cat `web/.env`, echo it, paste it, commit it or post it. Never
  write keys into files yourself; she does that. `.env` is gitignored —
  keep it that way.
- **Never spend API credit without her yes.** Before anything that calls a
  paid model (OpenAI or Claude: AI Edit chat, the story editor, the AI
  check, taste-model AI descriptions, restarting the server with a key
  loaded and the AI switch on), tell her the expected cost in dollars and
  wait for an explicit yes. A key being present is not a yes.
- Same for anything rented, any sign-up, and opening any public link or
  hosting. She creates hosting accounts herself.
- Public / hosted copies run with AI off.
- **Ask first on her Mac before:** installing anything (pip / npm / brew),
  deleting projects or files, changing git remotes, downloading videos.

## Design and product taste

- **Bright UI.** The heading serif for buttons and hints; the timeline uses
  the system font with tabular numbers. One design system
  (`web/frontend/src/ui.tsx`).
- **No tiny grey hint text**, and no control that only exists as a hidden
  gesture. Every action has something visible to click.
- The **preview is the biggest thing** on the edit screen; every border
  drags.
- **No identical shots** in an edit. Left-out thumbnails are dark red.
- Say "Captions", never "words on screen" / "overlays" in the UI. No jargon.
- **Captions, default look:** quiet vlog style — small lowercase, soft
  shadow, low left. Chapter titles are thin, white, widely spaced capitals
  that shrink to fit on one line, with a small italic line under. Captions
  must contrast with what's behind them.
- **Caption words:** a thought or what we're doing ("7:40 am · walk to
  class"), 3–5 casual first-person words, at most one emoji, never an AI
  description of the picture. At most 2 captions per chapter. Her own past
  lines come first (caption memory); no model writes words by default.
- **Vlog taste:** show the *day*, not her face; varied places; shot length
  follows the shot's job; end on a sign-off; music around -15 LUFS. No title
  in the first second.
- **Fonts:** openly licensed (OFL / Apache) and credited in `NOTICE`, or
  already on the creator's machine. Never a proprietary app font.
- **No generative video.** The viewer only ever sees frames the creator
  filmed.

## The vlog taste model (the essence of the algorithm)

sarah's direction: a learnable model that iterates and improves, reading a
cut the way an industry pro editor would — not a set of numbers to match.

- `taste/`: a scorer trained to tell pros' real edits from damaged copies
  (shuffled order, evened rhythm, flashes, moved captions). Make builds a
  few one-change versions and the model picks; the rules stay as safety
  limits. Her picks on the "Which do you like better?" cards refit her
  personal layer.
- Scores on unseen creators: long vlogs ~92%, shorts ~87%. Cold openings
  and endings are still mostly blind.
- **Data rules:** vlogs only (no GRWM, hauls, Q&A, podcasts, reviews,
  storytime). US-centric, varied genre. Style only from pro creators, never
  from her own videos or VibeCut's output. **The repo holds text and numbers
  only — never creators' videos, stills or their words** (no OCR'd caption
  lines in commits).
- New creators help far more than more videos from the same ones.
  Blind spots need new readings in code, not more data. Test every new
  reading on milder damage before believing a gain.
- The collector only runs on her Mac (needs YouTube / TikTok access):
  `caffeinate -i .venv/bin/python -m taste.collect --describe --train`
  (resumable; `--ai --cap N` spends course credit — ask first).

## Her Mac

- Repo: `/Users/sarahai/Desktop/VibeCut/repo`, Python from the repo's
  `.venv` (`.venv/bin/python`), yt-dlp installed.
- App: http://localhost:8766 (`VIBECUT_PORT=8766 .venv/bin/python -m
  web.backend`; default port is 8765). Browser: Chrome.
- Frontend: `cd web/frontend && npm run build` (if `tsc` fails on stray
  Finder duplicates, `npx --no-install vite build`).
- Exports land in `~/Movies/VibeCut`.
- Finder / iCloud duplicate files ending in " 2" / " 3" are harmless
  leftovers; don't commit them (a copy of a `.tsx` can break `tsc`).
- Landing page is `#/welcome`, linked only from the profile page ("About
  VibeCut"); home (`#/`) stays bare, in the landing page's dark look.

## Tests (hand-run, no CI)

- Python: each file runs on its own —
  `.venv/bin/python tests/test_make.py` (pytest also works where
  installed). Some need macOS helpers or `httpx`.
- Frontend: `cd web/frontend && npm test` (node's test runner).
- Run the tests touching what you changed before every push. Every new
  grammar rule ships with a discrimination test (see `CLAUDE.md`).
- `VIBECUT_BED=0` keeps tests offline.

## Code map

- `cutgrammar/` — the measuring engine (shots, motion, joins, music,
  style, rough cut). numpy only; pixels decoded once by `media.load()`.
- `polish/` — assist on an already-finished video (captions, effects).
- `taste/` — the taste model and its text-only dataset.
- `web/backend/` — FastAPI app (~90 modules): `make.py` (the one
  pipeline), `board.py` (turn log of ops; chat only emits ops), `export.py`
  (the only re-encode), `overlays.py`, `vlog.py`, `story.py` / `oai.py`
  (AI, key + switch only), plus four Swift helpers for Apple's on-device
  Vision, sound, speech and places (`vision/`, `sound/`, `speech/`,
  `place/`). One open project at a time, no user accounts yet.
- `web/frontend/` — Vite + React + TypeScript (`App.tsx`, `Inspector.tsx`,
  `overlayDraw.ts` draws captions for preview *and* export).
- `supabase/` — optional preferences mirror. `design/` — specs, research,
  eval screenshots.

## Where things stand (2026-11-08)

**Main** (`6511e85`, 2026-10-26): barbie's #54 / #57 (check my cut,
captions off faces, other-frame version, crop follows people, share and
YouTube posting, post copy and cover, caption memory) on top of #52
(landing page, vlog cutting on music phrases), plus sarah's merged drafts
#45 AI story editing, #47 main UI tools (clip tools, My resources, profile
after export, graphic animations), #49 captions.

**Open drafts:**
- #55 — Make cuts tall / wide videos like a vlog again; Learn a vibe no
  longer crashes on a beatless reel.
- #58 — Voiceover: record over the timeline, own Voice strip, music ducks.
- #60 — Colour adjust (brightness / contrast / saturation) and Stabilise.
- #61 — Home: "Your recent videos" with Open and Share.
- #59 — "Vlogs cut to the house style, songs to swap, subtitles on the
  Captions switch" (newest, 2026-11-08; check who opened it before
  touching it).
- #23 — opening + ending switch (never landed; Make does it already).
- #48 — Mac app — **paused**, don't work on it.

**Not built yet** (each needs her "build X"): noise reduction, square 1:1,
blurred background, picture-in-picture, green screen, keyframes, stickers,
text-to-speech, photos in a video. Public website / hosting: no go yet.
