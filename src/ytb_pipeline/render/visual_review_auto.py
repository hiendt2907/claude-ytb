"""Policy-gated automatic settlement of durable visual reviews."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config.settings import settings
from .asset_registry import AssetRegistry, content_sha256 as observed_content_sha256
from .visual_disposition import AutoDispositionPolicy, choose_auto_accept
from .visual_judge import CONTRACT_VERSION as JUDGE_CONTRACT_VERSION

if TYPE_CHECKING:
    from .visual_evaluation_store import VisualEvaluationStore
    from .visual_review import VisualReviewStore


logger = logging.getLogger(__name__)


def resolve_judge_target(judge_cfg: Any) -> tuple[str, str]:
    """Return the explicit operator override, or the profile judge target."""
    provider = (settings.visual_judge_provider or "").strip() or judge_cfg.provider
    model = (settings.visual_judge_model or "").strip() or judge_cfg.model
    if model != judge_cfg.model or provider != judge_cfg.provider:
        logger.warning(
            "visual_judge.operator_override profile=%s/%s -> %s/%s",
            judge_cfg.provider, judge_cfg.model, provider, model,
        )
    return provider, model


def resolve_auto_disposition(judge_cfg: Any) -> AutoDispositionPolicy:
    """Return the profile policy, applying only an explicit operator override."""
    from .visual_disposition import DispositionError

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
    logger.warning(
        "visual_judge.disposition_override profile=%s -> %s waived=%s min=%.2f",
        declared.mode, override.mode, ",".join(sorted(codes)) or "-",
        override.minimum_score,
    )
    return override


def try_auto_accept(
    entry: Any,
    request: Any,
    *,
    judge_cfg: Any,
    review_store: "VisualReviewStore | None",
    evaluation_store: "VisualEvaluationStore | None",
    registry: AssetRegistry,
) -> str | None:
    """Settle exactly one pending review, or return ``None`` without bypassing it.

    Policy permission alone is deliberately insufficient.  The method returns
    an asset only after it has resolved the durable entry using current,
    content-verified Judge evidence.
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
            judge_contract_version=JUDGE_CONTRACT_VERSION,
        )
        or not evaluated.matches_candidate_identity(candidate_identity)
        or set(evaluated.evaluations) != set(candidate_identity)
    ):
        return None
    evaluations = tuple(evaluated.evaluations[asset_id] for asset_id in entry.candidate_asset_ids)
    index = {asset_id: position for position, asset_id in enumerate(entry.candidate_asset_ids)}
    chosen = choose_auto_accept(evaluations, policy=policy, candidate_index_by_asset=index)
    if not isinstance(chosen, str) or not chosen:
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
    logger.warning(
        "visual_review.auto_accepted shot_id=%s review_id=%s asset_id=%s waived=%s",
        request.shot_id, entry.review_id, chosen, ",".join(waived) or "-",
    )
    return chosen
