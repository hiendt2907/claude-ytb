"""Production stages are independently runnable after batch-start approval."""

import pytest
from types import SimpleNamespace

from ytb_pipeline import pipeline


def test_voiceover_stage_runs_only_approved_input_and_voiceover():
    assert pipeline.stage_names("voiceover") == ("input", "voiceover")


def test_publish_stage_runs_the_full_production_chain():
    assert pipeline.stage_names("publish") == ("input", "voiceover", "render", "publish")


def test_long_cannot_enter_renderer_with_portrait_orientation(monkeypatch):
    monkeypatch.setattr(pipeline.settings, "orientation", "portrait")

    with pytest.raises(ValueError, match="Long phải render landscape"):
        pipeline.validate_render_orientation("long")


def test_short_cannot_enter_renderer_with_landscape_orientation(monkeypatch):
    monkeypatch.setattr(pipeline.settings, "orientation", "landscape")

    with pytest.raises(ValueError, match="Short phải render portrait"):
        pipeline.validate_render_orientation("short")


def test_strict_audio_quality_blocks_before_render(monkeypatch):
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "strict", raising=False)
    failed_audio = SimpleNamespace(
        passed=False,
        issues=(SimpleNamespace(code="TRANSCRIPT_MISMATCH", message="Transcript lệch script."),),
    )

    with pytest.raises(ValueError, match="Audio quality gate chặn render"):
        pipeline.enforce_audio_quality(failed_audio)


def test_report_only_audio_quality_does_not_block(monkeypatch):
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report", raising=False)
    failed_audio = SimpleNamespace(
        passed=False,
        issues=(SimpleNamespace(code="TRANSCRIPT_MISMATCH", message="Transcript lệch script."),),
    )

    pipeline.enforce_audio_quality(failed_audio)
