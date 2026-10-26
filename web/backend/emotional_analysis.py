"""Emotional intelligence: learn WHEN and WHY techniques are used.

Instead of just "this vlog uses Zoom 5 times", learn:
- What emotional/narrative moments DO they use zooms?
- When do they hold still vs cut fast?
- When do they use effects vs clean cuts?
- What's the emotional arc?

This turns mechanical technique copying into intelligent editing.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class MomentType:
    """A moment in a vlog where something happens that needs editing."""
    name: str  # "energy peak", "beat moment", "reveal", "dialogue", "transition", "pause", "action"
    description: str
    visual_cues: list[str]  # What to look for in the footage
    audio_cues: list[str]  # What to listen for
    recommended_techniques: list[str]  # Which techniques work best here
    recommended_tempo: str  # "fast" | "moderate" | "slow" | "paused"
    energy_level: int  # 0-10, how intense should this feel


# Standard moment types found in viral vlogs
MOMENT_TYPES = {
    "energy_peak": MomentType(
        name="Energy Peak",
        description="Action climax, emotional high, exciting reveal",
        visual_cues=["fast motion", "bright lighting", "multiple subjects", "change in scene", "subject reaction"],
        audio_cues=["music drop", "beat hit", "sound effect", "sudden silence", "dialogue reaction"],
        recommended_techniques=["Zoom In", "Fast Cuts", "Glitch", "Flash", "Glow"],
        recommended_tempo="fast",
        energy_level=9,
    ),
    "beat_moment": MomentType(
        name="Beat Moment",
        description="Music beat lands, rhythm point, synchronization",
        visual_cues=["beat indicator", "music aligns"],
        audio_cues=["kick drum", "snare hit", "bass drop", "vocal hit"],
        recommended_techniques=["Cut", "Punch In", "Dissolve"],
        recommended_tempo="synchronized",
        energy_level=7,
    ),
    "reveal": MomentType(
        name="Reveal",
        description="New location, new subject, punchline delivery, surprise",
        visual_cues=["camera moves to new subject", "subject enters frame", "environment change"],
        audio_cues=["dialogue reveals", "music build", "ambient change"],
        recommended_techniques=["Zoom Through", "Slide", "Fade", "Whip"],
        recommended_tempo="moderate",
        energy_level=8,
    ),
    "dialogue": MomentType(
        name="Dialogue",
        description="Someone talking to camera, explanation, emotion in voice",
        visual_cues=["face in frame", "mouth moving", "eye contact", "hand gestures"],
        audio_cues=["dialogue", "talking", "voice volume high"],
        recommended_techniques=["Hold", "Subtle Zoom", "Fade In"],
        recommended_tempo="medium",
        energy_level=5,
    ),
    "transition": MomentType(
        name="Transition",
        description="Moving between scenes, locations, or topics",
        visual_cues=["scene change", "cut to different place", "new background", "subject disappears"],
        audio_cues=["music change", "sound bridge", "ambient shift"],
        recommended_techniques=["Dissolve", "Fade", "Whip", "Light Leak"],
        recommended_tempo="moderate",
        energy_level=6,
    ),
    "pause": MomentType(
        name="Pause/Breath",
        description="Emotional moment, silence, contemplation, let it sink in",
        visual_cues=["static shot", "slow movement", "close-up face", "natural scenery"],
        audio_cues=["silence", "natural sound", "soft music", "ambient only"],
        recommended_techniques=["Hold", "No Cut", "Subtle Dissolve"],
        recommended_tempo="slow",
        energy_level=3,
    ),
    "action": MomentType(
        name="Action",
        description="Movement, motion, physical activity, running, jumping, dancing",
        visual_cues=["fast motion in frame", "camera pans with subject", "movement blur", "sports-like"],
        audio_cues=["impact sounds", "movement sounds", "heavy music"],
        recommended_techniques=["Cut On Motion", "Zoom", "Motion Blur", "Pulse"],
        recommended_tempo="fast",
        energy_level=8,
    ),
    "stillness": MomentType(
        name="Stillness",
        description="Static composition, no movement, establishes scene",
        visual_cues=["no motion in frame", "establishing shot", "landscape", "still subject"],
        audio_cues=["ambient sound", "music only", "natural quiet"],
        recommended_techniques=["Hold", "Slow Zoom", "No Effect"],
        recommended_tempo="slow",
        energy_level=2,
    ),
}


@dataclass
class EmotionalArc:
    """The emotional journey of a vlog."""
    peak_moments: list[dict[str, Any]]  # Times and types of energy peaks
    dialogue_moments: list[dict[str, Any]]  # Times of speaking
    action_moments: list[dict[str, Any]]  # Times of movement
    reveal_moments: list[dict[str, Any]]  # Times of new elements
    transition_moments: list[dict[str, Any]]  # Times of scene changes
    pause_moments: list[dict[str, Any]]  # Times of stillness
    energy_curve: list[int]  # Energy level 0-10 at each second

    # Overall shape
    opening_style: str  # "fast hook" | "slow burn" | "immediate action"
    body_pattern: str  # "builds" | "varied" | "steady" | "peaks and valleys"
    ending_style: str  # "explosive" | "fade out" | "cliffhanger" | "resolution"


@dataclass
class EmotionalBlueprint:
    """What emotional moments the vlog has and what techniques fit."""
    moments: dict[str, int]  # {"energy_peak": 5, "dialogue": 8, "action": 3}
    moment_sequences: list[str]  # ["energy_peak", "transition", "dialogue", "action", ...]
    emotional_arc: EmotionalArc

    # Decision rules
    technique_use_cases: dict[str, list[str]]  # {"Zoom": ["energy_peak", "reveal", "action"], ...}
    pacing_rules: list[str]  # ["fast during action", "hold on dialogue", "pause after reveals"]

    # One-liner
    editing_philosophy: str  # "Build energy then release", "Rapid-fire discoveries", etc.

    # Scene understanding (what's actually in the video)
    scene_types: list[dict[str, Any]] | None = None  # [{"type": "action", "confidence": 0.85}, ...]


def detect_energy_peaks_from_music(style_data: dict) -> list[dict[str, Any]]:
    """Find energy peaks from music analysis."""
    music = style_data.get("music", {})
    beat = style_data.get("beat", {})

    peaks = []

    # Check for beat drops (energy peaks)
    if music.get("drop_timestamp_s"):
        peaks.append({
            "type": "energy_peak",
            "time_s": music["drop_timestamp_s"],
            "intensity": "explosive" if music.get("drop_intensity") == "explosive" else "moderate",
            "reason": "music drop",
        })

    # Check for high BPM sections
    bpm = beat.get("bpm", 100)
    if bpm > 120:
        peaks.append({
            "type": "beat_moment",
            "time_s": None,  # Distributed throughout
            "intensity": "high",
            "reason": f"high tempo ({bpm} BPM)",
        })

    return peaks


def detect_dialogue_moments(style_data: dict) -> list[dict[str, Any]]:
    """Find dialogue moments from text/voice analysis."""
    words = style_data.get("words", {})
    text_count = len(words.get("text_samples", [])) if isinstance(words.get("text_samples"), list) else 0

    moments = []
    if text_count > 5:  # Heavy text = person talking/narrating
        moments.append({
            "type": "dialogue",
            "frequency": "frequent",
            "average_duration_s": words.get("average_text_duration_s", 2.0),
            "reason": "heavy text overlay",
        })

    return moments


def detect_action_moments_from_motion(style_data: dict) -> list[dict[str, Any]]:
    """Find action moments from motion analysis."""
    motion_data = getattr(style_data, 'motion', {}) if hasattr(style_data, 'motion') else {}

    moments = []
    # If motion analysis shows high motion intensity, there are action moments
    # This would be populated by deeper motion analysis

    return moments


def detect_scenes_from_style(style_data: dict) -> list[dict[str, Any]]:
    """Infer scene types from available metadata.

    Estimates what's in the video based on:
    - Motion intensity (action vs stillness)
    - Text patterns (dialogue vs narration)
    - Audio cues (music, voice, effects)
    - Transitions (scene changes)

    Returns list of estimated scenes with their types and characteristics.
    """
    scenes = []

    # Analyze motion patterns
    motion = style_data.get("motion", {})
    motion_intensity = motion.get("motion_intensity", "gentle")

    # Analyze text/dialogue
    words = style_data.get("words", {})
    text_frequency = words.get("text_frequency", "sparse")
    text_samples = words.get("text_samples", [])

    # Analyze audio
    audio = style_data.get("audio", {})
    music_energy = style_data.get("music", {}).get("music_energy", "medium")

    # Build scene inferences
    if motion_intensity == "frenetic" or motion_intensity == "dynamic":
        scenes.append({
            "type": "action",
            "confidence": 0.8,
            "visual_cues": ["high motion", "camera movement", "fast-paced"],
            "editing_cues": ["fast cuts", "zoom", "punch"],
            "typical_hold_s": 1.2,
        })

    if text_frequency == "heavy" or len(text_samples) > 5:
        scenes.append({
            "type": "dialogue",
            "confidence": 0.85,
            "visual_cues": ["person speaking", "text overlay", "stationary"],
            "editing_cues": ["hold", "dissolve", "fade"],
            "typical_hold_s": 2.5,
        })

    if motion_intensity == "static" or motion_intensity == "gentle":
        scenes.append({
            "type": "stillness",
            "confidence": 0.75,
            "visual_cues": ["no motion", "beauty shot", "environmental"],
            "editing_cues": ["long hold", "slow dissolve"],
            "typical_hold_s": 3.0,
        })

    # Music drops indicate transitions/reveals
    if music_energy == "builds" or style_data.get("music", {}).get("drop_intensity") == "explosive":
        scenes.append({
            "type": "reveal",
            "confidence": 0.8,
            "visual_cues": ["new location", "subject change", "energy shift"],
            "editing_cues": ["zoom through", "slide", "whip"],
            "typical_hold_s": 1.8,
        })

    # Transitions between scenes
    trans = style_data.get("transitions", {})
    if trans.get("list", []):
        scenes.append({
            "type": "transition",
            "confidence": 0.9,
            "visual_cues": ["scene change", "cut", "effect"],
            "editing_cues": ["dissolve", "fade", "whip"],
            "typical_hold_s": 1.5,
        })

    return scenes


def detect_transitions(style_data: dict) -> list[dict[str, Any]]:
    """Find transition moments."""
    trans = style_data.get("transitions", {})
    trans_list = trans.get("list", [])

    moments = []
    for t in trans_list[:10]:  # Sample first 10 transitions
        if t.get("kind") != "cut":
            moments.append({
                "type": "transition",
                "time_s": t.get("t", 0),
                "transition_type": t.get("kind"),
            })

    return moments


def build_emotional_arc(style_data: dict) -> EmotionalArc:
    """Construct the emotional journey, now with scene understanding."""
    peak_moments = detect_energy_peaks_from_music(style_data)
    dialogue_moments = detect_dialogue_moments(style_data)
    transition_moments = detect_transitions(style_data)
    scenes = detect_scenes_from_style(style_data)  # New: understand what's in the video

    # Estimate energy curve (simple version)
    duration = style_data.get("duration", 60)
    energy_curve = [5] * int(duration)  # Default medium energy

    # Boost energy at peaks
    for peak in peak_moments:
        if peak.get("time_s"):
            idx = int(peak["time_s"])
            if idx < len(energy_curve):
                energy_curve[idx] = 9  # Energy peak

    # Lower energy at dialogue
    for dialogue in dialogue_moments:
        if dialogue.get("average_duration_s"):
            # Dialogue is at medium energy
            pass

    # Detect opening style
    opening_style = "fast hook" if energy_curve[:5] and sum(energy_curve[:5]) / 5 > 7 else "slow burn"

    return EmotionalArc(
        peak_moments=peak_moments,
        dialogue_moments=dialogue_moments,
        action_moments=[],
        reveal_moments=[],
        transition_moments=transition_moments,
        pause_moments=[],
        energy_curve=energy_curve,
        opening_style=opening_style,
        body_pattern="builds",
        ending_style="explosive",
    )


def from_style(style_data: dict) -> EmotionalBlueprint:
    """Create emotional blueprint from learned style, with scene understanding."""

    emotional_arc = build_emotional_arc(style_data)
    scenes = detect_scenes_from_style(style_data)

    moments = {
        "energy_peak": len(emotional_arc.peak_moments),
        "dialogue": len(emotional_arc.dialogue_moments),
        "action": len(emotional_arc.action_moments),
        "reveal": len(emotional_arc.reveal_moments),
        "transition": len(emotional_arc.transition_moments),
        "pause": len(emotional_arc.pause_moments),
    }

    # Build recommended technique use cases, informed by detected scenes
    technique_use_cases = {
        "Zoom In": ["energy_peak", "reveal", "action"],
        "Zoom Through": ["reveal", "transition"],
        "Dissolve": ["transition", "pause", "dialogue"],
        "Fade": ["transition", "dialogue", "stillness"],
        "Whip": ["reveal", "action"],
        "Cut": ["beat_moment", "action", "transition"],
        "Hold": ["dialogue", "pause", "stillness"],
        "Flash": ["energy_peak", "action"],
        "Glitch": ["energy_peak"],
        "Glow": ["energy_peak", "reveal", "action"],
    }

    # Pacing rules informed by scene types found in reference
    pacing_rules = []
    for scene in scenes:
        scene_type = scene.get("type")
        hold_time = scene.get("typical_hold_s", 2.0)

        if scene_type == "action":
            pacing_rules.append(f"Fast cuts (1-2s) during action - {scene.get('confidence', 0):.0%} confidence")
        elif scene_type == "dialogue":
            pacing_rules.append(f"Hold {hold_time:.1f}s during dialogue - let words breathe")
        elif scene_type == "stillness":
            pacing_rules.append(f"Long holds ({hold_time:.1f}s+) for environmental/beauty shots")
        elif scene_type == "reveal":
            pacing_rules.append(f"Use Zoom Through or Slide for reveals - shows new subject")
        elif scene_type == "transition":
            pacing_rules.append("Use dissolve or fade between scenes for smoothness")

    # Add defaults if not covered
    if not any("action" in r for r in pacing_rules):
        pacing_rules.append("Fast cuts (1-2s) during action")
    if not any("dialogue" in r for r in pacing_rules):
        pacing_rules.append("Hold 2-3s during dialogue")

    # Build philosophy from observed scene composition
    has_action = any(s["type"] == "action" for s in scenes)
    has_dialogue = any(s["type"] == "dialogue" for s in scenes)
    has_stillness = any(s["type"] == "stillness" for s in scenes)

    if has_action and has_dialogue:
        editing_philosophy = "Mix energy (action with fast cuts) with breathing room (dialogue with longer holds)"
    elif has_action:
        editing_philosophy = "Keep energy high with quick cuts and dynamic transitions"
    elif has_dialogue:
        editing_philosophy = "Prioritize clarity and emotion - hold shots longer, use soft transitions"
    else:
        editing_philosophy = "Balance visual interest with emotional pacing"

    return EmotionalBlueprint(
        moments=moments,
        moment_sequences=[m.get("type") for m in emotional_arc.peak_moments[:5]],
        emotional_arc=emotional_arc,
        technique_use_cases=technique_use_cases,
        pacing_rules=pacing_rules,
        editing_philosophy=editing_philosophy,
        scene_types=[{"type": s["type"], "confidence": s.get("confidence", 0)} for s in scenes],
    )


def blueprint_to_dict(bp: EmotionalBlueprint) -> dict:
    """Convert to JSON-serializable dict."""
    return {
        "moments": bp.moments,
        "moment_sequences": bp.moment_sequences,
        "emotional_arc": {
            "opening_style": bp.emotional_arc.opening_style,
            "body_pattern": bp.emotional_arc.body_pattern,
            "ending_style": bp.emotional_arc.ending_style,
            "energy_curve_samples": bp.emotional_arc.energy_curve[:10],  # Sample first 10 seconds
        },
        "technique_use_cases": bp.technique_use_cases,
        "pacing_rules": bp.pacing_rules,
        "editing_philosophy": bp.editing_philosophy,
        "scene_types": bp.scene_types,  # What's actually in the video (action, dialogue, stillness, etc.)
    }
