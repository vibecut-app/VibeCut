"""Extract vibe characteristics and apply to generated graphics.

Learn from reference vlogs:
- Primary colors (dominant, accent)
- Motion style (fast/slow, smooth/snappy)
- Effects (glow, grain, vignette, glitch)
- Typography (bold, elegant, playful)
- Overall aesthetic (cinematic, vibrant, faded, high-key)

Apply to animations so they feel like part of the vlog.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class VibeGraphics:
    """Visual characteristics extracted from learned vibe."""
    # Colors
    primary_color: str  # Main color (hex)
    accent_color: str  # Accent/highlight color
    background_color: str  # Background for graphics
    text_color: str  # Text color for overlays

    # Motion
    motion_speed: str  # "fast" (1-2s), "moderate" (2-3s), "slow" (3-5s)
    motion_style: str  # "snappy" (instant), "smooth" (easing), "bouncy"
    transition_type: str  # "cut", "fade", "slide", "zoom", "dissolve"

    # Effects
    effect_intensity: float  # 0.0-1.0, how intense effects are
    effects_used: list[str]  # ["glow", "grain", "vignette", "glitch"]

    # Typography
    font_style: str  # "bold", "elegant", "playful", "minimal"
    text_weight: str  # "light", "regular", "bold"

    # Overall vibe
    aesthetic: str  # "cinematic", "vibrant", "faded", "high-key", "moody"
    brightness_level: str  # "bright", "mid", "dark"


def extract_vibe_graphics(blueprint: dict) -> VibeGraphics:
    """Extract visual characteristics from learned blueprint.

    Analyzes technical blueprint (colors, motion, effects) to build
    a VibeGraphics specification that can be applied to animations.
    """

    # Extract color information
    colors = blueprint.get("colors", {})
    dominant_colors = colors.get("dominant_colors", ["#FFFFFF"])
    color_temp = colors.get("color_temperature", "neutral")
    saturation = colors.get("saturation", "balanced")
    aesthetic = colors.get("lut_style", "cinematic")
    brightness = colors.get("brightness_level", "mid")

    # Primary: first dominant color, Accent: third or use derived
    primary = dominant_colors[0] if dominant_colors else "#FFFFFF"
    accent = dominant_colors[2] if len(dominant_colors) > 2 else "#00D9FF"

    # Background: dark or light based on brightness
    if brightness == "dark":
        background = "#0A0A0A"
        text_color = "#FFFFFF"
    elif brightness == "bright":
        background = "#F5F5F5"
        text_color = "#1A1A1A"
    else:
        background = "#1A1A1A"
        text_color = "#FFFFFF"

    # Extract motion information
    cut_rhythm = blueprint.get("cut_rhythm", {})
    avg_shot = cut_rhythm.get("average_shot_duration_s", 1.5)

    # Determine motion speed from shot duration
    if avg_shot < 1.5:
        motion_speed = "fast"
    elif avg_shot < 2.5:
        motion_speed = "moderate"
    else:
        motion_speed = "slow"

    # Extract transition style
    transitions = blueprint.get("transitions", {})
    trans_list = transitions.get("transitions", {})
    most_common_transition = max(trans_list.items(), key=lambda x: x[1])[0] if trans_list else "cut"

    # Extract effects
    effects = blueprint.get("effects", {})
    effects_used = list(effects.get("effects_used", {}).keys())[:3]  # Top 3 effects
    effect_intensity = effects.get("intensities", {})

    # Average intensity
    avg_intensity = sum(effect_intensity.values()) / len(effect_intensity) if effect_intensity else 0.5

    # Determine motion style from effect intensity
    if avg_intensity > 0.7:
        motion_style = "snappy"
    elif avg_intensity > 0.4:
        motion_style = "smooth"
    else:
        motion_style = "bouncy"

    # Extract typography
    text_data = blueprint.get("text", {})
    text_frequency = text_data.get("text_frequency", "moderate")

    # Determine font style
    if text_frequency == "heavy":
        font_style = "bold"
    elif "serif" in str(blueprint.get("fonts", {}).get("most_common", "")).lower():
        font_style = "elegant"
    else:
        font_style = "playful" if saturation == "highly saturated" else "minimal"

    return VibeGraphics(
        primary_color=primary,
        accent_color=accent,
        background_color=background,
        text_color=text_color,
        motion_speed=motion_speed,
        motion_style=motion_style,
        transition_type=most_common_transition,
        effect_intensity=avg_intensity,
        effects_used=effects_used,
        font_style=font_style,
        text_weight="bold" if font_style == "bold" else "regular",
        aesthetic=aesthetic,
        brightness_level=brightness,
    )


def apply_vibe_to_animation(animation_spec: dict, vibe: VibeGraphics) -> dict:
    """Apply vibe characteristics to an animation spec.

    Takes a generic animation and customizes colors, timing, effects,
    and style to match the learned vibe.
    """

    # Apply colors
    animation_spec["colors"] = {
        "primary": vibe.primary_color,
        "accent": vibe.accent_color,
        "background": vibe.background_color,
        "text": vibe.text_color,
    }

    # Apply motion timing based on speed
    duration_map = {
        "fast": 0.3,
        "moderate": 0.5,
        "slow": 0.8,
    }
    animation_spec["animation_duration_s"] = duration_map.get(vibe.motion_speed, 0.5)

    # Apply motion easing
    easing_map = {
        "snappy": "easeOutQuad",
        "smooth": "easeInOutQuad",
        "bouncy": "easeOutBounce",
    }
    animation_spec["easing"] = easing_map.get(vibe.motion_style, "easeInOutQuad")

    # Apply transition style
    animation_spec["transition"] = vibe.transition_type

    # Apply effects if intense
    if vibe.effect_intensity > 0.6:
        animation_spec["effects"] = vibe.effects_used[:2]
        animation_spec["effect_intensity"] = vibe.effect_intensity

    # Apply typography
    animation_spec["font"] = {
        "weight": vibe.text_weight,
        "style": vibe.font_style,
    }

    # Apply overall aesthetic via filter/grade
    animation_spec["aesthetic_filter"] = vibe.aesthetic

    return animation_spec


def get_animation_config(blueprint: dict) -> dict:
    """Get full animation configuration from learned vibe."""
    vibe = extract_vibe_graphics(blueprint)

    return {
        "vibe": vibe,
        "config": {
            "primary_color": vibe.primary_color,
            "accent_color": vibe.accent_color,
            "background_color": vibe.background_color,
            "text_color": vibe.text_color,
            "motion_speed": vibe.motion_speed,
            "motion_style": vibe.motion_style,
            "transition_type": vibe.transition_type,
            "effects": vibe.effects_used,
            "font_style": vibe.font_style,
            "aesthetic": vibe.aesthetic,
        }
    }
