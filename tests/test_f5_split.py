"""Test chia nhỏ text dài cho F5-TTS (tránh segfault với input quá dài)."""

import pytest

from ytb_pipeline.voiceover.f5_provider import _split_text, F5_MAX_CHARS


@pytest.mark.unit
def test_short_text_one_chunk():
    text = "Một câu ngắn gọn."
    assert _split_text(text) == [text]


@pytest.mark.unit
def test_long_text_split_under_limit():
    # đoạn 9 thực tế từng làm F5 segfault (442 ký tự)
    text = (
        "Môi trường mạnh hơn ý chí, luôn luôn. Nếu muốn ăn lành mạnh hơn, hãy để "
        "trái cây ngay trước mặt và giấu bánh kẹo vào ngăn tủ khó với. Nếu muốn "
        "đọc nhiều hơn, hãy đặt quyển sách trên gối và cắm sạc điện thoại ở phòng "
        "khác. Mỗi giây trì hoãn bạn thêm vào một thói quen xấu sẽ làm nó yếu đi. "
        "Mỗi rào cản bạn gỡ bỏ khỏi một thói quen tốt sẽ làm nó mạnh lên."
    )
    chunks = _split_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= F5_MAX_CHARS for c in chunks)
    # không mất nội dung: nối lại chứa mọi câu
    joined = " ".join(chunks)
    assert "Môi trường mạnh hơn ý chí" in joined
    assert "làm nó mạnh lên" in joined


@pytest.mark.unit
def test_single_overlong_sentence_split_on_comma():
    text = "phần một, " * 40  # 1 "câu" rất dài, chỉ có dấu phẩy
    chunks = _split_text(text)
    assert all(len(c) <= F5_MAX_CHARS for c in chunks)
    assert len(chunks) >= 2


@pytest.mark.unit
def test_boundary_exactly_max_chars():
    text = "a" * F5_MAX_CHARS
    assert _split_text(text) == [text]
