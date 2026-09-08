"""Classify 48–72h video analytics into explicit next-content decisions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .cohorts import classify_cohort
from ..config.settings import settings
from ..orchestrator.state_io import locked_json_update


class AnalyticsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.analytics_path

    def get(self, slug: str) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with locked_json_update(self.path) as data:
            return dict(data.get("videos", {}).get(slug, {}))

    def feedback_summary(self) -> list[str]:
        if not self.path.exists():
            return []
        with locked_json_update(self.path) as data:
            videos = data.get("videos", {})
            decisions = [f"{slug}: {entry.get('decision')}" for slug, entry in videos.items()
                         if isinstance(entry, dict) and entry.get("decision")]
            baseline = data.get("channel_baseline", {}).get("stayed_to_watch")
        if baseline is None:
            return decisions
        return decisions + self.format_feedback(baseline_stayed_to_watch=float(baseline))

    def record(self, slug: str, metrics: dict[str, Any]) -> str:
        decision = classify(metrics)
        with locked_json_update(self.path) as data:
            videos = data.setdefault("videos", {})
            videos[slug] = {**metrics, "decision": decision}
        return decision

    def record_snapshot(self, slug: str, metrics: dict[str, Any]) -> None:
        """Append an immutable observation instead of replacing video history."""
        if "stayed_to_watch" in metrics:
            stayed_to_watch = float(metrics["stayed_to_watch"])
            if not 0 <= stayed_to_watch <= 1:
                raise ValueError("stayed_to_watch snapshot phải nằm trong [0, 1].")
        for field in ("age_hours", "short_to_long_clicks", "subscribers_gained"):
            if field in metrics and float(metrics[field]) < 0:
                raise ValueError(f"{field} snapshot không được âm.")
        with locked_json_update(self.path) as data:
            videos = data.setdefault("videos", {})
            entry = videos.setdefault(slug, {})
            snapshots = entry.setdefault("snapshots", [])
            snapshots.append(dict(metrics))

    def record_channel_baseline(self, *, stayed_to_watch: float) -> None:
        """Persist the current batch's manually observed Shorts baseline."""
        if not 0 <= stayed_to_watch <= 1:
            raise ValueError("stayed_to_watch baseline phải nằm trong [0, 1].")
        with locked_json_update(self.path) as data:
            data["channel_baseline"] = {"stayed_to_watch": stayed_to_watch}

    def format_feedback(self, *, baseline_stayed_to_watch: float) -> list[str]:
        """Summarize mature snapshots by tested format for the next prompt."""
        if not self.path.exists():
            return []
        with locked_json_update(self.path) as data:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for entry in data.get("videos", {}).values():
                if not isinstance(entry, dict):
                    continue
                for snapshot in entry.get("snapshots", []):
                    if not isinstance(snapshot, dict):
                        continue
                    format_id = str(snapshot.get("format_id", "")).strip()
                    if format_id:
                        grouped.setdefault(format_id, []).append(snapshot)
        return [
            f"format={format_id}: {classify_cohort(snapshots, baseline_stayed_to_watch=baseline_stayed_to_watch)}"
            for format_id, snapshots in sorted(grouped.items())
        ]


def classify(metrics: dict[str, Any]) -> str:
    """Return one of scale/revise_hook/revise_value/drop_format/needs_more_data."""
    if float(metrics.get("age_hours", 72)) < 48:
        return "needs_more_data"
    retention = float(metrics.get("retention_3s", 0))
    avg_viewed = float(metrics.get("average_percentage_viewed", 0))
    subscribers = int(metrics.get("subscribers_gained", 0))
    views = int(metrics.get("views", 0))
    # YouTube Analytics API does not provide the Shorts 3-second retention
    # metric.  Missing data must not be treated as a failed hook.
    if "retention_3s" in metrics and retention < 0.4:
        return "revise_hook"
    if views >= 1_000 and retention >= 0.65 and avg_viewed >= 0.6 and subscribers > 0:
        return "scale"
    if retention >= 0.55 and avg_viewed < 0.4:
        return "revise_value"
    if views >= 1_000 and subscribers == 0:
        return "revise_value"
    if "retention_3s" in metrics and views < 300 and retention < 0.5:
        return "drop_format"
    return "needs_more_data"


def collect_youtube_metrics(
    slug: str,
    youtube_id: str,
    *,
    analytics_client=None,
    youtube_client=None,
    store: AnalyticsStore | None = None,
    published_at: str | None = None,
    now: str | None = None,
) -> str:
    """Collect video-level YouTube Analytics data and persist a content decision.

    The Analytics API does not expose Shorts' swipe/3-second retention metrics;
    those stay optional manual fields in the store.  This collector deliberately
    records only metrics returned by the API, rather than inventing a proxy.
    """
    if analytics_client is None:
        from ..publish.youtube_auth import get_youtube_analytics_client

        analytics_client = get_youtube_analytics_client()
    response = analytics_client.reports().query(
        ids="channel==MINE",
        startDate="2005-01-01",
        endDate=(now or datetime.now().astimezone().isoformat()).split("T", 1)[0],
        metrics="views,averageViewDuration,averageViewPercentage,subscribersGained,comments",
        filters=f"video=={youtube_id}",
    ).execute()
    rows = response.get("rows") or []
    row = rows[0] if rows else [0, 0, 0, 0, 0]
    metrics: dict[str, Any] = {
        "youtube_id": youtube_id,
        "views": int(row[0] or 0),
        "average_view_duration": float(row[1] or 0),
        "average_percentage_viewed": float(row[2] or 0),
        "subscribers_gained": int(row[3] or 0),
        "comments": int(row[4] or 0),
        "collected_at": now or datetime.now().astimezone().isoformat(),
    }
    if published_at:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        collected = datetime.fromisoformat(metrics["collected_at"].replace("Z", "+00:00"))
        metrics["age_hours"] = round((collected - published).total_seconds() / 3600, 2)
    elif rows:
        try:
            if youtube_client is None:
                from ..publish.youtube_auth import get_youtube_client

                youtube_client = get_youtube_client()
            metadata = youtube_client.videos().list(part="snippet", id=youtube_id).execute()
            published_at = (metadata.get("items") or [{}])[0].get("snippet", {}).get("publishedAt")
            if published_at:
                published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                collected = datetime.fromisoformat(metrics["collected_at"].replace("Z", "+00:00"))
                metrics["age_hours"] = round((collected - published).total_seconds() / 3600, 2)
        except Exception:  # metadata is supportive; never turn it into a false verdict
            metrics["age_hours"] = 0
    elif not rows:
        # Scheduled/private/new videos return no Analytics row.  It is not a
        # performance verdict, so prevent the feedback loop from dropping it.
        metrics["age_hours"] = 0
    return (store or AnalyticsStore()).record(slug, metrics)
