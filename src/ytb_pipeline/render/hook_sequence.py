"""Render-time editorial checks for strategy-v1 Short openings."""

from __future__ import annotations

from ..pkg.models import Voiceover


def validate_visual_hook(voiceover: Voiceover) -> None:
    """Require concrete visual evidence for the situation and answer beats.

    This does not judge the final footage aesthetically.  It makes sure the
    render has an explicit visual intention to follow, rather than quietly
    falling back to static title cards during the swipe-sensitive opening.
    """
    strategy = voiceover.strategy
    if voiceover.video_type != "short" or strategy is None or strategy.hook is None:
        return

    required = {"situation", "core_answer"}
    found: dict[str, object] = {}
    for segment in voiceover.segments:
        if segment.purpose in required and segment.purpose not in found:
            found[segment.purpose] = segment

    missing = required - found.keys()
    if missing:
        raise ValueError(f"Visual hook thiếu segment: {', '.join(sorted(missing))}.")
    for purpose, segment in found.items():
        visual_intent = getattr(segment, "visual_intent", "").strip()
        broll = getattr(segment, "broll", "").strip()
        if not visual_intent or not broll:
            raise ValueError(f"Visual hook {purpose} thiếu visual_intent hoặc broll cụ thể.")
