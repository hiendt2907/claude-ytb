"""Phase 13 visual-preparation review/disposition integration contracts."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from ytb_pipeline.render.asset_registry import AssetRegistry
from ytb_pipeline.render.scene_plan import Scene, ScenePlan, Shot
from ytb_pipeline.render.visual_assets import prepare_visual_assets
from ytb_pipeline.render.visual_candidates import VisualCandidateStore
from ytb_pipeline.render.visual_evaluation_store import VisualEvaluationStore
from ytb_pipeline.render.visual_judge import CandidateEvaluation, JudgeResult
from ytb_pipeline.render.visual_review import (
    ReviewReason,
    ReviewRequiredError,
    ReviewStatus,
    VisualAbandonedError,
    VisualReviewStore,
    VisualReviewError,
)
from ytb_pipeline.render.visual_review_ops import (
    abandon_visual_review,
    accept_existing_candidate,
    request_manual_regeneration,
)


def _segment(intent: str = "Minh đứng trước cửa quán") -> NS:
    return NS(visual_intent=intent, scene_characters=("minh",))


def _profile(*, recovery: str = "regenerate_once", hard_fail: bool = False) -> NS:
    return NS(
        profile_id="story",
        version="1",
        visual_generation=NS(
            enabled=True,
            style_prompt="illustrated story",
            negative_prompt="text, watermark",
            steps=10,
            cfg=5.0,
            solo_weight=1.0,
            duo_weight=1.0,
            duo_denoise=0.5,
            candidate_count=3,
            selection_policy="vlm_ranked",
            candidate_policy_version="phase9-v1",
            semantic_rejection_recovery=recovery,
            visual_judge=NS(
                enabled=True,
                provider="fake",
                model="fake-v1",
                policy_version="judge-v1",
                minimum_score=0.5,
                hard_fail_on_judge_error=hard_fail,
            ),
        ),
    )


def _plan(intent: str = "Minh đứng trước cửa quán") -> ScenePlan:
    shot = Shot("shot-001", 0.0, 3.0, "generated", intent, "", ("minh",))
    scene = Scene(
        "scene-001", 0, 0.0, 3.0, "core", intent, ("minh",), (shot,)
    )
    return ScenePlan((scene,), f"plan-{intent}")


class _Provider:
    def __init__(self, *, fail_once: str | None = None) -> None:
        self.calls = 0
        self.fail_once = fail_once

    def generate_scene(self, profile, **kwargs) -> None:
        self.calls += 1
        path = Path(kwargs["output_path"])
        if self.fail_once and self.fail_once in path.name:
            self.fail_once = None
            raise RuntimeError("ComfyUI unavailable")
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), (self.calls, self.calls, self.calls)).save(path)


class _Judge:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.batches: list[tuple[str, ...]] = []

    def evaluate(self, request, candidates, context) -> JudgeResult:
        self.calls += 1
        self.batches.append(tuple(item.asset_id for item in candidates))
        response = self.responses.pop(0)
        if response == "infrastructure_error":
            raise RuntimeError("xKiro timeout")
        evaluations = []
        for candidate in candidates:
            score = 0.1
            if response == "select_first":
                score = 0.9 if candidate.candidate_index == 0 else 0.1
            elif response != "reject":
                raise AssertionError(response)
            evaluations.append(
                CandidateEvaluation(
                    candidate.asset_id,
                    score,
                    score,
                    score,
                    score,
                    (),
                    (response,),
                )
            )
        return JudgeResult(tuple(evaluations), "fake", "fake-v1")


class _NoCalls:
    def generate_scene(self, *args, **kwargs) -> None:
        raise AssertionError("generation must not run")

    def evaluate(self, *args, **kwargs) -> JudgeResult:
        raise AssertionError("Judge must not run")


def _prepare(
    tmp_path,
    *,
    profile,
    registry,
    provider,
    judge,
    plan: ScenePlan | None = None,
):
    return prepare_visual_assets(
        NS(project_id="video", segments=(_segment((plan or _plan()).scenes[0].visual_intent),)),
        profile,
        project_dir=tmp_path / "project",
        dimensions=(1920, 1080),
        scene_plan=plan or _plan(),
        registry=registry,
        cache_dir=tmp_path / "cache",
        provider=provider,
        judge=judge,
    )


def _review(tmp_path):
    entry = VisualReviewStore(tmp_path / "project" / "visual_review.json").current_for_shot("shot-001")
    assert entry is not None
    return entry


def test_fail_closed_semantic_rejection_creates_pending_review(tmp_path):
    provider = _Provider()
    judge = _Judge("reject")
    registry = AssetRegistry(tmp_path / "registry.json")

    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(recovery="fail_closed"),
            registry=registry,
            provider=provider,
            judge=judge,
        )

    entry = _review(tmp_path)
    assert provider.calls == 3
    assert judge.calls == 1
    assert entry.status == ReviewStatus.PENDING
    assert entry.review_reason == ReviewReason.SEMANTIC_FAIL_CLOSED
    assert len(entry.candidate_asset_ids) == 3


def test_exhausted_recovery_creates_one_idempotent_pending_review(tmp_path):
    provider = _Provider()
    judge = _Judge("reject", "reject")
    registry = AssetRegistry(tmp_path / "registry.json")
    profile = _profile()

    with pytest.raises(ReviewRequiredError):
        _prepare(tmp_path, profile=profile, registry=registry, provider=provider, judge=judge)
    first = _review(tmp_path)
    with pytest.raises(ReviewRequiredError):
        _prepare(tmp_path, profile=profile, registry=registry, provider=_NoCalls(), judge=_NoCalls())

    assert first.review_reason == ReviewReason.SEMANTIC_RECOVERY_EXHAUSTED
    assert len(first.candidate_asset_ids) == 6
    assert len(VisualReviewStore(tmp_path / "project" / "visual_review.json").entries()) == 1


def test_happy_path_and_judge_infrastructure_fallback_create_no_review(tmp_path):
    first_root = tmp_path / "happy"
    first_registry = AssetRegistry(first_root / "registry.json")
    _prepare(
        first_root,
        profile=_profile(),
        registry=first_registry,
        provider=_Provider(),
        judge=_Judge("select_first"),
    )
    assert not (first_root / "project" / "visual_review.json").exists()

    fallback_root = tmp_path / "fallback"
    fallback_registry = AssetRegistry(fallback_root / "registry.json")
    _prepare(
        fallback_root,
        profile=_profile(hard_fail=False),
        registry=fallback_registry,
        provider=_Provider(),
        judge=_Judge("infrastructure_error"),
    )
    assert not (fallback_root / "project" / "visual_review.json").exists()


def test_human_accept_existing_updates_manifest_and_reruns_without_ai(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject", "reject"),
        )
    candidate_set = VisualCandidateStore(
        tmp_path / "project" / "visual_candidates.json"
    ).get("shot-001")
    accepted_asset_id = candidate_set.slot(1, generation_round=0).asset_id

    accepted = accept_existing_candidate(
        tmp_path / "project",
        "shot-001",
        accepted_asset_id,
        registry=registry,
    )
    _, manifest, _prepared = _prepare(
        tmp_path,
        profile=_profile(),
        registry=registry,
        provider=_NoCalls(),
        judge=_NoCalls(),
    )

    assert accepted.status == ReviewStatus.RESOLVED
    assert accepted.selection_mode == "operator_override"
    assert manifest.shots["shot-001"].asset_id == accepted_asset_id
    assert VisualEvaluationStore(tmp_path / "project" / "visual_evaluations.json").get("shot-001") is not None


def test_manual_regenerate_uses_separate_lineage_and_one_judge_then_resolves(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject", "reject"),
        )
    original_assets = {record["asset_id"] for record in registry.assets()}
    original_eval = VisualEvaluationStore(tmp_path / "project" / "visual_evaluations.json").get("shot-001")
    request_manual_regeneration(
        tmp_path / "project",
        "shot-001",
        "Giữ Minh một mình ở tiền cảnh. Bỏ đám đông phía sau.",
    )
    provider = _Provider()
    judge = _Judge("select_first")

    _, manifest, _prepared = _prepare(
        tmp_path,
        profile=_profile(),
        registry=registry,
        provider=provider,
        judge=judge,
    )

    entry = _review(tmp_path)
    assert provider.calls == 3
    assert judge.calls == 1
    assert entry.status == ReviewStatus.RESOLVED
    assert entry.manual_override.status == "resolved"
    assert entry.manual_override.selected_asset_id == manifest.shots["shot-001"].asset_id
    assert len(registry.assets()) == 9
    assert original_assets < {record["asset_id"] for record in registry.assets()}
    store = VisualEvaluationStore(tmp_path / "project" / "visual_evaluations.json")
    assert store.get("shot-001") == original_eval
    assert store.get(entry.manual_override.evaluation_store_key) is not None
    assert all("round-02" not in path.name for path in (tmp_path / "cache").iterdir())


def test_manual_semantic_rejection_remains_pending_without_second_attempt(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject", "reject"),
        )
    request_manual_regeneration(
        tmp_path / "project", "shot-001", "Chỉ để Minh trong khung hình"
    )
    provider = _Provider()
    judge = _Judge("reject")

    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=provider,
            judge=judge,
        )
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_NoCalls(),
            judge=_NoCalls(),
        )

    entry = _review(tmp_path)
    assert provider.calls == 3
    assert judge.calls == 1
    assert entry.status == ReviewStatus.PENDING
    assert entry.review_reason == ReviewReason.MANUAL_SEMANTIC_REJECTION
    assert entry.manual_override.status == "rejected"


def test_abandoned_review_stops_future_provider_work(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject", "reject"),
        )
    abandon_visual_review(tmp_path / "project", "shot-001")

    with pytest.raises(VisualAbandonedError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_NoCalls(),
            judge=_NoCalls(),
        )


def test_manual_partial_generation_resumes_only_failed_candidate(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject", "reject"),
        )
    request_manual_regeneration(
        tmp_path / "project", "shot-001", "Bỏ đám đông phía sau"
    )
    provider = _Provider(fail_once=".manual-candidate-02.png")

    with pytest.raises(ValueError, match="Manual generation chưa hoàn tất"):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=provider,
            judge=_NoCalls(),
        )
    after_failure = _review(tmp_path)
    completed_ids = {
        slot.asset_id
        for slot in after_failure.manual_override.candidates[:2]
    }
    assert provider.calls == 3
    assert after_failure.manual_override.candidates[2].status == "failed"

    _prepare(
        tmp_path,
        profile=_profile(),
        registry=registry,
        provider=provider,
        judge=_Judge("select_first"),
    )
    resolved = _review(tmp_path)
    assert provider.calls == 4
    assert {
        slot.asset_id for slot in resolved.manual_override.candidates[:2]
    } == completed_ids
    assert resolved.status == ReviewStatus.RESOLVED


@pytest.mark.parametrize("damage", ["missing", "sha"])
def test_accepted_asset_damage_returns_to_review_without_auto_selection(tmp_path, damage):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(recovery="fail_closed"),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject"),
        )
    candidate_set = VisualCandidateStore(tmp_path / "project" / "visual_candidates.json").get("shot-001")
    asset_id = candidate_set.slot(0).asset_id
    record = registry.find_by_asset_id(asset_id)
    accept_existing_candidate(
        tmp_path / "project", "shot-001", asset_id, registry=registry
    )
    path = Path(record["local_path"])
    if damage == "missing":
        path.unlink()
    else:
        Image.new("RGB", (8, 8), (250, 0, 0)).save(path)

    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(recovery="fail_closed"),
            registry=registry,
            provider=_NoCalls(),
            judge=_NoCalls(),
        )

    entry = _review(tmp_path)
    assert entry.status == ReviewStatus.PENDING
    assert entry.review_reason == ReviewReason.ACCEPTED_ASSET_INVALID
    assert entry.selected_asset_id == asset_id


def test_accept_rejects_arbitrary_asset_from_another_shot(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(recovery="fail_closed"),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject"),
        )
    foreign = tmp_path / "foreign.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(foreign)
    foreign_id = registry.record_generated(
        generation_key="f" * 64,
        local_path=foreign,
        is_fresh_generation=True,
        profile_id="story",
        profile_version="1",
        seed=1,
        scene_id="foreign-scene",
        shot_id="foreign-shot",
        video_slug="other-project",
    )

    with pytest.raises(VisualReviewError, match="không thuộc candidate history"):
        accept_existing_candidate(
            tmp_path / "project", "shot-001", foreign_id, registry=registry
        )


@pytest.mark.parametrize("disposition", ["abandon", "manual"])
def test_changed_request_stales_human_disposition_and_runs_fresh_automation(
    tmp_path, disposition
):
    registry = AssetRegistry(tmp_path / "registry.json")
    with pytest.raises(ReviewRequiredError):
        _prepare(
            tmp_path,
            profile=_profile(),
            registry=registry,
            provider=_Provider(),
            judge=_Judge("reject", "reject"),
        )
    old = _review(tmp_path)
    if disposition == "abandon":
        abandon_visual_review(tmp_path / "project", "shot-001")
    else:
        request_manual_regeneration(
            tmp_path / "project", "shot-001", "Bỏ đám đông phía sau"
        )
    provider = _Provider()
    judge = _Judge("select_first")

    _prepare(
        tmp_path,
        profile=_profile(),
        registry=registry,
        provider=provider,
        judge=judge,
        plan=_plan("Minh đứng một mình bên cửa sổ"),
    )

    assert provider.calls == 3
    assert judge.calls == 1
    store = VisualReviewStore(tmp_path / "project" / "visual_review.json")
    assert store.get(old.review_id).status == ReviewStatus.STALE
    assert store.current_for_shot("shot-001") is None
