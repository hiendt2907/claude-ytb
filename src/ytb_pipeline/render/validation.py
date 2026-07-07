"""Render output validation before publish."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from ..config.settings import settings
from ..pkg.models import RenderedVideo


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def validate_render(
    video: RenderedVideo,
    *,
    expected_dims: tuple[int, int],
    expected_duration_sec: float,
) -> None:
    """Fail fast when a rendered file is not publishable."""
    if video.video_path is None or not Path(video.video_path).exists():
        raise FileNotFoundError(f"Không tìm thấy video render: {video.video_path}")
    if expected_duration_sec <= 0:
        raise ValueError("Voiceover duration must be > 0 before render validation")

    data = _ffprobe(Path(video.video_path))
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video_stream is None:
        raise ValueError(f"Render thiếu video stream: {video.video_path}")
    if audio_stream is None:
        raise ValueError(f"Render thiếu audio stream: {video.video_path}")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if (width, height) != expected_dims:
        raise ValueError(f"Sai resolution: {(width, height)} != {expected_dims}")

    duration = float(data.get("format", {}).get("duration") or 0)
    drift = abs(duration - expected_duration_sec)
    if drift > settings.render_validation_max_drift_sec:
        raise ValueError(
            f"Render lệch timeline {drift:.2f}s > {settings.render_validation_max_drift_sec:.2f}s "
            f"(video={duration:.2f}s, audio={expected_duration_sec:.2f}s)"
        )


def validate_final_video(video: RenderedVideo) -> None:
    """Codex final QA gate before upload."""
    if video.video_path is None:
        raise FileNotFoundError("Final QA: video_path trống.")
    path = Path(video.video_path)
    if not path.exists():
        raise FileNotFoundError(f"Final QA: không tìm thấy video: {path}")
    data = _ffprobe(path)
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video_stream is None or audio_stream is None:
        raise ValueError("Final QA: thiếu audio hoặc video stream.")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    declared_type = getattr(video, "video_type", "short")
    if declared_type == "short" and height <= width:
        raise ValueError(f"Final QA: Short phải là video dọc, hiện tại {width}x{height}.")
    if declared_type == "long" and width <= height:
        raise ValueError(f"Final QA: Long phải là video ngang, hiện tại {width}x{height}.")

    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("Final QA: duration không hợp lệ.")
    if declared_type == "short" and duration > 180:
        raise ValueError(f"Final QA: Short dài quá 180s: {duration:.1f}s.")
    if not video.description or len(video.tags) < 3:
        raise ValueError("Final QA: metadata thiếu description hoặc tags (<3).")
    _check_not_blank(path)


def _check_not_blank(path: Path) -> None:
    """Sample frames and reject fully black/blank-looking renders."""
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", str(path),
             "-frames:v", "1", str(frame)],
            check=True,
        )
        from PIL import Image

        img = Image.open(frame).convert("L")
        extrema = img.getextrema()
        if extrema[1] < 12:
            raise ValueError("Final QA: frame mẫu gần như đen/blank.")
