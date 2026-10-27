# VibeCut — working notes for Claude

Read this before touching anything. It carries the decisions that are
already made, so they don't get relitigated every session.

## What this is

A tool that turns fragmented footage into something worth watching.
Target user: a vlogger who films 100 clips on a trip and cannot face
editing them. Not agencies, not ad teams, not performance marketers.

## The bet

Whether a vlog is *beautiful* is not computable. But most of what makes
amateur footage read as amateur is craft nobody taught the person holding
the camera — and craft is measurable.

Rough split of what drives the impression:

| Share | What | Automatable |
| --- | --- | --- |
| 40% | Hard constraints: exposure jumps, loudness, subtitle over a face | yes |
| 30% | Editing grammar: J/L cuts, cut on motion, 180° rule, shot size | yes |
| 20% | Surface consistency: one LUT, one font, fixed subtitle position | yes |
| 10% | Taste: what to include, where the emotion goes | **no — left to the user** |

The promise to a user is therefore *not* "this will be beautiful." It is
**"this will have no amateur tells."** Don't let the copy drift past that.

## Status

- `cutgrammar/` — measurement. Built, tested, uncalibrated.
- `cutfix/` — acts on the measurements. **Not built. Do not start yet.**
- `storyline/` — proposes several edits from one shoot. Not built as a
  module; v1 axis enumeration (time / place / subject, no LLM) lives in
  `web/backend/storyboard.py`.
- `taste/` — the taste model (sarah, 2026-10-21: "a learnable model that
  iterates and improves", read the way a pro editor reads a cut): reference
  vlogs described shot by shot, a scorer trained on real edits against
  damaged copies, Make weighs a few one-change versions with it and keeps
  at most one change per part (opening / rhythm / order / ending;
  `web/backend/tastepick.py`). Trained 2026-10-21 on her Mac (24 long vlogs /
  8 creators: 90% real-vs-damaged on unseen creators; 28 shorts / 12
  creators: 85%; both past `MIN_LOCO`, so Make uses them). 2026-10-23 (her
  Build it): new readings for talk left running and swapped shots
  (`longest_hold`, `talk_longest`, `flow_seen`, `continuity`,
  `music_under_talk`); retrained here: 93% / 85%; cold openings and endings
  are still not caught (half the pros open on an ordinary shot). 2026-10-24:
  20 more creators, mostly American (50 long / 20 creators: 92%; 37 shorts /
  17: 87%; better on the creators it knew, see the README). **Which do you
  like better?** (sarah, 2026-10-21; `web/backend/prefer.py`,
  `PreferCards.tsx`, `/api/prefer`): under the made video up to 3 cards
  play two versions one change apart; a pick refits her layer
  (`taste/model.py` `PICK_STEP`) and, while the video is untouched since
  Make, lands as one undoable turn. A turn the app adds by itself after Make
  (a profile's captions or transition) isn't a change: register its text in
  `app.REDRESS` and the picked version gets it too, inside the pick's turn
  (#47's "From your profile" needs that one line when the two meet).
  `tests/test_prefer.py`. Every threshold
  a prior. See `taste/README.md`.
- `web/` — the app (FastAPI + Vite/React). Built at the user's explicit
  request despite the "no web UI" non-goal below; scope is deliberately one
  path: **Projects → Footage → (style questions) → Story → Export**, the rough trim automatic
  (Phase 1 baseline, 2026-09-28; audit, parity matrix against Vyra and the
  plan in `design/specs/phase1-baseline.md`). The stage shown is *derived*
  from project state (`web/frontend/src/stage.ts`), never set by hand.
  Projects persist on disk (`web/backend/projects.py`: clip ids, turn log,
  workflow, cut overrides, brief, exports) and survive restarts; the
  middleware saves after every mutating request. A new video starts from
  its clips on the home page (drop or choose, see the row, remove any,
  Create; `drop.handOff` carries them into the project), and asks for no
  name: it is "New video" until its clips are read, then named from the
  days they were filmed (`projects.auto_name`, "Sep 22" / "Sep 22–24"; sarah:
  just the day for now) until the creator renames it. The Footage page is
  two stacks, Kept / Left out, dealt as clips are read (`Footage.tsx`). Two levels inside Story:
  **Story** (parts and shots, no timecodes) and **Frames** (the precise
  timeline). Select, then act; no jargon in the UI. One design system
  (`web/frontend/src/ui.tsx`); the old Creative-tools page and its four
  "coming soon" cards are gone (see `web/feature-roadmap.md`). What the
  machine can't do (no key, not macOS, no yt-dlp) is stated where the action
  would be, never hidden. Home is as bare as it can be (sarah, 2026-10-06:
  "as simple as possible"): "Good morning / afternoon / evening, <profile first name>!", then
  "Start with your clips", "Drag clips / folder here", Add clips + Add folder (a
  browser picker can't take both; a phone version only needs Add clips).
  Footage has no preview panel: an opened stack is a vertical column on its own side (Kept left, Left out right), the other stack shrinks opposite as the drop target; a clicked clip plays in place with a "Move to …" button (no double-click). See `web/README.md`.
  **The edit screen** (sarah, 2026-10-16: "change the layout to this
  reference photo", same colours; `App.tsx` frames view, `Inspector.tsx`,
  `Shelf.tsx`, `PreviewBar.tsx`, `Split.tsx`): top bar = name ▾ (rename, back
  to Footage, Other stories, Reference, Remix, Start over…), undo / redo,
  "Draft saved", Export. Left: a rail (Media · Text · Music · AI Edit, called
  History while the AI is off) opening one panel; Media is the clip grid with
  All / Kept / Left out tabs. Middle: the preview on black with play, time,
  a scrub bar, the frame (cycles short / vlog / wide) and full screen. Right:
  an inspector with Edit (trim bar, speed, rotate, mirror, fit / fill; with
  nothing clicked, Length / Tempo / Smoother cuts), Captions (style +
  animation for every caption), Effects (transition at the clicked cut, else
  every cut), Audio (shot / strip sound, else music), Adjust (the look).
  Bottom: the timeline with Video / Captions / Audio lanes (music drawn as a
  strip). Clicking something opens its tab. Every border drags (sizes saved
  in this browser). The old bottom tool bar (ShotBar) is gone.
- **Landing page** (`web/frontend/src/components/Landing.tsx`, route
  `#/welcome`; 2026-10-21, the user: "like those websites selling this
  product"; tightened 2026-10-22). Hero (two-line pitch + a before/after:
  the shoot as a pile of clips with its tells marked, then the edit; flips
  by itself until clicked), the 40/30/20/10 promise, three steps (with
  "or paste a reel you love" under them), what it fixes, pricing (early
  access free; a Creator plan named but unpriced), FAQ (which carries the
  privacy answers), closing. Restyled 2026-10-23 (the user: "the vibe of
  current YC companies' landing pages", then "too cartoon-ish, make it more
  aesthetic, cool and sharp"): on the app's own dark palette (`.on-video`,
  the one the player uses over footage), the app's own faces (Garamond
  headlines and wordmark, system sans labels; the user, 2026-10-23: "the
  font does not match the app"; Nunito only inside drawn captions) with one
  italic turn per headline, numbered section labels, hairline grids instead
  of cards, 4–10 px corners, film grain, one pale-blue accent, no emoji or
  pastels; the carousel's scenes are light (dusk, coast, night street), not
  drawings. A marquee of the tells, and a plain mark (`Mark`: one frame cut in two on a diagonal,
  also `public/favicon.svg`; the clapperboard mascot went, the user:
  "too cartoonish"); motion is in the file's
  own CSS and off under reduced motion. No logos, quotes or backers we don't
  have. Cut down 2026-10-23 (the user: "less words, more straight to the
  point, and a carousel of animations that we can do"): every section is a
  headline and a line; "What it can do" (`Moves`) is a carousel of 29 looping
  9:16 cards, filterable by Captions / Transitions / Effects / On the beat,
  each a move the editor has under its menu name, drawn as CSS over made-up
  scenes (no faces); it advances by itself until touched. Both
  sides of the before/after are drawn in CSS because every real screenshot
  shows the creator's face. The app's home (`#/`) stays bare; the page is
  linked only from the profile page ("About VibeCut"). Copy keeps to "no amateur tells", never "beautiful".
- Chat editing rule: a turn applies operations to the working storyboard
  (`web/backend/board.py`), never regenerates it. The LLM only emits ops;
  the diff is computed, not reported by the model. Keep it that way.
- **Chat on pause** (`web/backend/moment.py`, `/api/moment`, `/api/moment/chat`,
  `PauseChat.tsx`; sarah, 2026-10-05: pausing means something should change).
  While the edit is paused a box under the preview is pinned to that moment
  ("Shot 12 · 0:34 · IMG_4492"): the model gets the shot, its clip time and
  kept range, its neighbours, the words on screen and the paused index frame
  (small JPEG) with the message, through the same `llm.interpret`; its ops
  are only previewed (diff computed on a copy of the log) until Apply sends
  them to `/api/ops` as one undoable turn. `/api/moment` never calls the model
  and returns a per-message cost estimate (Opus 5 list price, output 600–2500
  tokens, priors; since 2026-10-18 priced for whoever answers, see AI Edit on
  the course key, and shown on Send). No AI: the box says so, offers the
  switch and sends nothing. `tests/test_moment.py` (mocked model).

- `cutgrammar/music.py` — energy-shape matching of the user's own tracks to
  the storyboard. Built, synthetic-tested; **not yet judged on a real music
  library** (none on the dev machine). Beat snapping is the next task.

- Timeline precision (`web/backend/timeline.py`, `web/frontend/src/snap.ts`):
  built and tested. Known: scrub-snapping at fit zoom on long edits pulls
  too far (21% of scrubs >1 s); motion targets are ±0.5 s (keyframe index).

- Rough cut (`cutgrammar/reject.py`, `trim.py`, `signals.py`; gate in
  `web/backend/workflow.py`, design adapted from cut-motion — see NOTICE).
  Discrimination-tested on synthetic fixtures; thresholds are guesses. The
  gate's page is gone (sarah, 2026-10-07: "skip it"): once the style questions
  are answered the trim is approved as it stands, and every trim stays
  changeable in Frames by dragging a shot's ends out to the whole shot as
  filmed (`timeline.build` gives `src_min`/`src_max`); left-out clips are
  overruled on Footage's stacks. `speech_mask` is level-based, so
  music read as talking and those clips were barely trimmed (3 real clips:
  7:16 → 7:12). **Voice reading** (`web/backend/sound.py`,
  `sound/vibesound.swift`, `signals.with_voice`): Apple's on-device sound
  classifier (macOS; audio track only, nothing leaves) gives per-second
  voice / music / singing / laughter, cached as `sound.json`; speech counts
  only where a voice is heard (VOICE_LO 0.15 → VOICE_HI 0.45, priors).
  Filled once on project open for older clips. Elsewhere the level mask
  stays. Silero was the brief's default but needs onnxruntime (not numpy-
  only, and pip installs are blocked on her Mac). `tests/test_voice.py`.
  At the gate the kept range can be dragged by its ends (`set` override,
  min 1 s, undone by `auto`; `tests/test_cut_set.py`); hovering the bar shows
  the frame at that moment (index sample first, then the clip seeked).
  **Best moment** (`web/backend/moments.py`, `trim.candidates`): the trim
  offers up to 3 different windows per shot (share ≤ ⅓ of their seconds,
  score within RUNNER_UP 0.1 of the best); with a key, Claude sees 3 index
  frames from each and picks one (frames leave the Mac; nothing else).
  Cached per shot in the clip dir's `moments.json`; no key, an error or a
  bad answer leaves the rules' first pick. `VIBECUT_MOMENTS=0` turns it off.
  `tests/test_moments.py`. Not yet judged against her picks on real footage.

- Words on screen + export (`web/backend/overlays.py`, `export.py`,
  `web/frontend/src/overlayDraw.ts`; ideas from Overlay Studio — design
  only, its licence forbids including its code, see NOTICE). Overlays are
  ops in the turn log, anchored to edit / end / part / shot; one style per
  video; suggestions only use words the edit already knows; checks report,
  never change. One Canvas function draws both preview and export frames;
  ffmpeg here has no drawtext, so don't move text rendering server-side.
  Export is the only place pixels are re-encoded. Checks' thresholds
  (reading speed etc.) are guesses, uncalibrated.

- Talking-head mode (`web/backend/talk.py`, `speech.py`, `TalkCut.tsx`):
  rules + optional model review; tested on synthetic transcripts and through
  the real recogniser (`tests/test_talk_speech.py`, macOS TTS). Thresholds
  (MIN_PAUSE 0.45 s, breath 0.27 s, retake similarity 0.6) are guesses. Not
  yet tried on a real creator's talking-head footage or with the live model.

- **Borrow a feeling** (`cutgrammar/style.py`, `grade.py`; `web/backend/
  reference.py`, `restyle.py`; `BorrowStyle.tsx`; idea from Hypit, analysis
  only — see NOTICE). A reference video (file, or link via yt-dlp) is read
  with `load()` and reduced to measurements: pace + arc, transitions, beat
  alignment, look, letterbox, music feel. Applied as one `apply_style` op
  (never from chat): pace/beat retime shots; LUT, transitions and bars are
  rendered only in `export.py` (dissolves use source handles so cuts stay
  on their frame, else fall back to cuts and say so). Tests:
  `tests/test_style.py` (discrimination; optional real footage via
  `VIBECUT_REAL_CLIPS`), `tests/test_restyle.py` (board + full render round
  trip). Dissolve thresholds were set on real handheld footage (a few
  dozen joins); a soft transition only counts as a habit above 15% of joins.
  Beat alignment needs a steady tempo, because hard audio cuts make their own onsets.
  Everything else is a guess. The reference's frames and audio never reach an export.

- **Remix** (`web/backend/remix.py`, `select.py`; `cutgrammar/openverse.py`;
  CLI: `python -m web.backend.remix --ref <link|file>… --footage <folder>`;
  since 2026-10-11 (plan step 4) also the **front door**: the home page's
  start box has "Make it like a reel you love" under the picked clips —
  links ride with the clips (`drop.handOffRefs`), the project starts a
  Remix the moment the clips are read (`Remix.tsx` `autoStart`), and when
  it lands `api_remix_start.on_done` passes the gate in the creator's name
  and writes a brief from the fingerprint (frame, length), so the stage
  reads story and the two-pick popup stays shut. **Judged picks**
  (`select.judge`, `llm.rank_shots`): with a key, Claude sees one index
  frame per candidate — the rules' picks plus `RUNNERS_UP` per session —
  and names which to keep; the rules still set the pool, quota and
  windows; no key / error → the rules' picks, and the plan's notes say
  when it was judged. `VIBECUT_REMIX_JUDGE=0` turns it off. Not tried
  against the live model. `select.time_windows` no longer indexes an
  empty target list (tiny shoots). `tests/test_frontdoor.py`.) Reference reels + the shoot → one finished short, server-side,
  no browser. The references' styles (Borrow a feeling) are merged into a
  fingerprint (median shot length + arc, hook hold, tempo range, energy arc,
  length); `select.py` picks that many moments — distinctive labels (IDF
  across the shoot), face-in-the-world, subject, steadiness; sqrt-of-footage
  quota per session; look-alikes (cosine ≥ 0.78 in a session) collapse;
  windows cut in just before the busiest second. Music comes from Openverse
  (Jamendo/Freesound, CC0/BY/BY-SA only, credit line written next to the
  export); the drop is found from the waveform and placed at the end of the
  hook; every shot is a whole number of beats. Captions (title, tag, clock +
  a phrase from a label) are drawn by an AppKit helper into export's PNG
  schedule; `export.py` gained `mix` (in-point, gain, original gain, ducks,
  sfx, loudnorm) and a per-item `punch` (zoompan). Tested on synthetic
  fixtures (`tests/test_select.py`, `test_remix.py`, `test_openverse.py`);
  judged on one real shoot (42 clips, 3 references). Every weight is a
  guess; the selector has no model behind it (no key on this Mac).

- **A reel's ideas, not only its rhythm** (2026-10-18, the user's vision
  restated: "analyse the aesthetics, get a similar version"). `style.learn`
  gained three traits: **words** (`text_style`: share of time with text,
  first words at, band bottom / middle / top, hold, cards, caps, size; from
  `vibevision --text` = Vision `RecognizeTextRequest` at `.fast`, spec P16,
  over the source's frames at 2 fps 540p, `reference.text_events`; frames
  deleted after; `pending: ["vision"]` elsewhere), **opening** (first cut,
  motion in the first 2 s vs the rest) and **ending** (last shot held,
  fade out, motion in the last 2 s). `VERSION` 2. `remix.fingerprint`
  carries `text` and `last_s`; `make.ops` puts captions where the reel's
  words were (`overlay_style captions`, `template: bold` for caps), holds
  them as long (`remix.captions(hold_s=…)`), gives no title when the reel's
  words start late, no words at all for a wordless reel, and `end_beats`
  holds the ending as many beats as the reel's last shot (1–4). Verified
  OCR end to end on this Mac (`tests/test_ideas.py`); references learnt
  before this have no `words` and fall back to the priors.
- **Into the drop** (`make.ramp_hook`, 2026-10-18; built from `split`,
  `set_shot speed` and `set_transition`, nothing new on the board): for a
  short with a beat, the hook grows by one beat of footage and its last
  sequence beat runs at `RAMP_SPEED` 2× (two beats of footage in one, so the
  drop doesn't move); Hype and Playful (`FLASH_LOOKS`) get a `FLASH_S` 0.2 s
  white flash on that cut. The split's second key is `{id}~{ms}` as
  `board._split` names it. A shot may now appear twice on a made board only
  as the two touching halves of that split. Preview plays the ramp by rate
  and the flash by veil; export by atempo and fade. Priors.
- **Motion on the beat and a deliberate ending** (`make.py`, 2026-10-18):
  `punch` is a shot fix like speed or mirror (`board.SHOT_FX`, ±`PUNCH_MAX`
  0.25; `timeline.layout` carries it, `export._shot` renders it as zoompan,
  `transport.dress` plays it as a CSS `scale` animation over the shot —
  preview and export agree). `make.punches`: the hook pushes in
  (`PUSH_HOOK` 0.08), the first body shot after the drop hits (`PUSH_HIT`
  0.14), every bar's first shot pushes ±`PUSH_BAR` 0.05 alternating; no
  beat known → hook and hit only. `make.end_strong`: the last stop ends on
  its strongest moment (only that stop reordered); `hold_ending`: ≥
  `END_BEATS` 2 beats. The hook is lifted out of its stop, not copied (a
  Remix played it twice). After Make the brief's pace / seconds / tempo
  describe the cut (`make.pace_of`), so the Frames chips tell the truth.
  Cuts sit on the half-beat grid (filler) with the hook and heroes on whole
  beats — `remix.quantise`'s rule, now pinned in `test_make`. All priors.
- **Habits: the second video learns from the first** (`web/backend/
  habits.py`, 2026-10-18; the user's ask "do everything now"). At export,
  `habits.record` keeps the video's *signals* on its record (`events`
  kind "signals": shots removed / kept / held by hand with their top
  labels and hour, music switched off by hand, lines retyped; the
  machine's own turns don't count). At Make, `habits.derive(pj.list_all())`
  turns the same thing on ≥ `MIN_PROJECTS` 2 videos into a habit (`avoid:`
  / `prefer:` a label at ±`LABEL_W` 0.2, `music_off`), kept in
  `$VIBECUT_CACHE/habits.json` with evidence, use count and an off switch
  that survives re-deriving; a label both removed and kept is no habit.
  Habits only *bias*: `select.hero_score(bias=)` adds weight × confidence
  per label (the "why" part `habit`), `music_default` sets the switch,
  `phrases` (retyped lines, also `remember_phrase` from `edit_overlay`)
  ride on the writer's prompt. The Make reply ends "Kept more food and
  fewer whiteboard shots, as you did last time."; `session.habits` lists
  what acted; the Watch screen's "Undo that" = `POST /api/habits/{id}
  {off, remake}` (switch off, undo the Make turn, make again). Used
  `SUGGEST_AFTER` 3 times without an undo → offered once as a rule
  (`_prefs_public`, id `habit:…`). Profile page: "What VibeCut has learned
  about you" with switches (`/api/habits`). Local only (not mirrored yet).
  `tests/test_habits.py`.
- **Lines from place and time** (`make.plain_lines`, `time_of_day`,
  2026-10-18): without a key a stop's line is "Morningside Heights,
  morning" from the clip's GPS (places.py) and hour — never a clock stamp
  alone, and a stop with nothing to say says nothing
  (`remix.captions(clock=False)`); with a key the writer gets the place as
  a label and the creator's own retyped lines (`phrasing`), and any empty
  answer falls back to the plain line.
  **Rewritten 2026-10-25** (the user: "no repeated place names, write lines
  a vlogger would actually post"; a day on one campus read "Columbia
  University, morning … , night" seven times, two identical): the place is
  named once, as the overlay's `sub` above the line, where the day arrives
  there (`make.arrivals`, `PLACE_SEP` "\n" inside a line); the line says
  what the picture shows (`daylog.phrases`, most specific first, not said
  before), else how the day moved on (`HOUR_LINES`: "good morning",
  "night time"); never a line twice, never the title again, and an empty
  line stays empty (`remix.captions` no longer fills it from its own
  table). On the face-free half of her shoot: "class time" (under Columbia
  University), "lunch", "study time", "heading out", "night time",
  "walking". `tests/test_plain_lines.py`. Priors.
  **Her lines first** (`web/backend/captionmem.py`, 2026-10-25; the user:
  "i dont want the caption to be ai generated … i fine tune it to make it
  something i want"; research in `reports/Vlog formats captions and
  graphics.md`: no tool learns a creator's caption words). Caption memory:
  `/api/ops` records each hand retype / deletion / line written over a
  placeholder of a caption, stop line or title with its moment (the stop's
  first shots' labels, hour, weekday, place, position; `app._caption_ctx`),
  in `$VIBECUT_CACHE/caption-memory.json`, never mirrored. Moves and
  restyles record nothing. `make.plain_lines` offers, per stop, first her
  own past line whose moment matches (`Memory.suggest`: labels 0.6, time of
  day 0.2, place 0.15, position 0.05, ≥ `MIN_MATCH` 0.45; a line that named
  the place / weekday / time of day is a template, "lunch at {place}";
  never twice in a video, of equals the one used least; titles only for
  titles), else the table line in her style (`Memory.shape`: her case, her
  ending, nothing for the lines she deletes), else nothing. Rules need
  `MIN_RULE` 3 edits at `RULE_SHARE` 0.7 (titles don't count toward case).
  Profile page section 04 "Your caption voice": the rules with switches,
  "My lines" to add / remove (`/api/captions/voice`, `/lines`, `/rules/{id}`),
  and the edit-distance trend from what was offered to what she kept (the
  PRELUDE measure). No model writes a word. Also fixed that day:
  `remix.captions` skipped a silent stop without advancing its clock, so
  every later line landed a stop early. `tests/test_caption_memory.py`.
  Walked through on her face-free clips: three retypes on one video came
  back at the same stops on the next. Priors.
- **Posting** (2026-10-18): `POST /api/export/{jid}/photos` imports the
  file into Photos by AppleScript (Mac only, says so elsewhere); the
  export dialog has Save to Photos and "Copy caption + credit" (the title
  line plus the track's licence credit, now on `session.music.credit`);
  the no-music export is the dialog's Music switch; "Would you post this?"
  stays the number.
  **Share it** (2026-10-23, the user: "after the video is created how to
  move it to like tiktok youtube … publish share it save it";
  `web/backend/share.py`, `SharePanel.tsx`): after an export the dialog
  shows Download, Save to Photos, Show in Finder (Mac) and Share… (the
  system sheet, AirDrop / Messages / Mail, through `navigator.share` with
  the file, fetched ahead so the click opens it; where the browser can't
  share files it says so and the button isn't there), then one link each
  for TikTok, YouTube (Shorts when vertical and ≤ 3 min, else a normal
  upload) and Instagram: the click copies the caption + credit (the credit
  only when the file has the music) and opens that platform's own upload
  page in a new tab, and the line under it says which file to pick from
  which folder. Each platform is checked against the file first
  (`GET /api/export/{jid}/share`: frame and length, e.g. "Too long for a
  Short", "Wide — TikTok shows it small with bars"), said in amber, never
  hidden. Limits are the platforms' own numbers as of 2026-10, in one
  table. Every way out is a `Project.events` entry (kind `share`, `how`,
  `export`; browser-side ones through `POST /api/export/{jid}/shared`,
  Photos and Finder by their own endpoints) and `launchlog` counts
  projects shared and each way next to "would you post this?". **VibeCut
  never posts by itself**: posting through TikTok's and Instagram's APIs
  (OAuth, app review, audits) is written up in `web/feature-roadmap.md` and
  waits for the user's go-ahead. `tests/test_share.py`.
  **Posting to YouTube** (the user, 2026-10-23: "start direct posting with
  YouTube … with a confirm before every post"; `web/backend/youtube.py`,
  `YouTubePost.tsx`): the creator's own Google Cloud "Desktop app" OAuth
  client (`YOUTUBE_CLIENT_ID` in web/.env; setup in web/README.md), else
  the Share box says it isn't set up. Sign-in = Google's page + a one-time
  listener on 127.0.0.1 (random port, closed after the answer), PKCE + state;
  scopes `youtube.upload` + `youtube.readonly` (to name the channel on the
  confirm screen); refresh token in the Keychain (`security`), channel in
  `$VIBECUT_CACHE/youtube.json`; disconnect revokes at Google. **Every post
  is confirmed**: `POST /api/export/{jid}/youtube/prepare` returns the
  channel, title, description (the music credit), whether it'll be a Short
  and a single-use code; `POST /api/export/{jid}/youtube` refuses without
  that code for that export, or without a made-for-kids answer; privacy
  defaults to Only me. Resumable upload over urllib in 8 MiB chunks, a
  dropped chunk asks where it stands and carries on, Stop between chunks
  leaves nothing; the reply reports the privacy YouTube actually set.
  Landed posts are a `share` event (`how: youtube_post`, video id) and
  `posted` on the export; launchlog counts `posted`. Never retried, never
  posted again by itself. `tests/test_youtube.py` against a stand-in Google
  (`tests/fake_google.py`); walked through in the app against the stand-in,
  not yet against real Google (needs the creator's client id).
  **Words and a cover to post with** (2026-10-24, the user: "think about
  what other feature is missing, keep building"; the Share box said "No
  caption to copy" on most edits). `web/backend/postcopy.py`: a draft from
  the edit alone, never the model — the title on screen, else where and
  when it was filmed ("A Saturday in Lisbon, morning to night", "3 days in
  Lisbon", from the edit's clips' times and the place names places.py has
  cached, no new lookups); ≤ `MAX_TAGS` 5 hashtags (#dayinmylife /
  #weekendvlog / #travel, #vlog, city, a named place, #shorts for a Short);
  YouTube chapters by YouTube's rules (first 0:00, ≥ 3, each ≥ 10 s; chapter
  titles on screen first, else stops by place; none for a Short). The Share
  box's "Words to post with it" is that draft, the creator's to change; the
  music credit is added to whatever they write. YouTube's confirm screen
  starts from its title / description. `web/backend/covers.py`: the cover
  is a frame of the export itself (captions and look included, never made
  up): up to 6 stills, the hook then the longest-held shots, picked in the
  Share box, saved full size as "<name> cover.jpg" beside the video (≤ 2 MB)
  and on the export's record; YouTube gets it with the post through
  `thumbnails.set` (`youtube.set_thumbnail`, not for a Short; a refusal,
  e.g. an unverified channel, is said and the post stands). The post sends
  only the cover the confirm screen showed (`cover_t`). Tests:
  `tests/test_postcopy.py`, additions in `test_share.py`, `test_youtube.py`.
  Tags and the cover rule are priors.
  **The other frame, one click** (2026-10-24, the user: "when an export is
  wide, add a one-click 'make a vertical version too' … and the other way
  round for YouTube"): the Share box offers the same edit in the other
  frame (`share.other_version`: wide → vertical "for TikTok, Reels and
  Shorts" as far as the length allows; vertical → wide "for YouTube"; not
  for a version or a square). `POST /api/export {frame: tall | wide}`
  exports it without touching the project's own frame; captions are drawn
  again for the new size by the same browser pipeline; `export.create(crop=
  True)` → `cover_mismatched`: shots filmed the other way up (after their
  quarter turns) fill the frame instead of bars, and the export says how
  many. Saved as "<name> · vertical …" / "· wide", `alt` on the job and the
  export record; the dialog lists what it made just now and asks "would you
  post this?" only of the original. `test_share.py` (bars vs filled, by
  brightness). **The crop follows the people** (2026-10-24, the user:
  "follow the people in each shot instead of always keeping the middle";
  `web/backend/aim.py`, `export.aim_refits`): one window per shot (a
  window chasing every frame reads as a robot camera), from Vision's face
  boxes on the index samples inside the seconds the shot uses (cached as
  `faceboxes.json`, written at index time from now on, read once for older
  clips): people who fit in the window together are kept together, else
  the largest face; the median across samples; centred across, `HEAD_AT`
  0.4 down (headroom); stops at the picture's edge; the shot's mirror and
  quarter turns applied to the point. Faces on under `MIN_SEEN` 0.3 of its
  samples, no Vision (not a Mac) or a shot filled by hand (the preview
  shows it centred) → the middle, and the note says how many were kept on
  people. Only the other-frame version aims; preview has no crop to match.
  On six real vertical clips cut wide, every aimed crop kept the face where
  the middle showed a neck. Numbers are priors. `tests/test_aim.py`
  (a person left / right of centre centred, the middle crop as control,
  headroom, turned shots, the note).
  **Captions off faces** (2026-10-24, the user: "move any caption that
  would sit over a face, using the same face boxes as the crop"): a
  version's captions are laid out again for its size, so they could land
  on the person the crop just centred. `export.face_areas` maps the same
  face boxes into the version's frame shot by shot (crop at its aim, or the
  picture between bars), `GET /api/export/{jid}/faces` (versions only: an
  export in the edit's own frame keeps the captions the preview showed),
  and the browser's `overlayDraw.faceShifts` slides each caption up or down
  (never sideways: the alignment is the look's) to the nearest place clear
  of every face on screen at any moment it's shown (`FACE_MARGIN` 0.02 of
  the short side), else the place that covers least, inside the safe area
  (the frame for words placed by hand); one shift for its whole time on
  screen, so words don't jump at a cut. The count rides on the start
  request (`moved`) into the export's notes. Priors. `tests/test_aim.py`
  (each face area against where the person is in the rendered file),
  `faceShifts.test.ts`; `design/eval/2026-10-24-captions-off-faces.png`
  (before / after, a stand-in face on the synthetic test shoot).
- **Watch, then Fine-tune** (2026-10-18, `App.tsx` `watching`): a made or
  remixed video opens as the video, full-size, with four chips under it —
  music (the bed switch), length (`LengthButton`), look (cycles the looks
  as one `set_look` turn), words (the captions switch) — plus Download
  (the export dialog) and one Fine-tune link that reveals the editor
  (rail, inspector, timeline). A hand-cut video opens in the editor as
  before. Same player wiring (`player(true)`), so nothing is duplicated.
  `design/eval/2026-10-18-watch.png`.
- **Music that matches a reel's feel** (2026-10-18): `music.brightness`
  (median spectral centroid over the middle minute, Hz) joins every track's
  features (`FEATURE_VERSION` 3: cached folders re-analyse once) and the
  reel's `music.bright` (`style.music_feel`, "a bright, airy sound" /
  "a warm, low sound"); `remix.fingerprint` carries the median as
  `bright`; `remix.pick_from` scores timbre (an octave off = 0) at 0.15
  when both are known, else the old weights. Priors. `tests/test_feel.py`.
  **Learn a vibe in the app**: `POST /api/vibes {niche, name, links}` runs
  `vibes.learn_set` as a job (`vibes.start`, `/api/vibes/jobs/{id}`); the
  Setup dialog has "+ Learn a vibe from reels you love…" under Cut it
  like, polls it, reloads the choices and selects the new vibe.
- **What you undo and refuse** (layer 3, 2026-10-18; `Preferences.
  suggestions` / `take`, `/api/preferences/suggest`, "From what you did"
  in `Chat.tsx`): an undone turn of the machine's own (`MACHINE`: the bed,
  the captions, the repeat check, smoother cuts) and a "no" at export with
  a note are offered once as suggested rules; only the creator turns one
  into a rule (every video needs when / when not; this video; or No), and
  the decision is kept in the preferences file (`suggested`) so it never
  comes back. Undone hand edits are not suggested (they're the creator's
  own). Nothing is applied from a suggestion by itself. `tests/test_learn3.py`.
  Also that day: the writer hears the reel's own lines (`words.samples`
  from the OCR, ≤ 12, on `fp.text.samples`, appended to the taste as
  "write new ones in that spirit, never these"); the setup's lengths
  differ by frame (`brief.length_for`: a vlog takes the Medium mark);
  Keyboard shortcuts and Polish left the name menu (the `?` in the timeline
  bar and `#polish` still reach them).
- **Taste in the loop** (layer 2 of preserving preference, 2026-10-18;
  key only). `make.taste_text(profile, PREFS.for_model())` renders the
  creator in their own words (name, what they make, the feeling, pace,
  never…) plus the confirmed rules; it rides on the system prompt of the
  two calls that choose and write: `llm.rank_shots(…, taste)` through
  `select.judge(taste=)` / `remix.plan_shots(taste=)`, and
  `llm.day_phrases(…, taste)` through `make.words`, which writes one line
  per stop from its time and labels (the same writer as the describe
  captions) and hands them to `remix.captions(phrases=)`; caps when the
  reel's words were caps; a failed call leaves the label table's phrase;
  the job records `taste` and `written`. The profile the server knows is
  the one mirrored from the profile page (`/api/profile`). Not tried
  against the live model (no key on this Mac). `tests/test_taste.py`.
  Layer 3 (undo and verdicts as candidate rules) is not built.
- **Recipes** (`web/backend/recipes.py`, `/api/recipes`, `SaveRecipe.tsx`;
  idea 4 of the open-tools research, built on barbie's vibes and Watch
  screen once merged, 2026-10-19). "Save as my recipe" (next to Download on
  the Watch screen, and in the name menu) measures the finished board, not
  the clips: pace and arc from `timeline.layout`'s shot ends, words from the
  resolved overlays (share, band by time held, hold, samples), the music's
  BPM and energy arc from its in-point, the ending; plus its dress (frame,
  look, music on/off, the caption `overlay_style`, a transition on every
  join, an effect on ≥ 75% of shots). Saved under a name (the same name
  replaces it) in `$VIBECUT_CACHE/recipes/`, mirrored as kind `vibe`, key
  `recipe:<id>`. Listed first under "Cut it like" (♥, renamed or deleted
  there; picking one preselects its frame, look and music). A Make with
  one: `make.fingerprint(vibe=…)` like any vibe, its caption samples ride
  as phrasing, and `recipes.dress_ops` lands on the same Make turn (one
  Undo; `board.applied` gives the trial board). A recipe is a vibe: no AI,
  nothing spent. `tests/test_recipes.py`.
- **The viral library** (`web/backend/vibes.py`, `/api/vibes`, "Cut it
  like" in `Setup.tsx`; the user's vision, 2026-10-18: learn from viral
  vlogs). A vibe = `remix.fingerprint` over a *set* of reels learnt through
  `reference.start` (so each has words / opening / ending too), saved as a
  dated record under `$VIBECUT_CACHE/vibes/` naming its sources, mirrored
  as kind `vibe` (`lib:<id>`). `MIN_REELS` 3. CLI: `python -m
  web.backend.vibes --niche … --links file | --files …` (`--limit` 120 s of
  each reel). The Setup dialog offers the library's vibes, then the
  creator's own learnt reels as one-reel vibes (`ref:<rid>`); the pick
  travels as `style.vibe`, is remembered (`defaults`), and
  `make.fingerprint(vibe=…)` takes it over the frame's prior (duration
  still capped by the frame). Popularity stands in for "well cut"; the
  record names its reels so that can be judged. `tests/test_vibes.py`.
  First real vibe, 2026-10-18: `day-in-my-life-popular-reels-20261018`
  from the 19 vlogs and reels on this Mac (the calibration set): 1.20 s a
  shot, hook 2.1 s, 69–144 BPM, builds; 90 s learnt of each.
- **The Supabase mirror** (`web/backend/cloud.py`, `supabase/migrations/
  0001_preferences.sql`; the user's decision, 2026-10-18: preferences in a
  backend connected to Supabase). One table, `preferences(device, kind,
  key, value, updated_at)`, kinds default / rule / profile / vibe. Local
  JSON stays the source of truth; every change pushes an upsert in a thread
  through PostgREST over urllib (no SDK), failures are logged and retried
  on the next push, nothing raises into a request. On start `_cloud_pull`
  applies rows newer than the local copy (`CLOCK_SLOP` 5 s): defaults
  (`defaults.note(_sync=False)`), rules (`Preferences.absorb`), the profile
  (`/api/profile`, also mirrored from the profile page's Save). A learnt
  reel pushes its numbers (`style` minus the transition list), never a
  frame. Identity is a `device` id in settings.json until sign-in. Config:
  `SUPABASE_URL` + `SUPABASE_ANON_KEY` in `web/.env`; off otherwise
  (`capabilities.cloud`). `tests/test_cloud.py` against a fake endpoint.
- **Defaults that follow the creator** (`web/backend/defaults.py`, layer 1
  of preserving preference, 2026-10-18): the frame, look and Music switch
  from Make, the frame chip, a look picked under Captions and a caption
  template / entrance are remembered in `$VIBECUT_CACHE/settings.json`
  and offered next time as the *preselected* answer ("as last time"; the
  footage's own frame suggestion still shown), never applied silently; the
  remembered caption style rides on the Make turn as its own `overlay_style`
  op (`source: "defaults"`, which is not re-remembered). `BriefAutoReq.music`
  None = as last time. Layer 2 (taste + confirmed rules into the judge's
  prompt, key only) and layer 3 (undo / verdicts as candidate rules) are
  not built. `tests/test_defaults.py`. `make.start(register=…)` sets the
  job before its thread runs — a fast job landed as "not mine" before.
- **The one pipeline** (`web/backend/make.py`, `/api/make`, 2026-10-17;
  after rendering the app headless on sarah's shoot: "Make my video" gave a
  13-shot chronological timeline with clock captions and no music, while the
  engine that makes the video she asked for lived under "Build a short from
  reference reels"). Make = the brief from the two picks → gate passed in
  the creator's name → a job: fingerprint (references', else `PRIOR` by
  frame and pace: a short 0.7–1.2 s a shot, hook 1.5 s, ≤ 60 s; a vlog
  1.8–3.2 s, hook 2.5 s) → `remix.plan_shots` (worth-ranked, judged with a
  key) → music from `bed.candidates` (own folder / Openverse / pack,
  prefetched at import now) with shots quantised to its beat and the drop
  at the end of the hook → one turn: `choose_option` (option `made`),
  `set_music` at the frame's levels (`LEVELS`: a short rides on the music,
  a vlog keeps its sound and ducks under talking), `set_look`, a title and
  a line per stop (`remix.captions`). Lands in Frames and plays. The
  three stories still exist under Other stories (the direction turn is
  added first). On her 42 clips: 27 moments, 25 s, hook first, cuts on the
  beat, music under it — see `design/eval/` screenshots 23–25. Every number
  in `PRIOR` / `LEVELS` is a guess. `tests/test_make.py`.
- **The story editor** (`web/backend/story.py`, `oai.py`; sarah, 2026-10-18,
  after comparing VibeCut with a London day vlog: named chapters, each a
  setup → steps → payoff, a designed title over a plain line). Inside Make,
  one OpenAI call (her course's team key, $25 for the term; **not Claude**)
  sees up to 60 rough-cut moments (one index frame each, low detail, plus
  time / stop / labels / faces / talking / worth) and returns chapters named
  by what happens, what's kept, its order, each shot's job and length
  (`ROLE_S` by frame, priors), a hook, a line under each chapter title and
  a caption on the few moments that want one. The rules still cut each
  window, the beat and the music. **The words** (sarah, 2026-10-18:
  "captions usually convey 1. a thought ... 2. what we're doing at a
  timestamp"; "green spaces, a green drink, and sunny streets" read as AI):
  every line is the creator typing over their own clip, a first-person
  thought or what they're doing, 3-5 words, lowercase, ≤ 1 emoji, never a
  description or list of the picture (`story.VOICE`, also in the chat's
  overlay rule and `llm.DAY_SYSTEM`); lines they typed before
  (`habits.phrases`) and their taste ride along. Checked in code
  (`story.line_of`: a list, a clock left mid-line, > 6 words or > 42
  characters drops the line, never cut to a fragment; a model's clock only
  comes off either end; one emoji, flags and CJK counted right);
  `clock` puts the real filming time in front ("7:40 am · walk to class").
  Captions (kind `caption`, so the Soft look) hang on their shot once the
  title has gone (a moment under the title starts its caption just after
  it), ≤ 2 a chapter, held 1.4-3 s to read, never past the chapter; after
  the self-check moves shots, `story.fit_captions` rides on the check turn
  and keeps each title inside its chapter and each caption after it, ≥ 1 s
  or dropped. Chapter titles are overlay kind `heading` with their own `look`,
  independent of the captions' one style: every AI title, and any added by
  hand, is `spaced` = thin white widely spaced capitals (Montserrat Light,
  bundled) over an italic line in the same family, with its own calm
  entrance (no card tilt or slam); a title always fits the frame on one
  line by getting smaller (`fitTitle`, ≥ 40% of its plain size, so one
  sized up by hand comes back down), in the typing box too (measured on the
  words being typed); where ink.py asks for a halo it wins over the title's
  soft shadow.
  script / bold / serif stay pickable by hand. `tests/test_story.py`,
  `headingLook.test.ts`.
  Runs only with `OPENAI_API_KEY` in web/.env **and** the AI switch on (the
  "AI" pill in the top bar and in the two-picks popup, `/api/ai`, kept in
  `$VIBECUT_CACHE/ai.json`, off by default; sarah, 2026-10-18), and only for
  a Make that carries the estimate she saw (`/api/make/estimate` → `ai_ok`):
  the popup shows "this edit will cost about $…" before Make. A key is not a
  yes to spend it. `OPENAI_MODEL` overrides `oai.MODEL`.
  Cost is read from each reply's usage, said in the reply and kept in
  `Project.events`. Any failure → the rules' edit, and the reply says so.
  urllib only (no SDK on her Mac). `tests/test_story.py` (stand-in replies).
  Not yet run against the live model.
- **AI Edit on the course key** (sarah, 2026-10-18: "Build it" on putting the
  chat on the course key so it shows when AI is on). `llm.chat_provider()`:
  OpenAI (`oai.enabled()`: key + AI switch) else Claude (its key) else
  nobody; only the chat moves (`interpret`, so the left-rail chat and Chat on
  pause), every other call in llm.py stays on Claude's key. Same SYSTEM,
  state text, history and SCHEMA (strict) on OpenAI, the paused frame at low
  detail. Before sending: `/api/chat/estimate` (free; `llm.estimate`, priced
  for whoever answers, output 600–2500 tokens, priors) puts "Send · 1–3¢" on
  the button, and on the course key a message is answered only when it
  carries that estimate (`ai_ok`, `_chat_gate`). After: the cost is on the
  turn (`Turn.cost`, persisted), in `Project.events` (kind `chat`, also for a
  paid answer that failed) and in the panel's "6¢ spent" (`_ai_spent`: chat
  + AI-planned Makes). The rail reads AI Edit whenever someone answers, else
  History, which then offers the switch (no key: says so, no switch). Idea
  chips above the box fill it, never send. Like other editors' assistants: an
  "About [Shot 3 · 0:12] / Whole video" chip (the clicked shot, else the one
  under the paused playhead) sends that moment's text + frame with the
  message (`ChatReq.t`, `_target`; never a `choose_option`); the AI is asked
  outside LOCK (`llm.prepare` → `llm.ask` → apply), so the app keeps
  working; Stop (`/api/chat/stop`, by the box's `rid`) frees the box at once
  and the answer changes nothing when it lands, its cost still counted; an
  answer landing on another video changes nothing; a failed one offers Try
  again. The app's own first story (no board, no `ai_ok`) is the free rules'.
  `tests/test_chat_ai.py` (stand-in replies). Not yet run live.
  **Caption looks by chat** (sarah, 2026-10-20: the chat said it "can't set
  custom fonts or background-matched contrasting colours"; "Build it"): the
  chat has the Captions tab's controls as `caption_style {captions}` (word
  art / soft, font / own, colour / auto, outline, shadow, background, boldness,
  animation, position) and moves or sizes words with `placement` on
  edit_overlay / add_overlay (set x, y, scale / usual, size, a chapter
  title's look); overlay `all_captions` (kind caption) / `all_titles` (kind
  heading) = one edit (or drop_overlay) each, never their words or timing; part labels, name
  tags, dates and the opening title go one at a time (they share moments on
  screen, so one point would stack them). Every field is `keep` unless asked
  and a number left alone is -1, so the strict schema can't reset the rest;
  `llm.expand` turns the answer into board ops against the edit as it is,
  exactly as the tab would: a new word art starts fresh (StyleBars `PLAIN`),
  a switch turned on starts from what the captions show (`_dress_of` mirrors
  overlayDraw's `dressOf` / `tinted`, word arts' own edges and boxes in
  `ART_DRESS`: keep the two in step), numbers clamped to its sliders (12 read
  as 12%), an unplaced overlay's spot as `CaptionWords` reckons it, enums
  without case, each op reading the edit as the earlier ops in the same answer
  left it (`board.applied` on only the ops added since, so a long answer stays
  quick; an outline or shadow asked before a new word art is read again on it,
  so the order in the answer doesn't matter); in the chat and on pause. What can't land still reaches the
  board, so the turn says "Skipped: …" instead of nothing. The state shows
  CAPTION STYLE (with the word art's own numbers) and each overlay's place
  (an unplaced one: where it's drawn and where a set starts, x 0.5 as the tab's
  Place / Size start; resizing in place is `size`).
  Many changed at once read as one line (`overlays._fold`). A template or
  entrance asked for in words is remembered like one picked in the tab, once
  it landed. What it can't do, it says where in the app it's done. The schema
  is at Claude's limit of 16 nullable fields: `option` / `amount` say
  "unused" instead. `tests/test_chat_captions.py`. Not yet run live.
- **The AI checks its own edit** (`web/backend/selfcheck.py`, `/api/check`,
  `/api/check/estimate`, `/api/check/sheet/{name}`; sarah, 2026-10-18: "lets
  do AI checks own edit"). The story editor sees one frame per moment and
  never the finished cut, so after an AI-planned Make (inside the job, stage
  `checking`) and on "Check my whole edit · ¢" in AI Edit, one call on the
  course key looks at contact sheets of the cut: one still per shot from the
  middle of the seconds it uses, 16 to a sheet at high detail, numbered as
  the timeline numbers them, a strip coloured by chapter (drawn in numpy: no
  drawtext here), plus a list (chapters with seconds and share; each shot's
  clip, time, labels, talking; the phone's look-alike and same-seconds
  hints). It answers with issues (repeat, drags, back_and_forth, opening,
  ending) and fixes (drop / shorten / move), checked in code: at most a
  quarter dropped, none from 5 shots or fewer, a talking shot dropped only
  as a repeat, shortening on whole half-beats and never under 0.6 s. One
  turn of kind `check` (its own Undo, its cost, "What it looked at"); one
  round, never a loop. Make's estimate covers planning + the check (`plan` /
  `check`); a button press carries its price (`ai_ok`); Stop by `rid` like
  the chat; a failed check is a turn that says so and changes nothing.
  Research of open tools (oh-my-cassette, ffmpeg-skill, OpenStoryline,
  ai-video-editing-skill): sheets there are for people or layout checks,
  none has a model review its own cut. `tests/test_selfcheck.py` (stand-in
  replies). Every number is a prior; not yet run live.
- **Two picks up front** (plan of 2026-10-10, step 2; `Setup.tsx`,
  `/api/brief/setup`, `/api/brief/auto {format, look}`, `/api/format`):
  after Footage's "Looks good" one popup asks the **frame** (short ·
  vertical ≤ `SHORT_MAX_S` 90 s / tall · vertical vlog / wide · 16:9;
  default from the upright share of the footage, `brief.suggest_format`)
  and the **look** (the seven of `looks/*.json`, default cozy), then "Make
  my video". They travel as `style.format` / `style.look`: the frame sets
  `export.frame_size(..., want)` for the stage and the export (a chip in
  Frames cycles it; not a board op, so not in the log) and the length
  (`brief.length_for`); the look is the first op when the story is chosen
  (`caption_ops` takes a look id, and dresses the video even with no
  captions). `tests/test_format.py`. `StyleQuestions.tsx` stays only for
  the chat's first message.
- **Style questions** (`web/backend/brief.py`, `StyleQuestions.tsx`,
  `web/frontend/src/brief.ts`): straight after Footage's "Looks good" (no
  "What's this video about?" box since 2026-10-06, sarah; the description is
  guessed from the shoot, `pitch.guess`, never the model). Since 2026-10-07 (sarah: "build") the popup isn't shown on the main path either: `/api/brief/auto` writes the brief itself (suggested length from `length_marks`, captions = describe, no pace question any more) and the stories are built, the one the shoot suggests is taken and the edit opens in Frames (sarah, 2026-10-07: no story choice for now; the others stay under Story). **Tempo** (`web/backend/tempo.py`, `PaceButton.tsx`; sarah: "you should be able to realize what kind of editing tempo we want"): quick / steady / calm read from the shoot (share of moving vs still shots by `activity`, talking and music from sound.json, median clip length), travels as `style.pace`; talking shots keep their whole window at any pace. The story: on camera most of the time → subject, several days over ≥3 places → place, else time. The top bar is Footage · Edit only, there is no Story / Frames switch (Other stories is under More and closes back into Frames), Media in Frames is two piles like Footage's, Kept = in the video / Left out (sarah, 2026-10-13; `Shelf.tsx`, `/api/pile`, `brief.clip_ops`): a clicked clip plays, says why it's out, and "Move to …" puts its rough-cut window in where it was filmed or takes every shot of it out, one undoable turn, the rough cut's call set to match, one Export button (sarah, 2026-10-07). Both shown with their reason under the tempo button in Frames, changeable there (`/api/pace`, one undoable turn). MOVING 30 / STILL 10 were set on her one shoot; the rest are priors. `tests/test_tempo.py`; Length and a Captions on/off switch (`/api/captions`, one undoable turn) sit in Frames. The popup code remains for the chat's first message: a
  popup asks length / pace / opening / focus, one question at a time, before
  the rough cut is shown. Length, pace and opening travel as `style` on the
  direction and reshape each proposal (`brief.shape`); focus and any
  Claude-tailored question (key only) become direction words. Targets (60 s,
  180 s, pace caps 8 / 5 / 2.5 s) are guesses. Tests: `tests/test_brief.py`.
  **Length is a slider** (sarah, 2026-10-06; `brief.length_marks`,
  `LengthSlider.tsx`): 15 s to everything the rough cut kept, Short / Medium
  / Long marks from how much there is and the kind of video the description
  says (day vlog / trip / event / other), one suggested with a reason; its
  end is what the edit can reach (`brief.reachable_s`: look-alikes count once,
  as `length_ops` never puts one back), not every usable second; it
  travels as `style.seconds` (≤ 75 s = one shot per moment, as `short` did).
  The same slider in Frames ("Length · 2:36") is one undoable turn
  (`brief.length_ops`, `/api/length`): weakest shots out first, else good
  shots back in filming order, their rough-cut window only (`add_shot` takes
  start/end), never a look-alike. Kind lengths and the "plenty" rule are
  priors. `tests/test_length.py`.
  **Captions** (none / describe / transcribe) travels as `style.captions`,
  and a follow-up asked only when there are captions (`when` on the
  question), the look (clean / bold = hype / cozy / quiet), as
  `style.caption_look`. When a story is chosen it becomes one undoable turn
  (`brief.caption_ops`: look + captions; no opening title, sarah 2026-10-06 — a cover image is planned instead). **Describe** = per moment
  the day moves on, "7:42 am · coffee run" (`daylog.py`; clock from the
  clip's recording time + shot offset, phrase from Vision labels, a bigger
  table incl. scenery; with a key Claude may phrase labels + time, text
  only) plus, where a new place starts, its name above the line (`sub`):
  GPS rounded to ~100 m → Apple's geocoder on the Mac (`places.py`,
  `place/vibeplace.swift`; coordinates only, free, cached in
  `$VIBECUT_CACHE/places.json`; a place, area or city, never an address).
  The default when the description says day-in-my-life. **Transcribe** =
  subtitles of what's said (`subtitles.py`): only clips where a voice is
  heard, Apple SpeechTranscriber on the Mac (speech.py, cached), lines
  broken at pauses ≥0.6 s / sentence ends / 42 chars (16 CJK), timed to the
  words, anchored to the shot; prefetched in the background when the brief
  is saved. Words never decide the cut. **Ink** (`ink.py`): each overlay's
  colour is checked against the frame behind it (32×18 tone grid per index
  sample, `tones.npy`, written at index time or once from the sample JPEGs
  for older clips); where the look's colour is under WCAG 4.5 it takes a
  tint / shade of the footage's own hue that reads over ≥95% of the band, a
  neutral only if none does; when none does (part light, part dark under
  the words) light words on a tight dark edge + soft shadow, never dark
  words (they vanished into hair and trousers on her footage). Derived per request, never stored in the log. The UI calls
  overlays "Captions". `tests/test_ink.py`. **Dragged by hand**: click a
  caption on the preview to select it, drag to move (snaps to the centre
  lines), drag a corner to size it, double-click for its words; each drop is
  one `edit_overlay` with `place: {x, y, scale}` (block centre, 0–1; null =
  back to its usual spot), drawn by the same `overlayDraw` in export, free
  up to the frame's edge (sarah, 2026-10-18: "all the way to the edge"; the
  safe area only places captions left where they usually go); checks still only warn. "Same place for all
  captions" is one turn. `test_overlays.py`, `overlayLooks.test.ts`. Older answers (day / simple / bold /
  key) map to describe + a look. `tests/test_captions_answer.py`.
  The description is read from the shoot (`pitch.py`: days,
  morning→night, themes, faces, talking, rough GPS; `guess` = the first
  template line, so `kind_of` sees day / weekend / days away).
  `tests/test_pitch.py`.
- **About the day, not the face** (sarah, 2026-10-14, after comparing
  VibeCut's edit of her school day with her own: half of it was her face,
  one chat with a friend held 14 s, food / stairs / night campus were left
  out). `tests/test_day_picking.py`. **Talk said to the audience vs talk
  overheard** (`trim.addressed`): faces.json rows are now `[presence, edge,
  people, facing]` (`vision.face_track`; the Swift helper adds each face's
  yaw, looking in = |yaw| ≤ 25°; older 2-column caches are re-read once on
  project open, `indexer.refresh_faces`, Mac only). Talking while looking
  into the lens keeps its sentence; talking turned away, or two people with
  no direction read, is chatter: `CHATTER_S` 3 s in the rough cut, cut by the
  pace like any shot, not counted as talking by `tempo.read`. No face at all
  (narration from behind the camera) changes nothing. **Every stop first**
  (`brief.spots`, `weakest`): a new stop when GPS moves > 150 m or 20 min
  pass; shortening (`shape`, `length_ops`) drops from the stop with the most
  shots, lengthening brings back stops not shown yet. **Shorts** hold no
  moment over `SHORT_CAP_S` 3.5 s (`brief.cap_for`, also `/api/pace`). **Lit
  night** shots (after 6 pm, contrast ≥ 0.4) are never left out for quality
  (`storyboard.lit_night`). **Swipe**: cozy and hype join parts with a whip
  (xfade slideleft + sideways smear, `export.swipe_blur`; the player slides
  both pictures, `joinView.swipeAt`); needs a dissolve's handles, else a cut.
  All numbers are priors from one of her edits. Not yet run on her clips.
- **What a moment is worth** (`web/backend/worth.py`; outside evaluation of
  the Oct 16 demo, sarah: "implement"). Every Shot gets `worth` (0..1) and
  `worth_why` in `shots_from_clips`: craft (`score`) plus feeling (laughter
  ≥2 heard seconds, singing, talking to the lens, from sound.json, which
  nothing used for picking before), label rarity across the shoot, the
  first face-free shot at a new stop ("first look at a new place"), minus a
  little for a face with nothing said. `shape` and `length_ops` rank by it
  (hook = the strongest moment, not the best-exposed), and `weakest` drops
  from the stop with the most shots *per its importance* (its best worth),
  so screen time follows what happened at a stop, not how much was filmed;
  a stop's last shot still goes last. Look-alike collapsing stays on craft.
  Weights are priors. `tests/test_worth.py`.
- **Music at social volume**: the bed's `set_music` asks for levelling
  (-14 LUFS, `audiomix.write_wav`), preview and export alike; the Oct 14
  school-day edit was -20 LUFS against her own -15. `tests/test_loudness.py`.
- HDR (HLG/PQ) footage: thumbnails and samples are tone-mapped to SDR in
  `media.to_sdr` so they look like the phone showed them; measurement frames
  are untouched. `tests/test_hdr.py`.

- **The vlog grammar** (`web/backend/vlog.py`; 2026-10-19, after the creator
  watched a made video: "the cut is too random, not those pretty vlogs on
  YouTube"). A tall or wide Make, when no reel is being copied, is cut like
  a vlog, not a reel: `make.PRIOR` holds 3–6 s a shot (hook 3 s), no speed
  ramp, no flash, only the hook pushes; the picker refuses shots filmed
  under 2.5 s (`select.choose(min_s)`) and a vlog that lands under 90% of
  its length asks for more moments once. Picks are regrouped into *scenes*
  (`brief.spots`: a place, twenty minutes; at most 7), each stop sequenced
  wide → medium → close from face area + detail labels, look-alikes apart,
  ending on a detail or a face; folded scenes keep the day's order. Holds
  follow stillness (`activity` < 15 ×1.5, > 40 ×0.7, clamped 1.5–7 s), cut
  in before the action (`select.window`). Shorts are unchanged. Judged on
  the one real shoot (42 clips: 27 shots of 0.6–3.9 s in 45-min sessions →
  20 shots of 2.6–6.8 s in 7 scenes, 73 s of the 90 asked: the footage is
  short). Every number is a prior. Then, the same day, the rest of the plan:
  **continuity** (`vlog.flow`: inside one stop, among the orders that keep
  wide → medium → close, the one the joins checker scores smoothest, with
  look-alikes apart and the scene still ending on a detail or a face;
  never across stops, so the day's order holds) and the smoother's nudge
  onto movement runs after a vlog Make as its own "Smoother cuts" turn
  (user decision 2026-10-19: Make is the machine's own edit, so this is
  not cutfix; it still never touches a hand-cut edit); **phrases**
  (`vlog.phrase`: the hook on a whole beat, every scene a whole number of
  two- or four-bar phrases, shots inside a scene where the action ends,
  not on the beat; the closing shot takes the slack); **natural sound**
  (the vlog's own sound at 1.0, music at `vlog.MUSIC_GAIN` 0.5 settling to
  `SETTLE` 0.6 of that inside each scene via the bed's duck list, so it
  rises at a scene change; `set_join carry_out` inside a scene = L cuts);
  **one word per scene** (`POST /api/scenes/{beat}/verdict {keep|cut|
  longer}` from the Watch screen; cut and longer are one undoable turn
  each, every word is a `scene_verdict` event on the project with the
  scene's labels and holds — the calibration record — and `habits.derive`
  reads cut / longer as removed / held; `launchlog.summary` counts them).
  Tested in `tests/test_vlog.py` and the wide Make in `test_make.py`.

- From montage-vlog-compiler (MIT; see NOTICE), four pieces:
  - **Evidence levels** (`cutgrammar/evidence.py`): every finding names
    what it rests on — meta / still / motion / audio. A finding whose
    reading the media lacks gets verdict `pending` ("not checked"), value
    kept. `load_index()` carries no motion. Rough-cut "shaky" is only a warning
    at the gate, never a rejection: guessed from stills, it threw out 17 of
    42 handheld videos once music stopped counting as talking.
  - **Inventory** (`cutgrammar/inventory.py`, `inventory.py`): read-only
    sha256 manifest of a shoot folder; verify names missing / changed /
    unexpected files. CLI only, not wired into import.
  - **Preferences** (`web/backend/preferences.py`): each edit turn is a
    candidate; only the creator sorts it. Only "every video" (needs rule +
    when + when-not) and "this video" are ever reused, and only confirmed
    rules reach the model. Undone edits can't be confirmed. Long-term rules
    live in `$VIBECUT_CACHE/preferences.json`.
  - **Voiceover mode** (`web/backend/voiceover.py`): opt-in fourth proposal
    from the creator's SRT or script. See the amended non-goal below.

- **Launch log** (`web/backend/launchlog.py`, `/api/exports/{n}/verdict`,
  the question in `Export.tsx`; launch checklist, 2026-10-11): the one
  workflow is drop → two picks → watch → export; completion = an export
  without a chat edit (`default_path` on the record), success = "would you
  post this?" answered yes. Bed outcomes and verdicts are `Project.events`;
  the CLI sums completions, failures, costs and feedback from the records.
  `tests/test_launchlog.py`. Eval of 2026-10-11 (20 real cases from the
  index, 20 pass) and the launch plan: `design/eval/`.
- **The bed** (`web/backend/bed.py`, `/api/bed`, the Music switch in
  Frames; plan of 2026-10-10, step 1): choosing a story puts music under
  it and moves the cuts onto its beat, one undoable turn that lands when
  the pick is ready (background job, `session.bed`). Track from the
  creator's folder, else Openverse by moods the pace suggests
  (`PACE_BPM`, `MOODS` — priors); scored by `remix.pick_from` (the Remix
  picker, now source-agnostic); drop at the end of the first shot (`HOOK_S`
  cap 8 s). Beat snap via `apply_style` traits=["beat"] with the grid in
  edit time and `keep` = talking shots (`restyle.retime` gained `keep`);
  `set_music` at `audiomix.MUSIC_GAIN`, original 1.0, ducked to
  `TALK_DUCK` under talking. Not for remix / talk / voiceover boards.
  **Backup songs** (`cutgrammar/songpack.py`; sarah, 2026-10-11: "only
  used if users link fail"): 24 songs VibeCut composes itself (8 per pace,
  CC0, no audio in the repo; rendered once into `$VIBECUT_CACHE/music/
  pack/`, ~20 s each, then measured like any track). Used only when
  Openverse hands back nothing or nothing that fits; never preferred. A
  failed Openverse search is no longer cached as "no songs".
  `tests/test_songpack.py`.
  `timeline.grid_of` now subtracts the music in-point (every Remix grid was
  off before). `VIBECUT_BED=0` keeps tests offline. `tests/test_bed.py`.
  A picked track (Openverse download or backup song) is found again by id
  in the music cache after a restart (`musiclib.find`); before, the edit
  lost its song. `tests/test_music_restart.py`.
  Measured 2026-10-10 on this Mac: a cold online pick took 195 s (36 tracks
  fetched + analysed), so `/api/brief/auto` calls `bed.prefetch(pace)` as
  soon as the pace is read and the chip shows done/total. Openverse's
  commercial slice is thin: one-word moods only (phrases return 0).
  Not yet judged on real footage.
- **Sound as glue** (`web/backend/audiomix.py`; research
  `design/research/08-fluency-and-motion-ux.md`, P0/P1). One numpy mixer builds the
  edit's whole sound; the preview plays it (picture muted, rate-nudged to
  stay in sync) and export muxes the same samples, so they can't disagree.
  Every join is micro-faded (15 ms); joins are per cut on the board
  (`set_join`: cut / carry_out = L / carry_in = J; default carry_out between
  parts, cut inside), carried only where the source has footage past the
  cut, else a clean break reported at the join. Music is board state
  (`set_music`: track, in-point, gains, ducks, sfx, level) — Remix writes it
  (and its grade via `apply_style`), so editing a remix no longer loses its
  mix. Default proposals keep one of each look-alike group filmed within
  15 min (Vision only; cos ≥ 0.78, or ≥ 0.72 from the same spot, GPS ≤150 m).
  An edit that already exists gets the same check (`brief.repeat_ops`, also
  the same stretch of one clip twice, across parts): when a story is chosen,
  and once for stories chosen before it, one undoable turn drops the
  weaker of each (sarah: never identical shots in the edit); later hand
  edits are never second-guessed. Overlay ffconcat gets `option framerate 30` (10 of
  30 frames were wrong). CARRY_S 0.5 s and MICRO_S are priors — calibrate.
  Tests: `tests/test_audiomix.py`, additions in `test_export.py`,
  `test_brief.py`, `test_remix.py`.
- **Extract audio** (`board.SOUND_OPS`: `extract_audio` / `edit_audio` /
  `drop_audio`; `audiomix.strips_of`, `timeline.audio_lane`; sarah,
  2026-10-14: "at least have the basic functions for most video editing
  apps"). The shot bar's Sound › "Take the sound off" puts the shot's sound
  on its own strip in a Sound lane under the picture (`sound.off` +
  `sound.strips` on the board), sounding as the shot did (its speed, volume
  and fades come along): the strip sits at a place in the edit (unlinked,
  like CapCut), drag to move it (sticks to the same targets), click it for
  its own bar (Volume 0–200%, Fade in / out, Mute, Delete this sound).
  Deleting leaves the shot silent; a cut through a silenced shot keeps both
  pieces silent. Preview and export hear it through the same mixer.
  `tests/test_extract_audio.py`.
- **Voiceover** (sarah, 2026-10-27: "build voiceover"; `web/backend/mic.py`,
  `/api/voice`, `board.add_voice`, the timeline's Record button, `App.tsx`
  `startRecording`). CapCut / iMovie's convention whole: Record (next to
  Split / Delete) → 3-2-1 over the preview → the edit plays from the playhead
  without its sound (`transport.silent`, iMovie's "Mute project") while the
  browser records the mic (echo cancel, noise suppression) → Stop, Space,
  Escape or the end of the video puts the take on its own orange strip in a
  Voice row of the Audio lane where recording started, one undoable turn.
  The take is saved once as 48 kHz WAV under `$VIBECUT_CACHE/voice/`; the
  board keeps its id, place and level (`sound.voice`), and it is moved,
  levelled (0–200%), faded, muted and deleted like an extracted strip
  (`edit_audio` / `drop_audio`). The mixer (preview and export alike) places
  it and ducks the music to `VOICE_DUCK` 0.3 where the voice is heard
  (`mic.speaking`: a level gate, pauses under 0.6 s bridged), back up in the
  pauses. Nothing is transcribed and nothing leaves the computer; this is not
  the script-led voiceover proposal (`voiceover.py`). Not from chat. Priors.
  `tests/test_mic.py`.
- **Shot bar** (`ShotBar.tsx`; `board.set_shot`, fields `speed` / `gain` /
  `mute` / `rotate` / `fill` / `mirror` / `fade_in` / `fade_out` on the
  entry, kept through a cut except the fade on the cut side; sarah,
  2026-10-14: the stepped menus were "very not user friendly", one click to
  a tool then a slider). Clicking a shot in Frames opens a bar along the
  bottom, no pop-up menu: Split · Sound (Volume slider 0–200%, Fade in /
  out 0–3 s, Mute, Take the sound off) · Speed (doubling slider ¼×–4×,
  0.5 / 1 / 2 / 4 presets) · Turn & crop (quarter turns, Mirror, Fill the
  frame = cover and crop instead of bars, Show it all) · Swap · Delete.
  A slider is one undoable turn when let go. A shot lasts `bd.seq_dur` =
  source seconds / speed; `timeline.layout`, the board's own arithmetic and
  overlays use it, the player plays the file at rate × speed and dresses
  the picture with the same turn / mirror / fill as `export._shot`. Sound
  at a speed is stretched with atempo (pitch kept, `audiomix.stretched`); a
  sped-up or slowed shot never carries sound or dissolves across its cuts.
  Known: the length slider, the bed's beat snap and restyle still count
  source seconds, so they're approximate on a shot that isn't at 1×.
  `tests/test_shot_fixes.py`.
- **Clip tools: Duplicate, Freeze frame, Reverse, Copy / Paste settings,
  music Volume** (sarah, 2026-10-19, "Build it"; Inspector Edit tab, ⌘D,
  ⌥⌘C / ⌥⌘V; `tests/test_clip_tools.py`). `duplicate_shot` puts a copy
  right after the shot; `freeze_frame {shot, at, dur}` (default `FREEZE_S`
  3 s, CapCut's) cuts in a held frame `{freeze: True}` whose span is its
  length (start = the frame), silent, keeps turn / mirror / fill; its ends
  only change how long it holds. `reverse` is a `set_shot` field: a cut or
  trim on a reversed shot acts on what plays first / last (`board.
  play_offset`; the frontend's `toSource` gives true source time).
  `reverse.py` makes the backwards span in 2 s pieces (ffmpeg's reverse
  holds every frame) for both the player (`/api/reversed`, 540p) and export
  (output size); the mixer reverses the samples; no handles, no carries.
  Copy / Paste settings is frontend only (one `set_shot`). Music volume is
  `set_music volume` (1 = as placed, ≤2) folded into the gain by
  `export.music_spec`; with `level` the loudnorm still levels the whole
  mix, so on a short it mostly moves the balance.
- **My resources** (`web/backend/resources.py`, `/api/resources`,
  `Resources.tsx`; sarah, 2026-10-19: "a resources folder so i can save my
  own animations or templates forever", on the left rail, in the profile,
  signed out it guides to sign in). A folder on the rail under AI Edit:
  caption looks (the hand-picked `overlay_style` fields, never the
  entrance), animations, transitions, effects, shot settings (`SHOT_FX`;
  a held frame takes only what it can show) and songs (track + in-point).
  Saved by "Save from your video" at the top of the folder (sarah, 2026-10-19:
  she couldn't find the tabs' buttons) and by "Save … to My resources" at the
  top of where each is made (Captions, Effects, Edit, Audio tabs): what's on
  the video now, never typed in; one readiness list (`saveWhy` in App.tsx)
  says what to do first when there's nothing to keep. One click
  puts it on as ops (`overlay_style`, `set_transition`, `set_shot`,
  `set_music` at the current levels, else the bed's) in one undoable turn,
  on the clicked shot / cut else everywhere. Kept in `$VIBECUT_CACHE/
  resources.json`, outside projects, and mirrored as kind `resource`
  (migration 0002; a delete is `{deleted: true}`). No accounts yet: the
  browser on the computer VibeCut runs on is signed in; a request relayed
  from elsewhere (X-Forwarded-For etc.) or `VIBECUT_PUBLIC=1` is signed out,
  sees "You need to log in to save your resources" with Log in and "No
  account? Create one now" (her words), and every Save opens it;
  `VIBECUT_SIGNIN_URL` / `VIBECUT_SIGNUP_URL` are where they will go. The
  app's `?visitor` (header `x-vibecut-visitor`, can only take rights away)
  shows the owner what a visitor sees. `tests/test_resources.py`.
- **Your profile, after an export** (sarah, 2026-10-14, draft #26 never
  merged; rebuilt 2026-10-19: "there isnt any page for me to build my own
  profile after my export"; `ProfileAsk.tsx`, `/api/profile/start`,
  `/api/profile/skip`, `defaults.asked` / `answer`). Closing Export after a
  video came out asks once: the email (the only typing; on the profile
  page's profile, never sent anywhere) and name, then taps preset to what
  that video used: Vlogs / Lessons, Quick / Steady / Calm, the transition for
  every cut, the caption style (Soft, a template, or No captions), plus "Keep
  this video's looks in My resources" for what it has. Not now = never asked
  again. The picks are defaults keys (`makes`, `pace`, `transition`,
  `captions` "off", `caption_template`): `/api/brief/auto` takes the pace
  ("…, as in your profile.") and, for lessons, captions "transcribe"; after
  Make (and on a chosen story) `_from_profile` adds one undoable "From your
  profile" turn: no captions, or a lesson's subtitles in place of Make's
  lines, the transition at every cut, on a chosen story the caption style.
  Once made, Frames keeps it up (the pace, the Captions switch, a transition
  for every cut); a skip learns nothing. The profile page's "How your videos
  start" saves each tap. Logged out (`?visitor`) it asks for an account
  instead, once per browser. `tests/test_profile_start.py`.
- **Graphic animations** (sarah, 2026-10-19: "make it an extra tool on the
  right called graphic animations"; `web/backend/graphics.py`,
  `web/frontend/src/graphicDraw.ts`, `Graphics.tsx`, the inspector's
  Graphic animations tab). Ten pieces drawn in code over her own frames,
  opt-in, free: Title card, Chapter opener, Route map, Place pin, Camcorder,
  Clock, Beat sticker, Sparkles, Circle it, Progress bar. They are board
  `graphics` (`add_graphic` / `edit_graphic` / `drop_graphic`, anchored like
  overlays, undone like any turn), kept apart from captions so the Captions
  switch, caption checks and the writer never touch them. Words come only
  from what the edit knows (name, days, part titles, places, recording
  time); the beat, camcorder clock, clock time and route are derived per
  request (`graphics.public`), and a piece with nothing true to show says
  why (`can`); the clock with no recording time shows no time. Editable:
  words, colour (muted swatches), sticker, length, `size` (0.4–3, apart
  from `place`), dragged on the picture like a caption (camcorder and
  progress are frame-wide). One function draws preview, tab tiles and
  export: each piece is a pure function of time; the export renders them
  as an under-layer beneath the captions (`renderSchedule` `under`, one PNG
  per run of equal `graphicsKey`s). Thin type and readouts use Montserrat
  400/500 and Playfair 400 italic (OFL, in `public/fonts`, added by
  FontFace so fonts.css is untouched). Saved to My resources as kind
  `graphic`. Each piece was scored by a separate reviewer pass (7 areas,
  redone below 7.5). Sizes, timings and colours are priors.
  `tests/test_graphics.py`, `graphicDraw.test.ts` (safe area, frame
  bounds, purity, export keys).
- **Every cut checked** (`cutgrammar/joins.py`, `web/backend/seams.py`;
  research 08 P2). Report only: per cut, brightness jump, colour change
  (best-frame proxy), same view again, energy step, loudness step, going
  back in time, shot size — each a Finding declared in `grammar.NEEDS`,
  from the index (no pixel decode). Story marks rough cuts (! + numbers on
  hover); each turn gets a second look in chat. The place axis now gives a
  return visit its own chapter in day order. Thresholds are priors.
  **Check my cut** (2026-10-24, the user: "timestamped notes on my own
  hand edit, from the cut checks you already have, report only"; idea from
  Eddie AI's feedback mode, `design/research/09-competitors-2026-10.md`;
  `web/backend/cutnotes.py`, `POST /api/cutnotes`, `CutNotes.tsx` under
  Smoother cuts in the Edit tab with nothing clicked). The same per-cut
  findings (`seams.check`, now carrying each finding's numbers as `data`)
  and caption findings (`overlays.check`), as a list in edit order: the
  time, "Cut from shot 4 to 5" or the caption's first words, what's off in
  plain words with the numbers ("much brighter at the cut (40 → 200 on a
  0–255 scale)"), and "Usually helps: …" in words only. A click plays
  through the cut from 1.5 s before (a caption: shows it); after any later
  turn the list says the edit changed since. Checks the media couldn't
  support are listed as not checked; the report says its limits are first
  guesses. Never an op, no model, free; each check is a `cut_check` event
  on the project (turn, notes, which checks fired) for calibration. Works
  on any edit, hand-cut or made. `tests/test_cutnotes.py` (a bright shot
  gives one note at its cut with the built-in numbers, an evenly lit one
  none, moving the shot moves the note; captions; through the API, nothing
  changes).
- **Smoother cuts** (`web/backend/smooth.py`, P3-1/P3-2). Only when asked,
  one undoable turn: beam search over join roughness + filming-order
  penalty inside a part (move_shot), and window nudges ≤2 s onto movement,
  never onto a word (trim). Never runs by default on a hand-cut edit — that
  would be cutfix. The one exception (2026-10-19, vlog.py step 5): the
  nudge alone runs after a vlog *Make*, as its own turn, because that edit
  is the machine's to begin with.
- **Looks** (`web/backend/looks.py`, `looks/*.json`, P3-3). The spec's 7
  vibes as dated records: type + motion, and since 2026-10-10 (plan step 1)
  the picture too — `grade` (relative to the footage: warmth, black floor /
  ceiling, sat and contrast ratios, split; `grade_target` → `grade.Look` →
  a .cube under `$VIBECUT_CACHE/looks/`, fitted on the story's thumbnails,
  export-only), `joins` (a transition policy, honoured by preview and
  export alike) and, for Hype / Playful, `camera` (Remix's push, export-only).
  `looks.picture(board, px)` is the one place the board's `style` is read
  for rendering (`app._style`): a borrowed reference's own look / joins win,
  the look fills what's empty; with no pixels the grade is `pending` so the
  Export dialog can say it's coming. Texture, sounds and music stay
  `not_yet`. All grade / join / camera numbers are priors; the export round
  trip in `tests/test_bed.py` shows the Cozy file comes out warmer.
  `set_look` (chat too) keeps what was set by hand and
  shows it; the profile's saved style is a default, not a choice.
  `overlayDraw.ts` reads the look's curve, entrance time, stepping, stagger,
  slam/card entrances, case and tracking; beat lock moves words onto a beat
  ≤0.25 s away. `overlayLooks.test.ts` checks every look keeps every word in
  the safe area on every intro frame. Tests: `test_joins.py`,
  `test_axes.py`, `test_smooth.py`, `test_looks.py`.
- **Joins you can see while playing** (P4; `web/frontend/src/joinView.ts`,
  `transport.ts`, `Player.tsx`). The player has two `<video>`s: the next
  shot is loaded and parked on its first frame before the cut, so a cut is
  a swap, not a seek (no black flash; `hold.ts` is only the fallback). A
  dissolve plays both over the export's own overlap window
  (`export.plan_transitions`, sent in `session.mix.transitions`), dips and
  flashes are a colour veil at the same opacity as the export's fade, and
  cinematic bars are drawn. The grade (LUT) still appears only in export.

- **Caption and transition templates** (sarah, 2026-10-15: "build";
  mockups in the project's `templates/` folder). Opt-in: nothing changes
  until picked. Click a caption → the bottom bar's **Style** (8 templates,
  `overlays.TEMPLATES`: outlined = her own hand edit, serif + black edge +
  the time on its own line; bold, label, highlight, handwritten, tape, pop,
  quiet) and **Animation** (6 entrances, `overlays.ENTERS`: fade, pop,
  slide, stamp, type, word). Both are `overlay_style` fields (`template`,
  `enter`; None = the look's own), one per video, kept when the look
  changes, drawn by `overlayDraw.ts` (TEMPLATES, motionFor) for preview and
  export alike; Mac system fonts only. Click the dot between two shots →
  **transitions** (`transitions.py`, `set_transition {shot | all, kind,
  dur}`): cut, fade, dip, flash, zoom through, slide up, blur, light leak;
  board `picture_joins` / `picture_all`, folded into the style's
  transitions policy (`at`) that `export.plan_transitions` reads. The four
  new ones are ffmpeg xfades over footage past the cut (light leak a custom
  expression), else a cut, said at export and in the bar; the player draws
  the same with CSS (`joinView.blendLook`; its blur is a plain blur where
  ffmpeg's hblur smears sideways). Tiles move the way the result will.
  Tests: `test_transitions.py` (each blend really at its cut, centred,
  length kept, all different), `test_caption_templates.py`,
  `overlayTemplates.test.ts` (safe area every intro frame, every template ×
  entrance). Sizes, durations and the glow are priors.
  **Caption words and colour in the Captions tab** (sarah, 2026-10-17): a
  clicked caption shows its words in one box, lines as on the picture (the
  place name is its first line; sarah 2026-10-18), See it play,
  Delete; with none clicked, Off/On and "Add a caption at the playhead".
  **Typed on the picture** (sarah, 2026-10-18: "edit the words on screen"):
  clicking a picked caption again (or Edit words, or a double-click) opens a
  box right where it's drawn, same lines as the tab (`captionWords.ts`);
  click away or Cmd/Ctrl+Enter = one undoable edit, Escape = no change.
  The box wears the caption's own look while typing (`overlayDraw.typeLook`:
  each line's font, size, colour, edge, band; the place name small above).
  **Soft is the default caption** (sarah, 2026-10-19, after a look at how
  day-in-my-life vlogs and Shorts caption): no template = `softTpl` in
  overlayDraw: the look's lettering at its regular weight, lowercase, small
  (0.05 of the short side), a soft shadow, low left; the place name in the
  same case above. A picked template keeps the centre. The Style tab calls
  it Soft. The words themselves (a thought or what's happening, never a
  scene description) belong to the story writer, not here.
  **Colour** is `overlay_style.text_color` (None = automatic, ink.py picks
  one that reads; never set by a look): a picked colour is kept as picked,
  ink.py only adds a glow where it would blend in; a template takes it as
  its letters (edge flips white under dark ones) or as its box / band.
- **Video effects** (sarah, 2026-10-18: "more effects ... i want the popular
  ones"; `web/backend/effects.py`, `web/frontend/src/effectView.ts`,
  `Effects.tsx`). 14 of the effects short-form edits use most, opt-in, one
  per shot: Shake, Zoom in / out, Pulse, Flash, Strobe, Blur in, Glow, VHS,
  Glitch, Film grain, Old film, Vignette, Disco. On the entry as
  `set_shot {effect, effect_amount}` (Strength 25–200%), kept through a cut;
  "Use for every shot" is one turn of set_shots. Each is a function of time
  into the shot: export runs `effects.chain` after `_fit` (ffmpeg crop /
  zoompan / blend / gblur / rgbashift / noise / vignette / hue), the player
  draws the same numbers with CSS + two SVG filters (`FxDefs`) and an overlay
  for tints and grain (`transport.paint`). Built from the filmed frames only.
  Every number is a prior. `tests/test_effects.py`, `effectView.test.ts`.
- **polish/** (`polish/`, `web/backend/polish_api.py`, `Polish.tsx`,
  `polishDraw.ts`; page `#polish`). Assisting an edit that is already cut:
  input is one finished video, never raw clips; no auto-editing, no
  storyboard, no selection, no music, no export, no login. One interaction:
  click the picture → anchor `{t on a frame, x, y in the picture, shot}` →
  one sentence → ops on caption/effect layers (turn log, computed diff,
  undo by replay, like `board.py`). Sentences are read by rules first
  (`parse.py`: 写上「…」 / boom / 大一点 小一点 / 删掉 / 改成 / 用我的配方 /
  存成配方); the model is asked only when no rule matches (key only).
  Captions use the creator's **recipe** (`recipe.py`, `$VIBECUT_CACHE/
  polish/recipes.json`): saved *from* a tuned caption, first = default.
  Layout (`layout.py`) is decided once, server-side, and the browser draws
  exactly those lines in that box (shrinking only if its real font is
  wider): off every face over the caption's span (moves above / below /
  top and says so), inside the safe area, no one-character last line.
  Effects snap to a movement onset (±0.4 s, frame-accurate from one
  `media.load()` of the finished video) or a beat (±0.25 s). Face boxes
  come from on-device Vision over the index's samples (macOS only);
  elsewhere the face rule reports `pending`, never "clear". Tests:
  `tests/test_polish.py`, `test_polish_api.py` (face in the lower third vs
  the top, through the API), `polishDraw.test.ts`. Windows and margins are
  priors.
- **Fonts: openly licensed, or already on the creator's machine.** A system
  family, a font file the creator points at (served back only if a saved
  recipe names it), or one of the caption fonts that ship with the app
  (below). Only OFL / Apache faces are ever bundled, each with its licence
  beside it; never a proprietary face (CapCut's, TikTok's or Instagram's own
  app fonts), never a look-alike pulled from a reference. **Recognising a
  font in a reference image or video is not a licence to render it** —
  naming it is fine, drawing with it needs the creator's own licensed copy.
  **Caption fonts** (sarah, 2026-10-18: "i want the popular ones to all be in
  our app"; `captionFonts.ts`, `public/fonts/`, `overlays.TYPEFACES`): 15
  faces popular in CapCut / TikTok / Reels captions (TikTok Sans, Montserrat,
  Poppins, Bebas Neue, Anton, Archivo Black, Luckiest Guy, Bangers, Fredoka,
  Permanent Marker, Caveat, Pacifico, Lobster, Playfair Display, Courier
  Prime), latin subsets, one weight each, from Fontsource (~850 KB), family
  names prefixed "VC " so a Mac's own copy never stands in. Picked in the
  Captions tab as `overlay_style.typeface` (None = the template's or look's
  own), one font per video like the colour; a template keeps its edge and
  backing around it; drawn by `overlayDraw` so preview, typing box and export
  match. Per-font size factors are eyeballed. `captionFonts.test.ts`.
  **Caption text panel** (sarah, 2026-10-18: "pick different fonts, colors,
  outlining, shadows, backgrounds and adjust how thick they are"; plain
  controls, no video behind them; word art shown on a frame). Captions tab:
  Font, Colour, Outline (on/off, colour, thickness), Shadow (colour,
  strength, softness, distance), Background (colour, opacity, roundness),
  Boldness (a stroke in the letters' own colour), then **Word art** (the
  templates, plus Neon, Glow, Gradient, 3D, Retro drop). `overlay_style`
  fields `outline` / `shadow` / `backdrop` / `thick` (`overlays.DRESS`; None
  = the template's own, width or opacity 0 = none); `overlayDraw.dress` lays
  them over the template, and a caption with no template but something set
  is drawn the template way from the look's lettering. Picking a word art
  starts it fresh (clears the four). One look for every caption, undoable,
  same drawing in preview, typing box and export. `overlayDress.test.ts`.

## The rule that matters most

**Do not build the fixer until the thresholds are calibrated against real
videos.** Every threshold in `grammar.py` is currently a guess. A fixer
driven by guessed thresholds will confidently make footage worse, and it
will be hard to tell that it has.

Calibration means: run the analyser over ~20 videos known to be well cut
and ~20 that aren't, and derive each threshold from that distribution.

The harness for that exists since 2026-10-11: `python calibrate.py --good …
--bad …` (files, folders, path lists, or links through yt-dlp;
`cutgrammar/calibrate.py`). It measures the first 90 s of each with
`grammar.analyze`, lays the two distributions side by side per finding,
proposes the cut point with the best balanced accuracy, shows the current
guess beside it, and writes `design/research/calibration/<date>.{json,md}`.
It changes nothing: a person moves the constant in `grammar.py` and cites
the record. Under 8 videos a side it says *thin*. `tests/test_calibrate.py`.

## Architecture

Pixels are touched exactly once. `media.load()` decodes to 48×27 RGB at
native frame rate plus mono 16 kHz audio; every later stage reads those
small arrays, never the original file. This is what makes iterating on the
rules cheap, and it is not negotiable — a change that re-decodes video per
rule is a bug even if it passes.

`media.load_index()` is the one other entry point: keyframes only (~1/s on
iPhone), decoded once at 384×216 on the hardware decoder, with the 48×27
grid derived in memory. It exists because full-rate decode of 4K60 HEVC is
~18s per 100s of footage — too slow to index a shoot. Grammar rules still
use `load()`; index mode is for shots, thumbnails (`bestframe.py`) and
storyboards, where ±1s cut accuracy is fine.

```
media.load()   ffprobe metadata + tiny frames + audio
  └ shots.detect()      histogram distance, adaptive threshold
      └ features.*      motion, spectral-flux novelty, brightness
          └ grammar.*   rules, each returning a number and a verdict
              └ report  terminal / JSON
```

## How to validate

**A metric that fires on bad footage proves nothing.** It has to *move*
when the edit improves. `tests/test_discriminates.py` is the pattern:
build two fixtures that differ in exactly one respect, assert the metric
separates them and recovers the magnitude that was built in.

Every new rule ships with a discrimination test or it does not ship.

## Conventions

- Python 3.10+, numpy only. ffmpeg/ffprobe via subprocess.
- New rules go in `grammar.py` as `check_*(media, shots) -> list[Finding]`
  and get registered in `analyze()`.
- Findings carry a raw `value` and a `verdict` (`ok` / `warn` / `bad`, or
  `pending` when the reading can't support a judgement — see
  `evidence.py`). Never a verdict without the number behind it. A new rule
  declares what it needs in `grammar.NEEDS`.
- Comments explain *why a rule exists in editing terms*, not what the
  code does.

## Non-goals

- **No generative video.** The viewer sees only frames the creator
  actually filmed. This is a positioning decision, not a technical limit:
  it is what separates this from every AI video tool, and it keeps
  inference cost sane.
- **No web UI** until the measurements are trusted. An earlier prototype
  (FRAME) burned its effort on a timeline editor before the core worked.
- **No transcript dependency.** ChatCut and Descript own the talking-head
  case because transcript-as-timeline works there. Vlogs have no
  transcript spine; that absence is the whole opening.
  *Amended (user decision):* the default path still needs no transcript.
  A creator who brings their **own** narration (SRT or script) gets one
  extra proposal that follows it — the voice sets time, the words pick
  footage by label, unmatched lines stay as listed gaps. Nothing is
  transcribed, no speech model is added, and no other path depends on it.
  Don't grow it into transcript-as-timeline editing.
  *Amended again (user decision, 2026-09-25):* a **talking-head mode (口播精剪)**
  may transcribe — opt-in, never on the default path. Speech-to-text runs
  on this Mac only (Apple SpeechTranscriber via `web/backend/speech/
  vibespeech.swift`; no Python speech model, audio never leaves). It cuts
  pauses to a breath, earlier takes of repeated sentences, stumbles and
  fillers, shows every cut at a gate, then becomes a normal storyboard with
  subtitle overlays (`web/backend/talk.py`). With a key, only the transcript
  *text* goes to Claude to judge retakes. It still isn't a transcript
  editor: the words are reviewed, not typed into.

## Known limits (upgrade path, in order)

1. Thresholds are guesses — calibrate first. First record 2026-10-11
   (`design/research/calibration/2026-10-11.md`, 18 vs 18): rhythm_cv,
   cut_on_motion and jl_cuts moved; the bad side was one shoot's exports,
   so it counts as "better than a guess", not done. Everything else
   (joins, trim, reject, looks, bed, tempo) is still a prior.
2. Motion is frame-differencing, not optical flow: no direction, so the
   180° rule can't be checked.
3. No face detection: shot size and subtitle-over-face unmeasured.
4. No beat tracking: cut-to-music alignment unmeasured.
5. Shot detection misses dissolves and fades (TransNetV2 is the fix).
