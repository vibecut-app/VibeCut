"""Learn user's personal editing habits across multiple videos.

After 2-3 videos, system learns:
- Shot hold times they prefer
- Transition types they use
- Effects intensity they like
- Color/look preferences
- Pacing adjustments they make
- Subjects they emphasize

Applies learned preferences automatically to new videos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json
from pathlib import Path


@dataclass
class EditingHabit:
    """A learned editing preference."""
    name: str
    value: float | str  # Numeric or categorical
    confidence: float  # 0.0-1.0, how certain we are
    seen_in_count: int  # How many videos showed this


@dataclass
class UserEditingProfile:
    """Learned editing style from multiple videos."""
    videos_analyzed: int

    # Shot preferences
    avg_shot_hold_s: float  # How long they typically hold shots
    shot_hold_variance: float  # How much they vary it

    # Transition preferences
    preferred_transitions: dict[str, float]  # {"cut": 0.6, "dissolve": 0.3, "fade": 0.1}

    # Effects
    effect_intensity_preference: float  # 0.0-1.0
    effects_they_use: list[str]  # Glow, grain, vignette, etc.

    # Color/Look
    preferred_look: str | None  # Which look they use most
    preferred_color_temp: str | None  # "warm", "cool", "neutral"

    # Pacing
    preferred_pace: str  # "fast", "moderate", "slow"

    # Behavioral patterns
    habits: list[EditingHabit] = field(default_factory=list)

    confidence_level: float = 0.5  # How confident in recommendations


def analyze_video_edits(
    video_data: dict[str, Any],
) -> dict[str, Any]:
    """Extract editing decisions from a completed video.

    Analyzes the turn log to understand what choices user made.
    """

    turns = video_data.get("turns", [])
    shots = video_data.get("shots", [])

    # Extract shot durations
    shot_holds = []
    for shot in shots:
        if "duration_s" in shot:
            shot_holds.append(shot["duration_s"])

    # Extract transitions used
    transitions_used = {}
    for turn in turns:
        ops = turn.get("ops", [])
        for op in ops:
            if op.get("op") == "set_transition":
                trans_type = op.get("kind", "cut")
                transitions_used[trans_type] = transitions_used.get(trans_type, 0) + 1

    # Normalize transitions
    total_transitions = sum(transitions_used.values()) or 1
    transitions_normalized = {
        k: v / total_transitions for k, v in transitions_used.items()
    }

    # Extract effects used
    effects_used = []
    for turn in turns:
        ops = turn.get("ops", [])
        for op in ops:
            if op.get("op") == "set_shot" and "effect" in op:
                effects_used.append(op["effect"])

    # Extract look/color preferences
    preferred_look = None
    for turn in turns:
        ops = turn.get("ops", [])
        for op in ops:
            if op.get("op") == "set_look":
                preferred_look = op.get("look")
                break

    return {
        "shot_holds": shot_holds,
        "transitions": transitions_normalized,
        "effects": effects_used,
        "look": preferred_look,
        "avg_shot_hold": sum(shot_holds) / len(shot_holds) if shot_holds else 2.0,
        "shot_hold_variance": max(shot_holds or [1.0]) - min(shot_holds or [1.0]),
    }


def build_editing_profile(
    videos: list[dict[str, Any]],
) -> UserEditingProfile:
    """Build editing profile from multiple videos.

    Learns patterns across 2+ videos.
    """

    if not videos:
        return UserEditingProfile(
            videos_analyzed=0,
            avg_shot_hold_s=2.0,
            shot_hold_variance=0.5,
            preferred_transitions={},
            effect_intensity_preference=0.5,
            effects_they_use=[],
            preferred_look=None,
            preferred_color_temp=None,
            preferred_pace="moderate",
        )

    all_shot_holds = []
    all_transitions = {}
    all_effects = []
    preferred_looks = []

    # Analyze each video
    for video in videos:
        analysis = analyze_video_edits(video)
        all_shot_holds.extend(analysis.get("shot_holds", []))

        for trans, count in analysis.get("transitions", {}).items():
            all_transitions[trans] = all_transitions.get(trans, 0) + count

        all_effects.extend(analysis.get("effects", []))

        if analysis.get("look"):
            preferred_looks.append(analysis["look"])

    # Calculate averages
    avg_shot_hold = sum(all_shot_holds) / len(all_shot_holds) if all_shot_holds else 2.0
    shot_hold_variance = max(all_shot_holds or [1.0]) - min(all_shot_holds or [1.0])

    # Normalize transitions
    total_trans = sum(all_transitions.values()) or 1
    normalized_transitions = {
        k: v / total_trans for k, v in all_transitions.items()
    }

    # Most common look
    most_common_look = max(set(preferred_looks), key=preferred_looks.count) if preferred_looks else None

    # Effect intensity (average usage)
    effect_intensity = len(all_effects) / (len(videos) * max(len(all_shot_holds or [1]), 1))

    # Determine pace from shot holds
    if avg_shot_hold < 1.5:
        pace = "fast"
    elif avg_shot_hold > 3.0:
        pace = "slow"
    else:
        pace = "moderate"

    # Build habits list
    habits = []

    # Hold time habit
    if len(videos) >= 2:
        habits.append(EditingHabit(
            name="preferred_shot_hold_s",
            value=round(avg_shot_hold, 1),
            confidence=min(1.0, 0.5 + (len(videos) * 0.25)),
            seen_in_count=len(videos),
        ))

    # Most used transition
    if normalized_transitions:
        most_used_trans = max(normalized_transitions.items(), key=lambda x: x[1])
        habits.append(EditingHabit(
            name="preferred_transition",
            value=most_used_trans[0],
            confidence=most_used_trans[1],
            seen_in_count=len(videos),
        ))

    return UserEditingProfile(
        videos_analyzed=len(videos),
        avg_shot_hold_s=avg_shot_hold,
        shot_hold_variance=shot_hold_variance,
        preferred_transitions=normalized_transitions,
        effect_intensity_preference=effect_intensity,
        effects_they_use=list(set(all_effects)),
        preferred_look=most_common_look,
        preferred_color_temp=None,  # Would be extracted from looks
        preferred_pace=pace,
        habits=habits,
        confidence_level=min(1.0, 0.3 + (len(videos) * 0.35)),
    )


def apply_profile_to_video(
    profile: UserEditingProfile,
    default_ops: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply learned preferences to new video operations.

    Adjusts default operations based on what user has done in past videos.
    """

    if profile.videos_analyzed < 2:
        # Not enough data yet
        return default_ops

    adjusted_ops = []

    for op in default_ops:
        adjusted_op = op.copy()

        # Apply shot hold preference
        if op.get("op") == "set_shot" and "duration" in op:
            # Adjust to match their preference (with some variation)
            default_duration = op["duration"]
            adjusted_duration = profile.avg_shot_hold_s

            # Don't change too much if they specifically edited this
            if abs(default_duration - profile.avg_shot_hold_s) > 0.5:
                # Use profile preference only if confident
                if profile.confidence_level > 0.7:
                    adjusted_op["duration"] = adjusted_duration

        # Apply transition preference
        if op.get("op") == "set_transition":
            # If they have a strong preference, suggest it
            if profile.preferred_transitions:
                most_preferred = max(
                    profile.preferred_transitions.items(),
                    key=lambda x: x[1]
                )
                if most_preferred[1] > 0.5:  # They use one transition >50%
                    adjusted_op["kind"] = most_preferred[0]

        # Apply look preference
        if op.get("op") == "set_look" and profile.preferred_look:
            if profile.confidence_level > 0.6:
                adjusted_op["look"] = profile.preferred_look

        adjusted_ops.append(adjusted_op)

    return adjusted_ops
