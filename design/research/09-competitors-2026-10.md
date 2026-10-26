# 09 — Competitors, October 2026: what they're good at, what to borrow

2026-10-24. Three web scans (AI editors of your own footage; mass-market
mobile editors; camera-roll auto-movies), mostly vendor docs, press, G2 /
Capterra / app stores and Buffer's hands-on test; Reddit wasn't reachable.
Sentiment claims are thin. "Borrow" means the idea — never code, assets,
fonts or templates (see NOTICE and the font rule in CLAUDE.md). Earlier
work: the Vyra parity matrix (`design/specs/phase1-baseline.md`), how the
glue works in CapCut / Google Photos / Apple / Quik (`08-…`).

## The field in one table

| Product | Best at | Users complain about | Price |
| --- | --- | --- | --- |
| **Vyra** (usevyra.com) | Raw footage + a chat brief → edit; copies a reference's pace, colour, transitions; MCP server | Slow cloud upload (81 s clip ≈ 20 min); tester asked for local folders | free → $24–129/mo |
| **Eddie AI** | Several storylines to compare, explains each cut; **Feedback Mode v2: timestamped notes on your own cut**; XML to Resolve / Premiere / FCP | Learning to "verbalise" the edit | credits, ~$10/footage hour |
| **Cutback Selects** | Looks at the picture: best takes, stringouts; **search by description** ("where he laughed"); NLE handoff on every plan | no independent reviews | free → $16–80/mo |
| **Gling** | Talking-head cleanup in the transcript, chapters | — (thin data) | free → $40/mo |
| **Captions / Mirage** | Pick a style → cut, captions, music, b-roll | lag, caption desync, export crashes; "abandoned captioning for AI" | AI Edit needs $24.99/mo |
| **Descript Underlord** | Prompt editing with revert; **saved "how I edit" instructions applied to every project** (Jun 2026) | "40% of the way", weak short-form, bill shock | $16–35/mo |
| **OpusClip** | Prompt-steered clipping, scheduling, MCP | credits per uploaded minute, clips out of context | $15–29/mo |
| **Clippra** (beta) | *Our pitch*: raw travel clips → 9:16 reel, hook, beat cuts, captions, grade, real footage only | tiny, unpriced | — |
| **CapCut** | Template / trend loop, AutoCut (beat + silences + captions), best auto captions, EditPilot chat | price doubled, watermarks on Pro templates, **perpetual content licence (2025 backlash)**, heavy generative AI | ~$10–20/mo |
| **Meta Edits** | Free 4K no watermark, captions, "Use template" copies a Reel's timing, weekly ideas from your past Reels, audio search by vibe | thinner than CapCut, mobile only | free (for now) |
| **YouTube "Edit with AI"** | **Camera-roll clips → a draft Short**, free, in the YouTube app | Shorts only, shallow picks, 1080p, some regions | free |
| **TikTok editor / Studio** | Auto-sync to a sound, AI titles / hashtags | most of the edit happens elsewhere first | free |
| **Apple Memories** | Prompt → movie in ~15 s; **Memory Mixes: swipe song + pace + look, the cut re-times to the new song** | ignores the prompt (dog → horse, Prague → Germany), music misses | free |
| **Google Photos** | Beat-cut templates, highlight videos by search; Video Remix is **generative** and paid | template-only control | Remix paid |
| **GoPro Quik** | Highlights from telemetry + HiLight tags; **the edit is waiting on your phone** | paywall to save, crashes, can't turn auto-highlight off | $50–100/yr |
| **Insta360 / DJI** | Theme → **the clips it needs, filmed to plan**; template from the scene; action-matched sound effects | fails with too few clips, slow on Android | free |

## What the market tells us

- **Nobody sells craft.** Everyone sells speed and templates. "No amateur
  tells, only frames you filmed" is still an open position, and the two
  biggest players are moving the other way (CapCut's Seedance / Veo / Sora,
  Google's generative Remix).
- **Trust is a real wedge.** CapCut's perpetual licence, watermarks and
  paywalls on save (Quik) are the top grievances; Vyra's top one is cloud
  upload time. VibeCut is local-first already and generates nothing — say so.
- **The closest threats:** YouTube's Edit with AI (free, camera roll →
  Short, inside the app creators post from), CapCut AutoCut, Clippra (same
  pitch, tiny), Vyra (same chat model, cloud).
- **Picking and story are where everyone fails** ("weird clip",
  repetitive, out of context, prompt ignored). That's where VibeCut's worth /
  scenes / vlog grammar already compete.

## Borrow and better — ranked for VibeCut

Each: who does it · what VibeCut has · the better version.

1. **Notes on your own cut** · Eddie Feedback Mode · `seams.py` checks every
   cut, `selfcheck.py` reviews only an AI Make · a "Check my cut" report on
   a *hand* edit: timestamped, in plain words (brightness jump at 0:34, same
   view twice, a shot held 9 s with nothing happening), click to jump there.
   Report only — fixing it would be cutfix. The free part runs on the rules;
   the model's read is optional. This is the bet itself, made visible. **Built 2026-10-24** (`cutnotes.py`).
2. **What a stop is missing** · Insta360 FlashCut shows the clips a theme
   needs · vlog grammar already orders wide → medium → close and ends on a
   detail · tell the creator "Stop 3 has no wide shot; the café has no
   closing detail" on Footage — and before the next trip, a one-screen shot
   list. Craft nobody taught them, which is the 40/30/20 promise.
3. **Mood swap that re-cuts** · Apple Memory Mixes · look chip, bed and
   beat snap exist separately · one swipe = song + pace + look, the cuts move
   to the new beat, one undoable turn; instant in the preview.
4. **Find a moment by describing it** · Cutback Selects · labels, laughter /
   voice (sound.json), places, time of day are all indexed · a search box on
   Media ("laughing", "night", "the beach") with no model; the key only
   widens it. Unlike Apple: say "nothing matched", never pad.
5. **Steer the picks in a sentence** · OpusClip, Apple prompts · habits bias
   labels, taste text rides on the key path · "more of the beach, less of the
   hotel" before Make becomes a label bias on the rules path too, and the
   reply shows which shots it moved and why.
6. **One "how I edit" box** · Descript saved instructions · profile + rules
   + habits, spread over three places · one editable paragraph the creator
   owns, shown next to what VibeCut has learned.
7. **The draft is ready when the import is** · GoPro Quik, YouTube Edit with
   AI · Make starts after two picks · once clips are read, make the default
   draft in the background with the remembered answers; never paywalled,
   switchable off (Quik's complaints).
8. **Hand-off to a pro editor** · Eddie, Cutback, Gling · nothing · FCPXML
   (Final Cut / Resolve) relinking to the original clips, so a creator who
   outgrows VibeCut keeps the cut.
9. **Drive it from Claude / ChatGPT** · Vyra, Selects, OpusClip, Descript
   (MCP) · ops already are the API · a local MCP server over the same ops;
   local = Vyra's upload complaint answered.
10. **Say the trust promises out loud** · against CapCut's licence, Quik's
    paywall, Google's generative Remix · landing FAQ · "your clips never
    leave your Mac unless you post them; nothing is generated; no watermark;
    you own everything" — copy only, no build.

Lower: highlights from GPS speed and filming bursts (Quik's telemetry idea,
fits decode-once); audio search by vibe and bilingual captions (Edits);
sound effects matched to action (DJI — risky, easily an amateur tell).

**Don't borrow:** generative restyling or b-roll (non-goal), virality scores
(promises more than "no amateur tells"), credit metering that surprises the
bill (Descript, OpusClip complaints — VibeCut already shows the price first).

## Sources

usevyra.com · buffer.com/library/ai-video-tools · heyeddie.ai/pricing ·
cined.com (Eddie Feedback Mode v2) · cutback.video/llms.txt · gling.ai/pricing
· eesel.ai/blog/captions-ai · createwith.com (Underlord preferences) ·
capterra.com (Opus Clip) · hunted.space/product/clippra ·
capcut.com/help/auto-cut-in-capcut · techradar.com (CapCut licence) ·
hooked.so/guides/capcut-updates · planoly.com (Reels templates) ·
socialmediatoday.com (Edits weekly ideas) · ppc.land (YouTube Edit with AI) ·
newsroom.tiktok.com · tomsguide.com (Apple Memory Movies, twice) ·
macrumors.com (Memory looks) · techcrunch.com (Google Photos, 2025-12 and
2026-07) · patents.justia.com/patent/9792502 (GoPro) ·
onlinemanual.insta360.com (FlashCut) · dji.com (Action 4 FAQ)
