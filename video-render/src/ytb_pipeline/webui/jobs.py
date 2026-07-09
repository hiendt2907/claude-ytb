"""Quản lý render job chạy nền cho web UI. Tách khỏi FastAPI để test độc lập,
không cần khởi động server thật.
"""

from __future__ import annotations

import json
import random
import threading
import traceback
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ytb_pipeline.assembler.assignment import build_assignments, find_duplicate_assignments
from ytb_pipeline.assembler.duration import (
    ClipLengthDurationStrategy,
    DurationStrategy,
    VoiceSilenceDurationStrategy,
)
from ytb_pipeline.assembler.manual_plan import parse_manual_plan
from ytb_pipeline.assembler.models import Assignment, Clip, ClipGroup, ClipSegment, SceneFolder
from ytb_pipeline.assembler.naming import output_path
from ytb_pipeline.assembler.profiles import RenderTuning, resolve_profile
from ytb_pipeline.assembler.cutting import (
    CutRange,
    apply_emoji_preset,
    conform_video_to_voice_duration,
    cut_video_excluding_ranges,
    mux_voice_after_video,
    parse_cut_ranges,
    suggest_cut_ranges_for_video,
)
from ytb_pipeline.assembler.render import render_output, render_video_only
from ytb_pipeline.assembler.scanning import scan_scene_folders
from ytb_pipeline.assembler.smart_trim import enrich_assignment_with_smart_trim
from ytb_pipeline.webui.quality import (
    BatchQualitySummary,
    VideoQualityIssue,
    VideoQualityResult,
    analyze_video_file,
    summarize_quality,
)

JobStatus = Literal["pending", "running", "done", "failed"]
JobKind = Literal["full", "preview"]
_PREVIEW_MAX_SCENES = 4
_PREVIEW_SCENE_DURATION = 3.0


@dataclass(frozen=True)
class RenderJob:
    job_id: str
    status: JobStatus
    total_outputs: int
    job_kind: JobKind = "full"
    completed_outputs: int = 0
    error: str | None = None
    output_paths: tuple[str, ...] = ()
    quality_summary: BatchQualitySummary | None = None
    quality_results: tuple[VideoQualityResult, ...] = ()
    render_plans: tuple["OutputRenderPlan", ...] = ()
    log_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedClip:
    ref: str
    path: str
    filename: str


@dataclass(frozen=True)
class PlannedSegment:
    clip_ref: str
    clip_path: str
    start_sec: float
    end_sec: float
    score: float


@dataclass(frozen=True)
class PlannedCutRange:
    start_sec: float
    end_sec: float


@dataclass(frozen=True)
class PlannedGroup:
    scene_index: int
    clips: tuple[PlannedClip, ...]
    segments: tuple[PlannedSegment, ...] = ()


@dataclass(frozen=True)
class OutputRenderPlan:
    output_index: int
    output_path: str
    profile_name: str
    duration_mode: str
    scene_durations: tuple[float, ...]
    voice_track: str
    aspect_ratio: str
    fit_mode: str
    watermark_path: str | None
    watermark_position: str
    watermark_scale: float
    subtitle_path: str | None
    groups: tuple[PlannedGroup, ...]
    raw_video_path: str | None = None
    cut_video_path: str | None = None
    final_video_path: str | None = None
    emoji_preset: str = "none"
    trim_mode: str = "manual_review"
    cut_ranges: tuple[PlannedCutRange, ...] = ()


def _quality_issue_from_dict(data: dict[str, Any]) -> VideoQualityIssue:
    return VideoQualityIssue(
        severity=data["severity"],
        message=data["message"],
        technical_detail=data["technical_detail"],
    )


def _quality_result_from_dict(data: dict[str, Any]) -> VideoQualityResult:
    return VideoQualityResult(
        path=data["path"],
        status=data["status"],
        title=data["title"],
        summary=data["summary"],
        issues=tuple(_quality_issue_from_dict(item) for item in data.get("issues", ())),
        technical_details=tuple(data.get("technical_details", ())),
    )


def _quality_summary_from_dict(data: dict[str, Any] | None) -> BatchQualitySummary | None:
    if data is None:
        return None
    return BatchQualitySummary(
        status=data["status"],
        title=data["title"],
        summary=data["summary"],
        action_label=data["action_label"],
        messages=tuple(data.get("messages", ())),
    )


def _planned_group_from_dict(data: dict[str, Any]) -> PlannedGroup:
    return PlannedGroup(
        scene_index=data["scene_index"],
        clips=tuple(PlannedClip(**item) for item in data.get("clips", ())),
        segments=tuple(PlannedSegment(**item) for item in data.get("segments", ())),
    )


def _render_plan_from_dict(data: dict[str, Any]) -> OutputRenderPlan:
    return OutputRenderPlan(
        output_index=data["output_index"],
        output_path=data["output_path"],
        profile_name=data["profile_name"],
        duration_mode=data["duration_mode"],
        scene_durations=tuple(data.get("scene_durations", ())),
        voice_track=data["voice_track"],
        aspect_ratio=data["aspect_ratio"],
        fit_mode=data["fit_mode"],
        watermark_path=data.get("watermark_path"),
        watermark_position=data["watermark_position"],
        watermark_scale=data["watermark_scale"],
        subtitle_path=data.get("subtitle_path"),
        groups=tuple(_planned_group_from_dict(item) for item in data.get("groups", ())),
        raw_video_path=data.get("raw_video_path"),
        cut_video_path=data.get("cut_video_path"),
        final_video_path=data.get("final_video_path"),
        emoji_preset=data.get("emoji_preset", "none"),
        trim_mode=data.get("trim_mode", "manual_review"),
        cut_ranges=tuple(PlannedCutRange(**item) for item in data.get("cut_ranges", ())),
    )


def _render_job_from_dict(data: dict[str, Any]) -> RenderJob:
    status = data["status"]
    error = data.get("error")
    log_lines = tuple(data.get("log_lines", ()))
    if status in {"pending", "running"}:
        status = "failed"
        error = "App đã khởi động lại khi job này chưa hoàn tất."
        log_lines = (*log_lines, "[restore] Job bị dừng vì app đã khởi động lại.")
    return RenderJob(
        job_id=data["job_id"],
        status=status,
        total_outputs=data["total_outputs"],
        job_kind=data.get("job_kind", "full"),
        completed_outputs=data.get("completed_outputs", 0),
        error=error,
        output_paths=tuple(data.get("output_paths", ())),
        quality_summary=_quality_summary_from_dict(data.get("quality_summary")),
        quality_results=tuple(_quality_result_from_dict(item) for item in data.get("quality_results", ())),
        render_plans=tuple(_render_plan_from_dict(item) for item in data.get("render_plans", ())),
        log_lines=log_lines,
    )


@dataclass(frozen=True)
class RenderRequest:
    scenes_dir: Path
    voice_track: Path
    product_name: str
    n_outputs: int
    output_dir: Path
    tmp_dir: Path
    duration_mode: str = "clip_length"
    seed: int | None = None
    aspect_ratio: str = "16:9"
    fit_mode: str = "pad"  # "pad" (letterbox) | "crop" (lấp đầy khung, mất viền)
    mode: str = "random"  # "random" | "manual"
    manual_plan_text: str = ""
    watermark_path: Path | None = None
    watermark_position: str = "bottom-right"
    watermark_scale: float = 0.15
    subtitle_path: Path | None = None
    edit_profile_name: str = "affiliate_default"
    tuning_override: RenderTuning | None = None
    emoji_preset: str = "none"
    trim_mode: str = "manual_review"
    job_kind: JobKind = "full"


def build_duration_strategy(mode: str) -> DurationStrategy:
    if mode == "clip_length":
        return ClipLengthDurationStrategy()
    if mode == "voice_silence":
        return VoiceSilenceDurationStrategy()
    raise ValueError(f"duration_mode không hợp lệ: {mode!r} (dùng clip_length | voice_silence)")


def build_assignments_for_request(
    scenes: tuple[SceneFolder, ...], request: RenderRequest
) -> tuple[Assignment, ...]:
    """Chọn nguồn assignment theo request.mode: random (thuật toán tự chia
    nhóm) hoặc manual (user tự chỉ định qua request.manual_plan_text)."""
    if request.mode == "manual":
        return parse_manual_plan(request.manual_plan_text, scenes)
    if request.mode == "random":
        rng = random.Random(request.seed)
        return build_assignments(scenes, request.n_outputs, rng)
    raise ValueError(f"mode không hợp lệ: {request.mode!r} (dùng random | manual)")


def _clip_ref(segment_or_clip: ClipSegment | Clip) -> str:
    clip = segment_or_clip.clip if isinstance(segment_or_clip, ClipSegment) else segment_or_clip
    return ".".join(str(part) for part in clip.sub_index)


def _render_plan_for_output(
    assignment: Assignment,
    durations: tuple[float, ...],
    out_path: Path,
    request: RenderRequest,
    profile_name: str,
) -> OutputRenderPlan:
    groups: list[PlannedGroup] = []
    for group in assignment.groups:
        clips = tuple(
            PlannedClip(
                ref=_clip_ref(clip),
                path=str(clip.path),
                filename=clip.path.name,
            )
            for clip in group.clips
        )
        segments = tuple(
            PlannedSegment(
                clip_ref=_clip_ref(segment),
                clip_path=str(segment.clip.path),
                start_sec=segment.start_sec,
                end_sec=segment.end_sec,
                score=segment.score,
            )
            for segment in group.segments
        )
        groups.append(
            PlannedGroup(
                scene_index=group.scene_index,
                clips=clips,
                segments=segments,
            )
        )
    return OutputRenderPlan(
        output_index=assignment.output_index,
        output_path=str(out_path),
        profile_name=profile_name,
        duration_mode=request.duration_mode,
        scene_durations=durations,
        voice_track=str(request.voice_track),
        aspect_ratio=request.aspect_ratio,
        fit_mode=request.fit_mode,
        watermark_path=str(request.watermark_path) if request.watermark_path is not None else None,
        watermark_position=request.watermark_position,
        watermark_scale=request.watermark_scale,
        subtitle_path=str(request.subtitle_path) if request.subtitle_path is not None else None,
        groups=tuple(groups),
        raw_video_path=str(out_path),
        emoji_preset=request.emoji_preset,
        trim_mode=request.trim_mode,
    )


class JobStore:
    """In-memory job registry. Job objects là frozen dataclass — mọi cập nhật
    tạo bản sao mới qua `dataclasses.replace()`, không mutate bản cũ."""

    def __init__(self, persistence_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, RenderJob] = {}
        self._persistence_dir = persistence_dir
        if self._persistence_dir is not None:
            self._persistence_dir.mkdir(parents=True, exist_ok=True)
            self._load_persisted_jobs()

    def _job_path(self, job_id: str) -> Path:
        if self._persistence_dir is None:
            raise RuntimeError("JobStore persistence is disabled")
        return self._persistence_dir / f"{job_id}.json"

    def _persist_locked(self, job: RenderJob) -> None:
        if self._persistence_dir is None:
            return
        payload = asdict(job)
        path = self._job_path(job.job_id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _load_persisted_jobs(self) -> None:
        if self._persistence_dir is None:
            return
        for path in sorted(self._persistence_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                job = _render_job_from_dict(data)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            self._jobs[job.job_id] = job

    def create(self, job_id: str, total_outputs: int, job_kind: JobKind = "full") -> RenderJob:
        job = RenderJob(
            job_id=job_id,
            status="pending",
            total_outputs=total_outputs,
            job_kind=job_kind,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._persist_locked(job)
        return job

    def get(self, job_id: str) -> RenderJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: object) -> None:
        with self._lock:
            current = self._jobs[job_id]
            updated = replace(current, **changes)
            self._jobs[job_id] = updated
            self._persist_locked(updated)

    def append_log(self, job_id: str, line: str) -> None:
        timestamped = f"[{datetime.now().strftime('%H:%M:%S')}] {line}"
        with self._lock:
            current = self._jobs[job_id]
            updated = replace(current, log_lines=(*current.log_lines, timestamped))
            self._jobs[job_id] = updated
            self._persist_locked(updated)


def run_render_job(job_id: str, store: JobStore, request: RenderRequest) -> None:
    """Chạy toàn bộ render N output, cập nhật tiến độ vào store sau mỗi output.

    Bắt mọi exception để job không "treo" ở trạng thái running khi ffmpeg lỗi.
    """
    store.update(job_id, status="running", job_kind=request.job_kind)
    if request.job_kind == "preview":
        store.append_log(job_id, f"Tạo bản xem thử cho '{request.product_name}'")
    else:
        store.append_log(job_id, f"Bắt đầu render '{request.product_name}'")
    try:
        scenes = scan_scene_folders(request.scenes_dir)
        store.append_log(job_id, f"Quét được {len(scenes)} cảnh trong {request.scenes_dir}")
        assignment_request = (
            replace(request, n_outputs=1)
            if request.job_kind == "preview" and request.mode == "random"
            else request
        )
        assignments = build_assignments_for_request(scenes, assignment_request)
        if request.job_kind == "preview":
            assignments = assignments[:1]
        total_outputs = len(assignments)
        store.update(job_id, total_outputs=total_outputs)

        duplicates = find_duplicate_assignments(assignments)
        for group in duplicates:
            variant_names = ", ".join(f"variant_{i + 1}" for i in group)
            store.append_log(
                job_id, f"CẢNH BÁO: các output sau ra tổ hợp clip giống hệt nhau: {variant_names}"
            )

        strategy = build_duration_strategy(request.duration_mode)
        edit_profile = resolve_profile(request.edit_profile_name)
        if request.tuning_override is not None:
            edit_profile = replace(edit_profile, tuning=request.tuning_override)

        output_dir = (
            request.output_dir / "_preview"
            if request.job_kind == "preview"
            else request.output_dir
        )
        product_name = (
            f"{request.product_name}_preview"
            if request.job_kind == "preview"
            else request.product_name
        )
        output_paths: list[str] = []
        quality_results: list[VideoQualityResult] = []
        render_plans: list[OutputRenderPlan] = []
        for assignment in assignments:
            durations = strategy.scene_durations(assignment.groups, request.voice_track)
            if request.job_kind == "preview":
                assignment, durations = build_preview_sample(assignment, durations)
            out_path = output_path(
                output_dir,
                product_name,
                assignment.output_index,
                total_outputs,
            )
            raw_out_path = out_path.with_name(f"{out_path.stem}_raw{out_path.suffix}")
            render_video_only(
                assignment=assignment,
                scene_durations=durations,
                out_path=raw_out_path,
                tmp_dir=request.tmp_dir / f"output_{assignment.output_index:03d}",
                aspect_ratio=request.aspect_ratio,
                fit_mode=request.fit_mode,
                watermark_path=request.watermark_path,
                watermark_position=request.watermark_position,
                watermark_scale=request.watermark_scale,
                subtitle_path=request.subtitle_path,
                edit_profile=edit_profile,
            )
            plan = _render_plan_for_output(
                assignment=assignment,
                durations=durations,
                out_path=raw_out_path,
                request=request,
                profile_name=edit_profile.name,
            )
            current_output_path = raw_out_path
            if request.trim_mode in {"auto_smart", "none"} and request.job_kind == "full":
                cut_ranges = (
                    suggest_cut_ranges_for_video(raw_out_path)
                    if request.trim_mode == "auto_smart"
                    else ()
                )
                if request.trim_mode == "auto_smart":
                    store.append_log(job_id, f"Tự tối ưu phát hiện {len(cut_ranges)} đoạn cần bỏ")
                current_output_path, plan = _finalize_raw_plan(plan, cut_ranges)
                store.append_log(job_id, "Đã gắn voice sau cùng và xuất final")

            output_paths.append(str(current_output_path))
            render_plans.append(plan)
            quality_result = analyze_video_file(current_output_path)
            quality_results.append(quality_result)
            store.update(
                job_id,
                completed_outputs=len(output_paths),
                output_paths=tuple(output_paths),
                quality_results=tuple(quality_results),
                render_plans=tuple(render_plans),
            )
            store.append_log(
                job_id,
                f"Hoàn tất output {len(output_paths)}/{total_outputs}: {current_output_path.name}",
            )
            if request.trim_mode == "manual_review" or request.job_kind == "preview":
                store.append_log(job_id, "Video thô chưa gắn voice, sẵn sàng review/cắt")
            store.append_log(job_id, f"Kiểm tra chất lượng: {quality_result.title}")
            for issue in quality_result.issues:
                store.append_log(job_id, issue.message)

        batch_messages = (
            ()
            if request.job_kind == "preview"
            else _source_coverage_messages(scenes, assignments)
        )
        quality_summary = summarize_quality(tuple(quality_results), batch_messages)
        store.update(job_id, status="done", quality_summary=quality_summary)
        store.append_log(job_id, quality_summary.title)
        store.append_log(job_id, "Hoàn tất toàn bộ")
    except Exception as exc:  # noqa: BLE001 — job runner phải nuốt lỗi để báo qua UI
        store.update(job_id, status="failed", error=f"{exc}\n{traceback.format_exc()}")
        store.append_log(job_id, f"Lỗi: {exc}")


def _sub_index_from_ref(ref: str) -> tuple[int, ...]:
    return tuple(int(part) for part in ref.split(".") if part.strip())


def _assignment_from_render_plan(plan: OutputRenderPlan) -> Assignment:
    groups: list[ClipGroup] = []
    for planned_group in plan.groups:
        clips = tuple(
            Clip(
                path=Path(planned_clip.path),
                scene_index=planned_group.scene_index,
                sub_index=_sub_index_from_ref(planned_clip.ref),
            )
            for planned_clip in planned_group.clips
        )
        clip_lookup = {_clip_ref(clip): clip for clip in clips}
        segments = tuple(
            ClipSegment(
                clip=clip_lookup.get(segment.clip_ref)
                or Clip(
                    path=Path(segment.clip_path),
                    scene_index=planned_group.scene_index,
                    sub_index=_sub_index_from_ref(segment.clip_ref),
                ),
                start_sec=segment.start_sec,
                end_sec=segment.end_sec,
                score=segment.score,
            )
            for segment in planned_group.segments
        )
        groups.append(
            ClipGroup(
                scene_index=planned_group.scene_index,
                clips=clips,
                segments=segments,
            )
        )
    return Assignment(output_index=0, groups=tuple(groups))


def _retry_output_path(original_path: Path) -> Path:
    return original_path.with_name(f"{original_path.stem}_smooth_retry{original_path.suffix}")


def _cut_output_paths(raw_path: Path) -> tuple[Path, Path, Path, Path]:
    base_stem = raw_path.stem.removesuffix("_raw")
    cut_path = raw_path.with_name(f"{base_stem}_cut_v1{raw_path.suffix}")
    conformed_path = raw_path.with_name(f"{base_stem}_voice_fit{raw_path.suffix}")
    emoji_path = raw_path.with_name(f"{base_stem}_emoji{raw_path.suffix}")
    final_path = raw_path.with_name(f"{base_stem}_final{raw_path.suffix}")
    return cut_path, conformed_path, emoji_path, final_path


def _planned_cut_ranges(cut_ranges: tuple[CutRange, ...]) -> tuple[PlannedCutRange, ...]:
    return tuple(
        PlannedCutRange(start_sec=item.start_sec, end_sec=item.end_sec)
        for item in cut_ranges
    )


def _finalize_raw_plan(
    source_plan: OutputRenderPlan,
    cut_ranges: tuple[CutRange, ...],
) -> tuple[Path, OutputRenderPlan]:
    raw_path = Path(source_plan.raw_video_path or source_plan.output_path)
    cut_path, conformed_path, emoji_path, final_path = _cut_output_paths(raw_path)
    cut_video_excluding_ranges(
        in_path=raw_path,
        out_path=cut_path,
        cut_ranges=cut_ranges,
    )
    conform_video_to_voice_duration(
        video_path=cut_path,
        voice_track=Path(source_plan.voice_track),
        out_path=conformed_path,
    )
    video_for_mux = apply_emoji_preset(
        video_path=conformed_path,
        out_path=emoji_path,
        preset=source_plan.emoji_preset,
        seed=source_plan.output_index,
    )
    mux_voice_after_video(
        video_path=video_for_mux,
        voice_track=Path(source_plan.voice_track),
        out_path=final_path,
    )
    updated_plan = replace(
        source_plan,
        output_path=str(final_path),
        cut_video_path=str(cut_path),
        final_video_path=str(final_path),
        cut_ranges=_planned_cut_ranges(cut_ranges),
    )
    return final_path, updated_plan


def run_cut_job(
    job_id: str,
    store: JobStore,
    source_plan: OutputRenderPlan,
    cut_ranges_text: str,
) -> None:
    """Cắt video thô theo range user chọn, rồi mới mux voice nguyên vẹn."""
    store.update(job_id, status="running", total_outputs=1, job_kind="full")
    store.append_log(job_id, "Bắt đầu cắt video thô và giữ nguyên voice")
    try:
        cut_ranges = parse_cut_ranges(cut_ranges_text)
        final_path, updated_plan = _finalize_raw_plan(source_plan, cut_ranges)
        store.append_log(job_id, f"Đã bỏ {len(cut_ranges)} đoạn khỏi video thô")
        store.append_log(job_id, "Đã canh độ dài video theo voice")
        if source_plan.emoji_preset != "none":
            store.append_log(job_id, f"Đã áp emoji preset: {source_plan.emoji_preset}")
        quality_result = analyze_video_file(final_path)
        quality_summary = summarize_quality((quality_result,))
        store.update(
            job_id,
            status="done",
            completed_outputs=1,
            output_paths=(str(final_path),),
            quality_results=(quality_result,),
            quality_summary=quality_summary,
            render_plans=(updated_plan,),
        )
        store.append_log(job_id, f"Hoàn tất final: {final_path.name}")
        store.append_log(job_id, quality_summary.title)
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="failed", error=f"{exc}\n{traceback.format_exc()}")
        store.append_log(job_id, f"Lỗi: {exc}")


def run_retry_job(job_id: str, store: JobStore, source_plan: OutputRenderPlan) -> None:
    """Render lại đúng output cũ bằng assignment/segments đã lưu."""
    store.update(job_id, status="running", total_outputs=1, job_kind="full")
    store.append_log(job_id, "Render lại đúng video lỗi bằng chế độ mượt hơn")
    try:
        retry_profile = resolve_profile("smooth_retry")
        assignment = _assignment_from_render_plan(source_plan)
        out_path = _retry_output_path(Path(source_plan.output_path))
        render_output(
            assignment=assignment,
            scene_durations=source_plan.scene_durations,
            voice_track=Path(source_plan.voice_track),
            out_path=out_path,
            tmp_dir=out_path.parent / ".tmp" / job_id,
            aspect_ratio=source_plan.aspect_ratio,
            fit_mode=source_plan.fit_mode,
            watermark_path=Path(source_plan.watermark_path) if source_plan.watermark_path else None,
            watermark_position=source_plan.watermark_position,
            watermark_scale=source_plan.watermark_scale,
            subtitle_path=Path(source_plan.subtitle_path) if source_plan.subtitle_path else None,
            edit_profile=retry_profile,
        )
        quality_result = analyze_video_file(out_path)
        retry_plan = replace(
            source_plan,
            output_index=0,
            output_path=str(out_path),
            profile_name=retry_profile.name,
        )
        quality_summary = summarize_quality((quality_result,))
        store.update(
            job_id,
            status="done",
            completed_outputs=1,
            output_paths=(str(out_path),),
            quality_results=(quality_result,),
            quality_summary=quality_summary,
            render_plans=(retry_plan,),
        )
        store.append_log(job_id, f"Hoàn tất render lại: {out_path.name}")
        store.append_log(job_id, quality_summary.title)
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="failed", error=f"{exc}\n{traceback.format_exc()}")
        store.append_log(job_id, f"Lỗi: {exc}")


def build_preview_sample(
    assignment: Assignment, scene_durations: tuple[float, ...]
) -> tuple[Assignment, tuple[float, ...]]:
    """Return a short preview assignment without mutating the full render plan."""
    available_count = min(len(assignment.groups), len(scene_durations))
    if available_count < 1:
        raise ValueError("Không có cảnh nào để tạo bản xem thử")
    keep_count = min(available_count, _PREVIEW_MAX_SCENES)
    if available_count <= keep_count:
        indices = tuple(range(available_count))
    else:
        indices = tuple(
            round(index * (available_count - 1) / (keep_count - 1))
            for index in range(keep_count)
        )
    preview_durations = tuple(
        min(duration, _PREVIEW_SCENE_DURATION)
        for index, duration in enumerate(scene_durations)
        if index in indices
    )
    preview_groups = tuple(assignment.groups[index] for index in indices)
    return replace(assignment, groups=preview_groups), preview_durations


def _source_coverage_messages(
    scenes: tuple[SceneFolder, ...], assignments: tuple[Assignment, ...]
) -> tuple[str, ...]:
    source_paths = {clip.path for scene in scenes for clip in scene.clips}
    used_paths = {
        clip.path
        for assignment in assignments
        for group in assignment.groups
        for clip in group.clips
    }
    missing = source_paths - used_paths
    if not missing:
        return ()
    return (f"Còn {len(missing)} clip nguồn chưa được dùng trong batch này.",)
