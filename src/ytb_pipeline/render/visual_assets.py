"""Prepared visual boundary for character-story renders.

This module deliberately owns resolution/generation.  A renderer receives its
manifest and only composites the recorded files; it never makes a ComfyUI call.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .asset_registry import AssetRegistry, content_sha256 as observed_content_sha256

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile
    from .scene_plan import ScenePlan


@dataclass(frozen=True)
class VisualRequest:
    request_id: str
    request_fingerprint: str
    scene_id: str
    shot_id: str
    visual_intent: str
    characters: tuple[str, ...]
    dimensions: tuple[int, int]
    resolution_kind: str
    semantic_constraints: tuple[str, ...] = ()


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def build_visual_requests(scene_plan: "ScenePlan", profile: "ContentProfile", *, dimensions: tuple[int, int]) -> tuple[VisualRequest, ...]:
    """Pure deterministic ScenePlan + profile -> one request per v1 shot."""
    requests = []
    policy = "generated" if getattr(getattr(profile, "visual_generation", None), "enabled", False) else "local"
    for scene in scene_plan.scenes:
        for shot in scene.shots:
            kind = "profile_local" if shot.visual_asset else "generated_image"
            fp = _fingerprint(profile.profile_id, profile.version, policy, scene.scene_id, shot.shot_id,
                              shot.visual_intent.strip(), ",".join(shot.scene_characters), f"{dimensions[0]}x{dimensions[1]}", kind)
            requests.append(VisualRequest(
                request_id=f"vr_{fp[:24]}", request_fingerprint=fp, scene_id=scene.scene_id,
                shot_id=shot.shot_id, visual_intent=shot.visual_intent, characters=shot.scene_characters,
                dimensions=dimensions, resolution_kind=kind,
            ))
    return tuple(requests)


@dataclass(frozen=True)
class VisualManifestEntry:
    request_id: str
    request_fingerprint: str
    status: str = "pending"
    asset_id: str | None = None
    attempt_count: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class VisualManifest:
    source_fingerprint: str
    shots: dict[str, VisualManifestEntry] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.shots is None:
            object.__setattr__(self, "shots", {})

    def mark_done(self, shot_id: str, *, request_id: str, request_fingerprint: str, asset_id: str) -> None:
        self.shots[shot_id] = VisualManifestEntry(request_id, request_fingerprint, "done", asset_id, self.shots.get(shot_id, VisualManifestEntry(request_id, request_fingerprint)).attempt_count + 1)

    def is_reusable(self, shot_id: str, *, request_fingerprint: str, asset_path: Path, content_sha256: str) -> bool:
        entry = self.shots.get(shot_id)
        return bool(entry and entry.status == "done" and entry.request_fingerprint == request_fingerprint and asset_path.is_file() and observed_content_sha256(asset_path) == content_sha256)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"source_fingerprint": self.source_fingerprint, "shots": {k: asdict(v) for k, v in self.shots.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def read_json(cls, path: Path) -> "VisualManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["source_fingerprint"], {k: VisualManifestEntry(**v) for k, v in data.get("shots", {}).items()})


def validate_prepared_manifest(manifest: VisualManifest, requests: tuple[VisualRequest, ...], registry: AssetRegistry) -> dict[str, Path]:
    """Return prepared paths or fail closed; only affected stale entries fail."""
    prepared: dict[str, Path] = {}
    for request in requests:
        entry = manifest.shots.get(request.shot_id)
        if entry is None or entry.status != "done" or entry.request_fingerprint != request.request_fingerprint or not entry.asset_id:
            raise ValueError(f"Visual manifest chưa hoàn tất shot {request.shot_id}.")
        record = registry.find_by_asset_id(entry.asset_id)
        if record is None:
            raise ValueError(f"Visual manifest tham chiếu AssetRecord thiếu: {entry.asset_id}")
        path = Path(record["local_path"])
        if not manifest.is_reusable(request.shot_id, request_fingerprint=request.request_fingerprint, asset_path=path, content_sha256=record["content_sha256"]):
            raise ValueError(f"Visual asset stale: {request.shot_id}")
        prepared[request.shot_id] = path
    return prepared


def prepare_visual_assets(voiceover, profile, *, project_dir: Path, dimensions: tuple[int, int]) -> tuple["ScenePlan", VisualManifest, dict[str, Path]]:
    """Resolve every story shot once, checkpointing each completed observation.

    Kept here (rather than in ``story``) so ComfyUI/cache/registry side effects
    are a pre-render stage. A previous valid entry is never regenerated.
    """
    from .scene_plan import build_story_scene_plan
    from .story import resolve_scene_image
    project_dir.mkdir(parents=True, exist_ok=True)
    plan = build_story_scene_plan(voiceover, profile)
    plan.write_json(project_dir / "scene_plan.json")
    requests = build_visual_requests(plan, profile, dimensions=dimensions)
    path = project_dir / "visual_manifest.json"
    manifest = VisualManifest.read_json(path) if path.is_file() else VisualManifest(plan.source_fingerprint)
    registry = AssetRegistry()
    prepared: dict[str, Path] = {}
    for request, scene in zip(requests, plan.scenes):
        try:
            entry = manifest.shots.get(request.shot_id)
            if entry and entry.asset_id:
                record = registry.find_by_asset_id(entry.asset_id)
                if record and manifest.is_reusable(request.shot_id, request_fingerprint=request.request_fingerprint, asset_path=Path(record["local_path"]), content_sha256=record["content_sha256"]):
                    prepared[request.shot_id] = Path(record["local_path"])
                    continue
            segment = voiceover.segments[scene.source_segment_index]
            image = resolve_scene_image(segment, profile, dimensions, scene_id=request.scene_id, shot_id=request.shot_id, video_slug=voiceover.project_id or "", registry=registry)
            record = next((a for a in registry.assets() if a.get("local_path") == str(image.resolve()) and any(u.get("shot_id") == request.shot_id for u in a.get("uses", []))), None)
            if record is None:
                raise ValueError(f"AssetRegistry không ghi được shot {request.shot_id}")
            manifest.mark_done(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint, asset_id=record["asset_id"])
            manifest.write_json(path)
            prepared[request.shot_id] = image
        except Exception as exc:
            previous = manifest.shots.get(request.shot_id)
            manifest.shots[request.shot_id] = VisualManifestEntry(request.request_id, request.request_fingerprint, "failed", None, (previous.attempt_count if previous else 0) + 1, str(exc))
            manifest.write_json(path)
            raise
    return plan, manifest, validate_prepared_manifest(manifest, requests, registry)
