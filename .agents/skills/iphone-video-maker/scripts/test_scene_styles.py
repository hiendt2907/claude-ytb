"""Test logic thuần cho mapping nhãn cảnh → style (không cần ffmpeg).

Chạy riêng, không nằm trong testpaths của pytest.ini (chỉ quét tests/ ở repo root)
nên không ảnh hưởng tới coverage gate của ytb_pipeline:

    python3 -m pytest .claude/skills/iphone-video-maker/scripts/test_scene_styles.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from edit_render import (  # noqa: E402
    DEFAULT_SCENE,
    SCENE_STYLES,
    scene_style,
    zoom_punch_crop_filter,
)

REQUIRED_STYLE_KEYS = {"extra_vf", "zoom_end", "punch"}


def test_unknown_scene_falls_back_to_default():
    assert scene_style("khong_ton_tai") == scene_style(DEFAULT_SCENE)


def test_missing_scene_falls_back_to_default():
    assert scene_style(None) == scene_style(DEFAULT_SCENE)


def test_every_scene_has_required_style_keys():
    for scene, style in SCENE_STYLES.items():
        assert REQUIRED_STYLE_KEYS.issubset(style.keys()), scene


def test_scene_style_returns_copy_not_reference():
    style = scene_style("cta")
    style["zoom_end"] = 999
    assert SCENE_STYLES["cta"]["zoom_end"] != 999


def test_zoom_punch_crop_filter_none_when_static():
    assert zoom_punch_crop_filter(1.0, 0.0, 5.0) is None


def test_zoom_punch_crop_filter_present_when_zoom_or_punch():
    assert zoom_punch_crop_filter(1.1, 0.0, 5.0) is not None
    assert zoom_punch_crop_filter(1.0, 0.05, 5.0) is not None


def test_zoom_punch_crop_filter_no_max_with_t_variable():
    # libavfilter báo lỗi eval khi dùng max() cùng biến t — đảm bảo không quay lại bug cũ.
    expr = zoom_punch_crop_filter(1.1, 0.05, 5.0)
    assert "max(" not in expr
