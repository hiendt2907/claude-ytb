"""Manual publish export provider for platforms without approved API access."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

from ...config.settings import settings
from ...pkg.models import PublishResult, RenderedVideo
from ...platform.metadata import MetadataAdapter, PublishMetadata


class ManualExportPublishProvider:
    """Create a clear manual upload package instead of pretending API upload exists."""

    name = "manual_export"
    platform = "manual"

    def __init__(self, platform: str | None = None) -> None:
        if platform is not None:
            self.platform = platform

    def is_available(self) -> bool:
        return True

    async def publish(
        self, video: RenderedVideo, metadata: PublishMetadata | None = None
    ) -> PublishResult:
        if video.video_path is None or not Path(video.video_path).exists():
            raise FileNotFoundError(f"Không tìm thấy video để export: {video.video_path}")

        adapter = MetadataAdapter()
        meta = metadata or adapter.adapt(
            video.title,
            video.description,
            list(video.tags),
            self.platform,
            privacy=settings.youtube_privacy,
            publish_at=None,
            contains_synthetic_media=settings.youtube_contains_synthetic_media,
        )

        package_dir = Path(settings.manual_publish_dir) / self.platform / Path(video.video_path).stem
        package_dir.mkdir(parents=True, exist_ok=True)
        exported_video = package_dir / Path(video.video_path).name
        if Path(video.video_path).resolve() != exported_video.resolve():
            shutil.copy2(video.video_path, exported_video)
        exported_thumb = None
        if video.thumbnail_path and Path(video.thumbnail_path).exists():
            exported_thumb = package_dir / Path(video.thumbnail_path).name
            shutil.copy2(video.thumbnail_path, exported_thumb)

        manifest = package_dir / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "platform": self.platform,
                    "video": str(exported_video),
                    "thumbnail": str(exported_thumb) if exported_thumb else None,
                    "title": meta.title,
                    "description": meta.description,
                    "hashtags": meta.hashtags,
                    "tags": meta.tags,
                    "duration_sec": video.duration_sec,
                    "uploaded": False,
                    "reason": "Manual/API-later export package; direct API not configured or approved.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return replace(PublishResult(**vars(video)), uploaded=False, url=str(manifest))


class InstagramReelExportProvider(ManualExportPublishProvider):
    name = "instagram_reel"
    platform = "instagram_reel"


class FacebookReelExportProvider(ManualExportPublishProvider):
    name = "facebook_reel"
    platform = "facebook_reel"
