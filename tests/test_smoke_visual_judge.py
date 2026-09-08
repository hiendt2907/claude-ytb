"""Offline tests for the explicit Phase-11 operator smoke command."""
from __future__ import annotations

from pathlib import Path

import pytest

from ytb_pipeline.render.visual_judge import CandidateEvaluation, JudgeResult


class _ProbeJudge:
    def __init__(self, *, correct=True):
        self.correct = correct
        self.calls = []

    def evaluate(self, request, candidates, context):
        self.calls.append((request, candidates, context))
        assert len(candidates) == 1
        payload = Path(candidates[0].local_path).read_bytes()
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        reasons = (
            "observed_color=blue",
            "observed_shape=triangle" if self.correct else "observed_shape=circle",
        )
        return JudgeResult(
            (
                CandidateEvaluation(
                    candidates[0].asset_id,
                    0.9,
                    0.9,
                    0.9,
                    0.9,
                    reasons=reasons,
                ),
            ),
            "xkiro",
            "qwen/qwen3.8-max:free",
        )


def test_status_reports_explicit_provider_model_and_adapter_state(monkeypatch, capsys):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.tools import smoke_visual_judge

    monkeypatch.setattr(settings, "visual_judge_provider", "xkiro", raising=False)
    monkeypatch.setattr(settings, "visual_judge_model", "qwen/qwen3.8-max:free", raising=False)
    monkeypatch.setattr(settings, "xkiro_api_key", "test-key", raising=False)

    assert smoke_visual_judge.main(["--status"]) == 0
    output = capsys.readouterr().out
    assert "semantic judge configured: yes" in output
    assert "vision-capable adapter registered: yes" in output
    assert "vision-capable adapter active: yes" in output
    assert "provider: xkiro" in output
    assert "model: qwen/qwen3.8-max:free" in output


def test_generated_probe_proves_image_fact_and_cleans_temp_media(monkeypatch, capsys):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.tools import smoke_visual_judge

    monkeypatch.setattr(settings, "visual_judge_provider", "xkiro", raising=False)
    monkeypatch.setattr(settings, "visual_judge_model", "qwen/qwen3.8-max:free", raising=False)
    fake = _ProbeJudge()
    monkeypatch.setattr(smoke_visual_judge, "get_visual_judge", lambda provider, model: fake)

    assert smoke_visual_judge.main(["--generate-probe"]) == 0

    output = capsys.readouterr().out
    assert "IMAGE_TRANSPORT_PROBE: PASS" in output
    assert "observed_color=blue" in output
    assert "observed_shape=triangle" in output
    assert len(fake.calls) == 1
    candidate_path = Path(fake.calls[0][1][0].local_path)
    assert not candidate_path.exists()


def test_generated_probe_exits_nonzero_when_observed_fact_is_wrong(monkeypatch, capsys):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.tools import smoke_visual_judge

    monkeypatch.setattr(settings, "visual_judge_provider", "xkiro", raising=False)
    monkeypatch.setattr(settings, "visual_judge_model", "qwen/qwen3.8-max:free", raising=False)
    monkeypatch.setattr(smoke_visual_judge, "get_visual_judge", lambda provider, model: _ProbeJudge(correct=False))

    assert smoke_visual_judge.main(["--generate-probe"]) == 1
    assert "IMAGE_TRANSPORT_PROBE: FAIL" in capsys.readouterr().err


def test_manual_image_smoke_uses_configured_adapter_and_strict_result(tmp_path, monkeypatch, capsys):
    from PIL import Image

    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.tools import smoke_visual_judge

    path = tmp_path / "manual.png"
    Image.new("RGB", (16, 16), (0, 0, 255)).save(path)
    monkeypatch.setattr(settings, "visual_judge_provider", "xkiro", raising=False)
    monkeypatch.setattr(settings, "visual_judge_model", "qwen/qwen3.8-max:free", raising=False)
    fake = _ProbeJudge()
    monkeypatch.setattr(smoke_visual_judge, "get_visual_judge", lambda provider, model: fake)

    assert smoke_visual_judge.main(["--image", str(path), "--intent", "Inspect this local image."]) == 0
    output = capsys.readouterr().out
    assert "VISUAL_JUDGE_SMOKE: PASS" in output
    assert "asset_id=smoke-candidate-00" in output
    assert path.exists()


def test_smoke_requires_explicit_config(monkeypatch, capsys):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.tools import smoke_visual_judge

    monkeypatch.setattr(settings, "visual_judge_provider", "", raising=False)
    monkeypatch.setattr(settings, "visual_judge_model", "", raising=False)

    assert smoke_visual_judge.main(["--generate-probe"]) == 2
    assert "VISUAL_JUDGE_PROVIDER" in capsys.readouterr().err


def test_settings_fail_fast_when_only_one_smoke_setting_is_configured():
    from pydantic import ValidationError

    from ytb_pipeline.config.settings import Settings

    with pytest.raises(ValidationError, match="VISUAL_JUDGE_PROVIDER"):
        Settings(
            _env_file=None,
            visual_judge_provider="xkiro",
            visual_judge_model="",
        )
