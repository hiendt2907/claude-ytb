"""SEOAgent — tối ưu title/tags/hashtag, THUẦN rule-based (không gọi LLM).

Tái dùng `MetadataAdapter` (platform/metadata.py) để áp ràng buộc platform
(độ dài title, số hashtag...). Tính thêm `seo_score` (0-100) theo các quy tắc
clickbait/độ dài/generic đơn giản.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..platform.metadata import MetadataAdapter
from ..platform.profiles import get_profile
from .base import AgentResult, AgentStatus

_ALL_CAPS_WORD_RE = re.compile(r"\b[A-Z]{4,}\b")
_GENERIC_TITLES = {"video", "tutorial", "how to", "guide"}
_SCORE_MAX = 100.0
_PENALTY_ALL_CAPS = 20.0
_PENALTY_TOO_LONG = 15.0
_PENALTY_GENERIC = 25.0
_PENALTY_EMPTY_TAGS = 10.0
_MAX_SELECTED_TAGS = 10


class SEOAgent:
    name = "seo"

    @property
    def required_context_keys(self) -> list[str]:
        return ["title", "topic", "tags", "platform"]

    def can_run(self, context: dict[str, Any]) -> bool:
        return all(key in context for key in self.required_context_keys)

    async def run(self, context: dict[str, Any]) -> AgentResult:
        start = time.monotonic()
        try:
            title = context["title"]
            tags = list(context.get("tags", ()))
            platform = context["platform"]
            description = context.get("description", "")

            adapter = MetadataAdapter()
            adapted = adapter.adapt(title, description, tags, platform)

            selected_tags = adapted.tags[:_MAX_SELECTED_TAGS] or adapted.tags
            seo_score = self._score(title, tags, platform)

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                output={
                    "optimized_title": adapted.title,
                    "selected_tags": selected_tags,
                    "hashtags": adapted.hashtags,
                    "seo_score": seo_score,
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

    def _score(self, title: str, tags: list[str], platform: Any) -> float:
        score = _SCORE_MAX
        profile = get_profile(platform)

        if _ALL_CAPS_WORD_RE.search(title):
            score -= _PENALTY_ALL_CAPS
        if len(title) > profile.max_title_chars:
            score -= _PENALTY_TOO_LONG
        if title.strip().lower() in _GENERIC_TITLES:
            score -= _PENALTY_GENERIC
        if not tags:
            score -= _PENALTY_EMPTY_TAGS

        return max(0.0, score)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
