"""Generation/repair prompts must state the same opening contract the QA
gate (`qa_agent._check_story_hook`) already enforces for every
`narrative_mode == "character_story"` profile.

Before this fix, `script_generation_system_prompt`'s character_story branch
said nothing about the opening at all, and the free-standing `repair_prompt`
only rewrote the hook for a Long explainer-style greeting. A Short character
story could pass duration and still fail QA's hook gate with no prompt ever
having told the model what "anchor" and "stake" mean — exactly what happened
with the real `qwen/qwen3.8-max:free` smoke
(`minh-hoi-dung-mot-cau_20260826_093025_326400.json`).

Every test here uses `office-thread-fixture`, a profile that is NOT
`ban-so-6` and has no Minh/An/coffee-shop content, to prove the fix is
profile-generic rather than tuned to one series.
"""

from __future__ import annotations

from pathlib import Path

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
    from types import SimpleNamespace

    return SimpleNamespace(
        video_type="short",
        target_minutes=None,
        content_profile_id=profile_id,
        content_profile_version=version,
        segments=(SimpleNamespace(narration=opening, purpose="situation"),),
    )


def test_generic_profile_opening_with_anchor_but_no_stake_is_rejected(office_profile):
    """QA behaviour under audit: anchor alone is not enough, on ANY profile."""
    opening = "Bảy giờ, Lan mở laptop và ngồi xuống chiếc bàn quen thuộc cạnh cửa sổ."

    violations = qa_agent._check_hook_strength(
        _script(opening, profile_id=office_profile.profile_id, version=office_profile.version)
    )

    assert [v["rule"] for v in violations] == ["hook"]


def test_generic_profile_opening_with_anchor_and_stake_passes(office_profile):
    opening = "Bảy giờ, Lan mở laptop. Tám rưỡi cậu phải gửi báo cáo cho quản lý."

    assert qa_agent._check_hook_strength(
        _script(opening, profile_id=office_profile.profile_id, version=office_profile.version)
    ) == []


def test_generic_character_story_system_prompt_states_anchor_and_stake_contract(office_profile):
    """The system prompt fed to generation must teach the same contract QA checks.

    Not scoped to `ban-so-6`: this asserts against a distinct profile with a
    different cast and topic to prove the rule is sourced from
    `narrative_mode`, not hardcoded prose about one series.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    prompt = script_generation_system_prompt(office_profile)

    lowered = prompt.lower()
    assert "anchor" in lowered
    assert "stake" in lowered or "deadline" in lowered or "consequence" in lowered
    # Generic contract text — never the other series' names.
    assert "minh" not in lowered
    assert "an đặt" not in lowered


def test_generic_character_story_generation_prompt_states_anchor_and_stake_contract(office_profile):
    """The per-batch user prompt (`local_script_prompt`) must carry the same
    contract, since it is the message that actually names the current cast."""
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(
        1, 1, "short", "auto", "", content_profile=office_profile,
    )

    lowered = prompt.lower()
    assert "anchor" in lowered
    assert "stake" in lowered or "deadline" in lowered or "consequence" in lowered


def test_repair_prompt_uses_anchor_and_stake_contract_for_character_story_hook_violation(
    office_profile,
):
    """A `rule=hook` repair for a character-story Short must not receive the
    Long-only "keep the greeting, add a tension marker" instruction — that
    rule cannot even apply, since a Short never has the greeting."""
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    payload = {
        "video_type": "short",
        "profile_id": office_profile.profile_id,
        "profile_version": office_profile.version,
        "sections": [{"purpose": "situation", "voiceover": "Lan mở laptop."}],
    }
    qa_output = {"violations": [{"rule": "hook", "detail": "missing stake"}]}

    prompt = repair_prompt(payload, qa_output, None)

    lowered = prompt.lower()
    assert "stake" in lowered or "deadline" in lowered or "consequence" in lowered
    assert "anchor" in lowered
    # The Long-only greeting/tension-marker instruction must not leak in.
    assert "keep the required greeting" not in lowered


def test_repair_prompt_keeps_the_long_tension_marker_rule_without_a_profile():
    """Regression: a legacy/no-profile Long repair keeps its old behaviour."""
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    payload = {"video_type": "long"}
    qa_output = {"violations": [{"rule": "hook"}]}

    prompt = repair_prompt(payload, qa_output, None)

    assert "explicit tension marker" in prompt
    assert "keep the required greeting" in prompt.lower()


def test_repair_prompt_preserves_strategy_v1_instead_of_downgrading_to_legacy():
    """Existing regression must still pass unchanged (duration-repair
    mechanism and strategy-v1 preservation are out of scope for this fix)."""
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt(
        {
            "video_type": "short",
            "strategy": {
                "format_id": "core_answer_first_v1",
                "hook": {"core_answer": "Não đang né sự mơ hồ"},
            },
        },
        {"violations": [{"rule": "hook_contract"}]},
        None,
    )

    assert '"strategy"' in prompt
    assert "core_answer" in prompt
