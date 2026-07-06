"""Focused tests for remaining local-first migration requirements."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _script_payload(video_type: str = "ai_video") -> dict:
    return {
        "topic": "T",
        "title": "Title",
        "description": "Desc",
        "tags": ["tag"],
        "sections": [
            {
                "caption": "cap",
                "narration": (
                    "Một cơ chế nhỏ có thể đổi cách ta nhìn hành vi. "
                    "Nó không phải lời khuyên chung chung mà là cách não xử lý tín hiệu. "
                ) * 10,
                "broll": "abstract brain mechanism",
                "video_type": video_type,
                "hook": True,
                "emphasis": ["cơ chế", "tín hiệu"],
            }
        ],
        "compliance": {
            "passed": True,
            "community": "ok",
            "copyright": "ok",
            "accuracy": "ok",
            "advertiser": "ok",
            "coppa": "not for kids",
            "notes": "ok",
        },
    }


def test_load_script_preserves_segment_video_type(tmp_path):
    from ytb_pipeline.ideation.generator import load_script

    path = tmp_path / "script.json"
    path.write_text(json.dumps(_script_payload("ai_video"), ensure_ascii=False), encoding="utf-8")

    script = load_script(path)

    assert script.segments[0].video_type == "ai_video"


def test_render_rejects_removed_local_video_strategy(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.render import compose_ai

    monkeypatch.setattr(settings, "broll_strategy", "mixed")

    with pytest.raises(RuntimeError, match="BROLL_STRATEGY"):
        compose_ai._moving_background(
            "prompt",
            5.0,
            index=0,
            dims=(1080, 1920),
            landscape=False,
            work=tmp_path,
            prefix="seg00",
            used=set(),
        )


def test_local_benchmark_writes_report_for_available_and_missing_providers(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator.local_benchmark import run_local_benchmark
    from ytb_pipeline.providers.errors import ProviderUnavailableError

    class FakeLLM:
        name = "ollama"

        async def complete(self, *args, **kwargs):
            return "ok"

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    class MissingVoice:
        name = "vieneu"

        async def synthesise(self, *args, **kwargs):
            raise ProviderUnavailableError("missing")

        def is_available(self):
            return False

    class FakeImage:
        name = "flux"

        def generate(self, prompt, width, height, output_path, **kwargs):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(b"png")
            return Path(output_path)

        def is_available(self):
            return True

    class MissingVideo:
        name = "wan"

        def generate(self, *args, **kwargs):
            raise ProviderUnavailableError("missing")

        def is_available(self):
            return False

    monkeypatch.setattr("ytb_pipeline.orchestrator.local_benchmark.get_llm_provider", lambda: FakeLLM())
    monkeypatch.setattr("ytb_pipeline.orchestrator.local_benchmark.get_voice_provider", lambda name=None: MissingVoice())
    monkeypatch.setattr("ytb_pipeline.orchestrator.local_benchmark.get_image_provider", lambda name=None: FakeImage())
    monkeypatch.setattr("ytb_pipeline.orchestrator.local_benchmark.get_video_provider", lambda name=None: MissingVideo())

    report = run_local_benchmark(tmp_path / "benchmark.json")

    assert (tmp_path / "benchmark.json").exists()
    assert report["script_generation"]["ok"] is True
    assert report["tts"]["ok"] is False
    assert report["flux_image"]["ok"] is True
    assert report["local_video"]["ok"] is False
