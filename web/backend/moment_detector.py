"""Detect emotional moments in the user's footage.

Find: action peaks, dialogue, stillness, transitions, reveals, beats
So we can apply the right technique at the right moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DetectedMoment:
    """A moment found in user's footage."""
    type: str  # "energy_peak", "dialogue", "action", "stillness", etc.
    start_s: float
    end_s: float
    confidence: float  # 0.0-1.0
    reason: str  # Why we think this is this moment type
    suggested_techniques: list[str]  # What would work well here
    suggested_hold_s: float  # How long to hold this shot


def detect_motion_spikes(media_analysis: dict) -> list[DetectedMoment]:
    """Find moments where there's fast motion (action)."""
    moments = []

    # This would analyze motion vectors from the media
    # For now, placeholder
    motion_data = media_analysis.get("motion", {})

    if motion_data.get("motion_intensity") in ["dynamic", "frenetic"]:
        moments.append(DetectedMoment(
            type="action",
            start_s=0,
            end_s=10,
            confidence=0.7,
            reason="High motion throughout",
            suggested_techniques=["Zoom In", "Fast Cuts", "Cut On Motion"],
            suggested_hold_s=1.2,
        ))

    return moments


def detect_stillness(media_analysis: dict) -> list[DetectedMoment]:
    """Find moments of no motion (pauses, dialogue, beauty shots)."""
    moments = []

    # Opposite of motion - low movement
    motion_data = media_analysis.get("motion", {})

    if motion_data.get("motion_intensity") == "static":
        moments.append(DetectedMoment(
            type="stillness",
            start_s=0,
            end_s=10,
            confidence=0.8,
            reason="No detected motion",
            suggested_techniques=["Hold", "Slow Zoom", "Subtle Dissolve"],
            suggested_hold_s=3.5,
        ))

    return moments


def detect_dialogue_shots(media_analysis: dict) -> list[DetectedMoment]:
    """Find shots that have talking/dialogue (face in frame, speaking)."""
    moments = []

    # Look for face detection + voice detection
    # This would come from Vision and Speech analysis

    # Placeholder: if there's voice detected
    voice_data = media_analysis.get("voice", {})
    if voice_data.get("detected"):
        moments.append(DetectedMoment(
            type="dialogue",
            start_s=0,
            end_s=5,
            confidence=0.8,
            reason="Voice detected",
            suggested_techniques=["Hold", "Subtle Zoom", "Fade In"],
            suggested_hold_s=2.5,
        ))

    return moments


def detect_transitions_in_footage(clips: list[dict]) -> list[DetectedMoment]:
    """Find natural transition points between shots."""
    moments = []

    # Look for scene/location changes
    # This would be detected by visual similarity drops, metadata changes, etc.

    # Placeholder: every clip boundary
    for i, clip in enumerate(clips[:-1]):
        if i < len(clips) - 1:
            moments.append(DetectedMoment(
                type="transition",
                start_s=clip.get("end_s", 10),
                end_s=clips[i + 1].get("start_s", 15),
                confidence=0.9,
                reason="Scene/shot change",
                suggested_techniques=["Dissolve", "Fade", "Whip"],
                suggested_hold_s=0.3,
            ))

    return moments


def detect_reveals(clips: list[dict]) -> list[DetectedMoment]:
    """Find moments where something new appears (new subject, new location, punchline)."""
    moments = []

    # Reveals are when:
    # - New face appears (visual detection)
    # - Subject enters frame (optical flow)
    # - Environment changes (color/composition difference)
    # - Dialogue reveals something (content analysis)

    # Placeholder: after transitions, there's often a reveal
    for i, clip in enumerate(clips):
        moments.append(DetectedMoment(
            type="reveal",
            start_s=clip.get("start_s", 0) + 0.5,  # Slightly after cut
            end_s=clip.get("start_s", 0) + 2.0,
            confidence=0.6,
            reason="New shot after transition",
            suggested_techniques=["Zoom In", "Slide", "Light Leak"],
            suggested_hold_s=1.5,
        ))

    return moments


def detect_beat_moments(media_analysis: dict, music_data: dict) -> list[DetectedMoment]:
    """Find moments that should align with music beats."""
    moments = []

    # Music has beats at regular intervals
    bpm = music_data.get("estimated_bpm", 120)
    beat_interval = 60.0 / bpm  # Seconds between beats

    # Generate beat points throughout the video
    duration = media_analysis.get("duration", 60)

    beat_times = []
    current_time = beat_interval
    while current_time < duration:
        beat_times.append(current_time)
        current_time += beat_interval

    # Every 2 beats is a strong beat (bars)
    for i, beat_time in enumerate(beat_times):
        if i % 2 == 0:  # Every other beat is stronger
            moments.append(DetectedMoment(
                type="beat_moment",
                start_s=beat_time,
                end_s=beat_time + 0.1,
                confidence=0.9,
                reason=f"Music beat at {bpm} BPM",
                suggested_techniques=["Cut", "Punch In", "Flash"],
                suggested_hold_s=beat_interval,
            ))

    return moments


def detect_energy_peaks(media_analysis: dict, music_data: dict) -> list[DetectedMoment]:
    """Find moments of high energy (should use dynamic techniques)."""
    moments = []

    # Energy peaks are:
    # - High motion + high music energy
    # - Music drop
    # - Sudden change

    motion_intensity = media_analysis.get("motion", {}).get("motion_intensity")
    music_energy = music_data.get("music_energy")

    if motion_intensity in ["dynamic", "frenetic"] and music_energy in ["high", "builds"]:
        moments.append(DetectedMoment(
            type="energy_peak",
            start_s=0,
            end_s=60,
            confidence=0.8,
            reason="High motion + energetic music",
            suggested_techniques=["Zoom In", "Fast Cuts", "Glitch", "Glow"],
            suggested_hold_s=1.0,
        ))

    # Music drop point
    if music_data.get("drop_timestamp_s"):
        moments.append(DetectedMoment(
            type="energy_peak",
            start_s=music_data["drop_timestamp_s"] - 1,
            end_s=music_data["drop_timestamp_s"] + 3,
            confidence=0.95,
            reason="Music drop",
            suggested_techniques=["Punch In", "Flash", "Zoom"],
            suggested_hold_s=0.8,
        ))

    return moments


def detect_scene_types(media_analysis: dict, music_data: dict) -> list[dict[str, Any]]:
    """Infer what types of scenes are in the user's footage.

    Helps match user's footage to learned techniques by understanding:
    - Is there action?
    - Is there dialogue?
    - Are there still/beauty moments?
    - Are there reveals/location changes?

    Returns list of detected scene types with confidence scores.
    """
    scenes = []

    # Analyze motion
    motion = media_analysis.get("motion", {})
    motion_intensity = motion.get("motion_intensity", "gentle")

    if motion_intensity in ["dynamic", "frenetic"]:
        scenes.append({
            "type": "action",
            "confidence": 0.8,
            "reason": f"High motion intensity: {motion_intensity}",
            "suggested_hold_s": 1.2,
            "editing_cue": "Use fast cuts, zoom, or punch effects",
        })

    if motion_intensity in ["static", "gentle"]:
        scenes.append({
            "type": "stillness",
            "confidence": 0.85,
            "reason": f"Low motion: {motion_intensity}",
            "suggested_hold_s": 3.0,
            "editing_cue": "Allow longer holds for emotional impact or beauty",
        })

    # Analyze audio for dialogue
    # (In real implementation, would check for voice detection)
    if media_analysis.get("has_voice", False):
        scenes.append({
            "type": "dialogue",
            "confidence": 0.9,
            "reason": "Voice detected in footage",
            "suggested_hold_s": 2.5,
            "editing_cue": "Hold longer to let words breathe, use soft transitions",
        })

    # Music drops suggest energy/reveals
    if music_data.get("drop_timestamp_s") is not None:
        scenes.append({
            "type": "reveal_or_peak",
            "confidence": 0.8,
            "reason": "Music drop detected - likely energy peak or reveal moment",
            "suggested_hold_s": 1.5,
            "editing_cue": "Use Zoom Through, Slide, or punch effect at drop",
        })

    return scenes


def detect_all_moments(
    media_analysis: dict,
    music_data: dict,
    clips: list[dict],
) -> list[DetectedMoment]:
    """Detect all moments in the user's footage, now with scene understanding."""

    all_moments = []

    # Detect moments based on motion, audio, and music
    all_moments.extend(detect_motion_spikes(media_analysis))
    all_moments.extend(detect_stillness(media_analysis))
    all_moments.extend(detect_dialogue_shots(media_analysis))
    all_moments.extend(detect_transitions_in_footage(clips))
    all_moments.extend(detect_reveals(clips))
    all_moments.extend(detect_beat_moments(media_analysis, music_data))
    all_moments.extend(detect_energy_peaks(media_analysis, music_data))

    # Also detect scene types to enable smarter matching with learned techniques
    scene_types = detect_scene_types(media_analysis, music_data)

    # Annotate moments with scene type information
    # This helps intelligent_editing match moments to learned techniques
    for moment in all_moments:
        for scene in scene_types:
            if scene["type"] in ["action", "stillness", "dialogue"] and moment.type == scene["type"]:
                # Refine moment with scene understanding
                moment.confidence = min(1.0, moment.confidence + 0.1)

    # Sort by time
    all_moments.sort(key=lambda m: m.start_s)

    return all_moments


def moments_to_dict(moments: list[DetectedMoment]) -> list[dict]:
    """Convert moments to serializable format."""
    return [
        {
            "type": m.type,
            "start_s": round(m.start_s, 2),
            "end_s": round(m.end_s, 2),
            "confidence": round(m.confidence, 2),
            "reason": m.reason,
            "suggested_techniques": m.suggested_techniques,
            "suggested_hold_s": round(m.suggested_hold_s, 1),
        }
        for m in moments
    ]
