"""Publish one rendered asset to one or more platform providers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from ..config.settings import settings
from ..orchestrator.queue_manager import mark_needs_review
from ..pkg.models import PublishResult, RenderedVideo
from ..providers.registry import get_publish_provider
from .validation import MonetizationReviewError, validate_monetization_ready, validate_publish_result


def configured_platforms() -> list[str]:
    raw = settings.target_platforms or settings.default_platform
    return [part.strip() for part in raw.split(",") if part.strip()]


async def publish_to_platforms(
    video: RenderedVideo,
    platforms: list[str] | None = None,
    *,
    project_id: str | None = None,
) -> dict[str, PublishResult]:
    selected = platforms or configured_platforms()
    results: dict[str, PublishResult] = {}
    for platform in selected:
        provider_name = "youtube" if platform in {"youtube_short", "youtube_long"} else platform
        provider = get_publish_provider(provider_name)
        try:
            # All providers share the same monetization audit.  Keep this here
            # rather than only inside the YouTube provider so an export cannot
            # bypass a failed human-review gate.
            if not settings.dry_run:
                validate_monetization_ready(video)
            result = await provider.publish(video)
        except MonetizationReviewError as exc:
            slug = project_id or _slug(video)
            mark_needs_review(slug, str(exc))
            _write_monetization_audit(slug, video, str(exc))
            raise
        validate_publish_result(platform, result)
        results[platform] = result
    return results


def publish_to_platforms_sync(video: RenderedVideo, platforms: list[str] | None = None) -> dict[str, PublishResult]:
    return asyncio.run(publish_to_platforms(video, platforms))


def _slug(video: RenderedVideo) -> str:
    from ..ideation.series import slugify

    return slugify(video.title) or slugify(video.topic)


def _write_monetization_audit(slug: str, video: RenderedVideo, reason: str) -> None:
    from ..orchestrator.state_io import atomic_write_json

    audit_path = Path(settings.projects_dir) / slug / "monetization_audit.json"
    atomic_write_json(audit_path, {
        "status": "needs_review",
        "reason": reason,
        "checked_at": datetime.now(UTC).isoformat(),
        "title": video.title,
        "tags": list(video.tags),
        "description_chars": len(video.description.strip()),
        "narration_chars": len(video.body.strip()),
    })
