"""Regression tests for the bounded, no-surprise batch recovery policy."""

from ytb_pipeline.orchestrator.recovery_contract import recovery_for_failure


def test_tts_transport_failure_is_the_only_voiceover_failure_retried_automatically():
    plan = recovery_for_failure("voiceover", "edge_tts.exceptions.NoAudioReceived")

    assert plan.code == "VOICEOVER_TTS_TRANSIENT"
    assert plan.retryable is True
    assert plan.max_attempts == 3
    assert plan.action == "resume_cached_segments_then_retry"


def test_invalid_llm_json_is_archived_then_regenerated_once_not_repaired_in_place():
    plan = recovery_for_failure("ideation", "LLM không trả JSON hợp lệ: Unterminated string")

    assert plan.code == "IDEATION_JSON_INVALID"
    assert plan.retryable is True
    assert plan.max_attempts == 1
    assert plan.action == "archive_candidate_then_regenerate_once"


def test_audio_content_mismatch_stops_for_editorial_or_voice_profile_review():
    plan = recovery_for_failure("voiceover", "TRANSCRIPT_MISMATCH: Transcript local khớp script 71%")

    assert plan.retryable is False
    assert plan.action == "preserve_audio_report_and_require_voice_review"


def test_oauth_never_retries_or_uploads_again_automatically():
    plan = recovery_for_failure("publish", "ReauthRequiredError: token has been revoked")

    assert plan.code == "PUBLISH_REAUTH_REQUIRED"
    assert plan.retryable is False
    assert plan.requires_operator is True


def test_publish_timeout_never_retries_because_upload_result_is_ambiguous():
    plan = recovery_for_failure("running-publish", "socket.timeout: timed out")

    assert plan.code == "PUBLISH_AMBIGUOUS_RESULT"
    assert plan.retryable is False
    assert plan.action == "preserve_upload_evidence_then_require_verify"


def test_unknown_failure_fails_closed_with_log_evidence():
    plan = recovery_for_failure("render", "ValueError: unexpected renderer invariant")

    assert plan.code == "RENDER_UNKNOWN"
    assert plan.retryable is False
    assert plan.action == "preserve_log_and_require_review"
