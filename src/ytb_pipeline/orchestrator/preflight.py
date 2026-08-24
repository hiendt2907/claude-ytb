"""Offline, side-effect-free admission checks for batch video scripts."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.settings import settings
from ..content_contract import chars_per_min_for_provider, contract_for, estimate_duration_sec
from ..ideation.generator import load_script
from ..ideation.script_contract import validate_script_payload
from ..providers.registry import get_voice_provider
from ..render.asset_catalog import AssetCatalog

MIN_FREE_DISK_BYTES = 10 * 1024**3


@dataclass(frozen=True)
class PreflightFailure:
    code: str
    message: str
    path: str = ""


@dataclass(frozen=True)
class PreflightResult:
    script_path: Path
    failures: tuple[PreflightFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def preflight_script(script_path: Path | str) -> PreflightResult:
    """Collect every local admission failure without calling a cloud provider."""
    path = Path(script_path)
    failures: list[PreflightFailure] = []
    payload = _read_payload(path, failures)
    if payload is None:
        return PreflightResult(path, tuple(failures))

    _validate_schema(payload, failures)
    script = _load_script(path, failures)
    _validate_runtime(script, failures)
    _validate_orientation(script, failures)
    _validate_tts(failures)
    _validate_local_assets(payload, failures)
    _validate_thumbnail(payload, failures)
    _validate_disk(failures)
    return PreflightResult(path, tuple(failures))


def format_preflight_result(result: PreflightResult) -> str:
    """Human-readable, deterministic output for the read-only CLI command."""
    if result.passed:
        return f"✓ {result.script_path}: preflight passed"
    lines = [f"✗ {result.script_path}: {len(result.failures)} preflight failure(s)"]
    lines.extend(f"  [{failure.code}] {failure.path}: {failure.message}" for failure in result.failures)
    return "\n".join(lines)


def _read_payload(path: Path, failures: list[PreflightFailure]) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(PreflightFailure("json.invalid", f"Không đọc được JSON script: {exc}", str(path)))
        return None
    if not isinstance(raw, dict):
        failures.append(PreflightFailure("json.object_required", "Script JSON phải là object.", str(path)))
        return None
    return raw


def _validate_schema(payload: dict[str, Any], failures: list[PreflightFailure]) -> None:
    result = validate_script_payload(payload)
    for finding in result.findings:
        failures.append(PreflightFailure(finding.rule, finding.message, finding.path))


def _load_script(path: Path, failures: list[PreflightFailure]):
    try:
        return load_script(path)
    except (OSError, ValueError) as exc:
        failures.append(PreflightFailure("script.loadable", f"Không nạp được script: {exc}", str(path)))
        return None


def _validate_runtime(script: Any, failures: list[PreflightFailure]) -> None:
    if script is None:
        return
    estimated = estimate_duration_sec(
        sum(len(segment.narration) for segment in script.segments),
        # Same format-specific rate the prompt planned with, so admission and
        # generation cannot disagree about how long a script will speak.
        chars_per_minute=chars_per_min_for_provider(
            settings.tts_provider, video_type=script.video_type,
        ),
    )
    try:
        contract_for(script.video_type).validate_audio_runtime(estimated, segment_count=len(script.segments))
    except ValueError as exc:
        failures.append(PreflightFailure("duration.estimated", str(exc)))


def _validate_orientation(script: Any, failures: list[PreflightFailure]) -> None:
    if script is None:
        return
    expected = {"short": "portrait", "long": "landscape"}.get(script.video_type)
    if expected is None or settings.orientation != expected:
        failures.append(PreflightFailure(
            "orientation.matches_video_type",
            f"{script.video_type} cần orientation={expected}; cấu hình hiện tại là {settings.orientation}.",
        ))


def _validate_tts(failures: list[PreflightFailure]) -> None:
    provider = get_voice_provider(settings.tts_provider)
    if not provider.is_available():
        failures.append(PreflightFailure(
            "tts.available",
            f"TTS provider '{settings.tts_provider}' chưa sẵn sàng.",
        ))


def _validate_local_assets(payload: dict[str, Any], failures: list[PreflightFailure]) -> None:
    catalog = AssetCatalog()
    orientation = settings.orientation
    assets = catalog.assets_readonly()
    for index, section in enumerate(payload.get("sections", ())):
        if not isinstance(section, dict):
            continue
        query = str(section.get("pexels_query") or section.get("broll") or "").strip()
        if not query:
            continue
        if not catalog.select_local_assets(query, orientation=orientation, assets=assets):
            failures.append(PreflightFailure(
                "asset.local_missing",
                f"Không có B-roll local phù hợp cho section {index + 1}: '{query}'.",
                f"sections[{index}].pexels_query",
            ))


def _validate_thumbnail(payload: dict[str, Any], failures: list[PreflightFailure]) -> None:
    brief = payload.get("thumbnail_brief")
    fields = ("visual_contradiction", "subject", "emotion", "headline")
    if not isinstance(brief, dict) or any(not str(brief.get(field) or "").strip() for field in fields):
        failures.append(PreflightFailure(
            "thumbnail_brief.incomplete",
            "thumbnail_brief phải đủ visual_contradiction, subject, emotion và headline.",
            "thumbnail_brief",
        ))


def _validate_disk(failures: list[PreflightFailure]) -> None:
    free = shutil.disk_usage(settings.assets_dir).free
    if free < MIN_FREE_DISK_BYTES:
        failures.append(PreflightFailure(
            "disk.free_space",
            f"Cần ít nhất {MIN_FREE_DISK_BYTES // 1024**3} GB trống để render batch.",
        ))
