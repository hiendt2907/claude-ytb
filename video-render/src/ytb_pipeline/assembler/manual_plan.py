"""Chế độ nhập tay: user tự chỉ định clip nào thuộc cảnh nào cho từng output,
thay vì để thuật toán random chọn (xem `assignment.py`).

Định dạng text, mỗi dòng 1 output:
    video 1: 1.1,1.2, 2.3,2.4, 3.1,3.2
    video 2: 1.3, 2.1,2.2, 3.3

Hoặc viết nhanh, mỗi dòng vẫn là 1 output:
    1.1,1.2, 2.3,2.4, 3.1,3.2
    1.3, 2.1,2.2, 3.3

Mỗi token (VD "1.1") tham chiếu 1 clip qua đúng số trong tên file (giống
`sub_index` dùng để sort trong `scanning.py`). Các token liên tiếp cùng cảnh
gộp thành 1 nhóm; nhóm đổi khi cảnh đổi. Thứ tự clip trong 1 nhóm vẫn phải
tăng dần theo sub_index — không cho phép đảo thứ tự tay, giữ đúng bất biến
"thứ tự nối trong nhóm theo tên file" của toàn bộ hệ thống.
"""

from __future__ import annotations

from ytb_pipeline.assembler.models import Assignment, Clip, ClipGroup, SceneFolder
from ytb_pipeline.assembler.scanning import parse_sub_index


def _build_clip_lookup(scenes: tuple[SceneFolder, ...]) -> dict[tuple[int, ...], tuple[int, Clip]]:
    lookup: dict[tuple[int, ...], tuple[int, Clip]] = {}
    for scene in scenes:
        for clip in scene.clips:
            if clip.sub_index in lookup:
                raise ValueError(
                    f"Trùng sub_index {clip.sub_index} giữa nhiều clip — không thể tham chiếu "
                    "bằng số trong chế độ nhập tay khi tên file bị trùng số thứ tự."
                )
            lookup[clip.sub_index] = (scene.scene_index, clip)
    return lookup


def _parse_line(
    line_no: int,
    line: str,
    lookup: dict[tuple[int, ...], tuple[int, Clip]],
    expected_scene_indices: list[int],
) -> tuple[ClipGroup, ...]:
    raw_refs = line.split(":", 1)[1] if ":" in line else line
    ref_tokens = [t.strip() for t in raw_refs.split(",") if t.strip()]
    if not ref_tokens:
        raise ValueError(f"Dòng {line_no} không có clip nào: {line!r}")

    groups: list[ClipGroup] = []
    current_scene_index: int | None = None
    current_clips: list[Clip] = []

    for token in ref_tokens:
        sub_idx = parse_sub_index(token)
        match = lookup.get(sub_idx)
        if match is None:
            raise ValueError(f"Dòng {line_no}: không tìm thấy clip khớp '{token}'")
        scene_index, clip = match

        if current_scene_index is None:
            current_scene_index = scene_index
        elif scene_index != current_scene_index:
            groups.append(ClipGroup(scene_index=current_scene_index, clips=tuple(current_clips)))
            current_clips = []
            current_scene_index = scene_index
        current_clips.append(clip)

    if current_scene_index is not None:
        groups.append(ClipGroup(scene_index=current_scene_index, clips=tuple(current_clips)))

    actual_scene_indices = [g.scene_index for g in groups]
    if actual_scene_indices != expected_scene_indices:
        raise ValueError(
            f"Dòng {line_no}: thứ tự/số cảnh không khớp — kỳ vọng cảnh {expected_scene_indices}, "
            f"nhận được {actual_scene_indices} (thiếu cảnh, thừa cảnh, hoặc sai thứ tự)."
        )

    for group in groups:
        sub_indices = [c.sub_index for c in group.clips]
        if sub_indices != sorted(sub_indices):
            names = [c.path.name for c in group.clips]
            raise ValueError(
                f"Dòng {line_no}, cảnh {group.scene_index}: clip trong 1 nhóm phải theo đúng thứ "
                f"tự tên file tăng dần, nhận được {names}."
            )

    return tuple(groups)


def parse_manual_plan(text: str, scenes: tuple[SceneFolder, ...]) -> tuple[Assignment, ...]:
    """Parse text nhập tay thành N Assignment. Raise ValueError với thông báo
    rõ ràng (số dòng cụ thể) khi input sai thay vì render lặng lẽ sai."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError("Chưa nhập plan nào (mỗi dòng 1 video, VD 'video 1: 1.1,1.2, 2.1,2.2')")

    lookup = _build_clip_lookup(scenes)
    expected_scene_indices = [s.scene_index for s in scenes]

    assignments = []
    for i, line in enumerate(lines, start=1):
        groups = _parse_line(i, line, lookup, expected_scene_indices)
        assignments.append(Assignment(output_index=i - 1, groups=groups))
    return tuple(assignments)


def preview_manual_plan(text: str, scenes: tuple[SceneFolder, ...]) -> tuple[dict[str, object], ...]:
    """Return a compact, user-facing preview of a manual plan.

    This intentionally reuses `parse_manual_plan` so preview/estimate/render all
    validate the same input shape and report the same line-specific errors.
    """
    assignments = parse_manual_plan(text, scenes)
    rows: list[dict[str, object]] = []
    for assignment in assignments:
        rows.append(
            {
                "video_label": f"Video {assignment.output_index + 1}",
                "scenes": tuple(
                    {
                        "scene_label": f"Cảnh {group.scene_index + 1}",
                        "clips": tuple(clip.path.name for clip in group.clips),
                    }
                    for group in assignment.groups
                ),
            }
        )
    return tuple(rows)
