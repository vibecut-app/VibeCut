"""Automatically enhance user photos and images to look professional.

When user adds photos or live photos, automatically:
- Crop to best composition (rule of thirds, face detection)
- Apply vibe's color grading
- Add vibe's effects (glow, grain, vignette)
- Match duration to video pacing
- Generate zoompan motion matching the vibe
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PhotoProcessingSpec:
    """How to process and display a photo."""
    source: str  # URL or local path

    # Cropping
    crop_strategy: str  # "auto_composition", "face_detect", "center", "none"
    crop_ratio: str  # "16:9", "9:16", "1:1"

    # Processing
    apply_color_grade: bool  # Apply vibe's LUT
    apply_effects: bool  # Apply vibe's effects

    # Motion
    motion_type: str  # "pan", "zoom", "zoom_pan", "static"
    duration_s: float  # How long to hold photo

    # Display
    position: str  # "center", "full_screen"
    fade_in_s: float
    fade_out_s: float


def auto_crop_photo(
    image_path: str,
    target_ratio: str = "16:9",
    strategy: str = "auto_composition",
) -> dict[str, Any]:
    """Determine best crop for a photo.

    Args:
        image_path: Path to image
        target_ratio: Desired aspect ratio
        strategy: How to find best crop
            - "auto_composition": Rule of thirds, balance
            - "face_detect": Center on face
            - "center": Just center the crop

    Returns:
        Crop spec: x, y, width, height (relative to original)
    """

    # In production would use:
    # - PIL/cv2 for rule of thirds
    # - Face detection for face centering
    # - Edge/saliency detection for interesting areas

    # For now, return center crop
    return {
        "strategy": strategy,
        "x": 0.125,  # 12.5% from left (centers in 16:9)
        "y": 0,
        "width": 0.75,
        "height": 1.0,
        "reason": "Auto-centered composition",
    }


def generate_photo_motion(
    motion_type: str = "pan",
    duration_s: float = 3.0,
    direction: str = "up",
) -> dict[str, Any]:
    """Generate smooth motion for photo.

    Creates zoompan or pan motion to keep photo dynamic:
    - Slow pan across interesting areas
    - Subtle zoom (Ken Burns effect)
    - Smooth easing
    """

    if motion_type == "static":
        return {
            "type": "static",
            "scale": 1.0,
        }

    elif motion_type == "pan":
        return {
            "type": "pan",
            "direction": direction,
            "speed": 1.0,
            "distance_percent": 5.0,  # Move 5% of frame
            "easing": "easeInOutQuad",
            "duration_s": duration_s,
        }

    elif motion_type == "zoom":
        return {
            "type": "zoom",
            "start_scale": 1.0,
            "end_scale": 1.1,  # Subtle 10% zoom (Ken Burns effect)
            "easing": "easeInOutQuad",
            "duration_s": duration_s,
        }

    else:  # zoom_pan
        return {
            "type": "zoom_pan",
            "start_scale": 1.0,
            "end_scale": 1.15,
            "pan_direction": direction,
            "pan_distance": 3.0,
            "easing": "easeInOutQuad",
            "duration_s": duration_s,
        }


def process_user_photo(
    photo_path: str,
    vibe: dict[str, Any] | None = None,
    duration_s: float = 3.0,
    aspect_ratio: str = "16:9",
) -> PhotoProcessingSpec:
    """Auto-enhance user photo to match vibe.

    Args:
        photo_path: Path to user's photo
        vibe: Vibe config with colors, effects, motion
        duration_s: How long to show photo
        aspect_ratio: Video aspect ratio

    Returns:
        Complete processing spec
    """

    # Default vibe if not provided
    if not vibe:
        vibe = {
            "motion_style": "smooth",
            "motion_speed": "moderate",
            "effects_used": ["glow"],
            "effect_intensity": 0.5,
        }

    # Determine motion type from vibe
    motion_style = vibe.get("motion_style", "smooth")
    if motion_style == "snappy":
        motion_type = "static"  # No motion for snappy
    elif motion_style == "bouncy":
        motion_type = "zoom"  # Zoom effect for bounce
    else:  # smooth
        motion_type = "zoom_pan"  # Most cinematic

    # Determine direction based on vibe's transition type
    transition_type = vibe.get("transition_type", "cut")
    direction_map = {
        "slide": "right",
        "zoom": "center",
        "whip": "down",
    }
    direction = direction_map.get(transition_type, "up")

    return PhotoProcessingSpec(
        source=photo_path,
        crop_strategy="auto_composition",
        crop_ratio=aspect_ratio,
        apply_color_grade=True,  # Always apply vibe's color
        apply_effects=vibe.get("effect_intensity", 0.5) > 0.3,  # Apply if effects used
        motion_type=motion_type,
        duration_s=duration_s,
        position="full_screen",
        fade_in_s=0.3,
        fade_out_s=0.3,
    )


def convert_to_board_op(
    photo_spec: PhotoProcessingSpec,
    start_s: float = 0.0,
) -> dict[str, Any]:
    """Convert photo processing spec to board operation.

    Creates a clip operation that can be applied to the timeline.
    """

    # Generate motion
    motion = generate_photo_motion(
        motion_type=photo_spec.motion_type,
        duration_s=photo_spec.duration_s,
    )

    # Generate crop
    crop = auto_crop_photo(
        image_path=photo_spec.source,
        target_ratio=photo_spec.crop_ratio,
    )

    return {
        "op": "add_photo_clip",
        "source": photo_spec.source,
        "at": start_s,
        "duration": photo_spec.duration_s,
        "crop": crop,
        "motion": motion,
        "effects": {
            "color_grade": photo_spec.apply_color_grade,
            "effects": photo_spec.apply_effects,
        },
        "fade": {
            "fade_in_s": photo_spec.fade_in_s,
            "fade_out_s": photo_spec.fade_out_s,
        },
    }


def detect_and_process_photos(
    clips: list[dict],
    vibe: dict[str, Any] | None = None,
) -> list[dict]:
    """Auto-process any photos in user's clips.

    Scans all clips, identifies photos/images, and generates
    processing operations to make them look professional.
    """

    ops = []
    current_time = 0.0

    for clip in clips:
        clip_type = clip.get("type", "video")

        if clip_type in ["photo", "image", "still"]:
            # This is a photo - process it
            duration = clip.get("duration", 3.0)

            spec = process_user_photo(
                photo_path=clip.get("path", ""),
                vibe=vibe,
                duration_s=duration,
            )

            op = convert_to_board_op(spec, start_s=current_time)
            ops.append(op)

            current_time += duration
        else:
            # Regular video clip
            duration = clip.get("duration", 1.0)
            current_time += duration

    return ops
