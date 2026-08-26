"""Regression tests for the user-approved creative contracts.

These assertions deliberately inspect the *assembled* system prompt rather
than isolated markdown files.  A profile contract that exists only in docs but
is not sent to the script model cannot protect the next transcript.
"""

from __future__ import annotations


def test_explainer_prompt_names_the_midcareer_burdened_man_and_friend_voice():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    prompt = " ".join(
        script_generation_system_prompt(
            load_content_profile("one-cup-cafe-6h"), video_type="long"
        ).split()
    ).casefold()

    assert "33–35" in prompt
    assert "nợ chưa trả hết" in prompt
    assert "nuôi gia đình" in prompt
    assert "một người bạn" in prompt
    assert "không bán công thức đổi đời" in prompt


def test_explainer_prompt_requires_lived_transitions_not_outline_labels():
    """A real failed draft turned distinct angles into a numbered lecture.

    The production prompt must teach the writer how to keep multiple angles
    without turning a friend-to-friend narration into an outline, and must not
    manufacture an escalation into generic specialist advice.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    prompt = " ".join(
        script_generation_system_prompt(
            load_content_profile("one-cup-cafe-6h"), video_type="long"
        ).split()
    ).casefold()

    assert "không dùng nhãn kiểu \"góc nhìn thứ nhất\"" in prompt
    assert "chỉ nhắc đến việc nhờ thêm hỗ trợ khi cảnh trước đó đã cho thấy" in prompt


def test_explainer_prompt_rejects_disguised_outlines_and_ungrounded_generalizations():
    """The second live draft evaded the first rule with 'một phía/phía thứ hai'."""
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    prompt = " ".join(
        script_generation_system_prompt(
            load_content_profile("one-cup-cafe-6h"), video_type="long"
        ).split()
    ).casefold()

    assert "không thay nhãn số bằng nhãn cấu trúc" in prompt
    assert "không khái quát hóa thay cho cảnh đời" in prompt


def test_story_prompt_keeps_table_six_as_a_real_relationship_not_a_stage_prop():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    prompt = script_generation_system_prompt(
        load_content_profile("ban-so-6"), video_type="long"
    ).casefold()

    assert "bàn số 6" in prompt
    assert "chủ quán" in prompt
    assert "mỗi sáng lúc 6 giờ" in prompt
    assert "không phải chuyên gia" in prompt
    assert "không nói thay người xem" in prompt


def test_story_closing_prompt_requires_a_limited_reflection_not_a_universal_moral():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    prompt = script_generation_system_prompt(
        load_content_profile("ban-so-6"), video_type="long"
    ).casefold()

    assert "phản chiếu khiêm tốn" in prompt
    assert "không phải một quy luật cho mọi người" in prompt
