"""Persistent, process-safe catalog for licensed stock-footage reuse."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config.settings import settings
from ..orchestrator.state_io import locked_json_update


_QUERY_TOKEN = re.compile(r"[a-z0-9]+")
_GENERIC_QUERY_TOKENS = frozenset({
    "and", "at", "for", "from", "into", "of", "on", "or", "person",
    "the", "then", "using", "with",
})


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

    def assets_readonly(self) -> list[dict[str, Any]]:
        """Read catalog records without taking a write lock or touching disk state."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        assets = raw.get("assets", {}) if isinstance(raw, dict) else {}
        return [dict(asset) for asset in assets.values() if isinstance(asset, dict)] if isinstance(assets, dict) else []

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

    def select_local_assets(
        self,
        query: str,
        *,
        orientation: str,
        excluded: set[str] | None = None,
        role: str = "body",
        assets: list[dict[str, Any]] | None = None,
    ) -> list[tuple[str, Path]]:
        """Return usable local footage, ranked by relevance then least recent reuse.

        The catalog is the source of provenance, so untracked files are never
        selected blindly. This keeps local reuse license-traceable and lets the
        renderer avoid a Pexels request whenever its known library has footage.
        """
        excluded = excluded or set()
        query_tokens = _meaningful_tokens(query)
        candidates: list[tuple[dict[str, Any], Path, int]] = []
        for asset in (assets if assets is not None else self.assets()):
            source_url = asset.get("source_url")
            local_path = asset.get("local_path")
            if (
                not isinstance(source_url, str)
                or source_url in excluded
                or asset.get("orientation") != orientation
                or not isinstance(local_path, str)
            ):
                continue
            path = Path(local_path)
            if not path.is_file() or path.stat().st_size <= 0:
                continue
            topics = asset.get("topics", [])
            topic_tokens = set().union(
                *(_meaningful_tokens(topic) for topic in topics if isinstance(topic, str))
            ) if topics else set()
            candidates.append((asset, path, len(query_tokens & topic_tokens)))

        def rank(item: tuple[dict[str, Any], Path, int]) -> tuple[int, int, int, int, str]:
            asset, _, relevance = item
            uses = asset.get("uses", []) if isinstance(asset.get("uses"), list) else []
            recent = uses[-20:]
            same_role = sum(1 for usage in recent if usage.get("role") == role)
            return (-relevance, same_role, len(recent), len(uses), asset["asset_id"])

        return [
            (asset["source_url"], path)
            for asset, path, _ in sorted(candidates, key=rank)
        ]

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


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token for token in _QUERY_TOKEN.findall(text.lower())
        if len(token) > 2 and token not in _GENERIC_QUERY_TOKENS
    }
