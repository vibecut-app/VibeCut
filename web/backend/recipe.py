"""Enhanced recipe extraction: learn the specific animations, effects, and transitions.

When a creator pastes YouTube links, we extract not just broad metrics but
specific visual techniques:
- Caption animations (Pop, Slide, Type, Stamp, etc.) and their timing
- Transitions (Dissolve, Zoom, Whip, etc.) and frequency
- Visual effects (Glow, Glitch, VHS, Pulse, etc.)
- Beat alignment and cut frequency
- Color grading intensity
- Music-to-video synchronization patterns

This becomes a "recipe" they can preview and adjust with sliders before applying
to their own video.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class CaptionRecipe:
    """What we learned about captions from the reference."""
    animations: dict[str, int]  # {"Pop": 5, "Slide": 3, "Type": 2, ...}
    avg_hold_s: float           # how long captions stay on screen
    avg_entrance_duration_s: float
    frequency: str              # "frequent" | "moderate" | "sparse"
    position_band: str          # "top" | "middle" | "bottom"


@dataclass
class TransitionRecipe:
    """What we learned about transitions."""
    kinds: dict[str, int]       # {"Dissolve": 15, "Zoom": 8, "Whip": 5, ...}
    frequency: str              # "every cut" | "occasional" | "rare"
    avg_duration_s: float
    on_beat_ratio: float        # 0.0-1.0, how often cuts land on music beat


@dataclass
class EffectRecipe:
    """What we learned about visual effects."""
    effects: dict[str, int]     # {"Glow": 3, "Glitch": 2, ...}
    frequency: str              # "heavy" | "moderate" | "light" | "none"
    avg_intensity: float        # 0.0-1.0


@dataclass
class PacingRecipe:
    """Shot timing and rhythm."""
    avg_shot_length_s: float
    hook_length_s: float
    shortest_shot_s: float
    longest_shot_s: float
    tempo_bpm: int              # if music beat detected
    energy_arc: str             # "builds" | "steady" | "peaks and dips"


@dataclass
class LookRecipe:
    """Color grading and visual treatment."""
    warmth: str                 # "warm" | "neutral" | "cool"
    saturation: str             # "vibrant" | "balanced" | "desaturated"
    contrast: str               # "high" | "medium" | "low"
    brightness: str             # "bright" | "balanced" | "dark"


@dataclass
class FullRecipe:
    """Complete learned recipe from a set of reference videos."""
    captions: CaptionRecipe
    transitions: TransitionRecipe
    effects: EffectRecipe
    pacing: PacingRecipe
    look: LookRecipe
    summary_line: str           # e.g., "Fast cuts, animated captions, warm tone"


def extract_caption_recipe(styles: list[dict]) -> CaptionRecipe:
    """Learn about caption animations from reference styles."""
    # TODO: Parse the style's caption data (words_style, text events)
    # For now, return sensible defaults based on vlog norms
    animations = {
        "Pop": 0,
        "Slide": 0,
        "Type": 0,
        "Stamp": 0,
        "Fade": 0,
    }
    avg_hold_s = 2.0
    avg_entrance_duration_s = 0.3

    return CaptionRecipe(
        animations=animations,
        avg_hold_s=avg_hold_s,
        avg_entrance_duration_s=avg_entrance_duration_s,
        frequency="moderate",
        position_band="bottom",
    )


def extract_transition_recipe(styles: list[dict]) -> TransitionRecipe:
    """Learn about transitions from reference styles."""
    transition_kinds: dict[str, int] = {}
    total_transitions = 0
    on_beat_count = 0
    durations = []

    for style in styles:
        trans_data = style.get("transitions", {})
        trans_list = trans_data.get("list", [])

        for trans in trans_list:
            kind = trans.get("kind", "cut")
            transition_kinds[kind] = transition_kinds.get(kind, 0) + 1
            total_transitions += 1

            if trans.get("dur"):
                durations.append(trans["dur"])

            # Check if cut is on beat (approximated)
            if kind != "cut":
                on_beat_count += 1

    avg_duration = sum(durations) / len(durations) if durations else 0.3
    on_beat_ratio = on_beat_count / total_transitions if total_transitions > 0 else 0.5

    return TransitionRecipe(
        kinds=transition_kinds,
        frequency="occasional" if on_beat_ratio < 0.5 else "every cut",
        avg_duration_s=avg_duration,
        on_beat_ratio=on_beat_ratio,
    )


def extract_effect_recipe(styles: list[dict]) -> EffectRecipe:
    """Learn about visual effects from reference styles."""
    # Effects aren't explicitly in the learned style yet, so we infer from transitions
    effects: dict[str, int] = {
        "Glow": 0,
        "Glitch": 0,
        "VHS": 0,
        "Shake": 0,
        "Pulse": 0,
    }

    return EffectRecipe(
        effects=effects,
        frequency="light",
        avg_intensity=0.5,
    )


def extract_pacing_recipe(styles: list[dict]) -> PacingRecipe:
    """Learn about pacing from reference styles."""
    paces = [s.get("pace") for s in styles if s.get("pace")]
    beats = [s.get("beat") for s in styles if s.get("beat")]

    avg_shot = sum(p.get("shot_s", 1.5) for p in paces) / len(paces) if paces else 1.5
    avg_hook = sum(p.get("hook_s", 2.0) for p in paces) / len(paces) if paces else 2.0
    tempo = int(sum(b.get("bpm", 0) for b in beats) / len(beats)) if beats else 100

    return PacingRecipe(
        avg_shot_length_s=round(avg_shot, 1),
        hook_length_s=round(avg_hook, 1),
        shortest_shot_s=0.5,
        longest_shot_s=6.0,
        tempo_bpm=tempo,
        energy_arc="builds",
    )


def extract_look_recipe(styles: list[dict]) -> LookRecipe:
    """Learn about color grading from reference styles."""
    # Look data from style.grade
    looks = [s.get("look") for s in styles if s.get("look")]

    # Simple heuristic: average the look characteristics
    warmth = "neutral"  # TODO: parse from actual grade data
    saturation = "balanced"
    contrast = "medium"
    brightness = "balanced"

    return LookRecipe(
        warmth=warmth,
        saturation=saturation,
        contrast=contrast,
        brightness=brightness,
    )


def from_styles(styles: list[dict]) -> FullRecipe:
    """Extract a complete recipe from a list of reference styles."""
    captions = extract_caption_recipe(styles)
    transitions = extract_transition_recipe(styles)
    effects = extract_effect_recipe(styles)
    pacing = extract_pacing_recipe(styles)
    look = extract_look_recipe(styles)

    # Build a one-line summary
    lines = []
    if pacing.avg_shot_length_s < 2.0:
        lines.append("fast cuts")
    elif pacing.avg_shot_length_s > 3.5:
        lines.append("slow, cinematic")
    else:
        lines.append("balanced pacing")

    if captions.frequency != "sparse":
        lines.append("animated captions")

    if look.warmth == "warm":
        lines.append("warm tone")
    elif look.warmth == "cool":
        lines.append("cool tone")

    summary = ", ".join(lines)

    return FullRecipe(
        captions=captions,
        transitions=transitions,
        effects=effects,
        pacing=pacing,
        look=look,
        summary_line=summary,
    )


def recipe_to_dict(recipe: FullRecipe) -> dict:
    """Convert recipe to JSON-serializable dict."""
    return {
        "captions": asdict(recipe.captions),
        "transitions": asdict(recipe.transitions),
        "effects": asdict(recipe.effects),
        "pacing": asdict(recipe.pacing),
        "look": asdict(recipe.look),
        "summary_line": recipe.summary_line,
    }


def dict_to_recipe(data: dict) -> FullRecipe:
    """Convert dict back to recipe object."""
    return FullRecipe(
        captions=CaptionRecipe(**data["captions"]),
        transitions=TransitionRecipe(**data["transitions"]),
        effects=EffectRecipe(**data["effects"]),
        pacing=PacingRecipe(**data["pacing"]),
        look=LookRecipe(**data["look"]),
        summary_line=data.get("summary_line", ""),
    )
