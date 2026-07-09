"""FFmpeg filter helpers cho render pipeline."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytb_pipeline.ffmpeg_bin import ffprobe_cmd

ASPECT_RATIO_SIZES: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}
OUTPUT_FPS = 30
X264_ENCODE_ARGS = [
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "18",
    "-pix_fmt",
    "yuv420p",
    "-r",
    str(OUTPUT_FPS),
    "-movflags",
    "+faststart",
]


def resolve_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    try:
        return ASPECT_RATIO_SIZES[aspect_ratio]
    except KeyError as exc:
        raise ValueError(
            f"aspect_ratio không hợp lệ: {aspect_ratio!r} (dùng {list(ASPECT_RATIO_SIZES)})"
        ) from exc


def scale_filter(width: int, height: int, fit_mode: str) -> str:
    if fit_mode == "pad":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
    if fit_mode == "crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1"
        )
    raise ValueError(f"fit_mode không hợp lệ: {fit_mode!r} (dùng pad | crop)")


def ken_burns_filter(
    width: int,
    height: int,
    motion_scale: float,
    pan_strength_x: float,
    pan_strength_y: float,
    pan_speed_x: float,
    pan_speed_y: float,
) -> str:
    scaled_w = round(width * motion_scale)
    scaled_h = round(height * motion_scale)
    x = f"(iw-ow)/2+sin(t*{pan_speed_x})*(iw-ow)*{pan_strength_x}"
    y = f"(ih-oh)/2+cos(t*{pan_speed_y})*(ih-oh)*{pan_strength_y}"
    return f"scale={scaled_w}:{scaled_h},crop={width}:{height}:x='{x}':y='{y}'"


def normalize_video_filter() -> str:
    # `fps=` tự nó đã ép CFR đúng OUTPUT_FPS (duplicate/drop frame để khớp).
    # Trước đây có thêm `setpts=N/(FPS*TB)` để "chắc chắn" CFR, nhưng filter
    # này dư thừa và trên ffmpeg 7.0 (bundle qua static-ffmpeg cho bản đóng
    # gói macOS) gây lỗi "constant frame rate 1/0 invalid" khi ghép vào
    # xfade — ffmpeg 8.x không lỗi nên không phát hiện được lúc dev bằng
    # Homebrew ffmpeg. Bỏ setpts, giữ đúng fps=OUTPUT_FPS/1 (verify bằng
    # ffprobe r_frame_rate/avg_frame_rate).
    return f"fps={OUTPUT_FPS},format=yuv420p,setsar=1"


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            ffprobe_cmd(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def fade_out_filter(duration: float, fade_duration: float) -> str:
    start = max(0.0, duration - fade_duration)
    return f"fade=t=out:st={start}:d={fade_duration}"


def effective_xfade_duration(
    prev_duration: float, next_duration: float, desired_duration: float
) -> float:
    return min(desired_duration, prev_duration * 0.4, next_duration * 0.4)
