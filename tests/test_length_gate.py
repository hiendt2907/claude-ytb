"""Ép độ dài video dài (ngang): >=10 phút, nội dung không được mỏng/chung chung."""

import pytest

from ytb_pipeline.ideation.generator import (
    CHARS_PER_MIN,
    estimate_minutes,
    load_script,
)
from ytb_pipeline.pkg.models import Segment

from conftest import chars_for_minutes, make_script


def _section(narration):
    return [{"caption": "c", "narration": narration}]


def test_estimate_minutes_theo_so_ky_tu():
    seg = Segment(caption="c", narration="x" * int(CHARS_PER_MIN))
    assert abs(estimate_minutes([seg]) - 1.0) < 1e-6


def test_short_qua_ngan_bi_chan(write_script):
    # Short không khai báo target, nội dung ~vài giây -> phải > 1 phút
    path = write_script(make_script(_section("ngắn thôi")))
    with pytest.raises(ValueError, match="quá ngắn"):
        load_script(path)


def test_short_qua_dai_bi_chan(write_script):
    # ~1.5 phút nội dung không khai báo target -> vượt khung Short (< 1.2 phút)
    path = write_script(make_script(_section(chars_for_minutes(1.5))))
    with pytest.raises(ValueError, match="quá dài"):
        load_script(path)


def test_short_trong_khoang_thi_qua(write_script):
    # ~1.0 phút -> nằm trong (0.8, 1.2) phút, không raise
    path = write_script(make_script(_section(chars_for_minutes(1.0))))
    assert load_script(path).segments


def test_video_dai_mong_bi_chan(write_script):
    # target 12 phút nhưng chỉ ~1 phút nội dung -> fail-fast
    thin = "Một câu chung chung. " * 50  # ~1000 ký tự ~0.8 phút
    path = write_script(make_script(_section(thin), target_minutes=12))
    with pytest.raises(ValueError, match="mỏng"):
        load_script(path)


def test_video_dai_du_day_thi_qua(write_script):
    full = ("Mến chào các bạn, hôm nay nói về chủ đề X. "
            + "Chi tiết cụ thể có số liệu và ví dụ thực tế. " * 400)  # ~17k ký tự ~14 phút
    path = write_script(make_script(_section(full), target_minutes=12))
    script = load_script(path)
    assert estimate_minutes(script.segments) >= 12


def test_target_ngoai_khoang_bi_chan(write_script):
    path = write_script(make_script(_section("x" * 99999), target_minutes=45))
    with pytest.raises(ValueError, match="target_minutes"):
        load_script(path)
