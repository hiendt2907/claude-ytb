"""Test caption động (lower-third, hiện dần từng từ) của khâu render."""

from ytb_pipeline.render import compose


def test_reveal_steps_one_word_per_step_accumulating():
    # Arrange
    caption = "Động lực là kẻ phản bội"  # 6 từ

    # Act
    steps = compose._reveal_steps(caption, duration=6.0)

    # Assert — mỗi mốc thêm một từ, tích luỹ dần
    assert len(steps) == 6
    assert steps[0][0] == "Động"
    assert steps[-1][0] == "Động lực là kẻ phản bội"


def test_reveal_steps_durations_sum_to_total():
    steps = compose._reveal_steps("một hai ba bốn", duration=4.0)
    assert sum(d for _, d in steps) == 4.0


def test_reveal_steps_single_word():
    steps = compose._reveal_steps("xin", duration=2.0)
    assert steps == [("xin", 2.0)]


def test_reveal_steps_empty_caption_is_one_blank_step():
    steps = compose._reveal_steps("", duration=1.5)
    assert steps == [("", 1.5)]


def test_caption_drawn_in_lower_third_not_centre():
    # tâm khối caption phải ở nửa dưới khung, không phải giữa
    assert compose.CAPTION_Y > 0.5
    assert int(compose.H * compose.CAPTION_Y) > compose.H // 2


def test_show_captions_off_by_default():
    # Mặc định KHÔNG chữ chạy trong video — mặt video sạch.
    from ytb_pipeline.config.settings import settings

    assert settings.show_captions is False
