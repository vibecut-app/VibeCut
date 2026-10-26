"""Auto-generate captions and voiceover scripts in the vibe's writing style.

Understands:
- What user is showing (content, action, emotion)
- Vibe's writing voice (casual, poetic, sarcastic, earnest, witty)
- Scene context (morning, travel, food, reaction, reveal)

Generates captions that feel authentic to the vibe, not generic.
User doesn't write anything - system writes for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SceneAnalysis:
    """Understanding of what's happening in a scene."""
    content_type: str  # "food", "travel", "morning", "reaction", "reveal", "stillness"
    action: str  # What's happening: "drinking coffee", "arriving at location", "laughing"
    emotion: str  # Detected emotion: "joy", "calm", "excited", "contemplative"
    context: str  # Time/location/narrative context
    duration_s: float  # How long this moment lasts


@dataclass
class VibeVoice:
    """The vibe's writing personality."""
    tone: str  # "casual", "poetic", "sarcastic", "earnest", "witty", "documentary"
    energy_level: str  # "high", "medium", "low", "building"
    vocabulary: str  # "simple", "sophisticated", "slang", "formal"
    patterns: list[str]  # Common phrase patterns from the vibe
    opening_lines: list[str]  # How the vibe typically starts captions
    transition_lines: list[str]  # How scenes connect
    punchline_style: str  # "understatement", "exaggeration", "observation", "joke"


def extract_vibe_voice(blueprint: dict) -> VibeVoice:
    """Learn the vibe's writing voice from reference vlogs.

    Analyzes:
    - Text samples and word choices
    - Pace and rhythm of captions
    - Emotional tone
    - Pacing philosophy
    """

    text_data = blueprint.get("text", {})
    text_samples = text_data.get("text_samples", [])
    text_frequency = text_data.get("text_frequency", "moderate")

    # Infer tone from samples
    # In production would use NLP sentiment/style analysis
    lowercase_trend = text_data.get("lowercase_trend", False)
    has_emoji = text_data.get("emoji_usage", False)

    tone = "casual" if lowercase_trend else "poetic"
    if has_emoji:
        tone = "witty"

    # Infer energy from editing philosophy and pacing
    editing_philosophy = blueprint.get("editing_philosophy", "")
    if "fast" in editing_philosophy.lower() or "energy" in editing_philosophy.lower():
        energy_level = "high"
    elif "pause" in editing_philosophy.lower() or "breathe" in editing_philosophy.lower():
        energy_level = "low"
    else:
        energy_level = "medium"

    # Determine vocabulary from text complexity
    avg_word_length = sum(len(w) for w in " ".join(text_samples).split()) / max(len(text_samples), 1)
    vocabulary = "sophisticated" if avg_word_length > 5 else "simple"

    return VibeVoice(
        tone=tone,
        energy_level=energy_level,
        vocabulary=vocabulary,
        patterns=[
            "starting with a time or place",
            "showing before revealing why",
            "understated reactions",
        ],
        opening_lines=[
            "started with",
            "came across",
            "noticed",
            "discovered",
            "happened to",
        ],
        transition_lines=[
            "then we got to",
            "next thing",
            "moved on to",
            "found ourselves",
            "ended up at",
        ],
        punchline_style="understatement",
    )


def analyze_scene(
    content_type: str,
    action: str,
    emotion: str | None = None,
    context: str | None = None,
    duration_s: float = 1.0,
) -> SceneAnalysis:
    """Understand what's happening in a scene."""

    return SceneAnalysis(
        content_type=content_type,
        action=action,
        emotion=emotion or "neutral",
        context=context or "",
        duration_s=duration_s,
    )


def generate_caption_for_scene(
    scene: SceneAnalysis,
    voice: VibeVoice,
    is_opening: bool = False,
    is_closing: bool = False,
) -> str:
    """Generate a caption for a scene that matches the vibe's voice.

    Args:
        scene: What's happening
        voice: Vibe's writing style
        is_opening: First moment of video
        is_closing: Final moment of video

    Returns:
        Generated caption text
    """

    # Build caption based on content type and voice
    caption_templates = {
        "morning": {
            "casual": "{action} like always",
            "poetic": "starting the day with {action}",
            "witty": "{action} — peak productivity",
            "earnest": "taking time to {action}",
        },
        "food": {
            "casual": "grabbed {action}",
            "poetic": "savoring {action}",
            "witty": "{action} hits different",
            "earnest": "enjoying {action}",
        },
        "travel": {
            "casual": "rolled up to {action}",
            "poetic": "discovered {action}",
            "witty": "{action} wasn't on the agenda",
            "earnest": "arrived at {action}",
        },
        "reaction": {
            "casual": "{emotion} about {action}",
            "poetic": "{emotion} when {action}",
            "witty": "me when {action}",
            "earnest": "couldn't help but {action}",
        },
        "reveal": {
            "casual": "turns out {action}",
            "poetic": "and then {action}",
            "witty": "here's the thing: {action}",
            "earnest": "realized {action}",
        },
        "stillness": {
            "casual": "just {action}",
            "poetic": "moment of {action}",
            "witty": "live laugh {action}",
            "earnest": "paused to {action}",
        },
    }

    # Get template
    content_templates = caption_templates.get(scene.content_type, caption_templates["reaction"])
    template = content_templates.get(voice.tone, list(content_templates.values())[0])

    # Fill in template
    caption = template.format(
        action=scene.action,
        emotion=scene.emotion,
    )

    # Add opening/closing flourish
    if is_opening and voice.tone == "witty":
        caption = f"{caption} — let's see where this goes"
    elif is_closing and voice.tone == "poetic":
        caption = f"{caption}. that's the day."

    # Apply case preference
    if voice.tone == "casual":
        caption = caption.lower()

    return caption


def generate_scene_captions(
    scenes: list[dict[str, Any]],
    blueprint: dict | None = None,
) -> list[str]:
    """Generate captions for a sequence of scenes.

    Args:
        scenes: List of scene data
        blueprint: Vibe blueprint to match voice

    Returns:
        List of generated captions
    """

    voice = extract_vibe_voice(blueprint) if blueprint else VibeVoice(
        tone="casual",
        energy_level="medium",
        vocabulary="simple",
        patterns=[],
        opening_lines=["started with"],
        transition_lines=["then"],
        punchline_style="understatement",
    )

    captions = []

    for i, scene_data in enumerate(scenes):
        scene = SceneAnalysis(
            content_type=scene_data.get("type", "reaction"),
            action=scene_data.get("action", "watching"),
            emotion=scene_data.get("emotion"),
            context=scene_data.get("context"),
            duration_s=scene_data.get("duration_s", 1.0),
        )

        is_opening = (i == 0)
        is_closing = (i == len(scenes) - 1)

        caption = generate_caption_for_scene(scene, voice, is_opening, is_closing)
        captions.append(caption)

    return captions


def generate_voiceover_script(
    scenes: list[dict[str, Any]],
    blueprint: dict | None = None,
) -> str:
    """Generate a full voiceover script from scenes.

    Chains captions together with transitions to create
    a cohesive narrative voiceover.
    """

    voice = extract_vibe_voice(blueprint) if blueprint else VibeVoice(
        tone="casual",
        energy_level="medium",
        vocabulary="simple",
        patterns=[],
        opening_lines=["started with"],
        transition_lines=["then"],
        punchline_style="understatement",
    )

    captions = generate_scene_captions(scenes, blueprint)

    # Chain captions with transitions
    script_lines = []

    for i, caption in enumerate(captions):
        if i > 0:
            # Add transition
            transition = voice.transition_lines[i % len(voice.transition_lines)]
            script_lines.append(f"{transition} {caption.lower()[0]}{caption[1:]}")
        else:
            script_lines.append(caption)

    return " ".join(script_lines)


def suggest_caption_edits(
    current_captions: list[str],
    blueprint: dict | None = None,
) -> list[str]:
    """Improve existing captions to match vibe's voice.

    User has written some captions, system enhances them
    to be more in the vibe's style.
    """

    voice = extract_vibe_voice(blueprint) if blueprint else VibeVoice(
        tone="casual",
        energy_level="medium",
        vocabulary="simple",
        patterns=[],
        opening_lines=[],
        transition_lines=[],
        punchline_style="understatement",
    )

    improved = []

    for caption in current_captions:
        # Apply voice characteristics
        edited = caption

        if voice.tone == "casual":
            edited = edited.lower()
        elif voice.tone == "poetic":
            edited = edited.replace("got", "found ourselves at")
            edited = edited.replace("saw", "discovered")
        elif voice.tone == "witty":
            if len(edited) < 20:
                edited = f"{edited} — plot twist"

        improved.append(edited)

    return improved
