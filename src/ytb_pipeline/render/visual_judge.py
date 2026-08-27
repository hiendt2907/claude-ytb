"""Provider-neutral semantic VisualJudge contract (Phase 10).

    technically-valid candidate AssetRecords
        -> VisualJudge.evaluate(request, candidates, context)
        -> CandidateEvaluation[] (strictly validated)
        -> ranked, deterministic selection (`select_vlm_ranked`)

This module owns exactly the SEMANTIC EVALUATION concern — it never
generates media (that stays in `visual_candidates.py`/ComfyUI provider),
never touches `AssetRegistry` provenance (immutable, generation-time
facts), and never renders (the renderer never imports this module).

No production vision-capable provider is configured in this repository as
of Phase 10 (`xkiro`/DeepSeek V4 Pro and the Claude CLI wrapper are both
text-only `LLMProvider.complete(prompt: str) -> str`, with no image
attachment in their signatures — see `providers/llm/*.py`). This module
therefore ships the full provider-neutral contract, strict schema
validation, the generic single-call-per-shot repair-driving orchestration
(`evaluate_via_transport`) any future adapter can implement against, and
a scoring/ranking implementation — but no adapter that claims to actually
see an image. `docs/handoffs/2026-08-27-visual-judge-phase10-handoff.md`
documents this blocker explicitly; `FakeVisualJudge` in
`tests/test_visual_judge.py` is a test double only, never wired into a
production code path.

Judge output is judged strictly: unknown top-level/evaluation fields,
unknown candidate `asset_id`s, missing candidates, duplicate candidate
evaluations, out-of-range scores, and unknown hard-failure codes all raise
`JudgeMalformedResponseError`. `evaluate_via_transport` allows exactly ONE
repair round-trip before treating a still-malformed response as a
`JudgeInfrastructureError` — the same class raised for a transport-level
failure (timeout, provider unavailable). Infrastructure failure and
semantic rejection are DELIBERATELY different: infra failure may fall
back to `first_valid` when a profile opts in
(`visual_judge.hard_fail_on_judge_error=False`); a successfully evaluated
candidate set where every candidate is hard-failed or below
`minimum_score` NEVER falls back — `visual_assets` fails closed for that
Shot, or semantic QC would mean nothing (see `render/visual_assets.py`'s
`_select_vlm_ranked`).

Explicitly OUT of scope, matching Phase 10's directive: no
beauty/attractiveness/body/age/gender/race desirability scoring of any
kind. The allowed dimensions are request-fidelity/technical-composition
only (`KNOWN_HARD_FAILURE_CODES`, `_SCORE_FIELDS`).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

CONTRACT_VERSION = "phase10-v1"

# Bounded, request-fidelity/technical-composition failure codes only — see
# module docstring §7/§8 of the Phase 10 directive: no appearance scoring.
KNOWN_HARD_FAILURE_CODES = frozenset({
    "required_character_absent",
    "wrong_main_character",
    "missing_required_object",
    "wrong_environment",
    "semantic_contradiction",
    "unreadable_required_text",
    "unsupported_format",
})

_SCORE_FIELDS = ("semantic_score", "character_score", "composition_score", "continuity_score")

# Phase 10 v1 aggregate formula — deliberately simple, documented rather
# than tuned; Phase 11 may replace this without touching the contract.
AGGREGATE_WEIGHTS = {
    "semantic_score": 0.50,
    "character_score": 0.25,
    "composition_score": 0.15,
    "continuity_score": 0.10,
}

_MAX_REASONS = 5
_MAX_REASON_CHARS = 200


class JudgeError(RuntimeError):
    """Base class for all VisualJudge failures."""


class JudgeInfrastructureError(JudgeError):
    """Transport/provider failure — timeout, unavailable, malformed response
    that survived one repair attempt. Governed by
    `visual_judge.hard_fail_on_judge_error` (see `visual_assets.py`)."""


class JudgeMalformedResponseError(JudgeError):
    """Raw judge response failed strict schema validation. Caught internally
    by `evaluate_via_transport` to drive exactly one repair attempt."""


@dataclass(frozen=True)
class JudgeCandidate:
    """Bounded, provider-neutral description of one technically-valid
    candidate — never a raw AssetRecord dict, never ComfyUI/cache internals."""
    asset_id: str
    local_path: str
    content_sha256: str
    candidate_index: int


@dataclass(frozen=True)
class JudgeContext:
    """Bounded planning context — never a full project/repo dump."""
    scene_id: str
    shot_id: str
    video_slug: str


@dataclass(frozen=True)
class CandidateEvaluation:
    asset_id: str
    semantic_score: float
    character_score: float
    composition_score: float
    continuity_score: float
    hard_failures: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def aggregate_score(self) -> float:
        return sum(getattr(self, name) * weight for name, weight in AGGREGATE_WEIGHTS.items())

    def is_hard_failed(self) -> bool:
        return bool(self.hard_failures)


@dataclass(frozen=True)
class JudgeResult:
    evaluations: tuple[CandidateEvaluation, ...]
    judge_provider: str
    judge_model: str
    judge_contract_version: str = CONTRACT_VERSION


class VisualJudge(Protocol):
    """The provider-neutral port. A real adapter implements this directly;
    `evaluate_via_transport` is a reusable helper for adapters that speak
    through a raw text-in/text-out transport with repair semantics."""

    def evaluate(
        self, request: Any, candidates: tuple[JudgeCandidate, ...], context: JudgeContext,
    ) -> JudgeResult: ...


def parse_judge_payload(
    raw: Any, *, candidate_asset_ids: tuple[str, ...], judge_provider: str, judge_model: str,
) -> JudgeResult:
    """Strict structured-output validation — no free-form prose as source
    of truth. Raises `JudgeMalformedResponseError` on any deviation."""
    if not isinstance(raw, dict):
        raise JudgeMalformedResponseError("Judge response phải là object JSON.")
    allowed_top_level = {"evaluations"}
    unknown_top_level = set(raw.keys()) - allowed_top_level
    if unknown_top_level:
        raise JudgeMalformedResponseError(f"Judge response có field lạ: {sorted(unknown_top_level)}")
    raw_evaluations = raw.get("evaluations")
    if not isinstance(raw_evaluations, list) or not raw_evaluations:
        raise JudgeMalformedResponseError("Judge response thiếu 'evaluations' hợp lệ (non-empty list).")

    allowed_fields = {"asset_id", *_SCORE_FIELDS, "hard_failures", "reasons"}
    seen: set[str] = set()
    evaluations: list[CandidateEvaluation] = []
    for item in raw_evaluations:
        if not isinstance(item, dict):
            raise JudgeMalformedResponseError("Mỗi evaluation phải là object JSON.")
        unknown_fields = set(item.keys()) - allowed_fields
        if unknown_fields:
            raise JudgeMalformedResponseError(f"Evaluation có field lạ: {sorted(unknown_fields)}")
        asset_id = item.get("asset_id")
        if not isinstance(asset_id, str) or asset_id not in candidate_asset_ids:
            raise JudgeMalformedResponseError(f"Judge trả asset_id không thuộc candidate set: {asset_id!r}")
        if asset_id in seen:
            raise JudgeMalformedResponseError(f"Judge trả trùng evaluation cho asset_id: {asset_id!r}")
        seen.add(asset_id)

        scores: dict[str, float] = {}
        for key in _SCORE_FIELDS:
            value = item.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
                raise JudgeMalformedResponseError(f"{key} phải là số trong [0.0, 1.0] cho asset_id {asset_id!r}.")
            scores[key] = float(value)

        hard_failures_raw = item.get("hard_failures", [])
        if not isinstance(hard_failures_raw, list) or not all(isinstance(code, str) for code in hard_failures_raw):
            raise JudgeMalformedResponseError(f"hard_failures phải là array string cho asset_id {asset_id!r}.")
        unknown_codes = set(hard_failures_raw) - KNOWN_HARD_FAILURE_CODES
        if unknown_codes:
            raise JudgeMalformedResponseError(f"hard_failures chứa mã không hợp lệ: {sorted(unknown_codes)}")

        reasons_raw = item.get("reasons", [])
        if not isinstance(reasons_raw, list) or not all(isinstance(reason, str) for reason in reasons_raw):
            raise JudgeMalformedResponseError(f"reasons phải là array string cho asset_id {asset_id!r}.")
        bounded_reasons = tuple(reason[:_MAX_REASON_CHARS] for reason in reasons_raw[:_MAX_REASONS])

        evaluations.append(CandidateEvaluation(
            asset_id=asset_id, hard_failures=tuple(hard_failures_raw), reasons=bounded_reasons, **scores,
        ))

    missing = set(candidate_asset_ids) - seen
    if missing:
        raise JudgeMalformedResponseError(f"Judge thiếu evaluation cho candidate: {sorted(missing)}")

    return JudgeResult(evaluations=tuple(evaluations), judge_provider=judge_provider, judge_model=judge_model)


class JudgeTransport(Protocol):
    """Raw text-in/text-out transport a future adapter implements. No
    image-attachment shape is prescribed here — see module docstring for
    why no adapter is wired against this yet."""

    def request(self, *, system: str, user: str) -> str: ...


_JUDGE_SYSTEM_PROMPT = (
    "Bạn là bộ đánh giá kỹ thuật/ngữ nghĩa cho ảnh do pipeline sản xuất video "
    "sinh ra. CHỈ đánh giá mức độ khớp với yêu cầu và bố cục/kỹ thuật — "
    "KHÔNG đánh giá vẻ đẹp, sức hấp dẫn, tuổi tác, giới tính hay chủng tộc. "
    "Trả lời DUY NHẤT một object JSON hợp lệ đúng schema — không giải thích, "
    "không markdown, không code fence."
)


def _build_judge_prompt(request: Any, candidates: tuple[JudgeCandidate, ...], context: JudgeContext) -> str:
    lines = [
        f"visual_intent: {request.visual_intent.strip()}",
        f"characters: {', '.join(request.characters) or '(không có)'}",
        f"semantic_constraints: {', '.join(getattr(request, 'semantic_constraints', ())) or '(không có)'}",
        f"scene_id: {context.scene_id}",
        f"shot_id: {context.shot_id}",
        "candidates:",
    ]
    for candidate in candidates:
        lines.append(f"  - asset_id={candidate.asset_id} candidate_index={candidate.candidate_index} path={candidate.local_path}")
    lines.append(
        'Trả JSON: {"evaluations": [{"asset_id": str, "semantic_score": 0..1, '
        '"character_score": 0..1, "composition_score": 0..1, "continuity_score": 0..1, '
        '"hard_failures": [str,...], "reasons": [str,...]}, ...]} — đúng MỘT phần tử cho '
        "MỖI candidate ở trên, không thêm/bớt."
    )
    return "\n".join(lines)


def evaluate_via_transport(
    transport: JudgeTransport, request: Any, candidates: tuple[JudgeCandidate, ...], context: JudgeContext,
    *, judge_provider: str, judge_model: str,
) -> JudgeResult:
    """Generic single-call-per-shot orchestration with exactly one repair
    round-trip. Comparative ranking across all technically-valid candidates
    happens in ONE call when the transport supports it (see module
    docstring — set-level, not per-candidate, evaluation)."""
    candidate_ids = tuple(candidate.asset_id for candidate in candidates)
    prompt = _build_judge_prompt(request, candidates, context)

    def _attempt(user_prompt: str) -> JudgeResult:
        raw_text = transport.request(system=_JUDGE_SYSTEM_PROMPT, user=user_prompt)
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise JudgeMalformedResponseError(f"Judge response không phải JSON hợp lệ: {exc}") from exc
        return parse_judge_payload(payload, candidate_asset_ids=candidate_ids, judge_provider=judge_provider, judge_model=judge_model)

    try:
        return _attempt(prompt)
    except JudgeMalformedResponseError as first_error:
        logger.info("visual_judge.repair shot_id=%s reason=%s", context.shot_id, first_error)
        repair_prompt = (
            f"{prompt}\n\nPhản hồi trước không hợp lệ ({first_error}). "
            "Trả lại DUY NHẤT JSON hợp lệ đúng schema, không thêm gì khác."
        )
        try:
            return _attempt(repair_prompt)
        except JudgeMalformedResponseError as second_error:
            raise JudgeInfrastructureError(
                f"Judge response không hợp lệ sau 1 lần repair: {second_error}"
            ) from second_error


def rank_eligible(
    evaluations: tuple[CandidateEvaluation, ...], candidate_index_by_asset: dict[str, int], *, minimum_score: float,
) -> list[CandidateEvaluation]:
    """Deterministic ranking: hard-failed and below-threshold candidates are
    ineligible; ties break on lowest `candidate_index`."""
    eligible = [
        evaluation for evaluation in evaluations
        if not evaluation.is_hard_failed() and evaluation.aggregate_score() >= minimum_score
    ]
    eligible.sort(key=lambda evaluation: (-evaluation.aggregate_score(), candidate_index_by_asset[evaluation.asset_id]))
    return eligible


def select_vlm_ranked(
    result: JudgeResult, candidate_index_by_asset: dict[str, int], *, minimum_score: float,
) -> str | None:
    """`None` means every evaluated candidate was hard-failed or below
    threshold — the caller must fail closed, never fall back to
    `first_valid` (semantic rejection is not an infrastructure failure)."""
    eligible = rank_eligible(result.evaluations, candidate_index_by_asset, minimum_score=minimum_score)
    return eligible[0].asset_id if eligible else None
