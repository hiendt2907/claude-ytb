"""Passive, local recovery observations for failed pipeline runs.

This module deliberately classifies and records failures only.  It does not
start a process, call an LLM or provider, alter schedules, or upload anything.
The operator (or a separately authorised command) must decide whether to act
on the proposed recovery plan.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from .recovery_contract import recovery_for_failure
from .state_io import atomic_write_json


_STAGE_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\[2/4\] Voiceover\s*▶"), "voiceover"),
    (re.compile(r"^\[3/4\] Render\s*▶.*\(ai/"), "ai-render"),
    (re.compile(r"^\[3/4\] Render\s*▶"), "render"),
    (re.compile(r"^\[4/4\] Publish\s*▶"), "publish"),
)


@dataclass(frozen=True)
class RecoveryReport:
    """A normalized, non-executing recommendation for one observed failure."""

    slug: str
    stage: str
    recovery_code: str
    proposed_action: str
    retryable: bool
    max_attempts: int
    requires_operator: bool
    log_pointer: str | None
    artifact_pointer: str | None
    automatic_action: bool = False


def build_recovery_report(
    *,
    slug: str,
    failure_output: str,
    stage: str | None = None,
    log_path: Path | str | None = None,
    artifact_path: Path | str | None = None,
) -> RecoveryReport:
    """Classify a failure without retaining its raw output in the report.

    ``stage`` is used when a caller has an authoritative checkpoint stage.
    Otherwise, the latest known stage marker in the captured pipeline output is
    used.  The recovery contract remains the source of truth and can override
    an unknown marker when the failure itself proves the stage (for example an
    OAuth reauthentication failure).
    """
    observed_stage = _normalize_stage(stage) if stage else _detect_stage(failure_output)
    plan = recovery_for_failure(observed_stage, failure_output)
    return RecoveryReport(
        slug=slug,
        stage=plan.stage,
        recovery_code=plan.code,
        proposed_action=plan.action,
        retryable=plan.retryable,
        max_attempts=plan.max_attempts,
        requires_operator=plan.requires_operator,
        log_pointer=_pointer(log_path),
        artifact_pointer=_pointer(artifact_path),
    )


def write_recovery_report(
    report_dir: Path,
    *,
    slug: str,
    failure_output: str,
    stage: str | None = None,
    log_path: Path | str | None = None,
    artifact_path: Path | str | None = None,
) -> Path:
    """Write one immutable local JSON report and return its path.

    The artifact contains normalized recovery metadata and evidence pointers,
    not raw subprocess output, which can contain credentials or private data.
    """
    report = build_recovery_report(
        slug=slug,
        failure_output=failure_output,
        stage=stage,
        log_path=log_path,
        artifact_path=artifact_path,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{_safe_filename_part(slug)}_{timestamp}_{report.recovery_code}.json"
    path = Path(report_dir) / filename
    payload = {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **asdict(report)}
    atomic_write_json(path, payload)
    return path


def _detect_stage(output: str) -> str:
    stage = "unknown"
    for line in output.splitlines():
        for pattern, candidate in _STAGE_MARKERS:
            if pattern.search(line):
                stage = candidate
                break
    return stage


def _normalize_stage(stage: str | None) -> str:
    return (stage or "unknown").removeprefix("running-").strip().lower() or "unknown"


def _pointer(value: Path | str | None) -> str | None:
    return str(value) if value is not None else None


def _safe_filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-") or "unknown"
