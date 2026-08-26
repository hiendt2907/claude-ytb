"""Structured failure memory and recovery hints for local script ideation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_QA_CODES = {
    "hook": "QA_HOOK_WEAK",
    "central_mechanism": "QA_CENTRAL_MECHANISM",
    "length": "QA_LENGTH",
    "intro": "QA_INTRO",
    "compliance": "QA_COMPLIANCE",
    "series_semantic_dedup": "QA_SERIES_SEMANTIC_DEDUP",
}

_RECOVERY = {
    "IDEATION_JSON_INVALID": (
        "Archive this malformed response with its parse error, then Regenerate one complete JSON candidate. "
        "Do not ask for an in-place repair or reuse partial narration."
    ),
    "QA_HOOK_WEAK": (
        "Rewrite only the opening: preserve the topic and its profile-declared opening contract; "
        "put a concrete question, stake, or tension in the first 28 spoken words as that contract requires."
    ),
    "QA_CENTRAL_MECHANISM": (
        "Keep one named mechanism only. Rewrite generic CTA phrases such as 'các cơ chế khiến…' "
        "without the word 'cơ chế', and describe secondary factors as context or consequences."
    ),
    "VALIDATION_LONG_LENGTH": (
        "Keep the existing valid sections and add topic-specific narration until the required runtime is met."
    ),
    "QA_SERIES_SEMANTIC_DEDUP": (
        "Replace the title, topic, and all narration with a genuinely different named mechanism, "
        "not a paraphrase of the conflicting topic in Issues. Keep the video type, target runtime, "
        "funnel fields, and CTA contract unchanged."
    ),
}


def classify_ideation_failure(validation_error: str | None, qa: dict[str, Any] | None) -> str:
    """Return a stable code for reports, repair policy, and later aggregation."""
    for violation in (qa or {}).get("violations", []) or []:
        rule = str(violation.get("rule", ""))
        if rule in _QA_CODES:
            return _QA_CODES[rule]
    detail = (validation_error or "").lower()
    if "json" in detail and ("không trả" in detail or "decode" in detail or "unterminated" in detail):
        return "IDEATION_JSON_INVALID"
    if "quá mỏng" in detail or "quá dài" in detail or "target_minutes" in detail:
        return "VALIDATION_LONG_LENGTH"
    if "video_type" in detail or "target_minutes" in detail:
        return "VALIDATION_SCHEMA"
    return "IDEATION_UNCLASSIFIED"


def recovery_directive(validation_error: str | None, qa: dict[str, Any] | None) -> str:
    return _RECOVERY.get(classify_ideation_failure(validation_error, qa), "")


def record_ideation_failure(
    report_path: Path,
    *,
    script_name: str,
    attempt: int,
    validation_error: str | None,
    qa: dict[str, Any] | None,
) -> None:
    """Append a durable, machine-readable failure event without secrets or full scripts."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code": classify_ideation_failure(validation_error, qa),
        "script": script_name,
        "attempt": attempt,
        "validation_error": validation_error,
        "violations": (qa or {}).get("violations", []),
    }
    with report_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
