"""Durable, process-safe provenance/catalog registry for `character_story`
generated visual assets.

    ScenePlan -> existing story visual resolution -> ComfyUI / existing asset
        -> physical asset file -> AssetRegistry -> filesystem path (renderer)

Phase 3.1 is additive observability/reproducibility, not a provider
redesign: `render/story.py`'s existing generation, caching, and ComfyUI
behaviour is completely unchanged by this module. `resolve_scene_image`
still resolves and returns a `Path` exactly as before; the registry only
RECORDS what already happened, alongside it — the renderer keeps consuming
paths.

Four concepts, kept deliberately independent (Phase 3.1 corrective
directive — Phase 3's first attempt wrongly derived `asset_id`
deterministically from `generation_key`, making them 1:1 in practice):

    asset_id          opaque identity of ONE concrete registered record
                       (a `uuid4`, unrelated to content or request identity —
                       reproducibility comes from the provenance fields a
                       record carries, not from a deterministic record ID)
    content_sha256    identity of the actual bytes observed AT REGISTRATION
                       TIME — the concrete-asset matching key. Two different
                       physical results (e.g. the same generation_key
                       regenerated after a checkpoint change) get two
                       different content_sha256 values and therefore two
                       different AssetRecords, even though they share one
                       generation_key.
    generation_key    identity of the semantic generation/cache REQUEST
                       (== the existing `_generation_cache_key` in
                       story.py). One `generation_key` may map to zero, one,
                       or MANY `AssetRecord`s over the asset's history —
                       never assume 1:1. Use `find_by_generation_key` (a
                       list), never a single-record lookup.
    local_path        a LOCATOR, not an identity. Bytes at a path can change
                       (file replaced) without that silently mutating an
                       existing record's historical provenance — matching
                       is always done by content, never by path alone.

Provenance is immutable once registered: `record_generated`/
`record_local_asset` never overwrite an existing record's provenance
fields — a cache hit against an already-registered physical asset only
appends a new `uses` entry, and a legacy asset is never silently
"upgraded" to complete provenance just because current settings happen to
be reconstructable.

Three provenance classes (`asset_class`), because they mean genuinely
different things:

    generated          fresh ComfyUI result THIS call actually produced —
                        complete, currently-known generation metadata.
    legacy_generated    a cache HIT with no prior registry record. The file
                        may predate Phase 3, or have been produced by a
                        different checkpoint/provider version behind the
                        same deterministic cache filename — its true
                        original generation parameters are NOT certain, so
                        none are fabricated. `provenance_status=
                        "legacy_unknown"`.
    profile_local       a fixed, hand-placed profile asset
                        (`Segment.visual_asset`) — never generated here, so
                        it has no generation metadata to record at all, but
                        its OWN provenance (which file, which profile) is
                        fully known: `provenance_status="complete"`.

Concurrency: two batch workers can render different projects at the same
time and both touch this shared file. `locked_json_update` (already used
by `render/asset_catalog.py` for the same class of problem) takes an
exclusive `fcntl.flock` on a sidecar `.lock` file and writes atomically
(tmpfile + rename), so upserts never interleave or corrupt the file —
proven safe across real OS processes in
`tests/test_asset_registry.py::test_concurrent_registration_across_real_os_processes_is_safe`
and across the locking primitive itself in `tests/test_state_io.py`.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config.settings import settings
from ..orchestrator.state_io import locked_json_update


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def content_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _new_asset_id() -> str:
    """Opaque, non-deterministic record identity — see module docstring.

    Deliberately NOT derived from `generation_key`/`content_sha256`/path:
    a deterministic ID would force a 1:1 relationship between a record and
    whichever input it was derived from, which is exactly the Phase 3
    defect this corrective phase removes. Reproducibility is carried by
    the record's provenance FIELDS, not by its ID.
    """
    return f"ast_{uuid.uuid4().hex}"


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

    def find_by_content_sha256(self, content_sha256_value: str) -> dict[str, Any] | None:
        for asset in self.assets():
            if asset.get("content_sha256") == content_sha256_value:
                return asset
        return None

    def find_by_generation_key(self, generation_key: str) -> list[dict[str, Any]]:
        """A `generation_key` may legitimately map to MANY records — never a
        single one. Callers must not assume 1:1."""
        return [a for a in self.assets() if a.get("generation_key") == generation_key]

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

    def _upsert_by_content(
        self, *, local_path: Path, scene_id: str, shot_id: str, video_slug: str,
        build_new_record: "Any",
    ) -> str:
        """Shared upsert core: match by `content_sha256` against every
        existing record BEFORE creating a new one, so the exact same
        physical asset reused anywhere never duplicates its record — only
        gains a new `uses` entry. Provenance fields of an existing match
        are NEVER touched (immutability — see module docstring)."""
        local_path = Path(local_path)
        sha256 = content_sha256(local_path)
        with locked_json_update(self.path) as data:
            assets = data.setdefault("assets", {})
            if not isinstance(assets, dict):
                raise ValueError(f"Asset registry {self.path} có payload assets không hợp lệ")
            existing = next(
                (asset for asset in assets.values() if asset.get("content_sha256") == sha256),
                None,
            )
            if existing is not None:
                self._record_use(existing, scene_id=scene_id, shot_id=shot_id, video_slug=video_slug)
                return existing["asset_id"]

            asset_id = _new_asset_id()
            record = build_new_record(asset_id=asset_id, content_sha256_value=sha256)
            record.setdefault("uses", [])
            assets[asset_id] = record
            self._record_use(record, scene_id=scene_id, shot_id=shot_id, video_slug=video_slug)
            return asset_id

    def record_generated(
        self,
        *,
        generation_key: str,
        local_path: Path,
        is_fresh_generation: bool,
        profile_id: str,
        profile_version: str,
        seed: int | None = None,
        prompt: str | None = None,
        style_prompt: str | None = None,
        negative_prompt: str | None = None,
        steps: int | None = None,
        cfg: float | None = None,
        width: int | None = None,
        height: int | None = None,
        characters: tuple[str, ...] = (),
        generation_mode: str | None = None,
        checkpoint: str | None = None,
        clip_vision_model: str | None = None,
        ipadapter_model: str | None = None,
        solo_weight: float | None = None,
        duo_weight: float | None = None,
        duo_denoise: float | None = None,
        sampler: str | None = None,
        scheduler: str | None = None,
        scene_id: str,
        shot_id: str,
        video_slug: str,
    ) -> str:
        """Register (or reuse, by physical content) a ComfyUI-path visual.

        `is_fresh_generation=True`: this call's provider request just
        produced these exact bytes — record COMPLETE, currently-known
        generation metadata (`asset_class="generated"`,
        `provenance_status="complete"`).

        `is_fresh_generation=False`: this is a cache HIT. If the physical
        file is already registered, this only adds a `uses` entry (its
        provenance, whatever it is, is untouched). If it is NOT already
        registered, the file predates this registry (or an earlier,
        uninstrumented code path) — its true original generation
        parameters are not certain, so NONE of the generation-detail
        arguments above are persisted, only what genuinely is known right
        now (`generation_key`, `content_sha256`, `local_path`, profile
        identity): `asset_class="legacy_generated"`,
        `provenance_status="legacy_unknown"`.
        """
        def build_new_record(*, asset_id: str, content_sha256_value: str) -> dict:
            if is_fresh_generation:
                return {
                    "asset_id": asset_id,
                    "asset_class": "generated",
                    "provenance_status": "complete",
                    "generation_key": generation_key,
                    "content_sha256": content_sha256_value,
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
                    "generation_mode": generation_mode,
                    "checkpoint": checkpoint,
                    "clip_vision_model": clip_vision_model,
                    "ipadapter_model": ipadapter_model,
                    "solo_weight": solo_weight,
                    "duo_weight": duo_weight,
                    "duo_denoise": duo_denoise,
                    "sampler": sampler,
                    "scheduler": scheduler,
                    "registered_at": _now_iso(),
                    "uses": [],
                }
            return {
                "asset_id": asset_id,
                "asset_class": "legacy_generated",
                "provenance_status": "legacy_unknown",
                "generation_key": generation_key,
                "content_sha256": content_sha256_value,
                "local_path": str(local_path),
                "profile_id": profile_id,
                "profile_version": profile_version,
                "registered_at": _now_iso(),
                "uses": [],
            }

        return self._upsert_by_content(
            local_path=local_path, scene_id=scene_id, shot_id=shot_id,
            video_slug=video_slug, build_new_record=build_new_record,
        )

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
        """Register (or reuse, by physical content) a fixed profile asset.

        No generation ever happened for this class of asset — recorded as
        `asset_class="profile_local"`, `provenance_status="complete"` (the
        asset's OWN provenance — which file, which profile — is fully
        known), with `generation_key=None` rather than inventing one.
        """
        def build_new_record(*, asset_id: str, content_sha256_value: str) -> dict:
            return {
                "asset_id": asset_id,
                "asset_class": "profile_local",
                "provenance_status": "complete",
                "generation_key": None,
                "content_sha256": content_sha256_value,
                "local_path": str(local_path),
                "relative_path": relative_path,
                "profile_id": profile_id,
                "profile_version": profile_version,
                "registered_at": _now_iso(),
                "uses": [],
            }

        return self._upsert_by_content(
            local_path=local_path, scene_id=scene_id, shot_id=shot_id,
            video_slug=video_slug, build_new_record=build_new_record,
        )
