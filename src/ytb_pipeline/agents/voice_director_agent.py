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

            if needs_clone:
                provider = "f5"
            elif segment_count >= _MANY_SEGMENTS_THRESHOLD:
                provider = "edge"
            else:
                provider = "edge"

            pause_adjustments = {
                "rate": _SLOW_PACE_RATE if has_code else _NORMAL_PACE_RATE,
                "pace": "slow" if has_code else "normal",
            }

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


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
