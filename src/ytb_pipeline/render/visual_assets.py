"""Prepared visual boundary for character-story renders.

This is the only production component allowed to resolve or generate story
images.  The renderer receives verified ``AssetRecord`` paths and composites
them; it deliberately has no provider or cache dependency.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config.settings import settings
from ..providers.image.comfyui_story_provider import SAMPLER, SCHEDULER
from .asset_registry import AssetRegistry, content_sha256 as observed_content_sha256

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile
    from ..pkg.models import Segment, Voiceover
    from .scene_plan import ScenePlan, Shot


@dataclass(frozen=True)
class VisualRequest:
    """Provider-neutral semantic need of a single ScenePlan shot."""
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
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def build_visual_requests(scene_plan: "ScenePlan", profile: "ContentProfile", *, dimensions: tuple[int, int]) -> tuple[VisualRequest, ...]:
    """Pure, deterministic ``ScenePlan + profile -> VisualRequest[]``."""
    policy = "generated" if getattr(getattr(profile, "visual_generation", None), "enabled", False) else "local"
    requests: list[VisualRequest] = []
    for scene in scene_plan.scenes:
        for shot in scene.shots:
            kind = "profile_local" if shot.visual_asset else "generated_image"
            fingerprint = _fingerprint(
                profile.profile_id, profile.version, policy, kind, scene.scene_id,
                shot.shot_id, shot.visual_intent.strip(), ",".join(shot.scene_characters),
                f"{dimensions[0]}x{dimensions[1]}",
            )
            requests.append(VisualRequest(
                request_id=f"vr_{fingerprint[:24]}", request_fingerprint=fingerprint,
                scene_id=scene.scene_id, shot_id=shot.shot_id,
                visual_intent=shot.visual_intent, characters=shot.scene_characters,
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


@dataclass
class VisualManifest:
    source_fingerprint: str
    shots: dict[str, VisualManifestEntry] = field(default_factory=dict)

    def _attempts(self, shot_id: str) -> int:
        return self.shots.get(shot_id, VisualManifestEntry("", "")).attempt_count + 1

    def mark_running(self, shot_id: str, *, request_id: str, request_fingerprint: str) -> None:
        self.shots[shot_id] = VisualManifestEntry(request_id, request_fingerprint, "running", None, self._attempts(shot_id))

    def mark_done(self, shot_id: str, *, request_id: str, request_fingerprint: str, asset_id: str) -> None:
        self.shots[shot_id] = VisualManifestEntry(request_id, request_fingerprint, "done", asset_id, self._attempts(shot_id))

    def mark_failed(self, shot_id: str, *, request_id: str, request_fingerprint: str, error: str) -> None:
        self.shots[shot_id] = VisualManifestEntry(request_id, request_fingerprint, "failed", None, self._attempts(shot_id), error)

    def is_reusable(self, shot_id: str, *, request_fingerprint: str, asset_path: Path, content_sha256: str) -> bool:
        entry = self.shots.get(shot_id)
        return bool(entry and entry.status == "done" and entry.request_fingerprint == request_fingerprint and asset_path.is_file() and observed_content_sha256(asset_path) == content_sha256)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"source_fingerprint": self.source_fingerprint, "shots": {key: asdict(value) for key, value in self.shots.items()}}
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def read_json(cls, path: Path) -> "VisualManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["source_fingerprint"], {key: VisualManifestEntry(**value) for key, value in data.get("shots", {}).items()})


def validate_prepared_manifest(manifest: VisualManifest, requests: tuple[VisualRequest, ...], registry: AssetRegistry) -> dict[str, Path]:
    """Fail closed unless every request maps to an intact registered asset."""
    prepared: dict[str, Path] = {}
    for request in requests:
        entry = manifest.shots.get(request.shot_id)
        if entry is None or entry.status != "done" or entry.request_fingerprint != request.request_fingerprint or not entry.asset_id:
            raise ValueError(f"Visual manifest chưa hoàn tất shot {request.shot_id}.")
        record = registry.find_by_asset_id(entry.asset_id)
        if record is None:
            raise ValueError(f"Visual manifest tham chiếu AssetRecord thiếu: {entry.asset_id}")
        asset_path = Path(record["local_path"])
        if not manifest.is_reusable(request.shot_id, request_fingerprint=request.request_fingerprint, asset_path=asset_path, content_sha256=record["content_sha256"]):
            raise ValueError(f"Visual asset stale: {request.shot_id}")
        prepared[request.shot_id] = asset_path
    return prepared


_SDXL_GENERATION_DIMS = {(1920, 1080): (1344, 768), (1080, 1920): (832, 1216)}


def _generation_key(segment: "Segment", profile: "ContentProfile", dimensions: tuple[int, int]) -> str:
    visual = profile.visual_generation
    payload = "\x1f".join((profile.profile_id, profile.version, f"{dimensions[0]}x{dimensions[1]}", ",".join(sorted(segment.scene_characters)), segment.visual_intent.strip(), visual.style_prompt, visual.negative_prompt, str(visual.steps), str(visual.cfg), str(visual.solo_weight), str(visual.duo_weight), str(visual.duo_denoise)))
    return hashlib.sha256(payload.encode()).hexdigest()


def _generation_mode(characters: tuple[str, ...]) -> str:
    return {0: "establishing", 1: "solo", 2: "duo"}.get(len(characters), "duo")


class VisualAssetResolver:
    """The single local/cache/ComfyUI/registry decision owner."""

    def __init__(self, profile: "ContentProfile", *, registry: AssetRegistry | None = None, cache_dir: Path | None = None, provider: Any = None) -> None:
        self.profile, self.registry, self.cache_dir, self.provider = profile, registry or AssetRegistry(), cache_dir, provider

    def resolve(self, request: VisualRequest, segment: "Segment", shot: "Shot", *, video_slug: str) -> dict[str, Any]:
        if request.resolution_kind == "profile_local":
            asset_path = self.profile.visual_asset_path(shot.visual_asset)
            asset_id = self.registry.record_local_asset(profile_id=self.profile.profile_id, profile_version=self.profile.version, relative_path=shot.visual_asset, local_path=asset_path, scene_id=request.scene_id, shot_id=request.shot_id, video_slug=video_slug)
            record = self.registry.find_by_asset_id(asset_id)
            assert record is not None
            return record
        visual = self.profile.visual_generation
        if visual is None or not visual.enabled:
            raise ValueError(f"Section thiếu visual_asset và profile '{self.profile.profile_id}' không bật visual_generation — không có ảnh nào để dùng.")
        key = _generation_key(segment, self.profile, request.dimensions)
        cache_dir = self.cache_dir or settings.assets_dir / "generated_visuals" / self.profile.profile_id
        asset_path = Path(cache_dir) / f"{key}.png"
        generated_dimensions = _SDXL_GENERATION_DIMS[request.dimensions]
        seed = int(key[:16], 16) % (2**32)
        characters = tuple(dict.fromkeys(segment.scene_characters))
        fresh = not asset_path.is_file()
        if fresh:
            provider = self.provider
            if provider is None:
                from ..providers.registry import get_story_image_provider
                provider = get_story_image_provider()
            provider.generate_scene(self.profile, characters_present=tuple(segment.scene_characters), prompt=segment.visual_intent.strip(), width=generated_dimensions[0], height=generated_dimensions[1], seed=seed, output_path=asset_path)
        asset_id = self.registry.record_generated(generation_key=key, local_path=asset_path, is_fresh_generation=fresh, profile_id=self.profile.profile_id, profile_version=self.profile.version, seed=seed, prompt=segment.visual_intent.strip(), style_prompt=visual.style_prompt, negative_prompt=visual.negative_prompt, steps=visual.steps, cfg=visual.cfg, width=generated_dimensions[0], height=generated_dimensions[1], characters=characters, generation_mode=_generation_mode(characters), checkpoint=settings.comfyui_sdxl_checkpoint, clip_vision_model=settings.comfyui_clip_vision_model, ipadapter_model=settings.comfyui_ipadapter_model, solo_weight=visual.solo_weight, duo_weight=visual.duo_weight, duo_denoise=visual.duo_denoise, sampler=SAMPLER, scheduler=SCHEDULER, scene_id=request.scene_id, shot_id=request.shot_id, video_slug=video_slug)
        record = self.registry.find_by_asset_id(asset_id)
        assert record is not None
        return record


def prepare_visual_assets(voiceover: "Voiceover", profile: "ContentProfile", *, project_dir: Path, dimensions: tuple[int, int], registry: AssetRegistry | None = None, cache_dir: Path | None = None, provider: Any = None) -> tuple["ScenePlan", VisualManifest, dict[str, Path]]:
    """Checkpoint each resolved shot; failures preserve earlier completed shots."""
    from .scene_plan import build_story_scene_plan
    project_dir.mkdir(parents=True, exist_ok=True)
    plan = build_story_scene_plan(voiceover, profile)
    plan.write_json(project_dir / "scene_plan.json")
    requests = build_visual_requests(plan, profile, dimensions=dimensions)
    manifest_path = project_dir / "visual_manifest.json"
    manifest = VisualManifest.read_json(manifest_path) if manifest_path.is_file() else VisualManifest(plan.source_fingerprint)
    registry = registry or AssetRegistry()
    resolver = VisualAssetResolver(profile, registry=registry, cache_dir=cache_dir, provider=provider)
    shots = {shot.shot_id: (scene, shot) for scene in plan.scenes for shot in scene.shots}
    prepared: dict[str, Path] = {}
    for request in requests:
        existing = manifest.shots.get(request.shot_id)
        if existing and existing.asset_id:
            record = registry.find_by_asset_id(existing.asset_id)
            if record and manifest.is_reusable(request.shot_id, request_fingerprint=request.request_fingerprint, asset_path=Path(record["local_path"]), content_sha256=record["content_sha256"]):
                prepared[request.shot_id] = Path(record["local_path"])
                continue
        scene, shot = shots[request.shot_id]
        manifest.mark_running(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint)
        manifest.write_json(manifest_path)
        try:
            record = resolver.resolve(request, voiceover.segments[scene.source_segment_index], shot, video_slug=voiceover.project_id or project_dir.name)
            manifest.mark_done(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint, asset_id=record["asset_id"])
            manifest.write_json(manifest_path)
            prepared[request.shot_id] = Path(record["local_path"])
        except Exception as exc:
            manifest.mark_failed(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint, error=str(exc))
            manifest.write_json(manifest_path)
            raise
    return plan, manifest, validate_prepared_manifest(manifest, requests, registry)
