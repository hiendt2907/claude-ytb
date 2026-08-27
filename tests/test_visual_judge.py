"""Phase 10 — provider-neutral VisualJudge contract, strict schema
validation, repair-driving transport orchestration, and deterministic
ranked selection. Unit-level, no real provider — see
`docs/handoffs/2026-08-27-visual-judge-phase10-handoff.md` for why no
production vision-capable adapter exists yet.
"""
from __future__ import annotations

import json

import pytest

from ytb_pipeline.render.visual_judge import (
    CandidateEvaluation,
    JudgeCandidate,
    JudgeContext,
    JudgeInfrastructureError,
    JudgeMalformedResponseError,
    JudgeResult,
    evaluate_via_transport,
    parse_judge_payload,
    rank_eligible,
    select_vlm_ranked,
)


def _candidates(n=3):
    return tuple(
        JudgeCandidate(asset_id=f"ast_{i}", local_path=f"/tmp/c{i}.png", content_sha256=f"sha-{i}", candidate_index=i)
        for i in range(n)
    )


def _valid_payload(asset_ids, scores=None):
    scores = scores or {aid: 0.8 for aid in asset_ids}
    return {
        "evaluations": [
            {
                "asset_id": aid, "semantic_score": scores[aid], "character_score": scores[aid],
                "composition_score": scores[aid], "continuity_score": scores[aid],
                "hard_failures": [], "reasons": ["ok"],
            }
            for aid in asset_ids
        ]
    }


# --- Strict structured evaluation parsing (§50 items 2-6) ------------------

def test_valid_payload_parses_into_a_judge_result():
    candidates = _candidates(2)
    asset_ids = [c.asset_id for c in candidates]
    result = parse_judge_payload(_valid_payload(asset_ids), candidate_asset_ids=tuple(asset_ids), judge_provider="fake", judge_model="fake-v1")
    assert isinstance(result, JudgeResult)
    assert len(result.evaluations) == 2
    assert result.judge_provider == "fake" and result.judge_model == "fake-v1"


def test_unknown_candidate_asset_id_is_rejected():
    payload = _valid_payload(["ast_0", "ast_unknown"])
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(payload, candidate_asset_ids=("ast_0", "ast_1"), judge_provider="p", judge_model="m")


def test_missing_candidate_evaluation_is_rejected():
    payload = _valid_payload(["ast_0"])
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(payload, candidate_asset_ids=("ast_0", "ast_1"), judge_provider="p", judge_model="m")


def test_duplicate_candidate_evaluation_is_rejected():
    payload = _valid_payload(["ast_0", "ast_0"])
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(payload, candidate_asset_ids=("ast_0",), judge_provider="p", judge_model="m")


@pytest.mark.parametrize("bad_score", [-0.1, 1.1, "high", True])
def test_out_of_range_or_wrong_type_score_is_rejected(bad_score):
    payload = _valid_payload(["ast_0"])
    payload["evaluations"][0]["semantic_score"] = bad_score
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(payload, candidate_asset_ids=("ast_0",), judge_provider="p", judge_model="m")


def test_unknown_hard_failure_code_is_rejected():
    payload = _valid_payload(["ast_0"])
    payload["evaluations"][0]["hard_failures"] = ["candidate_is_ugly"]
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(payload, candidate_asset_ids=("ast_0",), judge_provider="p", judge_model="m")


def test_unknown_top_level_field_is_rejected():
    payload = _valid_payload(["ast_0"])
    payload["extra"] = "nope"
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(payload, candidate_asset_ids=("ast_0",), judge_provider="p", judge_model="m")


def test_unknown_evaluation_field_is_rejected():
    payload = _valid_payload(["ast_0"])
    payload["evaluations"][0]["beauty_score"] = 0.9
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(payload, candidate_asset_ids=("ast_0",), judge_provider="p", judge_model="m")


def test_non_dict_payload_is_rejected():
    with pytest.raises(JudgeMalformedResponseError):
        parse_judge_payload(["not", "a", "dict"], candidate_asset_ids=("ast_0",), judge_provider="p", judge_model="m")


# --- Repair policy (§50 items 7-8) ------------------------------------------

class _ScriptedTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def request(self, *, system, user):
        self.calls += 1
        return self._responses.pop(0)


def _request(shot_id="shot-1"):
    from types import SimpleNamespace
    return SimpleNamespace(visual_intent="minh nhìn xa xăm", characters=(), semantic_constraints=())


def test_malformed_response_gets_exactly_one_repair_attempt_and_succeeds():
    candidates = _candidates(1)
    asset_ids = [c.asset_id for c in candidates]
    transport = _ScriptedTransport(["not json", json.dumps(_valid_payload(asset_ids))])
    context = JudgeContext(scene_id="scene-000", shot_id="shot-1", video_slug="vid")
    result = evaluate_via_transport(transport, _request(), candidates, context, judge_provider="p", judge_model="m")
    assert transport.calls == 2
    assert len(result.evaluations) == 1


def test_second_malformed_response_raises_infrastructure_error():
    candidates = _candidates(1)
    transport = _ScriptedTransport(["not json", "still not json"])
    context = JudgeContext(scene_id="scene-000", shot_id="shot-1", video_slug="vid")
    with pytest.raises(JudgeInfrastructureError):
        evaluate_via_transport(transport, _request(), candidates, context, judge_provider="p", judge_model="m")
    assert transport.calls == 2


def test_transport_level_exception_propagates_without_retry():
    class _FailingTransport:
        def request(self, *, system, user):
            raise TimeoutError("provider down")

    candidates = _candidates(1)
    context = JudgeContext(scene_id="scene-000", shot_id="shot-1", video_slug="vid")
    with pytest.raises(TimeoutError):
        evaluate_via_transport(_FailingTransport(), _request(), candidates, context, judge_provider="p", judge_model="m")


# --- Deterministic ranking / eligibility (§52 items 16-19) ------------------

def _evaluation(asset_id, score, hard_failures=()):
    return CandidateEvaluation(
        asset_id=asset_id, semantic_score=score, character_score=score,
        composition_score=score, continuity_score=score, hard_failures=hard_failures,
    )


def test_highest_eligible_score_wins():
    result = JudgeResult((_evaluation("ast_0", 0.65), _evaluation("ast_1", 0.92), _evaluation("ast_2", 0.10)), "p", "m")
    index_by_asset = {"ast_0": 0, "ast_1": 1, "ast_2": 2}
    assert select_vlm_ranked(result, index_by_asset, minimum_score=0.5) == "ast_1"


def test_tie_break_is_deterministic_lowest_candidate_index():
    result = JudgeResult((_evaluation("ast_1", 0.8), _evaluation("ast_0", 0.8)), "p", "m")
    index_by_asset = {"ast_0": 0, "ast_1": 1}
    assert select_vlm_ranked(result, index_by_asset, minimum_score=0.5) == "ast_0"


def test_hard_failed_candidate_cannot_win_even_with_highest_score():
    result = JudgeResult((_evaluation("ast_0", 0.99, hard_failures=("required_character_absent",)), _evaluation("ast_1", 0.5)), "p", "m")
    index_by_asset = {"ast_0": 0, "ast_1": 1}
    assert select_vlm_ranked(result, index_by_asset, minimum_score=0.4) == "ast_1"


def test_candidate_below_threshold_cannot_win():
    result = JudgeResult((_evaluation("ast_0", 0.4),), "p", "m")
    index_by_asset = {"ast_0": 0}
    assert select_vlm_ranked(result, index_by_asset, minimum_score=0.65) is None


def test_all_candidates_rejected_yields_no_selection_not_an_exception():
    result = JudgeResult((_evaluation("ast_0", 0.1), _evaluation("ast_1", 0.2, hard_failures=("wrong_main_character",))), "p", "m")
    index_by_asset = {"ast_0": 0, "ast_1": 1}
    assert select_vlm_ranked(result, index_by_asset, minimum_score=0.5) is None


def test_rank_eligible_excludes_hard_failed_and_below_threshold():
    evaluations = (_evaluation("ast_0", 0.9, hard_failures=("semantic_contradiction",)), _evaluation("ast_1", 0.3), _evaluation("ast_2", 0.7))
    eligible = rank_eligible(evaluations, {"ast_0": 0, "ast_1": 1, "ast_2": 2}, minimum_score=0.5)
    assert [e.asset_id for e in eligible] == ["ast_2"]
