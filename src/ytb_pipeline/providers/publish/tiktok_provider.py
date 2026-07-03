"""TikTok publisher.

Đăng video thật cần TikTok Content Posting API (OAuth 2.0 app phải được TikTok
duyệt riêng). Khi chưa có API/token, provider tạo manual export package thay vì
raise, để `target_platforms=tiktok` vẫn có output publish rõ ràng.
"""

from dataclasses import replace

from ...pkg.models import PublishResult, RenderedVideo
from ...platform.metadata import PublishMetadata
from .manual_export_provider import ManualExportPublishProvider


class TikTokPublishProvider:
    name = "tiktok"

    def is_available(self) -> bool:
        from ...config.settings import settings

        return bool(settings.tiktok_access_token)

    async def publish(
        self, video: RenderedVideo, metadata: PublishMetadata | None = None
    ) -> PublishResult:
        if not self.is_available():
            return await TikTokManualExportProvider().publish(video, metadata)

        # Stub: log dự định upload (chưa gọi API thật).
        print("── TIKTOK STUB — chưa upload thật ──")
        print(f"  Video : {video.video_path}")
        if metadata is not None:
            print(f"  Title : {metadata.title}")
            print(f"  Hashtag: {' '.join(metadata.hashtags) or '(không có)'}")

        # Real implementation: POST https://open.tiktokapis.com/v2/post/publish/video/.
        # Until then, return a manual queue package with explicit API-later metadata.
        result = await TikTokManualExportProvider().publish(video, metadata)
        return replace(
            result,
            url=f"{result.url}#api-pending",
        )


class TikTokManualExportProvider(ManualExportPublishProvider):
    name = "tiktok_manual_export"
    platform = "tiktok"
