"""Apply trend graphics to video: detect trends, find images, add overlays.

Coordinate the full pipeline:
1. Detect what user is talking about (trends, current topics)
2. Find relevant graphics online or generate them
3. Add as animated overlays to the timeline
"""

from __future__ import annotations

from . import trend_detector, graphics_finder


def apply_trend_graphics(
    session: dict,
    captions: list[dict] | None = None,
    voiceover_transcript: str | None = None,
    brief_description: str | None = None,
    auto_graphics: bool = True,
) -> list[dict]:
    """
    Detect trends in user's video and add animated graphics.

    Args:
        session: Current session with board and brief
        captions: List of caption overlays with text
        voiceover_transcript: If available, transcript of user's voice
        brief_description: Brief/description of the video
        auto_graphics: Whether to automatically find and add graphics

    Returns:
        List of overlay operations to add trend graphics
    """

    ops = []

    if not auto_graphics:
        return ops

    # Detect trend moments in the video
    trend_moments = trend_detector.detect_trends_in_video(
        captions=captions,
        voiceover_transcript=voiceover_transcript,
        brief_description=brief_description,
    )

    if not trend_moments:
        return ops

    # For each detected trend, find and add graphics
    finder = graphics_finder.GraphicsFinder()

    for moment in trend_moments:
        # Only add graphics for confident trend moments
        if moment.confidence < 0.6:
            continue

        # Search for relevant graphics
        graphics = finder.search_for_trend_moment(
            topic=moment.topic,
            keywords=moment.keywords,
            graphic_type=moment.graphic_type,
        )

        if not graphics:
            # Fall back to generating simple local graphics
            if moment.graphic_type == "stat":
                spec = graphics_finder.create_stat_graphic(
                    label=moment.topic.replace("_", " ").title(),
                    value="📈",
                    context=", ".join(moment.keywords),
                )
            elif moment.graphic_type == "chart":
                spec = graphics_finder.create_chart_graphic(
                    chart_type="bar",
                    data_points=[],
                    title=" ".join(moment.keywords).title(),
                )
            else:
                # Skip if no graphics available
                continue
        else:
            # Use found graphic
            graphic = graphics[0]  # Best match
            spec = {
                "type": "image",
                "url": graphic.url,
                "source": graphic.source,
                "credit": graphic.credit,
                "local_cached": graphic.local_cached,
            }

        # Get display specifications
        display_spec = trend_detector.suggest_graphic_specs(moment)

        # Merge specs
        spec.update(display_spec)

        # Create overlay operation
        overlay_id = f"trend-{moment.topic}-{int(moment.start_s)}"

        ops.append({
            "op": "add_overlay",
            "kind": "graphic",
            "id": overlay_id,
            "text": f"Trending {moment.topic}",
            "at_s": moment.start_s,
            "duration_s": display_spec.get("duration_s", 3.0),
            "pos": display_spec.get("position", "bottom-right"),
            "spec": spec,
            "reason": f"Trend detected: {moment.context[:50]}",
        })

    return ops


def detect_trends_only(
    captions: list[dict] | None = None,
    voiceover_transcript: str | None = None,
    brief_description: str | None = None,
) -> list[trend_detector.TrendMoment]:
    """Just detect trends without adding graphics.

    Useful for showing user what's available before auto-applying.
    """
    return trend_detector.detect_trends_in_video(
        captions=captions,
        voiceover_transcript=voiceover_transcript,
        brief_description=brief_description,
    )
