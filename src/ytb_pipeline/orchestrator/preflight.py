"""Offline, side-effect-free admission checks for batch video scripts."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analytics.quality_report import missing_required_purposes
from ..config.settings import settings
from ..content_contract import chars_per_min_for_provider, contract_for, estimate_duration_sec
from ..content_profiles import ContentProfile, ContentProfileError, load_content_profile
from ..ideation.generator import load_script
from ..ideation.script_contract import validate_script_payload
from ..providers.registry import get_render_provider, get_voice_provider
from ..render.asset_catalog import AssetCatalog

# Orientation is a property of the video format, not of ambient config.
_ORIENTATION_BY_VIDEO_TYPE = {"short": "portrait", "long": "landscape"}
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
    _validate_required_purposes(script, failures)
    _validate_orientation(script, failures)
    profile = _resolve_profile(payload, failures)
    if profile is not None:
        _validate_tts(failures, profile)
        _validate_render(failures, profile)
        _validate_local_assets(payload, failures, profile)
    _validate_thumbnail(payload, failures)
    _validate_disk(failures)
    return PreflightResult(path, tuple(failures))


def _resolve_profile(
    payload: dict[str, Any], failures: list[PreflightFailure]
) -> ContentProfile | None:
    try:
        return load_content_profile(
            str(payload.get("profile_id") or settings.content_profile_id)
        )
    except ContentProfileError as exc:
        if not any(failure.code == "profile.valid" for failure in failures):
            failures.append(PreflightFailure("profile.valid", str(exc), "profile_id"))
        return None


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
            (
                load_content_profile(script.content_profile_id).providers.tts
                if script.content_profile_version else settings.tts_provider
            ),
            video_type=script.video_type,
        ),
    )
    try:
        profile = (
            load_content_profile(script.content_profile_id)
            if script.content_profile_version else None
        )
        contract_for(script.video_type, profile).validate_audio_runtime(
            estimated, segment_count=len(script.segments)
        )
    except ValueError as exc:
        failures.append(PreflightFailure("duration.estimated", str(exc)))


def _validate_required_purposes(script: Any, failures: list[PreflightFailure]) -> None:
    """Reject offline what the pre-publish gate would reject after render.

    The release gate requires a fixed set of section purposes, but admission did
    not check them, so a Short missing `payoff` passed preflight, paid for TTS
    and a full render, and only then failed at publish.  Admission and release
    must reject the same script.
    """
    if script is None:
        return
    missing = missing_required_purposes(
        script.video_type, (segment.purpose for segment in script.segments),
    )
    for purpose in missing:
        failures.append(PreflightFailure(
            f"script.required_purpose.{purpose}",
            f"Kịch bản thiếu section purpose='{purpose}'; cổng trước publish sẽ chặn.",
        ))


def _validate_orientation(script: Any, failures: list[PreflightFailure]) -> None:
    """Check the script declares a format whose orientation is derivable.

    Deliberately NOT compared against `settings.orientation`: a funnel batch holds
    a landscape Long and its portrait Shorts together, and `build_env` already
    gives each queue item its own `ORIENTATION` before spawning the pipeline.
    Gating admission on the single ambient value rejected whichever format did
    not match it, so a real mixed batch could never run under `--loop`.
    """
    if script is None:
        return
    if script.video_type not in _ORIENTATION_BY_VIDEO_TYPE:
        failures.append(PreflightFailure(
            "orientation.matches_video_type",
            f"video_type '{script.video_type}' không xác định được orientation; "
            f"phải là một trong {sorted(_ORIENTATION_BY_VIDEO_TYPE)}.",
        ))


def _validate_tts(
    failures: list[PreflightFailure], profile: ContentProfile
) -> None:
    try:
        provider = get_voice_provider(profile.providers.tts)
    except ValueError as exc:
        failures.append(PreflightFailure("tts.available", str(exc)))
        return
    if not provider.is_available():
        failures.append(PreflightFailure(
            "tts.available",
            f"TTS provider '{profile.providers.tts}' chưa sẵn sàng.",
        ))


def _validate_render(
    failures: list[PreflightFailure], profile: ContentProfile
) -> None:
    try:
        provider = get_render_provider(profile.providers.render)
    except ValueError as exc:
        failures.append(PreflightFailure("render.available", str(exc)))
        return
    if not provider.is_available():
        failures.append(PreflightFailure(
            "render.available",
            f"Render provider '{profile.providers.render}' chưa sẵn sàng.",
        ))


def _validate_local_assets(
    payload: dict[str, Any], failures: list[PreflightFailure], profile: ContentProfile
) -> None:
    if profile.narrative_mode == "character_story":
        for index, section in enumerate(payload.get("sections", ())):
            if not isinstance(section, dict):
                continue
            relative = str(section.get("visual_asset") or "").strip()
            try:
                profile.visual_asset_path(relative)
            except (OSError, ValueError):
                failures.append(PreflightFailure(
                    "asset.profile_missing",
                    f"Không tìm thấy visual asset của profile cho section {index + 1}: '{relative}'.",
                    f"sections[{index}].visual_asset",
                ))
        return
    catalog = AssetCatalog()
    orientation = _ORIENTATION_BY_VIDEO_TYPE.get(
        str(payload.get("video_type") or "").strip().lower(), settings.orientation
    )
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
