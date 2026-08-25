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
