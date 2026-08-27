"""Bounded structured semantic shot planner for opted-in profiles."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectedShot:
    visual_intent: str
    characters: tuple[str, ...]
    duration_weight: float


def validate_directed_shots(raw: list[dict], *, allowed_characters: tuple[str, ...], max_shots: int) -> tuple[DirectedShot, ...]:
    if not 1 <= len(raw) <= max_shots:
        raise ValueError("Director output có số shot ngoài giới hạn.")
    shots = tuple(DirectedShot(str(item.get("visual_intent", "")).strip(), tuple(item.get("characters", ())), float(item.get("duration_weight", 0))) for item in raw)
    if any(not shot.visual_intent or shot.duration_weight <= 0 or not set(shot.characters).issubset(allowed_characters) for shot in shots):
        raise ValueError("Director output không hợp lệ.")
    return shots
