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


def test_builtin_topic_profiles_are_self_contained():
    from ytb_pipeline.content_profiles import load_content_profile

    explainer = load_content_profile("one-cup-cafe-6h")
    story = load_content_profile("ban-so-6")

    assert explainer.providers.render == "ai"
    assert explainer.content_rules.require_pexels_query is True
    assert story.providers.render == "story"
    assert story.content_rules.require_pexels_query is False
    assert story.voice_for("minh") != story.voice_for("an")
    assert "văn nói" in story.prompt_text("spoken_language").casefold()


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
                },
            ],
            "short_videos": [],
        }
    }
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state), encoding="utf-8")

    items = load_queue(path, batch_key="shorts_funnel_batch_profiles")

    assert [item.profile_id for item in items] == ["one-cup-cafe-6h", "ban-so-6"]


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
    assert "pexels_query" not in required
    assert schema["properties"]["profile_id"]["const"] == "ban-so-6"


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
