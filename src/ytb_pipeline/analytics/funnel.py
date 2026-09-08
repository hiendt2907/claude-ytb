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

    if batch.get("short_source_strategy_version") == "v1":
        if any(
            item.get("source_long_slug") != item.get("long_form_slug")
            or not isinstance(item.get("source_section_index"), int)
            or not str(item.get("source_excerpt", "")).strip()
            for item in shorts
        ):
            issues.append("shorts_without_long_source")

    requested_shorts_per_long = batch.get("shorts_per_long")
    if isinstance(requested_shorts_per_long, int) and requested_shorts_per_long > 0:
        for long_slug in sorted(long_slugs):
            linked_to_long = sum(
                1 for item in shorts if item.get("long_form_slug") == long_slug
            )
            if linked_to_long != requested_shorts_per_long:
                issues.append(
                    "shorts_per_long_mismatch:"
                    f"{long_slug}:{linked_to_long}/{requested_shorts_per_long}"
                )

    if batch.get("daily_cadence") == {"longs": 1, "shorts": 2}:
        for long_video in longs:
            long_slug = str(long_video.get("slug", ""))
            linked = [item for item in shorts if item.get("long_form_slug") == long_slug]
            if len(linked) != 2:
                continue
            if any(item.get("day") != long_video.get("day") for item in linked):
                issues.append(f"daily_bundle_day_mismatch:{long_slug}")
            source_sections = [item.get("source_section_index") for item in linked]
            if None not in source_sections and len(set(source_sections)) != 2:
                issues.append(f"daily_bundle_source_repeat:{long_slug}")

    # Batch 3 and earlier queues remain readable/auditable.  New queues opt in
    # explicitly, then receive the stricter content-strategy and cadence gates.
    if batch.get("content_strategy_version") == "v1":
        strategy_fields = ("format_id", "core_mechanism", "audience_problem", "angle")
        if any(not all(str(item.get(field, "")).strip() for field in strategy_fields) for item in shorts):
            issues.append("strategy_metadata_missing")

        per_day: dict[str, int] = {}
        for item in shorts:
            day = str(item.get("publish_at", "")).split("T", 1)[0]
            if day:
                per_day[day] = per_day.get(day, 0) + 1
        daily_limit = 3 if batch.get("scale_authorized") is True else 2
        if any(count > daily_limit for count in per_day.values()):
            issues.append("shorts_per_day_exceeded")

    return FunnelAudit(
        issues=tuple(issues),
        short_count=len(shorts),
        long_count=len(longs),
        linked_short_count=linked,
    )
