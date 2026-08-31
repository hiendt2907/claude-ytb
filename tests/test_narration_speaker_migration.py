"""A profile may declare a narration speaker id other than the "narrator"
sentinel via `editorial_contract.narration_speaker_id`.

Every consumer that filters/compares against the cast's narration role must
read that declared id instead of the literal string "narrator" — otherwise a
profile that renamed its narrator (e.g. "host") would have its narration
segments treated as a cast member by QA/schema/render.

`ban-so-6` and `one-cup-cafe-6h` never declare this field, so their behaviour
must be provably unchanged (default stays "narrator").
"""

from __future__ import annotations

import json
from pathlib import Path

from ytb_pipeline.content_profiles import load_content_profile


def _write_host_profile(root: Path, profile_id: str = "host-story-fixture") -> Path:
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets" / "identity").mkdir(parents=True)
    (folder / "prompts" / "editorial.md").write_text("Editorial rules.", encoding="utf-8")
    (folder / "prompts" / "spoken-language.md").write_text(
        "Mỗi câu thoại phải trả lời câu ngay trước.", encoding="utf-8"
    )
    (folder / "assets" / "identity" / "guest.png").write_bytes(b"fake-png")
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": profile_id,
        "topic": "Topic",
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
            "llm": "xkiro", "tts": "xkiro", "render": "story",
            "broll_strategy": "none", "broll_allow_downloads": False,
        },
        # "host" plays the narration role here instead of the "narrator" sentinel.
        "voice_cast": {
            "host": "standard-female-vietnamese",
            "guest": "confident-male-vietnamese",
        },
        "content_rules": {
            "require_pexels_query": False,
            "require_short_source_trace": False,
            "require_conversation_turns": True,
        },
        "render": {
            "assets_dir": "assets",
            "show_captions": True,
            "inter_segment_gap_sec": 0.4,
            "transition_overlap_sec": 0.2,
        },
        "visual_generation": {
            "enabled": True,
            "style_prompt": "style",
            "negative_prompt": "negative",
            "steps": 20,
            "cfg": 6.0,
            "solo_weight": 0.4,
            "duo_weight": 0.3,
            "duo_denoise": 0.5,
            "characters": {"guest": "identity/guest.png"},
            "duo_reference_image": "",
        },
        "editorial_contract": {
            "narration_speaker_id": "host",
        },
    }
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return folder


def test_profile_declares_a_non_default_narration_speaker_id(tmp_path):
    _write_host_profile(tmp_path)
    profile = load_content_profile("host-story-fixture", profiles_dir=tmp_path)

    assert profile.editorial_contract.narration_speaker_id == "host"
    assert profile.voice_for(None) == profile.voice_for("host")


def test_default_v1_profile_keeps_the_narrator_sentinel(tmp_path):
    """ban-so-6-shaped fixture, no editorial_contract override: unchanged."""
    from tests.test_visual_generation_profile import _write_profile

    _write_profile(tmp_path, "ban-so-6")
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.editorial_contract.narration_speaker_id == "narrator"


def test_render_speaker_colour_uses_the_declared_narration_id_not_the_cast(tmp_path):
    from ytb_pipeline.render.story import speaker_colour, _NARRATOR_COLOUR

    _write_host_profile(tmp_path)
    profile = load_content_profile("host-story-fixture", profiles_dir=tmp_path)

    # "host" must resolve as the narrator colour, not be looked up in the cast
    # (it would raise/misindex if the function still filtered on "narrator").
    assert speaker_colour(profile, "host") == _NARRATOR_COLOUR
    assert speaker_colour(profile, "guest") != _NARRATOR_COLOUR


def test_scene_characters_validation_rejects_the_declared_narration_id_as_a_cast_member(
    tmp_path, monkeypatch,
):
    from ytb_pipeline.ideation.script_contract import validate_script_payload
    from ytb_pipeline.content_contract import CONTRACT_VERSION
    from ytb_pipeline.config.settings import settings

    _write_host_profile(tmp_path)
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    profile = load_content_profile("host-story-fixture", profiles_dir=tmp_path)

    payload = {
        "ruleset_id": CONTRACT_VERSION,
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "slug": "s", "topic": "t", "title": "ti", "description": "d", "tags": [],
        "video_type": "long", "target_minutes": 6, "voice_profile": "knowledge",
        "thumbnail_brief": {"visual_contradiction": "x", "subject": "y", "emotion": "z", "headline": "h"},
        "sections": [
            {
                "purpose": "situation", "time_goal": 1.0, "voiceover": "Noi dung " * 5,
                "visual_intent": "vi", "speaker_id": "host", "scene_characters": ["host"],
                "turn": None, "caption": None, "hook": None, "transition": None,
                "payoff": None, "emphasis": None,
            },
        ],
        "compliance": {"passed": True},
    }
    result = validate_script_payload(payload)
    unknown = [f for f in result.findings if f.rule.endswith("scene_characters.unknown")]
    assert unknown, "host (the narration id) must not be accepted as a visible cast member"


def test_qa_speaker_prefix_check_uses_declared_narration_id_for_cast_lookup(tmp_path):
    from ytb_pipeline.agents.qa_agent import _check_speaker_prefix_leak

    class _Segment:
        def __init__(self, speaker_id, narration):
            self.speaker_id = speaker_id
            self.narration = narration
            self.voiceover = narration

    class _Script:
        def __init__(self, profile_id, profile_version, segments):
            self.content_profile_id = profile_id
            self.content_profile_version = profile_version
            self.segments = segments

    _write_host_profile(tmp_path)
    profile = load_content_profile("host-story-fixture", profiles_dir=tmp_path)

    import ytb_pipeline.agents.qa_agent as qa_module

    original = qa_module._content_profile
    qa_module._content_profile = lambda script: profile
    try:
        script = _Script(profile.profile_id, profile.version, [
            _Segment("guest", "guest: Toi moi chuyen den day."),
        ])
        violations = _check_speaker_prefix_leak(script)
        assert violations, "a cast member's own name-prefix must still be flagged"

        script_host = _Script(profile.profile_id, profile.version, [
            _Segment("host", "host: Chao mung cac ban toi voi day."),
        ])
        no_violation = _check_speaker_prefix_leak(script_host)
        assert not no_violation, "the declared narration id must not be treated as a cast member"
    finally:
        qa_module._content_profile = original


def test_qa_flags_a_machine_slug_spoken_inside_narration():
    """Slug lọt vào lời đọc thì TTS đọc ra chuỗi vô nghĩa.

    Đo trên bản Short thật: câu "Lần tới, video dài minh-cham-hon-dong-nghiep-tre
    sẽ đi tiếp..." được xKiro đọc thành "Video giải minh cờ hờ AMH Owner the
    owner Sơ". Section đó vẫn đạt 0.92 ở cổng audio vì 200 ký tự đúng pha loãng
    29 ký tự slug — cùng kiểu pha loãng mà cổng per-segment đã sửa, nhưng ở
    trong lòng một segment. Chặn ngay ở kịch bản là chỗ rẻ nhất.
    """
    from ytb_pipeline.agents.qa_agent import _check_slug_leak

    class _Strategy:
        long_form_slug = "minh-cham-hon-dong-nghiep-tre"
        cta_target = "minh-cham-hon-dong-nghiep-tre"
        source_long_slug = "minh-cham-hon-dong-nghiep-tre"

    class _Segment:
        def __init__(self, narration):
            self.speaker_id = "narrator"
            self.narration = narration
            self.voiceover = narration

    class _Script:
        def __init__(self, segments):
            self.slug = "vi-sao-toi-qua-khong-noi-som"
            self.strategy = _Strategy()
            self.segments = segments

    leaked = _Script([
        _Segment("Lần tới, video dài minh-cham-hon-dong-nghiep-tre sẽ đi tiếp."),
    ])
    violations = _check_slug_leak(leaked)
    assert violations, "slug đọc thành tiếng phải bị chặn"
    assert violations[0]["rule"] == "slug_leak"

    clean = _Script([
        _Segment("Lần tới, video dài sẽ đi tiếp từ chỗ chưa kịp nói đó."),
    ])
    assert _check_slug_leak(clean) == []


def test_qa_slug_leak_check_leaves_ordinary_hyphenated_vietnamese_alone():
    """Không được bắt nhầm gạch nối thường gặp trong tiếng Việt."""
    from ytb_pipeline.agents.qa_agent import _check_slug_leak

    class _Segment:
        def __init__(self, narration):
            self.speaker_id = "narrator"
            self.narration = narration
            self.voiceover = narration

    class _Script:
        slug = "mot-slug-khac"
        strategy = None
        def __init__(self, segments):
            self.segments = segments

    ordinary = _Script([_Segment("Cậu ấy pha cà-phê rồi ngồi xuống bàn số sáu.")])
    assert _check_slug_leak(ordinary) == []
