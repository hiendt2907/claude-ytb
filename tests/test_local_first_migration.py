"""Acceptance tests for LOCAL_FIRST_AI_MIGRATION_PLAN.md."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from ytb_pipeline.config.settings import settings
from ytb_pipeline.pkg.models import PublishResult, RenderedVideo


def _valid_short_script() -> dict:
    chunk = (
        "Não bộ không ra quyết định bằng khẩu hiệu. Nó so sánh chi phí, phần thưởng, "
        "rủi ro mất mặt và tín hiệu xã hội trước khi ta kịp gọi đó là ý chí. "
    )
    sections = [
        {
            "caption": f"Ý {i}",
            "narration": (chunk * 2).strip(),
            "broll": "abstract decision making",
            "emphasis": ["cơ chế"],
        }
        for i in range(4)
    ]
    return {
        "slug": "co-che-test-local",
        "topic": "Cơ chế test local",
        "title": "Cơ Chế Test Local",
        "description": "Một kịch bản test local-first.",
        "tags": ["tam ly", "hanh vi"],
        "sections": sections,
        "compliance": {
            "passed": True,
            "community": "ok",
            "copyright": "ok",
            "accuracy": "ok",
            "advertiser": "ok",
            "coppa": "not for kids",
            "notes": "test",
        },
    }


def test_settings_default_to_local_first_stack():
    assert settings.llm_provider == "ollama"
    assert settings.tts_provider in {"f5", "vieneu", "vixtts"}
    assert settings.image_provider == "pillow"
    assert settings.video_provider == "disabled"
    assert settings.broll_strategy == "local_image_motion"


def test_ai_render_provider_local_image_motion_does_not_require_pexels(monkeypatch):
    from ytb_pipeline.providers.render.ai_provider import AiRenderProvider

    original = {
        "broll_strategy": settings.broll_strategy,
        "image_provider": settings.image_provider,
        "pexels_api_key": settings.pexels_api_key,
    }
    try:
        settings.broll_strategy = "local_image_motion"
        settings.image_provider = "pillow"
        settings.pexels_api_key = ""
        assert AiRenderProvider().is_available() is True
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def test_local_doctor_reports_local_ai_readiness(monkeypatch):
    from ytb_pipeline.orchestrator.doctor import run_local_doctor_checks

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name if name == "ffmpeg" else None)

    checks = run_local_doctor_checks()
    names = {name for name, _ok, _detail in checks}

    assert "Ollama local LLM" in names
    assert "Local image provider" in names
    assert "Vietnamese TTS provider" in names
    assert "ffprobe" in names


def test_batch_start_local_uses_llm_provider_without_claude(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text("{}", encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )

    class FakeLLM:
        name = "ollama"

        async def complete(self, *args, **kwargs):
            return json.dumps(_valid_short_script(), ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    def fail_popen(*_args, **_kwargs):
        raise AssertionError("Claude subprocess must not be used in local start")

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda: FakeLLM())
    monkeypatch.setattr(cli.subprocess, "Popen", fail_popen)

    args = argparse.Namespace(
        num_of_vid=1,
        type_of_vid="short",
        type_of_rules="auto",
        resume=False,
        cloud=False,
    )
    ideation_cmd.cmd_start(args)

    script_path = scripts_dir / "co-che-test-local.json"
    assert script_path.exists()
    assert "co-che-test-local" in auto_state.read_text(encoding="utf-8")
    assert "co-che-test-local" in ledger.read_text(encoding="utf-8")


def test_batch_start_local_prints_steps_and_writes_trace_log(tmp_path, monkeypatch, capsys):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text("{}", encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )
    log_dir = tmp_path / "batch_logs"

    payload = _valid_short_script()
    payload["sections"][0]["emphasis"] = True

    class FakeLLM:
        name = "ollama"

        async def complete(self, *args, **kwargs):
            return json.dumps(payload, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "PIPELINE_LOG_DIR", log_dir)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda: FakeLLM())

    ideation_cmd.cmd_start(argparse.Namespace(
        num_of_vid=1,
        type_of_vid="short",
        type_of_rules="auto",
        resume=False,
        local=True,
        cloud=False,
    ))

    out = capsys.readouterr().out
    assert "ý tưởng: auto" in out
    assert "[1/1] prompt" in out
    assert "[1/1] LLM" in out
    assert "[1/1] validate" in out
    assert "log chi tiết:" in out
    logs = list(log_dir.glob("ideation_*.log"))
    assert len(logs) == 1
    log_text = logs[0].read_text(encoding="utf-8")
    assert "PROMPT" in log_text
    assert "RAW_LLM_RESPONSE" in log_text
    assert "VALIDATION_ATTEMPT 1" in log_text


def test_batch_start_local_can_clear_old_ledger_for_user_idea(tmp_path, monkeypatch, capsys):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text("{}", encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "| 2026-01-01 | old | Chủ đề cũ không được nhắc lại | done | ok | old |\n",
        encoding="utf-8",
    )

    captured_prompts: list[str] = []

    class FakeLLM:
        name = "ollama"

        async def complete(self, prompt, *args, **kwargs):
            captured_prompts.append(prompt)
            payload = _valid_short_script()
            payload["topic"] = "Cơ chế xấu hổ"
            payload["title"] = "Cơ Chế Xấu Hổ"
            payload["slug"] = "co-che-xau-ho"
            return json.dumps(payload, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda: FakeLLM())

    ideation_cmd.cmd_start(argparse.Namespace(
        num_of_vid=1,
        type_of_vid="short",
        type_of_rules="cơ chế xấu hổ",
        resume=False,
        local=True,
        cloud=False,
        clear_ledger=True,
    ))

    out = capsys.readouterr().out
    assert "Đã clear ledger cũ" in out
    assert "cơ chế xấu hổ" in captured_prompts[0]
    assert "Chủ đề cũ không được nhắc lại" not in captured_prompts[0]
    assert "co-che-xau-ho" in ledger.read_text(encoding="utf-8")
    assert "Chủ đề cũ không được nhắc lại" not in ledger.read_text(encoding="utf-8")
    backups = list(tmp_path.glob("ledger.backup.*.md"))
    assert len(backups) == 1
    assert "Chủ đề cũ không được nhắc lại" in backups[0].read_text(encoding="utf-8")


def test_batch_start_local_repairs_script_before_queueing(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text("{}", encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )

    bad = _valid_short_script()
    bad["compliance"] = {**bad["compliance"], "passed": False}
    fixed = _valid_short_script()

    class RepairingLLM:
        name = "ollama"

        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return json.dumps(bad if self.calls == 1 else fixed, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    provider = RepairingLLM()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("Claude must not run"))

    args = argparse.Namespace(
        num_of_vid=1,
        type_of_vid="short",
        type_of_rules="auto",
        resume=False,
        cloud=False,
    )
    ideation_cmd.cmd_start(args)

    assert provider.calls == 2
    script_path = scripts_dir / "co-che-test-local.json"
    assert json.loads(script_path.read_text(encoding="utf-8"))["compliance"]["passed"] is True
    assert "co-che-test-local" in ledger.read_text(encoding="utf-8")


def test_batch_start_local_repairs_duplicate_title_without_overwrite(tmp_path, monkeypatch, capsys):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text("{}", encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )

    duplicate = _valid_short_script()
    fixed = _valid_short_script()
    fixed["topic"] = "Người que rơi thang máy"
    fixed["title"] = "Người Que Rơi Thang Máy Nhưng Vẫn Cố Tỏ Ra Ổn"

    class DuplicateThenRepairLLM:
        name = "ollama"

        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return json.dumps(fixed if self.calls == 3 else duplicate, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    provider = DuplicateThenRepairLLM()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda: provider)

    ideation_cmd.cmd_start(argparse.Namespace(
        num_of_vid=2,
        type_of_vid="short",
        type_of_rules="làm về nội dung giải trí, người que",
        resume=False,
        local=True,
        cloud=False,
    ))

    out = capsys.readouterr().out
    assert "slug: adjusted duplicate `co-che-test-local` -> `co-che-test-local-2`" in out
    assert provider.calls == 3
    first = json.loads((scripts_dir / "co-che-test-local.json").read_text(encoding="utf-8"))
    second = json.loads((scripts_dir / "co-che-test-local-2.json").read_text(encoding="utf-8"))
    assert first["title"] == "Cơ Chế Test Local"
    assert second["title"] == "Người Que Rơi Thang Máy Nhưng Vẫn Cố Tỏ Ra Ổn"
    state = json.loads(auto_state.read_text(encoding="utf-8"))
    slugs = [item["slug"] for item in state["shorts_funnel_batch_local"]["short_videos"]]
    assert slugs == ["co-che-test-local", "co-che-test-local-2"]


def test_local_short_normalizer_shrinks_overlong_repair():
    from ytb_pipeline.orchestrator.ideation_cmd import (
        SHORT_MAX_CHARS,
        SHORT_MIN_CHARS,
        _normalize_short_narration,
        _short_narration_chars,
    )

    payload = _valid_short_script()
    payload["sections"] = [
        {
            "caption": f"Cảnh {i}",
            "narration": (
                "Chào mừng các bạn đến với video mới của chúng tôi. "
                "Người que chạy qua hành lang, trượt chân, bật dậy và cố tỏ ra bình thường. "
                "Cảnh này tiếp tục leo thang bằng một cú va chạm bất ngờ. "
            ) * 4,
            "broll": "người que chạy và ngã",
            "emphasis": ["punchline"],
        }
        for i in range(4)
    ]

    fixed, note = _normalize_short_narration(payload)

    assert note is not None
    assert SHORT_MIN_CHARS < _short_narration_chars(fixed) < SHORT_MAX_CHARS
    assert "Chào mừng các bạn" not in fixed["sections"][0]["narration"]


def test_local_short_normalizer_pads_too_short_script():
    from ytb_pipeline.orchestrator.ideation_cmd import (
        SHORT_MAX_CHARS,
        SHORT_MIN_CHARS,
        _normalize_short_narration,
        _short_narration_chars,
    )

    payload = _valid_short_script()
    payload["sections"] = [
        {
            "caption": "Hook",
            "narration": "Người que mở cửa, thấy sếp, đóng cửa lại.",
            "broll": "người que đóng cửa",
            "emphasis": ["hook"],
        },
        {
            "caption": "Punchline",
            "narration": "Cánh cửa tự mở lại, sếp cũng là người que.",
            "broll": "hai người que nhìn nhau",
            "emphasis": ["punchline"],
        },
    ]

    fixed, note = _normalize_short_narration(payload)

    assert note is not None
    assert SHORT_MIN_CHARS < _short_narration_chars(fixed) < SHORT_MAX_CHARS


@pytest.mark.asyncio
async def test_manual_export_provider_creates_queue_package(tmp_path, monkeypatch):
    from ytb_pipeline.platform.profiles import Platform, get_profile
    from ytb_pipeline.providers.registry import get_publish_provider

    profile = get_profile("facebook_reel")
    assert profile.platform == Platform.FACEBOOK_REEL

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"mp4")
    video = RenderedVideo(
        topic="topic",
        title="Title",
        description="Desc",
        tags=("tag",),
        video_path=video_file,
        duration_sec=12,
    )
    monkeypatch.setattr(settings, "manual_publish_dir", tmp_path / "manual")

    provider = get_publish_provider("facebook_reel")
    result = await provider.publish(video)

    assert result.uploaded is False
    assert result.url is not None
    manifest = Path(result.url)
    assert manifest.exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["platform"] == "facebook_reel"


@pytest.mark.asyncio
async def test_multiplatform_publish_validates_manual_export_manifest(tmp_path, monkeypatch):
    from dataclasses import replace

    from ytb_pipeline.pkg.models import PublishResult
    from ytb_pipeline.publish import multiplatform

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"mp4")
    video = RenderedVideo(
        topic="topic",
        title="Title",
        description="Desc",
        tags=("tag",),
        video_path=video_file,
        duration_sec=12,
    )

    class BrokenProvider:
        async def publish(self, video):
            return replace(PublishResult(**vars(video)), uploaded=False, url=str(tmp_path / "missing.json"))

        def is_available(self):
            return True

    monkeypatch.setattr(multiplatform, "get_publish_provider", lambda _name: BrokenProvider())

    with pytest.raises(FileNotFoundError):
        await multiplatform.publish_to_platforms(video, ["tiktok"])


def test_run_project_resume_publish_rehydrates_rendered_video(tmp_path, monkeypatch):
    from ytb_pipeline import pipeline
    from ytb_pipeline.project.checkpoint import CheckpointManager
    from ytb_pipeline.project.models import Project

    script_path = tmp_path / "scripts" / "co-che-test-local.json"
    script_path.parent.mkdir()
    script_path.write_text(json.dumps(_valid_short_script(), ensure_ascii=False), encoding="utf-8")
    video_path = tmp_path / "assets" / "output" / "co-che-test-local.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"mp4")

    checkpoint = CheckpointManager(tmp_path / "projects")
    project = Project(project_id="co-che-test-local", script_path=str(script_path))
    project = checkpoint.mark_done(project, "ideation", str(script_path))
    project = checkpoint.mark_done(
        project,
        "voiceover",
        str(tmp_path / "assets/audio/co-che-test-local.mp3"),
        {
            "duration_sec": 42.0,
            "segments": [
                {"index": index, "audio_path": str(tmp_path / f"seg{index}.mp3"), "duration_sec": 10.5}
                for index in range(4)
            ],
        },
    )
    project = checkpoint.mark_done(
        project,
        "render",
        str(video_path),
        {"video_path": str(video_path), "duration_sec": 42.0, "thumbnail_path": None},
    )

    seen: list[RenderedVideo] = []

    async def fake_publish_to_platforms(video):
        seen.append(video)
        return {"youtube_short": replace(PublishResult(**vars(video)), uploaded=False, url="manual://queued")}

    monkeypatch.setattr(pipeline, "publish_to_platforms", fake_publish_to_platforms)
    monkeypatch.setattr(pipeline, "gate", lambda script: script)

    result = asyncio.run(pipeline.run_project(project, checkpoint))

    assert seen
    assert seen[0].video_path == video_path
    assert seen[0].duration_sec == 42.0
    assert seen[0].segments[0].duration_sec == 10.5
    assert result.nodes["publish"].output_ref == "manual://queued"
    assert result.nodes["publish"].output_data["platforms"]["youtube_short"]["url"] == "manual://queued"
