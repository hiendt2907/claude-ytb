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
    CandidateSlot,
    MAX_GENERATION_ROUND,
    VisualCandidateSet,
    VisualCandidateStore,
    candidate_cache_path,
    candidate_is_valid,
    logger as _candidate_logger,
    resolve_selection_policy,
    validate_candidate_image,
)
from .visual_disposition import AutoDispositionPolicy, choose_auto_accept
from .visual_evaluation_store import ShotEvaluationSet, VisualEvaluationStore
from .visual_judge import (
    CONTRACT_VERSION as _JUDGE_CONTRACT_VERSION,
    JudgeCandidate,
    JudgeContext,
    JudgeResult,
    logger as _judge_logger,
    select_vlm_ranked,
)
from .visual_review import (
    ReviewDisposition,
    ReviewReason,
    ReviewRequiredError,
    ReviewStatus,
    VisualAbandonedError,
    VisualPreparationState,
    VisualReviewEntry,
    VisualReviewStore,
    derive_manual_visual_request,
    manual_candidate_cache_path,
    manual_generation_key,
)

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile
    from ..pkg.models import Segment, Voiceover
    from .scene_plan import ScenePlan, Shot



def resolve_judge_target(judge_cfg: Any) -> tuple[str, str]:
    """Provider/model nào thật sự chấm ảnh cho shot này.

    Model Judge được khai trong profile, và script ghim `profile_version`, nên
    snapshot đóng băng cả LỰA CHỌN HẠ TẦNG lẫn hợp đồng nội dung. Snapshot tồn
    tại để luật kể chuyện không đổi dưới chân một script đã viết; đóng băng
    luôn tên nhà cung cấp chỉ là tác dụng phụ của việc để chung một file.

    Đo 2026-09-04: `qwen/qwen3.8-max:free` trả HTTP 500 cho mọi request, kể cả
    text-only, và cả họ qwen cùng hỏng trên gateway. Mọi script ghim version có
    model đó trở thành KHÔNG BAO GIỜ sản xuất được — kể cả sau khi profile mới
    đã đổi sang model chạy được.

    `settings.visual_judge_provider/model` đã tồn tại nhưng chỉ được một smoke
    tool dùng. Ở đây chúng là cửa thoát TƯỜNG MINH cho operator: đặt env thì nó
    thắng, bỏ trống thì profile thắng đúng như trước. Không có mặc định ẩn nào
    thay đổi.
    """
    provider = (settings.visual_judge_provider or "").strip() or judge_cfg.provider
    model = (settings.visual_judge_model or "").strip() or judge_cfg.model
    if model != judge_cfg.model or provider != judge_cfg.provider:
        _judge_logger.warning(
            "visual_judge.operator_override profile=%s/%s -> %s/%s",
            judge_cfg.provider, judge_cfg.model, provider, model,
        )
    return provider, model


def resolve_auto_disposition(judge_cfg: Any) -> "AutoDispositionPolicy":
    """The disposition policy in force, profile first, operator override last.

    Same shape and same reason as `resolve_judge_target` above. Four ban-so-6
    Longs are pinned to profile snapshots 2.2.0 and 2.5.0, so a policy added to
    the live `profile.json` can never reach them — the snapshot exists exactly
    so story rules do not shift under a written script, and it freezes this
    with them. The env override is the explicit way out for an operator, and
    when it is unset the profile wins, unchanged.
    """
    from .visual_disposition import AutoDispositionPolicy, DispositionError

    # `judge_cfg` is duck-typed across this module. Anything that never
    # declared a disposition has not opted in, and halting is what not opting
    # in means — so read it defensively rather than requiring the full profile.
    reader = getattr(judge_cfg, "auto_disposition_policy", None)
    declared = reader() if callable(reader) else AutoDispositionPolicy()
    mode = (settings.visual_auto_disposition or "").strip()
    if not mode:
        return declared
    raw_codes = (settings.visual_auto_accept_waived_failures or "").strip()
    codes = frozenset(part.strip() for part in raw_codes.split(",") if part.strip())
    try:
        override = AutoDispositionPolicy(
            mode=mode,
            minimum_score=settings.visual_auto_accept_minimum_score,
            ignorable_hard_failures=codes,
        )
    except DispositionError as exc:
        raise DispositionError(f"Operator override không hợp lệ: {exc}") from exc
    _judge_logger.warning(
        "visual_judge.disposition_override profile=%s -> %s waived=%s min=%.2f",
        declared.mode, override.mode, ",".join(sorted(codes)) or "-",
        override.minimum_score,
    )
    return override


def try_auto_accept(
    entry: Any,
    request: "VisualRequest",
    *,
    judge_cfg: Any,
    review_store: Any,
    evaluation_store: Any,
    registry: AssetRegistry,
) -> str | None:
    """Settle one pending review by policy, or return None to keep waiting.

    Called from two places on purpose. A review entry outlives the run that
    created it, so a policy enabled afterwards would never reach the shots
    already halted if this only ran where the halt is first raised — which is
    exactly the state four ban-so-6 Longs were in.
    """
    if judge_cfg is None or review_store is None or evaluation_store is None:
        return None
    policy = resolve_auto_disposition(judge_cfg)
    if not policy.accepts_automatically:
        return None
    evaluated = evaluation_store.get(request.shot_id)
    if evaluated is None or evaluated.fallback_used:
        return None
    candidate_identity: dict[str, str] = {}
    for asset_id in entry.candidate_asset_ids:
        record = registry.find_by_asset_id(asset_id)
        if record is None:
            return None
        path = Path(str(record.get("local_path") or ""))
        if not path.is_file() or observed_content_sha256(path) != record.get("content_sha256"):
            return None
        candidate_identity[asset_id] = str(record["content_sha256"])
    judge_provider, judge_model = resolve_judge_target(judge_cfg)
    if (
        not evaluated.matches_context(
            request_fingerprint=request.request_fingerprint,
            judge_provider=judge_provider,
            judge_model=judge_model,
            judge_policy_version=judge_cfg.policy_version,
            judge_contract_version=_JUDGE_CONTRACT_VERSION,
        )
        or not evaluated.matches_candidate_identity(candidate_identity)
        or set(evaluated.evaluations) != set(candidate_identity)
    ):
        return None
    evaluations = tuple(evaluated.evaluations[asset_id] for asset_id in entry.candidate_asset_ids)
    index = {
        asset_id: position
        for position, asset_id in enumerate(entry.candidate_asset_ids)
    }
    chosen = choose_auto_accept(evaluations, policy=policy, candidate_index_by_asset=index)
    if chosen is None:
        return None
    review_store.resolve_accept_existing(
        entry.review_id,
        request_fingerprint=request.request_fingerprint,
        asset_id=chosen,
        selection_mode="auto_accept_best",
    )
    waived = sorted(
        code
        for evaluation in evaluations
        if evaluation.asset_id == chosen
        for code in evaluation.hard_failures
    )
    _candidate_logger.warning(
        "visual_review.auto_accepted shot_id=%s review_id=%s asset_id=%s waived=%s",
        request.shot_id, entry.review_id, chosen, ",".join(waived) or "-",
    )
    return chosen


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


@dataclass(frozen=True)
class RankedSelectionOutcome:
    """Internal selection result that keeps semantic rejection distinct
    from technical emptiness and Judge infrastructure fallback."""

    selected_asset_id: str | None
    semantic_rejection: bool = False
    evaluation_fingerprint: str = ""


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

    def mark_pending(self, shot_id: str, *, request_id: str, request_fingerprint: str, reason: str) -> None:
        """Record that no final resolution exists without duplicating review state."""
        attempts = self.shots.get(shot_id, VisualManifestEntry("", "")).attempt_count
        self.shots[shot_id] = VisualManifestEntry(
            request_id, request_fingerprint, "pending", None, attempts, reason
        )

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


def _selector_fingerprint(visual: Any) -> str:
    """Identity of selection semantics, deliberately excluding generation.

    Changing this fingerprint makes only the selected resolution stale. The
    candidate slots and their AssetRecords remain reusable.
    """
    policy = getattr(visual, "selection_policy", "first_valid")
    payload: dict[str, Any] = {
        "contract_version": "phase10-selector-v1",
        "selection_policy": policy,
        "candidate_count": getattr(visual, "candidate_count", 1),
    }
    if policy == "vlm_ranked":
        judge = getattr(visual, "visual_judge", None)
        payload["visual_judge"] = {
            "provider": getattr(judge, "provider", ""),
            "model": getattr(judge, "model", ""),
            "policy_version": getattr(judge, "policy_version", ""),
            "minimum_score": getattr(judge, "minimum_score", None),
            "hard_fail_on_judge_error": getattr(judge, "hard_fail_on_judge_error", None),
            "contract_version": _JUDGE_CONTRACT_VERSION,
        }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _evaluation_fingerprint(
    request: VisualRequest,
    judge_cfg: Any,
    candidate_identity: dict[str, str],
) -> str:
    """Exact identity of a successful whole-set semantic observation.

    Full evaluations stay in ``visual_evaluations.json``. The candidate
    checkpoint stores only this compact identity when a round is rejected.
    """
    payload = {
        "request_fingerprint": request.request_fingerprint,
        "judge_provider": judge_cfg.provider,
        "judge_model": judge_cfg.model,
        "judge_policy_version": judge_cfg.policy_version,
        "judge_contract_version": _JUDGE_CONTRACT_VERSION,
        "candidate_identity": candidate_identity,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _selection_checkpoint_is_reusable(
    request: VisualRequest,
    profile: "ContentProfile",
    candidate_store: VisualCandidateStore,
    *,
    has_reuse_source: bool,
) -> bool:
    """Whether a reusable manifest also has a current selection decision."""
    if has_reuse_source or request.resolution_kind != "generated_image":
        return True
    visual = getattr(profile, "visual_generation", None)
    if visual is None or getattr(visual, "candidate_count", 1) <= 1:
        return True
    candidate_set = candidate_store.get(request.shot_id)
    if candidate_set is None:
        return False
    return (
        candidate_set.request_fingerprint == request.request_fingerprint
        and candidate_set.selection_status == "selected"
        and candidate_set.selection_mode != "fallback_first_valid"
        and candidate_set.selector_fingerprint == _selector_fingerprint(visual)
    )


class VisualAssetResolver:
    """The single local/cache/ComfyUI/registry decision owner."""

    def __init__(self, profile: "ContentProfile", *, registry: AssetRegistry | None = None, cache_dir: Path | None = None, provider: Any = None, candidate_store: VisualCandidateStore | None = None, judge: Any = None, evaluation_store: VisualEvaluationStore | None = None, review_store: VisualReviewStore | None = None) -> None:
        self.profile, self.registry, self.cache_dir, self.provider = profile, registry or AssetRegistry(), cache_dir, provider
        self.candidate_store = candidate_store
        # Only consulted when a profile opts into
        # selection_policy="vlm_ranked". Tests may inject a deterministic
        # fake; production resolves the configured vision capability lazily
        # inside `_select_vlm_ranked`, after cache reuse has been checked.
        # first_valid/profile_local/parent-reuse therefore never even
        # instantiate a Judge adapter.
        self.judge = judge
        self.evaluation_store = evaluation_store
        self.review_store = review_store

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

    def _generate_candidate_round(
        self,
        request: VisualRequest,
        segment: "Segment",
        visual: Any,
        candidate_set: VisualCandidateSet,
        store: VisualCandidateStore,
        *,
        generation_round: int,
        generation_key: str,
        cache_dir: Path,
        generated_dimensions: tuple[int, int],
        characters: tuple[str, ...],
        video_slug: str,
    ) -> tuple[int, ...]:
        """Generate/resume one round sequentially and return invalid slots.

        Every slot is checkpointed immediately. Round 0 preserves all Phase-9
        identities; round 1 uses deterministic distinct seeds and paths.
        """
        _candidate_logger.info(
            "visual_candidates.round shot_id=%s recovery_policy=%s generation_round=%s target_count=%s",
            request.shot_id,
            candidate_set.recovery_policy,
            generation_round,
            candidate_set.target_candidate_count,
        )
        for index in range(candidate_set.target_candidate_count):
            slot = candidate_set.slot(index, generation_round=generation_round)
            if candidate_is_valid(slot, self.registry):
                continue
            slot.attempt_count += 1
            asset_path = candidate_cache_path(
                cache_dir,
                generation_key,
                index,
                generation_round=generation_round,
            )
            seed = slot.seed
            fresh = not asset_path.is_file()
            try:
                if fresh:
                    provider = self.provider
                    if provider is None:
                        from ..providers.registry import get_story_image_provider

                        provider = get_story_image_provider()
                    provider.generate_scene(
                        self.profile,
                        characters_present=tuple(segment.scene_characters),
                        prompt=segment.visual_intent.strip(),
                        width=generated_dimensions[0],
                        height=generated_dimensions[1],
                        seed=seed,
                        output_path=asset_path,
                    )
                if not validate_candidate_image(asset_path):
                    raise ValueError(
                        "Candidate ảnh không hợp lệ (technical validation thất bại): "
                        f"{asset_path}"
                    )
                asset_id = self.registry.record_generated(
                    generation_key=generation_key,
                    local_path=asset_path,
                    is_fresh_generation=fresh,
                    profile_id=self.profile.profile_id,
                    profile_version=self.profile.version,
                    seed=seed,
                    prompt=segment.visual_intent.strip(),
                    style_prompt=visual.style_prompt,
                    negative_prompt=visual.negative_prompt,
                    steps=visual.steps,
                    cfg=visual.cfg,
                    width=generated_dimensions[0],
                    height=generated_dimensions[1],
                    characters=characters,
                    generation_mode=_generation_mode(characters),
                    checkpoint=settings.comfyui_sdxl_checkpoint,
                    clip_vision_model=settings.comfyui_clip_vision_model,
                    ipadapter_model=settings.comfyui_ipadapter_model,
                    solo_weight=visual.solo_weight,
                    duo_weight=visual.duo_weight,
                    duo_denoise=visual.duo_denoise,
                    sampler=SAMPLER,
                    scheduler=SCHEDULER,
                    scene_id=request.scene_id,
                    shot_id=request.shot_id,
                    video_slug=video_slug,
                )
                slot.status, slot.asset_id, slot.last_error = "done", asset_id, None
            except Exception as exc:
                slot.status, slot.last_error = "failed", str(exc)
            store.write()
        return tuple(
            index
            for index in range(candidate_set.target_candidate_count)
            if not candidate_is_valid(
                candidate_set.slot(index, generation_round=generation_round),
                self.registry,
            )
        )

    @staticmethod
    def _record_semantic_rejection(
        candidate_set: VisualCandidateSet,
        store: VisualCandidateStore,
        *,
        generation_round: int,
        evaluation_fingerprint: str,
    ) -> None:
        if generation_round not in candidate_set.semantic_rejection_rounds:
            candidate_set.semantic_rejection_rounds.append(generation_round)
            candidate_set.semantic_rejection_rounds.sort()
        candidate_set.rejected_evaluation_fingerprint = evaluation_fingerprint
        store.write()
        _candidate_logger.info(
            "visual_candidates.semantic_rejection shot_id=%s generation_round=%s recovery_policy=%s",
            candidate_set.shot_id,
            generation_round,
            candidate_set.recovery_policy,
        )

    def _raise_semantic_review(
        self,
        request: VisualRequest,
        candidate_set: VisualCandidateSet,
        *,
        reason: ReviewReason,
        evaluation_fingerprint: str,
        visual: Any = None,
    ) -> str | None:
        """Persist the human boundary when a project-local store is available.

        Returns an asset id when the profile's disposition policy lets the
        engine settle the shot itself, and raises as before when it does not.
        Direct resolver callers without a project context retain the Phase-12
        ValueError behavior; production ``prepare_visual_assets`` always
        injects the durable review store.
        """
        if self.review_store is None:
            if reason == ReviewReason.SEMANTIC_RECOVERY_EXHAUSTED:
                raise ValueError(
                    f"Semantic recovery exhausted cho shot {request.shot_id}; "
                    "không tạo round 2."
                )
            raise ValueError(
                f"Không có candidate hợp lệ nào cho shot {request.shot_id} "
                f"(target_count={candidate_set.target_candidate_count})."
            )
        candidate_ids = tuple(
            slot.asset_id
            for generation_round in candidate_set.existing_rounds()
            for slot in candidate_set.existing_slots_for_round(generation_round)
            if slot.asset_id and candidate_is_valid(slot, self.registry)
        )
        entry = self.review_store.ensure_pending(
            request,
            reason=reason,
            candidate_asset_ids=candidate_ids,
            evaluation_fingerprint=evaluation_fingerprint,
            recovery_status=candidate_set.recovery_status,
        )
        _candidate_logger.info(
            "visual_review.created shot_id=%s review_id=%s reason=%s status=%s",
            request.shot_id,
            entry.review_id,
            entry.review_reason.value,
            entry.status.value,
        )
        accepted = self._auto_accept(request, entry, visual)
        if accepted is not None:
            return accepted
        raise ReviewRequiredError(entry)

    def _auto_accept(
        self, request: VisualRequest, entry: Any, visual: Any
    ) -> str | None:
        """Settle the shot without a person, when the profile allows it.

        Deliberately runs AFTER `ensure_pending`: the review entry is the audit
        record either way, so a shot the engine settled is still visible as a
        shot that needed settling, and `resolve_accept_existing` re-checks the
        asset against the entry's own candidate list.
        """
        return try_auto_accept(
            entry,
            request,
            judge_cfg=getattr(visual, "visual_judge", None) if visual is not None else None,
            review_store=self.review_store,
            evaluation_store=self.evaluation_store,
            registry=self.registry,
        )

    @staticmethod
    def _manual_candidate_slot(slot: Any) -> CandidateSlot:
        return CandidateSlot(
            candidate_slot_id=slot.candidate_slot_id,
            candidate_index=slot.candidate_index,
            seed=slot.seed,
            status=slot.status,
            asset_id=slot.asset_id,
            attempt_count=slot.attempt_count,
            last_error=slot.last_error,
            generation_round=0,
        )

    def resolve_manual_review(
        self,
        request: VisualRequest,
        segment: "Segment",
        entry: VisualReviewEntry,
        *,
        video_slug: str,
    ) -> dict[str, Any]:
        """Resume one human-authored candidate set; never create round 2."""
        if self.review_store is None or entry.manual_override is None:
            raise ValueError("Manual review execution thiếu durable review state.")
        override = entry.manual_override
        if override.status == "rejected":
            raise ReviewRequiredError(entry)
        if override.base_request_fingerprint != request.request_fingerprint:
            self.review_store.mark_stale_for_changed_request(
                request.shot_id, request.request_fingerprint
            )
            raise ReviewRequiredError(entry)

        visual = self.profile.visual_generation
        derived = derive_manual_visual_request(request, override)
        automated_key = _generation_key(segment, self.profile, request.dimensions)
        generation_key = manual_generation_key(automated_key, override)
        cache_dir = self.cache_dir or (
            settings.assets_dir / "generated_visuals" / self.profile.profile_id
        )
        generated_dimensions = _SDXL_GENERATION_DIMS[request.dimensions]
        characters = tuple(dict.fromkeys(segment.scene_characters))
        entry = self.review_store.initialize_manual_attempt(
            entry.review_id,
            request_fingerprint=request.request_fingerprint,
            candidate_count=visual.candidate_count,
            generation_key=generation_key,
        )
        override = entry.manual_override
        assert override is not None
        _candidate_logger.info(
            "visual_review.manual_attempt_started shot_id=%s override_id=%s candidates=%s",
            request.shot_id,
            override.override_id,
            override.candidate_count,
        )

        for persisted_slot in override.candidates:
            candidate_slot = self._manual_candidate_slot(persisted_slot)
            if candidate_is_valid(candidate_slot, self.registry):
                continue
            entry = self.review_store.update_manual_slot(
                entry.review_id,
                request_fingerprint=request.request_fingerprint,
                candidate_index=persisted_slot.candidate_index,
                status="running",
                asset_id=None,
                last_error=None,
                increment_attempt=True,
            )
            override = entry.manual_override
            assert override is not None
            slot = next(
                item
                for item in override.candidates
                if item.candidate_index == persisted_slot.candidate_index
            )
            asset_path = manual_candidate_cache_path(
                cache_dir, generation_key, slot.candidate_index
            )
            fresh = not asset_path.is_file()
            try:
                if fresh:
                    provider = self.provider
                    if provider is None:
                        from ..providers.registry import get_story_image_provider

                        provider = get_story_image_provider()
                    provider.generate_scene(
                        self.profile,
                        characters_present=tuple(segment.scene_characters),
                        prompt=derived.visual_intent,
                        width=generated_dimensions[0],
                        height=generated_dimensions[1],
                        seed=slot.seed,
                        output_path=asset_path,
                    )
                if not validate_candidate_image(asset_path):
                    raise ValueError(
                        "Manual candidate technical validation thất bại: "
                        f"{asset_path}"
                    )
                asset_id = self.registry.record_generated(
                    generation_key=generation_key,
                    local_path=asset_path,
                    is_fresh_generation=fresh,
                    profile_id=self.profile.profile_id,
                    profile_version=self.profile.version,
                    seed=slot.seed,
                    prompt=derived.visual_intent,
                    style_prompt=visual.style_prompt,
                    negative_prompt=visual.negative_prompt,
                    steps=visual.steps,
                    cfg=visual.cfg,
                    width=generated_dimensions[0],
                    height=generated_dimensions[1],
                    characters=characters,
                    generation_mode=_generation_mode(characters),
                    checkpoint=settings.comfyui_sdxl_checkpoint,
                    clip_vision_model=settings.comfyui_clip_vision_model,
                    ipadapter_model=settings.comfyui_ipadapter_model,
                    solo_weight=visual.solo_weight,
                    duo_weight=visual.duo_weight,
                    duo_denoise=visual.duo_denoise,
                    sampler=SAMPLER,
                    scheduler=SCHEDULER,
                    scene_id=request.scene_id,
                    shot_id=request.shot_id,
                    video_slug=video_slug,
                )
                entry = self.review_store.update_manual_slot(
                    entry.review_id,
                    request_fingerprint=request.request_fingerprint,
                    candidate_index=slot.candidate_index,
                    status="done",
                    asset_id=asset_id,
                    last_error=None,
                )
            except Exception as exc:
                entry = self.review_store.update_manual_slot(
                    entry.review_id,
                    request_fingerprint=request.request_fingerprint,
                    candidate_index=slot.candidate_index,
                    status="failed",
                    asset_id=None,
                    last_error=str(exc),
                )

        override = entry.manual_override
        assert override is not None
        candidate_slots = tuple(
            self._manual_candidate_slot(slot) for slot in override.candidates
        )
        invalid = tuple(
            slot.candidate_index
            for slot in candidate_slots
            if not candidate_is_valid(slot, self.registry)
        )
        if invalid:
            raise ValueError(
                f"Manual generation chưa hoàn tất cho shot {request.shot_id}; "
                f"failed_slots={list(invalid)}."
            )

        manual_set = VisualCandidateSet(
            shot_id=request.shot_id,
            request_id=derived.request_id,
            request_fingerprint=derived.request_fingerprint,
            generation_key=generation_key,
            candidate_policy_version=visual.candidate_policy_version,
            target_candidate_count=override.candidate_count,
            candidates={slot.candidate_slot_id: slot for slot in candidate_slots},
            selection_policy=visual.selection_policy,
        )
        if visual.selection_policy == "first_valid":
            selected_asset_id = next(
                (
                    slot.asset_id
                    for slot in candidate_slots
                    if candidate_is_valid(slot, self.registry)
                ),
                None,
            )
            semantic_rejection = False
            evaluation_fingerprint = ""
            selection_mode = "operator_manual_first_valid"
        else:
            outcome = self._select_vlm_ranked(
                derived,
                manual_set,
                video_slug=video_slug,
                evaluation_store_key=override.evaluation_store_key,
            )
            selected_asset_id = outcome.selected_asset_id
            semantic_rejection = outcome.semantic_rejection
            evaluation_fingerprint = outcome.evaluation_fingerprint
            selection_mode = (
                "operator_manual_fallback_first_valid"
                if manual_set.selection_mode == "fallback_first_valid"
                else "operator_manual_judged"
            )
        if selected_asset_id is None:
            if semantic_rejection:
                entry = self.review_store.mark_manual_rejected(
                    entry.review_id,
                    request_fingerprint=request.request_fingerprint,
                    evaluation_fingerprint=evaluation_fingerprint,
                )
                _candidate_logger.info(
                    "visual_review.manual_attempt_rejected shot_id=%s override_id=%s",
                    request.shot_id,
                    override.override_id,
                )
                raise ReviewRequiredError(entry)
            raise ValueError(
                f"Manual candidate set không có media hợp lệ cho shot {request.shot_id}."
            )

        entry = self.review_store.resolve_manual_attempt(
            entry.review_id,
            request_fingerprint=request.request_fingerprint,
            selected_asset_id=selected_asset_id,
            selection_mode=selection_mode,
            evaluation_fingerprint=evaluation_fingerprint,
        )
        if self.candidate_store is not None:
            automated = self.candidate_store.get(request.shot_id)
            if automated is not None:
                automated.selected_asset_id = selected_asset_id
                automated.selection_status = "selected"
                automated.selection_mode = selection_mode
                self.candidate_store.write()
        _candidate_logger.info(
            "visual_review.manual_attempt_completed shot_id=%s override_id=%s asset_id=%s",
            request.shot_id,
            override.override_id,
            selected_asset_id,
        )
        record = self.registry.find_by_asset_id(selected_asset_id)
        assert record is not None
        return record

    def _resolve_candidates(self, request: VisualRequest, segment: "Segment", visual: Any, generation_key: str, cache_dir: Path, generated_dimensions: tuple[int, int], characters: tuple[str, ...], video_slug: str) -> dict[str, Any]:
        """Resolve Phase-9 candidates plus Phase-12 bounded recovery."""
        target_count = visual.candidate_count
        policy_version = getattr(visual, "candidate_policy_version", "phase9-v1")
        policy_name = getattr(visual, "selection_policy", "first_valid")
        recovery_policy = getattr(
            visual,
            "semantic_rejection_recovery",
            "fail_closed",
        )
        store = self.candidate_store or VisualCandidateStore(Path(cache_dir) / "visual_candidates.json")
        candidate_set = store.get_or_create(
            shot_id=request.shot_id,
            request_id=request.request_id,
            request_fingerprint=request.request_fingerprint,
            generation_key=generation_key,
            candidate_policy_version=policy_version,
            target_candidate_count=target_count,
        )
        candidate_set.recovery_policy = recovery_policy
        _candidate_logger.info(
            "visual_candidates.prepare shot_id=%s target_count=%s policy=%s policy_version=%s recovery_policy=%s",
            request.shot_id,
            target_count,
            policy_name,
            policy_version,
            recovery_policy,
        )

        self._generate_candidate_round(
            request,
            segment,
            visual,
            candidate_set,
            store,
            generation_round=0,
            generation_key=generation_key,
            cache_dir=cache_dir,
            generated_dimensions=generated_dimensions,
            characters=characters,
            video_slug=video_slug,
        )

        selected_asset_id: str | None = None
        exhausted = False
        semantic_rejection_for_review = False
        rejected_evaluation_fingerprint = ""
        if policy_name == "first_valid":
            selected_asset_id = resolve_selection_policy(policy_name)(candidate_set, self.registry)
            candidate_set.selection_mode = "policy"
            candidate_set.recovery_status = (
                "resolved"
                if candidate_set.semantic_rejection_rounds and selected_asset_id
                else "not_needed"
            )
        elif policy_name == "vlm_ranked":
            has_round_one = 1 in candidate_set.existing_rounds()
            if (
                has_round_one
                and candidate_set.recovery_status == "running"
                and recovery_policy == "regenerate_once"
            ):
                invalid = self._generate_candidate_round(
                    request,
                    segment,
                    visual,
                    candidate_set,
                    store,
                    generation_round=1,
                    generation_key=generation_key,
                    cache_dir=cache_dir,
                    generated_dimensions=generated_dimensions,
                    characters=characters,
                    video_slug=video_slug,
                )
                if invalid:
                    candidate_set.selection_status = "failed"
                    store.write()
                    raise ValueError(
                        f"round 1 generation chưa hoàn tất cho shot {request.shot_id}; "
                        f"failed_slots={list(invalid)}."
                    )

            outcome = self._select_vlm_ranked(
                request,
                candidate_set,
                video_slug=video_slug,
            )
            selected_asset_id = outcome.selected_asset_id
            if selected_asset_id is not None:
                if candidate_set.selection_mode == "policy":
                    candidate_set.recovery_status = (
                        "resolved" if has_round_one else "not_needed"
                    )
            elif outcome.semantic_rejection:
                semantic_rejection_for_review = True
                rejected_evaluation_fingerprint = outcome.evaluation_fingerprint
                rejected_round = 1 if has_round_one else 0
                self._record_semantic_rejection(
                    candidate_set,
                    store,
                    generation_round=rejected_round,
                    evaluation_fingerprint=outcome.evaluation_fingerprint,
                )
                if has_round_one:
                    if candidate_set.recovery_status == "exhausted" or recovery_policy == "regenerate_once":
                        candidate_set.recovery_status = "exhausted"
                        exhausted = True
                    else:
                        candidate_set.recovery_status = "eligible"
                elif recovery_policy == "regenerate_once":
                    candidate_set.recovery_status = "running"
                    candidate_set.active_generation_round = MAX_GENERATION_ROUND
                    store.write()
                    _candidate_logger.info(
                        "visual_candidates.recovery_started shot_id=%s generation_round=1",
                        request.shot_id,
                    )
                    invalid = self._generate_candidate_round(
                        request,
                        segment,
                        visual,
                        candidate_set,
                        store,
                        generation_round=1,
                        generation_key=generation_key,
                        cache_dir=cache_dir,
                        generated_dimensions=generated_dimensions,
                        characters=characters,
                        video_slug=video_slug,
                    )
                    if invalid:
                        candidate_set.selection_status = "failed"
                        store.write()
                        raise ValueError(
                            f"round 1 generation chưa hoàn tất cho shot {request.shot_id}; "
                            f"failed_slots={list(invalid)}."
                        )
                    second = self._select_vlm_ranked(
                        request,
                        candidate_set,
                        video_slug=video_slug,
                    )
                    selected_asset_id = second.selected_asset_id
                    if selected_asset_id is not None:
                        if candidate_set.selection_mode == "policy":
                            candidate_set.recovery_status = "resolved"
                    elif second.semantic_rejection:
                        rejected_evaluation_fingerprint = second.evaluation_fingerprint
                        self._record_semantic_rejection(
                            candidate_set,
                            store,
                            generation_round=1,
                            evaluation_fingerprint=second.evaluation_fingerprint,
                        )
                        candidate_set.recovery_status = "exhausted"
                        exhausted = True
                else:
                    candidate_set.recovery_status = "eligible"
        else:
            raise ValueError(f"selection_policy không hợp lệ: {policy_name!r}")

        candidate_set.selection_policy = policy_name
        candidate_set.selector_fingerprint = _selector_fingerprint(visual)
        if selected_asset_id is None:
            candidate_set.selected_asset_id = None
            candidate_set.selection_status = "failed"
            store.write()
            if exhausted:
                _candidate_logger.info(
                    "visual_candidates.recovery_exhausted shot_id=%s generation_calls_bound=%s judge_calls_bound=2",
                    request.shot_id,
                    target_count * 2,
                )
                selected_asset_id = self._raise_semantic_review(
                    request,
                    candidate_set,
                    reason=ReviewReason.SEMANTIC_RECOVERY_EXHAUSTED,
                    evaluation_fingerprint=rejected_evaluation_fingerprint,
                    visual=visual,
                )
            if selected_asset_id is None and semantic_rejection_for_review:
                selected_asset_id = self._raise_semantic_review(
                    request,
                    candidate_set,
                    reason=ReviewReason.SEMANTIC_FAIL_CLOSED,
                    evaluation_fingerprint=rejected_evaluation_fingerprint,
                    visual=visual,
                )
            if selected_asset_id is not None:
                candidate_set.selected_asset_id = selected_asset_id
                # A policy settlement is a real selection.  Keep the normal
                # reusable status while recording *how* it was chosen, so the
                # next run can reuse the manifest without pretending a clean
                # Judge pass picked it.
                candidate_set.selection_mode = "auto_accept_best"
                store.write()
            else:
                raise ValueError(
                    f"Không có candidate hợp lệ nào cho shot {request.shot_id} "
                    f"(target_count={target_count})."
                )
        candidate_set.selected_asset_id = selected_asset_id
        candidate_set.selection_status = "selected"
        store.write()
        _candidate_logger.info(
            "visual_candidates.selected shot_id=%s asset_id=%s policy=%s mode=%s recovery_status=%s",
            request.shot_id,
            selected_asset_id,
            policy_name,
            candidate_set.selection_mode,
            candidate_set.recovery_status,
        )
        record = self.registry.find_by_asset_id(selected_asset_id)
        assert record is not None
        return record

    def _select_vlm_ranked(
        self,
        request: VisualRequest,
        candidate_set: VisualCandidateSet,
        *,
        video_slug: str,
        evaluation_store_key: str | None = None,
    ) -> RankedSelectionOutcome:
        """Phase-10 selection with an explicit semantic-rejection outcome.

        Infrastructure fallback and zero technically-valid media are never
        labeled semantic rejection, so neither can authorize Phase-12 media.
        """
        visual = self.profile.visual_generation
        judge_cfg = getattr(visual, "visual_judge", None)
        if judge_cfg is None:
            raise ValueError(
                f"Profile '{self.profile.profile_id}': selection_policy='vlm_ranked' "
                "yêu cầu visual_judge được cấu hình."
            )
        valid_slots = [
            slot
            for generation_round in candidate_set.existing_rounds()
            for slot in candidate_set.existing_slots_for_round(generation_round)
            if candidate_is_valid(slot, self.registry)
        ]
        if not valid_slots:
            return RankedSelectionOutcome(None)
        candidates: list[JudgeCandidate] = []
        for slot in valid_slots:
            record = self.registry.find_by_asset_id(slot.asset_id)
            assert record is not None
            candidates.append(JudgeCandidate(
                asset_id=slot.asset_id, local_path=record["local_path"],
                content_sha256=record["content_sha256"],
                candidate_index=(
                    slot.generation_round * candidate_set.target_candidate_count
                    + slot.candidate_index
                ),
            ))
        candidate_identity = {candidate.asset_id: candidate.content_sha256 for candidate in candidates}
        candidate_index_by_asset = {candidate.asset_id: candidate.candidate_index for candidate in candidates}
        evaluation_fingerprint = _evaluation_fingerprint(
            request,
            judge_cfg,
            candidate_identity,
        )

        store = self.evaluation_store or VisualEvaluationStore(Path(self.cache_dir or ".") / "visual_evaluations.json")
        store_key = evaluation_store_key or request.shot_id
        existing = store.get(store_key)
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
                judge = self.judge
                if judge is None:
                    from ..providers.vision import get_visual_judge

                    provider_name, model_name = resolve_judge_target(judge_cfg)
                    judge = get_visual_judge(provider_name, model_name)
                result = judge.evaluate(request, tuple(candidates), context)
            except Exception as exc:
                if not judge_cfg.hard_fail_on_judge_error:
                    _judge_logger.info("visual_judge.fallback shot_id=%s error=%s", request.shot_id, exc)
                    store.save(ShotEvaluationSet(
                        shot_id=store_key, request_fingerprint=request.request_fingerprint,
                        judge_provider=judge_cfg.provider, judge_model=judge_cfg.model,
                        judge_policy_version=judge_cfg.policy_version, judge_contract_version=_JUDGE_CONTRACT_VERSION,
                        candidate_identity=candidate_identity, evaluations={}, fallback_used=True, judge_error=str(exc),
                    ))
                    store.write()
                    candidate_set.selection_mode = "fallback_first_valid"
                    return RankedSelectionOutcome(
                        resolve_selection_policy("first_valid")(candidate_set, self.registry)
                    )
                raise ValueError(
                    f"VisualJudge lỗi hạ tầng và hard_fail_on_judge_error=true cho shot "
                    f"{request.shot_id}: {exc}"
                ) from exc
            store.save(ShotEvaluationSet(
                shot_id=store_key, request_fingerprint=request.request_fingerprint,
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
        selected_asset_id = select_vlm_ranked(
            result,
            candidate_index_by_asset,
            minimum_score=judge_cfg.minimum_score,
        )
        return RankedSelectionOutcome(
            selected_asset_id,
            semantic_rejection=selected_asset_id is None,
            evaluation_fingerprint=evaluation_fingerprint,
        )


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


def _resolved_review_record(
    entry: VisualReviewEntry,
    candidate_store: VisualCandidateStore,
    registry: AssetRegistry,
) -> dict[str, Any] | None:
    """Revalidate a human-selected asset without consulting Judge/generation."""
    asset_id = entry.selected_asset_id
    if not asset_id or asset_id not in entry.candidate_asset_ids:
        return None
    candidate_set = candidate_store.get(entry.shot_id)
    automated_ids = {
        slot.asset_id
        for slot in (candidate_set.candidates.values() if candidate_set else ())
        if slot.asset_id
    }
    manual_ids = {
        slot.asset_id
        for slot in (entry.manual_override.candidates if entry.manual_override else ())
        if slot.asset_id
    }
    if asset_id not in automated_ids | manual_ids:
        return None
    record = registry.find_by_asset_id(asset_id)
    if record is None:
        return None
    path = Path(record.get("local_path", ""))
    if (
        not path.is_file()
        or observed_content_sha256(path) != record.get("content_sha256")
        or not validate_candidate_image(path)
    ):
        return None
    return record


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
    review_store = VisualReviewStore(project_dir / "visual_review.json")
    resolver = VisualAssetResolver(profile, registry=registry, cache_dir=cache_dir, provider=provider, candidate_store=candidate_store, judge=judge, evaluation_store=evaluation_store, review_store=review_store)
    shots = {shot.shot_id: (scene, shot) for scene in plan.scenes for shot in scene.shots}
    prepared: dict[str, Path] = {}
    for request in requests:
        stale_entries = review_store.mark_stale_for_changed_request(
            request.shot_id, request.request_fingerprint
        )
        for stale in stale_entries:
            _candidate_logger.info(
                "visual_review.stale project=%s shot_id=%s review_id=%s",
                voiceover.project_id or project_dir.name,
                request.shot_id,
                stale.review_id,
            )
        review = review_store.current_for_shot(request.shot_id)
        if review is not None and review.request_fingerprint == request.request_fingerprint:
            if review.status == ReviewStatus.ABANDONED:
                raise VisualAbandonedError(review)
            if (
                review.status == ReviewStatus.PENDING
                and review.disposition != ReviewDisposition.MANUAL_REGENERATE
            ):
                judge_cfg = getattr(
                    getattr(profile, "visual_generation", None), "visual_judge", None
                )
                accepted = try_auto_accept(
                    review,
                    request,
                    judge_cfg=judge_cfg,
                    review_store=review_store,
                    evaluation_store=evaluation_store,
                    registry=registry,
                )
                if accepted is not None:
                    refreshed = review_store.current_for_shot(request.shot_id)
                    if refreshed is not None:
                        review = refreshed
            if review.status == ReviewStatus.RESOLVED:
                record = _resolved_review_record(review, candidate_store, registry)
                if record is None:
                    review = review_store.reopen_invalid_selection(
                        review.review_id,
                        request_fingerprint=request.request_fingerprint,
                        error="Accepted/manual selected asset missing, stale, or invalid.",
                    )
                    raise ReviewRequiredError(review)
                candidate_set = candidate_store.get(request.shot_id)
                if candidate_set is not None:
                    candidate_set.selected_asset_id = record["asset_id"]
                    candidate_set.selection_status = "selected"
                    candidate_set.selection_mode = review.selection_mode
                    candidate_store.write()
                manifest.mark_done(
                    request.shot_id,
                    request_id=request.request_id,
                    request_fingerprint=request.request_fingerprint,
                    asset_id=record["asset_id"],
                )
                manifest.write_json(manifest_path)
                prepared[request.shot_id] = Path(record["local_path"])
                continue
            if (
                review.status == ReviewStatus.PENDING
                and review.disposition != ReviewDisposition.MANUAL_REGENERATE
                and not resolve_auto_disposition(judge_cfg).accepts_automatically
            ):
                raise ReviewRequiredError(review)
        existing = manifest.shots.get(request.shot_id)
        if existing and existing.asset_id:
            record = registry.find_by_asset_id(existing.asset_id)
            if (
                record
                and manifest.is_reusable(
                    request.shot_id,
                    request_fingerprint=request.request_fingerprint,
                    asset_path=Path(record["local_path"]),
                    content_sha256=record["content_sha256"],
                )
                and _selection_checkpoint_is_reusable(
                    request,
                    profile,
                    candidate_store,
                    has_reuse_source=existing.reuse_source is not None,
                )
            ):
                prepared[request.shot_id] = Path(record["local_path"])
                continue
        scene, shot = shots[request.shot_id]
        manifest.mark_running(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint)
        manifest.write_json(manifest_path)
        try:
            if (
                review is not None
                and review.status == ReviewStatus.PENDING
                and review.disposition == ReviewDisposition.MANUAL_REGENERATE
            ):
                record = resolver.resolve_manual_review(
                    request,
                    voiceover.segments[scene.source_segment_index],
                    review,
                    video_slug=voiceover.project_id or project_dir.name,
                )
                reuse_source = None
            else:
                reused = _parent_reuse(request, lineage, registry, video_slug=voiceover.project_id or project_dir.name)
                record, reuse_source = reused if reused is not None else (resolver.resolve(request, voiceover.segments[scene.source_segment_index], shot, video_slug=voiceover.project_id or project_dir.name), None)
            manifest.mark_done(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint, asset_id=record["asset_id"], reuse_source=reuse_source)
            manifest.write_json(manifest_path)
            prepared[request.shot_id] = Path(record["local_path"])
        except ReviewRequiredError:
            manifest.mark_pending(
                request.shot_id,
                request_id=request.request_id,
                request_fingerprint=request.request_fingerprint,
                reason=VisualPreparationState.REVIEW_REQUIRED.value,
            )
            manifest.write_json(manifest_path)
            raise
        except Exception as exc:
            manifest.mark_failed(request.shot_id, request_id=request.request_id, request_fingerprint=request.request_fingerprint, error=str(exc))
            manifest.write_json(manifest_path)
            raise
    return plan, manifest, validate_prepared_manifest(manifest, requests, registry)
