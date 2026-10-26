"""Apply intelligent editing to a make session.

This bridges:
  Learned emotional blueprint + detected moments + current board
    → intelligent editing decisions
    → board operations

Called during make.py after the board is created but before render.
"""

from __future__ import annotations

from . import intelligent_editing, moment_detector, emotional_analysis


def apply_to_session(
    session: dict,
    emotional_blueprint: emotional_analysis.EmotionalBlueprint | None,
) -> list[dict]:
    """
    Generate intelligent editing operations for a session.

    Args:
        session: The current session (has board, clips, brief)
        emotional_blueprint: The emotional analysis from the reference vlog

    Returns:
        List of editing operations to apply
    """

    if not emotional_blueprint:
        # No emotional blueprint = no intelligent editing
        return []

    # Extract needed data from session
    board = session.get("board", {})
    clips = session.get("brief", {}).get("clips", [])
    media_analysis = session.get("media_analysis", {})
    music_data = session.get("session", {}).get("music", {})

    # Detect moments in the user's footage
    detected_moments = moment_detector.detect_all_moments(
        media_analysis,
        music_data,
        clips,
    )

    # Generate intelligent editing decisions
    decisions = intelligent_editing.build_intelligent_edit_plan(
        detected_moments,
        emotional_blueprint,
        {},  # Full blueprint (not needed for this part)
        clips,
    )

    # Add transitions between shots
    decisions = intelligent_editing.add_transitions_between_shots(decisions, emotional_blueprint)

    # Convert decisions to board operations
    ops = intelligent_editing.convert_to_board_ops(decisions)

    return ops


def has_emotional_blueprint(vibe_data: dict | None) -> bool:
    """Check if vibe has emotional intelligence."""
    if not vibe_data:
        return False
    blueprint = vibe_data.get("blueprint", {})
    return "emotional_blueprint" in blueprint and blueprint["emotional_blueprint"] is not None
