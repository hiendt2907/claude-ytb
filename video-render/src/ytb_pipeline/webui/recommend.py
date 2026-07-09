"""Lightweight, explainable edit-profile suggestions for the web UI.

Vẫn không dùng model AI/nhận diện vật thể — chỉ thêm một tín hiệu đo được
trực tiếp từ khung hình (độ chuyển động qua ffmpeg signalstats) để gợi ý
không còn phụ thuộc hoàn toàn vào việc người dùng đặt tên thư mục đúng
chuẩn tiếng Anh (fashion/food/...).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ytb_pipeline.assembler.models import SceneFolder
from ytb_pipeline.ffmpeg_bin import ffmpeg_cmd

# Lấy mẫu 5s đầu mỗi clip đại diện, downscale nhỏ + 2fps để phân tích nhanh
# (~1-1.5s/clip trên máy dev). Chỉ phân tích 1 clip/cảnh và tối đa
# _MAX_SCENES_ANALYZED cảnh để "Kiểm tra video nguồn" không bị treo lâu với
# project nhiều cảnh.
_MOTION_SAMPLE_DURATION_SEC = 5.0
_MOTION_SAMPLE_FPS = 2
_MOTION_ANALYSIS_TIMEOUT_SEC = 8.0
_MAX_SCENES_ANALYZED = 8
_YDIF_PATTERN = re.compile(r"lavfi\.signalstats\.YDIF=([0-9.]+)")

# Ngưỡng heuristic ban đầu, hiệu chỉnh thô trên vài clip demo thật (YDIF đo
# trên khung 160x90). Không phải giá trị tuyệt đối chuẩn hoá khoa học — nên
# tinh chỉnh lại khi có nhiều thể loại nội dung thật hơn để đối chiếu.
_LOW_MOTION_YDIF = 10.0
_HIGH_MOTION_YDIF = 22.0


@dataclass(frozen=True)
class ProfileSuggestion:
    profile_name: str
    label: str
    reason: str


def _estimate_motion_score(clip_path: Path) -> float | None:
    """Ước lượng độ chuyển động trung bình của clip (khung càng đổi nhiều so
    với khung trước thì YDIF càng cao). Trả None nếu ffmpeg lỗi/timeout thay
    vì raise, vì đây chỉ là tín hiệu gợi ý — không được làm hỏng luồng scan."""
    filter_graph = (
        f"trim=duration={_MOTION_SAMPLE_DURATION_SEC},"
        f"signalstats,scale=160:90,fps={_MOTION_SAMPLE_FPS},metadata=print"
    )
    try:
        result = subprocess.run(
            [
                ffmpeg_cmd(),
                "-v",
                "info",
                "-i",
                str(clip_path),
                "-vf",
                filter_graph,
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=_MOTION_ANALYSIS_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    values = [float(match) for match in _YDIF_PATTERN.findall(result.stderr)]
    return sum(values) / len(values) if values else None


def _estimate_project_motion(
    scenes: tuple[SceneFolder, ...],
    progress_callback: Callable[[int, int, Path], None] | None = None,
) -> float | None:
    """Trung bình motion score của 1 clip đại diện (clip đầu) mỗi cảnh, tối
    đa _MAX_SCENES_ANALYZED cảnh. None nếu không phân tích được cảnh nào."""
    sampled_scenes = [scene for scene in scenes if scene.clips][:_MAX_SCENES_ANALYZED]
    scores: list[float] = []
    total = len(sampled_scenes)
    for index, scene in enumerate(sampled_scenes, start=1):
        clip_path = scene.clips[0].path
        score = _estimate_motion_score(clip_path)
        if score is not None:
            scores.append(score)
        if progress_callback is not None:
            progress_callback(index, total, clip_path)
    return sum(scores) / len(scores) if scores else None


def recommend_profile(
    scenes: tuple[SceneFolder, ...],
    *,
    aspect_ratio: str,
    mode: str,
    progress_callback: Callable[[int, int, Path], None] | None = None,
) -> ProfileSuggestion:
    """Return an opt-in profile suggestion based on visible project shape."""
    scene_count = len(scenes)
    clip_counts = [len(scene.clips) for scene in scenes]
    total_clips = sum(clip_counts)
    avg_clips = total_clips / max(1, scene_count)

    if mode == "manual":
        return ProfileSuggestion(
            profile_name="affiliate_default",
            label="Giữ kiểu đang chọn",
            reason="Bạn đang dùng Tự chọn clip, nên app không tự đổi mạnh kiểu dựng.",
        )

    folder_text = " ".join(scene.path.name.lower() for scene in scenes)
    if any(keyword in folder_text for keyword in ("fashion", "try", "tryon", "outfit")):
        return ProfileSuggestion(
            profile_name="fashion_tryon",
            label="Fashion try-on",
            reason="Tên thư mục giống nội dung thử đồ/thời trang.",
        )

    if any(keyword in folder_text for keyword in ("food", "cook", "demo", "eat")):
        return ProfileSuggestion(
            profile_name="food_demo",
            label="Food demo",
            reason="Tên thư mục giống nội dung đồ ăn hoặc demo thao tác.",
        )

    motion_score = (
        _estimate_project_motion(scenes, progress_callback=progress_callback)
        if scene_count
        else None
    )
    if motion_score is not None:
        if motion_score >= _HIGH_MOTION_YDIF:
            return ProfileSuggestion(
                profile_name="tiktok_shop_fast",
                label="Bán hàng nhanh",
                reason=(
                    f"Clip nguồn chuyển động khá nhiều (điểm chuyển động ~"
                    f"{motion_score:.0f}, đo trên khung hình thật), hợp nhịp bán hàng nhanh."
                ),
            )
        if motion_score <= _LOW_MOTION_YDIF:
            return ProfileSuggestion(
                profile_name="product_review_smooth",
                label="Review mượt",
                reason=(
                    f"Clip nguồn khá tĩnh (điểm chuyển động ~{motion_score:.0f}, "
                    f"đo trên khung hình thật), nên giữ nhịp chậm để xem rõ sản phẩm."
                ),
            )

    if aspect_ratio == "9:16" and (scene_count >= 4 or avg_clips >= 2.5):
        return ProfileSuggestion(
            profile_name="tiktok_shop_fast",
            label="Bán hàng nhanh",
            reason="Video dọc có nhiều cảnh hoặc nhiều clip, hợp nhịp bán hàng nhanh.",
        )

    if scene_count <= 3 and avg_clips <= 2:
        return ProfileSuggestion(
            profile_name="product_review_smooth",
            label="Review mượt",
            reason="Ít cảnh và ít clip, nên giữ nhịp xem rõ sản phẩm.",
        )

    return ProfileSuggestion(
        profile_name="affiliate_default",
        label="Affiliate mặc định",
        reason="Cấu trúc nguồn cân bằng, dùng kiểu mặc định là an toàn.",
    )
