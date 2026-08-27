"""Durable, project-specific semantic-evaluation persistence (Phase 10).

    assets/projects/<slug>/visual_evaluations.json

Deliberately a SEPARATE file from `AssetRegistry` (global, immutable
concrete-media provenance — "what was generated") and from
`visual_candidates.json` (per-project generation/selection checkpoint —
"which slots exist, which one won"). This file answers a third, distinct
question: "how did THIS project, under THIS judge policy, score THIS exact
set of candidate bytes for THIS exact request?" — a fact that is
contextual (the same `AssetRecord` may legitimately score differently for
a different `VisualRequest`, project, or judge policy) and therefore must
never be written into `AssetRegistry`'s immutable provenance.

Evaluation identity (`ShotEvaluationSet.matches_context`/
`matches_candidate_identity`) is the conjunction of:

    request_fingerprint     the exact semantic VisualRequest evaluated
    candidate_identity      {asset_id: content_sha256} for every candidate
                            actually evaluated — a changed/added/removed
                            candidate invalidates reuse
    judge_provider/model    which concrete judge produced this score
    judge_policy_version    the profile's own semantic policy version
    judge_contract_version  this module's own JudgeResult schema version

All five must match for a persisted evaluation to be reused without a new
judge call — Phase 10's own version of the same "exact observation"
discipline `AssetRegistry` already applies to media identity.

This module chooses SET-LEVEL (whole-shot, comparative) evaluation, not
per-candidate: `render/visual_judge.py`'s `evaluate_via_transport` sends
every technically-valid candidate for one Shot in a single call so a real
adapter can rank them comparatively. Consequently there is no per-candidate
partial-evaluation resume within one shot — either the whole shot's
evaluation set is valid and reused, or the whole shot is (re)judged in one
call. Candidate GENERATION checkpointing (`visual_candidates.py`) remains
fully per-slot and is completely unaffected by this choice.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .visual_judge import CandidateEvaluation


@dataclass
class ShotEvaluationSet:
    shot_id: str
    request_fingerprint: str
    judge_provider: str
    judge_model: str
    judge_policy_version: str
    judge_contract_version: str
    # asset_id -> content_sha256 observed AT EVALUATION TIME for every
    # candidate this evaluation set actually covers.
    candidate_identity: dict[str, str] = field(default_factory=dict)
    evaluations: dict[str, CandidateEvaluation] = field(default_factory=dict)
    fallback_used: bool = False
    judge_error: str | None = None

    def matches_context(
        self, *, request_fingerprint: str, judge_provider: str, judge_model: str,
        judge_policy_version: str, judge_contract_version: str,
    ) -> bool:
        return (
            self.request_fingerprint == request_fingerprint
            and self.judge_provider == judge_provider
            and self.judge_model == judge_model
            and self.judge_policy_version == judge_policy_version
            and self.judge_contract_version == judge_contract_version
        )

    def matches_candidate_identity(self, candidate_identity: dict[str, str]) -> bool:
        return self.candidate_identity == candidate_identity

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "request_fingerprint": self.request_fingerprint,
            "judge_provider": self.judge_provider,
            "judge_model": self.judge_model,
            "judge_policy_version": self.judge_policy_version,
            "judge_contract_version": self.judge_contract_version,
            "candidate_identity": dict(self.candidate_identity),
            "evaluations": {asset_id: asdict(evaluation) for asset_id, evaluation in self.evaluations.items()},
            "fallback_used": self.fallback_used,
            "judge_error": self.judge_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShotEvaluationSet":
        return cls(
            data["shot_id"], data["request_fingerprint"], data["judge_provider"], data["judge_model"],
            data["judge_policy_version"], data["judge_contract_version"],
            dict(data.get("candidate_identity", {})),
            {
                asset_id: CandidateEvaluation(
                    asset_id=payload["asset_id"], semantic_score=payload["semantic_score"],
                    character_score=payload["character_score"], composition_score=payload["composition_score"],
                    continuity_score=payload["continuity_score"], hard_failures=tuple(payload.get("hard_failures", ())),
                    reasons=tuple(payload.get("reasons", ())),
                )
                for asset_id, payload in data.get("evaluations", {}).items()
            },
            data.get("fallback_used", False), data.get("judge_error"),
        )


class VisualEvaluationStore:
    """One JSON file per project — mirrors `VisualCandidateStore`'s own
    read-fully-at-construction, atomic-write-on-`write()` pattern."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._shots: dict[str, ShotEvaluationSet] = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._shots = {key: ShotEvaluationSet.from_dict(value) for key, value in data.get("shots", {}).items()}

    def get(self, shot_id: str) -> ShotEvaluationSet | None:
        return self._shots.get(shot_id)

    def save(self, evaluation_set: ShotEvaluationSet) -> None:
        self._shots[evaluation_set.shot_id] = evaluation_set

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"shots": {key: value.to_dict() for key, value in self._shots.items()}}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
