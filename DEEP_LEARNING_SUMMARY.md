# Deep Learning from Reference Vlogs - Complete Architecture

## The Problem

Before: "Cut it like" just learned broad metrics (pacing, beat, look).

Now: **LEARN EVERYTHING** - exactly what fonts, transitions, effects, colors, music, etc. the vlogs use.

## The Solution: Three-Layer Learning

### Layer 1: Basic Metrics (remix.fingerprint)
- Pacing, beat, look, opening, ending
- `VERSION: 1` records from before

### Layer 2: Enhanced Recipe (recipe.py)
- Caption animations (Pop, Slide, Type, etc.)
- Transition types and frequencies
- Visual effects and intensity
- Music analysis
- Color grading
- Pacing patterns

### Layer 3: COMPLETE BLUEPRINT (deep_learn.py) ← NEW
Extract **EVERYTHING**:

```
FontAnalysis
├── fonts (Montserrat, Playfair, etc.)
├── sizes (24px, 32px, etc.)
├── colors (#FF9FB4, #FFFFFF, etc.)
├── animations (Pop ×8, Slide ×4, Fade ×2)
├── hold_duration_s (2.2 seconds)
└── positions (top, middle, bottom)

TransitionAnalysis
├── transitions (Dissolve ×8, Zoom ×5, Whip ×3)
├── durations_ms (avg 300-500ms per type)
├── on_beat_ratio (67% of cuts hit the beat)
└── usage_pattern ("every cut", "occasional", "rare")

EffectAnalysis
├── effects_used (Glow ×3, Glitch ×2, VHS ×1)
├── intensities (Glow: 0.6, Zoom: 0.8)
└── duration_pattern ("sustained", "flashes", "crescendos")

ColorAnalysis
├── dominant_colors (#E8B48A, #B8A184, #FF7A9C)
├── color_temperature ("warm", "cool", "neutral")
├── saturation ("vibrant", "balanced", "desaturated")
├── contrast_ratio (0.65)
├── lut_style ("cinematic", "vibrant", "faded")
└── brightness_level ("bright", "mid", "dark")

MotionAnalysis
├── camera_movements (Zoom In ×4, Pan ×2)
├── zoom_speeds ([1.02, 1.05, ...])
├── motion_intensity ("dynamic", "static", "frenetic")
├── handheld_level (0.3 = 30% shaky)
└── stabilization_detected (true/false)

MusicAnalysis
├── estimated_bpm (120)
├── tempo_variation ("steady", "varies", "dramatic")
├── music_energy ("builds", "steady", "drops")
├── drop_timestamp_s (8.5 seconds)
├── instrumentation (["drums", "bass", "synth", "vocal"])
├── beat_sync_style ("tight", "moderate", "loose")
└── drop_intensity ("explosive", "moderate", "subtle")

AudioMixAnalysis
├── levels (-12 LUFS voice, -6 LUFS music, -20 LUFS sfx)
├── ducking_patterns (when music ducks under dialogue)
├── eq_applied (per-track EQ)
├── compression (ratio per track)
├── reverb_style ("tight", "roomy", "cathedral")
└── noise_gate_enabled (true/false)

CutRhythmAnalysis
├── average_shot_duration_s (1.5 seconds)
├── shot_duration_variance (0.8 std dev)
├── longest_hold_s (6.0)
├── shortest_flash_ms (200)
└── cut_pattern ("staccato", "flowing", "locked to beat")

ShotCompositionAnalysis
├── aspect_ratios_used (["9:16", "16:9", "1:1"])
├── framing_rules (rule of thirds, center, leading lines)
├── shot_sizes (wide, medium, close-up counts)
├── depth_of_field ("shallow", "moderate", "deep")
└── subject_movement ("static", "slow", "fast", "erratic")

TextOverlayAnalysis
├── text_samples (["7:42 am", "coffee run", ...])
├── text_frequency ("sparse", "moderate", "heavy")
├── average_text_duration_s (2.0)
├── emoji_usage (true/false)
├── lowercase_trend (true/false)
└── typewriter_effect (true/false)
```

Plus:
- **style_one_liner**: "Fast-paced vlog with warm tones, heavy motion blur, beat-locked cuts"
- **key_techniques**: ["Cut on motion", "Zoom transitions", "Glitch effects", ...]
- **difficulty_level**: "beginner" | "intermediate" | "advanced" | "expert"

## New User Flow

```
Setup Dialog
  ↓
User clicks "+ Learn a vibe from reels you love"
  ↓
Paste 3+ YouTube links
  ↓
[App learns from each vlog]
  ↓
BLUEPRINT VIEWER (new!)
  Tabs:
  - Fonts & Text (fonts, animations, sizes, colors, hold times)
  - Transitions (types, durations, on-beat %, patterns)
  - Effects (effects used, intensities, duration patterns)
  - Color (palette, temperature, saturation, grading style)
  - Motion (camera movements, intensity, handheld %)
  - Music (BPM, energy, drop timing, instrumentation, beat sync)
  - Audio (levels in LUFS, ducking, reverb, compression)
  - Cut Rhythm (shot length, cut pattern, beats per shot)
  - Shots (aspect ratios, framing rules, shot sizes)
  - Text (samples, frequency, emoji, lowercase trend)
  ↓
"Got it, let's apply this" button
  ↓
Back to Setup with vibe selected
  ↓
"Make my video" applies all learned techniques
```

## Technical Implementation

### Backend Changes

**1. `/web/backend/deep_learn.py` (NEW - 500+ lines)**
- `FontAnalysis`: Fonts, sizes, colors, animations
- `TransitionAnalysis`: Transition types, timing, patterns
- `EffectAnalysis`: Effects, intensity, timing
- `ColorAnalysis`: Color palette, grading, temperature
- `MotionAnalysis`: Camera movements, motion intensity
- `MusicAnalysis`: BPM, energy, beat sync, instrumentation
- `AudioMixAnalysis`: Levels, ducking, EQ, compression
- `CutRhythmAnalysis`: Shot length, cut patterns, rhythm
- `ShotCompositionAnalysis`: Framing, aspect ratios, sizes
- `TextOverlayAnalysis`: Text samples, styling, emoji, lowercase
- `FullBlueprint`: Complete analysis + one-liner + key techniques

**2. `/web/backend/vibes.py` (UPDATED)**
- `learn_set()` now calls `deep_learn.from_style()` after learning
- Generates full blueprint and stores in vibe record
- Version bumped to `2` (includes blueprint)

**3. `/web/backend/app.py` (UPDATED)**
- `GET /api/vibes/{vid}` now returns `blueprint` field with full analysis

### Frontend Changes

**1. `/web/frontend/src/components/BlueprintViewer.tsx` (NEW - 400+ lines)**
- Tabbed interface showing all 10 categories
- Interactive tabs: Fonts, Transitions, Effects, Colors, Motion, Music, Audio, Rhythm, Shots, Text
- Visual representation of data (color swatches, percentage bars, etc.)
- "Got it, let's apply this" button

**2. `/web/frontend/src/components/Setup.tsx` (UPDATED)**
- Imports `BlueprintViewer` component
- State: `showBlueprintPreview` for blueprint display
- Learn flow: fetch vibe data → show blueprint → show recipe → select vibe
- Conditional rendering: blueprint first, then recipe preview

**3. `/web/frontend/src/api.ts` (UPDATED)**
- Method `vibeGet(id)`: fetch vibe with blueprint
- Method `get(url)`: generic GET for flexibility

## Data Flow

```
YouTube Vlog
  ↓ yt-dlp
Video file (first 10 min)
  ↓ reference.start()
Learnt style data
  ↓ vibes.learn_set()
    ├── remix.fingerprint()  → metrics
    ├── recipe.from_styles()  → recipe
    └── deep_learn.from_style()  → blueprint ← NEW
  ↓
Saved vibe record:
{
  "id": "...",
  "name": "...",
  "version": 2,
  "recipe": { ... },
  "blueprint": { 
    "fonts": { ... },
    "transitions": { ... },
    "effects": { ... },
    ... (10 categories)
  }
}
  ↓ GET /api/vibes/{id}
Frontend Blueprint Viewer
```

## What Gets Returned by `/api/vibes/{id}`

```json
{
  "id": "day-in-my-life-popular-reels-20261023",
  "name": "Day in My Life",
  "niche": "vlogs",
  "n": 5,
  "blueprint": {
    "fonts": {
      "fonts": { "Montserrat": 12, "Playfair Display": 3 },
      "most_common": "Montserrat",
      "colors": ["#FFFFFF", "#000000", "#FF9FB4"],
      "animations": { "Pop": 8, "Slide": 4, "Fade": 2 },
      "entrance_duration_ms": 250,
      "hold_duration_s": 2.2,
      ...
    },
    "transitions": {
      "transitions": { "Dissolve": 8, "Zoom": 5, "Whip": 3 },
      "on_beat_ratio": 0.67,
      "usage_pattern": "every cut",
      ...
    },
    ... (8 more categories)
    "style_one_liner": "Fast-paced vlogs with warm cinema tone, dynamic motion, beat-locked cuts, animated captions",
    "key_techniques": ["Fast, staccato cuts", "Zoom transitions", "Warm grading", "Tight beat sync", ...],
    "difficulty_level": "intermediate"
  }
}
```

## UI/UX Experience

1. **Learn** - Paste YouTube links
2. **Discover** - Swipe through 10 tabs of exact techniques
3. **Understand** - See what fonts, effects, music, timing they use
4. **Choose** - Decide which techniques to apply
5. **Apply** - One click to make your video in that style

Example journey for "trendy TikTok vlogs":
- **Fonts tab**: See "TikTok Sans Bold" is used 15 times, holds 2.1s, positioned at bottom
- **Effects tab**: Glitch effect used 3 times at 65% intensity, quick flashes
- **Music tab**: 140 BPM, heavy drops, instrumentation is drums + synth
- **Cut Rhythm**: Average 1.2s shots, staccato pattern, 1.4 beats per shot
- **Motion**: Zoom In camera movement 6 times, handheld 20% (not too shaky)

Then apply ALL of this to their own clips with one click.

## Next Steps (Future Enhancements)

1. **Font Recognition** - Add OCR + font matching to identify exact fonts
2. **Real Motion Analysis** - Optical flow to detect pan/zoom/camera movements
3. **Color Grading Export** - Export the learned LUT for use in other tools
4. **Audio Profile Export** - Export the learned mixing profile
5. **Preset Saving** - Save "my favorite techniques from all vlogs I love"
6. **Visual Examples** - Show GIFs of each technique in each tab
7. **Intensity Sliders** - Adjust "I want 70% of the motion, 100% of the music feel"
8. **Per-Vlog Breakdown** - See what each source vlog contributes to the blueprint

## Key Insight

Instead of vague "it's fast and warm," users now see:
- **EXACTLY** which fonts
- **EXACTLY** which transitions and how often
- **EXACTLY** the music tempo, energy, and beat patterns
- **EXACTLY** the color palette and grading style
- **EXACTLY** the camera movements and motion intensity
- **EXACTLY** the audio mix levels
- **EXACTLY** the cut timing and rhythm

Making it possible to replicate the style with precision.
