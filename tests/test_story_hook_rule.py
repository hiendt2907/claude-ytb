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


def _script(opening: str, *, profile_id: str = "ban-so-6", version: str = "1.0.0"):
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
    script = _script(payload["sections"][0]["voiceover"])

    assert qa_agent._check_hook_strength(script) == []
