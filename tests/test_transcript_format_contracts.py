"""Engine-level contracts for the three supported transcript formats.

These tests deliberately use a disposable profile and cast.  The production
engine must learn the format from profile data, never from a series name.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def _write_story_profile(root):
    profile_id = "office-thread-fixture"
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "prompts" / "editorial.md").write_text("Core editorial rules.", encoding="utf-8")
    (folder / "prompts" / "long-structure.md").write_text(
        "STORY_LONG_STRUCTURE: narrator opens stakes; main and supporting character "
        "have a causal conversation; narrator closes the lesson and next-episode bridge.",
        encoding="utf-8",
    )
    (folder / "prompts" / "short-structure.md").write_text(
        "STORY_SHORT_STRUCTURE: this legacy format must never be generated.", encoding="utf-8"
    )
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": "Generic office story",
        "topic": "Generic story topic",
        "narrative_mode": "character_story",
        "prompts": {
            "editorial": "prompts/editorial.md",
            "long_structure": "prompts/long-structure.md",
            "short_structure": "prompts/short-structure.md",
        },
        "format_prompts": {"long": "long_structure", "short": "short_structure"},
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10},
        },
        "providers": {
            "llm": "xkiro", "tts": "xkiro", "render": "story",
            "broll_strategy": "none", "broll_allow_downloads": False,
        },
        "voice_cast": {
            "narrator": "voice-narrator", "primary": "voice-primary", "supporting": "voice-supporting",
        },
        "content_rules": {
            "require_pexels_query": False,
            "require_short_source_trace": False,
            "require_conversation_turns": True,
            "allow_short_generation": False,
            "story_primary_speaker_id": "primary",
            "story_supporting_speaker_id": "supporting",
            "require_next_episode_bridge": True,
        },
        "render": {
            "assets_dir": "assets", "show_captions": True,
            "inter_segment_gap_sec": 0.4, "transition_overlap_sec": 0.4, "scene_assets": [],
        },
    }
    (folder / "profile.json").write_text(json.dumps(payload), encoding="utf-8")
    return profile_id


def test_profile_format_contract_scopes_system_prompt_and_disables_story_shorts(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile
    from ytb_pipeline.ideation.generation_schema import script_generation_schema
    from ytb_pipeline.orchestrator.ideation_prompts import (
        local_script_prompt,
        script_generation_system_prompt,
    )

    profile = load_content_profile(_write_story_profile(tmp_path), profiles_dir=tmp_path)

    assert profile.supports_generation("long") is True
    assert profile.supports_generation("short") is False

    prompt = script_generation_system_prompt(profile, video_type="long")

    assert "STORY_LONG_STRUCTURE" in prompt
    assert "STORY_SHORT_STRUCTURE" not in prompt
    assert "primary speaker_id is \"primary\"" in prompt
    assert "supporting speaker_id is \"supporting\"" in prompt

    with pytest.raises(ContentProfileError, match="không cho sinh short"):
        local_script_prompt(1, 1, "short", "auto", "", content_profile=profile)
    with pytest.raises(ValueError, match="không cho sinh short"):
        script_generation_schema("short", content_profile=profile)


def test_story_long_contract_does_not_leak_into_short_or_legacy_closing(tmp_path):
    """A role-heavy Long profile may still offer a small, independent Short.

    The generation prompt has to follow both the requested format and the
    opt-in narrator-lesson rule; otherwise it asks a Short to satisfy the
    Long's three-role arc, or asks a legacy Long to pass the wrong QA ending.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import (
        local_script_prompt,
        script_generation_system_prompt,
    )

    profile_id = _write_story_profile(tmp_path)
    profile_path = tmp_path / profile_id / "profile.json"
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    raw["content_rules"]["allow_short_generation"] = True
    # narrator_lesson_closing is deliberately absent: this is a legacy story
    # ending, which QA evaluates as a bounded action plus its declared bridge.
    profile_path.write_text(json.dumps(raw), encoding="utf-8")
    profile = load_content_profile(profile_id, profiles_dir=tmp_path)

    long_prompt = script_generation_system_prompt(profile, video_type="long")
    assert 'primary speaker_id is "primary"' in long_prompt
    assert "concrete bounded action" in long_prompt
    assert "next episode will examine" in long_prompt
    assert "STORY_LESSON_BRIDGE" not in long_prompt

    short_prompt = script_generation_system_prompt(profile, video_type="short")
    local_short_prompt = local_script_prompt(
        1, 1, "short", "auto", "", content_profile=profile,
    )
    for prompt in (short_prompt, local_short_prompt):
        assert 'primary speaker_id is "primary"' not in prompt
        assert "concrete bounded action" not in prompt


def test_story_series_qa_requires_both_roles_narrator_lesson_and_next_episode(tmp_path, monkeypatch):
    from ytb_pipeline.agents import qa_agent
    from ytb_pipeline.content_profiles import load_content_profile

    profile_id = _write_story_profile(tmp_path)
    profile = load_content_profile(profile_id, profiles_dir=tmp_path)
    monkeypatch.setattr(qa_agent, "load_content_profile", lambda _profile_id: profile)
    script = SimpleNamespace(
        content_profile_id=profile_id,
        content_profile_version="1.0.0",
        video_type="long",
        segments=[
            SimpleNamespace(speaker_id="narrator", narration="Bảy giờ, bản báo cáo chưa được gửi."),
            SimpleNamespace(speaker_id="primary", narration="Tôi sợ gửi bản nháp rồi bị chê."),
            SimpleNamespace(speaker_id="supporting", narration="Cậu muốn người ta góp ý điều gì trước?"),
            SimpleNamespace(
                speaker_id="narrator",
                narration="Bạn không cần chờ hết sợ mới cho người khác thấy bản nháp. Tập sau, chúng ta xem một góp ý nhỏ có thể đổi cuộc nói chuyện ra sao.",
            ),
        ],
    )

    assert qa_agent._check_story_series_arc(script) == []

    script.segments[-1].narration = "Bạn không cần chờ hết sợ mới cho người khác thấy bản nháp."
    violations = qa_agent._check_story_series_arc(script)
    assert {item["rule"] for item in violations} == {"story_series_next_episode"}


def test_short_funnel_structure_is_selected_without_leaking_long_structure(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    folder = tmp_path / "explainer-fixture"
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    for name, text in {
        "editorial.md": "Core editorial rules.",
        "long.md": "EXPLAINER_LONG_STRUCTURE: pain, symptoms, cause, handling.",
        "short.md": "FUNNEL_SHORT_STRUCTURE: pain, question, bridge to the Long.",
    }.items():
        (folder / "prompts" / name).write_text(text, encoding="utf-8")
    payload = {
        "schema_version": 1, "profile_id": "explainer-fixture", "version": "1.0.0",
        "display_name": "Explainer", "topic": "Generic", "narrative_mode": "mechanism_explainer",
        "prompts": {"editorial": "prompts/editorial.md", "long_structure": "prompts/long.md", "short_structure": "prompts/short.md"},
        "format_prompts": {"long": "long_structure", "short": "short_structure"},
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10},
        },
        "providers": {"llm": "xkiro", "tts": "xkiro", "render": "ai", "broll_strategy": "pexels", "broll_allow_downloads": False},
        "voice_cast": {"narrator": "voice-narrator"},
        "content_rules": {
            "require_pexels_query": True,
            "require_short_source_trace": True,
            "long_opening_mode": "pain_first",
            "short_ending_mode": "funnel_bridge",
        },
        "render": {"assets_dir": "assets", "show_captions": False, "inter_segment_gap_sec": 0.0, "transition_overlap_sec": 0.4, "scene_assets": []},
    }
    (folder / "profile.json").write_text(json.dumps(payload), encoding="utf-8")
    profile = load_content_profile("explainer-fixture", profiles_dir=tmp_path)

    prompt = script_generation_system_prompt(profile, video_type="short")

    assert "FUNNEL_SHORT_STRUCTURE" in prompt
    assert "EXPLAINER_LONG_STRUCTURE" not in prompt
    assert "SHORT ENDING MODE: FUNNEL_BRIDGE" in prompt

    long_prompt = script_generation_system_prompt(profile, video_type="long")
    assert "OPENING MODE: PAIN_FIRST" in long_prompt
    assert "CLOSING MODE: FINAL_ACTION" in long_prompt
    assert "Mến chào các bạn" not in long_prompt


def test_funnel_short_uses_a_verified_long_bridge_instead_of_a_final_imperative(
    tmp_path, monkeypatch,
):
    """A funnel profile earns its ending by pointing to the declared Long."""
    from ytb_pipeline.agents import qa_agent

    profile_id = _write_story_profile(tmp_path)
    profile_path = tmp_path / profile_id / "profile.json"
    profile_raw = json.loads(profile_path.read_text(encoding="utf-8"))
    profile_raw["narrative_mode"] = "mechanism_explainer"
    profile_raw["content_rules"] = {
        "require_pexels_query": True,
        "require_short_source_trace": True,
        "short_ending_mode": "funnel_bridge",
    }
    profile_path.write_text(json.dumps(profile_raw), encoding="utf-8")
    from ytb_pipeline.content_profiles import load_content_profile

    profile = load_content_profile(profile_id, profiles_dir=tmp_path)
    script = SimpleNamespace(
        video_type="short",
        target_minutes=None,
        strategy=SimpleNamespace(
            long_form_slug="long-topic",
            cta_target="long-topic",
            source_long_slug="long-topic",
        ),
        segments=(SimpleNamespace(
            narration="Xem tiếp video dài để hiểu phần triệu chứng và cách xử lý.",
        ),),
    )
    monkeypatch.setattr(qa_agent, "_content_profile", lambda _script: profile)

    assert qa_agent._check_immediate_action(script) == []

    script.strategy.cta_target = "another-long"
    assert [item["rule"] for item in qa_agent._check_immediate_action(script)] == ["funnel_bridge"]


def test_story_profile_runtime_tolerance_is_shared_with_qa_length_gate(monkeypatch):
    """A tiny calibrated estimate miss must not buy another LLM rewrite.

    The profile declares this tolerance because it was measured for its
    multi-voice TTS; the engine must use the same effective rate in QA as it
    did when it admitted the transcript.
    """
    from ytb_pipeline.agents import qa_agent
    from ytb_pipeline.content_contract import contract_for
    from ytb_pipeline.content_profiles import load_content_profile

    profile = load_content_profile("ban-so-6")
    contract = contract_for("long", profile)
    assert profile.format_for("long").runtime_tolerance_sec == 3.0
    contract.validate_audio_runtime(297.5, segment_count=1)
    with pytest.raises(ValueError, match="Long quá ngắn"):
        contract.validate_audio_runtime(296.9, segment_count=1)

    script = SimpleNamespace(
        video_type="long",
        target_minutes=5,
        ruleset_id="2026-07-28.1",
        segments=(SimpleNamespace(narration="x" * 5076),),
    )
    monkeypatch.setattr(qa_agent, "_content_profile", lambda _script: profile)
    assert qa_agent._check_length(script) == []
