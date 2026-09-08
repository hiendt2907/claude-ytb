"""Regression: a pacing piece must always contain something to speak.

A closing curly quote is not a break character, so `“…”.` used to split into a
piece holding only `”.`.  xKiro rejects such an input with HTTP 400 and the
whole segment fails, which is why only some scripts with curly quotes broke.
"""

from __future__ import annotations

import pytest

from ytb_pipeline.voiceover.tts import _split_for_pacing


def _speakable(text: str) -> bool:
    return any(character.isalnum() for character in text)


@pytest.mark.parametrize(
    "text",
    [
        'Tên của nó là “chi phí cơ hội”. Bạn vừa trả một cái giá không ai ghi.',
        'Bạn tự hỏi “mình mất gì”, rồi bỏ qua câu trả lời.',
        'Anh ấy nói “không sao”… và im lặng.',
        '“Đã giảm giá”. “Đang tiện”. “Để mai tính”.',
    ],
)
def test_every_piece_has_something_to_speak(text):
    pieces = _split_for_pacing(text, 0.25, 0.4)

    assert pieces
    assert all(_speakable(piece) for piece, _ in pieces), pieces


def test_punctuation_only_input_yields_no_piece():
    assert _split_for_pacing("”.", 0.25, 0.4) == []


def test_merging_keeps_the_full_text_and_the_longer_pause():
    text = 'Nó tên là “chi phí cơ hội”. Hết.'

    pieces = _split_for_pacing(text, 0.25, 0.4)

    assert "".join(piece for piece, _ in pieces).replace(" ", "") == text.replace(" ", "")
    assert pieces[0][1] == 0.4
