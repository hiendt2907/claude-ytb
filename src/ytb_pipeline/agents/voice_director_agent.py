"""VoiceDirectorAgent — chọn TTS provider + prosody hint, THUẦN rule-based,
KHÔNG gọi LLM. Đầu vào `context["script"]` có thể là `Script` dataclass hoặc
dict {"segments": [...], "voice": str, "language": str}.
"""

from __future__ import annotations

import time
from typing import Any

from .base import AgentResult, AgentStatus

_MANY_SEGMENTS_THRESHOLD = 8
_SLOW_PACE_RATE = 0.85
_NORMAL_PACE_RATE = 1.0
_ENTERTAINMENT_RATE = 1.16
_KNOWLEDGE_RATE = 0.96
_ENTERTAINMENT_HINTS = ("giải trí", "giai tri", "người que", "nguoi que", "stickman", "hài", "meme", "viral")
_KNOWLEDGE_HINTS = ("kiến thức", "kien thuc", "tâm lý", "tam ly", "phát triển bản thân", "khoa học")


class VoiceDirectorAgent:
    name = "voice_director"

    @property
    def required_context_keys(self) -> list[str]:
        return ["script"]

    def can_run(self, context: dict[str, Any]) -> bool:
        return "script" in context

    async def run(self, context: dict[str, Any]) -> AgentResult:
        start = time.monotonic()
        try:
            script = context["script"]
            segments = _extract_segments(script)
            voice = _extract_attr(script, "voice", "vi-VN-NamMinhNeural")
            needs_clone = bool(context.get("voice_clone_required", False))

            has_code = any(_extract_attr(seg, "code", "") for seg in segments)
            segment_count = len(segments)
            intent = _intent(script, segments)

            if needs_clone:
                provider = "f5"
            elif segment_count >= _MANY_SEGMENTS_THRESHOLD:
                provider = "edge"
            else:
                provider = "edge"

            pause_adjustments = _pause_adjustments(intent, has_code)

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                output={
                    "provider": provider,
                    "voice": voice,
                    "pause_adjustments": pause_adjustments,
                },
                latency_ms=_elapsed_ms(start),
            )
        except Exception as exc:  # noqa: BLE001 — agent KHÔNG BAO GIỜ raise
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                output=None,
                error=str(exc),
                latency_ms=_elapsed_ms(start),
            )


def _extract_segments(script: Any) -> list[Any]:
    if isinstance(script, dict):
        return list(script.get("segments", ()))
    return list(getattr(script, "segments", ()))


def _extract_attr(obj: Any, key: str, default: Any) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _intent(script: Any, segments: list[Any]) -> str:
    text = " ".join([
        str(_extract_attr(script, "topic", "")),
        str(_extract_attr(script, "title", "")),
        str(_extract_attr(script, "description", "")),
        " ".join(str(t) for t in (_extract_attr(script, "tags", ()) or ())),
        " ".join(str(_extract_attr(seg, "narration", "")) for seg in segments),
        " ".join(str(_extract_attr(seg, "broll", "")) for seg in segments),
    ]).lower()
    if any(hint in text for hint in _ENTERTAINMENT_HINTS):
        return "entertainment"
    if any(hint in text for hint in _KNOWLEDGE_HINTS):
        return "knowledge"
    return "neutral"


def _pause_adjustments(intent: str, has_code: bool) -> dict[str, Any]:
    if has_code:
        return {"rate": _SLOW_PACE_RATE, "pace": "slow"}
    if intent == "entertainment":
        return {"rate": _ENTERTAINMENT_RATE, "pace": "fast", "profile": "entertainment"}
    if intent == "knowledge":
        return {"rate": _KNOWLEDGE_RATE, "pace": "inspiring", "profile": "knowledge"}
    return {"rate": _NORMAL_PACE_RATE, "pace": "normal", "profile": "neutral"}


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
