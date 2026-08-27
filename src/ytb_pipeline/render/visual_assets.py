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
from .visual_candidates import (
    VisualCandidateStore,
    candidate_cache_path,
    candidate_is_valid,
    logger as _candidate_logger,
    resolve_selection_policy,
    validate_candidate_image,
)
from .visual_evaluation_store import ShotEvaluationSet, VisualEvaluationStore
from .visual_judge import (
    CONTRACT_VERSION as _JUDGE_CONTRACT_VERSION,
    JudgeCandidate,
    JudgeContext,
    JudgeResult,
    logger as _judge_logger,
    select_vlm_ranked,
)

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
    reuse_source: dict[str, str] | None = None


@dataclass
class VisualManifest:
    source_fingerprint: str
    shots: dict[str, VisualManifestEntry] = field(default_factory=dict)

    def _attempts(self, shot_id: str) -> int:
        return self.shots.get(shot_id, VisualManifestEntry("", "")).attempt_count + 1

    def mark_running(self, shot_id: str, *, request_id: str, request_fingerprint: str) -> None:
        self.shots[shot_id] = VisualManifestEntry(request_id, request_fingerprint, "running", None, self._attempts(shot_id))

    def mark_done(self, shot_id: str, *, request_id: str, request_fingerprint: str, asset_id: str, reuse_source: dict[str, str] | None = None) -> None:
        self.shots[shot_id] = VisualManifestEntry(request_id, request_fingerprint, "done", asset_id, self._attempts(shot_id), None, reuse_source)

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

    def __init__(self, profile: "ContentProfile", *, registry: AssetRegistry | None = None, cache_dir: Path | None = None, provider: Any = None, candidate_store: VisualCandidateStore | None = None, judge: Any = None, evaluation_store: VisualEvaluationStore | None = None) -> None:
        self.profile, self.registry, self.cache_dir, self.provider = profile, registry or AssetRegistry(), cache_dir, provider
        self.candidate_store = candidate_store
        # Phase 10 — only consulted when a profile opts into
        # selection_policy="vlm_ranked". No production VisualJudge exists
        # yet (see render/visual_judge.py module docstring); a caller must
        # inject one explicitly (tests do), otherwise a missing judge is
        # itself treated as a judge infrastructure failure, governed by the
        # same `hard_fail_on_judge_error` policy as a real transport error.
        self.judge = judge
        self.evaluation_store = evaluation_store

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
        generated_dimensions = _SDXL_GENERATION_DIMS[request.dimensions]
        characters = tuple(dict.fromkeys(segment.scene_characters))
        candidate_count = getattr(visual, "candidate_count", 1)
        if candidate_count <= 1:
            # Unchanged Phase 8 single-candidate path — same filename, same
            # seed formula, same call shape as before Phase 9 existed.
            asset_path = Path(cache_dir) / f"{key}.png"
            seed = int(key[:16], 16) % (2**32)
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
        return self._resolve_candidates(request, segment, visual, key, cache_dir, generated_dimensions, characters, video_slug)

    def _resolve_candidates(self, request: VisualRequest, segment: "Segment", visual: Any, generation_key: str, cache_dir: Path, generated_dimensions: tuple[int, int], characters: tuple[str, ...], video_slug: str) -> dict[str, Any]:
        """Opt-in Phase 9 multi-candidate path (`candidate_count > 1`)."""
        target_count = visual.candidate_count
        policy_version = getattr(visual, "candidate_policy_version", "phase9-v1")
        policy_name = getattr(visual, "selection_policy", "first_valid")
        store = self.candidate_store or VisualCandidateStore(Path(cache_dir) / "visual_candidates.json")
        candidate_set = store.get_or_create(
            shot_id=request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint,
            generation_key=generation_key, candidate_policy_version=policy_version, target_candidate_count=target_count,
        )
        _candidate_logger.info(
            "visual_candidates.prepare shot_id=%s target_count=%s policy=%s policy_version=%s",
            request.shot_id, target_count, policy_name, policy_version,
        )
        for index in range(target_count):
            slot = candidate_set.slot(index)
            if candidate_is_valid(slot, self.registry):
                continue
            slot.attempt_count += 1
            asset_path = candidate_cache_path(cache_dir, generation_key, index)
            seed = slot.seed
            fresh = not asset_path.is_file()
            try:
                if fresh:
                    provider = self.provider
                    if provider is None:
                        from ..providers.registry import get_story_image_provider
                        provider = get_story_image_provider()
                    provider.generate_scene(self.profile, characters_present=tuple(segment.scene_characters), prompt=segment.visual_intent.strip(), width=generated_dimensions[0], height=generated_dimensions[1], seed=seed, output_path=asset_path)
                if not validate_candidate_image(asset_path):
                    raise ValueError(f"Candidate ảnh không hợp lệ (technical validation thất bại): {asset_path}")
                asset_id = self.registry.record_generated(generation_key=generation_key, local_path=asset_path, is_fresh_generation=fresh, profile_id=self.profile.profile_id, profile_version=self.profile.version, seed=seed, prompt=segment.visual_intent.strip(), style_prompt=visual.style_prompt, negative_prompt=visual.negative_prompt, steps=visual.steps, cfg=visual.cfg, width=generated_dimensions[0], height=generated_dimensions[1], characters=characters, generation_mode=_generation_mode(characters), checkpoint=settings.comfyui_sdxl_checkpoint, clip_vision_model=settings.comfyui_clip_vision_model, ipadapter_model=settings.comfyui_ipadapter_model, solo_weight=visual.solo_weight, duo_weight=visual.duo_weight, duo_denoise=visual.duo_denoise, sampler=SAMPLER, scheduler=SCHEDULER, scene_id=request.scene_id, shot_id=request.shot_id, video_slug=video_slug)
                slot.status, slot.asset_id, slot.last_error = "done", asset_id, None
            except Exception as exc:
                slot.status, slot.last_error = "failed", str(exc)
            store.write()
        # Selection is ALWAYS recomputed here — never cached/skipped based
        # on a prior `selected_asset_id` — so a changed `selection_policy`
        # or judge policy reselects on the very next call with no explicit
        # invalidation step (see `VisualCandidateSet.selection_policy`
        # docstring / Phase 10 handoff §16). Only candidate GENERATION
        # above is checkpointed/skipped.
        if policy_name == "vlm_ranked":
            selected_asset_id = self._select_vlm_ranked(request, candidate_set, video_slug=video_slug)
        elif policy_name == "first_valid":
            selected_asset_id = resolve_selection_policy(policy_name)(candidate_set, self.registry)
            candidate_set.selection_mode = "policy"
        else:
            raise ValueError(f"selection_policy không hợp lệ: {policy_name!r}")
        candidate_set.selection_policy = policy_name
        if selected_asset_id is None:
            candidate_set.selection_status = "failed"
            store.write()
            raise ValueError(f"Không có candidate hợp lệ nào cho shot {request.shot_id} (target_count={target_count}).")
        candidate_set.selected_asset_id = selected_asset_id
        candidate_set.selection_status = "selected"
        store.write()
        record = self.registry.find_by_asset_id(selected_asset_id)
        assert record is not None
        return record

    def _select_vlm_ranked(self, request: VisualRequest, candidate_set, *, video_slug: str) -> str | None:
        """Phase 10 opt-in ranked selection. Returns `None` only when there
        is truly nothing eligible to select (zero technically-valid
        candidates, or a successfully-judged set with zero eligible
        candidates) — the caller fails closed in both cases, exactly like
        `first_valid`'s own zero-valid-candidates behaviour."""
        visual = self.profile.visual_generation
        judge_cfg = getattr(visual, "visual_judge", None)
        if judge_cfg is None:
            raise ValueError(
                f"Profile '{self.profile.profile_id}': selection_policy='vlm_ranked' "
                "yêu cầu visual_judge được cấu hình."
            )
        valid_slots = [
            candidate_set.slot(index) for index in range(candidate_set.target_candidate_count)
            if candidate_is_valid(candidate_set.slot(index), self.registry)
        ]
        if not valid_slots:
            return None
        candidates: list[JudgeCandidate] = []
        for slot in valid_slots:
            record = self.registry.find_by_asset_id(slot.asset_id)
            assert record is not None
            candidates.append(JudgeCandidate(
                asset_id=slot.asset_id, local_path=record["local_path"],
                content_sha256=record["content_sha256"], candidate_index=slot.candidate_index,
            ))
        candidate_identity = {candidate.asset_id: candidate.content_sha256 for candidate in candidates}
        candidate_index_by_asset = {candidate.asset_id: candidate.candidate_index for candidate in candidates}

        store = self.evaluation_store or VisualEvaluationStore(Path(self.cache_dir or ".") / "visual_evaluations.json")
        existing = store.get(request.shot_id)
        can_reuse = (
            existing is not None and not existing.fallback_used
            and existing.matches_context(
                request_fingerprint=request.request_fingerprint, judge_provider=judge_cfg.provider,
                judge_model=judge_cfg.model, judge_policy_version=judge_cfg.policy_version,
                judge_contract_version=_JUDGE_CONTRACT_VERSION,
            )
            and existing.matches_candidate_identity(candidate_identity)
        )
        if can_reuse:
            _judge_logger.info("visual_judge.reuse shot_id=%s candidates=%s", request.shot_id, len(candidates))
            result = JudgeResult(
                tuple(existing.evaluations[asset_id] for asset_id in candidate_identity),
                existing.judge_provider, existing.judge_model, existing.judge_contract_version,
            )
        else:
            context = JudgeContext(scene_id=request.scene_id, shot_id=request.shot_id, video_slug=video_slug)
            try:
                if self.judge is None:
                    raise ValueError("Không có VisualJudge khả dụng cho selection_policy='vlm_ranked'.")
                result = self.judge.evaluate(request, tuple(candidates), context)
            except Exception as exc:
                if not judge_cfg.hard_fail_on_judge_error:
                    _judge_logger.info("visual_judge.fallback shot_id=%s error=%s", request.shot_id, exc)
                    store.save(ShotEvaluationSet(
                        shot_id=request.shot_id, request_fingerprint=request.request_fingerprint,
                        judge_provider=judge_cfg.provider, judge_model=judge_cfg.model,
                        judge_policy_version=judge_cfg.policy_version, judge_contract_version=_JUDGE_CONTRACT_VERSION,
                        candidate_identity=candidate_identity, evaluations={}, fallback_used=True, judge_error=str(exc),
                    ))
                    store.write()
                    candidate_set.selection_mode = "fallback_first_valid"
                    return resolve_selection_policy("first_valid")(candidate_set, self.registry)
                raise ValueError(
                    f"VisualJudge lỗi hạ tầng và hard_fail_on_judge_error=true cho shot "
                    f"{request.shot_id}: {exc}"
                ) from exc
            store.save(ShotEvaluationSet(
                shot_id=request.shot_id, request_fingerprint=request.request_fingerprint,
                judge_provider=result.judge_provider, judge_model=result.judge_model,
                judge_policy_version=judge_cfg.policy_version, judge_contract_version=result.judge_contract_version,
                candidate_identity=candidate_identity,
                evaluations={evaluation.asset_id: evaluation for evaluation in result.evaluations},
                fallback_used=False, judge_error=None,
            ))
            store.write()
            hard_failed = sum(1 for evaluation in result.evaluations if evaluation.is_hard_failed())
            _judge_logger.info(
                "visual_judge.evaluated shot_id=%s candidates=%s hard_failures=%s",
                request.shot_id, len(candidates), hard_failed,
            )
        candidate_set.selection_mode = "policy"
        # `None` here means every candidate was hard-failed or below
        # threshold — NEVER falls back to first_valid (semantic rejection,
        # not infrastructure failure; see module docstring).
        return select_vlm_ranked(result, candidate_index_by_asset, minimum_score=judge_cfg.minimum_score)


def _parent_reuse(request: VisualRequest, lineage, registry: AssetRegistry, *, video_slug: str) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Validate an explicitly linked concrete parent asset; never search."""
    if lineage is None or (source := lineage.source_for(request.shot_id)) is None:
        return None
    for record in registry.assets():
        if not any(use.get("video_slug") == source.parent_project_id and use.get("scene_id") == source.parent_scene_id and use.get("shot_id") == source.parent_shot_id for use in record.get("uses", ())):
            continue
        path = Path(record.get("local_path", ""))
        if (record.get("asset_class") not in {"generated", "legacy_generated", "profile_local"} or
            not path.is_file() or observed_content_sha256(path) != record.get("content_sha256") or
            record.get("width") != _SDXL_GENERATION_DIMS[request.dimensions][0] or record.get("height") != _SDXL_GENERATION_DIMS[request.dimensions][1]):
            continue
        updated = registry.record_existing_use(record["asset_id"], scene_id=request.scene_id, shot_id=request.shot_id, video_slug=video_slug)
        if updated is not None:
            return updated, {"parent_project_id": source.parent_project_id, "parent_scene_id": source.parent_scene_id, "parent_shot_id": source.parent_shot_id, "parent_asset_id": record["asset_id"], "reuse_policy": source.policy_version}
    return None


def prepare_visual_assets(voiceover: "Voiceover", profile: "ContentProfile", *, project_dir: Path, dimensions: tuple[int, int], scene_plan: "ScenePlan | None" = None, registry: AssetRegistry | None = None, cache_dir: Path | None = None, provider: Any = None, lineage=None, judge: Any = None) -> tuple["ScenePlan", VisualManifest, dict[str, Path]]:
    """Checkpoint each resolved shot; failures preserve earlier completed shots.

    The optional fallback is a compatibility convenience for direct legacy
    callers.  Production DAG callers must supply the already-persisted plan:
    visual preparation never invokes the Director or chooses a replacement.
    """
    from .scene_plan import build_story_scene_plan
    project_dir.mkdir(parents=True, exist_ok=True)
    plan = scene_plan or build_story_scene_plan(voiceover, profile)
    requests = build_visual_requests(plan, profile, dimensions=dimensions)
    manifest_path = project_dir / "visual_manifest.json"
    manifest = VisualManifest.read_json(manifest_path) if manifest_path.is_file() else VisualManifest(plan.source_fingerprint)
    registry = registry or AssetRegistry()
    candidate_store = VisualCandidateStore(project_dir / "visual_candidates.json")
    evaluation_store = VisualEvaluationStore(project_dir / "visual_evaluations.json")
    resolver = VisualAssetResolver(profile, registry=registry, cache_dir=cache_dir, provider=provider, candidate_store=candidate_store, judge=judge, evaluation_store=evaluation_store)
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
            reused = _parent_reuse(request, lineage, registry, video_slug=voiceover.project_id or project_dir.name)
            record, reuse_source = reused if reused is not None else (resolver.resolve(request, voiceover.segments[scene.source_segment_index], shot, video_slug=voiceover.project_id or project_dir.name), None)
            manifest.mark_done(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint, asset_id=record["asset_id"], reuse_source=reuse_source)
            manifest.write_json(manifest_path)
            prepared[request.shot_id] = Path(record["local_path"])
        except Exception as exc:
            manifest.mark_failed(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint, error=str(exc))
            manifest.write_json(manifest_path)
            raise
    return plan, manifest, validate_prepared_manifest(manifest, requests, registry)
