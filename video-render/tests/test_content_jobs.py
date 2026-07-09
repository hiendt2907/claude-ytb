"""Test content/jobs.py — mock script_gen/voiceover/pexels_fetch, không chạy thật."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ytb_pipeline.content import jobs as content_jobs
from ytb_pipeline.content.models import Script, ScriptSegment


def _script() -> Script:
    return Script(
        title="t",
        description="",
        segments=(ScriptSegment(narration="a", visual_keywords=("x",)),),
    )


class _FakeVoiceover:
    def __init__(self, audio_path: Path):
        self.audio_path = audio_path


def _wait_until_terminal(job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = content_jobs.get_content_job(job_id)
        if job["stage"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise TimeoutError(f"job {job_id} không kết thúc trong {timeout}s: {job}")


def _pass_qa_and_isolate_ledger(monkeypatch):
    """Test orchestration (script→voice→pexels→render), không phải QA/ledger
    (đã có test riêng: test_content_qa.py/test_content_ledger.py) — bypass để
    không cần narration đủ dài/không gọi claude -p thật khi cần sửa lỗi QA."""
    monkeypatch.setattr(
        content_jobs.qa, "check_script", lambda script, ledger=None: {"passed": True, "violations": [], "warnings": []}
    )
    monkeypatch.setattr(content_jobs.ledger_mod, "load_ledger", lambda: [])
    monkeypatch.setattr(content_jobs.ledger_mod, "append_ledger", lambda title, created_at: None)


def test_pipeline_runs_script_voice_pexels_then_render(monkeypatch, tmp_path):
    _pass_qa_and_isolate_ledger(monkeypatch)
    monkeypatch.setattr(content_jobs.script_gen, "generate_script", lambda topic: _script())
    monkeypatch.setattr(
        content_jobs.voiceover, "synthesize", lambda script, out_dir: _FakeVoiceover(out_dir / "v.mp3")
    )
    fetch_calls = []
    monkeypatch.setattr(
        content_jobs.pexels_fetch,
        "fetch_scenes",
        lambda script, out_dir, **kw: fetch_calls.append((out_dir, kw)) or [out_dir / "scene_00"],
    )

    render_calls = []

    def fake_start_render(scenes_dir, voice_track):
        render_calls.append((scenes_dir, voice_track))
        return {"job_id": "render-123"}

    job_id = content_jobs.start_content_pipeline(
        topic="chủ đề X",
        manual_script=None,
        work_dir=tmp_path,
        candidates_per_scene=3,
        landscape=False,
        start_render=fake_start_render,
    )

    job = _wait_until_terminal(job_id)

    assert job["stage"] == "done"
    assert job["render_job_id"] == "render-123"
    assert job["script"]["title"] == "t"
    assert len(render_calls) == 1
    assert len(fetch_calls) == 1


def test_pipeline_uses_manual_script_without_calling_claude(monkeypatch, tmp_path):
    _pass_qa_and_isolate_ledger(monkeypatch)
    called = []
    monkeypatch.setattr(
        content_jobs.script_gen, "generate_script", lambda topic: called.append(topic) or _script()
    )
    monkeypatch.setattr(
        content_jobs.voiceover, "synthesize", lambda script, out_dir: _FakeVoiceover(out_dir / "v.mp3")
    )
    monkeypatch.setattr(
        content_jobs.pexels_fetch, "fetch_scenes", lambda script, out_dir, **kw: [out_dir / "scene_00"]
    )

    job_id = content_jobs.start_content_pipeline(
        topic="",
        manual_script=_script(),
        work_dir=tmp_path,
        candidates_per_scene=3,
        landscape=False,
        start_render=lambda s, v: {"job_id": "r"},
    )

    job = _wait_until_terminal(job_id)

    assert job["stage"] == "done"
    assert called == []


def test_pipeline_marks_failed_on_exception(monkeypatch, tmp_path):
    def boom(topic):
        raise RuntimeError("claude lỗi")

    monkeypatch.setattr(content_jobs.script_gen, "generate_script", boom)

    job_id = content_jobs.start_content_pipeline(
        topic="x",
        manual_script=None,
        work_dir=tmp_path,
        candidates_per_scene=3,
        landscape=False,
        start_render=lambda s, v: {"job_id": "r"},
    )

    job = _wait_until_terminal(job_id)

    assert job["stage"] == "failed"
    assert "claude lỗi" in job["error"]


def test_get_content_job_returns_none_for_unknown_id():
    assert content_jobs.get_content_job("khong-ton-tai") is None
