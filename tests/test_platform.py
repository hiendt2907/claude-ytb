"""Tests for YouTube platform profiles and metadata adaptation."""

import pytest

from ytb_pipeline.platform.metadata import MetadataAdapter
from ytb_pipeline.platform.profiles import Platform, get_profile


def test_get_profile_by_string_name():
    assert get_profile("youtube_short").platform == Platform.YOUTUBE_SHORT


def test_get_profile_by_enum_same_result():
    assert get_profile("youtube_short") == get_profile(Platform.YOUTUBE_SHORT)


def test_get_profile_invalid_name_raises_value_error():
    with pytest.raises(ValueError, match="invalid"):
        get_profile("invalid")


def test_youtube_short_profile_dimensions():
    profile = get_profile("youtube_short")
    assert (profile.width, profile.height) == (1080, 1920)


def test_youtube_long_profile_dimensions():
    profile = get_profile("youtube_long")
    assert (profile.width, profile.height) == (1920, 1080)


def test_metadata_adapter_truncates_title_and_description():
    adapter = MetadataAdapter()
    profile = get_profile("youtube_short")
    metadata = adapter.adapt("x" * 500, "y" * 10000, [], "youtube_short")
    assert len(metadata.title) == profile.max_title_chars
    assert len(metadata.description) == profile.max_description_chars


def test_metadata_adapter_youtube_short_includes_shorts_hashtag():
    metadata = MetadataAdapter().adapt("Title", "Desc", ["python", "ai"], "youtube_short")
    assert "#Shorts" in metadata.hashtags


def test_metadata_adapter_limits_tags():
    metadata = MetadataAdapter().adapt(
        "Title", "Desc", [f"tag{i}" for i in range(50)], "youtube_short"
    )
    assert len(metadata.tags) <= get_profile("youtube_short").max_tags


def test_publish_metadata_is_frozen():
    metadata = MetadataAdapter().adapt("Title", "Desc", [], "youtube_short")
    with pytest.raises(Exception):
        metadata.title = "changed"


def test_metadata_adapter_podcast_no_hashtags():
    metadata = MetadataAdapter().adapt("Title", "Desc", ["tag1"], "podcast")
    assert metadata.hashtags == []
