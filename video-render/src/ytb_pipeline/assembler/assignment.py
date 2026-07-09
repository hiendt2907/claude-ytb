"""Thuật toán chọn/ghép clip: random hoá việc chia nhóm qua từng output,
đảm bảo mọi clip trong mọi thư mục cảnh được dùng ít nhất 1 lần sau N output.

Trong 1 nhóm đã chọn cho 1 cảnh/1 output, thứ tự nối clip LUÔN theo sub_index
(tên file) — không random. Việc random chỉ áp dụng cho ranh giới chia nhóm và
việc chọn nhóm nào cho output nào.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Sequence

from ytb_pipeline.assembler.models import Assignment, Clip, ClipGroup, SceneFolder


def _random_contiguous_group(clips: tuple[Clip, ...], rng: random.Random) -> tuple[Clip, ...]:
    """Chọn ngẫu nhiên 1 nhóm liên tiếp (1..len(clips) clip) từ danh sách đã sort."""
    start = rng.randint(0, len(clips) - 1)
    end = rng.randint(start, len(clips) - 1)
    return clips[start : end + 1]


def _expand_group_to_include(
    clips: tuple[Clip, ...], current_group: tuple[Clip, ...], target: Clip
) -> tuple[Clip, ...]:
    """Mở rộng group hiện tại để chứa `target` mà không làm mất clip đã cover."""
    if not current_group:
        return (target,)
    target_pos = clips.index(target)
    current_positions = [clips.index(clip) for clip in current_group]
    start = min(target_pos, *current_positions)
    end = max(target_pos, *current_positions)
    return clips[start : end + 1]


def _assign_scene_groups(
    scene: SceneFolder, n_outputs: int, rng: random.Random
) -> list[ClipGroup]:
    """Sinh N nhóm clip cho 1 cảnh (1 nhóm/output), rồi vá coverage nếu thiếu."""
    if not scene.clips:
        return [ClipGroup(scene_index=scene.scene_index, clips=()) for _ in range(n_outputs)]

    groups = [_random_contiguous_group(scene.clips, rng) for _ in range(n_outputs)]

    used: set[Clip] = {clip for group in groups for clip in group}
    missing = [clip for clip in scene.clips if clip not in used]
    for clip in missing:
        target_output = rng.randrange(n_outputs)
        groups[target_output] = _expand_group_to_include(
            scene.clips, groups[target_output], clip
        )

    return [ClipGroup(scene_index=scene.scene_index, clips=group) for group in groups]


def build_assignments(
    scenes: Sequence[SceneFolder], n_outputs: int, rng: random.Random | None = None
) -> tuple[Assignment, ...]:
    """Sinh N assignment (1 assignment/output), đảm bảo coverage 100% clip nguồn.

    Mỗi assignment gồm đúng 1 ClipGroup/cảnh, theo đúng thứ tự scene_index.
    """
    if n_outputs < 1:
        raise ValueError("n_outputs phải >= 1")
    rng = rng if rng is not None else random.Random()

    per_scene_groups = [_assign_scene_groups(scene, n_outputs, rng) for scene in scenes]

    assignments = []
    for output_index in range(n_outputs):
        groups = tuple(per_scene_groups[scene_i][output_index] for scene_i in range(len(scenes)))
        assignments.append(Assignment(output_index=output_index, groups=groups))
    return tuple(assignments)


def _assignment_signature(assignment: Assignment) -> tuple:
    """Chữ ký duy nhất cho tổ hợp clip của 1 assignment — 2 assignment có cùng
    chữ ký nghĩa là ra video giống hệt nhau về mặt hình ảnh (cùng clip, cùng
    cảnh, cùng thứ tự)."""
    return tuple((g.scene_index, tuple(c.sub_index for c in g.clips)) for g in assignment.groups)


def find_duplicate_assignments(assignments: Sequence[Assignment]) -> tuple[tuple[int, ...], ...]:
    """Tìm các nhóm output_index có tổ hợp clip giống hệt nhau trong cùng 1 batch.

    Trả về tuple các tuple output_index (0-based) — mỗi tuple con là 1 nhóm
    >= 2 output trùng nhau. Rỗng nếu không có trùng lặp. Chỉ để CẢNH BÁO,
    không chặn render — do random hoặc plan tay đều có thể vô tình trùng.
    """
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for assignment in assignments:
        buckets[_assignment_signature(assignment)].append(assignment.output_index)
    return tuple(tuple(v) for v in buckets.values() if len(v) > 1)
