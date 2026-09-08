"""Phase 12 — one durable, opt-in semantic-rejection recovery round.

All generation and Judge boundaries are local fakes.  The tests exercise the
real candidate/evaluation/manifest stores under ``tmp_path`` and never call
ComfyUI or xKiro.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from ytb_pipeline.render.asset_registry import AssetRegistry
from ytb_pipeline.render.scene_plan import Scene, ScenePlan, Shot
from ytb_pipeline.render.visual_assets import (
    VisualAssetResolver,
    VisualRequest,
    prepare_visual_assets,
)
from ytb_pipeline.render.visual_candidates import VisualCandidateStore
from ytb_pipeline.render.visual_evaluation_store import VisualEvaluationStore
from ytb_pipeline.render.visual_judge import CandidateEvaluation, JudgeResult


def _request(*, fingerprint: str = "request-fp", intent: str = "Minh nhìn An") -> VisualRequest:
    return VisualRequest(
        request_id=f"vr-{fingerprint}",
        request_fingerprint=fingerprint,
        scene_id="scene-000",
        shot_id="scene-000-shot-00",
        visual_intent=intent,
        characters=("minh", "an"),
        dimensions=(1080, 1920),
        resolution_kind="generated_image",
    )


def _segment(*, intent: str = "Minh nhìn An") -> NS:
    return NS(visual_intent=intent, scene_characters=("minh", "an"))


def _visual(
    *,
    recovery: str = "fail_closed",
    selection_policy: str = "vlm_ranked",
    hard_fail: bool = False,
    model: str = "fake-v1",
    judge_policy_version: str = "judge-v1",
    candidate_count: int = 3,
) -> NS:
    return NS(
        enabled=True,
        style_prompt="illustrated story",
        negative_prompt="text, watermark",
        steps=10,
        cfg=5.0,
        solo_weight=1.0,
        duo_weight=1.0,
        duo_denoise=0.5,
        candidate_count=candidate_count,
        selection_policy=selection_policy,
        candidate_policy_version="phase9-v1",
        semantic_rejection_recovery=recovery,
        visual_judge=NS(
            enabled=True,
            provider="fake",
            model=model,
            policy_version=judge_policy_version,
            minimum_score=0.5,
            hard_fail_on_judge_error=hard_fail,
        ),
    )


def _profile(**visual_overrides) -> NS:
    return NS(profile_id="story", version="1", visual_generation=_visual(**visual_overrides))


class _CountingProvider:
    def __init__(self, *, fail_once_path_fragment: str | None = None) -> None:
        self.calls = 0
        self.paths: list[Path] = []
        self.seeds: list[int] = []
        self.fail_once_path_fragment = fail_once_path_fragment

    def generate_scene(self, profile, **kwargs) -> None:
        self.calls += 1
        path = Path(kwargs["output_path"])
        self.paths.append(path)
        self.seeds.append(kwargs["seed"])
        if self.fail_once_path_fragment and self.fail_once_path_fragment in path.name:
            self.fail_once_path_fragment = None
            raise RuntimeError("ComfyUI generation failed")
        path.parent.mkdir(parents=True, exist_ok=True)
        value = self.calls % 255
        Image.new("RGB", (8, 8), (value, value, value)).save(path)


class _SequenceJudge:
    def __init__(self, *responses: str, provider: str = "fake", model: str = "fake-v1") -> None:
        self.responses = list(responses)
        self.provider = provider
        self.model = model
        self.calls = 0
        self.batches: list[tuple[tuple[str, int], ...]] = []

    def evaluate(self, request, candidates, context) -> JudgeResult:
        self.calls += 1
        self.batches.append(tuple((item.asset_id, item.candidate_index) for item in candidates))
        response = self.responses.pop(0)
        if response == "infrastructure_error":
            raise RuntimeError("Judge transport timeout")
        evaluations = []
        for candidate in candidates:
            score = 0.1
            if response == "select_first":
                score = 0.9 if candidate.candidate_index == 0 else 0.1
            elif response == "select_round1":
                score = 0.9 if candidate.candidate_index == 4 else 0.1
            elif response != "reject":
                raise AssertionError(f"unknown fake response: {response}")
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
        return JudgeResult(tuple(evaluations), self.provider, self.model)


class _NoCalls:
    def generate_scene(self, *args, **kwargs) -> None:
        raise AssertionError("generation must not run")

    def evaluate(self, *args, **kwargs) -> JudgeResult:
        raise AssertionError("Judge must not run")


def _resolver(tmp_path, *, profile, registry, provider, judge) -> VisualAssetResolver:
    project = tmp_path / "project"
    return VisualAssetResolver(
        profile,
        registry=registry,
        cache_dir=tmp_path / "cache",
        provider=provider,
        candidate_store=VisualCandidateStore(project / "visual_candidates.json"),
        judge=judge,
        evaluation_store=VisualEvaluationStore(project / "visual_evaluations.json"),
    )


def _candidate_set(tmp_path) -> object:
    candidate_set = VisualCandidateStore(
        tmp_path / "project" / "visual_candidates.json"
    ).get("scene-000-shot-00")
    assert candidate_set is not None
    return candidate_set


def _plan() -> ScenePlan:
    shot = Shot(
        "scene-000-shot-00",
        0,
        3.0,
        "generated",
        "Minh nhìn An",
        "",
        ("minh", "an"),
    )
    scene = Scene(
        "scene-000",
        0,
        0,
        3.0,
        "core",
        "Minh nhìn An",
        ("minh", "an"),
        (shot,),
    )
    return ScenePlan((scene,), "phase12-plan")


def test_default_fail_closed_semantic_rejection_generates_only_round_zero(tmp_path):
    provider = _CountingProvider()
    judge = _SequenceJudge("reject")
    resolver = _resolver(
        tmp_path,
        profile=_profile(),
        registry=AssetRegistry(tmp_path / "registry.json"),
        provider=provider,
        judge=judge,
    )

    with pytest.raises(ValueError, match="Không có candidate hợp lệ"):
        resolver.resolve(_request(), _segment(), None, video_slug="video")

    candidate_set = _candidate_set(tmp_path)
    assert provider.calls == 3
    assert judge.calls == 1
    assert candidate_set.recovery_policy == "fail_closed"
    assert candidate_set.recovery_status == "eligible"
    assert candidate_set.semantic_rejection_rounds == [0]
    assert all(slot.generation_round == 0 for slot in candidate_set.candidates.values())


def test_first_valid_ignores_regeneration_policy_and_never_calls_judge(tmp_path):
    provider = _CountingProvider()
    resolver = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once", selection_policy="first_valid"),
        registry=AssetRegistry(tmp_path / "registry.json"),
        provider=provider,
        judge=_NoCalls(),
    )

    resolver.resolve(_request(), _segment(), None, video_slug="video")

    candidate_set = _candidate_set(tmp_path)
    assert provider.calls == 3
    assert candidate_set.active_generation_round == 0
    assert candidate_set.recovery_status == "not_needed"


def test_successful_round_zero_selection_never_starts_recovery(tmp_path):
    provider = _CountingProvider()
    judge = _SequenceJudge("select_first")
    resolver = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=AssetRegistry(tmp_path / "registry.json"),
        provider=provider,
        judge=judge,
    )

    resolver.resolve(_request(), _segment(), None, video_slug="video")

    candidate_set = _candidate_set(tmp_path)
    assert provider.calls == 3
    assert judge.calls == 1
    assert candidate_set.active_generation_round == 0
    assert candidate_set.recovery_status == "not_needed"


@pytest.mark.parametrize("hard_fail", [False, True])
def test_judge_infrastructure_failure_never_triggers_recovery(tmp_path, hard_fail):
    provider = _CountingProvider()
    judge = _SequenceJudge("infrastructure_error")
    resolver = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once", hard_fail=hard_fail),
        registry=AssetRegistry(tmp_path / "registry.json"),
        provider=provider,
        judge=judge,
    )

    if hard_fail:
        with pytest.raises(ValueError, match="hard_fail_on_judge_error"):
            resolver.resolve(_request(), _segment(), None, video_slug="video")
    else:
        resolver.resolve(_request(), _segment(), None, video_slug="video")

    candidate_set = _candidate_set(tmp_path)
    assert provider.calls == 3
    assert judge.calls == 1
    assert candidate_set.active_generation_round == 0
    assert candidate_set.semantic_rejection_rounds == []
    assert candidate_set.recovery_status == "not_needed"


def test_recovery_success_generates_six_assets_judges_twice_and_prepared_rerender_is_pure(tmp_path):
    profile = _profile(recovery="regenerate_once")
    provider = _CountingProvider()
    judge = _SequenceJudge("reject", "select_round1")
    registry = AssetRegistry(tmp_path / "registry.json")
    project = tmp_path / "project"
    voiceover = NS(project_id="phase12", segments=(_segment(),))

    _, manifest, prepared = prepare_visual_assets(
        voiceover,
        profile,
        project_dir=project,
        dimensions=(1080, 1920),
        scene_plan=_plan(),
        registry=registry,
        cache_dir=tmp_path / "cache",
        provider=provider,
        judge=judge,
    )

    candidate_set = _candidate_set(tmp_path)
    selected = candidate_set.slot(1, generation_round=1).asset_id
    assert provider.calls == 6
    assert judge.calls == 2
    assert [len(batch) for batch in judge.batches] == [3, 6]
    assert len(registry.assets()) == 6
    assert manifest.shots["scene-000-shot-00"].asset_id == selected
    assert candidate_set.recovery_status == "resolved"
    assert candidate_set.semantic_rejection_rounds == [0]
    assert candidate_set.active_generation_round == 1
    assert {record["generation_key"] for record in registry.assets()} == {
        registry.assets()[0]["generation_key"]
    }
    assert len({record["seed"] for record in registry.assets()}) == 6
    assert all(
        not ({"rejected", "recovery_round_winner", "quality", "bad"} & set(record))
        for record in registry.assets()
    )
    registry_snapshot = {
        record["asset_id"]: dict(record)
        for record in registry.assets()
    }

    _, manifest_again, prepared_again = prepare_visual_assets(
        voiceover,
        profile,
        project_dir=project,
        dimensions=(1080, 1920),
        scene_plan=_plan(),
        registry=registry,
        cache_dir=tmp_path / "cache",
        provider=_NoCalls(),
        judge=_NoCalls(),
    )
    assert manifest_again.shots["scene-000-shot-00"].asset_id == selected
    assert prepared_again == prepared
    assert {
        record["asset_id"]: dict(record)
        for record in registry.assets()
    } == registry_snapshot


def test_new_whole_set_evaluation_may_select_a_round_zero_asset(tmp_path):
    provider = _CountingProvider()
    judge = _SequenceJudge("reject", "select_first")
    registry = AssetRegistry(tmp_path / "registry.json")
    resolver = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=registry,
        provider=provider,
        judge=judge,
    )

    record = resolver.resolve(_request(), _segment(), None, video_slug="video")

    candidate_set = _candidate_set(tmp_path)
    assert record["asset_id"] == candidate_set.slot(0, generation_round=0).asset_id
    assert len(judge.batches[1]) == 6


def test_round_one_partial_generation_resumes_only_failed_slot(tmp_path):
    provider = _CountingProvider(
        fail_once_path_fragment=".round-01.candidate-02.png"
    )
    registry = AssetRegistry(tmp_path / "registry.json")
    first_judge = _SequenceJudge("reject")
    first = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=registry,
        provider=provider,
        judge=first_judge,
    )

    with pytest.raises(ValueError, match="round 1 generation"):
        first.resolve(_request(), _segment(), None, video_slug="video")

    persisted = _candidate_set(tmp_path)
    assert provider.calls == 6
    assert first_judge.calls == 1
    assert persisted.slot(0, generation_round=1).status == "done"
    assert persisted.slot(1, generation_round=1).status == "done"
    assert persisted.slot(2, generation_round=1).status == "failed"
    completed_ids = {
        persisted.slot(0, generation_round=1).asset_id,
        persisted.slot(1, generation_round=1).asset_id,
    }

    resumed_judge = _SequenceJudge("select_round1")
    resumed = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=registry,
        provider=provider,
        judge=resumed_judge,
    )
    resumed.resolve(_request(), _segment(), None, video_slug="video")

    restored = _candidate_set(tmp_path)
    assert provider.calls == 7
    assert resumed_judge.calls == 1
    assert {
        restored.slot(0, generation_round=1).asset_id,
        restored.slot(1, generation_round=1).asset_id,
    } == completed_ids
    assert restored.slot(2, generation_round=1).status == "done"


def test_recovery_exhaustion_is_durable_and_rerun_creates_no_round_two(tmp_path):
    profile = _profile(recovery="regenerate_once")
    registry = AssetRegistry(tmp_path / "registry.json")
    provider = _CountingProvider()
    judge = _SequenceJudge("reject", "reject")
    resolver = _resolver(
        tmp_path,
        profile=profile,
        registry=registry,
        provider=provider,
        judge=judge,
    )

    with pytest.raises(ValueError, match="recovery exhausted"):
        resolver.resolve(_request(), _segment(), None, video_slug="video")

    exhausted = _candidate_set(tmp_path)
    assert provider.calls == 6
    assert judge.calls == 2
    assert exhausted.recovery_status == "exhausted"
    assert exhausted.semantic_rejection_rounds == [0, 1]
    assert all(slot.generation_round <= 1 for slot in exhausted.candidates.values())

    rerun = _resolver(
        tmp_path,
        profile=profile,
        registry=registry,
        provider=_NoCalls(),
        judge=_NoCalls(),
    )
    with pytest.raises(ValueError, match="recovery exhausted"):
        rerun.resolve(_request(), _segment(), None, video_slug="video")

    unchanged = _candidate_set(tmp_path)
    assert len(registry.assets()) == 6
    assert unchanged.semantic_rejection_rounds == [0, 1]
    assert all("round-02" not in slot_id for slot_id in unchanged.candidates)


def test_fail_closed_to_regenerate_once_reuses_round_zero_then_starts_only_round_one(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    provider = _CountingProvider()
    first = _resolver(
        tmp_path,
        profile=_profile(recovery="fail_closed"),
        registry=registry,
        provider=provider,
        judge=_SequenceJudge("reject"),
    )
    with pytest.raises(ValueError):
        first.resolve(_request(), _segment(), None, video_slug="video")
    assert provider.calls == 3

    second_judge = _SequenceJudge("select_round1")
    second = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=registry,
        provider=provider,
        judge=second_judge,
    )
    second.resolve(_request(), _segment(), None, video_slug="video")

    assert provider.calls == 6
    assert second_judge.calls == 1
    assert len(registry.assets()) == 6


def test_judge_model_change_rejudges_existing_exhausted_media_without_regeneration(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    provider = _CountingProvider()
    first = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=registry,
        provider=provider,
        judge=_SequenceJudge("reject", "reject"),
    )
    with pytest.raises(ValueError):
        first.resolve(_request(), _segment(), None, video_slug="video")
    assert len(registry.assets()) == 6

    changed_judge = _SequenceJudge("select_first", model="fake-v2")
    changed = _resolver(
        tmp_path,
        profile=_profile(recovery="fail_closed", model="fake-v2"),
        registry=registry,
        provider=_NoCalls(),
        judge=changed_judge,
    )
    record = changed.resolve(_request(), _segment(), None, video_slug="video")

    assert record["asset_id"] is not None
    assert changed_judge.calls == 1
    assert len(changed_judge.batches[0]) == 6
    assert len(registry.assets()) == 6
    assert _candidate_set(tmp_path).recovery_status == "resolved"


def test_regenerate_once_to_fail_closed_preserves_both_rounds_and_budget(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    first = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=registry,
        provider=_CountingProvider(),
        judge=_SequenceJudge("reject", "reject"),
    )
    with pytest.raises(ValueError, match="recovery exhausted"):
        first.resolve(_request(), _segment(), None, video_slug="video")
    before = {record["asset_id"]: dict(record) for record in registry.assets()}

    changed_policy = _resolver(
        tmp_path,
        profile=_profile(recovery="fail_closed"),
        registry=registry,
        provider=_NoCalls(),
        judge=_NoCalls(),
    )
    with pytest.raises(ValueError, match="recovery exhausted"):
        changed_policy.resolve(_request(), _segment(), None, video_slug="video")

    persisted = _candidate_set(tmp_path)
    assert persisted.recovery_policy == "fail_closed"
    assert persisted.recovery_status == "exhausted"
    assert persisted.semantic_rejection_rounds == [0, 1]
    assert {record["asset_id"]: dict(record) for record in registry.assets()} == before


def test_round_zero_generation_failure_is_not_semantic_rejection(tmp_path):
    class _AlwaysFailProvider:
        calls = 0

        def generate_scene(self, profile, **kwargs) -> None:
            self.calls += 1
            raise RuntimeError("ComfyUI unavailable")

    provider = _AlwaysFailProvider()
    resolver = _resolver(
        tmp_path,
        profile=_profile(recovery="regenerate_once"),
        registry=AssetRegistry(tmp_path / "registry.json"),
        provider=provider,
        judge=_NoCalls(),
    )

    with pytest.raises(ValueError, match="Không có candidate hợp lệ"):
        resolver.resolve(_request(), _segment(), None, video_slug="video")

    candidate_set = _candidate_set(tmp_path)
    assert provider.calls == 3
    assert candidate_set.semantic_rejection_rounds == []
    assert candidate_set.recovery_status == "not_needed"
    assert candidate_set.active_generation_round == 0
