"""Đăng ký các PublishProvider vào publish_registry khi module này được import."""

from ..registry import publish_registry
from .drive_provider import DrivePublishProvider
from .manual_export_provider import FacebookReelExportProvider, InstagramReelExportProvider, ManualExportPublishProvider
from .youtube_provider import YouTubePublishProvider

publish_registry.register("youtube", YouTubePublishProvider)
publish_registry.register("drive", DrivePublishProvider)
publish_registry.register("manual_export", ManualExportPublishProvider)
publish_registry.register("instagram_reel", InstagramReelExportProvider)
publish_registry.register("facebook_reel", FacebookReelExportProvider)

__all__ = [
    "YouTubePublishProvider",
    "DrivePublishProvider",
    "ManualExportPublishProvider",
    "InstagramReelExportProvider",
    "FacebookReelExportProvider",
]
