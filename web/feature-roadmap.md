# Feature roadmap — what is not in the app, and why

The Phase 1 baseline (`design/specs/phase1-baseline.md`) consolidated the
app around one path: Projects → Footage → Brief → Rough cut → Story →
Export. The "Creative tools" page that used to list seven feature cards is
gone: three of them were second doors to things the workspace already does
(*Plan my edit* = the chat; *Titles & motion* = Words on screen → *Add
titles for me*; *Borrow a feeling* = *Reference* in the header), and four
were disabled cards. Those four are recorded here, not in the product, so
nothing in the app looks like a feature that isn't one.

## Ideas from the September 20 recordings, not built

Descriptions of third-party implementations are research guidance, not
proof of their internal architecture. None of these has a pipeline, a
provider, or a UI. Each would need explicit consent and cost decisions
before it becomes a screen.

| Idea | Source recording | What it would take | Why it waits |
| --- | --- | --- | --- |
| Camera motion (animate a still moment) | ScreenRecording_09-20-2026 19-16-28_1.MP4 | An image-to-video provider, motion constraints, preview and subject-consistency checks | Generates frames the creator didn't film — against the non-goal in CLAUDE.md unless kept as a clearly separate, opt-in mode |
| Try another version (variants of the hook) | ScreenRecording_09-20-2026 19-29-16_1.MP4 | Reusable scene templates, timing alignment, non-destructive alternate versions | Versions need a project model first (now exists: `projects.py`); the storyboard's op log can branch, but the UI for comparing versions is not designed |
| My on-screen character (presenter / cartoon narrator) | ScreenRecording_09-20-2026 19-30-49_1.MP4 | Voice and avatar providers, a consent step before any cloning, composition | Paid providers and consent flow; generated media is a separate mode by design |
| Find the supporting shots (B-roll suggestions) | ScreenRecording_09-20-2026 19-20-48_1.MP4 | Beat/transcript understanding, retrieval over the creator's own index first, approval before insertion | Start with the creator's own footage: the index already has labels (macOS) and per-second signals; a "show what I'm talking about" suggestion is the first honest version |

## What Phase 1 deliberately left out (see the parity matrix)

- Semantic search over footage by content ("every shot of the product on
  the table"): needs embeddings and a model; the index has no text
  descriptions yet.
- Cross-platform speech-to-text: transcripts stay macOS-only and opt-in
  (talking-to-camera mode). The default path needs no transcript.
- Multiple aspect ratios per export: the export follows the footage's
  shape; a format choice is a small addition once calibrated framing exists.
- External agents (MCP): the ops interface in `board.py` is the right
  boundary for it; nothing is exposed yet.

## Posting straight to TikTok, YouTube and Instagram (YouTube built; the others ask first)

Today (2026-10-23) "Share it" after an export copies the caption and opens
each platform's own upload page; the creator picks the file and presses
post there. Posting *from* VibeCut would save that last step, but it means
acting on the creator's accounts, so it waits for the user's explicit
go-ahead, and even then nothing is posted without a confirm per video (a
preview, the caption, who can see it). The user said yes for YouTube on
2026-10-23: built (`web/backend/youtube.py`, `YouTubePost.tsx`; setup in
web/README.md, "Posting to YouTube"). TikTok and Instagram still wait for
a yes. What each one takes, as the platforms describe it (check again
before building; these change):

| Platform | Interface | What we'd have to set up | Catches |
| --- | --- | --- | --- |
| YouTube (and Shorts) — **built** | YouTube Data API v3, `videos.insert`, resumable upload; a Short is just vertical and ≤ 3 min | A Google Cloud project, an OAuth consent screen, the `youtube.upload` scope (+ `youtube.readonly` to name the channel on the confirm screen); the desktop OAuth flow (loopback redirect, PKCE) works from a Mac app; tokens in the Keychain | Both scopes are sensitive: Google's app verification before strangers can use it; until then the consent screen stays in Testing, only listed test users can sign in, and their sign-in lapses after 7 days. Google's page (checked 2026-10-23) now says uploads from unverified projects are *not* held private and that uploads have their own quota (100 a day per project); the app reports the privacy YouTube actually set either way |
| TikTok | Content Posting API: Login Kit + `video.upload` (lands in the creator's TikTok inbox as a draft to finish in the app) or `video.publish` (direct post) | A TikTok for Developers app, its redirect URI, the scopes, the UX TikTok requires (creator's name and avatar, a privacy choice, no preset caption pushed on them) | Every app goes through TikTok's review; until the app passes the audit, direct posts are **private only** and capped to a few users. The draft-to-inbox route is the gentler first step |
| Instagram (Reels) | Instagram API content publishing (`/media` with `media_type=REELS`, then `/media_publish`) | A Meta app, app review for `instagram_content_publish`, an https redirect | Only **Business or Creator** accounts. Meta fetches the video from a public URL (or its resumable upload), so a file on this Mac needs hosting or the resumable path first. Rate-limited per account per day |

Common to all three: an OAuth sign-in per platform (a sign-in screen in the
app, a token store, refresh, sign-out), an https callback some platforms
insist on (so possibly a small hosted page), a privacy policy and terms the
reviews ask for, and a record of what was posted where. Order: YouTube
first (done), TikTok's draft-to-inbox second, Instagram last — each only
on the user's yes.

## Next implementation order

1. Calibrate thresholds on real footage (the rule that matters most).
2. B-roll suggestions from the creator's own index, with approval.
3. Versions of a project (branch the op log), then variants.
4. Paid generation only after provider, cost and consent choices are explicit.
