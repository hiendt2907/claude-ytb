"""Durable, process-safe provenance/catalog registry for `character_story`
generated visual assets.

    ScenePlan -> existing story visual resolution -> ComfyUI / existing asset
        -> physical asset file -> AssetRegistry -> filesystem path (renderer)

Phase 3 is additive observability/reproducibility, not a provider redesign:
`render/story.py`'s existing generation, caching, and ComfyUI behaviour is
completely unchanged by this module. `resolve_scene_image` still resolves
and returns a `Path` exactly as before; the registry only RECORDS what
already happened, alongside it — the renderer keeps consuming paths.

Three identities are kept deliberately distinct, per the Phase 3 directive:

    asset_id          stable opaque identity for THIS REGISTERED RECORD
    content_sha256    hash of the actual asset bytes on disk right now
    generation_key    deterministic identity of the generation/reuse request
                       (== the existing `_generation_cache_key` in story.py)

`asset_id` is derived deterministically from `generation_key` through a
distinct, namespaced hash (never literally equal to either
`content_sha256` or `generation_key`), so that resolving the exact same
request twice — e.g. two different projects reusing the same generated
character illustration — upserts the SAME registry record instead of
creating a duplicate. `content_sha256` is re-read from disk on every upsert
so a record can reveal drift (the same request producing different bytes
after a model/checkpoint change) without that drift changing its identity.

Concurrency: two batch workers can render different projects at the same
time and both touch this shared file. `locked_json_update` (already used by
`render/asset_catalog.py` for the same class of problem) takes an
exclusive `fcntl.flock` on a sidecar `.lock` file and writes atomically
(tmpfile + rename), so upserts never interleave or corrupt the file.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config.settings import settings
from ..orchestrator.state_io import locked_json_update

_ASSET_ID_NAMESPACE = "asset-registry:v1:generation:"
_LOCAL_ASSET_ID_NAMESPACE = "asset-registry:v1:local:"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def asset_id_for_generation_key(generation_key: str) -> str:
    """Deterministic, opaque record identity for a generated asset.

    Namespaced separately from `generation_key` itself so the two values are
    never byte-for-byte equal, even though one is derived from the other.
    """
    return hashlib.sha256(
        f"{_ASSET_ID_NAMESPACE}{generation_key}".encode("utf-8")
    ).hexdigest()[:24]


def asset_id_for_local_path(profile_id: str, relative_path: str) -> str:
    """Deterministic, opaque record identity for a fixed profile asset.

    Fixed assets (`Segment.visual_asset`) are never generated, so they have
    no `generation_key` to derive from — identity comes from where the asset
    lives in the profile instead.
    """
    return hashlib.sha256(
        f"{_LOCAL_ASSET_ID_NAMESPACE}{profile_id}:{relative_path}".encode("utf-8")
    ).hexdigest()[:24]


def content_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AssetRegistry:
    """Upserts `AssetRecord`s and their scene/shot usage history."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.asset_registry_path

    def assets(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with locked_json_update(self.path) as data:
            raw = data.get("assets", {})
            return [dict(asset) for asset in raw.values() if isinstance(asset, dict)]

    def _record_use(self, record: dict, *, scene_id: str, shot_id: str, video_slug: str) -> None:
        used_at = _now_iso()
        uses = record.setdefault("uses", [])
        already = any(
            usage.get("scene_id") == scene_id
            and usage.get("shot_id") == shot_id
            and usage.get("video_slug") == video_slug
            for usage in uses
        )
        if not already:
            uses.append({
                "scene_id": scene_id, "shot_id": shot_id,
                "video_slug": video_slug, "used_at": used_at,
            })

    def record_generated(
        self,
        *,
        generation_key: str,
        local_path: Path,
        profile_id: str,
        profile_version: str,
        seed: int,
        prompt: str,
        style_prompt: str,
        negative_prompt: str,
        steps: int,
        cfg: float,
        width: int,
        height: int,
        characters: tuple[str, ...],
        scene_id: str,
        shot_id: str,
        video_slug: str,
    ) -> str:
        """Upsert an `AssetRecord` for a ComfyUI-generated visual.

        Called on BOTH a fresh generation and a cache hit: the same
        `generation_key` formula that already drives `story.py`'s cache
        reconstructs the exact request parameters either way, so a cache
        hit is not "incomplete provenance" — the request that would have
        produced this exact file is fully known.
        """
        asset_id = asset_id_for_generation_key(generation_key)
        local_path = Path(local_path)
        sha256 = content_sha256(local_path)
        with locked_json_update(self.path) as data:
            assets = data.setdefault("assets", {})
            if not isinstance(assets, dict):
                raise ValueError(f"Asset registry {self.path} có payload assets không hợp lệ")
            record = assets.setdefault(asset_id, {
                "asset_id": asset_id,
                "generation_key": generation_key,
                "source": "comfyui_story_generated",
                "provenance_complete": True,
                "registered_at": _now_iso(),
                "uses": [],
            })
            record.update({
                "content_sha256": sha256,
                "local_path": str(local_path),
                "profile_id": profile_id,
                "profile_version": profile_version,
                "seed": seed,
                "prompt": prompt,
                "style_prompt": style_prompt,
                "negative_prompt": negative_prompt,
                "steps": steps,
                "cfg": cfg,
                "width": width,
                "height": height,
                "characters": list(characters),
            })
            self._record_use(record, scene_id=scene_id, shot_id=shot_id, video_slug=video_slug)
        return asset_id

    def record_local_asset(
        self,
        *,
        profile_id: str,
        profile_version: str,
        relative_path: str,
        local_path: Path,
        scene_id: str,
        shot_id: str,
        video_slug: str,
    ) -> str:
        """Upsert an `AssetRecord` for a fixed, hand-placed profile asset.

        No generation parameters exist for this class of asset — recorded
        as `provenance_complete=False` with `generation_key=None` rather
        than inventing a seed/prompt that was never used.
        """
        asset_id = asset_id_for_local_path(profile_id, relative_path)
        local_path = Path(local_path)
        sha256 = content_sha256(local_path)
        with locked_json_update(self.path) as data:
            assets = data.setdefault("assets", {})
            if not isinstance(assets, dict):
                raise ValueError(f"Asset registry {self.path} có payload assets không hợp lệ")
            record = assets.setdefault(asset_id, {
                "asset_id": asset_id,
                "generation_key": None,
                "source": "profile_local_asset",
                "provenance_complete": False,
                "registered_at": _now_iso(),
                "uses": [],
            })
            record.update({
                "content_sha256": sha256,
                "local_path": str(local_path),
                "relative_path": relative_path,
                "profile_id": profile_id,
                "profile_version": profile_version,
            })
            self._record_use(record, scene_id=scene_id, shot_id=shot_id, video_slug=video_slug)
        return asset_id
