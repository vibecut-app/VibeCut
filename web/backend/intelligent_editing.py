"""Intelligent editing: apply the RIGHT technique at the RIGHT moment.

Instead of:
  "User has action shot" + "Vlog uses Zoom 5 times" = "Apply Zoom"

Do:
  "User has action shot" + "Vlog uses Zoom for energy peaks" = "Apply Zoom if it's an energy peak"

This is the difference between mechanical copying and smart editing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import emotional_analysis, moment_detector


@dataclass
class EditingDecision:
    """A decision about what to do at a moment in the timeline."""
    shot_id: str
    moment_type: str
    start_s: float
    end_s: float

    # What to do
    technique: str | None  # Zoom, Dissolve, Cut, etc. or None for hold
    transition: str | None  # Type of transition to next shot
    duration_s: float  # How long to hold shot
    speed: float  # Speed multiplier (1.0 = normal)
    effect: str | None  # Effect to apply
    effect_intensity: float  # 0.0-1.0

    reason: str  # Why we made this choice


def match_moment_to_techniques(
    detected_moment: moment_detector.DetectedMoment,
    emotional_blueprint: emotional_analysis.EmotionalBlueprint,
) -> list[str]:
    """Given a moment type, what techniques work?"""

    # Get technique recommendations for this moment type
    recommendations = emotional_blueprint.technique_use_cases.get(
        detected_moment.type,
        ["Cut"],  # Default to cut
    )

    # Filter to techniques suggested for this specific moment
    techniques = []
    for tech in recommendations:
        if tech in emotional_blueprint.technique_use_cases:
            if detected_moment.type in emotional_blueprint.technique_use_cases[tech]:
                techniques.append(tech)

    return techniques if techniques else recommendations


def decide_shot_treatment(
    shot_idx: int,
    detected_moment: moment_detector.DetectedMoment,
    emotional_blueprint: emotional_analysis.EmotionalBlueprint,
    blueprint: dict,  # Full deep_learn blueprint
    clip_duration_s: float,
) -> EditingDecision:
    """Make a decision about how to edit a shot."""

    # Get best techniques for this moment type
    candidate_techniques = match_moment_to_techniques(detected_moment, emotional_blueprint)

    # Pick the best one (first in list, or weighted by what the reference vlog used)
    chosen_technique = candidate_techniques[0] if candidate_techniques else "Cut"

    # Determine duration based on moment type and pacing rules
    if detected_moment.type == "dialogue":
        duration = detected_moment.suggested_hold_s  # Hold longer for dialogue
        speed = 1.0
        effect = None
    elif detected_moment.type == "action":
        duration = min(detected_moment.suggested_hold_s, 2.0)  # Shorter holds for action
        speed = 1.0
        effect = None  # Could add motion blur
    elif detected_moment.type == "energy_peak":
        duration = min(detected_moment.suggested_hold_s, 1.5)  # Very short for peaks
        speed = 1.0
        effect = "Glow"  # Add intensity
    elif detected_moment.type == "stillness":
        duration = 4.0  # Let it breathe
        speed = 1.0
        effect = None
    else:
        duration = detected_moment.suggested_hold_s
        speed = 1.0
        effect = None

    # Cap at actual clip duration
    duration = min(duration, clip_duration_s)

    return EditingDecision(
        shot_id=f"shot_{shot_idx}",
        moment_type=detected_moment.type,
        start_s=detected_moment.start_s,
        end_s=detected_moment.end_s,
        technique=chosen_technique if chosen_technique != "Cut" else None,
        transition=None,  # Set between shots
        duration_s=duration,
        speed=speed,
        effect=effect,
        effect_intensity=0.6,
        reason=f"{detected_moment.type}: {detected_moment.reason} → {chosen_technique}",
    )


def build_intelligent_edit_plan(
    detected_moments: list[moment_detector.DetectedMoment],
    emotional_blueprint: emotional_analysis.EmotionalBlueprint,
    blueprint: dict,
    clips: list[dict],
) -> list[EditingDecision]:
    """Create a complete editing plan based on emotional moments."""

    decisions = []

    for i, clip in enumerate(clips):
        # Find moments that overlap with this clip
        clip_start = clip.get("start_s", i * 3)
        clip_end = clip_start + clip.get("duration_s", 3)

        overlapping_moments = [
            m for m in detected_moments
            if m.start_s < clip_end and m.end_s > clip_start
        ]

        # Use the strongest moment for this clip
        if overlapping_moments:
            strongest = max(overlapping_moments, key=lambda m: m.confidence)
            decision = decide_shot_treatment(
                i,
                strongest,
                emotional_blueprint,
                blueprint,
                clip.get("duration_s", 3),
            )
        else:
            # No strong moment - default behavior
            decision = EditingDecision(
                shot_id=f"shot_{i}",
                moment_type="default",
                start_s=clip_start,
                end_s=clip_end,
                technique=None,
                transition=None,
                duration_s=clip.get("duration_s", 3),
                speed=1.0,
                effect=None,
                effect_intensity=0.0,
                reason="No specific moment detected - default treatment",
            )

        decisions.append(decision)

    return decisions


def add_transitions_between_shots(
    decisions: list[EditingDecision],
    emotional_blueprint: emotional_analysis.EmotionalBlueprint,
) -> list[EditingDecision]:
    """Add appropriate transitions between shots."""

    for i in range(len(decisions) - 1):
        current = decisions[i]
        next_shot = decisions[i + 1]

        # Choose transition based on moment types
        if current.moment_type == "energy_peak" and next_shot.moment_type == "action":
            current.transition = "Whip"  # Fast transition
        elif current.moment_type == "dialogue" and next_shot.moment_type == "action":
            current.transition = "Dissolve"  # Smooth to different content
        elif current.moment_type == "action" and next_shot.moment_type == "energy_peak":
            current.transition = "Flash"  # Energetic
        elif current.moment_type == "stillness" and next_shot.moment_type == "action":
            current.transition = "Fade"  # Gentle transition to change
        else:
            current.transition = "Cut"  # Default

    return decisions


def convert_to_board_ops(decisions: list[EditingDecision]) -> list[dict]:
    """Convert editing decisions to board operations for the editor."""

    ops = []

    for decision in decisions:
        # Set the shot duration (trim)
        ops.append({
            "op": "set_shot",
            "target": decision.shot_id,
            "field": "trim_end_s",
            "value": decision.duration_s,
            "reason": decision.reason,
        })

        # Set speed if needed
        if decision.speed != 1.0:
            ops.append({
                "op": "set_shot",
                "target": decision.shot_id,
                "field": "speed",
                "value": decision.speed,
            })

        # Add effect if needed
        if decision.effect:
            ops.append({
                "op": "set_shot",
                "target": decision.shot_id,
                "field": "effect",
                "value": decision.effect,
                "intensity": decision.effect_intensity,
            })

        # Add transition if specified
        if decision.transition:
            ops.append({
                "op": "set_transition",
                "target": decision.shot_id,
                "transition": decision.transition,
            })

    return ops


def decisions_to_dict(decisions: list[EditingDecision]) -> list[dict]:
    """Convert decisions to serializable format."""
    return [
        {
            "shot_id": d.shot_id,
            "moment_type": d.moment_type,
            "technique": d.technique,
            "transition": d.transition,
            "duration_s": round(d.duration_s, 2),
            "effect": d.effect,
            "reason": d.reason,
        }
        for d in decisions
    ]
