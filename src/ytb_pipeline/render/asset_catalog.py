"""Persistent, process-safe catalog for licensed stock-footage reuse."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config.settings import settings
from ..orchestrator.state_io import locked_json_update


class AssetCatalog:
    """Records provenance and usage, then ranks candidate Pexels URLs by reuse."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.asset_catalog_path

    def assets(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with locked_json_update(self.path) as data:
            raw = data.get("assets", {})
            return [dict(asset) for asset in raw.values() if isinstance(asset, dict)]

    def select_urls(
        self,
        urls: list[str],
        *,
        excluded: set[str] | None = None,
        role: str = "body",
    ) -> list[str]:
        """Rank new/least-recently-used URLs, excluding shots already in this video."""
        excluded = excluded or set()
        records = {asset.get("source_url"): asset for asset in self.assets()}
        candidates = [url for url in urls if url not in excluded]

        def rank(url: str) -> tuple[int, int, int, int]:
            asset = records.get(url, {})
            uses = asset.get("uses", []) if isinstance(asset, dict) else []
            recent = uses[-20:] if isinstance(uses, list) else []
            same_role = sum(1 for usage in recent if usage.get("role") == role)
            return (0 if asset else -1, same_role, len(recent), len(uses))

        return sorted(candidates, key=rank)

    def record_usage(
        self,
        *,
        source_url: str,
        local_path: Path,
        query: str,
        orientation: str,
        video_slug: str,
        role: str,
        duration_sec: float = 0.0,
    ) -> None:
        """Upsert a Pexels asset and append a traceable video-use record."""
        asset_id = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
        used_at = datetime.now(UTC).isoformat()
        with locked_json_update(self.path) as data:
            assets = data.setdefault("assets", {})
            if not isinstance(assets, dict):
                raise ValueError(f"Asset catalog {self.path} has invalid assets payload")
            asset = assets.setdefault(asset_id, {
                "asset_id": asset_id,
                "source": "pexels",
                "license": "Pexels License",
                "source_url": source_url,
                "local_path": str(local_path),
                "topics": [],
                "orientation": orientation,
                "duration_sec": duration_sec,
                "uses": [],
            })
            asset["local_path"] = str(local_path)
            asset["orientation"] = orientation
            asset["duration_sec"] = duration_sec
            topics = asset.setdefault("topics", [])
            if query and query not in topics:
                topics.append(query)
            uses = asset.setdefault("uses", [])
            if not any(
                usage.get("video_slug") == video_slug and usage.get("role") == role
                for usage in uses
            ):
                uses.append({"video_slug": video_slug, "role": role, "used_at": used_at})
