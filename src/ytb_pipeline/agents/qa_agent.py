"""QAAgent — quality gate enforcer, THUẦN rule-based (không gọi LLM).

Chạy lại các cổng verify tương đương `ideation/generator.py` (length/intro/
compliance) trên dữ liệu script đã có trong context (không cần file), cộng
2 gate mới: niche self-help mantra + sourced claims (vd "studies show" thiếu
nguồn) + dedup theo `context["done_topics"]`.

`passed=False` => downstream agent KHÔNG được chạy tiếp (enforced bởi caller,
agent này chỉ báo cáo).
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..ideation import series as series_mod
from ..ideation.generator import (
    GREETING_PREFIX,
    LONG_MAX_MINUTES,
    LONG_MIN_MINUTES,
    SHORT_MAX_MINUTES,
    SHORT_MIN_MINUTES,
    estimate_minutes,
)
from .base import AgentResult, AgentStatus

_SELF_HELP_MANTRAS = (
    "just believe in yourself",
    "hãy tin vào bản thân",
    "bạn có thể làm được mọi thứ",
    "manifest your dreams",
)
_SOURCED_CLAIM_PHRASES = (
    "studies show",
    "nghiên cứu cho thấy",
    "các nhà khoa học",
    "research shows",
)
_SOURCE_HINTS = ("http://", "https://", "nguồn:", "source:", "doi:")


class QAAgent:
    name = "qa"

    @property
    def required_context_keys(self) -> list[str]:
        return ["script"]

    def can_run(self, context: dict[str, Any]) -> bool:
        return "script" in context

    async def run(self, context: dict[str, Any]) -> AgentResult:
        start = time.monotonic()
        try:
            script = context["script"]
            violations: list[dict[str, str]] = []
            warnings: list[dict[str, str]] = []

            violations.extend(_check_compliance(script))
            violations.extend(_check_length(script))
            violations.extend(_check_intro(script))
            violations.extend(_check_self_help(script))
            warnings.extend(_check_sourced_claims(script))
            violations.extend(_check_dedup(script, context.get("done_topics")))

            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                output={
                    "passed": len(violations) == 0,
                    "violations": violations,
                    "warnings": warnings,
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


# ---------------------------------------------------------------------------
# Gate helpers — đọc script dict/dataclass, KHÔNG mutate, KHÔNG raise (gom
# thành violation dict thay vì ValueError như generator.py bản file-based).
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _segments_of(script: Any) -> list[Any]:
    return list(_get(script, "segments", ()) or ())


def _narration_of(segment: Any) -> str:
    return _get(segment, "narration", "") or ""


def _check_compliance(script: Any) -> list[dict[str, str]]:
    compliance = _get(script, "compliance")
    passed = _get(compliance, "passed") if compliance is not None else None
    if compliance is None or passed is not True:
        return [{
            "rule": "compliance",
            "detail": "Thiếu khối compliance hoặc 'passed' != true.",
        }]
    return []


def _check_length(script: Any) -> list[dict[str, str]]:
    segments = _segments_of(script)
    if not segments:
        return [{"rule": "length", "detail": "Script không có segment narration."}]

    target_minutes = _get(script, "target_minutes")
    est = estimate_minutes(segments)

    if target_minutes is not None:
        if not (LONG_MIN_MINUTES <= target_minutes <= LONG_MAX_MINUTES):
            return [{
                "rule": "length",
                "detail": (
                    f"target_minutes={target_minutes} ngoài khoảng "
                    f"[{LONG_MIN_MINUTES}, {LONG_MAX_MINUTES}]."
                ),
            }]
        if est < target_minutes:
            return [{
                "rule": "length",
                "detail": f"Nội dung quá mỏng: ước lượng {est:.1f}p < target {target_minutes}p.",
            }]
        return []

    if est <= SHORT_MIN_MINUTES:
        return [{"rule": "length", "detail": f"Short quá ngắn: ước lượng {est:.2f}p."}]
    if est >= SHORT_MAX_MINUTES:
        return [{"rule": "length", "detail": f"Short quá dài: ước lượng {est:.2f}p."}]
    return []


def _check_intro(script: Any) -> list[dict[str, str]]:
    segments = _segments_of(script)
    if not segments:
        return []
    first = _narration_of(segments[0]).lstrip()
    is_long = _get(script, "target_minutes") is not None
    starts_with_greeting = first.startswith(GREETING_PREFIX)

    if is_long and not starts_with_greeting:
        return [{
            "rule": "intro",
            "detail": f"Video dài phải mở đầu bằng \"{GREETING_PREFIX}\".",
        }]
    if not is_long and starts_with_greeting:
        return [{
            "rule": "intro",
            "detail": f"Short KHÔNG được mở bằng \"{GREETING_PREFIX}\".",
        }]
    return []


def _check_self_help(script: Any) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for segment in _segments_of(script):
        narration_lower = _narration_of(segment).lower()
        for mantra in _SELF_HELP_MANTRAS:
            if mantra in narration_lower:
                violations.append({
                    "rule": "niche_self_help",
                    "detail": f"Phát hiện mantra self-help chung chung: '{mantra}'.",
                })
    return violations


def _check_sourced_claims(script: Any) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for segment in _segments_of(script):
        narration = _narration_of(segment)
        narration_lower = narration.lower()
        for phrase in _SOURCED_CLAIM_PHRASES:
            if phrase in narration_lower:
                has_source = any(hint in narration_lower for hint in _SOURCE_HINTS)
                if not has_source:
                    warnings.append({
                        "rule": "sourced_claims",
                        "detail": f"Cụm '{phrase}' không kèm nguồn rõ ràng.",
                    })
    return warnings


def _check_dedup(script: Any, done_topics: Any) -> list[dict[str, str]]:
    if not done_topics:
        return []
    candidates = [
        value
        for value in (
            _get(script, "topic", ""),
            _get(script, "title", ""),
        )
        if value
    ]
    if not candidates:
        return []
    done_slugs = {series_mod.slugify(t) for t in done_topics}
    for candidate in candidates:
        slug = series_mod.slugify(candidate)
        if slug in done_slugs:
            return [{
                "rule": "series_dedup",
                "detail": f"Chủ đề/title '{candidate}' (slug={slug}) đã có trong done_topics.",
            }]
    return []


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
