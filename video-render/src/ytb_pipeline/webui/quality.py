"""User-facing quality checks for rendered videos.

The UI should speak in simple publishing terms, while this module keeps the
ffprobe/ffmpeg details available for debugging.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal

from ytb_pipeline.ffmpeg_bin import ffmpeg_cmd, ffprobe_cmd

QualityStatus = Literal["ready", "review", "rerender"]
IssueSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class VideoQualityIssue:
    severity: IssueSeverity
    message: str
    technical_detail: str


@dataclass(frozen=True)
class VideoQualityResult:
    path: str
    status: QualityStatus
    title: str
    summary: str
    issues: tuple[VideoQualityIssue, ...] = ()
    technical_details: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchQualitySummary:
    status: QualityStatus
    title: str
    summary: str
    action_label: str
    messages: tuple[str, ...] = ()


def _format_time(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _parse_rate(rate: str | None) -> float | None:
    if not rate or rate == "0/0":
        return None
    try:
        return float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return None


def _probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            ffprobe_cmd(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,avg_frame_rate,r_frame_rate,pix_fmt,nb_frames,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _run_video_filter(path: Path, filter_name: str) -> str:
    result = subprocess.run(
        [
            ffmpeg_cmd(),
            "-v",
            "warning",
            "-i",
            str(path),
            "-vf",
            filter_name,
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stderr


def _freeze_issues(path: Path) -> tuple[VideoQualityIssue, ...]:
    stderr = _run_video_filter(path, "freezedetect=n=-60dB:d=1.0")
    starts = [float(match) for match in re.findall(r"freeze_start:\s*([0-9.]+)", stderr)]
    ends = [float(match) for match in re.findall(r"freeze_end:\s*([0-9.]+)", stderr)]
    durations = [float(match) for match in re.findall(r"freeze_duration:\s*([0-9.]+)", stderr)]
    issues: list[VideoQualityIssue] = []
    for idx, start in enumerate(starts):
        duration = durations[idx] if idx < len(durations) else 0.0
        end = ends[idx] if idx < len(ends) else start + duration
        issues.append(
            VideoQualityIssue(
                severity="error",
                message=(
                    f"Có đoạn đứng hình ở {_format_time(start)} - {_format_time(end)}. "
                    "Nên render lại bằng chế độ mượt hơn."
                ),
                technical_detail=f"freezedetect start={start:.2f}s end={end:.2f}s",
            )
        )
    return tuple(issues)


def _black_frame_issues(path: Path) -> tuple[VideoQualityIssue, ...]:
    stderr = _run_video_filter(path, "blackdetect=d=0.5:pix_th=0.10")
    starts = [float(match) for match in re.findall(r"black_start:\s*([0-9.]+)", stderr)]
    ends = [float(match) for match in re.findall(r"black_end:\s*([0-9.]+)", stderr)]
    issues: list[VideoQualityIssue] = []
    for idx, start in enumerate(starts):
        end = ends[idx] if idx < len(ends) else start
        issues.append(
            VideoQualityIssue(
                severity="warning",
                message=(
                    f"Có đoạn tối/đen ở {_format_time(start)} - {_format_time(end)}. "
                    "Nên mở video xem lại đoạn này."
                ),
                technical_detail=f"blackdetect start={start:.2f}s end={end:.2f}s",
            )
        )
    return tuple(issues)


def _probe_issues(probe: dict) -> tuple[VideoQualityIssue, ...]:
    streams = probe.get("streams") or [{}]
    stream = next(
        (item for item in streams if item.get("codec_type") == "video"),
        streams[0],
    )
    issues: list[VideoQualityIssue] = []
    fps = _parse_rate(stream.get("avg_frame_rate"))
    pix_fmt = stream.get("pix_fmt")
    duration = float(stream.get("duration") or probe.get("format", {}).get("duration") or 0)
    nb_frames_raw = stream.get("nb_frames")

    if fps is None or abs(fps - 30.0) > 0.2:
        issues.append(
            VideoQualityIssue(
                severity="warning",
                message="Video có thể bị giật do tốc độ khung hình chưa ổn định.",
                technical_detail=f"avg_frame_rate={stream.get('avg_frame_rate')}",
            )
        )

    if pix_fmt != "yuv420p":
        issues.append(
            VideoQualityIssue(
                severity="warning",
                message="Video dùng định dạng màu kém tương thích, nên render lại trước khi đăng.",
                technical_detail=f"pix_fmt={pix_fmt}",
            )
        )

    if nb_frames_raw and duration > 0 and fps:
        frame_delta = abs(int(nb_frames_raw) - round(duration * fps))
        if frame_delta > 3:
            issues.append(
                VideoQualityIssue(
                    severity="warning",
                    message="Số khung hình không khớp thời lượng, video có thể không mượt.",
                    technical_detail=(
                        f"nb_frames={nb_frames_raw} duration={duration:.2f}s fps={fps:.2f}"
                    ),
                )
            )

    return tuple(issues)


def _audio_video_duration_issues(probe: dict) -> tuple[VideoQualityIssue, ...]:
    streams = probe.get("streams") or []
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video_stream is None or audio_stream is None:
        return ()
    try:
        video_duration = float(video_stream.get("duration") or 0)
        audio_duration = float(audio_stream.get("duration") or 0)
    except (TypeError, ValueError):
        return ()
    if video_duration <= 0 or audio_duration <= 0:
        return ()
    delta = abs(video_duration - audio_duration)
    if delta <= 0.5:
        return ()
    return (
        VideoQualityIssue(
            severity="warning",
            message="Độ dài tiếng và hình lệch nhau, nên mở video xem lại trước khi đăng.",
            technical_detail=(
                f"video_duration={video_duration:.2f}s audio_duration={audio_duration:.2f}s"
            ),
        ),
    )


def analyze_video_file(path: Path) -> VideoQualityResult:
    try:
        probe = _probe_video(path)
        issues = (
            *_probe_issues(probe),
            *_audio_video_duration_issues(probe),
            *_freeze_issues(path),
            *_black_frame_issues(path),
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        issue = VideoQualityIssue(
            severity="error",
            message="Không kiểm tra được video này. Nên render lại hoặc xem log kỹ thuật.",
            technical_detail=str(exc),
        )
        return VideoQualityResult(
            path=str(path),
            status="rerender",
            title="Nên render lại",
            summary="App không xác nhận được chất lượng video.",
            issues=(issue,),
            technical_details=(str(exc),),
        )

    if any(issue.severity == "error" for issue in issues):
        return VideoQualityResult(
            path=str(path),
            status="rerender",
            title="Nên render lại",
            summary="Video có đoạn dễ bị đứng hình hoặc không ổn.",
            issues=issues,
            technical_details=tuple(issue.technical_detail for issue in issues),
        )
    if issues:
        return VideoQualityResult(
            path=str(path),
            status="review",
            title="Cần xem lại",
            summary="Video render xong nhưng có điểm nên kiểm tra trước khi đăng.",
            issues=issues,
            technical_details=tuple(issue.technical_detail for issue in issues),
        )
    return VideoQualityResult(
        path=str(path),
        status="ready",
        title="Sẵn sàng đăng",
        summary="Video ổn, có thể dùng.",
        issues=(),
        technical_details=(),
    )


def summarize_quality(
    results: tuple[VideoQualityResult, ...],
    batch_messages: tuple[str, ...] = (),
) -> BatchQualitySummary:
    if any(result.status == "rerender" for result in results):
        return BatchQualitySummary(
            status="rerender",
            title="Nên render lại",
            summary="Có video cần render lại để tránh giật, đứng hình hoặc lỗi hiển thị.",
            action_label="Render lại video lỗi",
            messages=batch_messages,
        )
    if batch_messages or any(result.status == "review" for result in results):
        return BatchQualitySummary(
            status="review",
            title="Cần xem lại",
            summary="Video đã render xong, nhưng có vài điểm nên kiểm tra trước khi đăng.",
            action_label="Mở video để xem lại",
            messages=batch_messages,
        )
    return BatchQualitySummary(
        status="ready",
        title="Sẵn sàng đăng",
        summary="Tất cả video đã qua kiểm tra tự động.",
        action_label="Mở thư mục kết quả",
        messages=(),
    )
