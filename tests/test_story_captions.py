"""Captions must show what is being SAID, timed to when it is said.

The first story renderer drew `Segment.caption` — a description of the picture
("Cửa kính quán lúc sáng sớm") — under an ALL-CAPS `NARRATOR` slug on a plate
covering a quarter of the frame.  A viewer reads a screenplay note that has no
relation to the sentence in their ears, for the whole 25-second section.

The prototype in ../ai-money does it the other way: one card per spoken line,
the line itself, speaker identity carried by colour instead of a label.
"""

from __future__ import annotations

import pytest

from ytb_pipeline.content_profiles import load_content_profile
from ytb_pipeline.render.story import caption_lines, line_durations, speaker_colour


def test_caption_lines_split_on_sentences():
    narration = "Sáu giờ bảy phút. Minh đẩy cửa kính bước vào quán. Cậu đặt túi canvas xuống."

    lines = caption_lines(narration, max_chars=40)

    assert len(lines) >= 2
    assert lines[0].startswith("Sáu giờ bảy")
    assert all(len(line) <= 60 for line in lines)


def test_caption_lines_keep_every_word_of_the_narration():
    narration = "Minh mở laptop lần thứ nhất. File trống. Cậu đóng lại sau mười lăm giây."

    joined = " ".join(caption_lines(narration, max_chars=30))

    for word in narration.replace(".", "").split():
        assert word in joined


def test_a_long_sentence_is_wrapped_rather_than_dropped():
    sentence = "Cậu ngồi nhìn màn hình trắng một lúc lâu rồi quyết định lấy giấy ra sắp lại đầu mục cho gọn"

    lines = caption_lines(sentence, max_chars=40)

    assert len(lines) > 1
    assert " ".join(lines).split() == sentence.split()


def test_empty_narration_yields_no_card():
    assert caption_lines("   ", max_chars=40) == []


def test_line_durations_sum_to_the_measured_audio():
    lines = ["Sáu giờ bảy phút.", "Minh đẩy cửa kính bước vào quán rồi ngồi xuống."]

    durations = line_durations(lines, total_sec=10.0)

    assert pytest.approx(sum(durations), abs=1e-6) == 10.0
    assert durations[1] > durations[0], "câu dài hơn phải chiếm nhiều thời gian hơn"


def test_line_durations_never_returns_a_zero_slice():
    durations = line_durations(["a", "một câu dài hơn nhiều so với câu trước"], total_sec=4.0)

    assert all(duration > 0 for duration in durations)


def test_each_cast_member_gets_a_distinct_colour():
    profile = load_content_profile("ban-so-6")

    colours = {name: speaker_colour(profile, name) for name in profile.voice_cast}

    assert len(set(colours.values())) == len(colours)


def test_speaker_colour_is_stable_across_calls():
    profile = load_content_profile("ban-so-6")

    assert speaker_colour(profile, "minh") == speaker_colour(profile, "minh")


def test_unknown_speaker_falls_back_to_the_narrator_colour():
    profile = load_content_profile("ban-so-6")

    assert speaker_colour(profile, "khach-la") == speaker_colour(profile, "narrator")


def test_segment_cards_never_yields_a_clip_shorter_than_the_profile_transition_overlap(tmp_path):
    """A real Long render crashed in `_compose_clips` ('Story transition_overlap_sec
    phải ngắn hơn mọi segment clip.') because a short trailing sentence
    ('Cậu thấy sao?') got its own proportional caption card, and that
    card's duration fell at/under `profile.render.transition_overlap_sec`.
    `_segment_cards` must merge such a card into a neighbour instead of ever
    handing the renderer a clip length the compose step cannot use."""
    from ytb_pipeline.render.story import _segment_cards, LANDSCAPE
    from ytb_pipeline.pkg.models import Segment
    from tests.test_visual_generation_profile import _write_profile

    folder = _write_profile(tmp_path, "ban-so-6")
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)
    # Verbatim narration from a real Long render that crashed here: a long
    # sentence wraps to a tiny trailing chunk ("đó?"), whose proportional
    # share of the section's real measured duration (16.43s) came out at
    # 0.176s — under the profile's 0.4s transition_overlap_sec.
    narration = (
        "Vậy cậu thấy câu hỏi nào làm cậu khó chịu nhất? Là phần số liệu, "
        "phương pháp, hay câu hỏi mục tiêu đó? An hỏi, tay cầm cốc cà phê của "
        "mình, không uống mà chỉ xoay nhẹ. 'Tớ không phải chuyên gia, nhưng "
        "tớ có thể nghe cậu nói xem cậu đang bí ở đâu. Đôi khi chỉ cần nói ra "
        "là thấy nhẹ hơn.'"
    )
    segment = Segment(
        caption="", narration=narration, voiceover=narration,
        time_goal=0.3, visual_intent="An hoi Minh.", speaker_id="an",
        scene_characters=("minh", "an"), duration_sec=16.426485,
        audio_path=str(tmp_path / "fake.mp3"),
    )

    cards = _segment_cards(segment, profile, LANDSCAPE)

    assert all(
        length > profile.render.transition_overlap_sec for _text, _seek, length in cards
    ), [length for _t, _s, length in cards]
