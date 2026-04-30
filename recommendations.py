"""Recommendation helpers for Carbon Footprint dashboard cards."""

from __future__ import annotations

import logging
from math import isfinite
from typing import Any

_LOGGER = logging.getLogger(__name__)


def get_carbon_label(ci: Any) -> str:
    """Return a human-readable carbon intensity label."""
    safe_ci = _to_float(ci)
    if safe_ci is None:
        return " "
    if safe_ci < 150:
        return "Good"
    if safe_ci < 300:
        return "Moderate"
    return "High"


def get_carbon_color(ci: Any) -> str:
    """Return the frontend CSS class for a carbon intensity value."""
    safe_ci = _to_float(ci)
    if safe_ci is None:
        return "ci-unknown"
    if safe_ci < 150:
        return "ci-low"
    if safe_ci < 300:
        return "ci-medium"
    return "ci-high"


def get_high_impact_area_recommendation(room_data: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Get the recommendation for the highest-impact room."""
    if not isinstance(room_data, list) or not room_data:
        return {
            "title": "No Data Available",
            "message": "We couldn't find any data to determine the high-impact area.",
            "severity": "info",
        }

    try:
        high_impact_room = max(room_data, key=lambda room: _to_float(room.get("total_carbon")) or 0)
        room_name = high_impact_room.get("room") or high_impact_room.get("type") or "Unknown"
        total_carbon = _to_float(high_impact_room.get("total_carbon")) or 0
        return {
            "title": "High-Impact Area Identified",
            "message": f"The room with the highest carbon footprint is {room_name} with a total of {total_carbon:.2f} kg CO2.",
            "emoji": "!",
            "severity": "warning",
        }
    except Exception:
        _LOGGER.exception("Failed to compute high-impact area recommendation")
        return {
            "title": "No Data Available",
            "message": "We couldn't determine the high-impact area.",
            "severity": "info",
        }


def get_carbon_intensity_recommendation(ci: Any) -> dict[str, Any]:
    """Get a recommendation based on current carbon intensity."""
    label = get_carbon_label(ci)
    safe_ci = _to_float(ci)

    if safe_ci is None:
        return {
            "label": label,
            "message": "Carbon intensity data unavailable.",
            "color": "#eeeeee",
            "emoji": "?",
            "severity": "info",
        }

    if safe_ci < 150:
        return {
            "label": label,
            "message": f"The carbon intensity is <b>low ({safe_ci:g} gCO2eq/kWh)</b>. This is a good time to run appliances like washing machines and dishwashers.",
            "color": "#e8f5e9",
            "emoji": "OK",
            "severity": "good",
        }

    if safe_ci < 300:
        return {
            "label": label,
            "message": f"The carbon intensity is <b>moderate ({safe_ci:g} gCO2eq/kWh)</b>. If possible, shift flexible loads to cleaner hours.",
            "color": "#fff8e1",
            "emoji": "!",
            "severity": "warning",
        }

    return {
        "label": label,
        "message": f"The carbon intensity is <b>high ({safe_ci:g} gCO2eq/kWh)</b>. Avoid heavy appliance use now and delay non-essential loads.",
        "color": "#ffebee",
        "emoji": "!",
        "severity": "bad",
    }


def get_iot_share_recommendation(yearly_contribution: Any) -> dict[str, Any]:
    """Get a recommendation based on IoT consumption share."""
    value = _to_float(yearly_contribution) or 0
    if value == 0:
        return {
            "message": "No IoT consumption share was detected. Add devices to get a more accurate recommendation.",
            "emoji": "i",
            "severity": "info",
        }
    if value <= 5:
        return {
            "message": f"Your IoT load is low at {value:.1f}% of yearly consumption. Keep optimizing with smart scheduling.",
            "emoji": "OK",
            "severity": "good",
        }
    if value <= 20:
        return {
            "message": f"Your IoT load is moderate at {value:.1f}%. Review the highest-use devices to reduce waste.",
            "emoji": "!",
            "severity": "warning",
        }
    if value > 100:
        return {
            "message": "Incoherent value computed, have you set an energy meter or a fallback energy value in the settings?",
            "emoji": "!",
            "severity": "bad",
        }
    return {
        "message": f"Your IoT load is relatively high at {value:.1f}%. Consider a device audit and smarter controls to cut emissions.",
        "emoji": "!",
        "severity": "bad",
    }


def get_usage_pattern_recommendation(
    usage_history: dict[str, Any] | None,
    intensity_history: list[dict[str, Any]] | None,
    current_intensity: Any,
) -> dict[str, Any]:
    """Compare usage timing against carbon-intensity history."""
    result_base = {
        "id": "usage_pattern",
        "title": "Usage Pattern Insight",
    }

    safe_intensity = _to_float(current_intensity)
    has_current_intensity = safe_intensity is not None
    has_intensity_history = isinstance(intensity_history, list) and len(intensity_history) > 0
    has_usage_history = isinstance(usage_history, dict) and len(usage_history) > 0

    if not has_intensity_history:
        if has_current_intensity:
            message = (
                "I do not have enough historical carbon-intensity data yet to compare your usage timing over time. "
                f"Based on the current grid value, carbon intensity is <b>{safe_intensity:.0f} gCO2eq/kWh</b>."
            )
            severity = "neutral"
            emoji = "o"
            color = "#fff8e1"

            if safe_intensity < 150:
                message += " That is relatively low, so now is a good moment to run flexible appliances such as a dishwasher, washing machine, dryer, or EV charger."
                severity = "good"
                emoji = "OK"
                color = "#e8f5e9"
            elif safe_intensity < 300:
                message += " That is a moderate level. If the task is flexible, waiting for a cleaner period could slightly reduce emissions."
                emoji = "!"
            else:
                message += " That is high. Try to postpone non-essential, energy-heavy tasks until the grid is cleaner."
                severity = "warning"
                emoji = "!"
                color = "#ffebee"

            return {**result_base, "message": message, "severity": severity, "color": color, "emoji": emoji}

        return {
            **result_base,
            "message": "I cannot analyze your usage pattern yet because historical carbon-intensity data is unavailable. Once intensity history is collected, this recommendation can check whether your energy use happens during cleaner or dirtier grid periods.",
            "severity": "neutral",
            "color": "#e8f5e9",
            "emoji": "i",
        }

    if not has_usage_history:
        return {
            **result_base,
            "message": "I have carbon-intensity history, but no usable energy-usage history yet. Once device usage is collected, this recommendation will compare when you consume energy against how clean the grid was at those same times.",
            "severity": "neutral",
            "color": "#e8f5e9",
            "emoji": "i",
        }

    usage_by_timestamp: dict[str, float] = {}
    for device_points in usage_history.values():
        if not isinstance(device_points, list):
            continue

        previous_cumulative_usage = None
        for point in device_points:
            if not isinstance(point, dict):
                continue
            timestamp = point.get("timestamp")
            usage_value = _to_float(point.get("usage_kwh"))

            if usage_value is None:
                cumulative_usage = _to_float(point.get("energy", point.get("usage")))
                if cumulative_usage is not None:
                    usage_value = 0 if previous_cumulative_usage is None else max(cumulative_usage - previous_cumulative_usage, 0)
                    previous_cumulative_usage = cumulative_usage
                else:
                    usage_value = _to_float(point.get("consumption_footprint", point.get("energy_footprint")))

            if not timestamp or usage_value is None or usage_value <= 0:
                continue
            usage_by_timestamp[timestamp] = usage_by_timestamp.get(timestamp, 0) + usage_value

    if not usage_by_timestamp:
        return {
            **result_base,
            "message": "Usage history exists, but I could not extract any positive consumption values from it. Check that usage points include a timestamp and a numeric value such as <b>usage_kwh</b>, <b>energy</b>, <b>usage</b>, <b>consumption_footprint</b>, or <b>energy_footprint</b>.",
            "severity": "neutral",
            "color": "#e8f5e9",
            "emoji": "i",
        }

    intensity_by_timestamp = {}
    for point in intensity_history or []:
        if not isinstance(point, dict):
            continue
        timestamp = point.get("timestamp")
        intensity_value = _to_float(point.get("intensity", point.get("value", point.get("co2_intensity"))))
        if not timestamp or intensity_value is None or intensity_value <= 0:
            continue
        intensity_by_timestamp[timestamp] = intensity_value

    if not intensity_by_timestamp:
        return {
            **result_base,
            "message": "Carbon-intensity history exists, but I could not extract any valid intensity values from it. The recommendation needs timestamped values such as <b>intensity</b>, <b>value</b>, or <b>co2_intensity</b>.",
            "severity": "neutral",
            "color": "#e8f5e9",
            "emoji": "i",
        }

    matched_usage = 0.0
    weighted_sum = 0.0
    matched_intensities = []
    for timestamp, usage_value in usage_by_timestamp.items():
        intensity_value = intensity_by_timestamp.get(timestamp)
        if intensity_value is None:
            continue
        matched_usage += usage_value
        weighted_sum += usage_value * intensity_value
        matched_intensities.append(intensity_value)

    if matched_usage == 0 or len(matched_intensities) < 2:
        return {
            **result_base,
            "message": "I found both usage data and carbon-intensity data, but there were not enough matching timestamps to compare them reliably. This usually means the two histories use different time intervals or timestamp formats.",
            "severity": "neutral",
            "color": "#e8f5e9",
            "emoji": "i",
        }

    weighted_intensity = weighted_sum / matched_usage
    average_intensity = sum(matched_intensities) / len(matched_intensities)
    intensity_difference_percent = ((weighted_intensity - average_intensity) / average_intensity) * 100 if average_intensity > 0 else 0
    comparison_direction = "higher" if intensity_difference_percent > 0 else "lower"
    comparison_text = (
        "almost exactly in line with"
        if abs(intensity_difference_percent) < 1
        else f"{abs(intensity_difference_percent):.0f}% {comparison_direction} than"
    )
    metrics_message = (
        f"Across <b>{len(matched_intensities)}</b> matched time periods, your usage-weighted grid intensity was <b>{weighted_intensity:.0f} gCO2eq/kWh</b>. "
        f"The average grid intensity during those same periods was <b>{average_intensity:.0f} gCO2eq/kWh</b>, so your usage was {comparison_text} the period average."
    )

    if weighted_intensity > average_intensity * 1.15:
        return {
            **result_base,
            "message": f"{metrics_message} This suggests a noticeable share of your energy use happened when the grid was dirtier than usual. Try shifting flexible loads, such as laundry, dishwashing, charging, or heating cycles, to lower-carbon hours when possible.",
            "severity": "warning",
            "color": "#ffebee",
            "emoji": "!",
        }

    if weighted_intensity < average_intensity * 0.85:
        return {
            **result_base,
            "message": f"{metrics_message} This is a good pattern: your energy use is already aligned with cleaner grid periods. Keep scheduling flexible appliances during lower-carbon hours to maintain the benefit.",
            "severity": "good",
            "color": "#e8f5e9",
            "emoji": "OK",
        }

    return {
        **result_base,
        "message": f"{metrics_message} Your timing is close to average, so there is no strong problem signal. You may still reduce emissions by moving flexible, energy-heavy tasks away from higher-carbon periods when convenient.",
        "severity": "neutral",
        "color": "#fff8e1",
        "emoji": "!",
    }


def build_recommendations(
    room_data: list[dict[str, Any]] | None,
    yearly_contribution: Any,
    usage_history: dict[str, Any] | None,
    intensity_history: list[dict[str, Any]] | None,
    current_intensity: Any,
) -> dict[str, Any]:
    """Build all dashboard recommendations and carbon intensity display metadata."""
    _LOGGER.debug("Building dashboard recommendations")
    return {
        "high_impact_area": get_high_impact_area_recommendation(room_data),
        "carbon_intensity": get_carbon_intensity_recommendation(current_intensity),
        "iot_share": get_iot_share_recommendation(yearly_contribution),
        "usage_pattern": get_usage_pattern_recommendation(
            usage_history,
            intensity_history,
            current_intensity,
        ),
        "carbon_intensity_info": {
            "colorClass": get_carbon_color(current_intensity),
            "label": get_carbon_label(current_intensity),
        },
    }


def _to_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if isfinite(converted) else None
