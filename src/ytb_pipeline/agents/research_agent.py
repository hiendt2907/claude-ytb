"""ResearchAgent — wrap `ideation/research.py` (trending + hashtag) thành agent.

Không có `YOUTUBE_API_KEY` -> graceful degrade: trả output rỗng (không raise),
để pipeline vẫn chạy tiếp với context nghèo hơn thay vì chết cứng.
"""

from __future__ import annotations

import time
from typing import Any

from ..config.settings import settings
from ..ideation import research as research_mod
from .base import AgentResult, AgentStatus


class ResearchAgent:
    name = "research"

    @property
    def required_context_keys(self) -> list[str]:
        return ["topic", "type_of_vid"]

    def can_run(self, context: dict[str, Any]) -> bool:
        return "topic" in context

    async def run(self, context: dict[str, Any]) -> AgentResult:
        start = time.monotonic()
        try:
            if not settings.youtube_api_key:
                return AgentResult(
                    agent_name=self.name,
                    status=AgentStatus.SUCCESS,
                    output={
                        "trending_tags": [],
                        "related_topics": [],
                        "hashtag_pool": [],
                    },
                    latency_ms=_elapsed_ms(start),
                )

            region = context.get("region", "VN")
            result = research_mod.research_trending(region=region)
            seo_pool = result.get("seo_pool", {})
            related_topics = [item["topic"] for item in result.get("research", [])]

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                output={
                    "trending_tags": seo_pool.get("keywords", []),
                    "related_topics": related_topics,
                    "hashtag_pool": seo_pool.get("hashtags", []),
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


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
