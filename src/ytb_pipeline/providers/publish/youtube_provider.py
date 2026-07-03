"""Adapter — bọc `publish/uploader.py` (YouTube Data API) thành PublishProvider."""

from ...pkg.models import PublishResult, RenderedVideo


class YouTubePublishProvider:
    name = "youtube"

    async def publish(self, video: RenderedVideo) -> PublishResult:
        from ...publish.uploader import publish

        return publish(video)

    def is_available(self) -> bool:
        from ...config.settings import settings

        if settings.dry_run:
            return True
        try:
            from ...publish.youtube_auth import get_youtube_client  # noqa: F401

            return True
        except ImportError:
            return False
