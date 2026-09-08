from __future__ import annotations

import pytest


def _strategy_voiceover(*, second_visual: str):
    from ytb_pipeline.pkg.models import ContentStrategy, HookPlan, Segment, Voiceover

    return Voiceover(
        topic="Trì hoãn",
        title="Mở laptop rồi cầm điện thoại",
        description="",
        video_type="short",
        strategy=ContentStrategy(
            format_id="core_answer_first_v1", core_mechanism="tránh né sự mơ hồ",
            audience_problem="mở laptop rồi cầm điện thoại", angle="trang trắng",
            long_form_slug="buoc-dau-mo-ho", playlist="co-che-tri-hoan",
            cta_target="buoc-dau-mo-ho",
            hook=HookPlan("Mở laptop", "Não đang né sự mơ hồ", "Vì sao?"),
        ),
        segments=(
            Segment("MỞ LAPTOP", "Mở laptop rồi cầm điện thoại.", purpose="situation",
                    visual_intent="Bàn tay mở laptop rồi với điện thoại", broll="hand opens laptop phone"),
            Segment("SỰ MƠ HỒ", "Não đang né sự mơ hồ.", purpose="core_answer",
                    visual_intent=second_visual, broll="blank document cursor"),
        ),
    )


def test_visual_hook_accepts_two_concrete_opening_beats():
    from ytb_pipeline.render.hook_sequence import validate_visual_hook

    validate_visual_hook(_strategy_voiceover(second_visual="Con trỏ chớp trên trang tài liệu trắng"))


def test_visual_hook_rejects_a_missing_core_answer_visual():
    from ytb_pipeline.render.hook_sequence import validate_visual_hook

    with pytest.raises(ValueError, match="core_answer"):
        validate_visual_hook(_strategy_voiceover(second_visual=""))
