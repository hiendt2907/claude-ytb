"""Test cho Phase 4 — platform-independence (profiles, metadata adapter,
TikTok stub). Xem `src/ytb_pipeline/platform/` và
`src/ytb_pipeline/providers/publish/tiktok_provider.py`.
"""

import pytest

from ytb_pipeline.platform.metadata import MetadataAdapter, PublishMetadata
from ytb_pipeline.platform.profiles import Platform, get_profile
from ytb_pipeline.providers.publish.tiktok_provider import TikTokPublishProvider
from ytb_pipeline.providers.registry import publish_registry


def test_get_profile_by_string_name():
    profile = get_profile("youtube_short")
    assert profile.platform == Platform.YOUTUBE_SHORT


def test_get_profile_by_enum_same_result():
    by_string = get_profile("youtube_short")
    by_enum = get_profile(Platform.YOUTUBE_SHORT)
    assert by_string == by_enum


def test_get_profile_invalid_name_raises_value_error():
    with pytest.raises(ValueError, match="invalid"):
        get_profile("invalid")


def test_youtube_short_profile_dimensions():
    profile = get_profile("youtube_short")
    assert profile.width == 1080
    assert profile.height == 1920


def test_youtube_long_profile_dimensions():
    profile = get_profile("youtube_long")
    assert profile.width == 1920
    assert profile.height == 1080


def test_tiktok_profile_max_duration():
    profile = get_profile("tiktok")
    assert profile.max_duration_sec == 600


def test_metadata_adapter_truncates_title():
    adapter = MetadataAdapter()
    long_title = "x" * 500
    metadata = adapter.adapt(long_title, "desc", [], "tiktok")
    profile = get_profile("tiktok")
    assert len(metadata.title) == profile.max_title_chars


def test_metadata_adapter_youtube_short_includes_shorts_hashtag():
    adapter = MetadataAdapter()
    metadata = adapter.adapt("Title", "Desc", ["python", "ai"], "youtube_short")
    assert "#Shorts" in metadata.hashtags


def test_metadata_adapter_tiktok_max_hashtags():
    adapter = MetadataAdapter()
    tags = [f"tag{i}" for i in range(20)]
    metadata = adapter.adapt("Title", "Desc", tags, "tiktok")
    profile = get_profile("tiktok")
    assert len(metadata.hashtags) <= profile.max_hashtags


def test_metadata_adapter_truncates_description():
    adapter = MetadataAdapter()
    long_description = "y" * 10000
    metadata = adapter.adapt("Title", long_description, [], "tiktok")
    profile = get_profile("tiktok")
    assert len(metadata.description) == profile.max_description_chars


def test_metadata_adapter_limits_tags_to_max_tags():
    adapter = MetadataAdapter()
    tags = [f"tag{i}" for i in range(50)]
    metadata = adapter.adapt("Title", "Desc", tags, "youtube_short")
    profile = get_profile("youtube_short")
    assert len(metadata.tags) <= profile.max_tags


def test_publish_metadata_is_frozen():
    adapter = MetadataAdapter()
    metadata = adapter.adapt("Title", "Desc", [], "tiktok")
    with pytest.raises(Exception):
        metadata.title = "changed"


def test_tiktok_provider_is_available_false_when_token_empty():
    from ytb_pipeline.config.settings import settings

    original = settings.tiktok_access_token
    try:
        settings.tiktok_access_token = ""
        provider = TikTokPublishProvider()
        assert provider.is_available() is False
    finally:
        settings.tiktok_access_token = original


def test_tiktok_provider_is_available_true_when_token_set():
    from ytb_pipeline.config.settings import settings

    original = settings.tiktok_access_token
    try:
        settings.tiktok_access_token = "fake-token"
        provider = TikTokPublishProvider()
        assert provider.is_available() is True
    finally:
        settings.tiktok_access_token = original


def test_publish_registry_includes_tiktok():
    assert "tiktok" in publish_registry.available()


def test_metadata_adapter_podcast_no_hashtags():
    adapter = MetadataAdapter()
    metadata = adapter.adapt("Title", "Desc", ["tag1", "tag2"], "podcast")
    profile = get_profile("podcast")
    assert profile.max_hashtags == 0
    assert metadata.hashtags == []


@pytest.mark.asyncio
async def test_tiktok_provider_publish_exports_manual_package_when_available(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.pkg.models import RenderedVideo

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"mp4")
    original_token = settings.tiktok_access_token
    original_dir = settings.manual_publish_dir
    try:
        settings.tiktok_access_token = "fake-token"
        settings.manual_publish_dir = tmp_path / "manual"
        provider = TikTokPublishProvider()
        video = RenderedVideo(
            topic="t", title="Title", description="Desc", tags=("a",), video_path=video_file
        )
        result = await provider.publish(video)
        assert result.uploaded is False
        assert result.url is not None
        assert "api-pending" in result.url
    finally:
        settings.tiktok_access_token = original_token
        settings.manual_publish_dir = original_dir


@pytest.mark.asyncio
async def test_tiktok_provider_publish_exports_manual_package_when_no_token(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.pkg.models import RenderedVideo

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"mp4")
    original_token = settings.tiktok_access_token
    original_dir = settings.manual_publish_dir
    try:
        settings.tiktok_access_token = ""
        settings.manual_publish_dir = tmp_path / "manual"
        provider = TikTokPublishProvider()
        video = RenderedVideo(
            topic="t", title="Title", description="Desc", tags=("a",), video_path=video_file
        )
        result = await provider.publish(video)
        assert result.uploaded is False
        assert result.url is not None
        assert "manual/tiktok/video/manifest.json" in result.url
    finally:
        settings.tiktok_access_token = original_token
        settings.manual_publish_dir = original_dir
