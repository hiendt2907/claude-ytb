"""Bounded recovery policy shared by batch workers and operator reports.

The contract intentionally separates failures that can safely be retried from
ones where another request could duplicate an upload, hide a content defect, or
spend another cloud completion.  It is pure so the same decision is testable in
the CLI, monitors, and future UI without making network calls.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryPlan:
    code: str
    stage: str
    retryable: bool
    max_attempts: int
    action: str
    requires_operator: bool = False


def recovery_for_failure(stage: str, output: str) -> RecoveryPlan:
    """Classify one observed failure into a bounded, safe next action."""
    normalized_stage = stage.removeprefix("running-").strip().lower() or "unknown"
    detail = output.casefold()

    if "reauthrequirederror" in detail or "ytb auth" in detail or "token has been revoked" in detail:
        return RecoveryPlan(
            "PUBLISH_REAUTH_REQUIRED", "publish", False, 0,
            "preserve_upload_evidence_then_require_ytb_auth", True,
        )
    if "schedule drift" in detail or "lệch lịch publish" in detail:
        return RecoveryPlan(
            "PUBLISH_SCHEDULE_DRIFT", "publish", False, 0,
            "preserve_verified_metadata_and_require_schedule_confirmation", True,
        )
    # A transport failure once publish has started is ambiguous: YouTube may
    # already have accepted the upload while the client lost its response.
    # Retrying the whole subprocess can create a duplicate public/private video.
    if normalized_stage == "publish":
        return RecoveryPlan(
            "PUBLISH_AMBIGUOUS_RESULT", "publish", False, 0,
            "preserve_upload_evidence_then_require_verify", True,
        )
    if "không trả json hợp lệ" in detail or "jsondecodeerror" in detail or "unterminated string" in detail:
        return RecoveryPlan(
            "IDEATION_JSON_INVALID", "ideation", True, 1,
            "archive_candidate_then_regenerate_once",
        )
    if normalized_stage == "ideation" or "ideationqualityfailure" in detail or "quality_status" in detail:
        return RecoveryPlan(
            "IDEATION_CONTRACT_REJECTED", "ideation", False, 0,
            "archive_candidate_and_require_editorial_replacement", True,
        )
    if "transcript_mismatch" in detail or "transcript_repeat" in detail or "duration_target_deviation" in detail:
        return RecoveryPlan(
            "VOICEOVER_CONTENT_MISMATCH", "voiceover", False, 0,
            "preserve_audio_report_and_require_voice_review", True,
        )
    if "noaudioreceived" in detail or "no audio was received" in detail:
        return RecoveryPlan(
            "VOICEOVER_TTS_TRANSIENT", "voiceover", True, 3,
            "resume_cached_segments_then_retry",
        )
    if "audio_missing" in detail or "audio_duration_unavailable" in detail:
        return RecoveryPlan(
            "VOICEOVER_ARTIFACT_INVALID", "voiceover", False, 0,
            "invalidate_audio_artifact_then_require_tts_review", True,
        )
    if "pexels" in detail or "ffmpeg" in detail or "render" in normalized_stage:
        if _is_transport_failure(detail):
            return RecoveryPlan(
                "RENDER_TRANSIENT", "render", True, 3,
                "resume_checkpoint_then_retry",
            )
        return RecoveryPlan(
            "RENDER_UNKNOWN", "render", False, 0,
            "preserve_log_and_require_review", True,
        )
    if _is_transport_failure(detail):
        return RecoveryPlan(
            "TRANSPORT_TRANSIENT", normalized_stage, True, 3,
            "resume_checkpoint_then_retry",
        )
    return RecoveryPlan(
        f"{normalized_stage.upper()}_UNKNOWN", normalized_stage, False, 0,
        "preserve_log_and_require_review", True,
    )


def _is_transport_failure(detail: str) -> bool:
    return any(marker in detail for marker in (
        "http error 409", "conflict", "http error 5", "temporary failure in name resolution",
        "broken pipe", "connection reset", "connectionerror", "timed out",
        "name or service not known",
    ))
