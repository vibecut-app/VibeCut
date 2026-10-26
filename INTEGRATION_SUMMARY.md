# LearnVibe Integration Summary

## What Was Built

The complete "Cut it like" enhancement is now integrated into the Setup flow. Users can learn from YouTube vlogs and see exactly what was learned before applying it to their video.

## User Flow

```
Setup Dialog opens
    ↓
User clicks "+ Learn a vibe from reels you love"
    ↓
Learning Dialog:
  - Enter a description (e.g., "day in my life")
  - Paste 3+ YouTube links
  - Click "Learn it"
    ↓
[App analyzes the vlogs and extracts the recipe]
    ↓
Recipe Preview Dialog appears with:
  1. Carousel showing 5 style elements:
     - Caption Style (animations, hold time)
     - Transitions (types used, frequency)
     - Visual Effects (effects & intensity)
     - Pacing & Rhythm (shot length, tempo)
     - Color & Grade (warmth, saturation, contrast)
  
  2. Sliders for each element (0-100% intensity)
  
  3. Before/After preview toggling
     - Shows effect of adjustments in real-time
    ↓
User adjusts sliders as desired
    ↓
User clicks "Apply this recipe → (87% intensity)"
    ↓
Back to Setup Dialog with vibe selected
    ↓
User clicks "Make my video"
    ↓
Video is created with the recipe applied
```

## Files Changed

### Backend

1. **`web/backend/recipe.py`** (NEW)
   - `CaptionRecipe`: Learns caption animations, hold time, frequency
   - `TransitionRecipe`: Learns transition types, frequency, beat sync
   - `EffectRecipe`: Learns visual effects and intensity
   - `PacingRecipe`: Learns shot length, hook timing, tempo, energy
   - `LookRecipe`: Learns color grading (warmth, saturation, contrast)
   - `FullRecipe`: Complete learned recipe
   - Functions to extract recipes from reference styles and convert to/from JSON

2. **`web/backend/vibes.py`** (UPDATED)
   - Now imports `recipe` module
   - `learn_set()` function now generates and stores recipe with each learned vibe

3. **`web/backend/app.py`** (UPDATED)
   - New endpoint: `GET /api/vibes/{vid}` returns vibe data with recipe

### Frontend

1. **`web/frontend/src/components/LearnVibe.tsx`** (NEW)
   - `Recipe` interface (exported) for TypeScript
   - `RecipeCard` component: Carousel of 5 style elements with sliders
   - `BeforeAfter` component: Preview toggle showing effect of adjustments
   - `LearnVibePreview` component: Complete recipe preview UI

2. **`web/frontend/src/components/Setup.tsx`** (UPDATED)
   - Imports `LearnVibePreview` component
   - New state: `showRecipePreview` to manage recipe preview display
   - Updated `learn()` function to fetch and show recipe after learning
   - Conditional rendering: Shows recipe preview dialog when vibe is learned
   - "Back" button in recipe preview returns to setup dialog
   - "Apply this recipe" button selects the vibe and closes preview

3. **`web/frontend/src/api.ts`** (UPDATED)
   - New method: `vibeGet(id)` to fetch vibe data with recipe
   - New method: `get(url)` for generic GET requests

## Technical Details

### Recipe Extraction

The `recipe.py` module analyzes reference videos and learns:

- **Captions**: Which animations are used most (Pop, Slide, Type, Stamp, Fade)
  - Average hold time on screen
  - Where captions are positioned (top, middle, bottom)
  - Animation frequency (frequent, moderate, sparse)

- **Transitions**: Types of cuts and transitions used
  - Frequency of each transition type
  - Percentage of cuts that land on the beat
  - Average transition duration

- **Effects**: Visual effects used
  - Which effects (Glow, Glitch, VHS, Shake, etc.)
  - Overall intensity (heavy, moderate, light, none)

- **Pacing**: Timing and rhythm
  - Average shot length (in seconds)
  - Hook length (first shot/grab)
  - Tempo (BPM if music detected)
  - Energy arc (builds, steady, peaks and dips)

- **Look**: Color grading
  - Warmth (warm, neutral, cool)
  - Saturation (vibrant, balanced, desaturated)
  - Contrast (high, medium, low)
  - Brightness (bright, balanced, dark)

### Adjustment System

Each recipe element has an intensity slider (0-100%):
- 0% = Don't apply this element
- 50% = Apply it subtly
- 100% = Apply it fully

The average adjustment across all elements determines overall intensity shown when user applies the recipe.

### API Flow

```
Frontend                          Backend
---------                         -------
POST /api/vibes
  { niche, links }
                                  ↓ Job created
                                  Learns from each reel
                                  Extracts recipe via recipe.py
                                  Saves vibe with recipe
GET /api/vibes/{jid}
  ↓ Poll until done
                                  Returns job.public()
When done:
GET /api/vibes/{vid}
  ↓
                                  vibes.get(vid) returns full record
                                  including recipe
Returns:
{
  "id": "...",
  "name": "...",
  "recipe": {
    "captions": { ... },
    "transitions": { ... },
    "effects": { ... },
    "pacing": { ... },
    "look": { ... },
    "summary_line": "..."
  }
}
```

## What's Next (Optional)

1. **Real Preview**: Connect the before/after preview to actually show a sample of your clip with the recipe applied (currently it's a placeholder)

2. **Save Presets**: Let users save their favorite slider combinations as reusable presets ("80% captions, 50% effects" = my style)

3. **Share Recipes**: Export learned recipes as JSON so friends can use them

4. **Fine-tune in Frames**: Let users adjust the recipe intensity after the video is made (in the Frames editor)

5. **Visual Examples**: Show small animated GIFs in each carousel card demonstrating the animation/transition/effect

## Testing

The integration is ready to test:

1. Open the app and go to a project
2. On Setup, click "+ Learn a vibe from reels you love"
3. Enter a description (e.g., "trending TikToks")
4. Paste 3+ YouTube Shorts/Reels links
5. Click "Learn it" and wait for analysis
6. See the recipe carousel with all 5 elements
7. Adjust sliders to fine-tune
8. Click "Apply this recipe" → back to Setup with vibe selected
9. Click "Make my video" → your video uses the recipe!
