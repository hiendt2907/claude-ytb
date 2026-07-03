"""Publish one rendered asset to one or more platform providers."""

from __future__ import annotations

import asyncio

from ..config.settings import settings
from ..pkg.models import PublishResult, RenderedVideo
from ..providers.registry import get_publish_provider
from .validation import validate_publish_result


def configured_platforms() -> list[str]:
    raw = settings.target_platforms or settings.default_platform
    return [part.strip() for part in raw.split(",") if part.strip()]


async def publish_to_platforms(video: RenderedVideo, platforms: list[str] | None = None) -> dict[str, PublishResult]:
    selected = platforms or configured_platforms()
    results: dict[str, PublishResult] = {}
    for platform in selected:
        provider_name = "youtube" if platform in {"youtube_short", "youtube_long"} else platform
        provider = get_publish_provider(provider_name)
        result = await provider.publish(video)
        validate_publish_result(platform, result)
        results[platform] = result
    return results


def publish_to_platforms_sync(video: RenderedVideo, platforms: list[str] | None = None) -> dict[str, PublishResult]:
    return asyncio.run(publish_to_platforms(video, platforms))
