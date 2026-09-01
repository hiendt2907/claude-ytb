"""Test wiring `python -m ytb_pipeline` -> WorkflowGraph + CheckpointManager.

Không chạy provider thật — chỉ test load/create project, reset node stale,
đọc publish summary từ checkpoint, và cmd_reset xoá checkpoint.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from ytb_pipeline import pipeline
from ytb_pipeline.pkg.models import PublishResult
from ytb_pipeline.project.checkpoint import CheckpointManager
from ytb_pipeline.project.models import NodeStatus, Project


def _script_file(tmp_path, slug="vid-x"):
    path = tmp_path / f"{slug}.json"
    path.write_text(json.dumps({"ruleset_id": pipeline.CONTRACT_VERSION}), encoding="utf-8")
    return path


# ── load_or_create_project ────────────────────────────────────────────────────
def test_load_or_create_project_creates_and_persists(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)

    project = pipeline.load_or_create_project(str(script), checkpoint)

    assert project.project_id == "vid-x"
    assert project.script_path == str(script)
    assert (tmp_path / "projects" / "vid-x" / "project.json").exists()


def test_load_or_create_project_resumes_existing_done_nodes(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    script_sha = pipeline._script_sha256(script)
    existing = Project(
        project_id="vid-x",
        script_path=str(script),
        metadata={
            "script_sha256": script_sha,
            "ruleset_id": pipeline.CONTRACT_VERSION,
            **pipeline._script_profile(script),
        },
    )
    existing = checkpoint.mark_done(existing, "ideation", str(script))
    checkpoint.save(existing)

    project = pipeline.load_or_create_project(str(script), checkpoint)

    assert checkpoint.is_done(project, "ideation")  # resume: node done giữ nguyên


def test_load_or_create_project_invalidates_nodes_when_ruleset_is_legacy(tmp_path):
    """Old 2x-tempo artifacts cannot be resumed after a contract migration."""
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    script.write_text(json.dumps({"ruleset_id": "2026-07-23.1"}), encoding="utf-8")
    existing = Project(
        project_id="vid-x",
        script_path=str(script),
        metadata={
            "script_sha256": pipeline._script_sha256(script),
            "ruleset_id": "2026-07-23.1",
        },
    )
    existing = checkpoint.mark_done(existing, "voiceover", str(tmp_path / "old-tempo.mp3"))
    checkpoint.save(existing)

    project = pipeline.load_or_create_project(str(script), checkpoint)

    assert project.nodes == {}
    assert project.metadata["ruleset_id"] == "2026-07-23.1"


def test_script_change_invalidates_all_downstream_artifacts(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    project = pipeline.load_or_create_project(str(script), checkpoint)
    project = checkpoint.mark_done(project, "voiceover", str(tmp_path / "old.mp3"))
    project = checkpoint.mark_done(project, "render", str(tmp_path / "old.mp4"))
    checkpoint.save(project)

    script.write_text('{"changed": true}', encoding="utf-8")
    refreshed = pipeline.load_or_create_project(str(script), checkpoint)

    assert refreshed.nodes == {}
    assert refreshed.metadata["script_sha256"] == pipeline._script_sha256(script)


def test_profile_fingerprint_change_invalidates_all_downstream_artifacts(tmp_path, monkeypatch):
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    fingerprints = iter(("profile-a", "profile-b"))
    monkeypatch.setattr(
        pipeline,
        "_script_profile",
        lambda _path: {
            "content_profile_id": "ban-so-6",
            "content_profile_version": "1.0.0",
            "content_profile_fingerprint": next(fingerprints),
        },
    )
    project = pipeline.load_or_create_project(str(script), checkpoint)
    project = checkpoint.mark_done(project, "voiceover", str(tmp_path / "old.mp3"))
    checkpoint.save(project)

    refreshed = pipeline.load_or_create_project(str(script), checkpoint)

    assert refreshed.nodes == {}
    assert refreshed.metadata["content_profile_fingerprint"] == "profile-b"


# ── _reset_stale_nodes ────────────────────────────────────────────────────────
def _project_with_done_publish(script, *, uploaded: bool) -> Project:
    checkpoint = CheckpointManager(script.parent / "projects")
    project = Project(project_id=script.stem, script_path=str(script))
    return checkpoint.mark_done(
        project, "publish", "ref",
        {"platforms": {"youtube_short": {"uploaded": uploaded, "url": "https://youtu.be/X"}}},
    )


def test_reset_stale_publish_when_never_really_uploaded(tmp_path):
    # Arrange — publish DONE nhưng uploaded=False (dry-run/export tay cũ)
    project = _project_with_done_publish(_script_file(tmp_path), uploaded=False)

    # Act
    result = pipeline._reset_stale_nodes(project)

    # Assert — phải publish lại, không được skip (bất kể dry_run hiện tại)
    assert result.nodes["publish"].status == NodeStatus.PENDING


def test_keep_done_publish_when_really_uploaded(tmp_path):
    project = _project_with_done_publish(_script_file(tmp_path), uploaded=True)

    result = pipeline._reset_stale_nodes(project)

    assert result.nodes["publish"].status == NodeStatus.DONE


def test_reset_stale_render_when_output_file_missing(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    project = Project(project_id="vid-x", script_path=str(script))
    project = checkpoint.mark_done(project, "render", str(tmp_path / "gone.mp4"))

    result = pipeline._reset_stale_nodes(project)

    assert result.nodes["render"].status == NodeStatus.PENDING


def test_keep_done_render_when_output_file_exists(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    video = tmp_path / "ok.mp4"
    video.write_bytes(b"v")
    project = Project(project_id="vid-x", script_path=str(script))
    project = checkpoint.mark_done(project, "render", str(video))

    result = pipeline._reset_stale_nodes(project)

    assert result.nodes["render"].status == NodeStatus.DONE


def test_keep_done_render_with_missing_file_when_publish_done(monkeypatch, tmp_path):
    # Sau upload thật + Drive move, video local bị xoá NHƯNG publish đã DONE
    # -> không được reset render (project đã hoàn tất).
    monkeypatch.setattr(pipeline.settings, "dry_run", False)
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    project = Project(project_id="vid-x", script_path=str(script))
    project = checkpoint.mark_done(project, "render", str(tmp_path / "moved-to-drive.mp4"))
    project = checkpoint.mark_done(
        project, "publish", "https://youtu.be/X",
        {"platforms": {"youtube_short": {"uploaded": True, "url": "https://youtu.be/X"}}},
    )

    result = pipeline._reset_stale_nodes(project)

    assert result.nodes["render"].status == NodeStatus.DONE
    assert result.nodes["publish"].status == NodeStatus.DONE


# ── publish_summary ───────────────────────────────────────────────────────────
def test_publish_summary_prefers_primary_platform(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    project = Project(project_id="vid-x")
    project = checkpoint.mark_done(
        project, "publish", "ref",
        {"platforms": {
            "youtube_short": {"uploaded": True, "url": "https://youtu.be/X"},
        }},
    )

    uploaded, url = pipeline.publish_summary(project, checkpoint)

    assert uploaded is True
    assert url == "https://youtu.be/X"


def test_publish_summary_empty_when_no_publish_node(tmp_path):
    checkpoint = CheckpointManager(tmp_path / "projects")
    project = Project(project_id="vid-x")

    uploaded, url = pipeline.publish_summary(project, checkpoint)

    assert uploaded is False
    assert url is None


def test_cleanup_after_success_keeps_other_render_workspace(tmp_path, monkeypatch):
    """Backup của một worker không được xoá frame đang dùng bởi worker khác."""
    monkeypatch.chdir(tmp_path)
    frames = tmp_path / "assets/output/_frames_ai"
    own_workspace = frames / "uploaded-video"
    other_workspace = frames / "still-rendering"
    own_workspace.mkdir(parents=True)
    other_workspace.mkdir()
    (own_workspace / "own-frame.png").write_bytes(b"frame")
    (other_workspace / "concat-input.txt").write_text("in use", encoding="utf-8")

    audio = tmp_path / "assets/audio/uploaded-video.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    result = PublishResult(
        topic="t", title="T", description="d", audio_path=Path("assets/audio/uploaded-video.mp3"),
    )

    pipeline._cleanup_after_success(result)

    assert not own_workspace.exists()
    assert (other_workspace / "concat-input.txt").exists()


# ── cmd_reset xoá checkpoint ──────────────────────────────────────────────────
def test_cmd_reset_removes_project_checkpoint(tmp_path, monkeypatch):
    import json

    from ytb_pipeline.orchestrator import batch_cli as cli

    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text(json.dumps({
        "shorts_funnel_batch_2026-07-14": {
            "long_videos": [
                {"day": 1, "slug": "vid-x", "publish_at": "", "shorts_status": "queued"},
            ]
        }
    }), encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")
    projects_dir = tmp_path / "projects"
    (projects_dir / "vid-x").mkdir(parents=True)
    (projects_dir / "vid-x" / "project.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(cli.settings, "projects_dir", projects_dir)
    monkeypatch.setattr(cli, "current_running_slug", lambda: None)

    cli.cmd_reset(argparse.Namespace(slug="vid-x"))

    assert not (projects_dir / "vid-x").exists()
    assert "reset" in ledger.read_text(encoding="utf-8")


# ── audio gate: tổng hợp lại đúng segment hỏng ────────────────────────────────
def _project_with_failed_audio_gate(tmp_path, *, worst_index: int, attempts: int = 0):
    """Dựng project ở đúng trạng thái engine từng kẹt vĩnh viễn."""
    checkpoint = CheckpointManager(tmp_path / "projects")
    script = _script_file(tmp_path)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(exist_ok=True)
    merged = audio_dir / "merged.mp3"
    merged.write_bytes(b"merged")
    segments = []
    for index in range(3):
        path = audio_dir / f"seg{index}.mp3"
        path.write_bytes(b"seg")
        segments.append({"index": index, "audio_path": str(path), "duration_sec": 3.0})

    project = Project(
        project_id=script.stem, script_path=str(script),
        metadata={"audio_resynth_attempts": attempts} if attempts else {},
    )
    project = checkpoint.mark_done(
        project, "voiceover", str(merged), {"segments": segments},
    )
    project = checkpoint.mark_done(
        project, "audio_quality", str(merged),
        {
            "passed": False,
            "quality_status": "failed",
            "issues": [{
                "code": "SEGMENT_TRANSCRIPT_MISMATCH", "severity": "error",
                "message": "Đoạn 1 chỉ khớp 24%",
                "repair": {"target": "audio_or_segment",
                           "action": "resynthesise_mismatched_segment"},
            }],
            "metrics": {"transcript": {"worst_segment_index": worst_index}},
        },
    )
    return project, segments, merged


def test_failed_audio_gate_drops_only_the_mismatched_segment_audio(tmp_path):
    """Gate biết đoạn nào hỏng và tự gọi tên cách chữa, nhưng không ai thực thi.

    xKiro TTS không tất định: cùng một câu, 5 lần gọi cho 5 file audio khác
    nhau, và thỉnh thoảng đọc hỏng một cụm ("gọi năm lần" -> "G.I.N. Mơ Lân").
    Trước đây `_reset_stale_nodes` chỉ chạy lại CỔNG chứ không bao giờ chạy lại
    TTS, nên gate chấm lại đúng file hỏng cũ và project kẹt vĩnh viễn — lối
    thoát duy nhất là `ytb batch reset`, vứt cả render lẫn ảnh đã sinh.
    """
    project, segments, merged = _project_with_failed_audio_gate(tmp_path, worst_index=1)

    result = pipeline._reset_stale_nodes(project)

    assert not Path(segments[1]["audio_path"]).exists(), "phải xoá đúng segment hỏng"
    assert Path(segments[0]["audio_path"]).exists(), "segment tốt phải được giữ"
    assert Path(segments[2]["audio_path"]).exists(), "segment tốt phải được giữ"
    assert result.nodes["voiceover"].status == NodeStatus.PENDING, "phải tổng hợp lại"
    assert result.metadata["audio_resynth_attempts"] == 1, "phải đếm lượt, có trần"


def test_audio_gate_recovery_is_bounded_and_then_fails_closed(tmp_path):
    """Hết lượt thì dừng — không được xoá/tổng hợp lại vô hạn."""
    project, segments, _ = _project_with_failed_audio_gate(
        tmp_path, worst_index=1, attempts=pipeline.MAX_AUDIO_RESYNTH_ATTEMPTS,
    )

    result = pipeline._reset_stale_nodes(project)

    assert Path(segments[1]["audio_path"]).exists(), "hết lượt thì giữ nguyên bằng chứng"
    assert result.nodes["voiceover"].status == NodeStatus.DONE


def test_passing_audio_gate_never_touches_segment_audio(tmp_path):
    project, segments, merged = _project_with_failed_audio_gate(tmp_path, worst_index=1)
    node = project.nodes["audio_quality"]
    project = project.with_node(
        replace(node, output_data={"passed": True, "quality_status": "pass"}),
    )

    result = pipeline._reset_stale_nodes(project)

    assert all(Path(s["audio_path"]).exists() for s in segments)
    assert result.nodes["voiceover"].status == NodeStatus.DONE
