"""Detect trends and topics where animated graphics would enhance the video.

When a user talks about "today's trends", current events, or viral topics,
add relevant graphics: trending images, charts, stats, data visualizations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


@dataclass
class TrendMoment:
    """A moment where trend graphics would enhance the video."""
    start_s: float
    end_s: float

    # What the user is talking about
    topic: str  # "weather", "stock market", "viral challenge", etc.
    keywords: list[str]  # ["hot", "temperature", "record-breaking"]
    context: str  # Full phrase: "Today's weather is crazy hot"

    # How to enhance it
    graphic_type: str  # "chart", "image", "stat", "animation"
    search_query: str  # What to search for: "trending heat wave 2026"
    confidence: float  # 0.0-1.0, how certain this needs graphics


# Keyword patterns for trend detection
TREND_PATTERNS = {
    "weather": {
        "keywords": ["hot", "cold", "rain", "snow", "wind", "storm", "weather", "temperature", "sunny", "cloudy"],
        "graphic_type": "chart",
        "search_base": "trending weather today",
    },
    "stocks_crypto": {
        "keywords": ["stock", "crypto", "bitcoin", "market", "down", "up", "rally", "crash", "bull", "bear"],
        "graphic_type": "chart",
        "search_base": "stock market trends today",
    },
    "viral_challenge": {
        "keywords": ["viral", "challenge", "trend", "trending", "tiktok", "reels", "challenge", "meme"],
        "graphic_type": "image",
        "search_base": "trending challenges today",
    },
    "sports": {
        "keywords": ["game", "score", "win", "lose", "match", "tournament", "championship", "playoff"],
        "graphic_type": "stat",
        "search_base": "sports headlines today",
    },
    "news": {
        "keywords": ["breaking", "news", "headline", "just happened", "today", "event", "incident"],
        "graphic_type": "image",
        "search_base": "news trending today",
    },
    "entertainment": {
        "keywords": ["celebrity", "movie", "show", "album", "release", "premiere", "debut"],
        "graphic_type": "image",
        "search_base": "entertainment news today",
    },
}


def extract_captions_text(captions: list[dict]) -> str:
    """Extract all caption text from video captions."""
    text_parts = []
    for cap in captions:
        if isinstance(cap, dict) and "text" in cap:
            text_parts.append(cap["text"])
    return " ".join(text_parts)


def detect_trends_in_text(text: str, start_s: float = 0.0) -> list[TrendMoment]:
    """Find trend topics in text that would benefit from graphics.

    Args:
        text: Caption text, voiceover transcript, or user description
        start_s: When this text starts in the video (for timing)

    Returns:
        List of detected trend moments with graphics suggestions
    """
    text_lower = text.lower()
    moments = []
    duration_estimate = len(text.split()) / 2.5  # Rough estimate: 2.5 words/second

    # Check for explicit trend mentions
    if any(word in text_lower for word in ["today", "trending", "viral", "breaking"]):
        base_confidence = 0.8
    else:
        base_confidence = 0.5

    # Check each trend pattern
    for trend_type, pattern_data in TREND_PATTERNS.items():
        matched_keywords = [
            kw for kw in pattern_data["keywords"]
            if re.search(rf'\b{kw}\b', text_lower)
        ]

        if matched_keywords:
            # Found trend-related content
            confidence = min(1.0, base_confidence + (len(matched_keywords) * 0.1))

            # Build search query from context
            search_query = f"{pattern_data['search_base']} {' '.join(matched_keywords)}"

            moment = TrendMoment(
                start_s=start_s,
                end_s=start_s + duration_estimate,
                topic=trend_type,
                keywords=matched_keywords,
                context=text[:100],  # First 100 chars as context
                graphic_type=pattern_data["graphic_type"],
                search_query=search_query,
                confidence=confidence,
            )
            moments.append(moment)

    return moments


def detect_trends_in_video(
    captions: list[dict] | None,
    voiceover_transcript: str | None,
    brief_description: str | None,
) -> list[TrendMoment]:
    """Detect all trend moments in user's video.

    Analyzes captions, voiceover, and brief description to find moments
    where animated graphics or charts would enhance the story.
    """
    all_moments = []

    # Check captions
    if captions:
        caption_text = extract_captions_text(captions)
        all_moments.extend(detect_trends_in_text(caption_text))

    # Check voiceover transcript
    if voiceover_transcript:
        # Would be from speech-to-text, but for now use as-is
        all_moments.extend(detect_trends_in_text(voiceover_transcript))

    # Check brief/description
    if brief_description:
        moments = detect_trends_in_text(brief_description)
        # Brief mentions might be lower confidence
        for m in moments:
            m.confidence *= 0.7
        all_moments.extend(moments)

    # Remove duplicates and sort by confidence
    unique_moments = {}
    for m in all_moments:
        key = (m.topic, m.start_s)
        if key not in unique_moments or m.confidence > unique_moments[key].confidence:
            unique_moments[key] = m

    result = sorted(unique_moments.values(), key=lambda m: (-m.confidence, m.start_s))
    return result


def format_search_query(moment: TrendMoment) -> str:
    """Create a good search query from a trend moment."""
    return moment.search_query


def suggest_graphic_specs(moment: TrendMoment) -> dict[str, Any]:
    """Suggest how to display this graphic based on moment type."""
    specs = {
        "type": moment.graphic_type,
        "duration_s": min(5.0, (moment.end_s - moment.start_s) * 2),  # Hold graphic longer than mention
        "animation_in": "fade",  # Fade in when mentioned
        "animation_out": "fade",  # Fade out
        "position": "bottom-right",  # Don't cover subject
        "opacity": 0.85,
        "reason": f"Trending {moment.topic}: {', '.join(moment.keywords)}",
    }

    # Customize per type
    if moment.graphic_type == "chart":
        specs["position"] = "bottom-left"
        specs["size"] = "medium"
    elif moment.graphic_type == "stat":
        specs["position"] = "bottom-center"
        specs["size"] = "small"
    elif moment.graphic_type == "image":
        specs["position"] = "top-right"
        specs["size"] = "large"

    return specs
