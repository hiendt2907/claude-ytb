"""Phase 10 — evaluation persistence, identity/fingerprint invalidation.

Covers `render/visual_evaluation_store.py` in isolation: reuse only when
request + candidate identity + judge context all agree; any single change
invalidates. See `tests/test_visual_assets.py` for the end-to-end resolver
wiring that actually calls `matches_context`/`matches_candidate_identity`.
"""
from __future__ import annotations

from ytb_pipeline.render.visual_evaluation_store import ShotEvaluationSet, VisualEvaluationStore
from ytb_pipeline.render.visual_judge import CandidateEvaluation


def _evaluation_set(**overrides):
    base = dict(
        shot_id="shot-1", request_fingerprint="fp-1", judge_provider="fake",
        judge_model="fake-v1", judge_policy_version="v1", judge_contract_version="phase10-v1",
        candidate_identity={"ast_0": "sha-0", "ast_1": "sha-1"},
        evaluations={
            "ast_0": CandidateEvaluation("ast_0", 0.8, 0.8, 0.8, 0.8),
            "ast_1": CandidateEvaluation("ast_1", 0.5, 0.5, 0.5, 0.5),
        },
    )
    base.update(overrides)
    return ShotEvaluationSet(**base)


def _matches(evaluation_set, **overrides):
    kwargs = dict(
        request_fingerprint="fp-1", judge_provider="fake", judge_model="fake-v1",
        judge_policy_version="v1", judge_contract_version="phase10-v1",
    )
    kwargs.update(overrides)
    return evaluation_set.matches_context(**kwargs)


# --- Evaluation identity (§51 items 9-14) -----------------------------------

def test_identical_context_and_candidate_identity_matches():
    evaluation_set = _evaluation_set()
    assert _matches(evaluation_set)
    assert evaluation_set.matches_candidate_identity({"ast_0": "sha-0", "ast_1": "sha-1"})


def test_request_fingerprint_change_invalidates():
    evaluation_set = _evaluation_set()
    assert not _matches(evaluation_set, request_fingerprint="fp-2")


def test_candidate_content_sha_change_invalidates():
    evaluation_set = _evaluation_set()
    assert not evaluation_set.matches_candidate_identity({"ast_0": "sha-CHANGED", "ast_1": "sha-1"})


def test_added_or_removed_candidate_invalidates():
    evaluation_set = _evaluation_set()
    assert not evaluation_set.matches_candidate_identity({"ast_0": "sha-0"})
    assert not evaluation_set.matches_candidate_identity({"ast_0": "sha-0", "ast_1": "sha-1", "ast_2": "sha-2"})


def test_judge_policy_version_change_invalidates():
    evaluation_set = _evaluation_set()
    assert not _matches(evaluation_set, judge_policy_version="v2")


def test_judge_provider_or_model_change_invalidates():
    evaluation_set = _evaluation_set()
    assert not _matches(evaluation_set, judge_provider="other")
    assert not _matches(evaluation_set, judge_model="other-model")


def test_judge_contract_version_change_invalidates():
    evaluation_set = _evaluation_set()
    assert not _matches(evaluation_set, judge_contract_version="phase11-v1")


def test_unrelated_field_order_or_extra_dict_keys_do_not_spuriously_invalidate():
    """Item 14: unrelated runtime state must not invalidate — rebuilding
    the identical candidate_identity dict via a different insertion order
    is still equal."""
    evaluation_set = _evaluation_set()
    rebuilt = {}
    rebuilt["ast_1"] = "sha-1"
    rebuilt["ast_0"] = "sha-0"
    assert evaluation_set.matches_candidate_identity(rebuilt)


# --- Persistence round-trip --------------------------------------------------

def test_store_persists_and_reloads_evaluation_sets(tmp_path):
    path = tmp_path / "visual_evaluations.json"
    store = VisualEvaluationStore(path)
    store.save(_evaluation_set())
    store.write()

    reloaded = VisualEvaluationStore(path)
    restored = reloaded.get("shot-1")
    assert restored is not None
    assert restored.evaluations["ast_0"].semantic_score == 0.8
    assert restored.candidate_identity == {"ast_0": "sha-0", "ast_1": "sha-1"}


def test_fallback_evaluation_set_persists_error_and_flag(tmp_path):
    path = tmp_path / "visual_evaluations.json"
    store = VisualEvaluationStore(path)
    store.save(_evaluation_set(evaluations={}, fallback_used=True, judge_error="timeout"))
    store.write()

    reloaded = VisualEvaluationStore(path)
    restored = reloaded.get("shot-1")
    assert restored.fallback_used is True
    assert restored.judge_error == "timeout"
    assert restored.evaluations == {}


def test_reading_an_absent_store_returns_none_for_any_shot(tmp_path):
    store = VisualEvaluationStore(tmp_path / "missing.json")
    assert store.get("shot-1") is None
