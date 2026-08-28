"""Offline, side-effect-free admission checks for batch video scripts."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analytics.quality_report import missing_required_purposes
from ..config.settings import settings
from ..content_contract import contract_for, effective_chars_per_min, estimate_duration_sec
from ..content_profiles import ContentProfile, ContentProfileError, load_content_profile
from ..ideation.generator import load_script
from ..ideation.script_contract import validate_script_payload
from ..providers.registry import (
    get_llm_provider,
    get_render_provider,
    get_story_image_provider,
    get_voice_provider,
)
from ..providers.vision import get_visual_judge
from ..render.audio_mixer import _validate_audio_asset
from ..render.asset_catalog import AssetCatalog
from ..render.visual_judge import JudgeInfrastructureError

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


def preflight_script(
    script_path: Path | str,
    *,
    live_providers: bool = False,
    publish: bool = False,
) -> PreflightResult:
    """Collect effective admission failures before expensive production work.

    The default remains local/offline for queue admission and the automated
    suite. Operators may explicitly request live, non-generating capability
    checks (ComfyUI inventory, xKiro vision catalog and OAuth refresh) before
    a supervised production run.
    """
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
        _validate_provider_configuration(profile, failures)
        _validate_llm(failures, profile)
        _validate_tts(failures, profile)
        _validate_render(failures, profile)
        _validate_story_generation(profile, failures, live=live_providers)
        _validate_profile_audio(profile, failures)
        _validate_local_assets(payload, failures, profile)
    _validate_thumbnail(payload, failures)
    _validate_runtime_tools(failures)
    _validate_writable_directories(failures)
    if publish:
        _validate_publish_configuration(failures, live=live_providers)
    _validate_disk(failures)
    return PreflightResult(path, tuple(failures))


def _validate_provider_configuration(
    profile: ContentProfile, failures: list[PreflightFailure]
) -> None:
    xkiro_roles = [
        role
        for role, provider in (
            ("LLM", profile.providers.llm),
            ("TTS", profile.providers.tts),
            (
                "Vision Judge",
                profile.visual_generation.visual_judge.provider
                if profile.visual_generation
                and profile.visual_generation.visual_judge
                and profile.visual_generation.visual_judge.enabled
                else "",
            ),
        )
        if provider == "xkiro"
    ]
    if xkiro_roles and not settings.xkiro_api_key.strip():
        failures.append(PreflightFailure(
            "xkiro.config",
            "XKIRO_API_KEY chưa được cấu hình cho: " + ", ".join(xkiro_roles) + ".",
        ))


def _validate_llm(
    failures: list[PreflightFailure], profile: ContentProfile
) -> None:
    try:
        provider = get_llm_provider(profile.providers.llm)
    except ValueError as exc:
        failures.append(PreflightFailure("llm.available", str(exc)))
        return
    if not provider.is_available():
        failures.append(PreflightFailure(
            "llm.available",
            f"LLM provider '{profile.providers.llm}' chưa sẵn sàng.",
        ))


def _validate_story_generation(
    profile: ContentProfile,
    failures: list[PreflightFailure],
    *,
    live: bool,
) -> None:
    visual = profile.visual_generation
    if profile.narrative_mode != "character_story" or visual is None or not visual.enabled:
        return

    try:
        story_provider = get_story_image_provider(settings.story_image_provider)
    except ValueError as exc:
        failures.append(PreflightFailure("story_generation.config", str(exc)))
        story_provider = None

    # Profile loading already validates these paths; repeat the concrete media
    # check here so an operator gets a readiness-specific finding if a file was
    # deleted between load and execution.
    for character_id in visual.characters:
        try:
            reference = profile.character_reference_path(character_id)
        except ContentProfileError as exc:
            failures.append(PreflightFailure(
                "story_generation.reference",
                str(exc),
                f"visual_generation.characters.{character_id}",
            ))
        else:
            if not reference.is_file():
                failures.append(PreflightFailure(
                    "story_generation.reference",
                    f"Thiếu ảnh identity cho nhân vật '{character_id}': {reference}",
                    f"visual_generation.characters.{character_id}",
                ))
    if visual.duo_reference_image:
        try:
            duo_reference = profile.duo_reference_path()
        except ContentProfileError as exc:
            failures.append(PreflightFailure(
                "story_generation.reference", str(exc), "visual_generation.duo_reference_image"
            ))
        else:
            if not duo_reference.is_file():
                failures.append(PreflightFailure(
                    "story_generation.reference",
                    f"Thiếu ảnh duo identity: {duo_reference}",
                    "visual_generation.duo_reference_image",
                ))

    if live and story_provider is not None:
        try:
            ok, detail = story_provider.availability_status()
        except (OSError, ValueError) as exc:
            ok, detail = False, str(exc)
        if not ok:
            failures.append(PreflightFailure(
                "story_generation.live",
                f"Story image provider chưa sẵn sàng: {detail}",
            ))

    judge_policy = visual.visual_judge
    if visual.selection_policy != "vlm_ranked" or not judge_policy or not judge_policy.enabled:
        return
    try:
        judge = get_visual_judge(judge_policy.provider, judge_policy.model)
    except (ValueError, JudgeInfrastructureError) as exc:
        failures.append(PreflightFailure("visual_judge.config", str(exc)))
        return
    if not live:
        return
    verifier = getattr(getattr(judge, "transport", None), "verify_vision_model", None)
    if not callable(verifier):
        failures.append(PreflightFailure(
            "visual_judge.live",
            "VisualJudge adapter không có capability check cho image model.",
        ))
        return
    try:
        verifier(judge_policy.model)
    except (JudgeInfrastructureError, OSError, ValueError) as exc:
        failures.append(PreflightFailure("visual_judge.live", str(exc)))


def _validate_profile_audio(
    profile: ContentProfile, failures: list[PreflightFailure]
) -> None:
    audio = profile.render.audio
    configured = []
    if audio.background_music is not None:
        configured.append(("background_music", audio.background_music.asset))
    configured.extend((f"sfx[{index}]", effect.asset) for index, effect in enumerate(audio.sfx))
    for label, relative in configured:
        path = profile.assets_dir / relative
        try:
            _validate_audio_asset(path)
        except (OSError, ValueError) as exc:
            failures.append(PreflightFailure(
                "audio.media",
                str(exc),
                f"render.audio.{label}.asset",
            ))


def _validate_runtime_tools(failures: list[PreflightFailure]) -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            failures.append(PreflightFailure(
                f"runtime.{binary}", f"Không tìm thấy '{binary}' trong PATH."
            ))


def _validate_writable_directories(failures: list[PreflightFailure]) -> None:
    for label, configured in (
        ("assets", settings.assets_dir),
        ("projects", settings.projects_dir),
        ("output", settings.output_dir),
    ):
        path = Path(configured)
        probe = path if path.exists() else path.parent
        if not probe.is_dir() or not os.access(probe, os.W_OK):
            failures.append(PreflightFailure(
                "filesystem.writable",
                f"Thư mục {label} không ghi được: {path}",
                str(path),
            ))


def _validate_publish_configuration(
    failures: list[PreflightFailure], *, live: bool
) -> None:
    paths = (
        ("youtube.client_secrets", Path(settings.youtube_client_secrets)),
        ("youtube.oauth_token", Path(settings.youtube_token_file)),
    )
    if settings.drive_backup:
        paths += (("drive.oauth_token", Path(settings.drive_token_file)),)
    for code, path in paths:
        if not path.is_file():
            failures.append(PreflightFailure(code, f"Thiếu credential file: {path}", str(path)))
    if settings.youtube_privacy not in {"private", "unlisted", "public"}:
        failures.append(PreflightFailure(
            "youtube.privacy",
            f"YOUTUBE_PRIVACY không hợp lệ: {settings.youtube_privacy!r}.",
        ))
    if not live:
        return

    from ..publish.youtube_auth import DRIVE_SCOPES, YOUTUBE_SCOPES
    from .doctor import _check_oauth_token

    oauth_checks = [
        _check_oauth_token("YouTube OAuth token", settings.youtube_token_file, YOUTUBE_SCOPES)
    ]
    if settings.drive_backup:
        oauth_checks.append(
            _check_oauth_token("Drive OAuth token", settings.drive_token_file, DRIVE_SCOPES)
        )
    for label, ok, detail in oauth_checks:
        if not ok:
            failures.append(PreflightFailure(
                "publish.oauth_live", f"{label}: {detail}"
            ))


def _resolve_profile(
    payload: dict[str, Any], failures: list[PreflightFailure]
) -> ContentProfile | None:
    try:
        return load_content_profile(
            str(payload.get("profile_id") or settings.content_profile_id),
            version=str(payload.get("profile_version") or "").strip() or None,
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
    profile = (
        load_content_profile(script.content_profile_id, version=script.content_profile_version)
        if script.content_profile_version else None
    )
    estimated = estimate_duration_sec(
        sum(len(segment.narration) for segment in script.segments),
        # Same format-specific rate (+ profile pace factor) the prompt
        # planned with, so admission and generation cannot disagree about
        # how long a script will speak.
        chars_per_minute=effective_chars_per_min(
            profile.providers.tts if profile else settings.tts_provider,
            video_type=script.video_type,
            content_profile=profile,
        ),
    )
    try:
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
    profile = (
        load_content_profile(script.content_profile_id, version=script.content_profile_version)
        if script.content_profile_version else None
    )
    required_purposes = (
        profile.editorial_contract.purpose_policy.required if profile is not None else None
    )
    missing = missing_required_purposes(
        script.video_type, (segment.purpose for segment in script.segments),
        required_purposes=required_purposes,
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
        auto_visuals = profile.visual_generation is not None and profile.visual_generation.enabled
        for index, section in enumerate(payload.get("sections", ())):
            if not isinstance(section, dict):
                continue
            relative = str(section.get("visual_asset") or "").strip()
            if not relative:
                # Auto-generate profile: scene_characters thay visual_asset,
                # đã được _validate_schema (script_contract) kiểm ở bước
                # trước trong preflight_script — không kiểm trùng ở đây.
                if auto_visuals:
                    continue
                failures.append(PreflightFailure(
                    "asset.profile_missing",
                    f"Không tìm thấy visual asset của profile cho section {index + 1}: '{relative}'.",
                    f"sections[{index}].visual_asset",
                ))
                continue
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
