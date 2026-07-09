"""Ước tính thời gian render trước khi chạy thật — dùng lại đúng thuật toán
assignment + duration strategy (chỉ đọc metadata qua ffprobe, không encode)
để tránh sai lệch giữa số ước tính và số thật.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ytb_pipeline.assembler.assignment import find_duplicate_assignments
from ytb_pipeline.assembler.models import SceneFolder
from ytb_pipeline.webui.jobs import (
    RenderRequest,
    build_assignments_for_request,
    build_duration_strategy,
)

# Hệ số kinh nghiệm: ffmpeg re-encode (concat + loop/trim + mux) chạy chậm hơn
# thời lượng thực của video khoảng 1.5 lần trên phần cứng phổ thông (libx264 preset mặc định).
_ENCODE_FACTOR = 1.5
# Overhead cố định (giây) cho mỗi lệnh ffmpeg con (khởi động process, mở file...).
_FFMPEG_CALL_OVERHEAD_SEC = 2.0


@dataclass(frozen=True)
class ProductEstimate:
    product_name: str
    voice_track: str
    n_outputs: int
    estimated_seconds: float
    duplicate_output_groups: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True)
class EstimateResult:
    items: tuple[ProductEstimate, ...]
    grand_total_estimated_seconds: float


def _estimate_one_output_seconds(scenes: tuple[SceneFolder, ...], scene_durations: tuple[float, ...]) -> float:
    encode_seconds = sum(scene_durations) * _ENCODE_FACTOR
    # mỗi cảnh: 1 lệnh concat clip + 1 lệnh loop/trim; cộng thêm 1 lệnh concat+mux cuối.
    ffmpeg_calls = 2 * len(scenes) + 1
    return encode_seconds + ffmpeg_calls * _FFMPEG_CALL_OVERHEAD_SEC


def estimate_product(
    scenes: tuple[SceneFolder, ...],
    voice_track: Path,
    product_name: str,
    n_outputs: int,
    duration_mode: str,
    seed: int | None,
    mode: str = "random",
    manual_plan_text: str = "",
) -> ProductEstimate:
    """Ước tính thời gian render cho 1 sản phẩm (1 voice track, N output).

    Dùng đúng `build_assignments_for_request` mà job thật sẽ chạy (random hoặc
    manual) để số ước tính không lệch khỏi số thật.
    """
    request = RenderRequest(
        scenes_dir=Path("."),
        voice_track=voice_track,
        product_name=product_name,
        n_outputs=n_outputs,
        output_dir=Path("."),
        tmp_dir=Path("."),
        duration_mode=duration_mode,
        seed=seed,
        mode=mode,
        manual_plan_text=manual_plan_text,
    )
    assignments = build_assignments_for_request(scenes, request)
    strategy = build_duration_strategy(duration_mode)

    total_seconds = 0.0
    for assignment in assignments:
        durations = strategy.scene_durations(assignment.groups, voice_track)
        total_seconds += _estimate_one_output_seconds(scenes, durations)

    return ProductEstimate(
        product_name=product_name,
        voice_track=str(voice_track),
        n_outputs=len(assignments),
        estimated_seconds=total_seconds,
        duplicate_output_groups=find_duplicate_assignments(assignments),
    )


def estimate_all(
    scenes: tuple[SceneFolder, ...],
    voice_tracks: list[Path],
    base_product_name: str,
    n_outputs: int,
    duration_mode: str,
    seed: int | None,
    mode: str = "random",
    manual_plan_text: str = "",
) -> EstimateResult:
    """Ước tính cho toàn bộ voice track đã chọn (mỗi voice = 1 sản phẩm/job)."""
    items = []
    for voice_track in voice_tracks:
        product_name = (
            f"{base_product_name}_{voice_track.stem}"
            if len(voice_tracks) > 1
            else base_product_name
        )
        items.append(
            estimate_product(
                scenes,
                voice_track,
                product_name,
                n_outputs,
                duration_mode,
                seed,
                mode=mode,
                manual_plan_text=manual_plan_text,
            )
        )
    grand_total = sum(item.estimated_seconds for item in items)
    return EstimateResult(items=tuple(items), grand_total_estimated_seconds=grand_total)
