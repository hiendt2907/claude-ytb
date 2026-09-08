"""Focused tests for the passive pipeline recovery report artifact."""

from __future__ import annotations

import json


def test_build_recovery_report_detects_latest_stage_and_safe_action():
    from ytb_pipeline.orchestrator.recovery_report import build_recovery_report

    report = build_recovery_report(
        slug="choice-overload",
        failure_output=(
            "[2/4] Voiceover ▶ edge-tts\n"
            "edge_tts.exceptions.NoAudioReceived: No audio was received"
        ),
        log_path="assets/batch_logs/choice-overload.log",
        artifact_path="assets/audio/choice-overload.mp3",
    )

    assert report.slug == "choice-overload"
    assert report.stage == "voiceover"
    assert report.recovery_code == "VOICEOVER_TTS_TRANSIENT"
    assert report.proposed_action == "resume_cached_segments_then_retry"
    assert report.log_pointer == "assets/batch_logs/choice-overload.log"
    assert report.artifact_pointer == "assets/audio/choice-overload.mp3"
    assert report.automatic_action is False


def test_explicit_running_stage_is_normalized_and_publish_never_retries():
    from ytb_pipeline.orchestrator.recovery_report import build_recovery_report

    report = build_recovery_report(
        slug="ambiguous-upload",
        failure_output="socket.timeout: timed out",
        stage="running-publish",
        log_path="assets/batch_logs/ambiguous-upload.log",
    )

    assert report.stage == "publish"
    assert report.recovery_code == "PUBLISH_AMBIGUOUS_RESULT"
    assert report.proposed_action == "preserve_upload_evidence_then_require_verify"
    assert report.retryable is False
    assert report.requires_operator is True


def test_write_recovery_report_persists_only_normalized_observation(tmp_path):
    from ytb_pipeline.orchestrator.recovery_report import write_recovery_report

    path = write_recovery_report(
        tmp_path,
        slug="render-failure",
        failure_output="token=should-not-be-persisted\nValueError: renderer invariant",
        stage="render",
        log_path="assets/batch_logs/render-failure.log",
        artifact_path="assets/output/render-failure.mp4",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["stage"] == "render"
    assert payload["recovery_code"] == "RENDER_UNKNOWN"
    assert payload["proposed_action"] == "preserve_log_and_require_review"
    assert payload["log_pointer"] == "assets/batch_logs/render-failure.log"
    assert payload["artifact_pointer"] == "assets/output/render-failure.mp4"
    assert "should-not-be-persisted" not in path.read_text(encoding="utf-8")
