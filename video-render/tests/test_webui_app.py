"""Test FastAPI app qua TestClient — không gọi ffmpeg thật, monkeypatch render_output."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ytb_pipeline.webui import app as app_module
from ytb_pipeline.webui import jobs as jobs_module
from ytb_pipeline.webui.recommend import ProfileSuggestion


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_index_serves_html() -> None:
    client = TestClient(app_module.app)
    res = client.get("/")
    assert res.status_code == 200
    assert "video-render" in res.text


def test_index_has_preview_modal() -> None:
    client = TestClient(app_module.app)
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="previewModal"' in res.text
    assert 'id="previewVideo"' in res.text
    assert "renderAdjustedPreview" in res.text
    assert "Dùng kiểu này" in res.text


def test_index_has_manual_plan_preview_controls() -> None:
    client = TestClient(app_module.app)
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="checkManualPlanBtn"' in res.text
    assert 'id="createManualSampleBtn"' in res.text
    assert 'id="manualPlanPreview"' in res.text
    assert 'id="profileSuggestionBox"' in res.text
    assert 'id="applyProfileSuggestionBtn"' in res.text
    assert "Tự chọn clip" in res.text


def test_index_has_output_review_cut_controls() -> None:
    client = TestClient(app_module.app)
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="cutReviewModal"' in res.text
    assert 'id="cutTimeline"' in res.text
    assert 'id="emojiPresetSelect"' in res.text
    assert "Review & cắt" in res.text


def test_scan_rejects_missing_dir() -> None:
    client = TestClient(app_module.app)
    res = client.post("/api/scan", data={"scenes_dir": "/no/such/dir"})
    assert res.status_code == 400


def test_scan_returns_scene_clip_counts(tmp_path) -> None:
    _touch(tmp_path / "scene_00" / "1.1.mp4")
    _touch(tmp_path / "scene_00" / "1.2.mp4")
    client = TestClient(app_module.app)

    res = client.post("/api/scan", data={"scenes_dir": str(tmp_path)})

    assert res.status_code == 200
    body = res.json()
    assert body["scenes"][0]["scene_index"] == 0
    assert body["scenes"][0]["folder"] == "scene_00"
    assert body["scenes"][0]["clip_count"] == 2
    assert body["scenes"][0]["clips"] == [
        {"ref": "1.1", "filename": "1.1.mp4"},
        {"ref": "1.2", "filename": "1.2.mp4"},
    ]


def test_scan_returns_profile_suggestion(tmp_path) -> None:
    for scene_index in range(4):
        _touch(tmp_path / f"scene_{scene_index:02d}" / f"{scene_index + 1}.1.mp4")
        _touch(tmp_path / f"scene_{scene_index:02d}" / f"{scene_index + 1}.2.mp4")
        _touch(tmp_path / f"scene_{scene_index:02d}" / f"{scene_index + 1}.3.mp4")
    client = TestClient(app_module.app)

    res = client.post(
        "/api/scan",
        data={
            "scenes_dir": str(tmp_path),
            "aspect_ratio": "9:16",
            "mode": "random",
        },
    )

    assert res.status_code == 200
    suggestion = res.json()["suggestion"]
    assert suggestion["profile_name"] == "tiktok_shop_fast"
    assert "Video dọc" in suggestion["reason"]


def test_scan_job_reports_progress_and_result(tmp_path, monkeypatch) -> None:
    _touch(tmp_path / "scene_00" / "1.1.mp4")
    _touch(tmp_path / "scene_01" / "2.1.mp4")

    def fake_recommend_profile(scenes, *, aspect_ratio, mode, progress_callback=None):
        for index, scene in enumerate(scenes, start=1):
            if progress_callback is not None:
                progress_callback(index, len(scenes), scene.clips[0].path)
        return ProfileSuggestion(
            profile_name="affiliate_default",
            label="Affiliate mặc định",
            reason="Fake progress for test.",
        )

    monkeypatch.setattr(app_module, "recommend_profile", fake_recommend_profile)
    client = TestClient(app_module.app)

    res = client.post(
        "/api/scan/jobs",
        data={
            "scenes_dir": str(tmp_path),
            "aspect_ratio": "16:9",
            "mode": "random",
        },
    )

    assert res.status_code == 200
    job_id = res.json()["job_id"]
    for _ in range(50):
        status_res = client.get(f"/api/scan/jobs/{job_id}")
        body = status_res.json()
        if body["status"] == "done":
            break
        time.sleep(0.02)

    assert body["status"] == "done"
    assert body["completed_clips"] == 2
    assert body["total_clips"] == 2
    assert body["result"]["scenes"][0]["folder"] == "scene_00"
    assert body["result"]["suggestion"]["profile_name"] == "affiliate_default"


def test_scan_job_reports_failure(tmp_path, monkeypatch) -> None:
    _touch(tmp_path / "scene_00" / "1.1.mp4")

    def fake_recommend_profile(*args, **kwargs):
        raise RuntimeError("motion probe failed")

    monkeypatch.setattr(app_module, "recommend_profile", fake_recommend_profile)
    client = TestClient(app_module.app)

    res = client.post("/api/scan/jobs", data={"scenes_dir": str(tmp_path)})

    assert res.status_code == 200
    job_id = res.json()["job_id"]
    for _ in range(50):
        status_res = client.get(f"/api/scan/jobs/{job_id}")
        body = status_res.json()
        if body["status"] == "failed":
            break
        time.sleep(0.02)

    assert body["status"] == "failed"
    assert "motion probe failed" in body["error"]


def test_edit_profiles_endpoint_returns_common_profiles() -> None:
    client = TestClient(app_module.app)

    res = client.get("/api/edit-profiles")

    assert res.status_code == 200
    names = {profile["name"] for profile in res.json()["profiles"]}
    assert {"affiliate_default", "tiktok_shop_fast", "product_review_smooth"}.issubset(names)


def test_tuning_override_validation_accepts_valid_values() -> None:
    base = app_module.resolve_profile("affiliate_default").tuning

    tuning = app_module._parse_tuning_override(
        base,
        '{"motion_scale": 1.1, "pan_speed_x": "0.5"}',
    )

    assert tuning is not None
    assert tuning.motion_scale == 1.1
    assert tuning.pan_speed_x == 0.5


@pytest.mark.parametrize(
    ("raw_json", "message"),
    [
        ("not-json", "không phải JSON"),
        ("[]", "phải là object"),
        ('{"unknown": 1}', "field không hợp lệ"),
        ('{"motion_scale": "fast"}', "phải là số"),
        ('{"motion_scale": 9}', "phải trong khoảng"),
    ],
)
def test_tuning_override_validation_reports_user_errors(raw_json, message) -> None:
    base = app_module.resolve_profile("affiliate_default").tuning

    with pytest.raises(HTTPException) as exc_info:
        app_module._parse_tuning_override(base, raw_json)

    assert exc_info.value.status_code == 400
    assert message in exc_info.value.detail


def test_manual_plan_preview_accepts_short_lines(tmp_path) -> None:
    _touch(tmp_path / "scenes" / "scene_00" / "1.1.mp4")
    _touch(tmp_path / "scenes" / "scene_01" / "2.1.mp4")
    client = TestClient(app_module.app)

    res = client.post(
        "/api/manual-plan/preview",
        data={
            "scenes_dir": str(tmp_path / "scenes"),
            "manual_plan_text": "1.1, 2.1",
        },
    )

    assert res.status_code == 200
    assert res.json() == {
        "items": [
            {
                "video_label": "Video 1",
                "scenes": [
                    {"scene_label": "Cảnh 1", "clips": ["1.1.mp4"]},
                    {"scene_label": "Cảnh 2", "clips": ["2.1.mp4"]},
                ],
            }
        ]
    }


def test_manual_plan_preview_reports_line_error(tmp_path) -> None:
    _touch(tmp_path / "scenes" / "scene_00" / "1.1.mp4")
    client = TestClient(app_module.app)

    res = client.post(
        "/api/manual-plan/preview",
        data={
            "scenes_dir": str(tmp_path / "scenes"),
            "manual_plan_text": "9.9",
        },
    )

    assert res.status_code == 400
    assert "Dòng 1" in res.json()["detail"]


def test_render_rejects_invalid_input(tmp_path) -> None:
    client = TestClient(app_module.app)
    res = client.post(
        "/api/render",
        data={
            "scenes_dir": "/no/such/dir",
            "voice_track": str(tmp_path / "voice.wav"),
            "product_name": "p",
            "n_outputs": "1",
        },
    )
    assert res.status_code == 400


def test_render_end_to_end_reaches_done(tmp_path, monkeypatch) -> None:
    _touch(tmp_path / "scenes" / "scene_00" / "1.1.mp4")
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)

    monkeypatch.setattr(jobs_module, "render_video_only", lambda **kwargs: kwargs["out_path"])
    monkeypatch.setattr(
        "ytb_pipeline.assembler.duration.ClipLengthDurationStrategy.scene_durations",
        lambda self, groups, voice_track: tuple(1.0 for _ in groups),
    )

    client = TestClient(app_module.app)
    res = client.post(
        "/api/render",
        data={
            "scenes_dir": str(tmp_path / "scenes"),
            "voice_track": str(voice_track),
            "product_name": "p",
            "n_outputs": "1",
            "output_dir": str(tmp_path / "output"),
        },
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    for _ in range(50):
        status_res = client.get(f"/api/jobs/{job_id}")
        if status_res.json()["status"] in {"done", "failed"}:
            break
        time.sleep(0.05)

    body = status_res.json()
    assert body["status"] == "done"
    assert body["completed_outputs"] == 1


def test_preview_endpoint_starts_single_preview_job(tmp_path, monkeypatch) -> None:
    _touch(tmp_path / "scenes" / "scene_00" / "1.1.mp4")
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)

    monkeypatch.setattr(jobs_module, "render_video_only", lambda **kwargs: kwargs["out_path"])
    monkeypatch.setattr(
        jobs_module,
        "analyze_video_file",
        lambda path: jobs_module.VideoQualityResult(
            path=str(path),
            status="ready",
            title="Sẵn sàng đăng",
            summary="Video ổn, có thể dùng.",
            issues=(),
            technical_details=(),
        ),
    )
    monkeypatch.setattr(
        "ytb_pipeline.assembler.duration.ClipLengthDurationStrategy.scene_durations",
        lambda self, groups, voice_track: tuple(1.0 for _ in groups),
    )

    client = TestClient(app_module.app)
    res = client.post(
        "/api/preview",
        data={
            "scenes_dir": str(tmp_path / "scenes"),
            "voice_track": str(voice_track),
            "product_name": "p",
            "n_outputs": "5",
            "output_dir": str(tmp_path / "output"),
        },
    )
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    for _ in range(50):
        status_res = client.get(f"/api/jobs/{job_id}")
        if status_res.json()["status"] in {"done", "failed"}:
            break
        time.sleep(0.05)

    body = status_res.json()
    assert body["status"] == "done"
    assert body["total_outputs"] == 1
    assert body["quality_summary"]["title"] == "Sẵn sàng đăng"


def test_retry_endpoint_renders_saved_output_plan(tmp_path, monkeypatch) -> None:
    source_clip = tmp_path / "scenes" / "scene_00" / "1.1.mp4"
    _touch(source_clip)
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)

    monkeypatch.setattr(jobs_module, "render_output", lambda **kwargs: kwargs["out_path"])
    monkeypatch.setattr(
        jobs_module,
        "analyze_video_file",
        lambda path: jobs_module.VideoQualityResult(
            path=str(path),
            status="ready",
            title="Sẵn sàng đăng",
            summary="Video ổn, có thể dùng.",
            issues=(),
            technical_details=(),
        ),
    )

    source_job = app_module.store.create("source_retry", total_outputs=1)
    app_module.store.update(
        source_job.job_id,
        render_plans=(
            jobs_module.OutputRenderPlan(
                output_index=0,
                output_path=str(tmp_path / "output" / "variant_1.mp4"),
                profile_name="tiktok_shop_fast",
                duration_mode="clip_length",
                scene_durations=(3.0,),
                voice_track=str(voice_track),
                aspect_ratio="16:9",
                fit_mode="pad",
                watermark_path=None,
                watermark_position="bottom-right",
                watermark_scale=0.15,
                subtitle_path=None,
                groups=(
                    jobs_module.PlannedGroup(
                        scene_index=0,
                        clips=(
                            jobs_module.PlannedClip(
                                ref="1.1",
                                path=str(source_clip),
                                filename="1.1.mp4",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    client = TestClient(app_module.app)

    res = client.post("/api/jobs/source_retry/retry/0")

    assert res.status_code == 200
    retry_job_id = res.json()["job_id"]
    for _ in range(50):
        status_res = client.get(f"/api/jobs/{retry_job_id}")
        if status_res.json()["status"] in {"done", "failed"}:
            break
        time.sleep(0.05)
    body = status_res.json()
    assert body["status"] == "done"
    assert body["render_plans"][0]["profile_name"] == "smooth_retry"


def test_cut_endpoint_renders_final_from_saved_raw_plan(tmp_path, monkeypatch) -> None:
    raw_path = tmp_path / "output" / "variant_01_raw.mp4"
    _touch(raw_path)
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)

    monkeypatch.setattr(jobs_module, "cut_video_excluding_ranges", lambda **kwargs: kwargs["out_path"])
    monkeypatch.setattr(
        jobs_module,
        "conform_video_to_voice_duration",
        lambda **kwargs: kwargs["out_path"],
    )
    monkeypatch.setattr(jobs_module, "mux_voice_after_video", lambda **kwargs: kwargs["out_path"])
    monkeypatch.setattr(
        jobs_module,
        "analyze_video_file",
        lambda path: jobs_module.VideoQualityResult(
            path=str(path),
            status="ready",
            title="Sẵn sàng đăng",
            summary="Video ổn, có thể dùng.",
            issues=(),
            technical_details=(),
        ),
    )

    source_job = app_module.store.create("source_cut", total_outputs=1)
    app_module.store.update(
        source_job.job_id,
        output_paths=(str(raw_path),),
        render_plans=(
            jobs_module.OutputRenderPlan(
                output_index=0,
                output_path=str(raw_path),
                raw_video_path=str(raw_path),
                profile_name="affiliate_default",
                duration_mode="clip_length",
                scene_durations=(6.0,),
                voice_track=str(voice_track),
                aspect_ratio="16:9",
                fit_mode="pad",
                watermark_path=None,
                watermark_position="bottom-right",
                watermark_scale=0.15,
                subtitle_path=None,
                groups=(),
            ),
        ),
    )
    client = TestClient(app_module.app)

    res = client.post("/api/jobs/source_cut/cut/0", data={"cut_ranges_text": "1-2"})

    assert res.status_code == 200
    cut_job_id = res.json()["job_id"]
    for _ in range(50):
        status_res = client.get(f"/api/jobs/{cut_job_id}")
        if status_res.json()["status"] in {"done", "failed"}:
            break
        time.sleep(0.05)
    body = status_res.json()
    assert body["status"] == "done"
    assert body["render_plans"][0]["cut_ranges"][0]["start_sec"] == 1.0


def test_job_status_missing_returns_404() -> None:
    client = TestClient(app_module.app)
    res = client.get("/api/jobs/does-not-exist")
    assert res.status_code == 404
