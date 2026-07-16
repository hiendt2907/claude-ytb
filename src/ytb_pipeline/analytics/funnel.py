"""Deterministic checks for the Short -> long-form growth funnel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FunnelAudit:
    """Immutable result of auditing one batch's content relationships."""

    issues: tuple[str, ...] = ()
    short_count: int = 0
    long_count: int = 0
    linked_short_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def summary(self) -> str:
        if self.ok:
            return f"{self.short_count} Shorts, {self.long_count} long, funnel nối đủ"
        return (
            f"{self.short_count} Shorts, {self.long_count} long, "
            f"lỗi: {', '.join(self.issues)}"
        )


def audit_batch(batch: dict[str, Any]) -> FunnelAudit:
    """Audit active batch metadata without changing the loaded state.

    Empty or completed batches are informationally valid. An active batch with
    Shorts must have at least one long-form target and every Short must declare
    its long-form slug, playlist and CTA target.
    """
    if batch.get("status") not in {"active", "queued", "running"}:
        return FunnelAudit()

    shorts = [item for item in batch.get("short_videos", []) or [] if isinstance(item, dict)]
    longs = [item for item in batch.get("long_videos", []) or [] if isinstance(item, dict)]
    if not shorts:
        return FunnelAudit(short_count=0, long_count=len(longs))

    issues: list[str] = []
    long_slugs = {str(item.get("slug")) for item in longs if item.get("slug")}
    if not long_slugs:
        issues.append("no_long_form")

    linked = 0
    for item in shorts:
        target = item.get("long_form_slug")
        if target and target in long_slugs and item.get("playlist") and item.get("cta_target"):
            linked += 1
    if linked != len(shorts):
        issues.append("shorts_without_target")

    return FunnelAudit(
        issues=tuple(issues),
        short_count=len(shorts),
        long_count=len(longs),
        linked_short_count=linked,
    )
