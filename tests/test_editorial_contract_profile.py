"""Purpose vocabulary/required-purposes must be declared by the profile, not
hardcoded in core for one narrative taxonomy (mechanism explainer).

`ban-so-6` and `one-cup-cafe-6h` are both real profiles that predate this
field, so a v1 `profile.json` with no `editorial_contract` key must still load
and behave exactly as it did before (legacy explainer vocabulary/required
purposes). A brand-new profile with its own vocabulary must not need any
pipeline code change to work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytb_pipeline.content_profiles import (
    ContentProfileError,
    load_content_profile,
)


def _base_payload(profile_id: str, *, narrative_mode: str = "panel_debate") -> dict:
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": profile_id,
        "topic": f"Topic {profile_id}",
        "narrative_mode": narrative_mode,
        "prompts": {"editorial": "prompts/editorial.md"},
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 3},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 6},
        },
        "providers": {
            "llm": "xkiro",
            "tts": "xkiro",
            "render": "slide",
            "broll_strategy": "none",
            "broll_allow_downloads": False,
        },
        "voice_cast": {"narrator": "standard-female-vietnamese"},
        "content_rules": {
            "require_pexels_query": False,
            "require_short_source_trace": False,
        },
        "render": {
            "assets_dir": "assets",
            "show_captions": True,
            "inter_segment_gap_sec": 0.2,
            "transition_overlap_sec": 0.0,
        },
    }


def _write_profile(root: Path, profile_id: str, payload: dict) -> Path:
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "prompts" / "editorial.md").write_text(
        f"Editorial rules for {profile_id}", encoding="utf-8"
    )
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return folder


PANEL_VOCABULARY = ("cold_open", "claim", "rebuttal", "synthesis")
PANEL_REQUIRED = {
    "short": ["cold_open", "claim"],
    "long": ["cold_open", "claim", "rebuttal", "synthesis"],
}


def _panel_payload(profile_id: str = "panel-debate-fixture") -> dict:
    payload = _base_payload(profile_id)
    payload["editorial_contract"] = {
        "purpose_vocabulary": list(PANEL_VOCABULARY),
        "required_purposes": {key: list(value) for key, value in PANEL_REQUIRED.items()},
    }
    return payload


def test_v1_profile_without_editorial_contract_gets_legacy_explainer_vocabulary(tmp_path):
    """A profile.json predating this field must load unchanged (compat)."""
    _write_profile(tmp_path, "legacy-profile", _base_payload("legacy-profile"))

    profile = load_content_profile("legacy-profile", profiles_dir=tmp_path)

    assert profile.editorial_contract.purpose_policy.vocabulary == (
        "situation", "core_answer", "evidence", "application", "payoff",
    )
    assert profile.editorial_contract.purpose_policy.required_for("short") == (
        "situation", "core_answer", "application", "payoff",
    )
    assert profile.editorial_contract.purpose_policy.required_for("long") == (
        "situation", "core_answer", "evidence", "application", "payoff",
    )
    assert profile.editorial_contract.narration_speaker_id == "narrator"


def test_second_profile_declares_its_own_purpose_vocabulary_with_no_pipeline_change(tmp_path):
    """A non-explainer, non-story profile is a first-class citizen."""
    _write_profile(tmp_path, "panel-debate-fixture", _panel_payload())

    profile = load_content_profile("panel-debate-fixture", profiles_dir=tmp_path)

    assert profile.editorial_contract.purpose_policy.vocabulary == PANEL_VOCABULARY
    assert profile.editorial_contract.purpose_policy.required_for("short") == ("cold_open", "claim")
    assert profile.editorial_contract.purpose_policy.required_for("long") == (
        "cold_open", "claim", "rebuttal", "synthesis",
    )


def test_required_purpose_outside_vocabulary_fails_closed(tmp_path):
    payload = _panel_payload("bad-panel-fixture")
    payload["editorial_contract"]["required_purposes"]["short"] = ["cold_open", "not_in_vocab"]
    _write_profile(tmp_path, "bad-panel-fixture", payload)

    with pytest.raises(ContentProfileError):
        load_content_profile("bad-panel-fixture", profiles_dir=tmp_path)


def test_empty_purpose_vocabulary_fails_closed(tmp_path):
    payload = _panel_payload("empty-vocab-fixture")
    payload["editorial_contract"]["purpose_vocabulary"] = []
    _write_profile(tmp_path, "empty-vocab-fixture", payload)

    with pytest.raises(ContentProfileError):
        load_content_profile("empty-vocab-fixture", profiles_dir=tmp_path)


def test_generation_schema_enforces_the_profile_purpose_vocabulary(tmp_path):
    """A custom profile must never be forced through the explainer enum."""
    from ytb_pipeline.ideation.generation_schema import script_generation_schema

    _write_profile(tmp_path, "panel-debate-fixture", _panel_payload())
    profile = load_content_profile("panel-debate-fixture", profiles_dir=tmp_path)

    schema = script_generation_schema("long", content_profile=profile)
    purpose_enum = schema["properties"]["sections"]["items"]["properties"]["purpose"]["enum"]

    assert purpose_enum == list(PANEL_VOCABULARY)
    assert "situation" not in purpose_enum
    assert "core_answer" not in purpose_enum


def test_generation_schema_without_profile_keeps_the_legacy_enum():
    from ytb_pipeline.ideation.generation_schema import script_generation_schema

    schema = script_generation_schema("long")
    purpose_enum = schema["properties"]["sections"]["items"]["properties"]["purpose"]["enum"]

    assert purpose_enum == [
        "situation", "core_answer", "evidence", "application", "payoff",
    ]


def _panel_script_payload(profile, *, purposes) -> dict:
    """Minimal current-ruleset payload with the given section purposes."""
    from ytb_pipeline.content_contract import CONTRACT_VERSION

    return {
        "ruleset_id": CONTRACT_VERSION,
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "slug": "panel-ep1",
        "topic": "topic",
        "title": "title",
        "description": "desc",
        "tags": [],
        "video_type": "long",
        "target_minutes": 6,
        "voice_profile": "knowledge",
        "thumbnail_brief": {
            "visual_contradiction": "x", "subject": "y", "emotion": "z", "headline": "h",
        },
        "sections": [
            {
                "purpose": purpose, "time_goal": 1.0, "voiceover": "Noi dung " * 5,
                "visual_intent": "vi", "caption": None, "hook": None,
                "transition": None, "payoff": None, "emphasis": None,
            }
            for purpose in purposes
        ],
        "compliance": {"passed": True},
    }


def test_release_purpose_gate_uses_the_profile_vocabulary_not_the_legacy_one(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_release_purposes

    _write_profile(tmp_path, "panel-debate-fixture", _panel_payload())
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    profile = load_content_profile("panel-debate-fixture", profiles_dir=tmp_path)
    payload = _panel_script_payload(profile, purposes=["cold_open", "claim"])
    with pytest.raises(ValueError) as excinfo:
        validate_release_purposes(payload)
    message = str(excinfo.value)
    assert "rebuttal" in message
    assert "synthesis" in message
    assert "situation" not in message
    assert "evidence" not in message


def test_system_prompt_states_the_profiles_own_required_purposes(tmp_path):
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    _write_profile(tmp_path, "panel-debate-fixture", _panel_payload())
    profile = load_content_profile("panel-debate-fixture", profiles_dir=tmp_path)

    prompt = script_generation_system_prompt(profile)

    assert "cold_open" in prompt
    assert "rebuttal" in prompt
    assert "synthesis" in prompt
    assert "situation, core_answer, evidence, application, payoff" not in prompt


def test_system_prompt_does_not_force_strategy_v1_when_profile_does_not_require_it(tmp_path):
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    _write_profile(tmp_path, "panel-debate-fixture", _panel_payload())
    profile = load_content_profile("panel-debate-fixture", profiles_dir=tmp_path)

    prompt = script_generation_system_prompt(profile)

    assert "core_answer_first_v1" not in prompt
    assert "strategy-v1 is mandatory" not in prompt
    assert "Every section must include a grounded pexels_query" not in prompt


def test_system_prompt_still_requires_strategy_v1_when_profile_declares_it(tmp_path):
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    payload = _panel_payload()
    payload["content_rules"]["require_short_source_trace"] = True
    payload["content_rules"]["require_pexels_query"] = True
    _write_profile(tmp_path, "panel-debate-fixture", payload)
    profile = load_content_profile("panel-debate-fixture", profiles_dir=tmp_path)

    prompt = script_generation_system_prompt(profile)

    assert "core_answer_first_v1" in prompt
    assert "pexels_query" in prompt


def _story_panel_payload(profile_id: str = "story-panel-fixture") -> dict:
    """character_story narrative mode combined with a custom purpose policy,
    proving auto_visuals/turn gating and purpose policy compose independently."""
    payload = _base_payload(profile_id, narrative_mode="character_story")
    payload["voice_cast"] = {
        "narrator": "standard-female-vietnamese",
        "hostA": "confident-male-vietnamese",
        "hostB": "sweet-female-vietnamese",
    }
    payload["content_rules"]["require_conversation_turns"] = True
    payload["editorial_contract"] = {
        "purpose_vocabulary": list(PANEL_VOCABULARY),
        "required_purposes": {key: list(value) for key, value in PANEL_REQUIRED.items()},
    }
    return payload


def test_long_extension_prompt_follows_profile_speaker_and_turn_policy_not_pexels(tmp_path):
    from ytb_pipeline.orchestrator.ideation_prompts import long_extension_prompt

    _write_profile(tmp_path, "story-panel-fixture", _story_panel_payload())
    profile = load_content_profile("story-panel-fixture", profiles_dir=tmp_path)

    payload = {
        "slug": "s", "topic": "t", "title": "ti", "description": "d", "tags": [],
        "voice_profile": "knowledge", "compliance": {},
        "sections": [
            {"purpose": "cold_open", "voiceover": "a"},
            {"purpose": "synthesis", "voiceover": "b"},
        ],
    }
    prompt = long_extension_prompt(payload, 500, content_profile=profile)

    assert "speaker_id" in prompt
    assert "turn" in prompt
    assert "pexels_query" not in prompt


def test_long_extension_prompt_without_profile_keeps_legacy_pexels_field():
    from ytb_pipeline.orchestrator.ideation_prompts import long_extension_prompt

    payload = {
        "slug": "s", "topic": "t", "title": "ti", "description": "d", "tags": [],
        "voice_profile": "knowledge", "compliance": {},
        "sections": [{"purpose": "situation", "voiceover": "a"}, {"purpose": "payoff", "voiceover": "b"}],
    }
    prompt = long_extension_prompt(payload, 500)

    assert "pexels_query" in prompt


def test_on_disk_second_profile_loads_and_never_mentions_the_other_profiles():
    """Prove a real profile directory works with zero pipeline code changes.

    This loads the checked-in test fixture `panel-debate-fixture` — a
    narrative_mode the pipeline has never seen — through the exact same
    `load_content_profile`/`script_generation_system_prompt` call path used
    for `ban-so-6` and `one-cup-cafe-6h` in production.
    """
    fixtures_root = Path(__file__).parent / "fixtures" / "content_profiles"
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    profile = load_content_profile("panel-debate-fixture", profiles_dir=fixtures_root)
    prompt = script_generation_system_prompt(profile)

    for leaked_identity in ("Minh", "An", "Bàn số 6", "core_answer_first_v1", "Hãy "):
        assert leaked_identity not in prompt
    assert "cold_open" in prompt
    assert profile.editorial_contract.purpose_policy.vocabulary == PANEL_VOCABULARY
