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


def test_mixed_render_uses_cached_local_video_for_ai_video_segment(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.pkg.models import Segment
    from ytb_pipeline.render import compose_ai

    calls: list[Path] = []

    class FakeVideoProvider:
        name = "wan"

        def generate(self, prompt, duration_sec, width, height, output_path, **kwargs):
            calls.append(Path(output_path))
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(b"video")
            return Path(output_path)

        def is_available(self):
            return True

    monkeypatch.setattr(settings, "broll_strategy", "mixed")
    monkeypatch.setattr(settings, "video_provider", "wan")
    monkeypatch.setattr(compose_ai, "get_video_provider", lambda _name=None: FakeVideoProvider())
    monkeypatch.setattr(compose_ai, "_valid_clip", lambda path: Path(path).exists())

    seg = Segment(
        caption="cap",
        narration="n",
        broll="prompt",
        video_type="ai_video",
        hook=True,
        duration_sec=5.0,
    )

    first = compose_ai._local_background(
        "prompt",
        5.0,
        index=3,
        dims=(1080, 1920),
        work=tmp_path,
        prefix="seg03",
        segment=seg,
    )
    second = compose_ai._local_background(
        "prompt",
        5.0,
        index=3,
        dims=(1080, 1920),
        work=tmp_path,
        prefix="seg03b",
        segment=seg,
    )

    assert first == second
    assert len(calls) == 1
    assert "local_videos" in str(first)


def test_local_image_motion_ignores_ai_video_segment_type(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.pkg.models import Segment
    from ytb_pipeline.render import compose_ai

    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    built: list[Path] = []

    monkeypatch.setattr(settings, "broll_strategy", "local_image_motion")
    monkeypatch.setattr(compose_ai, "get_video_provider", lambda _name=None: pytest.fail("Wan must stay disabled"))
    monkeypatch.setattr(compose_ai, "_local_image", lambda *args, **kwargs: image)

    def fake_build_background(beats, dims, out):
        built.append(Path(out))
        Path(out).write_bytes(b"video")

    monkeypatch.setattr(compose_ai, "_build_background", fake_build_background)

    seg = Segment(
        caption="cap",
        narration="n",
        broll="prompt",
        video_type="ai_video",
        hook=True,
        duration_sec=5.0,
    )

    out = compose_ai._local_background(
        "prompt",
        5.0,
        index=0,
        dims=(1080, 1920),
        work=tmp_path,
        prefix="seg00",
        segment=seg,
    )

    assert out == tmp_path / "seg00_bg.mp4"
    assert built == [out]


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
