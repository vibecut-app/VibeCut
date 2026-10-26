"""Generate smooth, animated graphics for trend moments.

Creates animated visualizations:
- Weather animations (animated weather icons, temperature counters)
- Stock/crypto animations (scrolling tickers, price counters)
- Sports animations (score counters, leaderboards)
- Trending counters (view counts, like counts)
- Search result animations

All with vibe matching so they fit the video's aesthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from . import vibe_graphics


@dataclass
class AnimationSpec:
    """Complete spec for an animated graphic overlay."""
    type: str  # "weather", "stock_ticker", "counter", "leaderboard", etc.
    content: dict[str, Any]  # Data to display
    style: dict[str, Any]  # Colors, fonts, sizing
    animation: dict[str, Any]  # Motion, timing, easing
    duration_s: float  # How long to show
    position: str  # Where on screen


def generate_weather_animation(
    condition: str = "sunny",
    temperature: str = "28°C",
    trend: str = "↑",
    vibe: vibe_graphics.VibeGraphics | None = None,
) -> AnimationSpec:
    """Create animated weather graphic.

    Shows animated weather icon + temperature with trending indicator.
    Smooth pop-in animation, holds for 3s, fades out.
    """

    # Default vibe if not provided
    if not vibe:
        vibe = vibe_graphics.VibeGraphics(
            primary_color="#FFFFFF",
            accent_color="#00D9FF",
            background_color="#1A1A1A",
            text_color="#FFFFFF",
            motion_speed="moderate",
            motion_style="smooth",
            transition_type="fade",
            effect_intensity=0.5,
            effects_used=["glow"],
            font_style="bold",
            text_weight="bold",
            aesthetic="cinematic",
            brightness_level="mid",
        )

    animation_duration = {"fast": 0.3, "moderate": 0.5, "slow": 0.8}.get(vibe.motion_speed, 0.5)

    return AnimationSpec(
        type="weather",
        content={
            "condition": condition,
            "icon": f"🌡️ {condition}",
            "temperature": temperature,
            "trend": trend,
            "description": f"{condition.title()} with {temperature}",
        },
        style={
            "background": vibe.background_color,
            "primary": vibe.primary_color,
            "accent": vibe.accent_color,
            "text": vibe.text_color,
            "font_size": "48px",
            "font_weight": vibe.text_weight,
            "corner_radius": "12px",
            "padding": "20px",
            "border": f"2px solid {vibe.accent_color}",
        },
        animation={
            "enter": "pop",
            "enter_duration_s": animation_duration,
            "enter_easing": "easeOutQuad",
            "hold_duration_s": 3.0,
            "exit": "fade",
            "exit_duration_s": animation_duration,
            "exit_easing": "easeInQuad",
        },
        duration_s=3.5 + (animation_duration * 2),
        position="bottom-right",
    )


def generate_stock_ticker_animation(
    symbol: str = "AAPL",
    price: str = "$195.42",
    change: str = "+2.5%",
    trending: bool = True,
    vibe: vibe_graphics.VibeGraphics | None = None,
) -> AnimationSpec:
    """Create animated stock ticker.

    Scrolling ticker showing stock price with trending indicator.
    Smooth slide animation, continuous scroll.
    """

    if not vibe:
        vibe = vibe_graphics.VibeGraphics(
            primary_color="#FFFFFF",
            accent_color="#00FF88" if trending else "#FF6B6B",
            background_color="#0A0A0A",
            text_color="#FFFFFF",
            motion_speed="fast",
            motion_style="smooth",
            transition_type="slide",
            effect_intensity=0.6,
            effects_used=["glow"],
            font_style="bold",
            text_weight="bold",
            aesthetic="cinematic",
            brightness_level="dark",
        )

    animation_duration = {"fast": 0.3, "moderate": 0.5, "slow": 0.8}.get(vibe.motion_speed, 0.5)

    return AnimationSpec(
        type="stock_ticker",
        content={
            "symbol": symbol,
            "price": price,
            "change": change,
            "trending": trending,
            "display": f"{symbol} {price} {change}",
        },
        style={
            "background": vibe.background_color,
            "primary": vibe.primary_color,
            "accent": vibe.accent_color,
            "text": vibe.text_color,
            "font_size": "32px",
            "font_weight": "bold",
            "font_family": "monospace",
            "border": f"2px solid {vibe.accent_color}",
            "padding": "16px",
        },
        animation={
            "enter": "slide_in",
            "enter_direction": "left",
            "enter_duration_s": animation_duration,
            "enter_easing": "easeOutQuad",
            "hold_duration_s": 3.0,
            "exit": "slide_out",
            "exit_direction": "right",
            "exit_duration_s": animation_duration,
        },
        duration_s=3.5 + (animation_duration * 2),
        position="bottom-left",
    )


def generate_counter_animation(
    label: str = "Views",
    value: str = "1.2M",
    unit: str = "",
    vibe: vibe_graphics.VibeGraphics | None = None,
) -> AnimationSpec:
    """Create animated counter graphic.

    Shows number with optional label and unit.
    Counts up from 0, holds, fades out.
    """

    if not vibe:
        vibe = vibe_graphics.VibeGraphics(
            primary_color="#FFFFFF",
            accent_color="#00D9FF",
            background_color="#1A1A1A",
            text_color="#FFFFFF",
            motion_speed="moderate",
            motion_style="smooth",
            transition_type="fade",
            effect_intensity=0.5,
            effects_used=["glow"],
            font_style="bold",
            text_weight="bold",
            aesthetic="cinematic",
            brightness_level="mid",
        )

    animation_duration = {"fast": 0.3, "moderate": 0.5, "slow": 0.8}.get(vibe.motion_speed, 0.5)

    return AnimationSpec(
        type="counter",
        content={
            "label": label,
            "value": value,
            "unit": unit,
            "display": f"{label}: {value}{unit}",
        },
        style={
            "background": f"rgba(0, 0, 0, 0.7)",
            "accent": vibe.accent_color,
            "text": vibe.text_color,
            "font_size": "56px",
            "font_weight": vibe.text_weight,
            "label_size": "24px",
            "corner_radius": "16px",
            "padding": "24px",
        },
        animation={
            "enter": "pop",
            "enter_duration_s": animation_duration,
            "enter_easing": "easeOutBounce",
            "count_up": True,  # Count from 0 to value
            "count_duration_s": 1.5,
            "hold_duration_s": 2.0,
            "exit": "fade",
            "exit_duration_s": animation_duration,
        },
        duration_s=4.0 + (animation_duration * 2),
        position="center",
    )


def generate_sports_animation(
    home_team: str = "Lakers",
    away_team: str = "Celtics",
    home_score: str = "95",
    away_score: str = "98",
    status: str = "Final",
    vibe: vibe_graphics.VibeGraphics | None = None,
) -> AnimationSpec:
    """Create sports scoreboard animation."""

    if not vibe:
        vibe = vibe_graphics.VibeGraphics(
            primary_color="#FFFFFF",
            accent_color="#FF6B6B",
            background_color="#1A1A1A",
            text_color="#FFFFFF",
            motion_speed="moderate",
            motion_style="smooth",
            transition_type="slide",
            effect_intensity=0.6,
            effects_used=["glow"],
            font_style="bold",
            text_weight="bold",
            aesthetic="cinematic",
            brightness_level="mid",
        )

    animation_duration = {"fast": 0.3, "moderate": 0.5, "slow": 0.8}.get(vibe.motion_speed, 0.5)

    return AnimationSpec(
        type="sports_score",
        content={
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "status": status,
        },
        style={
            "background": vibe.background_color,
            "primary": vibe.primary_color,
            "accent": vibe.accent_color,
            "text": vibe.text_color,
            "team_size": "28px",
            "score_size": "48px",
            "status_size": "16px",
            "border": f"3px solid {vibe.accent_color}",
        },
        animation={
            "enter": "slide_in",
            "enter_direction": "top",
            "enter_duration_s": animation_duration,
            "hold_duration_s": 3.0,
            "exit": "slide_out",
            "exit_direction": "bottom",
            "exit_duration_s": animation_duration,
        },
        duration_s=3.5 + (animation_duration * 2),
        position="top-center",
    )


def create_animation_for_trend(
    trend_type: str,
    data: dict[str, Any],
    blueprint: dict | None = None,
) -> AnimationSpec:
    """Create appropriate animation based on trend type.

    Automatically selects animation type and applies vibe.
    """

    # Extract vibe if blueprint provided
    vibe_obj = None
    if blueprint:
        vibe_obj = vibe_graphics.extract_vibe_graphics(blueprint)

    # Create animation based on trend type
    if trend_type == "weather":
        return generate_weather_animation(
            condition=data.get("condition", "sunny"),
            temperature=data.get("temperature", "25°C"),
            trend=data.get("trend", "→"),
            vibe=vibe_obj,
        )

    elif trend_type == "stocks_crypto":
        return generate_stock_ticker_animation(
            symbol=data.get("symbol", "BTC"),
            price=data.get("price", "$42,000"),
            change=data.get("change", "+5%"),
            trending=data.get("trending", True),
            vibe=vibe_obj,
        )

    elif trend_type == "sports":
        return generate_sports_animation(
            home_team=data.get("home", "Team A"),
            away_team=data.get("away", "Team B"),
            home_score=data.get("home_score", "0"),
            away_score=data.get("away_score", "0"),
            status=data.get("status", "Live"),
            vibe=vibe_obj,
        )

    else:
        # Default to counter for other trends
        return generate_counter_animation(
            label=trend_type.replace("_", " ").title(),
            value=data.get("value", "—"),
            unit=data.get("unit", ""),
            vibe=vibe_obj,
        )
