"""Hậu kỳ video-only: cắt bỏ đoạn xấu rồi mux voice sau cùng."""

from __future__ import annotations

import re
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ytb_pipeline.assembler.render_effects import X264_ENCODE_ARGS, ffprobe_duration, normalize_video_filter
from ytb_pipeline.ffmpeg_bin import ffmpeg_cmd


@dataclass(frozen=True)
class CutRange:
    """Một đoạn trên video raw sẽ bị bỏ trước khi gắn voice."""

    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


def _parse_timestamp(value: str) -> float:
    value = value.strip()
    if not value:
        raise ValueError("timestamp rỗng")
    parts = value.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) > 3:
        raise ValueError(f"timestamp không hợp lệ: {value!r}")
    seconds = 0.0
    multiplier = 1.0
    for part in reversed(parts):
        seconds += float(part) * multiplier
        multiplier *= 60.0
    return seconds


def _merge_ranges(ranges: list[CutRange]) -> tuple[CutRange, ...]:
    if not ranges:
        return ()
    ranges.sort(key=lambda item: item.start_sec)
    merged: list[CutRange] = [ranges[0]]
    for item in ranges[1:]:
        current = merged[-1]
        if item.start_sec <= current.end_sec + 0.001:
            merged[-1] = CutRange(current.start_sec, max(current.end_sec, item.end_sec))
            continue
        merged.append(item)
    return tuple(merged)


def _detect_ranges(
    path: Path,
    filter_name: str,
    start_pattern: str,
    end_pattern: str,
) -> tuple[CutRange, ...]:
    try:
        result = subprocess.run(
            [
                ffmpeg_cmd(),
                "-v",
                "info",
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
    except (OSError, subprocess.CalledProcessError):
        return ()

    starts = [float(match) for match in re.findall(start_pattern, result.stderr)]
    ends = [float(match) for match in re.findall(end_pattern, result.stderr)]
    ranges = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else start
        if end > start:
            ranges.append(CutRange(round(start, 3), round(end, 3)))
    return tuple(ranges)


def suggest_cut_ranges_for_video(path: Path) -> tuple[CutRange, ...]:
    """Gợi ý đoạn xấu trên raw output bằng black/freeze detection.

    Đây là detector hậu kỳ tối thiểu: chỉ tự cắt các đoạn có tín hiệu rõ ràng
    như black frame hoặc freeze dài, tránh tự ý cắt cảnh bình thường.
    """
    total_duration = ffprobe_duration(path)
    ranges = [
        *_detect_ranges(
            path,
            "blackdetect=d=0.6:pix_th=0.10",
            r"black_start:\s*([0-9.]+)",
            r"black_end:\s*([0-9.]+)",
        ),
        *_detect_ranges(
            path,
            "freezedetect=n=-60dB:d=1.0",
            r"freeze_start:\s*([0-9.]+)",
            r"freeze_end:\s*([0-9.]+)",
        ),
    ]
    clamped = [
        CutRange(
            start_sec=max(0.0, min(item.start_sec, total_duration)),
            end_sec=max(0.0, min(item.end_sec, total_duration)),
        )
        for item in ranges
        if item.duration_sec >= 0.5
    ]
    return _merge_ranges([item for item in clamped if item.end_sec > item.start_sec])


def parse_cut_ranges(text: str) -> tuple[CutRange, ...]:
    """Parse các dòng `start-end` thành range đã sort/merge.

    Hỗ trợ giây thập phân (`12.5-14`) và timestamp (`00:03-00:05.5`).
    """
    ranges: list[CutRange] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = re.split(r"\s*[-–]\s*", line, maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Dòng {line_no}: nhập dạng start-end, ví dụ 00:03-00:05")
        try:
            start = _parse_timestamp(parts[0])
            end = _parse_timestamp(parts[1])
        except ValueError as exc:
            raise ValueError(f"Dòng {line_no}: timestamp không hợp lệ") from exc
        if start < 0 or end <= start:
            raise ValueError(f"Dòng {line_no}: đoạn cắt phải có end lớn hơn start")
        ranges.append(CutRange(round(start, 3), round(end, 3)))
    return _merge_ranges(ranges)


def _keep_ranges(total_duration: float, cut_ranges: tuple[CutRange, ...]) -> tuple[CutRange, ...]:
    keep: list[CutRange] = []
    cursor = 0.0
    for cut in cut_ranges:
        start = min(max(cut.start_sec, 0.0), total_duration)
        end = min(max(cut.end_sec, 0.0), total_duration)
        if start > cursor:
            keep.append(CutRange(round(cursor, 3), round(start, 3)))
        cursor = max(cursor, end)
    if cursor < total_duration:
        keep.append(CutRange(round(cursor, 3), round(total_duration, 3)))
    return tuple(item for item in keep if item.duration_sec > 0.05)


def cut_video_excluding_ranges(
    in_path: Path,
    out_path: Path,
    cut_ranges: tuple[CutRange, ...],
) -> Path:
    """Xuất video-only mới sau khi bỏ các đoạn đã chọn."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cut_ranges:
        cmd = [
            ffmpeg_cmd(),
            "-y",
            "-i",
            str(in_path),
            "-an",
            "-vf",
            normalize_video_filter(),
            *X264_ENCODE_ARGS,
            str(out_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return out_path

    total_duration = ffprobe_duration(in_path)
    keep = _keep_ranges(total_duration, cut_ranges)
    if not keep:
        raise ValueError("Không thể cắt bỏ toàn bộ video")

    parts: list[str] = []
    labels: list[str] = []
    for index, item in enumerate(keep):
        label = f"[v{index}]"
        parts.append(
            f"[0:v:0]trim=start={item.start_sec}:end={item.end_sec},"
            f"setpts=PTS-STARTPTS,{normalize_video_filter()}{label}"
        )
        labels.append(label)
    if len(labels) == 1:
        parts.append(f"{labels[0]}null[v]")
    else:
        parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[v]")

    cmd = [
        ffmpeg_cmd(),
        "-y",
        "-i",
        str(in_path),
        "-filter_complex",
        ";".join(parts),
        "-map",
        "[v]",
        "-an",
        *X264_ENCODE_ARGS,
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


def conform_video_to_voice_duration(video_path: Path, voice_track: Path, out_path: Path) -> Path:
    """Loop video nếu ngắn hơn voice, nhưng không trim mất footage đã giữ."""
    voice_duration = ffprobe_duration(voice_track)
    video_duration = ffprobe_duration(video_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_cmd(), "-y"]
    if video_duration + 0.05 < voice_duration:
        cmd.extend(["-stream_loop", "-1"])
    cmd.extend(["-i", str(video_path)])
    if video_duration + 0.05 < voice_duration:
        cmd.extend(["-t", str(round(voice_duration, 3))])
    cmd.extend(
        [
            "-vf",
            normalize_video_filter(),
            "-an",
            *X264_ENCODE_ARGS,
            str(out_path),
        ]
    )
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


def mux_voice_after_video(video_path: Path, voice_track: Path, out_path: Path) -> Path:
    """Gắn voice sau cùng, pad audio để không cắt mất video đã review."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_cmd(),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(voice_track),
        "-filter_complex",
        "[1:a:0]apad[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


_STICKER_PRESETS: dict[str, tuple[str, ...]] = {
    "light": ("white@0.62", "0x21c55d@0.55"),
    "sales": ("0xff3b30@0.60", "0x21c55d@0.55", "0xfacc15@0.62"),
    "bold": ("0xff3b30@0.68", "0xfacc15@0.68", "0x21c55d@0.58", "white@0.62"),
}


def apply_emoji_preset(video_path: Path, out_path: Path, preset: str, seed: int = 0) -> Path:
    """Overlay sticker accents trước khi mux voice.

    Dùng `drawbox` thay vì `drawtext` để chạy được với các ffmpeg build không
    có font/text filters. Preset đặt ở vùng rìa để giảm rủi ro che sản phẩm.
    """
    colors = _STICKER_PRESETS.get(preset)
    if not colors:
        return video_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(f"{preset}:{seed}")
    positions = [
        ("iw*0.78", "ih*0.10", "iw*0.12", "ih*0.055"),
        ("iw*0.08", "ih*0.72", "iw*0.14", "ih*0.050"),
        ("iw*0.74", "ih*0.72", "iw*0.16", "ih*0.050"),
        ("iw*0.10", "ih*0.12", "iw*0.12", "ih*0.055"),
    ]
    shuffled_colors = list(colors)
    rng.shuffle(shuffled_colors)
    rng.shuffle(positions)
    count = min(len(shuffled_colors), 2 + rng.randrange(0, min(2, len(shuffled_colors)) + 1))
    filters: list[str] = [normalize_video_filter()]
    for index, color in enumerate(shuffled_colors[:count]):
        x, y, width, height = positions[index % len(positions)]
        start = 0.45 + index * 1.2 + rng.random() * 0.5
        end = start + 1.2 + rng.random() * 0.8
        filters.append(
            f"drawbox=x={x}:y={y}:w={width}:h={height}:"
            f"color={color}:t=fill:enable='between(t,{start:.2f},{end:.2f})'"
        )

    cmd = [
        ffmpeg_cmd(),
        "-y",
        "-i",
        str(video_path),
        "-vf",
        ",".join(filters),
        "-an",
        *X264_ENCODE_ARGS,
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path
