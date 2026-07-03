"""Validation helpers for publish provider results."""

from __future__ import annotations

from pathlib import Path

from ..pkg.models import PublishResult


def validate_publish_result(platform: str, result: PublishResult) -> None:
    """Fail fast on impossible publish results before checkpoint/ledger writes."""
    if result.uploaded:
        if not result.url:
            raise ValueError(f"{platform}: uploaded=True nhưng thiếu url")
        if platform.startswith("youtube") and not result.youtube_id:
            raise ValueError(f"{platform}: YouTube upload thiếu youtube_id")
        return

    if platform in {"tiktok", "instagram_reel", "facebook_reel", "manual_export"}:
        if not result.url:
            raise ValueError(f"{platform}: manual export thiếu manifest url")
        manifest = Path(result.url.split("#", 1)[0])
        if not manifest.exists():
            raise FileNotFoundError(f"{platform}: không thấy manifest export: {manifest}")
