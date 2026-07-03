"""StoryArchitectAgent — dựng outline 3-act (problem -> mechanism -> solution)
qua LLMProvider (claude CLI mặc định, hoặc ollama local qua
`settings.llm_provider`). Provider không khả dụng -> placeholder outline,
KHÔNG raise (graceful degrade, giống ResearchAgent thiếu API key).
"""

from __future__ import annotations

import time
from typing import Any

from ..providers.registry import get_llm_provider
from .base import AgentResult, AgentStatus


class StoryArchitectAgent:
    name = "story_architect"

    @property
    def required_context_keys(self) -> list[str]:
        return ["topic", "research", "type_of_vid"]

    def can_run(self, context: dict[str, Any]) -> bool:
        return all(key in context for key in self.required_context_keys)

    async def run(self, context: dict[str, Any]) -> AgentResult:
        start = time.monotonic()
        try:
            topic = context.get("topic", "")
            type_of_vid = context.get("type_of_vid", "")

            llm_provider = get_llm_provider()
            if not llm_provider.is_available():
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    output={"outline": _placeholder_outline(topic)},
                    latency_ms=_elapsed_ms(start),
                )

            prompt = self._build_prompt(topic, type_of_vid, context.get("research", {}))
            try:
                raw = await llm_provider.complete(prompt)
            except Exception:
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    output={"outline": _placeholder_outline(topic)},
                    latency_ms=_elapsed_ms(start),
                )

            outline = _parse_outline(raw, topic)
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                output={"outline": outline},
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

    def _build_prompt(self, topic: str, type_of_vid: str, research: dict) -> str:
        return (
            f"Dựng outline 3-act (problem -> mechanism -> solution) cho video "
            f"'{type_of_vid}' chủ đề '{topic}'. Research context: {research}."
        )


def _placeholder_outline(topic: str) -> dict:
    return {
        "acts": [
            {"act": "problem", "summary": f"Vấn đề liên quan tới {topic}."},
            {"act": "mechanism", "summary": "Cơ chế/tại sao vấn đề xảy ra."},
            {"act": "solution", "summary": "Giải pháp/áp dụng thực tế."},
        ],
        "mechanism": "placeholder — claude CLI không khả dụng",
        "hook": f"Bạn có biết về {topic}?",
    }


def _parse_outline(raw: str, topic: str) -> dict:
    """Best-effort: claude trả text tự do, không ép JSON — bọc thô vào outline."""
    text = raw.strip()
    if not text:
        return _placeholder_outline(topic)
    return {
        "acts": [
            {"act": "problem", "summary": text},
            {"act": "mechanism", "summary": text},
            {"act": "solution", "summary": text},
        ],
        "mechanism": text,
        "hook": text.splitlines()[0] if text.splitlines() else topic,
    }


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
