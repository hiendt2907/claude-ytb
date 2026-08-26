"""`_check_story_hook`'s stake marker list must cover the semantic classes
`STORY_HOOK_CONTRACT` promises — obligation/deadline, AND consequence/risk —
not just the first class.

Root cause (from a real `qwen/qwen3.8-max:free` smoke, see
docs/handoffs/2026-08-26-*-hook-*.md): the real candidate opened with
"Sáu giờ hai mươi sáng. Minh đã gạch ba phương án phân công ca chiều, sợ hỏi
An thì bị chê là thiếu chủ động." — a concrete anchor (a clock time, a named
cast member) plus a concrete risk ("sợ ... thì bị chê" = afraid of being
criticized), yet QA rejected it, because `_STORY_STAKE_MARKERS` only
recognised the obligation/deadline class ("phải", "chưa", "sắp", "hạn", ...)
and had no marker for the consequence/risk class the contract also promises.

The fix must not be "add the literal phrase 'sợ hỏi An thì bị chê'" — that
patches one sentence. It must recognise the semantic CLASS: "bị" is
Vietnamese's adversative-passive marker (something bad happens TO the
subject, unlike the neutral/positive "được"), so it generalises to any
negative-consequence verb that follows ("bị chê", "bị la", "bị phạt", "bị
đuổi", ...) without listing each one; "sợ"/"lo"/"nếu"/"nhỡ"/"kẻo" mark an
anticipated risk the character is reacting to. Every test below uses a cast
and topic that is NOT `ban-so-6` to prove the fix is about the marker class,
not one profile's fixture sentence.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.agents import qa_agent
from ytb_pipeline.config.settings import settings
from ytb_pipeline.content_profiles import load_content_profile

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "content_profiles"


@pytest.fixture()
def office_profile(monkeypatch):
    monkeypatch.setattr(settings, "content_profiles_dir", FIXTURES_ROOT, raising=False)
    return load_content_profile("office-thread-fixture", profiles_dir=FIXTURES_ROOT)


def _script(opening: str, *, profile_id: str, version: str):
    return SimpleNamespace(
        video_type="short",
        target_minutes=None,
        content_profile_id=profile_id,
        content_profile_version=version,
        segments=(SimpleNamespace(narration=opening, purpose="situation"),),
    )


def test_anchor_with_natural_fear_and_consequence_stake_passes(office_profile):
    """The exact semantic shape of the real rejected Qwen candidate,
    reproduced deterministically with a different cast/topic."""
    opening = (
        "Sáu giờ hai mươi sáng. Lan đã gạch ba phương án phân công ca chiều, "
        "sợ hỏi Duy thì bị chê là thiếu chủ động."
    )

    assert qa_agent._check_hook_strength(
        _script(opening, profile_id=office_profile.profile_id, version=office_profile.version)
    ) == []


@pytest.mark.parametrize(
    "opening",
    [
        # "bị" alone (adversative passive) with a different negative verb —
        # proves the fix generalises past the one verb in the real candidate.
        "Bảy giờ, Duy vừa gửi bản nháp thì bị anh quản lý gọi lên ngay.",
        # "lo" (worry) instead of "sợ" — same risk/anticipation class. No
        # overlap with the obligation/deadline markers ("trễ", "hạn", ...)
        # so this exercises the risk class in isolation.
        "Tám giờ, Lan lo Duy đọc bản nháp rồi lại nghĩ cô làm ẩu.",
    ],
)
def test_other_members_of_the_risk_consequence_class_also_pass(office_profile, opening):
    assert qa_agent._check_hook_strength(
        _script(opening, profile_id=office_profile.profile_id, version=office_profile.version)
    ) == []


def test_anchor_without_any_stake_class_is_still_rejected(office_profile):
    """Regression: a scene with a moment and a name but no pressure at all
    (neither obligation/deadline nor consequence/risk) must still fail."""
    opening = "Sáu giờ hai mươi sáng, Lan ngồi xuống chiếc bàn quen thuộc cạnh cửa sổ."

    violations = qa_agent._check_hook_strength(
        _script(opening, profile_id=office_profile.profile_id, version=office_profile.version)
    )

    assert [v["rule"] for v in violations] == ["hook"]


def test_stake_without_any_anchor_is_rejected(office_profile):
    """A risk with no concrete moment, place, or named character is not a
    hook either — the contract requires BOTH, not just one."""
    opening = "Có người sợ rằng nếu hỏi thì sẽ bị chê là thiếu chủ động."

    violations = qa_agent._check_hook_strength(
        _script(opening, profile_id=office_profile.profile_id, version=office_profile.version)
    )

    assert [v["rule"] for v in violations] == ["hook"]


def test_qa_judges_the_canonical_spoken_text_not_a_staging_description(tmp_path, monkeypatch):
    """QA must never read a visual/camera-direction field: it must read
    whatever text the loader resolves as the actual TTS voiceover.

    A real Qwen candidate had DIFFERENT `voiceover` and `narration` values in
    its raw JSON — `narration` held a camera-direction description
    ("Mở cảnh bằng đồng hồ treo tường chỉ 6:20, máy lia xuống...") while
    `voiceover` held the actual spoken line with the real anchor+stake. This
    locks in that `ideation.generator.load_script` resolves to `voiceover`
    (never the staging text) before QA ever sees the segment, so nobody
    reintroduces a staging-description leak by reading the wrong field later.
    """
    import json

    from ytb_pipeline.ideation.generator import load_script

    monkeypatch.setattr(settings, "content_profiles_dir", FIXTURES_ROOT, raising=False)
    profile = load_content_profile("office-thread-fixture", profiles_dir=FIXTURES_ROOT)
    spoken = "Bảy giờ, Lan mở laptop. Tám rưỡi cậu phải gửi báo cáo cho quản lý."
    staging_description = "Camera pans across a dark wooden desk toward a wall clock at 7:00."
    payload = {
        "ruleset_id": "2026-07-28.1",
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "slug": "canon-check",
        "topic": "t", "title": "t", "description": "d", "tags": [],
        "video_type": "short", "voice_profile": "knowledge",
        "thumbnail_brief": {
            "visual_contradiction": "x", "subject": "y", "emotion": "z", "headline": "h",
        },
        "sections": [
            {
                "purpose": "situation", "time_goal": 0.5,
                "voiceover": spoken, "narration": staging_description,
                "visual_intent": "vi", "speaker_id": "narrator", "visual_asset": "",
                "scene_characters": [], "caption": None, "hook": None,
                "transition": None, "payoff": None, "emphasis": None,
            },
            # Filler sections only to satisfy the fixture profile's
            # min_sections=4 for Short; irrelevant to what this test checks.
            *[
                {
                    "purpose": "application", "time_goal": 0.3,
                    "voiceover": (
                        f"Đoạn thứ {i} này chỉ để đủ độ dài tối thiểu cho Short theo "
                        "hợp đồng thời lượng của profile, hoàn toàn không liên quan "
                        "tới nội dung đang được bài test này kiểm tra ở đây."
                    ),
                    "narration": (
                        f"Đoạn thứ {i} này chỉ để đủ độ dài tối thiểu cho Short theo "
                        "hợp đồng thời lượng của profile, hoàn toàn không liên quan "
                        "tới nội dung đang được bài test này kiểm tra ở đây."
                    ),
                    "visual_intent": "vi", "speaker_id": "narrator", "visual_asset": "",
                    "scene_characters": [], "caption": None, "hook": None,
                    "transition": None, "payoff": None, "emphasis": None,
                }
                for i in range(2, 5)
            ],
        ],
        "compliance": {"passed": True},
        "continuity": {
            "episode_summary": "x", "character_changes": {},
            "threads_opened": [], "threads_closed": [],
        },
    }
    script_path = tmp_path / "canon-check.json"
    script_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    script = load_script(script_path)

    assert script.segments[0].narration == spoken
    assert script.segments[0].narration != staging_description
    assert qa_agent._check_hook_strength(script) == []
