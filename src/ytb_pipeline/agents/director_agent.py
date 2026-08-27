"""Bounded structured semantic shot planner for opted-in profiles."""
from __future__ import annotations

from dataclasses import dataclass
import json

from ..providers.registry import get_llm_provider


@dataclass(frozen=True)
class DirectedShot:
    visual_intent: str
    characters: tuple[str, ...]
    duration_weight: float


def validate_directed_shots(raw: list[dict], *, allowed_characters: tuple[str, ...], max_shots: int) -> tuple[DirectedShot, ...]:
    if not 1 <= len(raw) <= max_shots:
        raise ValueError("Director output có số shot ngoài giới hạn.")
    required = {"visual_intent", "characters", "duration_weight"}
    if any(not isinstance(item, dict) or set(item) != required for item in raw):
        raise ValueError("Director output chứa field không thuộc structured shot contract.")
    shots = tuple(DirectedShot(str(item.get("visual_intent", "")).strip(), tuple(item.get("characters", ())), float(item.get("duration_weight", 0))) for item in raw)
    if any(not shot.visual_intent or shot.duration_weight <= 0 or not set(shot.characters).issubset(allowed_characters) for shot in shots):
        raise ValueError("Director output không hợp lệ.")
    return shots


class DirectorAgent:
    """One configured-provider call per scene, with one bounded repair."""
    ruleset_version = "director-v1"

    async def plan_scene(self, *, narration: str, visual_intent: str, characters: tuple[str, ...], max_shots: int):
        provider = get_llm_provider()
        if not provider.is_available():
            raise RuntimeError("Director LLM provider không khả dụng.")
        prompt = f"Return JSON {{shots:[{{visual_intent,characters,duration_weight}}]}}. Scene: {visual_intent}. Narration: {narration}. Allowed characters: {','.join(characters)}. Max shots: {max_shots}."
        error = None
        for _ in range(2):
            try:
                raw = await provider.complete(prompt if error is None else prompt + " Repair: output valid JSON only.")
                data = json.loads(raw)
                if set(data) != {"shots"} or not isinstance(data["shots"], list):
                    raise ValueError("Director JSON schema không hợp lệ.")
                return validate_directed_shots(data["shots"], allowed_characters=characters, max_shots=max_shots)
            except Exception as exc:
                error = exc
        raise ValueError(f"Director không tạo được scene plan hợp lệ: {error}")
