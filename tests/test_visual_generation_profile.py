"""Content profile schema for local IPAdapter identity-anchored image generation.

Gated to `narrative_mode == "character_story"` only, per explicit product
decision: a mechanism-explainer profile has no cast, so image generation has
nothing to anchor identity to and must stay on the existing B-roll path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_profile(root: Path, profile_id: str, *, narrative_mode="character_story", visual_generation=None):
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    assets = folder / "assets"
    assets.mkdir()
    (folder / "prompts" / "editorial.md").write_text("x", encoding="utf-8")
    identity_dir = assets / "identity"
    identity_dir.mkdir()
    (identity_dir / "minh.png").write_bytes(b"fake-png-minh")
    (identity_dir / "an.png").write_bytes(b"fake-png-an")
    (assets / "recognition.png").write_bytes(b"fake-png-duo")
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": profile_id,
        "topic": "t",
        "narrative_mode": narrative_mode,
        "prompts": {"editorial": "prompts/editorial.md"},
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10},
        },
        "providers": {
            "llm": "xkiro", "tts": "xkiro", "render": "story",
            "broll_strategy": "none", "broll_allow_downloads": False,
        },
        "voice_cast": {
            "narrator": "standard-female-vietnamese",
            "minh": "confident-male-vietnamese",
            "an": "sweet-female-vietnamese",
        },
        "content_rules": {"require_pexels_query": False, "require_short_source_trace": False},
        "render": {"assets_dir": "assets", "show_captions": True, "inter_segment_gap_sec": 0.22},
    }
    if visual_generation is not None:
        payload["visual_generation"] = visual_generation
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return folder


def _vg(**overrides):
    base = {
        "enabled": True,
        "style_prompt": "2D editorial illustration",
        "negative_prompt": "photo, 3d render",
        "steps": 28,
        "cfg": 6.5,
        "solo_weight": 0.45,
        "duo_weight": 0.3,
        "duo_denoise": 0.5,
        "characters": {"minh": "identity/minh.png", "an": "identity/an.png"},
        "duo_reference_image": "recognition.png",
    }
    base.update(overrides)
    return base


def test_visual_generation_loads_and_resolves_character_reference_paths(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg())

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation is not None
    assert profile.visual_generation.enabled is True
    assert profile.character_reference_path("minh") == tmp_path / "ban-so-6" / "assets" / "identity" / "minh.png"
    assert profile.character_reference_path("an").is_file()
    assert profile.duo_reference_path() == tmp_path / "ban-so-6" / "assets" / "recognition.png"


def test_profile_without_visual_generation_block_has_none():
    from ytb_pipeline.content_profiles import load_content_profile

    profile = load_content_profile("one-cup-cafe-6h")

    assert profile.visual_generation is None


def test_visual_generation_enabled_on_a_non_story_profile_is_rejected(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(
        tmp_path, "explainer-with-visuals",
        narrative_mode="mechanism_explainer", visual_generation=_vg(),
    )

    with pytest.raises(ContentProfileError, match="character_story"):
        load_content_profile("explainer-with-visuals", profiles_dir=tmp_path)


def test_unknown_character_id_in_visual_generation_is_rejected(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(
        tmp_path, "ban-so-6",
        visual_generation=_vg(characters={"khach-la": "identity/minh.png"}),
    )

    with pytest.raises(ContentProfileError, match="voice_cast"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


def test_missing_character_reference_file_is_rejected(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(
        tmp_path, "ban-so-6",
        visual_generation=_vg(characters={"minh": "identity/does-not-exist.png"}),
    )

    with pytest.raises(ContentProfileError):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


def test_character_reference_path_rejects_traversal(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.content_profiles import ContentProfileError

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg())
    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    with pytest.raises(ContentProfileError):
        profile.character_reference_path("../../../../etc/passwd")


@pytest.mark.parametrize("field,value", [
    ("steps", 0), ("cfg", 0), ("cfg", -1), ("solo_weight", -0.1),
    ("duo_weight", 3), ("duo_denoise", 0), ("duo_denoise", 1.5),
])
def test_out_of_range_numeric_fields_are_rejected(tmp_path, field, value):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg(**{field: value}))

    with pytest.raises(ContentProfileError):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


def test_disabled_visual_generation_skips_asset_existence_checks(tmp_path):
    """An operator can author the block ahead of having final art."""
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(
        tmp_path, "ban-so-6",
        visual_generation=_vg(enabled=False, characters={"minh": "identity/not-there-yet.png"}),
    )

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation.enabled is False


def test_profile_fingerprint_changes_when_an_identity_image_changes(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile, profile_fingerprint

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg())
    before = profile_fingerprint(load_content_profile("ban-so-6", profiles_dir=tmp_path))

    (tmp_path / "ban-so-6" / "assets" / "identity" / "minh.png").write_bytes(b"different-bytes")

    after = profile_fingerprint(load_content_profile("ban-so-6", profiles_dir=tmp_path))
    assert before != after


def test_tts_pace_factor_defaults_to_one_when_absent(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6")

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.providers.tts_pace_factor == 1.0


def test_tts_pace_factor_reads_from_providers_block(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile
    import json

    folder = _write_profile(tmp_path, "ban-so-6")
    payload = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    payload["providers"]["tts_pace_factor"] = 0.93
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.providers.tts_pace_factor == 0.93


@pytest.mark.parametrize("value", [0, -0.1, 2.5])
def test_tts_pace_factor_out_of_range_is_rejected(tmp_path, value):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile
    import json

    folder = _write_profile(tmp_path, "ban-so-6")
    payload = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    payload["providers"]["tts_pace_factor"] = value
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentProfileError):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


# --- Phase 9: candidate_count / selection_policy config -------------------

def test_candidate_count_defaults_to_one_and_selection_policy_defaults_to_first_valid(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg())

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation.candidate_count == 1
    assert profile.visual_generation.selection_policy == "first_valid"
    assert profile.visual_generation.candidate_policy_version == "phase9-v1"


def test_candidate_count_can_be_raised_within_the_hard_maximum(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg(candidate_count=3))

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation.candidate_count == 3


@pytest.mark.parametrize("value", [0, -1, 5, 100])
def test_candidate_count_outside_the_bound_is_rejected(tmp_path, value):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg(candidate_count=value))

    with pytest.raises(ContentProfileError, match="candidate_count"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


def test_unknown_selection_policy_is_rejected(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg(selection_policy="best_of_n_vlm"))

    with pytest.raises(ContentProfileError, match="selection_policy"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


# --- Phase 10: visual_judge config -----------------------------------------

def _vg_with_judge(**judge_overrides):
    judge = {
        "enabled": True, "provider": "fake", "model": "fake-v1", "policy_version": "v1",
    }
    judge.update(judge_overrides)
    return _vg(candidate_count=3, selection_policy="vlm_ranked", visual_judge=judge)


def test_visual_judge_absent_by_default(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg())

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation.visual_judge is None


def test_vlm_ranked_with_visual_judge_enabled_loads(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg_with_judge())

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation.selection_policy == "vlm_ranked"
    assert profile.visual_generation.visual_judge.enabled is True
    assert profile.visual_generation.visual_judge.provider == "fake"
    assert profile.visual_generation.visual_judge.minimum_score == 0.5
    assert profile.visual_generation.visual_judge.hard_fail_on_judge_error is False


def test_vlm_ranked_without_visual_judge_block_is_rejected(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg(candidate_count=3, selection_policy="vlm_ranked"))

    with pytest.raises(ContentProfileError, match="visual_judge"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


def test_vlm_ranked_with_visual_judge_disabled_is_rejected(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg_with_judge(enabled=False))

    with pytest.raises(ContentProfileError, match="visual_judge"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


def test_visual_judge_enabled_requires_provider_and_model(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg_with_judge(provider=""))

    with pytest.raises(ContentProfileError, match="provider"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_visual_judge_minimum_score_out_of_range_is_rejected(tmp_path, value):
    from ytb_pipeline.content_profiles import ContentProfileError, load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg_with_judge(minimum_score=value))

    with pytest.raises(ContentProfileError, match="minimum_score"):
        load_content_profile("ban-so-6", profiles_dir=tmp_path)


def test_visual_judge_hard_fail_on_judge_error_can_be_enabled(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg_with_judge(hard_fail_on_judge_error=True))

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation.visual_judge.hard_fail_on_judge_error is True


def test_first_valid_selection_policy_does_not_require_visual_judge(tmp_path):
    from ytb_pipeline.content_profiles import load_content_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg(candidate_count=3, selection_policy="first_valid"))

    profile = load_content_profile("ban-so-6", profiles_dir=tmp_path)

    assert profile.visual_generation.visual_judge is None
