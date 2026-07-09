"""Chiến lược xác định thời lượng mỗi cảnh — user chọn 1 trong 2:

- ClipLengthDurationStrategy: thời lượng cảnh = độ dài tự nhiên của clip group đã chọn.
- VoiceSilenceDurationStrategy: suy ra thời lượng từng cảnh từ khoảng lặng trong voice track.

Cả hai đều gọi ffmpeg/ffprobe qua subprocess — không unit test được, xem
`tests/test_duration.py` (@pytest.mark.integration).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol

from ytb_pipeline.assembler.models import ClipGroup
from ytb_pipeline.ffmpeg_bin import ffmpeg_cmd, ffprobe_cmd

_SILENCE_START = re.compile(r"silence_start:\s*(?P<ts>[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(?P<ts>[\d.]+)")


class DurationStrategy(Protocol):
    def scene_durations(
        self, groups: tuple[ClipGroup, ...], voice_track: Path
    ) -> tuple[float, ...]:
        """Trả về thời lượng (giây) cho từng cảnh, theo đúng thứ tự groups."""
        ...


def _ffprobe_duration(path: Path) -> float:
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


class ClipLengthDurationStrategy:
    """Thời lượng cảnh = tổng độ dài các clip đã chọn cho cảnh đó (nối liên tiếp)."""

    def scene_durations(
        self, groups: tuple[ClipGroup, ...], voice_track: Path
    ) -> tuple[float, ...]:
        return tuple(
            sum(_ffprobe_duration(clip.path) for clip in group.clips) if group.clips else 0.0
            for group in groups
        )


class VoiceSilenceDurationStrategy:
    """Thời lượng cảnh suy ra từ khoảng lặng trong voice track (1 cảnh = 1 đoạn thoại).

    Yêu cầu số đoạn thoại tách ra (giữa 2 khoảng lặng) khớp số cảnh — nếu lệch,
    raise ValueError để user chỉnh lại silence threshold/duration thay vì render sai.
    """

    def __init__(self, noise_db: float = -30.0, min_silence_sec: float = 0.3) -> None:
        self._noise_db = noise_db
        self._min_silence_sec = min_silence_sec

    def _detect_silences(self, voice_track: Path) -> list[tuple[float, float]]:
        cmd = [
            ffmpeg_cmd(),
            "-i",
            str(voice_track),
            "-af",
            f"silencedetect=noise={self._noise_db}dB:d={self._min_silence_sec}",
            "-f",
            "null",
            "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        starts = [float(m.group("ts")) for m in _SILENCE_START.finditer(result.stderr)]
        ends = [float(m.group("ts")) for m in _SILENCE_END.finditer(result.stderr)]
        return list(zip(starts, ends, strict=False))

    def scene_durations(
        self, groups: tuple[ClipGroup, ...], voice_track: Path
    ) -> tuple[float, ...]:
        total_duration = _ffprobe_duration(voice_track)
        silences = self._detect_silences(voice_track)

        boundaries = [0.0]
        for start, end in silences:
            midpoint = (start + end) / 2
            boundaries.append(midpoint)
        boundaries.append(total_duration)

        segments = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]
        if len(segments) != len(groups):
            raise ValueError(
                f"Số đoạn thoại tách được từ voice track ({len(segments)}) không khớp "
                f"số cảnh ({len(groups)}). Chỉnh noise_db/min_silence_sec hoặc dùng "
                "ClipLengthDurationStrategy."
            )
        return tuple(segments)
