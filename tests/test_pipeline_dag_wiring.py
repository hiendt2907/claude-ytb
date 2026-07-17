"""Test wiring `python -m ytb_pipeline` -> WorkflowGraph + CheckpointManager.

Không chạy provider thật — chỉ test load/create project, reset node stale,
đọc publish summary từ checkpoint, và cmd_reset xoá checkpoint.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ytb_pipeline import pipeline
from ytb_pipeline.pkg.models import PublishResult
from ytb_pipeline.project.checkpoint import CheckpointManager
from ytb_pipeline.project.models import NodeStatus, Project


def _script_file(tmp_path, slug="vid-x"):
    path = tmp_path / f"{slug}.json"
    path.write_text("{}", encoding="utf-8")
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
    existing = Project(project_id="vid-x", script_path=str(script))
    existing = checkpoint.mark_done(existing, "ideation", str(script))
    checkpoint.save(existing)

    project = pipeline.load_or_create_project(str(script), checkpoint)

    assert checkpoint.is_done(project, "ideation")  # resume: node done giữ nguyên


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
