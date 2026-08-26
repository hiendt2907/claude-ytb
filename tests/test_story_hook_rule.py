"""The opening gate must judge a story by story standards.

`_check_hook_strength` was written for the mechanism-explainer channel: it
demands a paradox marker ("nhưng", "thật ra", "vì sao") or a question in the
first sentence.  A character-story Short opens on a scene, so a perfectly good
episode was rejected at the input node — after ideation had already been paid
for.  A story opening is strong when it anchors the viewer in a concrete moment
and puts something at stake, which is what this rule checks instead.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ytb_pipeline.agents import qa_agent
from ytb_pipeline.content_profiles import load_content_profile


def _script(opening: str, *, profile_id: str = "ban-so-6", version: str | None = None):
    if version is None:
        version = load_content_profile(profile_id).version
    return SimpleNamespace(
        video_type="short",
        target_minutes=None,
        content_profile_id=profile_id,
        content_profile_version=version,
        segments=(SimpleNamespace(narration=opening, purpose="situation"),),
    )


def test_story_opening_with_moment_and_stake_passes():
    opening = "Sáu giờ bảy, Minh mở laptop. Tám rưỡi, cậu phải gửi bản đề xuất cho chị Hương."

    assert qa_agent._check_hook_strength(_script(opening)) == []


@pytest.mark.parametrize(
    "opening",
    [
        # No anchor: nobody, nowhere, no moment.
        "Có những buổi sáng trôi qua rất nhanh và người ta không kịp làm gì cả.",
        # Anchor but nothing at stake — a scene with no pressure is not a hook.
        "Sáu giờ bảy, Minh mở laptop và ngồi xuống chiếc bàn quen thuộc cạnh cửa kính.",
        # Too short to establish anything.
        "Minh mở laptop.",
    ],
)
def test_story_opening_without_moment_or_stake_is_rejected(opening):
    violations = qa_agent._check_hook_strength(_script(opening))

    assert [violation["rule"] for violation in violations] == ["hook"]


def test_explainer_profile_keeps_the_paradox_rule():
    """The old rule must stay intact for the mechanism-explainer channel."""
    scene_opening = "Sáu giờ bảy, Minh mở laptop. Tám rưỡi, cậu phải gửi bản đề xuất."

    violations = qa_agent._check_hook_strength(
        _script(scene_opening, profile_id="one-cup-cafe-6h")
    )

    assert [violation["rule"] for violation in violations] == ["hook"]


def test_legacy_script_without_profile_keeps_the_paradox_rule():
    scene_opening = "Sáu giờ bảy, Minh mở laptop. Tám rưỡi, cậu phải gửi bản đề xuất."

    violations = qa_agent._check_hook_strength(_script(scene_opening, version=""))

    assert [violation["rule"] for violation in violations] == ["hook"]


def test_shipped_story_fixture_passes_the_gate():
    """The profile's own fixture must satisfy its own profile's gate."""
    import json

    profile = load_content_profile("ban-so-6")
    payload = json.loads(
        (profile.root / "fixtures" / "episode-01-short.json").read_text(encoding="utf-8")
    )
    script = _script(
        payload["sections"][0]["voiceover"], version=payload["profile_version"],
    )

    assert qa_agent._check_hook_strength(script) == []


# ---------------------------------------------------------------------------
# Two more explainer-shaped gates that a story cannot satisfy on their terms.
# ---------------------------------------------------------------------------

def _story_script(sections):
    return SimpleNamespace(
        video_type="short",
        target_minutes=None,
        content_profile_id="ban-so-6",
        content_profile_version=load_content_profile("ban-so-6").version,
        segments=tuple(
            SimpleNamespace(narration=text, purpose=purpose, speaker_id=speaker)
            for purpose, speaker, text in sections
        ),
    )


def test_story_profile_with_narrator_reflection_does_not_accept_a_bounded_action_as_its_closing():
    """A profile that opts into narrator reflection cannot bypass it with an action."""
    script = _story_script([
        ("situation", "narrator", "Bảy giờ, Minh mở hộp thư lần thứ tư. Vẫn phải chờ."),
        ("payoff", "narrator", "Minh úp điện thoại xuống và làm việc kế tiếp trong hai mươi phút."),
    ])

    assert [v["rule"] for v in qa_agent._check_immediate_action(script)] == ["narrator_reflection"]


def test_story_ending_without_any_concrete_action_is_still_rejected():
    script = _story_script([
        ("situation", "narrator", "Bảy giờ, Minh mở hộp thư lần thứ tư. Vẫn phải chờ."),
        ("payoff", "narrator", "Buổi sáng trôi qua và Minh cảm thấy nhẹ nhõm hơn một chút."),
    ])

    assert [v["rule"] for v in qa_agent._check_immediate_action(script)] == ["narrator_reflection"]


def test_unconfigured_explainer_still_requires_an_imperative(monkeypatch):
    script = SimpleNamespace(
        video_type="short", target_minutes=None,
        content_profile_id="one-cup-cafe-6h", content_profile_version="1.0.0",
        segments=(SimpleNamespace(
            narration="Bạn sẽ thấy dễ chịu hơn khi làm việc trong hai mươi phút.",
            purpose="payoff",
        ),),
    )

    monkeypatch.setattr(qa_agent, "_content_profile", lambda _script: None)

    assert [v["rule"] for v in qa_agent._check_immediate_action(script)] == ["immediate_action"]


def test_speaker_name_prefix_in_narration_is_rejected():
    """`speaker_id` already routes the voice; a spoken "An:" is read aloud."""
    script = _story_script([
        ("situation", "narrator", "Bảy giờ, Minh mở hộp thư lần thứ tư. Vẫn phải chờ."),
        ("core_answer", "an", "An: Cậu đã mở hộp thư lần thứ mấy rồi?"),
    ])

    violations = qa_agent._check_speaker_prefix_leak(script)

    assert [v["rule"] for v in violations] == ["speaker_prefix"]


def test_story_rejects_direct_character_monologue_hidden_in_narrator_voice():
    script = _story_script([
        (
            "situation", "narrator",
            "An đặt tách cà phê xuống. Chị ơi, em không biết phải bắt đầu từ đâu nữa, "
            "em đã mở máy rất nhiều lần rồi mà vẫn không dám gửi bản nháp này cho ai cả. "
            "Cứ nghĩ đến phản hồi là em lại muốn đóng máy và làm việc khác để khỏi phải nhìn vào nó.",
        ),
    ])

    violations = qa_agent._check_story_speaker_ownership(script)

    assert [v["rule"] for v in violations] == ["speaker_ownership"]


def test_story_rejects_staging_prefix_in_character_voiceover():
    script = _story_script([
        ("core_answer", "an", "An đặt tách cà phê xuống: 'Cậu mở hộp thư lần thứ mấy rồi?'"),
    ])

    violations = qa_agent._check_character_voiceover_is_direct(script)

    assert [v["rule"] for v in violations] == ["character_voiceover_direct"]


def test_story_allows_a_character_to_quote_the_exact_words_they_will_say():
    """A colon can introduce a character's own quote, not just staging."""
    script = _story_script([
        (
            "application",
            "an",
            "Tôi sẽ nói đúng một câu: 'Chỗ dột sau kệ nước, nhờ anh xem giúp.'",
        ),
    ])

    assert qa_agent._check_character_voiceover_is_direct(script) == []


def test_narration_naming_a_character_normally_is_not_a_prefix_leak():
    script = _story_script([
        ("situation", "narrator", "Bảy giờ, Minh mở hộp thư lần thứ tư. Vẫn phải chờ."),
        ("core_answer", "an", "Cậu đã mở hộp thư lần thứ mấy rồi, Minh?"),
    ])

    assert qa_agent._check_speaker_prefix_leak(script) == []
