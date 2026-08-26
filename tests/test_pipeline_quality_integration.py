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


def _short_fixture_text(prefix: str, *, fraction: float = 0.25) -> str:
    """Keep pipeline fixtures inside the active provider's Short contract."""
    from conftest import chars_for_minutes

    target = int(len(chars_for_minutes(1.2)) * fraction)
    filler = "Sự mơ hồ của bước đầu khiến ta ngần ngại bắt tay vào việc. "
    return (prefix + " " + filler * (-(-target // len(filler))))[:target]


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
    # floor without exceeding its ceiling at the active provider's calibrated
    # chars/minute rate.
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
            Segment("Tình huống", _short_fixture_text("Mở laptop rồi lại cầm điện thoại."), purpose="situation"),
            Segment("Cơ chế", _short_fixture_text("Não né sự mơ hồ của việc khó."), purpose="core_answer"),
            Segment("Thử ngay", _short_fixture_text("Viết bước đầu tiên trong mười phút."), purpose="application"),
            Segment("Chốt", _short_fixture_text("Rõ bước đầu, não bớt né việc khó."), purpose="payoff"),
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


def _prepare_run(monkeypatch, tmp_path, audio_result, voice_scripts=None):
    script = _script()
    voiceover = _voiceover(tmp_path)
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    rendered = replace(RenderedVideo(**vars(voiceover)), video_path=video_path)
    rendered_calls: list[Voiceover] = []

    class VoiceProvider:
        async def synthesise(self, _script, _output_dir):
            if voice_scripts is not None:
                voice_scripts.append(_script)
            # Production providers preserve the Script identity in Voiceover;
            # keep this fake honest so renderer selection tests exercise the
            # same profile contract.
            return replace(
                voiceover,
                content_profile_id=_script.content_profile_id,
                content_profile_version=_script.content_profile_version,
            )

    class RenderProvider:
        async def render(self, voiced, _output_dir):
            rendered_calls.append(voiced)
            return rendered

    monkeypatch.setattr(pipeline, "load_script", lambda _path: script)
    monkeypatch.setattr(pipeline, "get_voice_provider", lambda: VoiceProvider())
    monkeypatch.setattr(pipeline, "get_render_provider", lambda _name=None: RenderProvider())
    monkeypatch.setattr(pipeline, "validate_audio", lambda _voice: None)
    monkeypatch.setattr(pipeline, "validate_final_video", lambda _video: None)
    monkeypatch.setattr(
        pipeline,
        "run_audio_quality_gate",
        lambda voice, *, cache_dir, stt_adapter=None, require_transcript=False: audio_result,
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
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
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


def test_voice_provider_receives_project_id_as_artifact_slug(monkeypatch, tmp_path):
    audio_result = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    received_scripts = []
    project, checkpoint, _ = _prepare_run(monkeypatch, tmp_path, audio_result, received_scripts)

    asyncio.run(pipeline.run_project(project, checkpoint, through="voiceover"))

    assert received_scripts[0].project_id == "nao-ne-viec-kho"


def test_direct_pipeline_blocks_a_profile_script_that_fails_editorial_review(monkeypatch, tmp_path):
    """`python -m ytb_pipeline` cannot bypass batch-start's content gate."""
    audio_result = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, _ = _prepare_run(monkeypatch, tmp_path, audio_result)
    monkeypatch.setattr(pipeline.settings, "assets_dir", tmp_path / "assets", raising=False)
    payload = _raw_script_payload()
    payload["profile_id"] = "one-cup-cafe-6h"
    payload["profile_version"] = "1.1.0"
    payload["sections"] = payload["sections"][:4]
    for section, purpose in zip(payload["sections"], ("situation", "core_answer", "application", "payoff")):
        section["purpose"] = purpose
    Path(project.script_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    class PassingQa:
        async def run(self, _context):
            return SimpleNamespace(status=pipeline.AgentStatus.SUCCESS, output={"passed": True})

    class RejectingReviewerProvider:
        async def complete(self, _prompt, **_kwargs):
            return json.dumps({
                "passed": False,
                "overall_score": 6,
                "dimension_scores": {
                    "human_truth": 6, "spoken_naturalness": 6,
                    "causal_coherence": 7, "role_fidelity": 9,
                    "useful_restraint": 8,
                },
                "blocking_findings": ["Nội dung nghe như một bài thuyết minh."],
                "section_refs": [1],
                "repair_brief": "Viết lại bằng một cảnh thật.",
            })

    monkeypatch.setattr(pipeline, "QAAgent", PassingQa)
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda _name=None: RejectingReviewerProvider())

    from ytb_pipeline.project.workflow import WorkflowError

    with pytest.raises(WorkflowError, match="Editorial review chặn TTS"):
        asyncio.run(pipeline.run_project(project, checkpoint, through="input"))


def test_publish_manifest_requires_an_editorial_approval_for_enabled_profile(tmp_path):
    """A project completed before the editorial gate cannot resume to publish."""
    payload = _raw_script_payload()
    payload["profile_id"] = "one-cup-cafe-6h"
    payload["profile_version"] = "1.1.0"
    path = tmp_path / "profile-script.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="Editorial release manifest"):
        pipeline.validate_editorial_release_approval(path, {"qa_decision": "pass"})


def test_render_uses_renderer_declared_by_script_content_profile(monkeypatch, tmp_path):
    """A direct pipeline run must not silently fall back to settings.render_provider.

    The batch runner exports RENDER_PROVIDER from the queue profile, but direct
    or resumed pipeline runs have to honour the same script contract themselves.
    Otherwise a character-story script can pass preflight for ``story`` and then
    render a stock-B-roll video through global ``ai`` settings.
    """
    audio_result = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, _ = _prepare_run(monkeypatch, tmp_path, audio_result)
    from ytb_pipeline.content_profiles import load_content_profile

    script = replace(
        _script(),
        content_profile_id="ban-so-6",
        content_profile_version=load_content_profile("ban-so-6").version,
    )
    requested_renderers: list[str | None] = []

    class StoryRenderProvider:
        async def render(self, voiceover, _output_dir):
            video_path = tmp_path / "story.mp4"
            video_path.write_bytes(b"story")
            return replace(RenderedVideo(**vars(voiceover)), video_path=video_path)

    class PassingQAAgent:
        async def run(self, _context):
            return SimpleNamespace(status=pipeline.AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(pipeline, "load_script", lambda _path: script)
    monkeypatch.setattr(pipeline, "QAAgent", PassingQAAgent)
    monkeypatch.setattr(
        pipeline,
        "get_render_provider",
        lambda name=None: (requested_renderers.append(name), StoryRenderProvider())[1],
    )

    asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert requested_renderers == ["story"]


def test_resumed_voiceover_keeps_project_id_for_renderer(monkeypatch, tmp_path):
    audio_result = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, audio_result)
    voice = _voiceover(tmp_path)
    project = replace(project, project_id=Path(project.script_path).stem)
    project = replace(project, metadata={
        "script_sha256": pipeline._script_sha256(Path(project.script_path)),
        "ruleset_id": pipeline._script_ruleset_id(Path(project.script_path)),
        **pipeline._script_profile(Path(project.script_path)),
    })
    project = checkpoint.mark_done(
        project,
        "voiceover",
        str(voice.audio_path),
        {
            "duration_sec": voice.duration_sec,
            "segments": [
                {
                    "index": index,
                    "audio_path": str(segment.audio_path),
                    "duration_sec": segment.duration_sec,
                }
                for index, segment in enumerate(voice.segments)
            ],
        },
    )
    checkpoint.save(project)

    resumed = pipeline.load_or_create_project(project.script_path, checkpoint)
    asyncio.run(pipeline.run_project(resumed, checkpoint, through="render"))

    assert rendered_calls[0].project_id == "approved"


@pytest.mark.parametrize("mode", ["report", "strict"])
def test_failed_audio_gate_blocks_render_in_every_mode(monkeypatch, tmp_path, mode):
    """A real audio-content defect always blocks render — not just in strict.

    Rendering AI B-roll is the most expensive step in the pipeline; audio
    already known-bad would be rejected at publish anyway (render_quality
    folds audio findings into its own gate), so failing here only saves
    compute and never changes which videos end up published.
    """
    audio_result = SimpleNamespace(
        passed=False,
        issues=(SimpleNamespace(code="LOW_VOLUME", message="Âm lượng quá nhỏ."),),
        cache_key="audio-key",
        cached=False,
        metrics={},
        repair_payload={},
    )
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, audio_result)
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", mode)

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
                "Tình huống", _short_fixture_text("Bạn định làm việc ngay, nhưng tay lại mở điện thoại trước."),
                purpose="situation", pexels_query="person checking phone at desk", payoff="x",
            ),
            Segment(
                "Giải thích", _short_fixture_text("Não né sự mơ hồ của việc khó."),
                purpose="core_answer", pexels_query="person staring at blank page", payoff="x",
            ),
            Segment(
                "Thử ngay", _short_fixture_text("Viết bước đầu tiên trong mười phút."),
                purpose="application", pexels_query="person writing in notebook at desk", payoff="x",
            ),
            Segment(
                "Chốt", _short_fixture_text("Rõ bước đầu, não bớt né việc khó. Hãy viết một dòng vào sổ ngay hôm nay."),
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

    def _gate(_voice, *, cache_dir, stt_adapter, require_transcript=False):
        captured["adapter"] = stt_adapter
        return audio_result

    monkeypatch.setattr(pipeline, "run_audio_quality_gate", _gate)
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report")
    monkeypatch.setattr(pipeline.settings, "quality_stt_model_path", model_dir)

    asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert captured["adapter"].model_path == model_dir


def test_pipeline_passes_explicit_local_stt_runtime_to_the_audio_gate(monkeypatch, tmp_path):
    audio_result = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, _rendered_calls = _prepare_run(monkeypatch, tmp_path, audio_result)
    model_dir = tmp_path / "whisper-model"
    model_dir.mkdir()
    captured = {}

    def _gate(_voice, *, cache_dir, stt_adapter, require_transcript=False):
        captured["adapter"] = stt_adapter
        return audio_result

    class PassingQa:
        async def run(self, _payload):
            return SimpleNamespace(status=pipeline.AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(pipeline, "run_audio_quality_gate", _gate)
    monkeypatch.setattr(pipeline, "QAAgent", PassingQa)
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report")
    monkeypatch.setattr(pipeline.settings, "quality_stt_model_path", model_dir)
    monkeypatch.setattr(pipeline.settings, "quality_stt_device", "cpu", raising=False)
    monkeypatch.setattr(pipeline.settings, "quality_stt_compute_type", "int8", raising=False)
    monkeypatch.setattr(pipeline.settings, "quality_stt_cpu_threads", 4, raising=False)

    asyncio.run(pipeline.run_project(project, checkpoint, through="render"))

    assert (
        captured["adapter"].device,
        captured["adapter"].compute_type,
        captured["adapter"].cpu_threads,
    ) == ("cpu", "int8", 4)


def test_a_gate_fix_unblocks_a_stale_failed_verdict_on_resume_without_batch_reset(
    monkeypatch, tmp_path,
):
    """A fixed detector must self-heal a stale FAILED verdict via a normal resume.

    Production 2026-08-24: a Long was blocked by a since-fixed `TRANSCRIPT_REPEAT`
    false positive. Under live time pressure this looked like a permanently
    frozen checkpoint verdict needing `ytb batch reset` (which discards the whole
    project, not just the stale audio_quality snapshot). This test proves that
    reading was wrong: `load_or_create_project` -> `_reset_stale_nodes` already
    puts a DONE `audio_quality` back to PENDING whenever `render` has not
    completed, so a plain `python -m ytb_pipeline` retry re-evaluates the gate
    with current code — no `ytb batch reset` required. The project_id must equal
    the script's filename stem, exactly as every real caller constructs it
    (`ideation_state.py`, `python -m ytb_pipeline scripts/<slug>.json`); a
    mismatched id here silently takes `load_or_create_project`'s "no existing
    checkpoint" branch and proves nothing about resume.
    """
    failing = SimpleNamespace(
        passed=False,
        issues=(SimpleNamespace(code="TRANSCRIPT_REPEAT", message="Transcript lặp liền câu/ý: 'x'."),),
        cache_key="audio-key-old-logic", cached=False, metrics={}, repair_payload={},
    )
    project, checkpoint, rendered_calls = _prepare_run(monkeypatch, tmp_path, failing)
    slug = Path(project.script_path).stem
    project = replace(
        project,
        project_id=slug,
        metadata={
            "script_sha256": pipeline._script_sha256(Path(project.script_path)),
            "ruleset_id": pipeline._script_ruleset_id(Path(project.script_path)),
            **pipeline._script_profile(Path(project.script_path)),
        },
    )
    monkeypatch.setattr(pipeline.settings, "quality_gate_mode", "report")

    with pytest.raises(Exception, match="Audio quality gate chặn render"):
        asyncio.run(pipeline.run_project(project, checkpoint, through="render"))
    assert rendered_calls == []
    assert checkpoint.load(slug).nodes["render"].status == NodeStatus.FAILED

    # The detector is fixed; nothing about the script or audio changed.
    fixed = SimpleNamespace(
        passed=True, issues=(), cache_key="audio-key-new-logic", cached=False, metrics={}, repair_payload={},
    )
    monkeypatch.setattr(pipeline, "run_audio_quality_gate",
        lambda voice, *, cache_dir, stt_adapter=None, require_transcript=False: fixed)

    resumed = pipeline.load_or_create_project(project.script_path, checkpoint)
    assert resumed.nodes["audio_quality"].status == NodeStatus.PENDING
    assert resumed.nodes["voiceover"].status == NodeStatus.DONE  # TTS not repaid

    final = asyncio.run(pipeline.run_project(resumed, checkpoint, through="render"))

    assert rendered_calls != []
    assert final.nodes["audio_quality"].output_data["quality_status"] == "pass"
