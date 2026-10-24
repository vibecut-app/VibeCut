# web/ — the VibeCut app

One application, one path: **Projects → Footage → Brief → Rough cut →
Story (or Frames) → Export.** Drop a folder of clips, say in one line what
the video is, approve what the rough cut leaves out, start from one of three
proposals, then shape it by talking or by hand. Every change is a turn that
shows its diff and can be undone. Footage, thumbnails and the index never
leave this machine; with a key set, only the storyboard's *text* goes to
Claude to be turned into operations.

```bash
# from the repo root
pip install -r requirements.txt -r web/requirements.txt
(cd web/frontend && npm install && npm run build)
python -m web.backend            # → http://localhost:8765
```

Chat edits need an Anthropic key: put `ANTHROPIC_API_KEY=...` in
`web/.env` (gitignored) or export it. Without one, the whole path still
works — proposals, the rough cut, direct edits, words on screen, sound,
export — only *typed* edits are off, and the app says so.

For UI work, run `npm run dev` in `web/frontend` as well (Vite on :5173,
proxying `/api` to the backend).

Needs macOS for the full experience: the hardware decoder (VideoToolbox),
the on-device Vision helper (labels, faces) and the speech helper (talking
to camera). Elsewhere it falls back to software decode and colour-based
subject grouping, and the home screen lists what this machine can and
cannot do.

## Screens

| Route | Screen | What it is |
| --- | --- | --- |
| `#/` | **Projects** | Every video you're making: cover, name, clips, length, stage, last edited. New video. Secondary: *Polish a finished video*, your profile. |
| `#/p/<id>` | **Workspace** | One project. The header carries the stepper — Footage · Brief · Rough cut · Story — and the stage in the middle is *derived* from the project's state, never set by hand; passed steps can be looked at again. |
| `#/p/<id>/frames` | **Frames** | The same edit, frame-accurate: shelf, player, timeline, keyboard. A view of the Story stage, not a step. |
| `#/profile` | **Your profile** | Name and handle (name tags, end cards), the default font / colour / placement of words on screen, bookmarks. Stored in this browser. |
| `#/polish` | **Polish** | A separate tool for a video that is already cut: point at a moment, say what to put there. |

The stages:

1. **Footage** — drop clips or a folder; per-file reading status; files that
   couldn't be read, with *Try again*; the clip grid. Nothing is copied,
   moved or changed (files the locator can't find on disk are copied into
   the cache). The one action: *What's this video? →*.
2. **Brief** — since 2026-10-10 two picks in one popup: the frame (Short ·
   vertical under 1½ min, Vlog · vertical, Wide · 16:9; the footage's
   upright share suggests one) and the look (the seven below; Cozy by
   default). "Make my video" reads the rest from the clips: what it is,
   the length the frame asks for, the pace, captions on. The frame can be
   changed in Frames (a chip; the stage and the export follow); the look
   under Captions. Before that it was one line, then the style questions (length, pace, opening,
   focus). Opt-in side doors: *Follow my voiceover* (an SRT or script
   becomes a fourth proposal), *Talking to camera* (macOS).
3. **Rough cut** — the gate: what would be thrown away and trimmed, with
   reasons and what each reason rests on; override anything; *Looks right —
   continue*. Nothing is built until you do.
4. **Story** — three proposals; start from one; parts and shots; chat on the
   left (ops only, never a regeneration); on the right the player, words on
   screen and music. *Reference* in the header borrows a video's feel.
   *More ▾* holds the side tools (talking to camera, build a short from
   reels, keyboard, polish, start over).
5. **Export** — one MP4, rendered from the same plan the preview plays;
   every export is recorded on the project and listed in the dialog.

## Projects and persistence

A project is a small record on disk (`$VIBECUT_CACHE/projects/<id>.json`,
`web/backend/projects.py`): which files it holds (by index id — the
per-file cache does the heavy lifting), the turn log the storyboard is
replayed from, where the workflow stands, the rough-cut overrides, the
brief, this video's confirmed preferences, and its exports. It is written
after every change (a middleware saves after each successful mutating
request, and the import job saves when it lands) and read back when the
project is opened, so a restart changes nothing. The original media is
only ever read. If a file has moved since, the footage screen says so.

`tests/test_projects.py` walks the whole path through the API and checks
that a reopened project has the identical board, timeline, log, brief and
gate, that undo still works afterwards, and that deleting a project touches
no clip and no export.

## Your profile

Open it from the avatar. Name, handle, what you make, where you share; the
default font, accent colour and caption placement for words on screen;
taste (feeling, pacing, things to avoid); up to 10 reference bookmarks.
Saved in this browser's localStorage; no account. The editor reads the
name, handle, font, colour and caption placement (words on screen, name
tags, end cards). Taste and bookmarks are kept for you and not yet read by
the editor — the page says so.

## Watch, then fine-tune

A made video opens as the video: full-size, playing, with four chips
under it — the music, the length, the look, the words — and Download. One
link, *Fine-tune*, opens the editor underneath: every shot, caption, join
and sound, with undo. A video you cut by hand opens in the editor.

## Make my video

Since 2026-10-17 the two picks run one pipeline — the same one a Remix
uses — and land as the video, playing: the strongest moments of the shoot
(a hook first), each a whole number of beats of a track picked for the
footage's pace and the edit's arc, the look, a title and a line per stop.
A short is cut like a reel (under a second a shot, a minute at most) and
rides on the music; a vlog breathes and keeps its own sound up front. The
dialog shows where it is (choosing, music, words); the result is one turn,
so Undo takes it all back, and the three stories are still there under
Other stories. Music is fetched the moment the clips are read, so by the
time you press Make it's usually waiting.

## Cut it like: the viral library

A vibe is what a set of reels has in common: twenty day-in-my-life shorts
that did well give one record (shot length and arc, hook, tempo, where the
words sit and how long, how the ending lands), built with
`python -m web.backend.vibes --niche "day in my life" --links links.txt`.
The Setup dialog lists the library's vibes and your own learnt reels under
*Cut it like*; pick one and Make cuts to its fingerprint instead of the
frame's own pace. Only numbers are kept from a reel, and the record names
its sources.

## The front door: a short like a reel you love

On the home page, under the clips you picked, there is one more line:
*Make it like a reel you love*. Paste one to three links (TikTok, Reels,
Shorts, or files on this Mac) and the button becomes *Make a short like
it*. The video is created, the clips are read, and a Remix starts by
itself with those reels: their pace, length, how they hold the first shot
and the feel of their music — never their frames. When it lands it *is* the
story: the gate is passed in your name, the brief carries the reels' frame
and length, and the edit opens in Frames with music under it, editable like
any other cut. With an API key, Claude judges the picked moments from one
frame each (the rules' picks plus two runners-up a session) and the plan
says so; without one, the rules choose.

## Reference: make it feel like a video you love

**Reference** in the header (or *Fine-tune* after a style is on): paste a
link (needs `yt-dlp`) or drop a video whose editing you love. VibeCut reads
it once at 48×27 and learns its **pacing** (shot length and how it changes
through the video), **transitions** (hard cut / dissolve / dip to black /
white flash / fades), whether it **cuts on the beat**, its **colour** (tone
curve, white balance, split toning, saturation), its **frame** (cinematic
bars) and its **music feel** (energy arc, tempo). Each trait says what it
was measured from.

Since 2026-10-18 a reference also teaches its **ideas**: where it puts
words and for how long (read from its frames by the Mac's Vision; "not
checked" elsewhere), how it opens (first cut, on action or still) and how
it ends (last shot held, fade). Make my video with a reel puts your
captions where the reel's were, holds them as long, skips the title when
the reel's words start late, makes a wordless video from a wordless reel,
and holds your ending as many beats as the reel's last shot.

Tick what to borrow. Pacing and beat retime your shots (a shot is never
held longer than it was filmed; voiceover parts keep their timing). The
colour becomes one LUT fitted to *your* shots, previewed before/after, with
colour shifts capped so the reference's subject matter doesn't tint your
footage. Grade, transitions and bars are rendered in the export only, not
in the preview. Music is never copied; your own tracks with the same feel
are suggested instead. It's all one turn, and Undo removes it. Learnt styles
are kept in `$VIBECUT_CACHE/references/`, where Forget also deletes a
downloaded copy. The same dialog links to **Build a short from reference
reels** (Remix): the shelf becomes a finished short in the reels' style,
which then lands on the storyboard like any other cut.

## Layout: two levels

**Story** (default, where people live): the edit as parts and shots. Before
a story is chosen, the centre shows the three options side by side (parts,
thumbnails, a one-line explanation, a Watch button). After choosing: one
row per part — drag a row to move it, click a part's title for Rename /
Watch / Move / Remove / "Fine-tune in Frames", click a shot for Watch / Swap
/ Remove. No timecodes, no tracks. The player stays on the right; chat on
the left. Below about 1100 px the chat becomes a drawer and the player
stacks under the story.

**Frames** (drill-down, one click on the switch in the header or from a
part): the shelf, player and the precise timeline with its keyboard.
Clicking a shot or an empty space on the timeline shows what can be done to
it, beside it.

Select, then act: nothing asks you to pick a tool first. Every change shows
an Undo right away. Words say what happens ("Remove — the rest moves up",
"Remove — leave empty space"), not editor terms.

## Pipeline

```
drop ─ locate.py      find the files on disk by name + size + mtime
                      (Spotlight, then folder name under ~/Movies etc.);
                      upload into the cache only what can't be found
     ─ indexer.py     process pool, one clip per worker:
                        media.load_index   keyframes, HW decode, one pass
                        shots.detect       shot boundaries
                        bestframe          best frame → thumbnail, quality
     ─ vision.py      on-device Apple Vision over the thumbnails:
                      labels, faces, aesthetics score, feature-print
     ─ storyboard.py  three axes, no LLM:
                        time     sessions split on 45-min gaps / days
                        place    GPS single-linkage, radius chosen adaptively
                        subject  on-camera shots, then k-means on Vision
                                 feature-prints, named by distinctive labels
```

The direction line is read by keyword matching against Vision labels
("food" → food, dessert, restaurant, …). The reply says which words were
used and which were ignored; there is no language model. Matched shots
are highlighted everywhere and lead the subject storyboard.

Index results are cached per file under `~/.cache/vibecut`
(`VIBECUT_CACHE` to override), so dropping the same folder again is instant.
The project record (which files, the turn log, the gate, the brief) is
saved beside it under `projects/`, so a restart reopens the last project
as it was left.

## The rough cut: throwing away, with one human gate

Editing is subtractive: most of every clip is thrown away. After indexing,
two stages run on the whole shoot, then everything stops at one gate.

1. **Reject** (`cutgrammar/reject.py`): whole clips nobody would use — lens
   cap / pocket, murky-dark or blurred end to end, shaking throughout, a
   two-second mis-tap, a second take of the same view (kept: the better one).
   Each has a plain reason ("全片模糊", "和 IMG_4471 几乎一样"). A reason
about movement ("全程剧烈晃动") was judged from about one frame a second,
so it is marked "judged from a few frames, play it to be sure". Talking
   clips are never dropped as duplicates — they may say different things —
   only flagged as possible retakes.
2. **Trim** (`cutgrammar/trim.py`): the best window inside each kept shot.
   Per-second scores (quality, steadiness, subject in frame, speech) from
   `cutgrammar/signals.py`; exact max-sum sliding window; windows that start
   mid-pan, mid-word or on a subject leaving frame are penalised, the start
   twice as much as the end. Cut points are moved out of words. Talking clips
   only lose unusable ends: without a transcript nothing can know which
   sentences matter.

**The gate** (`web/backend/workflow.py`, adapted from cut-motion — see
NOTICE): the Story view shows "47 个片段 → 保留 31 → 剪出 3:22（原始 11:24）",
every thrown-away clip with its reason, every trim as a bar over the whole
clip. Use it anyway / Throw away / Shorter / Longer / Keep the whole clip,
each undoable. Nothing (storyboards, chat edits) proceeds until you press
"Looks right — continue". New clips after that reopen the gate. Nothing is
deleted: rejects stay on the shelf with their reason and a "Use it" button;
trims are in/out points and the full source stays reachable.

Signals are per second (the index samples keyframes, ~1 s). Subject presence
is spectral-residual saliency plus on-device Vision faces per second.

## The conversation edits; it never regenerates

`board.py` holds the working storyboard as a pure function of a turn log.
Each turn is a list of operations — `move_beat`, `drop_beat`, `drop_shot`,
`swap_shot`, `add_shot`, `move_shot`, `retitle_beat`, `set_pace`,
`open_with`, `end_with`, `choose_option` — applied by deterministic code.

- `llm.py` gives Claude (`claude-opus-5`, JSON-schema-constrained output) a
  text rendering of the storyboard and shelf, and gets back a reply, at most
  one clarifying question with choices, an optional new direction, and
  operations. It never returns a storyboard.
- Timeline drags, deletes and Apply are the same operations, in the same
  log, with the same undo.
- Undo any turn = replay the log without it. Ops that depended on it are
  skipped and reported, never guessed. Decisions made at apply time (which
  shelf shot a swap picked, what a proposal looked like when chosen) are
  recorded into the op, so replay is exact.
- The diff (removed / added / moved / trimmed / renamed) is computed from
  before/after boards, not from what the model claims it did.
- Setting a new direction rebuilds the three *proposals* only; the working
  storyboard is untouched.

`tests/test_board.py` pins this down without a model: the two ops for the
acceptance request change the opening and remove the market, and every
other beat comes out byte-identical.

## Follow your voiceover (opt-in)

If you've recorded narration — or written it — paste its subtitles (.srt)
or the script under **Follow my voiceover…**, before or after the three
proposals appear. A fourth proposal, *Follow the voiceover*, comes first:
one part per spoken line (`backend/voiceover.py`).

- The voice sets the time: a line holds the screen until the next begins,
  so the edit is exactly as long as the narration.
- What a line names (food, the sea, a temple, people, 市场, 海边, 寺…)
  recalls shots by their on-device labels; which ones are used is decided
  by how well they're made, never by the label's confidence. A long line
  is split over a few shots; the same clip never plays twice in a row.
- A line nothing on the shelf shows — or an abstract one ("I finally felt
  free") — is left as an **empty stretch of its length** and listed under
  "Lines with nothing to show", with why. It is not covered with an
  unrelated pretty shot. Fill it by dropping a shot there, or film one.
- Timing is labelled honestly: subtitles give *estimated* timing (never
  checked against the recording), a script gives *text only* (lengths from
  word counts, ~15% off). Nothing claims the picture is locked to the voice.

The voiceover is a turn in the log like any other: Undo removes it. A new
description of the video keeps it. Once chosen, the story is edited by
chat and timeline exactly as before. The narration itself is not played or
mixed — there's no audio track for it yet.

## What follows you to the next video

The frame, the look and the music switch you picked last time are
preselected next time, marked *as last time*, with the footage's own
suggestion still shown. A look you choose under Captions, a caption style
or entrance, and the frame chip follow too. Nothing is applied without the
dialog showing it; everything is one file in the cache
(`settings.json`). Taste and rules reaching the edit itself come later.

With `SUPABASE_URL` and `SUPABASE_ANON_KEY` in `web/.env`, those defaults,
your confirmed rules, your profile and the styles you've learnt from reels
are mirrored to Supabase (`supabase/migrations/0001_preferences.sql`), so
they're there on your next Mac. Footage, the index and exports never are.
Offline, nothing changes; the next change catches up.

## What your edits teach — only when you say so

Every edit (chat or timeline) can be sorted with **Remember…** under it
(`backend/preferences.py`): *Just here*, *For this video*, *Every video*,
*Privacy or rights*, or *Don't learn*. Leaving it alone teaches nothing.
Only *For this video* and *Every video* are ever used again, and *Every
video* needs the rule, when it applies, and when it doesn't. Saying "from
now on" / "以后也这样" only suggests *Every video*; you still confirm it.
An undone edit can't be remembered — its before and after are gone.

Confirmed rules are listed at the top of the chat (**Remembered**) and are
sent to the chat model with each message; candidates never are. *Only this
video* narrows an every-video rule; *Forget* retires it. Both keep the old
record with who changed it and when. Every-video rules persist in
`~/.cache/vibecut/preferences.json`; this-video rules go when the shelf is
cleared.

## Music by default, cuts on its beat

Choosing a story puts a bed under it (`backend/bed.py`), as one undoable
turn that lands when the pick is ready — a few seconds from your own
folder, up to a minute online:

- **The track** comes from your music folder when one is set, else from
  Openverse (Jamendo / Freesound, CC0 / BY / BY-SA only; the credit line is
  written next to the export). It's scored like a Remix — tempo in the
  range the footage's pace asks for, energy shape against the edit's own
  arc, the catalogue's words, continuity — and starts so its drop lands at
  the end of the first shot (8 s in at most).
- **The cuts move onto the beat** (`restyle.retime`, ≤ 0.35 s each). A
  shot where someone talks keeps its window; the music dips under it.
- **The mix**: music at the export's 0.35 under your own sound, faded out
  over the last 2 s. Preview and export play the same bed.
- **Music off** in Frames takes the bed away (one turn; the cuts stay where
  the beat put them); pressing it again finds a track again. A Remix, a
  talking-head cut and a voiceover story don't get one — they bring their
  own, or the voice sets time.

Tempo ranges, moods, the duck and the hook cap are priors. The pick has no
model behind it. `tests/test_bed.py` (storyboard, then through the API).

## Music that fits the storyboard's shape

Under the working storyboard: the top 5 tracks from the creator's own music
folder (set it in that box; mp3/m4a/wav/flac, walked recursively), each with
a play button and a one-line reason built from the curves — or no reason.

`cutgrammar/music.py` does the work, behind a `TrackSource` seam
(`LocalFolderSource` is the only adapter). Each beat gets an energy value
from its shots' motion and cutting rate; each track an RMS energy curve and,
when the pulse is unmistakable, a tempo. Curves are resampled, z-normalised
and correlated over the part of the track that would play (it's assumed to
start with the edit). Tracks shorter than the edit are left out. Features are
cached in `.vibecut-music.json` inside the music folder.

What `tests/test_music.py` shows, and doesn't: rising vs falling separates
by a wide margin (+0.82 vs −0.95), loudness has no effect, and the score is
far above shapeless tracks. But with a 3-beat storyboard the edit's shape is
only a few numbers, so ~1 in 9 random rising curves out-score a clean ramp:
it can tell a build from a fade, not pick the best of many builds.

## A precise timeline without dragging

The timeline is the storyboard laid out in time (`backend/timeline.py`),
with a sorted list of snap targets: shot boundaries (strongest), silence
edges from `features.speech_mask` (10 ms), motion onsets/offsets (only as
precise as the index's keyframes, ±0.5 s — labelled so), and the beat grid (in edit time: a track that starts
at its drop has its beats shifted by that in-point, wrong for every Remix
until 2026-10-10)
of a music track put under the edit with "Use". Word boundaries have a seam
and no source until there's a transcript.

`src/snap.ts` looks targets up by binary search. The threshold is 8 px, so
in seconds it scales with zoom; each type pulls with its own weight; Alt
disables it. The snapped (or approaching) target is drawn and named.

Keys follow NLE convention — press `?` in the app for the full list:
Space, J/K/L shuttle, I/O marks, ←/→ frame, ⇧ second, ⌥ next target,
↑/↓ cut points, B or ⌘K cut (during playback it lands on the nearest target,
allowing for reaction time), Q/W ripple-trim to the playhead, `,`/`.` trim
by a frame (⇧ second, ⌘ music beat), Delete removes the In–Out range or the
selection and closes up (⌥ leaves a gap), ⌘Z undo. The timecode box takes
`21.3`, `0:21.3` or `00:00:21:09` and never snaps.

Every one of these is an operation in the same turn log as chat edits:
`split`, `trim`, `drop_range`, `drop_shot` — addressed by entry key and
source time, never by timeline position, so undoing an earlier turn can't
make a later cut land somewhere else.

Tests: `npm test` in `web/frontend` (snap + timecode), `tests/test_timeline.py`
(targets), `tests/test_board.py` (cut / trim / ripple / gap / range / undo).

**Measured on the real clips (5½-min edit, 67 targets):** with keys and typed
times, all five test cuts landed where aimed. Scrubbing with the mouse at the
default fit zoom (1 px ≈ 0.4 s) snaps on 50% of scrubs and pulls 21% of them
more than 1 s from where you pointed — that is snapping fighting you. At 5×
zoom it's 19% and never more than 1 s. Not tuned; see the report.

## Measured

30 real iPhone 4K HEVC clips (1.4 GB, 7 min 18 s of footage), cold cache,
M5 MacBook, Chrome driving the real UI:

| Step | Time |
| --- | --- |
| Folder picked → 30 clips indexed and thumbnailed | 4.9 s |
| → three storyboards on screen | 5.2 s |

When Spotlight and the folder search both miss, the files are copied over
localhost instead; the same 30 clips took 6.9 s that way.

## Words on screen (titles, labels, captions)

**Words on screen** sits under the player in Story and as a tab beside the
shelf in Frames (`backend/overlays.py`, `src/overlayDraw.ts`). Seven kinds:
title, part label, name tag, caption, date, end card, chapter bar.

- **✦ Add titles for me** fills in only what the edit already knows: the
  title from what you said the video is, a label for each part, a date where
  the filming day changes, one caption per line of your voiceover (on the
  *Follow the voiceover* story), a name tag from your Creator profile over
  the first shot of you talking to camera (after the title, never on top
  of it), and an end card with your handle. A kind with nothing true to say
  is left out, and the reply says why. Suggesting again never replaces
  what's there.
- **Anchored, not placed.** Each overlay hangs off the whole video, its end,
  a part or a shot. Move the part and its label moves; cut the video shorter
  and the end card stays at the end; remove the shot and its name tag goes,
  and the diff says so. Dragging a pill on the timeline's overlay lane (it
  sticks to cuts, ⌥ for exact) re-anchors it to what's under it.
- **One look per video:** font (Clean / Editorial / Rounded), text and
  accent colour, backing (shadow / box / none) and caption position are
  set once for the whole video. Starting values come from your Creator
  profile.
- Per overlay: words, second line, place (3×3 within the safe area; vertical
  video keeps clear of where TikTok/Reels put their buttons), size, how it
  comes in (fade / rise / slide / type on), length, start.
- Every change is an op (`add_overlay`, `edit_overlay`, `drop_overlay`,
  `overlay_style`) in the same turn log as cuts: diffed, undoable, and
  sortable with *Remember…*. With a key set, chat can add or reword them
  too ("put 'Kyoto' on the temple part") — wired and schema-checked, not yet tried
  against the live model.
- **Checks report, never change** (`overlays.check`, each with its number):
  cut off by the end of the video, on screen too briefly to read (15 chars/s
  Latin, 7/s CJK, +0.5 s), two in the same spot at once, more than two on
  screen, and a middle-of-frame overlay over someone talking to camera
  (a warning, judged from one still). Thresholds are guesses, like the rest.

The preview draws with the same function the export uses, over a stage with
the export's aspect ratio, so the player shows what the file will show.

## 口播精剪 · talking to camera (opt-in)

**Talking to camera** (on the Brief screen beside *Follow my voiceover…*,
or under *More ▾*; shown as unavailable with the reason on anything but
macOS 26) is for clips where you talk to camera. Pick 中文 or English, optionally paste your script
(稿子), press **Transcribe & cut**.

1. **Transcribe on this Mac** (`backend/speech.py` → `speech/vibespeech.swift`,
   Apple SpeechTranscriber, macOS 26+). Timed per character in Chinese, per
   word in English; the OS downloads the language model once. Cached per
   clip. `NLTokenizer` gives word boundaries so subtitles don't split words.
2. **Find what to cut** (`backend/talk.py`):
   - **气口 pauses** over 0.45 s are cut down to a breath (0.12 s + 0.15 s).
     The recogniser folds pauses into characters, so each is first shrunk
     to its loudest burst of sound.
   - **重说 retakes**: a sentence said again within the next two loses its
     earlier take — also when only the end of a sentence was repeated.
     Character-pair matching tolerates mishearing (剧子/句子).
   - **卡顿 stumbles** ("我觉得我觉得", restarts at a clause start) and
     **语气词 fillers** (嗯/呃/um/uh).
   - **With a script**: takes of the same line compete and the most complete
     stays; lines you never said are listed; off-script asides are flagged,
     not cut.
   - **With an API key**, the sentences' *text* (never audio) goes to Claude,
     whose judgement replaces the rules' for whole sentences; if it can't be
     reached the rules stand. *Not yet tried against the live model.*
3. **The gate**: the whole transcript, every cut struck through with its
   reason; click to put anything back (or keep a pause whole). Click a
   sentence to hear it.
4. **Use this cut** → one undoable turn: a storyboard of the kept pieces
   (parts split at long pauses) with **subtitles** as caption overlays —
   one line per phrase, broken between words, never starting with 了/的/吗…,
   timed to the cut, appearing instantly. Edit them in Words on screen;
   Export renders them.

Measured: a 31 s TTS talking-head test (5 long pauses, a restart, a
stutter, a filler) → 20.5 s; the exported audio transcribed back contains
every intended word and none of the removed ones.

## The sound holds the edit together

Most of what makes an auto-edit feel like a pile of clips is heard, not
seen: every cut used to cut the sound too. Now the edit's sound is built
once (`backend/audiomix.py`) and both **Watch it all** and **Export** use
that same track, so the preview sounds exactly like the file:

- no join is a raw step (a 15 ms fade hides the click);
- **between parts the place's sound carries on** for half a second under
  the next part (an L cut) — the chip between two parts says so and offers
  *Let the sound flow on*, *Hear the next part first* (a J cut) or *Clean
  break*; chat can do the same ("let the market sound flow into dinner").
  Where the shot wasn't filmed long enough past the cut, the chip says
  "no footage to carry" and it plays as a clean break;
- the music sits at the export's level, ducks where a Remix asked, and is
  part of the storyboard (`set_music`), so it's undoable and a Remix's
  track, in-point, levels and grade survive editing.

The picture is untouched: every shot keeps its frame count.

## Which cuts feel rough, and smoothing them on request

Every cut of the story is checked from the index (`cutgrammar/joins.py`):
a brightness or colour jump, the same view again from another take, a busy
second slammed into a still one, a jump in loudness, the day running
backwards, the same framing of a face. A rough cut gets a **!** between its
shots (the numbers on hover) and colours the chip between parts; after
each change the chat says which cuts it made rougher or fixed. Nothing is
changed by this — it's a report.

**Smoother cuts** (Story header) is the one place it acts, and only when
pressed: it can reorder shots inside a part (parts stay put; the day only
runs backwards if that clearly pays) and slide a shot a second or two so
the cut lands on movement (never on a word). One turn, one Undo; the
weights are first guesses.

## Looks

**Look** (in Words on screen, or "make it cozy" in chat) sets the vibe of
the words for the whole video: Clean, Cozy, Quiet, Cinematic, Film,
Playful, Hype — font, case, colours, backing, and how words move (Cozy's
stepped paper card, Hype's slam, Playful's bounce). Playful and Hype put
words on the music's beat when one is under the edit. Anything you set by
hand is kept and shown ("Your font differs from the look · Use the
look's").

Since 2026-10-10 a look also sets the **picture**: a colour grade and a
join family, so "Cozy" is warm, lifted and dissolves between parts, not
only a paper card for the words. The grade is relative to your footage
("warmer, lifted blacks, a little less colour" on top of what you filmed;
a black floor or ceiling, never an absolute level, and colour shifts
capped so a sunset stays a sunset), fitted to the story's own thumbnails
and rendered in export only — the preview shows the joins (dissolve, dip,
flash, the opening and closing fades) but not the colour. Hype and
Playful add a slow push into every shot, also export-only. A borrowed
reference's own colour and transitions win over the look's; the look
fills in what the reference left empty. Every number in a look's grade,
joins and camera is a prior (`backend/looks/*.json`).

## Seeing the joins while it plays

Watch it all shows the joins the file will have: a borrowed style's
dissolves play both shots across the same overlap window export uses, dips
to black and flashes fade the same way, and cinematic bars are drawn. The
next shot is loaded in a second, hidden player before each cut, so cuts
don't flash black while a new file loads. The borrowed colour grade is
still export-only.

## Polish: point at a moment of a finished video (`#polish`)

For an edit that's already cut. Open the video (it's read once: cuts,
movement, beat — and faces on a Mac), click the picture where you want
something, say it:

- 「这里写上东京第一天」 / `write "Day one"` — words at that moment, in your
  recipe
- 「这里加个 boom」 — a punch-in that starts on the nearest movement (or beat),
  not on the frame you happened to click; it says which
- 「这段字大一点 / 小一点」, 「改成「…」」, 「删掉这条字幕」
- 「把这条字幕存成配方」 — the caption's font, size, colour, stroke, position
  and entrance become your recipe; new words use it. 「用我的配方」 puts it on
  the caption you clicked.

Words never cover a face (they move above it, below it or to the top, and
the change says so), never leave the safe area, and never end on a lonely
character. Every change is listed with Undo. Fonts: your Mac's own, or a
font file you point at — nothing is bundled.

## Export

**Export** (header, or the timeline bar) renders the timeline to one MP4 in
`~/Movies/VibeCut` (`VIBECUT_EXPORTS` to override): 1080p, vertical if most
of the edit was filmed vertically, 30 fps, H.264 (VideoToolbox on a Mac) +
AAC, with the words on screen and the edit's mixed sound (above: joins,
music at 35% faded out over the last 2 s). The original files are only read.

1. The browser draws every *distinct* overlay frame (a title holding still
   is one PNG with a duration) and uploads it with a schedule.
2. Each span is rendered to a frame-exact piece (PCM audio, so joins can't
   drift), joined by stream copy, then overlays and music are composited
   and encoded once. ffmpeg needs no text renderer.

Measured on the 42 real iPhone 4K HEVC clips: a 6:44 vertical edit with 8
overlays exported in 139 s on an M5; an 11 s voiceover edit in 4 s.
`tests/test_export.py` checks frame-exact length, the overlay window to the
frame, and one audio track through silent clips and gaps.

## Share it, and posting to YouTube

After an export the dialog's **Share it** box has Download, Save to Photos,
Show in Finder, Share… (AirDrop / Messages / Mail, where the browser can
hand over a file) and one link each for TikTok, YouTube and Instagram: the
click copies the caption + credit and opens that platform's upload page.
Each platform is checked against the file first (frame, length).
Above them, **Words to post with it** is a first draft from where and when
you filmed (a line, a few hashtags; on YouTube also chapters), yours to
change; the music credit is added when you copy. **Cover** offers a few
frames of the finished video; the one you pick is saved beside it as
"… cover.jpg" for TikTok's and Instagram's cover step, and goes to YouTube
with a post.
A wide export offers **Make a vertical version too** (for TikTok, Reels and
Shorts), a vertical one **Make a wide version too** (for YouTube): the same
edit rendered in the other frame, captions laid out again, shots filmed the
other way cropped to fill it, the crop moved onto the people in each shot
(faces found on the Mac; a shot with nobody in it keeps the middle). Your
project's frame stays as it was.

**Posting to YouTube from VibeCut** ("Or post it to your YouTube channel
from here…") needs a Google Cloud project of your own, once:

1. In the Google Cloud console make a project, and enable **YouTube Data
   API v3** for it.
2. **OAuth consent screen**: user type External, app name VibeCut, your
   e-mail; add the scopes `.../auth/youtube.upload` and
   `.../auth/youtube.readonly`; under **Test users** add the Google account
   that owns your channel. (While the app is in Testing, the sign-in lasts
   7 days; then VibeCut asks you to connect again.)
3. **Credentials → Create credentials → OAuth client ID → Desktop app**.
   No redirect address to fill in: VibeCut listens on 127.0.0.1 for the
   answer, once.
4. Put it in `web/.env` and restart the server:

   ```
   YOUTUBE_CLIENT_ID=….apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=…        # if Google showed one
   ```

Then the first post asks you to sign in with Google (VibeCut asks only to
upload and to see your channel's name); the sign-in stays in this Mac's
Keychain until you press "Use another account". Every post opens a confirm
screen — channel, video, title, description, who can see it (Only me by
default), made for kids? (YouTube asks of every video) — and nothing goes
up until you press **Post to YouTube**; the button carries a single-use
code, so the server refuses a post that didn't come from that screen. The
upload is resumable (Stop between chunks leaves nothing on YouTube); when
it lands you get the video's link and YouTube Studio's, and the privacy
YouTube actually set. `tests/test_youtube.py` runs the whole thing against
a stand-in Google (`tests/fake_google.py`).

## What the launch tracks

One workflow counts: drop a day's clips, make the two picks, watch, export.
After every export the dialog asks one question — *Would you post this?* —
with room for a line. The answer sits on the export's record
(`/api/exports/{n}/verdict`), and `python -m web.backend.launchlog` reads
every project record into the numbers the launch checklist asks for:
completions (an export made without a typed chat edit), successes (a yes),
failures (unreadable files, a music hunt that found nothing, exports judged
not postable, with the words), costs (model calls, render seconds, seconds
spent hunting music) and how much was undone. Nothing is sent anywhere; it
is a file on this Mac.

## Out of scope

Auth, database, collaboration, automatic style learning (edits are only
learned when the creator sorts them — see above), transcription outside
口播精剪 (vlog captions come only from the creator's own subtitles or
script), editing by typing into the transcript, animated graphics
beyond the seven kinds, transitions, colour grading, per-overlay fonts.

## Known limits

- Cut positions inside a clip are keyframe-accurate (±1 s on iPhone).
- The place axis needs GPS; screen recordings and downloads have none, and
  a shoot filmed in one spot has only one place. The card says so.
- The quality score's weights and the storyboard quality floor are guesses,
  same as every cutgrammar threshold. They only decide ranking and what's
  left off a storyboard — nothing is cut out of a file.
