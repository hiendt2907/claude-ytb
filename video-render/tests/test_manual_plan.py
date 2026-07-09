"""Test chế độ nhập tay thứ tự clip theo cảnh (thay cho random assignment)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ytb_pipeline.assembler.manual_plan import parse_manual_plan, preview_manual_plan
from ytb_pipeline.assembler.models import Clip, SceneFolder


def _clip(scene_index: int, *nums: int) -> Clip:
    name = ".".join(str(n) for n in nums)
    return Clip(path=Path(f"scene_{scene_index}/{name}.mp4"), scene_index=scene_index, sub_index=nums)


def _scenes() -> tuple[SceneFolder, ...]:
    scene0 = SceneFolder(
        scene_index=0, path=Path("scene_0"),
        clips=(_clip(0, 1, 1), _clip(0, 1, 2), _clip(0, 1, 3)),
    )
    scene1 = SceneFolder(
        scene_index=1, path=Path("scene_1"),
        clips=(_clip(1, 2, 1), _clip(1, 2, 2), _clip(1, 2, 3), _clip(1, 2, 4)),
    )
    scene2 = SceneFolder(
        scene_index=2, path=Path("scene_2"),
        clips=(_clip(2, 3, 1), _clip(2, 3, 2)),
    )
    return (scene0, scene1, scene2)


def test_parse_manual_plan_builds_groups_from_refs() -> None:
    text = "video 1: 1.1,1.2, 2.3,2.4, 3.1,3.2"
    assignments = parse_manual_plan(text, _scenes())

    assert len(assignments) == 1
    a = assignments[0]
    assert [g.scene_index for g in a.groups] == [0, 1, 2]
    assert [c.sub_index for c in a.groups[0].clips] == [(1, 1), (1, 2)]
    assert [c.sub_index for c in a.groups[1].clips] == [(2, 3), (2, 4)]
    assert [c.sub_index for c in a.groups[2].clips] == [(3, 1), (3, 2)]


def test_parse_manual_plan_multiple_lines_multiple_outputs() -> None:
    text = "\n".join([
        "video 1: 1.1, 2.1, 3.1",
        "video 2: 1.2, 2.2, 3.2",
    ])
    assignments = parse_manual_plan(text, _scenes())
    assert len(assignments) == 2
    assert assignments[0].output_index == 0
    assert assignments[1].output_index == 1


def test_parse_manual_plan_single_clip_per_scene_allowed() -> None:
    text = "video 1: 1.1, 2.1, 3.1"
    assignments = parse_manual_plan(text, _scenes())
    assert [len(g.clips) for g in assignments[0].groups] == [1, 1, 1]


def test_parse_manual_plan_accepts_short_line_without_video_label() -> None:
    text = "\n".join([
        "1.1, 2.1, 3.1",
        "1.2, 2.2, 3.2",
    ])
    assignments = parse_manual_plan(text, _scenes())

    assert len(assignments) == 2
    assert [c.sub_index for c in assignments[0].groups[0].clips] == [(1, 1)]
    assert [c.sub_index for c in assignments[1].groups[2].clips] == [(3, 2)]


def test_preview_manual_plan_returns_user_facing_rows() -> None:
    preview = preview_manual_plan("1.1, 2.1, 3.1", _scenes())

    assert preview == (
        {
            "video_label": "Video 1",
            "scenes": (
                {"scene_label": "Cảnh 1", "clips": ("1.1.mp4",)},
                {"scene_label": "Cảnh 2", "clips": ("2.1.mp4",)},
                {"scene_label": "Cảnh 3", "clips": ("3.1.mp4",)},
            ),
        },
    )


def test_parse_manual_plan_rejects_missing_scene() -> None:
    text = "video 1: 1.1, 3.1"  # thiếu cảnh 1 (scene_index=1)
    with pytest.raises(ValueError, match="thứ tự/số cảnh không khớp"):
        parse_manual_plan(text, _scenes())


def test_parse_manual_plan_rejects_unknown_clip_ref() -> None:
    text = "video 1: 1.1, 2.1, 9.9"
    with pytest.raises(ValueError, match="không tìm thấy clip"):
        parse_manual_plan(text, _scenes())


def test_parse_manual_plan_rejects_out_of_order_clips_within_group() -> None:
    text = "video 1: 1.2,1.1, 2.1, 3.1"
    with pytest.raises(ValueError, match="thứ tự tên file tăng dần"):
        parse_manual_plan(text, _scenes())


def test_parse_manual_plan_rejects_missing_colon() -> None:
    with pytest.raises(ValueError, match="không tìm thấy clip"):
        parse_manual_plan("video 1 1.1, 2.1, 3.1", _scenes())


def test_parse_manual_plan_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="Chưa nhập plan"):
        parse_manual_plan("   ", _scenes())
