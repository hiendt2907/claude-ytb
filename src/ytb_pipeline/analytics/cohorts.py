"""Cohort-level feedback for tested Short formats.

The YouTube API cannot provide every Shorts metric, so callers may add manual
Studio fields such as ``stayed_to_watch`` and ``short_to_long_clicks``.  This
module deliberately waits for a small cohort instead of promoting one lucky
video into a channel-wide template.
"""

from __future__ import annotations

from statistics import median
from typing import Any

MIN_MATURE_SHORTS = 4
MATURE_AFTER_HOURS = 48


def classify_cohort(
    snapshots: list[dict[str, Any]],
    *,
    baseline_stayed_to_watch: float,
) -> str:
    """Return one decision for a single format cohort."""
    mature = [
        snapshot for snapshot in snapshots
        if float(snapshot.get("age_hours", 0)) >= MATURE_AFTER_HOURS
    ]
    if len(mature) < MIN_MATURE_SHORTS:
        return "needs_more_data"

    stayed = [float(snapshot.get("stayed_to_watch", 0)) for snapshot in mature]
    median_stayed = median(stayed)
    funnel_clicks = sum(int(snapshot.get("short_to_long_clicks", 0)) for snapshot in mature)
    subscribers = sum(int(snapshot.get("subscribers_gained", 0)) for snapshot in mature)

    if median_stayed < baseline_stayed_to_watch:
        return "revise_hook"
    if median_stayed >= baseline_stayed_to_watch * 1.2 and funnel_clicks > 0 and subscribers > 0:
        return "scale"
    if funnel_clicks == 0 or subscribers == 0:
        return "revise_value"
    return "needs_more_data"
