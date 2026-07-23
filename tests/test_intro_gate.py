"""Cổng mở đầu (mục 1b): video DÀI phải có lời chào + đọc tiêu đề; SHORT thì KHÔNG.

Phần CỐ ĐỊNH duy nhất của lời chào là cụm "Mến chào các bạn," — phần sau kịch bản
tự sinh đa dạng. Short vào hook thẳng, cấm mở bằng lời chào.
"""

import pytest

from ytb_pipeline.ideation.generator import CHARS_PER_MIN, GREETING_PREFIX, load_script

from conftest import make_script


def _long_body(text: str) -> str:
    """Nối thêm cho đủ độ dày ~12 phút để không vướng cổng độ dài."""
    filler = " Chi tiết cụ thể có cơ chế và ví dụ thực tế. "
    needed = int(CHARS_PER_MIN * 12.1) - len(text)
    return text + (filler * (-(-needed // len(filler))))[:needed]


def _short_body(text: str) -> str:
    filler = " Chi tiết cụ thể có cơ chế và ví dụ thực tế. "
    needed = int(CHARS_PER_MIN * 1.1) - len(text)
    return text + (filler * (-(-needed // len(filler))))[:needed]


def _long(narration):
    chunk_size = -(-len(narration) // 24)
    return make_script([
        {"caption": f"c-{index}", "narration": narration[index * chunk_size:(index + 1) * chunk_size]}
        for index in range(24)
    ], target_minutes=12)


def _short(narration):
    return make_script([{"caption": "c", "narration": narration}])


def test_video_dai_thieu_loi_chao_bi_chan(write_script):
    body = _long_body("Bạn có đang mất tập trung không? Hôm nay ta nói về deep work.")
    path = write_script(_long(body))
    with pytest.raises(ValueError, match="Mến chào các bạn"):
        load_script(path)


def test_video_dai_co_loi_chao_thi_qua(write_script):
    body = _long_body(
        f"{GREETING_PREFIX} bạn có đang mất tập trung vào công việc không? "
        "Video hôm nay: Deep Work — Làm Sâu Trong Thời Đại Sao Nhãng."
    )
    path = write_script(_long(body))
    assert load_script(path).segments[0].narration.startswith(GREETING_PREFIX)


def test_video_dai_loi_chao_da_dang_ve_sau_tu_do(write_script):
    # Phần sau cụm cố định khác nhau giữa các tập -> vẫn hợp lệ
    body = _long_body(
        f"{GREETING_PREFIX} đã bao giờ bạn ép mình kỷ luật mà vẫn thất bại chưa? "
        "Video hôm nay nói về cơ chế ý chí."
    )
    path = write_script(_long(body))
    assert load_script(path).segments


def test_short_co_loi_chao_bi_chan(write_script):
    # Short trong khung 1-1.5 phút nhưng mở bằng lời chào -> phải bị chặn.
    body = _short_body(f"{GREETING_PREFIX} vào hook đi nào.")
    path = write_script(_short(body))
    with pytest.raises(ValueError, match="Short.*lời chào"):
        load_script(path)


def test_short_khong_loi_chao_thi_qua(write_script):
    body = _short_body("Dừng ngay việc này lại.")
    path = write_script(_short(body))
    assert load_script(path).segments
