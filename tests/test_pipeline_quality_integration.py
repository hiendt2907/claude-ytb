"""Quality gates wired at pipeline boundaries stay local and resumable."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline import pipeline
from ytb_pipeline.content_contract import CONTRACT_VERSION
from ytb_pipeline.pkg.models import ComplianceCheck, RenderedVideo, Script, Segment, ThumbnailBrief, Voiceover
from ytb_pipeline.project.checkpoint import CheckpointManager
from ytb_pipeline.project.models import NodeStatus, Project


def _raw_script_payload() -> dict:
    """Minimal on-disk payload satisfying script_contract.validate_script_payload.

    pipeline.py's "input" node now reads and validates the raw script JSON
    itself before calling (the monkeypatched) `load_script`, so a real file
    must exist on disk even though its parsed content is never consulted.
    """
    sections = [
        {
            "purpose": "situation" if i == 0 else ("core_answer" if i == 1 else "point"),
            "voiceover": f"Nội dung phần {i}.",
            "visual_intent": "cảnh minh hoạ",
            "pexels_query": "abstract decision making",
            "time_goal": 0.2,
        }
        for i in range(6)
    ]
    return {
        "ruleset_id": CONTRACT_VERSION,
        "video_type": "short",
        "title": "Não né việc khó",
        "topic": "Trì hoãn",
        "thumbnail_brief": {
            "visual_contradiction": "x",
            "subject": "x",
            "emotion": "x",
            "headline": "x",
        },
        "sections": sections,
        "strategy": {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "né sự mơ hồ",
            "audience_problem": "việc khó",
            "angle": "bước đầu",
            "long_form_slug": "long-a",
            "playlist": "series",
            "cta_target": "long-a",
            "source_long_slug": "long-a",
            "source_excerpt": "Trích đoạn nguồn.",
            "source_section_index": 0,
            "hook": {
                "situation": "Mở laptop rồi lại cầm điện thoại",
                "core_answer": "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu",
                "open_loop": "Vì sao sự mơ hồ thắng ý chí?",
            },
        },
    }


def _script() -> Script:
    # QAAgent's always-on checks (compliance + length) run even with
    # strict=False, so this fixture needs a passing ComplianceCheck and
    # enough narration to clear content_contract's Short audio-runtime
    # floor (~60s, ~2000 chars at the default f5 chars/minute rate).
    filler = "Sự mơ hồ của bước đầu khiến ta ngần ngại bắt tay vào việc. " * 12
    return Script(
        topic="Trì hoãn",
        title="Não né việc khó",
        description="Giải thích cơ chế trì hoãn qua một ví dụ cụ thể.",
        tags=("tâm lý", "trì hoãn", "tập trung"),
        video_type="short",
        compliance=ComplianceCheck(
            passed=True,
            community="PASS",
            copyright="PASS — nội dung tự sinh",
            accuracy="PASS",
            advertiser="PASS",
            coppa="không hướng tới trẻ em",
        ),
        segments=(
            Segment("Tình huống", "Mở laptop rồi lại cầm điện thoại." + filler, purpose="situation"),
            Segment("Cơ chế", "Não né sự mơ hồ của việc khó." + filler, purpose="core_answer"),
            Segment("Thử ngay", "Viết bước đầu tiên trong mười phút." + filler, purpose="application"),
            Segment("Chốt", "Rõ bước đầu, não bớt né việc khó." + filler, purpose="payoff"),
        ),
    )


def _voiceover(tmp_path: Path) -> Voiceover:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"audio")
    segments = tuple(
        replace(segment, audio_path=tmp_path / f"segment-{index}.mp3", duration_sec=2.0)
        for index, segment in enumerate(_script().segments)
    )
    return Voiceover(**vars(replace(_script(), segments=segments)), audio_path=audio, duration_sec=8.0)


def _prepare_run(monkeypatch, tmp_path, audio_result):
    script = _script()
    voiceover = _voiceover(tmp_path)
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    rendered = replace(RenderedVideo(**vars(voiceover)), video_path=video_path)
    rendered_calls: list[Voiceover] = []

    class VoiceProvider:
        async def synthesise(self, _script, _output_dir):
            return voiceover

    class RenderProvider:
        async def render(self, voiced, _output_dir):
            rendered_calls.append(voiced)
            return rendered

    monkeypatch.setattr(pipeline, "load_script", lambda _path: script)
    monkeypatch.setattr(pipeline, "get_voice_provider", lambda: VoiceProvider())
    monkeypatch.setattr(pipeline, "get_render_provider", lambda: RenderProvider())
    monkeypatch.setattr(pipeline, "validate_audio", lambda _voice: None)
    monkeypatch.setattr(pipeline, "validate_final_video", lambda _video: None)
    monkeypatch.setattr(
        pipeline,
        "run_audio_quality_gate",
        lambda voice, *, cache_dir, stt_adapter=None: audio_result,
    )
    monkeypatch.setattr(
        pipeline,
        "render_evidence_for",
        lambda _video: pipeline.RenderEvidence(width=1080, height=1920, duration_sec=8.0),
    )
    monkeypatch.setattr(pipeline.settings, "quality_reports_dir", tmp_path / "quality-reports")

    script_path = tmp_path / "approved.json"
    script_path.write_text(json.dumps(_raw_script_payload(), ensure_ascii=False), encoding="utf-8")
    project = Project(project_id="nao-ne-viec-kho", script_path=str(script_path))
    return project, CheckpointManager(tmp_path / "projects"), rendered_calls


def test_report_mode_runs_audio_gate_and_writes_local_post_render_reports(monkeypatch, tmp_path):
    audio_result = SimpleNamespace(
        passed=False, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, audio_result)
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report")

    result = asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert rendered_calls
    output = result.nodes["render_quality"].output_data
    assert Path(output["quality_report_json"]).exists()
    assert Path(output["quality_report_markdown"]).exists()
    assert Path(output["quality_repair_brief"]).exists()
    assert result.nodes["audio_quality"].output_data["cache_key"] == "audio-key"


def test_strict_mode_blocks_failed_audio_gate_before_renderer(monkeypatch, tmp_path):
    audio_result = SimpleNamespace(
        passed=False,
        issues=(SimpleNamespace(code="LOW_VOLUME", message="Âm lượng quá nhỏ."),),
        cache_key="audio-key",
        cached=False,
        metrics={},
        repair_payload={},
    )
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, audio_result)
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "strict")

    with pytest.raises(Exception, match="Audio quality gate chặn render"):
        asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert rendered_calls == []

    saved = checkpoint.load("nao-ne-viec-kho")
    assert saved is not None
    assert saved.nodes["voiceover"].output_ref.endswith("voice.mp3")
    assert saved.nodes["audio_quality"].output_data["quality_status"] == "failed"


def test_resume_retries_checkpointed_audio_qa_without_invalidating_voiceover(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    audio_path = tmp_path / "resume-quality.mp3"
    audio_path.write_bytes(b"audio")
    project = Project(project_id="resume-quality", script_path="approved.json")
    project = checkpoint.mark_done(project, "voiceover", str(audio_path))
    project = checkpoint.mark_done(
        project,
        "audio_quality",
        str(audio_path),
        {"quality_status": "failed"},
    )

    resumed = pipeline._reset_stale_nodes(project)

    assert resumed.nodes["voiceover"].status == NodeStatus.DONE
    assert resumed.nodes["voiceover"].output_ref == str(audio_path)
    assert resumed.nodes["audio_quality"].status == NodeStatus.PENDING


def test_off_mode_skips_audio_and_post_render_quality_gates(monkeypatch, tmp_path):
    project, checkpoint, _rendered_calls = _prepare_run(monkeypatch, tmp_path, object())
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "off")
    monkeypatch.setattr(
        pipeline,
        "run_audio_quality_gate",
        lambda *_args, **_kwargs: pytest.fail("audio gate must be disabled"),
    )
    monkeypatch.setattr(
        pipeline,
        "write_quality_report",
        lambda *_args, **_kwargs: pytest.fail("post-render report must be disabled"),
    )

    result = asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert "quality_report_json" not in result.nodes["render"].output_data


def test_report_mode_treats_local_audio_qa_crash_as_warning(monkeypatch, tmp_path):
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, object())
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report")
    monkeypatch.setattr(
        pipeline,
        "run_audio_quality_gate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cache is read-only")),
    )

    result = asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert rendered_calls
    assert result.nodes["audio_quality"].output_data["quality_status"] == "warning"
    assert result.nodes["voiceover"].output_ref.endswith("voice.mp3")


def test_strict_mode_fails_closed_after_audio_qa_crash_but_keeps_voiceover(monkeypatch, tmp_path):
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, object())
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "strict")
    monkeypatch.setattr(
        pipeline,
        "run_audio_quality_gate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cache is read-only")),
    )

    with pytest.raises(Exception, match="Audio quality gate chặn render"):
        asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert rendered_calls == []
    saved = checkpoint.load("nao-ne-viec-kho")
    assert saved is not None
    assert saved.nodes["voiceover"].output_ref.endswith("voice.mp3")
    assert saved.nodes["audio_quality"].output_data["quality_status"] == "error"


def test_report_mode_treats_post_render_report_failure_as_warning(monkeypatch, tmp_path):
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, object())
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report")
    monkeypatch.setattr(
        pipeline,
        "write_post_render_quality_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("report directory is read-only")),
    )

    result = asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert rendered_calls
    assert result.nodes["render_quality"].output_data["quality_status"] == "warning"
    assert result.nodes["render"].output_ref.endswith("video.mp4")


def test_strict_post_render_qa_failure_preserves_render_checkpoint(monkeypatch, tmp_path):
    audio_result = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, _rendered_calls = _prepare_run(monkeypatch, tmp_path, audio_result)
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "strict")
    monkeypatch.setattr(
        pipeline,
        "write_post_render_quality_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("report directory is read-only")),
    )
    # publish_fn only proceeds to enforce_pre_publish_quality once its own
    # release-manifest guard passes: current.metadata.ruleset_id must equal
    # CONTRACT_VERSION and match the "input" node's own recorded
    # ruleset_id/script_sha256 (both sourced from the loaded Script's own
    # ruleset_id — the shared `_script()` fixture deliberately leaves that
    # blank for the other, non-publish tests in this file, so this test
    # supplies its own strict-QA-compliant Script/metadata instead of
    # mutating the shared fixture).
    filler = "Một bước nhỏ mỗi ngày giúp giảm sự mơ hồ khi bắt đầu. " * 12
    strict_script = Script(
        topic="Trì hoãn",
        title="Não né việc khó",
        description="Giải thích cơ chế trì hoãn qua một ví dụ cụ thể.",
        tags=("tâm lý", "trì hoãn", "tập trung"),
        video_type="short",
        ruleset_id=CONTRACT_VERSION,
        compliance=ComplianceCheck(passed=True, community="PASS", copyright="PASS", accuracy="PASS", advertiser="PASS", coppa="không hướng tới trẻ em"),
        thumbnail_brief=ThumbnailBrief(
            visual_contradiction="Laptop mở nhưng tay cầm điện thoại",
            subject="Người trẻ trước laptop",
            emotion="Bối rối",
            headline="Vì sao trì hoãn",
        ),
        segments=(
            Segment(
                "Tình huống", "Bạn định làm việc ngay, nhưng tay lại mở điện thoại trước." + filler,
                purpose="situation", pexels_query="person checking phone at desk", payoff="x",
            ),
            Segment(
                "Giải thích", "Não né sự mơ hồ của việc khó." + filler,
                purpose="core_answer", pexels_query="person staring at blank page", payoff="x",
            ),
            Segment(
                "Thử ngay", "Viết bước đầu tiên trong mười phút." + filler,
                purpose="application", pexels_query="person writing in notebook at desk", payoff="x",
            ),
            Segment(
                "Chốt", "Rõ bước đầu, não bớt né việc khó. Hãy viết một dòng vào sổ ngay hôm nay." + filler,
                purpose="payoff", pexels_query="person closing notebook satisfied",
                payoff="Bạn thấy bước đầu rõ ràng hơn.",
            ),
        ),
    )
    monkeypatch.setattr(pipeline, "load_script", lambda _path: strict_script)
    script_sha256 = pipeline._script_sha256(Path(project.script_path))
    project = replace(project, metadata={"script_sha256": script_sha256, "ruleset_id": CONTRACT_VERSION})

    with pytest.raises(Exception, match="Pre-publish quality gate chặn publish"):
        asyncio.run(pipeline.run_project(project, checkpoint, through="publish"))

    saved = checkpoint.load("nao-ne-viec-kho")
    assert saved is not None
    assert saved.nodes["render"].output_ref.endswith("video.mp4")
    assert saved.nodes["render_quality"].output_data["quality_status"] == "error"


def test_post_render_report_uses_script_thumbnail_headline(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path)
    brief = ThumbnailBrief(
        visual_contradiction="Laptop mở nhưng điện thoại lại được cầm lên.",
        subject="Một người trước laptop",
        emotion="bối rối",
        headline="Não né việc",
    )
    voiceover = replace(voiceover, thumbnail_brief=brief)
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    video = replace(RenderedVideo(**vars(voiceover)), video_path=video_path)
    project = Project(project_id="nao-ne-viec-kho", script_path="approved.json")
    monkeypatch.setattr(
        pipeline,
        "render_evidence_for",
        lambda _video: pipeline.RenderEvidence(width=1080, height=1920, duration_sec=8.0),
    )
    monkeypatch.setattr(pipeline.settings, "quality_reports_dir", tmp_path / "quality-reports")

    original_evaluate = pipeline.evaluate_pre_publish_quality
    captured = {}

    def _capture(input_data):
        captured["thumbnail_text"] = input_data.thumbnail_text
        return original_evaluate(input_data)

    monkeypatch.setattr(pipeline, "evaluate_pre_publish_quality", _capture)

    output = pipeline.write_post_render_quality_report(project, video, None)

    report = Path(output["quality_report_json"]).read_text(encoding="utf-8")
    assert captured["thumbnail_text"] == "Não né việc"
    assert "packaging.thumbnail_text.present" not in report


def test_strict_quality_blocks_a_blocked_report_before_publish(monkeypatch):
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "strict")

    with pytest.raises(ValueError, match="Pre-publish quality gate chặn publish"):
        pipeline.enforce_pre_publish_quality("blocked")


def test_pipeline_passes_an_explicit_local_stt_path_to_the_audio_gate(monkeypatch, tmp_path):
    audio_result = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, _rendered_calls = _prepare_run(monkeypatch, tmp_path, audio_result)
    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    captured = {}

    def _gate(_voice, *, cache_dir, stt_adapter):
        captured["adapter"] = stt_adapter
        return audio_result

    monkeypatch.setattr(pipeline, "run_audio_quality_gate", _gate)
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report")
    monkeypatch.setattr(pipeline.settings, "quality_stt_model_path", model_dir)

    asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert captured["adapter"].model_path == model_dir
