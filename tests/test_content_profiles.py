"""Content profiles are topic folders resolved into the shared pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


def _write_profile(
    root: Path,
    profile_id: str,
    *,
    render_provider: str = "story",
    require_pexels_query: bool = False,
) -> Path:
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "prompts" / "editorial.md").write_text(
        f"Editorial rules for {profile_id}", encoding="utf-8"
    )
    (folder / "prompts" / "spoken-language.md").write_text(
        "Mỗi câu thoại phải trả lời câu ngay trước.", encoding="utf-8"
    )
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": profile_id,
        "topic": f"Topic {profile_id}",
        "narrative_mode": "character_story",
        "prompts": {
            "editorial": "prompts/editorial.md",
            "spoken_language": "prompts/spoken-language.md",
        },
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10},
        },
        "providers": {
            "llm": "xkiro",
            "tts": "xkiro",
            "render": render_provider,
            "broll_strategy": "none" if render_provider == "story" else "pexels",
            "broll_allow_downloads": False,
        },
        "voice_cast": {
            "narrator": "standard-female-vietnamese",
            "minh": "confident-male-vietnamese",
            "an": "sweet-female-vietnamese",
        },
        "content_rules": {
            "require_pexels_query": require_pexels_query,
            "require_short_source_trace": False,
        },
        "render": {
            "assets_dir": "assets",
            "show_captions": True,
            "inter_segment_gap_sec": 0.22,
        },
    }
    (folder / "profile.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return folder


def test_profile_loader_reads_topic_folder_and_prompt_assets(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6")

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.profile_id == "ban-so-6"
    assert profile.topic == "Topic ban-so-6"
    assert profile.format_for("short").viewer_runtime_bounds_sec == (30.0, 45.0)
    assert profile.prompt_text("editorial") == "Editorial rules for ban-so-6"
    assert profile.voice_for("an") == "sweet-female-vietnamese"
    assert profile.assets_dir == tmp_path / "ban-so-6" / "assets"


def test_profile_loader_rejects_traversal_and_identity_mismatch(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6")
    payload_path = tmp_path / "ban-so-6" / "profile.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["profile_id"] = "different-id"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContentProfileError, match="profile_id"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)
    with pytest.raises(ContentProfileError, match="không hợp lệ"):
        load_content_profile("../secrets", profiles_dir=tmp_path)
    payload["profile_id"] = "ban-so-6"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)
    with pytest.raises(ContentProfileError, match="không được đi ra ngoài"):
        profile.visual_asset_path("../profile.json")


def test_builtin_topic_profiles_are_self_contained():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.content_contract import contract_for
    from ytb_pipeline.render.story import expected_story_duration_sec

    explainer = load_content_profile("one-cup-cafe-6h")
    story = load_content_profile("ban-so-6")

    assert explainer.providers.render == "ai"
    assert explainer.content_rules.require_pexels_query is True
    assert story.providers.render == "story"
    assert story.content_rules.require_pexels_query is False
    assert story.content_rules.require_conversation_turns is True
    assert story.voice_for("minh") != story.voice_for("an")
    assert "văn nói" in story.prompt_text("spoken_language").casefold()
    assert "conversation contract" in story.prompt_text("conversation_contract").casefold()
    assert "forbidden in character voiceover" in story.prompt_text("conversation_contract").casefold()
    assert "người dẫn chuyện bắt buộc" in story.prompt_text("conversation_contract").casefold()
    assert story.render.transition_overlap_sec == pytest.approx(0.4)
    assert contract_for("short", story).transition_loss_sec(9) == pytest.approx(0.0)
    assert expected_story_duration_sec(story, [5.0] * 9) == pytest.approx(45.0)


def test_story_profile_requires_turn_cards_for_character_conversation():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    payload = json.loads(
        (Path("profiles/ban-so-6/fixtures/episode-01-short.json")).read_text(encoding="utf-8")
    )
    payload["sections"][1].pop("turn")

    result = validate_script_payload(payload)

    assert not result.publishable
    assert any(finding.rule.endswith("turn.required") for finding in result.findings)


def test_story_system_prompt_includes_declared_series_memory():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    system = script_generation_system_prompt(load_content_profile("ban-so-6"))

    assert "29 tuổi" in system
    assert "chỗ dột" in system
    assert "Bảy lần mở laptop" in system


def test_story_system_prompt_requires_story_pacing_and_real_dialogue():
    """Profile prompts, not global code, own editorial quality requirements."""
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    system = script_generation_system_prompt(load_content_profile("ban-so-6"))
    normalized = " ".join(system.split()).casefold()

    assert "không được kết thúc cao trào rồi nối thêm một bài luận" in normalized
    assert "thoại trực tiếp" in normalized
    assert "người có thể phản hồi" in normalized


def test_queue_loads_profile_and_legacy_item_uses_configured_default(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.orchestrator.queue_manager import load_queue

    monkeypatch.setattr(settings, "content_profile_id", "one-cup-cafe-6h", raising=False)
    state = {
        "shorts_funnel_batch_profiles": {
            "long_videos": [
                {"day": 1, "slug": "legacy", "orientation": "landscape"},
                {
                    "day": 2,
                    "slug": "story",
                    "orientation": "landscape",
                    "profile_id": "ban-so-6",
                    "profile_version": "1.0.0",
                },
            ],
            "short_videos": [],
        }
    }
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state), encoding="utf-8")

    items = load_queue(path, batch_key="shorts_funnel_batch_profiles")

    assert [item.profile_id for item in items] == ["one-cup-cafe-6h", "ban-so-6"]
    assert [item.profile_version for item in items] == ["", "1.0.0"]


def test_batch_environment_is_resolved_from_profile_not_hardcoded(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.orchestrator.pipeline_runner import build_env
    from ytb_pipeline.orchestrator.queue_manager import QueueItem

    _write_profile(tmp_path, "ban-so-6")
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    item = QueueItem(1, "story", "", "queued", "portrait", profile_id="ban-so-6")

    env = build_env(item)

    assert env["CONTENT_PROFILE_ID"] == "ban-so-6"
    assert env["RENDER_PROVIDER"] == "story"
    assert env["BROLL_STRATEGY"] == "none"
    assert env["BROLL_ALLOW_DOWNLOADS"] == "false"
    assert env["SHORT_VIEWER_MIN_SEC"] == "30.0"
    assert env["LONG_VIEWER_MAX_SEC"] == "420.0"


def test_queue_and_explicit_script_profile_must_match(tmp_path):
    from ytb_pipeline.orchestrator.pipeline_runner import validate_queue_profile_binding
    from ytb_pipeline.orchestrator.queue_manager import QueueItem

    path = tmp_path / "story.json"
    path.write_text(json.dumps({
        "profile_id": "ban-so-6", "profile_version": "1.0.0"
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="mismatch"):
        validate_queue_profile_binding(
            QueueItem(
                1, "story", "", "queued", profile_id="one-cup-cafe-6h",
                profile_version="1.0.0",
            ),
            path,
        )


def test_cli_accepts_profile_for_batch_start():
    from ytb_pipeline.orchestrator import batch_cli as cli

    names = (
        "start", "status", "run", "verify", "retry", "logs", "ledger", "queue",
        "analytics", "reconcile", "ps", "reset", "cancel", "stop", "doctor",
        "auth", "benchmark-local", "preflight",
    )
    parser = cli.build_parser(doc="test", cmd_funcs={name: (lambda _args: None) for name in names})

    args = parser.parse_args(["start", "-n", "1", "--profile", "ban-so-6"])

    assert args.profile_id == "ban-so-6"


def test_profile_prompt_replaces_channel_hardcode_and_static_six_section_budget(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    _write_profile(tmp_path, "ban-so-6")
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    prompt = local_script_prompt(1, 1, "short", "auto", "", content_profile=profile)

    assert "Editorial rules for ban-so-6" in prompt
    assert "exactly six sections" not in prompt
    assert "550-700" not in prompt
    assert "Use exactly 4 sections" in prompt
    assert "grounded Pexels queries" not in prompt


def test_custom_story_idea_keeps_profile_voice_instead_of_old_knowledge_channel_rules():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(
        1, 1, "short", "Minh ngại gửi bản nháp", "",
        content_profile=load_content_profile("ban-so-6"),
    )

    assert "not entertainment" not in prompt
    assert "knowledge Short" not in prompt
    assert "Minh ngại gửi bản nháp" in prompt


def test_story_prompt_names_the_cast_for_scene_characters_when_auto_generating():
    """ban-so-6 has visual_generation enabled: the model names WHO is on
    screen (scene_characters), not a fixed filename."""
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    profile = load_content_profile("ban-so-6")
    prompt = local_script_prompt(
        1, 1, "short", "auto", "", content_profile=profile
    )

    assert "scene_characters" in prompt
    assert "'minh'" in prompt or "minh" in prompt
    assert "Use only these visual_asset filenames" not in prompt


def test_story_prompt_requires_complete_long_arc_and_single_speaker_turns():
    """Profile generation cannot contradict the shared release contract.

    A story Long still needs an evidence beat; its evidence may be an observed
    consequence in the scene rather than a forced research claim.  And because
    speaker_id selects one TTS voice, one character section cannot also narrate
    action or another character's reply.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import script_generation_system_prompt

    prompt = script_generation_system_prompt(load_content_profile("ban-so-6"))

    assert "situation, core_answer, evidence, application, payoff" in prompt
    assert "exactly that character's spoken utterance" in prompt


def test_story_prompt_lists_only_assets_available_in_the_profile(tmp_path):
    """A character_story profile WITHOUT auto-generation still gets the
    fixed-filename whitelist instruction."""
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt
    from tests.test_visual_generation_profile import _write_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=None)
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)
    prompt = local_script_prompt(
        1, 1, "short", "auto", "", content_profile=profile
    )

    assert "Use only these visual_asset filenames" in prompt


def test_generation_schema_follows_profile_section_and_visual_contract(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.ideation.generation_schema import script_generation_schema

    _write_profile(tmp_path, "ban-so-6")
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    schema = script_generation_schema("short", content_profile=profile)
    sections = schema["properties"]["sections"]
    required = sections["items"]["required"]

    assert sections["minItems"] == 4
    assert sections["maxItems"] == 4
    assert "speaker_id" in sections["items"]["properties"]
    assert "visual_asset" in sections["items"]["properties"]
    assert sections["items"]["properties"]["speaker_id"]["enum"] == [
        "an", "minh", "narrator"
    ]
    assert "pexels_query" not in required
    assert schema["properties"]["profile_id"]["const"] == "ban-so-6"


def test_release_contract_fails_closed_on_profile_version_cast_and_section_cap():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    fixture = Path("profiles/ban-so-6/fixtures/episode-01-short.json")
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    without_version = dict(payload)
    without_version.pop("profile_version")
    assert "profile.version_required" in {
        finding.rule for finding in validate_script_payload(without_version).findings
    }

    bad_cast = json.loads(json.dumps(payload))
    bad_cast["sections"][1]["speaker_id"] = "minhh"
    assert "sections[1].speaker_id.in_voice_cast" in {
        finding.rule for finding in validate_script_payload(bad_cast).findings
    }

    too_many = json.loads(json.dumps(payload))
    while len(too_many["sections"]) <= 12:
        too_many["sections"].append(dict(too_many["sections"][2]))
    assert "sections.maximum_count" in {
        finding.rule for finding in validate_script_payload(too_many).findings
    }


def test_loader_rejects_explicit_profile_without_version_and_too_many_sections(tmp_path):
    from ytb_pipeline.ideation.generator import load_script

    fixture = Path("profiles/ban-so-6/fixtures/episode-01-short.json")
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload.pop("profile_version")
    path = tmp_path / "missing-version.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="profile_version"):
        load_script(path)

    from ytb_pipeline.content_profiles import load_content_profile

    payload["profile_version"] = load_content_profile("ban-so-6").version
    while len(payload["sections"]) <= 12:
        payload["sections"].append(dict(payload["sections"][2]))
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="tối đa 12"):
        load_script(path)


def test_profile_loader_rejects_string_booleans_nonfinite_numbers_and_dialogue_overlap(
    tmp_path,
):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    folder = _write_profile(tmp_path, "strict-profile")
    config_path = folder / "profile.json"
    base = json.loads(config_path.read_text(encoding="utf-8"))

    invalid_cases = (
        lambda raw: raw["render"].update({"show_captions": "false"}),
        lambda raw: raw["render"].update({"inter_segment_gap_sec": float("nan")}),
        lambda raw: raw["render"].update(
            {"inter_segment_gap_sec": 0.1, "transition_overlap_sec": 0.4}
        ),
    )
    for mutate in invalid_cases:
        raw = json.loads(json.dumps(base))
        mutate(raw)
        config_path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ContentProfileError):
            load_content_profile("strict-profile", profiles_dir=tmp_path)


def test_profile_loader_uses_profile_tts_for_runtime_estimation(monkeypatch):
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.ideation import generator
    from ytb_pipeline.pkg.models import Segment

    profile = load_content_profile("ban-so-6")
    calls: list[tuple[str | None, str | None]] = []

    def calibrated(provider=None, *, video_type=None):
        calls.append((provider, video_type))
        return 1030.0

    monkeypatch.setattr(generator, "chars_per_min_for_provider", calibrated)
    segments = tuple(Segment("", "x" * 190) for _ in range(4))

    generator._validate_length(
        segments,
        None,
        "profile.json",
        renderer_aware=True,
        content_profile=profile,
    )

    assert calls == [("xkiro", "short")]


def test_story_short_normalizer_derives_budget_from_declared_profile():
    from ytb_pipeline.content_contract import chars_per_min_for_provider, contract_for
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_script_fix import (
        normalize_short_narration,
        short_narration_chars,
    )

    profile = load_content_profile("ban-so-6")
    payload = {
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "video_type": "short",
        "sections": [
            {"purpose": purpose, "voiceover": "Một câu kể tự nhiên. " * 12}
            for purpose in ("situation", "core_answer", "application", "payoff")
        ],
    }
    absolute_max = int(
        chars_per_min_for_provider(profile.providers.tts, video_type="short")
        * contract_for("short", profile).audio_runtime_bounds_sec(segment_count=4)[1]
        / 60
    )

    fixed, note = normalize_short_narration(payload, expected_video_type="short")

    assert note is not None
    assert short_narration_chars(fixed) <= absolute_max


def test_repair_followup_uses_declared_profile_system_prompt():
    from ytb_pipeline.orchestrator.ideation_script_fix import repair_system_prompt

    system = repair_system_prompt({
        "profile_id": "ban-so-6", "profile_version": "1.0.0"
    })

    assert "Bàn số 6" in system
    assert "chỗ dột" in system


def test_story_script_loads_profile_speaker_and_visual_asset(tmp_path, write_script, monkeypatch):
    from conftest import chars_for_minutes, passing_compliance
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.ideation.generator import load_script

    profiles = tmp_path / "profiles"
    _write_profile(profiles, "ban-so-6")
    monkeypatch.setattr(settings, "content_profiles_dir", profiles, raising=False)
    narration = chars_for_minutes(0.14)
    sections = [
        {
            "purpose": purpose,
            "time_goal": 0.15,
            "voiceover": narration,
            "visual_intent": "Minh ở bàn số 6",
            "visual_asset": "opening.png",
            "speaker_id": speaker,
            "caption": "",
            "hook": False,
            "transition": None,
            "payoff": None,
            "emphasis": None,
        }
        for purpose, speaker in (
            ("situation", "narrator"),
            ("core_answer", "minh"),
            ("application", "an"),
            ("payoff", "narrator"),
        )
    ]
    path = write_script({
        "ruleset_id": "2026-07-28.1",
        "profile_id": "ban-so-6",
        "profile_version": "1.0.0",
        "video_type": "short",
        "title": "Bàn số 6",
        "topic": "Một bản nháp chưa hoàn chỉnh",
        "description": "d",
        "tags": [],
        "voice_profile": "knowledge",
        "thumbnail_brief": {
            "visual_contradiction": "giấy kín chữ nhưng file trống",
            "subject": "Minh",
            "emotion": "do dự",
            "headline": "File Vẫn Trống",
        },
        "sections": sections,
        "compliance": passing_compliance(),
    })

    script = load_script(path)

    assert script.content_profile_id == "ban-so-6"
    assert script.content_profile_version == "1.0.0"
    assert [segment.speaker_id for segment in script.segments] == [
        "narrator", "minh", "an", "narrator"
    ]
    assert script.segments[0].visual_asset == "opening.png"


def test_effective_chars_per_min_applies_the_profile_pace_factor(tmp_path):
    from ytb_pipeline.content_contract import chars_per_min_for_provider, effective_chars_per_min
    from ytb_pipeline.content_profiles import load_content_profile
    import json

    folder = _write_profile(tmp_path, "ban-so-6")
    payload = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    payload["providers"]["tts_pace_factor"] = 0.9
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    base = chars_per_min_for_provider("xkiro", video_type="long")
    adjusted = effective_chars_per_min("xkiro", video_type="long", content_profile=profile)

    assert adjusted == pytest.approx(base * 0.9)


def test_effective_chars_per_min_without_profile_is_unchanged():
    from ytb_pipeline.content_contract import chars_per_min_for_provider, effective_chars_per_min

    assert effective_chars_per_min("xkiro", video_type="long") == chars_per_min_for_provider(
        "xkiro", video_type="long"
    )


def test_loader_duration_estimate_honors_the_content_profile_tts_pace():
    """Ideation admission and preflight must estimate story audio identically."""
    from types import SimpleNamespace

    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.ideation.generator import estimate_minutes

    segments = [SimpleNamespace(narration="x" * 5_100)]
    profile = load_content_profile("ban-so-6")

    profile_minutes = estimate_minutes(
        segments, tts_provider="xkiro", video_type="long", content_profile=profile
    )
    generic_minutes = estimate_minutes(segments, tts_provider="xkiro", video_type="long")

    assert profile_minutes > generic_minutes
