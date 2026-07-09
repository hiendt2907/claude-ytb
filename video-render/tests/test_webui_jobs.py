"""Unit test cho JobStore/run_render_job — không gọi ffmpeg thật (monkeypatch render_output)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ytb_pipeline.assembler.models import Assignment, ClipGroup
from ytb_pipeline.webui import jobs as jobs_module
from ytb_pipeline.webui.jobs import JobStore, RenderRequest, run_render_job


def test_job_store_create_get_update_are_immutable_copies() -> None:
    store = JobStore()
    job = store.create("abc", total_outputs=3)
    assert job.status == "pending"

    store.update("abc", status="running")
    updated = store.get("abc")
    assert updated is not None
    assert updated.status == "running"
    assert job.status == "pending"  # bản gốc không bị mutate


def test_job_store_get_missing_returns_none() -> None:
    store = JobStore()
    assert store.get("missing") is None


def test_job_store_persists_done_jobs_for_restart(tmp_path) -> None:
    store = JobStore(persistence_dir=tmp_path / "jobs")
    store.create("job_persist", total_outputs=1)
    store.update(
        "job_persist",
        status="done",
        completed_outputs=1,
        output_paths=(str(tmp_path / "variant_1.mp4"),),
    )

    restored = JobStore(persistence_dir=tmp_path / "jobs")
    job = restored.get("job_persist")

    assert job is not None
    assert job.status == "done"
    assert job.completed_outputs == 1
    assert job.output_paths == (str(tmp_path / "variant_1.mp4"),)


def test_job_store_restores_nested_quality_and_render_plan(tmp_path) -> None:
    store = JobStore(persistence_dir=tmp_path / "jobs")
    store.create("job_nested", total_outputs=1)
    store.update(
        "job_nested",
        status="done",
        completed_outputs=1,
        output_paths=(str(tmp_path / "variant_1_final.mp4"),),
        quality_summary=jobs_module.BatchQualitySummary(
            status="review",
            title="Cần xem lại",
            summary="Có cảnh cần xem lại.",
            action_label="Mở video",
            messages=("coverage warning",),
        ),
        quality_results=(
            jobs_module.VideoQualityResult(
                path=str(tmp_path / "variant_1_final.mp4"),
                status="review",
                title="Cần xem lại",
                summary="Có issue.",
                issues=(
                    jobs_module.VideoQualityIssue(
                        severity="warning",
                        message="Độ dài tiếng và hình lệch nhau.",
                        technical_detail="duration delta",
                    ),
                ),
                technical_details=("duration delta",),
            ),
        ),
        render_plans=(
            jobs_module.OutputRenderPlan(
                output_index=0,
                output_path=str(tmp_path / "variant_1_final.mp4"),
                profile_name="affiliate_default",
                duration_mode="clip_length",
                scene_durations=(1.25,),
                voice_track=str(tmp_path / "voice.mp3"),
                aspect_ratio="9:16",
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
                                path=str(tmp_path / "scene_00" / "1.1.mp4"),
                                filename="1.1.mp4",
                            ),
                        ),
                        segments=(
                            jobs_module.PlannedSegment(
                                clip_ref="1.1",
                                clip_path=str(tmp_path / "scene_00" / "1.1.mp4"),
                                start_sec=0.0,
                                end_sec=1.25,
                                score=0.8,
                            ),
                        ),
                    ),
                ),
                raw_video_path=str(tmp_path / "variant_1_raw.mp4"),
                final_video_path=str(tmp_path / "variant_1_final.mp4"),
                emoji_preset="sales",
                trim_mode="auto_smart",
                cut_ranges=(jobs_module.PlannedCutRange(start_sec=0.1, end_sec=0.3),),
            ),
        ),
    )

    restored = JobStore(persistence_dir=tmp_path / "jobs")
    job = restored.get("job_nested")

    assert job is not None
    assert job.quality_summary is not None
    assert job.quality_summary.messages == ("coverage warning",)
    assert job.quality_results[0].issues[0].technical_detail == "duration delta"
    assert job.render_plans[0].groups[0].segments[0].end_sec == 1.25
    assert job.render_plans[0].cut_ranges[0].end_sec == 0.3


def test_job_store_marks_running_jobs_failed_after_restart(tmp_path) -> None:
    store = JobStore(persistence_dir=tmp_path / "jobs")
    store.create("job_running", total_outputs=1)
    store.update("job_running", status="running")

    restored = JobStore(persistence_dir=tmp_path / "jobs")
    job = restored.get("job_running")

    assert job is not None
    assert job.status == "failed"
    assert "khởi động lại" in (job.error or "")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_run_render_job_updates_progress_and_marks_done(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    _touch(scenes_dir / "scene_00" / "1.1.mp4")
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)

    monkeypatch.setattr(
        jobs_module, "render_video_only", lambda **kwargs: kwargs["out_path"]
    )
    monkeypatch.setattr(
        "ytb_pipeline.assembler.duration.ClipLengthDurationStrategy.scene_durations",
        lambda self, groups, voice_track: tuple(1.0 for _ in groups),
    )

    store = JobStore()
    request = RenderRequest(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name="p",
        n_outputs=2,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
        duration_mode="clip_length",
        seed=1,
    )
    store.create("job1", total_outputs=2)

    run_render_job("job1", store, request)

    job = store.get("job1")
    assert job is not None
    assert job.status == "done"
    assert job.completed_outputs == 2
    assert len(job.output_paths) == 2


def test_run_render_job_passes_edit_profile_to_renderer(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    _touch(scenes_dir / "scene_00" / "1.1.mp4")
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)
    seen_profiles: list[str] = []

    def fake_render_output(**kwargs):
        seen_profiles.append(kwargs["edit_profile"].name)
        return kwargs["out_path"]

    monkeypatch.setattr(jobs_module, "render_video_only", fake_render_output)
    monkeypatch.setattr(
        "ytb_pipeline.assembler.duration.ClipLengthDurationStrategy.scene_durations",
        lambda self, groups, voice_track: tuple(1.0 for _ in groups),
    )

    store = JobStore()
    request = RenderRequest(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name="p",
        n_outputs=1,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
        edit_profile_name="tiktok_shop_fast",
    )
    store.create("job_profile", total_outputs=1)

    run_render_job("job_profile", store, request)

    assert seen_profiles == ["tiktok_shop_fast"]


def test_run_render_job_collects_user_friendly_quality_summary(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    _touch(scenes_dir / "scene_00" / "1.1.mp4")
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

    store = JobStore()
    request = RenderRequest(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name="p",
        n_outputs=1,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
    )
    store.create("job_quality", total_outputs=1)

    run_render_job("job_quality", store, request)

    job = store.get("job_quality")
    assert job is not None
    assert job.status == "done"
    assert job.quality_summary is not None
    assert job.quality_summary.title == "Sẵn sàng đăng"
    assert job.quality_results[0].summary == "Video ổn, có thể dùng."


def test_run_render_job_skips_smart_trim_on_initial_render(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    _touch(scenes_dir / "scene_00" / "1.1.mp4")
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)
    rendered_group_segments = []

    def fake_render_output(**kwargs):
        rendered_group_segments.append(kwargs["assignment"].groups[0].segments)
        return kwargs["out_path"]

    monkeypatch.setattr(jobs_module, "render_video_only", fake_render_output)
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
        lambda self, groups, voice_track: tuple(12.0 for _ in groups),
    )
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Smart Trim must not run before the first render")

    monkeypatch.setattr(jobs_module, "enrich_assignment_with_smart_trim", fail_if_called)

    store = JobStore()
    request = RenderRequest(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name="p",
        n_outputs=1,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
    )
    store.create("job_smart_trim", total_outputs=1)

    run_render_job("job_smart_trim", store, request)

    assert rendered_group_segments == [()]


def test_run_render_job_stores_render_plan_metadata(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    _touch(scenes_dir / "scene_00" / "1.1.mp4")
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
        lambda self, groups, voice_track: tuple(8.0 for _ in groups),
    )

    store = JobStore()
    request = RenderRequest(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name="p",
        n_outputs=1,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
        edit_profile_name="tiktok_shop_fast",
    )
    store.create("job_plan", total_outputs=1)

    run_render_job("job_plan", store, request)

    job = store.get("job_plan")
    assert job is not None
    assert len(job.render_plans) == 1
    plan = job.render_plans[0]
    assert plan.output_index == 0
    assert plan.profile_name == "tiktok_shop_fast"
    assert plan.duration_mode == "clip_length"
    assert plan.scene_durations == (8.0,)
    assert plan.groups[0].clips[0].ref == "1.1"
    assert plan.groups[0].segments == ()


def test_run_retry_job_uses_saved_plan_with_smooth_retry(tmp_path, monkeypatch) -> None:
    rendered: list[dict] = []

    def fake_render_output(**kwargs):
        rendered.append(kwargs)
        return kwargs["out_path"]

    monkeypatch.setattr(jobs_module, "render_output", fake_render_output)
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

    source_clip = tmp_path / "scenes" / "scene_00" / "1.1.mp4"
    _touch(source_clip)
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)
    plan = jobs_module.OutputRenderPlan(
        output_index=3,
        output_path=str(tmp_path / "output" / "variant_4.mp4"),
        profile_name="tiktok_shop_fast",
        duration_mode="clip_length",
        scene_durations=(3.5,),
        voice_track=str(voice_track),
        aspect_ratio="9:16",
        fit_mode="crop",
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
                segments=(
                    jobs_module.PlannedSegment(
                        clip_ref="1.1",
                        clip_path=str(source_clip),
                        start_sec=1.0,
                        end_sec=4.5,
                        score=0.9,
                    ),
                ),
            ),
        ),
    )
    store = JobStore()
    store.create("retry_job", total_outputs=1)

    jobs_module.run_retry_job("retry_job", store, plan)

    job = store.get("retry_job")
    assert job is not None
    assert job.status == "done"
    assert job.completed_outputs == 1
    assert rendered[0]["edit_profile"].name == "smooth_retry"
    assert rendered[0]["aspect_ratio"] == "9:16"
    assert rendered[0]["fit_mode"] == "crop"
    assert rendered[0]["assignment"].groups[0].segments[0].start_sec == 1.0
    assert Path(job.output_paths[0]).name == "variant_4_smooth_retry.mp4"


def test_run_cut_job_cuts_raw_video_then_muxes_voice(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, Path, Path]] = []

    def fake_cut_video_excluding_ranges(**kwargs):
        calls.append(("cut", kwargs["in_path"], kwargs["out_path"]))
        return kwargs["out_path"]

    def fake_conform_video_to_voice(**kwargs):
        calls.append(("conform", kwargs["video_path"], kwargs["out_path"]))
        return kwargs["out_path"]

    def fake_mux_voice_after_video(**kwargs):
        calls.append(("mux", kwargs["video_path"], kwargs["out_path"]))
        return kwargs["out_path"]

    monkeypatch.setattr(jobs_module, "cut_video_excluding_ranges", fake_cut_video_excluding_ranges)
    monkeypatch.setattr(jobs_module, "conform_video_to_voice_duration", fake_conform_video_to_voice)
    monkeypatch.setattr(jobs_module, "mux_voice_after_video", fake_mux_voice_after_video)
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

    raw_path = tmp_path / "output" / "variant_01_raw.mp4"
    _touch(raw_path)
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)
    plan = jobs_module.OutputRenderPlan(
        output_index=0,
        output_path=str(raw_path),
        raw_video_path=str(raw_path),
        profile_name="affiliate_default",
        duration_mode="clip_length",
        scene_durations=(8.0,),
        voice_track=str(voice_track),
        aspect_ratio="16:9",
        fit_mode="pad",
        watermark_path=None,
        watermark_position="bottom-right",
        watermark_scale=0.15,
        subtitle_path=None,
        groups=(),
    )
    store = JobStore()
    store.create("cut_job", total_outputs=1)

    jobs_module.run_cut_job("cut_job", store, plan, "2-4\n6-7")

    job = store.get("cut_job")
    assert job is not None
    assert job.status == "done"
    assert job.completed_outputs == 1
    assert calls[0][0] == "cut"
    assert calls[1][0] == "conform"
    assert calls[2][0] == "mux"
    assert Path(job.output_paths[0]).name == "variant_01_final.mp4"
    assert job.render_plans[0].cut_ranges[0].start_sec == 2.0


def test_run_render_job_auto_smart_outputs_final_video(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    _touch(scenes_dir / "scene_00" / "1.1.mp4")
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)
    calls: list[str] = []

    monkeypatch.setattr(
        jobs_module, "render_video_only", lambda **kwargs: kwargs["out_path"]
    )
    monkeypatch.setattr(
        jobs_module,
        "suggest_cut_ranges_for_video",
        lambda path: (jobs_module.CutRange(start_sec=1.0, end_sec=2.0),),
    )
    monkeypatch.setattr(
        jobs_module,
        "cut_video_excluding_ranges",
        lambda **kwargs: calls.append("cut") or kwargs["out_path"],
    )
    monkeypatch.setattr(
        jobs_module,
        "conform_video_to_voice_duration",
        lambda **kwargs: calls.append("conform") or kwargs["out_path"],
    )
    monkeypatch.setattr(
        jobs_module,
        "mux_voice_after_video",
        lambda **kwargs: calls.append("mux") or kwargs["out_path"],
    )
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
        lambda self, groups, voice_track: tuple(4.0 for _ in groups),
    )

    store = JobStore()
    request = RenderRequest(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name="p",
        n_outputs=1,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
        trim_mode="auto_smart",
    )
    store.create("auto_job", total_outputs=1)

    run_render_job("auto_job", store, request)

    job = store.get("auto_job")
    assert job is not None
    assert job.status == "done"
    assert calls == ["cut", "conform", "mux"]
    assert Path(job.output_paths[0]).name == "variant_1_final.mp4"
    assert job.render_plans[0].raw_video_path is not None
    assert job.render_plans[0].final_video_path == job.output_paths[0]
    assert job.render_plans[0].cut_ranges[0].start_sec == 1.0


def test_preview_request_renders_single_output_in_preview_folder(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    for index in range(5):
        _touch(scenes_dir / f"scene_{index:02d}" / f"{index + 1}.1.mp4")
    voice_track = tmp_path / "voice.wav"
    _touch(voice_track)
    seen_paths: list[Path] = []
    seen_durations: list[tuple[float, ...]] = []
    seen_group_counts: list[int] = []

    def fake_render_output(**kwargs):
        seen_paths.append(kwargs["out_path"])
        seen_durations.append(kwargs["scene_durations"])
        seen_group_counts.append(len(kwargs["assignment"].groups))
        return kwargs["out_path"]

    monkeypatch.setattr(jobs_module, "render_video_only", fake_render_output)
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
        lambda self, groups, voice_track: tuple(10.0 for _ in groups),
    )

    store = JobStore()
    request = RenderRequest(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name="p",
        n_outputs=5,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
        job_kind="preview",
    )
    store.create("job_preview", total_outputs=1)

    run_render_job("job_preview", store, request)

    job = store.get("job_preview")
    assert job is not None
    assert job.status == "done"
    assert job.total_outputs == 1
    assert job.completed_outputs == 1
    assert seen_paths
    assert "_preview" in seen_paths[0].parts
    assert seen_group_counts == [4]
    assert len(seen_durations[0]) == 4
    assert all(0 < duration <= 3.0 for duration in seen_durations[0])
    assert job.quality_summary is not None
    assert job.quality_summary.messages == ()


def test_build_preview_sample_uses_start_middle_and_end_for_long_videos() -> None:
    clips = tuple(
        ClipGroup(scene_index=index, clips=())
        for index in range(8)
    )
    assignment = Assignment(output_index=0, groups=clips)

    preview_assignment, preview_durations = jobs_module.build_preview_sample(
        assignment,
        tuple(10.0 for _ in clips),
    )

    assert [group.scene_index for group in preview_assignment.groups] == [0, 2, 5, 7]
    assert preview_durations == (3.0, 3.0, 3.0, 3.0)


def test_run_render_job_marks_failed_on_error(tmp_path) -> None:
    store = JobStore()
    request = RenderRequest(
        scenes_dir=tmp_path / "does_not_exist",
        voice_track=tmp_path / "voice.wav",
        product_name="p",
        n_outputs=1,
        output_dir=tmp_path / "output",
        tmp_dir=tmp_path / "tmp",
    )
    store.create("job2", total_outputs=1)

    run_render_job("job2", store, request)

    job = store.get("job2")
    assert job is not None
    assert job.status == "failed"
    assert job.error is not None


def test_build_duration_strategy_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        jobs_module.build_duration_strategy("bogus")
