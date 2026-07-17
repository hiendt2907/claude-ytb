"""Validation helpers for publish provider results."""

from __future__ import annotations

from pathlib import Path

from ..pkg.models import PublishResult


class MonetizationReviewError(ValueError):
    """The video must be held for human review instead of uploaded."""


_ABSOLUTE_CLAIMS = ("chữa khỏi", "chắc chắn", "đảm bảo", "100%", "guaranteed")


def validate_monetization_ready(video) -> None:  # noqa: ANN001 - accepts RenderedVideo-compatible models
    """Reject thin, misleading metadata before a real upload is attempted."""
    text = f"{video.title} {video.description}".lower()
    reasons: list[str] = []
    if len(video.description.strip()) < 80:
        reasons.append("description quá ngắn, không chứng minh commentary/education gốc")
    if not video.tags:
        reasons.append("thiếu tag chủ đề trực tiếp")
    if any(claim in text for claim in _ABSOLUTE_CLAIMS):
        reasons.append("claim tuyệt đối về sức khỏe/tài chính")
    narration = str(getattr(video, "body", "")).strip()
    if narration and len(narration) < 240:
        reasons.append("narration gốc quá ngắn để audit commentary")
    if reasons:
        raise MonetizationReviewError("; ".join(reasons))


def validate_publish_result(platform: str, result: PublishResult) -> None:
    """Fail fast on impossible publish results before checkpoint/ledger writes."""
    if result.uploaded:
        if not result.url:
            raise ValueError(f"{platform}: uploaded=True nhưng thiếu url")
        if platform.startswith("youtube") and not result.youtube_id:
            raise ValueError(f"{platform}: YouTube upload thiếu youtube_id")
        return

    if platform in {"instagram_reel", "facebook_reel", "manual_export"}:
        if not result.url:
            raise ValueError(f"{platform}: manual export thiếu manifest url")
        manifest = Path(result.url.split("#", 1)[0])
        if not manifest.exists():
            raise FileNotFoundError(f"{platform}: không thấy manifest export: {manifest}")
