"""MetadataAdapter — chuyển metadata chung (title/description/tags) thành
`PublishMetadata` đã áp ràng buộc riêng của từng platform (độ dài, số
hashtag, quy tắc #Shorts...). Tách khỏi `publish/uploader.py` để khâu publish
không còn hardcode logic riêng cho YouTube.
"""

from dataclasses import dataclass, field

from .profiles import Platform, PlatformProfile, get_profile


@dataclass(frozen=True)
class PublishMetadata:
    """Metadata đã chuẩn hoá, độc lập platform — publish provider dùng trực tiếp."""

    title: str
    description: str
    tags: list[str]
    hashtags: list[str]
    privacy: str
    publish_at: str | None
    contains_synthetic_media: bool
    platform: Platform
    raw: dict = field(default_factory=dict)


class MetadataAdapter:
    """Áp ràng buộc của 1 `PlatformProfile` lên metadata thô của script."""

    def adapt(
        self,
        title: str,
        description: str,
        tags: list[str],
        platform: "Platform | str",
        *,
        publish_at: str | None = None,
        privacy: str = "private",
        contains_synthetic_media: bool = True,
    ) -> PublishMetadata:
        profile = get_profile(platform)
        platform_enum = profile.platform

        adapted_title = title[: profile.max_title_chars]
        adapted_description = description[: profile.max_description_chars]
        adapted_tags = list(tags[: profile.max_tags]) if profile.max_tags > 0 else []
        hashtags = self._build_hashtags(tags, platform_enum, profile)

        return PublishMetadata(
            title=adapted_title,
            description=adapted_description,
            tags=adapted_tags,
            hashtags=hashtags,
            privacy=privacy,
            publish_at=publish_at if profile.supports_scheduled_publish else None,
            contains_synthetic_media=contains_synthetic_media,
            platform=platform_enum,
            raw={},
        )

    def _build_hashtags(
        self, tags: list[str], platform: Platform, profile: PlatformProfile
    ) -> list[str]:
        """Quy tắc hashtag riêng từng platform:
        - YouTube Short: luôn có #Shorts đứng đầu.
        - Instagram/Facebook Reel: dùng tag thô (không thêm "#"), nền tảng tự gắn.
        - Podcast/Blog: max_hashtags=0 -> không có hashtag.
        - Còn lại: top N tag (đã thêm "#") theo max_hashtags.
        """
        if profile.max_hashtags <= 0:
            return []

        if platform == Platform.YOUTUBE_SHORT:
            hashtags = ["#Shorts"]
            for tag in tags:
                hashtag = self._to_hashtag(tag)
                if not hashtag or hashtag.lower() in (h.lower() for h in hashtags):
                    continue
                hashtags.append(hashtag)
                if len(hashtags) >= profile.max_hashtags:
                    break
            return hashtags

        if platform in (Platform.INSTAGRAM_REEL, Platform.FACEBOOK_REEL):
            seen: list[str] = []
            for tag in tags:
                cleaned = tag.strip().lstrip("#")
                if not cleaned or cleaned.lower() in (s.lower() for s in seen):
                    continue
                seen.append(cleaned)
                if len(seen) >= profile.max_hashtags:
                    break
            return seen

        hashtags = []
        for tag in tags:
            hashtag = self._to_hashtag(tag)
            if not hashtag or hashtag.lower() in (h.lower() for h in hashtags):
                continue
            hashtags.append(hashtag)
            if len(hashtags) >= profile.max_hashtags:
                break
        return hashtags

    @staticmethod
    def _to_hashtag(tag: str) -> str:
        import re

        cleaned = re.sub(r"[^\w]", "", tag, flags=re.UNICODE)
        return f"#{cleaned}" if cleaned else ""
