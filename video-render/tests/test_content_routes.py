"""Test webui/content_routes.py — TestClient + mock script_gen/content pipeline."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from ytb_pipeline.content import jobs as content_jobs
from ytb_pipeline.content.models import Script, ScriptSegment
from ytb_pipeline.webui import app as app_module
from ytb_pipeline.webui import content_routes


def _client() -> TestClient:
    return TestClient(app_module.app)


def _script() -> Script:
    return Script(
        title="Thói quen dậy sớm",
        description="d",
        segments=(ScriptSegment(narration="a", visual_keywords=("sunrise",)),),
    )


def test_generate_script_endpoint_returns_script_json(monkeypatch):
    monkeypatch.setattr(content_routes, "generate_script", lambda topic, num_segments=6: _script())

    resp = _client().post("/api/content/generate-script", data={"topic": "dậy sớm"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Thói quen dậy sớm"
    assert body["segments"][0]["visual_keywords"] == ["sunrise"]


def test_generate_script_endpoint_returns_400_on_claude_failure(monkeypatch):
    def boom(topic, num_segments=6):
        raise RuntimeError("claude lỗi")

    monkeypatch.setattr(content_routes, "generate_script", boom)

    resp = _client().post("/api/content/generate-script", data={"topic": "x"})

    assert resp.status_code == 400
    assert "claude lỗi" in resp.json()["detail"]


def test_start_pipeline_requires_topic_or_script_json():
    resp = _client().post("/api/content/jobs", data={"product_name": "p"})
    assert resp.status_code == 400


def test_start_pipeline_requires_product_name():
    # FastAPI Form(...) tự trả 422 khi field rỗng (trước khi vào route) —
    # route chỉ cần bảo đảm không lọt qua nếu FastAPI đổi hành vi validation.
    resp = _client().post(
        "/api/content/jobs", data={"topic": "dậy sớm", "product_name": ""}
    )
    assert resp.status_code == 422


def test_start_pipeline_with_topic_kicks_off_content_job(monkeypatch):
    started = {}

    def fake_start_content_pipeline(**kwargs):
        started.update(kwargs)
        return "content-job-1"

    monkeypatch.setattr(content_routes, "start_content_pipeline", fake_start_content_pipeline)

    resp = _client().post(
        "/api/content/jobs",
        data={"topic": "dậy sớm", "product_name": "video1", "n_outputs": 1},
    )

    assert resp.status_code == 200
    assert resp.json() == {"content_job_id": "content-job-1"}
    assert started["topic"] == "dậy sớm"
    assert started["manual_script"] is None
    assert callable(started["start_render"])


def test_start_pipeline_with_script_json_skips_claude(monkeypatch):
    started = {}

    def fake_start_content_pipeline(**kwargs):
        started.update(kwargs)
        return "content-job-2"

    monkeypatch.setattr(content_routes, "start_content_pipeline", fake_start_content_pipeline)

    script_json = (
        '{"title": "t", "description": "", '
        '"segments": [{"narration": "a", "visual_keywords": ["x"]}]}'
    )
    resp = _client().post(
        "/api/content/jobs",
        data={"script_json": script_json, "product_name": "video2"},
    )

    assert resp.status_code == 200
    assert started["manual_script"].title == "t"
    assert started["topic"] == ""


def test_start_pipeline_rejects_invalid_script_json():
    resp = _client().post(
        "/api/content/jobs",
        data={"script_json": "{not valid json", "product_name": "video3"},
    )
    assert resp.status_code in (400, 422)


def test_content_job_status_returns_404_for_unknown_id():
    resp = _client().get("/api/content/jobs/khong-ton-tai")
    assert resp.status_code == 404


def test_content_job_status_returns_job_dict():
    job_id = content_jobs.create_content_job()

    resp = _client().get(f"/api/content/jobs/{job_id}")

    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id
    assert resp.json()["stage"] == "pending"


def _make_render_job_with_output(tmp_path):
    from ytb_pipeline.webui.store import store

    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    job_id = "render-with-output"
    store.create(job_id, total_outputs=1)
    store.update(job_id, output_paths=(str(video_path),))
    return job_id, video_path


def test_publish_output_returns_404_for_unknown_job():
    resp = _client().post(
        "/api/content/publish/khong-ton-tai/0", data={"title": "t"}
    )
    assert resp.status_code == 404


def test_publish_output_returns_404_for_out_of_range_index(tmp_path):
    job_id, _ = _make_render_job_with_output(tmp_path)

    resp = _client().post(f"/api/content/publish/{job_id}/5", data={"title": "t"})

    assert resp.status_code == 404


def test_publish_output_calls_publish_video_and_returns_result(monkeypatch, tmp_path):
    job_id, video_path = _make_render_job_with_output(tmp_path)

    calls = {}

    class _FakeResult:
        youtube_id = "abc"
        url = "https://youtu.be/abc"

    def fake_publish_video(path, title, description, tags=(), *, thumbnail_path=None, publish_at=None):
        calls.update(
            path=path, title=title, description=description, tags=tags, publish_at=publish_at
        )
        return _FakeResult()

    monkeypatch.setattr(content_routes, "publish_video", fake_publish_video)

    resp = _client().post(
        f"/api/content/publish/{job_id}/0",
        data={
            "title": "Tiêu đề",
            "description": "Mô tả",
            "tags": "a, b, c",
            "publish_at": "2026-07-10T09:00:00Z",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"youtube_id": "abc", "url": "https://youtu.be/abc"}
    assert calls["path"] == video_path
    assert calls["tags"] == ("a", "b", "c")
    assert calls["publish_at"] == "2026-07-10T09:00:00Z"


def test_publish_output_returns_502_on_upload_failure(monkeypatch, tmp_path):
    job_id, _ = _make_render_job_with_output(tmp_path)

    def fake_publish_video(*a, **kw):
        raise RuntimeError("token hết hạn")

    monkeypatch.setattr(content_routes, "publish_video", fake_publish_video)

    resp = _client().post(f"/api/content/publish/{job_id}/0", data={"title": "t"})

    assert resp.status_code == 502
    assert "token hết hạn" in resp.json()["detail"]
