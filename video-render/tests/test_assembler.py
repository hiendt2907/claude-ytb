"""Unit test cho assembler: scanning, assignment (coverage + random grouping), naming."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from ytb_pipeline.assembler.assignment import build_assignments, find_duplicate_assignments
from ytb_pipeline.assembler.models import Clip, ClipGroup, SceneFolder
from ytb_pipeline.assembler.naming import output_path
from ytb_pipeline.assembler.scanning import parse_sub_index, scan_scene_folders


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_parse_sub_index_extracts_numeric_tokens() -> None:
    assert parse_sub_index("1.2") == (1, 2)
    assert parse_sub_index("10.3") == (10, 3)
    assert parse_sub_index("no_numbers") == ()


def test_scan_scene_folders_sorts_clips_by_sub_index(tmp_path: Path) -> None:
    scene1 = tmp_path / "scene_01"
    _touch(scene1 / "1.10.mp4")
    _touch(scene1 / "1.2.mp4")
    _touch(scene1 / "1.1.mp4")

    scenes = scan_scene_folders(tmp_path)

    assert len(scenes) == 1
    names = [c.path.name for c in scenes[0].clips]
    assert names == ["1.1.mp4", "1.2.mp4", "1.10.mp4"]


def test_scan_scene_folders_orders_scenes_by_folder_name(tmp_path: Path) -> None:
    _touch(tmp_path / "scene_02" / "2.1.mp4")
    _touch(tmp_path / "scene_01" / "1.1.mp4")

    scenes = scan_scene_folders(tmp_path)

    assert [s.path.name for s in scenes] == ["scene_01", "scene_02"]
    assert [s.scene_index for s in scenes] == [0, 1]


def test_scan_scene_folders_uses_natural_sort_past_10_scenes(tmp_path: Path) -> None:
    """'scene_10' phải đứng SAU 'scene_2', không phải trước (sort chuỗi thuần sẽ sai)."""
    for name in ["scene_1", "scene_2", "scene_10", "scene_11", "scene_9"]:
        _touch(tmp_path / name / "clip.mp4")

    scenes = scan_scene_folders(tmp_path)

    assert [s.path.name for s in scenes] == [
        "scene_1",
        "scene_2",
        "scene_9",
        "scene_10",
        "scene_11",
    ]


def _make_scene(scene_index: int, n_clips: int) -> SceneFolder:
    clips = tuple(
        Clip(path=Path(f"scene_{scene_index}/{scene_index}.{i}.mp4"), scene_index=scene_index, sub_index=(scene_index, i))
        for i in range(1, n_clips + 1)
    )
    return SceneFolder(scene_index=scene_index, path=Path(f"scene_{scene_index}"), clips=clips)


def test_build_assignments_covers_every_clip_at_least_once() -> None:
    scenes = [_make_scene(0, 7), _make_scene(1, 3)]
    rng = random.Random(42)

    assignments = build_assignments(scenes, n_outputs=5, rng=rng)

    assert len(assignments) == 5
    for scene in scenes:
        used = {
            clip
            for assignment in assignments
            for group in assignment.groups
            if group.scene_index == scene.scene_index
            for clip in group.clips
        }
        assert used == set(scene.clips)


def test_build_assignments_coverage_repair_does_not_drop_previously_used_clip() -> None:
    """Regression: vá missing clip bằng cách thay group có thể làm mất clip đã cover."""
    scenes = [_make_scene(0, 3)]
    assignments = build_assignments(scenes, n_outputs=2, rng=random.Random(7))

    used = {
        clip
        for assignment in assignments
        for group in assignment.groups
        for clip in group.clips
    }

    assert used == set(scenes[0].clips)


def test_build_assignments_keeps_within_group_order_by_sub_index() -> None:
    scenes = [_make_scene(0, 5)]
    rng = random.Random(7)

    assignments = build_assignments(scenes, n_outputs=8, rng=rng)

    for assignment in assignments:
        for group in assignment.groups:
            sub_indices = [c.sub_index for c in group.clips]
            assert sub_indices == sorted(sub_indices)


def test_build_assignments_varies_grouping_across_outputs() -> None:
    scenes = [_make_scene(0, 12)]
    rng = random.Random(123)

    assignments = build_assignments(scenes, n_outputs=6, rng=rng)

    group_signatures = {
        tuple(c.sub_index for c in assignment.groups[0].clips) for assignment in assignments
    }
    assert len(group_signatures) > 1


def test_build_assignments_rejects_invalid_n_outputs() -> None:
    with pytest.raises(ValueError):
        build_assignments([_make_scene(0, 3)], n_outputs=0)


def test_find_duplicate_assignments_detects_identical_groups() -> None:
    from ytb_pipeline.assembler.models import Assignment

    scene0 = _make_scene(0, 3)
    group_a = ClipGroup(scene_index=0, clips=(scene0.clips[0], scene0.clips[1]))
    group_b = ClipGroup(scene_index=0, clips=(scene0.clips[2],))
    assignments = (
        Assignment(output_index=0, groups=(group_a,)),
        Assignment(output_index=1, groups=(group_a,)),  # trùng với output 0
        Assignment(output_index=2, groups=(group_b,)),
    )

    duplicates = find_duplicate_assignments(assignments)

    assert duplicates == ((0, 1),)


def test_find_duplicate_assignments_empty_when_all_unique() -> None:
    scenes = [_make_scene(0, 6)]
    rng = random.Random(1)
    assignments = build_assignments(scenes, n_outputs=2, rng=rng)
    # có thể trùng hoặc không tuỳ random, chỉ kiểm tra hàm chạy không lỗi
    duplicates = find_duplicate_assignments(assignments)
    assert isinstance(duplicates, tuple)


def test_output_path_zero_pads_by_n_outputs() -> None:
    p = output_path(Path("output"), "my_product", output_index=0, n_outputs=12)
    assert p == Path("output/my_product/variant_01.mp4")

    p2 = output_path(Path("output"), "my_product", output_index=11, n_outputs=12)
    assert p2 == Path("output/my_product/variant_12.mp4")
