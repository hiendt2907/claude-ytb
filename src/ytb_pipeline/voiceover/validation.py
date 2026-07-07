"""Audio QA gate before render."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ..pkg.models import Voiceover

_STAGE_DIRECTION_PATTERNS = (
    r"\bCú hình tiếp theo\s*:",
    r"\bBeat sau\s*:",
    r"\bChốt cảnh\s*:",
    r"\[[^\]]+\]",
)


def validate_audio(
    voiceover: Voiceover,
    *,
    max_duration_drift_sec: float = 2.0,
    max_silence_ratio: float = 0.65,
) -> None:
    """Fail fast when synthesized audio is not usable for render."""
    if voiceover.audio_path is None or not Path(voiceover.audio_path).exists():
        raise FileNotFoundError(f"Không tìm thấy audio voiceover: {voiceover.audio_path}")
    for index, segment in enumerate(voiceover.segments, start=1):
        if segment.audio_path is None or not Path(segment.audio_path).exists():
            raise FileNotFoundError(f"Không tìm thấy audio section {index}: {segment.audio_path}")
        if segment.duration_sec <= 0:
            raise ValueError(f"Audio section {index} duration không hợp lệ: {segment.duration_sec}")
        for pattern in _STAGE_DIRECTION_PATTERNS:
            if re.search(pattern, segment.narration, flags=re.IGNORECASE):
                raise ValueError(
                    f"Audio QA chặn section {index}: voiceover còn stage direction ({pattern})."
                )

    actual_duration = _duration(Path(voiceover.audio_path))
    expected_duration = sum(segment.duration_sec for segment in voiceover.segments)
    if actual_duration <= 0:
        raise ValueError(f"Audio duration không hợp lệ: {voiceover.audio_path}")
    if abs(actual_duration - expected_duration) > max_duration_drift_sec:
        raise ValueError(
            f"Audio tổng lệch section {abs(actual_duration - expected_duration):.2f}s "
            f"> {max_duration_drift_sec:.2f}s."
        )

    mean_volume, silence_ratio = _volume_and_silence(Path(voiceover.audio_path))
    if mean_volume is not None and mean_volume < -35.0:
        raise ValueError(f"Audio volume quá nhỏ: mean_volume={mean_volume:.1f} dB")
    if silence_ratio is not None and silence_ratio > max_silence_ratio:
        raise ValueError(f"Audio có quá nhiều silence: {silence_ratio:.0%}")


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(out.stdout).get("format", {}).get("duration") or 0)


def _volume_and_silence(path: Path) -> tuple[float | None, float | None]:
    duration = _duration(path)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-af",
        "volumedetect,silencedetect=noise=-38dB:d=0.5",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stderr
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", text)
    mean_volume = float(m.group(1)) if m else None
    silence = sum(float(x) for x in re.findall(r"silence_duration:\s*(\d+(?:\.\d+)?)", text))
    silence_ratio = (silence / duration) if duration > 0 else None
    return mean_volume, silence_ratio
