"""Platform profiles — ràng buộc kỹ thuật + metadata cho từng nền tảng đăng.

Mỗi `PlatformProfile` mô tả độ phân giải, độ dài tối đa/tối thiểu, giới hạn
tiêu đề/mô tả/tag/hashtag... để `MetadataAdapter` (xem `metadata.py`) và khâu
publish dùng chung, không hardcode rải rác như uploader.py hiện tại.
"""

from dataclasses import dataclass
from enum import Enum


class Platform(str, Enum):
    YOUTUBE_SHORT = "youtube_short"
    YOUTUBE_LONG = "youtube_long"
    TIKTOK = "tiktok"
    INSTAGRAM_REEL = "instagram_reel"
    FACEBOOK_REEL = "facebook_reel"
    PODCAST = "podcast"
    BLOG = "blog"


@dataclass(frozen=True)
class PlatformProfile:
    platform: Platform
    # Video constraints
    max_duration_sec: int
    min_duration_sec: int
    width: int
    height: int
    fps: int
    # Audio
    sample_rate: int
    # Metadata
    max_title_chars: int
    max_description_chars: int
    max_tags: int
    max_hashtags: int
    supports_scheduled_publish: bool
    requires_aspect_ratio_disclosure: bool
    # Names
    display_name: str


PROFILES: dict[Platform, PlatformProfile] = {
    Platform.YOUTUBE_SHORT: PlatformProfile(
        platform=Platform.YOUTUBE_SHORT,
        max_duration_sec=180,
        min_duration_sec=15,
        width=1080,
        height=1920,
        fps=30,
        sample_rate=44100,
        max_title_chars=100,
        max_description_chars=5000,
        max_tags=30,
        max_hashtags=3,
        supports_scheduled_publish=True,
        requires_aspect_ratio_disclosure=False,
        display_name="YouTube Shorts",
    ),
    Platform.YOUTUBE_LONG: PlatformProfile(
        platform=Platform.YOUTUBE_LONG,
        max_duration_sec=43200,
        min_duration_sec=60,
        width=1920,
        height=1080,
        fps=30,
        sample_rate=44100,
        max_title_chars=100,
        max_description_chars=5000,
        max_tags=30,
        max_hashtags=3,
        supports_scheduled_publish=True,
        requires_aspect_ratio_disclosure=False,
        display_name="YouTube Long",
    ),
    Platform.TIKTOK: PlatformProfile(
        platform=Platform.TIKTOK,
        max_duration_sec=600,
        min_duration_sec=3,
        width=1080,
        height=1920,
        fps=30,
        sample_rate=44100,
        max_title_chars=150,
        max_description_chars=2200,
        max_tags=0,
        max_hashtags=5,
        supports_scheduled_publish=False,
        requires_aspect_ratio_disclosure=False,
        display_name="TikTok",
    ),
    Platform.INSTAGRAM_REEL: PlatformProfile(
        platform=Platform.INSTAGRAM_REEL,
        max_duration_sec=90,
        min_duration_sec=3,
        width=1080,
        height=1920,
        fps=30,
        sample_rate=44100,
        max_title_chars=125,
        max_description_chars=2200,
        max_tags=0,
        max_hashtags=5,
        supports_scheduled_publish=False,
        requires_aspect_ratio_disclosure=False,
        display_name="Instagram Reels",
    ),
    Platform.FACEBOOK_REEL: PlatformProfile(
        platform=Platform.FACEBOOK_REEL,
        max_duration_sec=90,
        min_duration_sec=3,
        width=1080,
        height=1920,
        fps=30,
        sample_rate=44100,
        max_title_chars=125,
        max_description_chars=2200,
        max_tags=0,
        max_hashtags=5,
        supports_scheduled_publish=False,
        requires_aspect_ratio_disclosure=False,
        display_name="Facebook Reels",
    ),
    Platform.PODCAST: PlatformProfile(
        platform=Platform.PODCAST,
        max_duration_sec=7200,
        min_duration_sec=60,
        width=3000,
        height=3000,
        fps=1,  # artwork tĩnh, không phải video
        sample_rate=44100,
        max_title_chars=255,
        max_description_chars=4000,
        max_tags=20,
        max_hashtags=0,
        supports_scheduled_publish=True,
        requires_aspect_ratio_disclosure=False,
        display_name="Podcast",
    ),
    Platform.BLOG: PlatformProfile(
        platform=Platform.BLOG,
        max_duration_sec=0,
        min_duration_sec=0,
        width=0,
        height=0,
        fps=0,
        sample_rate=0,
        max_title_chars=70,
        max_description_chars=160,
        max_tags=10,
        max_hashtags=0,
        supports_scheduled_publish=True,
        requires_aspect_ratio_disclosure=False,
        display_name="Blog",
    ),
}


def get_profile(platform: "Platform | str") -> PlatformProfile:
    """Tra cứu profile theo Platform enum hoặc tên chuỗi (vd "tiktok")."""
    if isinstance(platform, Platform):
        return PROFILES[platform]
    try:
        platform_enum = Platform(platform)
    except ValueError as exc:
        valid = ", ".join(p.value for p in Platform)
        raise ValueError(
            f"Platform không hợp lệ: '{platform}'. Hợp lệ: {valid}"
        ) from exc
    return PROFILES[platform_enum]
