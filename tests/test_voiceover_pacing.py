"""Test nhịp ngắt nghỉ giọng đọc — chia narration thành cụm + khoảng lặng sau cụm."""

from ytb_pipeline.voiceover import tts


def test_split_pacing_sentence_gets_sentence_pause():
    # Arrange
    text = "Xin chào. Tạm biệt."

    # Act
    pieces = tts._split_for_pacing(text, comma_sec=0.25, sentence_sec=0.4)

    # Assert — cụm đầu kết bằng dấu chấm → nghỉ dài; cụm cuối nghỉ 0 (để mức segment lo)
    assert pieces[0] == ("Xin chào.", 0.4)
    assert pieces[-1][1] == 0.0


def test_split_pacing_comma_gets_shorter_pause():
    pieces = tts._split_for_pacing("Một, hai ba.", comma_sec=0.25, sentence_sec=0.4)
    assert pieces[0] == ("Một,", 0.25)


def test_split_pacing_empty_returns_empty():
    assert tts._split_for_pacing("", comma_sec=0.25, sentence_sec=0.4) == []


def test_split_pacing_single_clause_no_internal_pause():
    pieces = tts._split_for_pacing("Một câu không dấu", comma_sec=0.25, sentence_sec=0.4)
    assert pieces == [("Một câu không dấu", 0.0)]


def test_split_pacing_preserves_all_words():
    text = "Học nhanh, nhớ lâu. Hiệu quả thật!"
    pieces = tts._split_for_pacing(text, comma_sec=0.2, sentence_sec=0.5)
    joined = " ".join(p for p, _ in pieces)
    assert "Học nhanh" in joined and "nhớ lâu" in joined and "Hiệu quả thật" in joined
