"""Render output validation before publish."""

from __future__ import annotations

import json
import subprocess
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
