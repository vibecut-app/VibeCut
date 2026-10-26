"""Auto-adapt videos for different social platforms.

One video → multiple platform-optimized versions:
- TikTok: Vertical 9:16, aggressive cuts, 15-60s, top-heavy composition
- Instagram Reels: Vertical 9:16, engaging hook in first 3s
- Instagram Feed: Square 1:1, static or slow motion
- YouTube: Horizontal 16:9, can be longer, full cinematic
- YouTube Shorts: Vertical 9:16, punchy, 15-60s

Each version is recomposed, recut, and optimized for platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlatformSpec:
    """Specifications for a social platform."""
    name: str
    aspect_ratios: list[str]  # Supported ratios
    preferred_ratio: str  # What to optimize for
    duration_min_s: float
    duration_max_s: float
    typical_duration_s: float

    # Editing style
    cut_speed: str  # "fast", "moderate", "slow"
    intro_hook_critical: bool  # First 3s must hook
    text_heavy: bool  # Captions required?

    # Composition
    safe_area: str  # "top_heavy", "center", "full"
    motion_preference: str  # "fast_cuts", "smooth_pans", "static"
    effects_intensity: str  # "high", "moderate", "low"


PLATFORM_SPECS = {
    "tiktok": PlatformSpec(
        name="TikTok",
        aspect_ratios=["9:16"],
        preferred_ratio="9:16",
        duration_min_s=3,
        duration_max_s=60,
        typical_duration_s=30,
        cut_speed="fast",
        intro_hook_critical=True,
        text_heavy=True,
        safe_area="top_heavy",
        motion_preference="fast_cuts",
        effects_intensity="high",
    ),
    "instagram_reels": PlatformSpec(
        name="Instagram Reels",
        aspect_ratios=["9:16"],
        preferred_ratio="9:16",
        duration_min_s=3,
        duration_max_s=90,
        typical_duration_s=30,
        cut_speed="moderate",
        intro_hook_critical=True,
        text_heavy=True,
        safe_area="top_heavy",
        motion_preference="smooth_pans",
        effects_intensity="moderate",
    ),
    "instagram_feed": PlatformSpec(
        name="Instagram Feed",
        aspect_ratios=["1:1", "4:5"],
        preferred_ratio="1:1",
        duration_min_s=1,
        duration_max_s=60,
        typical_duration_s=15,
        cut_speed="slow",
        intro_hook_critical=False,
        text_heavy=False,
        safe_area="center",
        motion_preference="static",
        effects_intensity="low",
    ),
    "youtube_shorts": PlatformSpec(
        name="YouTube Shorts",
        aspect_ratios=["9:16"],
        preferred_ratio="9:16",
        duration_min_s=15,
        duration_max_s=60,
        typical_duration_s=30,
        cut_speed="fast",
        intro_hook_critical=True,
        text_heavy=True,
        safe_area="top_heavy",
        motion_preference="fast_cuts",
        effects_intensity="high",
    ),
    "youtube": PlatformSpec(
        name="YouTube",
        aspect_ratios=["16:9"],
        preferred_ratio="16:9",
        duration_min_s=60,
        duration_max_s=3600,
        typical_duration_s=600,
        cut_speed="moderate",
        intro_hook_critical=True,
        text_heavy=False,
        safe_area="full",
        motion_preference="smooth_pans",
        effects_intensity="moderate",
    ),
}


def generate_crop_for_platform(
    platform: str,
    original_size: tuple[int, int],
) -> dict[str, Any]:
    """Generate crop specification for a platform.

    Args:
        platform: Target platform
        original_size: (width, height) of original video

    Returns:
        Crop spec with x, y, width, height
    """

    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["youtube"])
    target_ratio = spec.preferred_ratio

    orig_w, orig_h = original_size
    orig_ratio = orig_w / orig_h

    # Parse target ratio
    target_parts = target_ratio.split(":")
    target_w, target_h = int(target_parts[0]), int(target_parts[1])
    target_ratio_num = target_w / target_h

    # Calculate crop
    if orig_ratio > target_ratio_num:
        # Original is wider, crop width
        new_w = int(orig_h * target_ratio_num)
        new_h = orig_h
        x = (orig_w - new_w) // 2
        y = 0
    else:
        # Original is taller, crop height
        new_w = orig_w
        new_h = int(orig_w / target_ratio_num)
        x = 0
        y = (orig_h - new_h) // 2

    # Adjust composition based on safe area
    if spec.safe_area == "top_heavy":
        y = max(0, y - int(new_h * 0.1))  # Pull up slightly for face/action

    return {
        "x": x,
        "y": y,
        "width": new_w,
        "height": new_h,
        "ratio": target_ratio,
    }


def adjust_cut_pacing(
    ops: list[dict[str, Any]],
    platform: str,
) -> list[dict[str, Any]]:
    """Adjust cutting speed for platform.

    TikTok/Shorts: More aggressive cuts, faster pacing
    YouTube: Longer shots, contemplative pacing
    """

    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["youtube"])

    adjusted_ops = []
    pacing_multiplier = {
        "fast": 0.7,  # 30% shorter
        "moderate": 1.0,
        "slow": 1.4,  # 40% longer
    }[spec.cut_speed]

    for op in ops:
        if op.get("op") == "set_shot" and "duration" in op:
            op = op.copy()
            op["duration"] = op["duration"] * pacing_multiplier

        adjusted_ops.append(op)

    return adjusted_ops


def add_platform_captions(
    ops: list[dict[str, Any]],
    platform: str,
    captions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Add captions if platform requires them.

    TikTok and Reels heavily benefit from captions.
    YouTube doesn't require them.
    """

    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["youtube"])

    if not spec.text_heavy or not captions:
        return ops

    # Add caption ops for required platform
    # (In full implementation, would insert at appropriate times)
    return ops


def generate_thumbnail_for_platform(
    key_frame: Any,
    platform: str,
) -> dict[str, Any]:
    """Generate platform-specific thumbnail.

    YouTube: 16:9 with title
    TikTok/Reels: 9:16 top-heavy
    Instagram: 1:1 square
    """

    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["youtube"])

    return {
        "platform": platform,
        "ratio": spec.preferred_ratio,
        "text_required": platform in ["tiktok", "instagram_reels"],
        "frame": key_frame,
        "composition": "top_heavy" if spec.safe_area == "top_heavy" else "center",
    }


def adapt_video_for_platform(
    original_ops: list[dict[str, Any]],
    original_duration_s: float,
    captions: list[str] | None = None,
    platform: str = "youtube",
) -> dict[str, Any]:
    """Fully adapt video for a platform.

    Returns complete spec for rendering platform-specific version.
    """

    spec = PLATFORM_SPECS.get(platform, PLATFORM_SPECS["youtube"])

    # Adjust duration if needed
    target_duration = min(
        max(original_duration_s, spec.duration_min_s),
        spec.duration_max_s,
    )

    # Recut if needed to hit target duration
    duration_ratio = target_duration / original_duration_s if original_duration_s > 0 else 1.0

    # Apply adjustments
    adjusted_ops = adjust_cut_pacing(original_ops, platform)
    adjusted_ops = add_platform_captions(adjusted_ops, platform, captions)

    return {
        "platform": platform,
        "format": spec.preferred_ratio,
        "target_duration_s": target_duration,
        "duration_ratio": duration_ratio,
        "ops": adjusted_ops,
        "specs": {
            "cut_speed": spec.cut_speed,
            "text_required": spec.text_heavy,
            "safe_area": spec.safe_area,
            "effects_intensity": spec.effects_intensity,
        },
    }


def generate_all_platform_versions(
    original_ops: list[dict[str, Any]],
    original_duration_s: float,
    captions: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate versions for all major platforms.

    Returns dict with platform -> adapted spec.
    """

    platforms = ["tiktok", "instagram_reels", "instagram_feed", "youtube_shorts", "youtube"]

    versions = {}
    for platform in platforms:
        versions[platform] = adapt_video_for_platform(
            original_ops,
            original_duration_s,
            captions,
            platform,
        )

    return versions
