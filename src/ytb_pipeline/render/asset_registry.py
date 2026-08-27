"""Durable, process-safe provenance/catalog registry for `character_story`
generated visual assets.

    ScenePlan -> existing story visual resolution -> ComfyUI / existing asset
        -> physical asset file -> AssetRegistry -> filesystem path (renderer)

Phase 3.2 is additive observability/reproducibility, not a provider
redesign: `render/story.py`'s existing generation, caching, and ComfyUI
behaviour is completely unchanged by this module. `resolve_scene_image`
still resolves and returns a `Path` exactly as before; the registry only
RECORDS what already happened, alongside it — the renderer keeps consuming
paths.

Locked identity model — four concepts, kept fully independent:

    asset_id          opaque identity of ONE registered concrete asset/
                       provenance record (a `uuid4`, unrelated to content,
                       request, or path identity — reproducibility comes
                       from a record's provenance FIELDS, not from its ID
                       being derivable from anything).
    content_sha256    identity/EVIDENCE of the bytes observed AT
                       REGISTRATION TIME. It is an INDEX (`find_by_
                       content_sha256` returns a list), never a primary
                       key: identical bytes prove byte equality, nothing
                       else — not same provenance, not same generation
                       event, not same asset class, not same generation
                       request, not same physical/cache entry.
    generation_key    identity of the semantic generation/cache REQUEST
                       (== the existing `_generation_cache_key` in
                       story.py). One `generation_key` may map to zero,
                       one, or MANY `AssetRecord`s — `find_by_generation_
                       key` always returns a list.
    local_path        a LOCATOR, not an identity. Bytes at a path can
                       change (file replaced) without that silently
                       mutating an existing record's historical
                       provenance.

Phase 3.1's own fix (removing a deterministic `asset_id` derived from
`generation_key`) was correct but incomplete: it then used
`content_sha256` ALONE as a universal upsert/dedup key, which is exactly
the same class of mistake one level down — "same bytes" was being treated
as "same record identity". This phase (3.2) replaces that with EXACT
OBSERVATION matching: reusing an existing record requires evidence that
the SAME CONCRETE OBSERVED ARTIFACT is being seen again — `local_path` +
`content_sha256` + a compatible provenance class (+ `generation_key`,
+ `seed` for a fresh-generation event) — never bytes alone. See
`_match_generation_observation`/`_match_profile_local_observation` below
for the exact rules, and
`docs/handoffs/2026-08-27-asset-registry-phase3.2-handoff.md` for the
worked examples (same generation_key/different seeds; same bytes/
different provenance; generated vs legacy vs profile_local never
collapsing).

Provenance is immutable once registered: a record's provenance fields and
`asset_class` are NEVER rewritten after creation — a reuse only appends a
new `uses` entry. A conflicting observation (same locator/hash/generation_
key evidence but a materially different fresh-generation detail such as
`seed`) never silently overwrites the existing record; it creates a new
one, because it represents a distinct historical event.

Three provenance classes (`asset_class`), because they mean genuinely
different things and must never auto-merge into one another:

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
time and both touch this shared file. The full match-then-insert-or-reuse
decision happens inside ONE `locked_json_update` critical section (never
"read, decide, then re-lock to insert" — that would let two racing workers
both create a record for the same cache hit). `locked_json_update`
(already used by `render/asset_catalog.py` for the same class of problem)
takes an exclusive `fcntl.flock` on a sidecar `.lock` file and writes
atomically (tmpfile + rename). `fcntl.flock` is enforced by the kernel per
OPEN FILE DESCRIPTION, not per process, so a thread-based race against the
shared file (each thread opens its own descriptor via `file_lock()`)
exercises the identical kernel-level serialization a second batch-worker
OS process would — see `tests/test_asset_registry.py`'s concurrency tests
(including a same-exact-observation race) for why a real
`multiprocessing`/fork-based variant was tried and reverted: forking a
pytest worker process destabilised unrelated tests elsewhere in the suite.
`tests/test_state_io.py` separately proves the locking primitive itself.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config.settings import settings
from ..orchestrator.state_io import locked_json_update

_GENERATION_ASSET_CLASSES = ("generated", "legacy_generated")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def content_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _normalize_path(path: Path) -> str:
    return str(Path(path))


def _new_asset_id() -> str:
    """Opaque, non-deterministic record identity — see module docstring.

    Deliberately NOT derived from `generation_key`/`content_sha256`/path:
    a deterministic ID would force a 1:1 relationship between a record and
    whichever input it was derived from — the exact defect Phase 3.1
    removed for `generation_key`. Reproducibility is carried by the
    record's provenance FIELDS, not by its ID.
    """
    return f"ast_{uuid.uuid4().hex}"


def _match_generation_observation(
    assets: dict, *, path_str: str, content_sha256_value: str,
    generation_key: str | None, seed_for_fresh_match: int | None,
) -> dict | None:
    """Exact-observation match for a ComfyUI-path visual (fresh or cache-hit).

    Searches `generated` AND `legacy_generated` records — a cache hit may
    legitimately reuse either (that is the "same generated cache file
    reused by project A and B -> one record" case). A FRESH generation
    (`seed_for_fresh_match is not None`) is additionally restricted to only
    ever match within the `generated` class (never silently adopting/
    upgrading a `legacy_generated` record — `asset_class` is immutable),
    AND requires the existing record's `seed` to agree: identical locator/
    hash/generation_key evidence with a CONFLICTING seed means a distinct
    generation event, not a duplicate observation of the same one, and
    must not be merged into the existing record.
    """
    for asset in assets.values():
        if not isinstance(asset, dict):
            continue
        if asset.get("asset_class") not in _GENERATION_ASSET_CLASSES:
            continue
        if asset.get("content_sha256") != content_sha256_value:
            continue
        if asset.get("local_path") != path_str:
            continue
        if asset.get("generation_key") != generation_key:
            continue
        if seed_for_fresh_match is not None:
            if asset.get("asset_class") != "generated":
                continue
            if asset.get("seed") != seed_for_fresh_match:
                continue
        return asset
    return None


def _match_profile_local_observation(
    assets: dict, *, path_str: str, content_sha256_value: str,
) -> dict | None:
    """Exact-observation match for a fixed profile asset.

    Scoped strictly to `asset_class == "profile_local"` — a `generated`/
    `legacy_generated` record with identical bytes must never satisfy this
    lookup (Example C of the Phase 3.2 directive).
    """
    for asset in assets.values():
        if not isinstance(asset, dict):
            continue
        if asset.get("asset_class") != "profile_local":
            continue
        if asset.get("content_sha256") != content_sha256_value:
            continue
        if asset.get("local_path") != path_str:
            continue
        return asset
    return None


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

    def find_by_asset_id(self, asset_id: str) -> dict[str, Any] | None:
        for asset in self.assets():
            if asset.get("asset_id") == asset_id:
                return asset
        return None

    def find_by_content_sha256(self, content_sha256_value: str) -> list[dict[str, Any]]:
        """A SEARCH index, not a primary key: identical bytes may belong to
        MANY `AssetRecord`s with different provenance (see module
        docstring). Never treat this as "the" record for a hash."""
        return [a for a in self.assets() if a.get("content_sha256") == content_sha256_value]

    def find_by_generation_key(self, generation_key: str) -> list[dict[str, Any]]:
        """A `generation_key` may legitimately map to MANY records — never a
        single one. Callers must not assume 1:1."""
        return [a for a in self.assets() if a.get("generation_key") == generation_key]

    def find_exact_observation(
        self, *, path: Path, content_sha256_value: str, asset_class: str,
        generation_key: str | None = None, seed: int | None = None,
    ) -> dict[str, Any] | None:
        """External-facing exact-observation lookup — the SAME matching
        rule the internal upsert path uses, exposed for inspection without
        mutating anything (registering nothing, adding no `uses`)."""
        path_str = _normalize_path(path)
        with locked_json_update(self.path) as data:
            assets = data.get("assets", {})
            if asset_class == "profile_local":
                return _match_profile_local_observation(
                    assets, path_str=path_str, content_sha256_value=content_sha256_value,
                )
            if asset_class in _GENERATION_ASSET_CLASSES:
                return _match_generation_observation(
                    assets, path_str=path_str, content_sha256_value=content_sha256_value,
                    generation_key=generation_key, seed_for_fresh_match=seed,
                )
            raise ValueError(f"asset_class không hợp lệ: {asset_class!r}")

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
        """Register (or reuse, by exact observation) a ComfyUI-path visual.

        `is_fresh_generation=True`: this call's provider request just
        produced these exact bytes. Matches ONLY an existing `generated`
        record with the same `local_path` + `content_sha256` +
        `generation_key` + `seed` (a conflicting `seed` on otherwise
        identical evidence is treated as a DISTINCT generation event, never
        merged — see `_match_generation_observation`). On no match: records
        COMPLETE, currently-known generation metadata
        (`asset_class="generated"`, `provenance_status="complete"`).

        `is_fresh_generation=False`: this is a cache HIT. Matches an
        existing `generated` OR `legacy_generated` record with the same
        `local_path` + `content_sha256` + `generation_key` (this is the
        common "same cached file reused by many projects" path — it
        reuses whichever record already represents that concrete cached
        artifact, WITHOUT touching its provenance/asset_class). On no
        match: the file predates this registry (or an earlier,
        uninstrumented code path) — its true original generation
        parameters are not certain, so NONE of the generation-detail
        arguments above are persisted, only what genuinely is known right
        now (`generation_key`, `content_sha256`, `local_path`, profile
        identity): `asset_class="legacy_generated"`,
        `provenance_status="legacy_unknown"`.

        The match-then-insert-or-reuse decision happens inside one
        `locked_json_update` critical section, so two racing processes
        observing the same concrete artifact can never both create a
        record for it.
        """
        local_path = Path(local_path)
        path_str = _normalize_path(local_path)
        sha256 = content_sha256(local_path)

        with locked_json_update(self.path) as data:
            assets = data.setdefault("assets", {})
            if not isinstance(assets, dict):
                raise ValueError(f"Asset registry {self.path} có payload assets không hợp lệ")

            existing = _match_generation_observation(
                assets, path_str=path_str, content_sha256_value=sha256,
                generation_key=generation_key,
                seed_for_fresh_match=seed if is_fresh_generation else None,
            )
            if existing is not None:
                self._record_use(existing, scene_id=scene_id, shot_id=shot_id, video_slug=video_slug)
                return existing["asset_id"]

            asset_id = _new_asset_id()
            if is_fresh_generation:
                record: dict[str, Any] = {
                    "asset_id": asset_id,
                    "asset_class": "generated",
                    "provenance_status": "complete",
                    "generation_key": generation_key,
                    "content_sha256": sha256,
                    "local_path": path_str,
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
            else:
                record = {
                    "asset_id": asset_id,
                    "asset_class": "legacy_generated",
                    "provenance_status": "legacy_unknown",
                    "generation_key": generation_key,
                    "content_sha256": sha256,
                    "local_path": path_str,
                    "profile_id": profile_id,
                    "profile_version": profile_version,
                    "registered_at": _now_iso(),
                    "uses": [],
                }
            assets[asset_id] = record
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
        """Register (or reuse, by exact observation) a fixed profile asset.

        Matches ONLY an existing `profile_local` record with the same
        `local_path` + `content_sha256` — a `generated`/`legacy_generated`
        record with identical bytes never satisfies this lookup. No
        generation ever happened for this class of asset — recorded as
        `asset_class="profile_local"`, `provenance_status="complete"` (the
        asset's OWN provenance — which file, which profile — is fully
        known), with `generation_key=None` rather than inventing one.
        """
        local_path = Path(local_path)
        path_str = _normalize_path(local_path)
        sha256 = content_sha256(local_path)

        with locked_json_update(self.path) as data:
            assets = data.setdefault("assets", {})
            if not isinstance(assets, dict):
                raise ValueError(f"Asset registry {self.path} có payload assets không hợp lệ")

            existing = _match_profile_local_observation(
                assets, path_str=path_str, content_sha256_value=sha256,
            )
            if existing is not None:
                self._record_use(existing, scene_id=scene_id, shot_id=shot_id, video_slug=video_slug)
                return existing["asset_id"]

            asset_id = _new_asset_id()
            record = {
                "asset_id": asset_id,
                "asset_class": "profile_local",
                "provenance_status": "complete",
                "generation_key": None,
                "content_sha256": sha256,
                "local_path": path_str,
                "relative_path": relative_path,
                "profile_id": profile_id,
                "profile_version": profile_version,
                "registered_at": _now_iso(),
                "uses": [],
            }
            assets[asset_id] = record
            self._record_use(record, scene_id=scene_id, shot_id=shot_id, video_slug=video_slug)
            return asset_id
