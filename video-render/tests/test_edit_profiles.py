"""Test catalog auto-edit profiles/styles/animations."""

from __future__ import annotations

import pytest

from ytb_pipeline.assembler.profiles import (
    ANIMATIONS,
    PROFILES,
    STYLES,
    AutoEditProfile,
    RenderTuning,
    list_profiles,
    resolve_profile,
)


def test_profile_catalog_contains_affiliate_defaults() -> None:
    names = {profile.name for profile in list_profiles()}

    assert {
        "affiliate_default",
        "tiktok_shop_fast",
        "product_review_smooth",
        "beauty_skincare",
        "food_demo",
        "voiceover_catalog",
        "smooth_retry",
    }.issubset(names)


def test_profiles_reference_known_styles_and_animations() -> None:
    style_names = set(STYLES)
    animation_names = set(ANIMATIONS)

    for profile in PROFILES.values():
        assert profile.style_name in style_names
        assert set(profile.animation_names).issubset(animation_names)


def test_resolve_profile_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="edit_profile không hợp lệ"):
        resolve_profile("does_not_exist")


def test_profile_tuning_is_distinct_by_use_case() -> None:
    fast = resolve_profile("tiktok_shop_fast")
    smooth = resolve_profile("product_review_smooth")
    retry = resolve_profile("smooth_retry")

    assert fast.tuning.scene_transition_duration < smooth.tuning.scene_transition_duration
    assert fast.tuning.motion_scale > smooth.tuning.motion_scale
    assert fast.tuning.clip_transition_duration <= smooth.tuning.clip_transition_duration
    assert retry.tuning.scene_transition_duration >= smooth.tuning.scene_transition_duration
    assert retry.tuning.clip_transition_duration >= smooth.tuning.clip_transition_duration


def test_profile_objects_are_frozen() -> None:
    profile = resolve_profile("affiliate_default")

    with pytest.raises(Exception):
        profile.tuning = RenderTuning()  # type: ignore[misc]

    assert isinstance(profile, AutoEditProfile)
