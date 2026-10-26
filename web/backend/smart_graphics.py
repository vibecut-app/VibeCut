"""Smart Graphics Coordinator: Auto-enhance videos with animations and photos.

Full automation:
1. Detect trends in what user talks about
2. Generate smooth, animated graphics matching vibe
3. Auto-process any photos user added
4. Add everything to timeline
5. Result: Professional looking vlog, no manual work

Everything auto-matched to the learned reference vibe.
"""

from __future__ import annotations

from . import (
    trend_detector,
    animation_generator,
    vibe_graphics,
    photo_processor,
)


def apply_smart_graphics(
    session: dict,
    blueprint: dict | None = None,
    captions: list[dict] | None = None,
    voiceover_transcript: str | None = None,
    brief_description: str | None = None,
    clips: list[dict] | None = None,
) -> list[dict]:
    """
    Intelligently enhance entire video with animations and photo processing.

    Full pipeline:
    1. Extract vibe characteristics from learned blueprint
    2. Detect trends in content
    3. Generate animated graphics with vibe applied
    4. Auto-process any photos in footage
    5. Return all operations to apply to board
    """

    ops = []

    if not blueprint:
        return ops

    # Step 1: Extract vibe characteristics for matching animations
    vibe = vibe_graphics.extract_vibe_graphics(blueprint)
    vibe_config = vibe_graphics.get_animation_config(blueprint)

    # Step 2: Detect trends in content
    trend_moments = trend_detector.detect_trends_in_video(
        captions=captions,
        voiceover_transcript=voiceover_transcript,
        brief_description=brief_description,
    )

    # Step 3: Generate animated graphics for trends
    for moment in trend_moments:
        # Only create graphics for confident trends
        if moment.confidence < 0.6:
            continue

        # Create animation matched to vibe
        animation_spec = animation_generator.create_animation_for_trend(
            trend_type=moment.topic,
            data={},  # Would populate from trend analysis
            blueprint=blueprint,
        )

        # Convert to overlay operation
        ops.append({
            "op": "add_overlay",
            "kind": "animation",
            "type": animation_spec.type,
            "at": moment.start_s,
            "duration": animation_spec.duration_s,
            "position": animation_spec.position,
            "content": animation_spec.content,
            "style": animation_spec.style,
            "animation": animation_spec.animation,
            "reason": f"Trend animation: {moment.context[:40]}",
        })

    # Step 4: Auto-process any photos in clips
    if clips:
        photo_ops = photo_processor.detect_and_process_photos(
            clips=clips,
            vibe=vibe_config["config"],
        )
        ops.extend(photo_ops)

    return ops


def should_apply_smart_graphics(
    brief: dict | None = None,
) -> bool:
    """Check if smart graphics should be applied.

    Disabled for certain video types:
    - Talking head mode
    - Voiceover mode
    - Already heavily processed
    """

    if not brief:
        return True

    # Don't apply if it's a talking head or voiceover video
    if brief.get("format") in ["talk", "voiceover"]:
        return False

    return True
