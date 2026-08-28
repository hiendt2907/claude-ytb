"""Durable multi-candidate visual generation and deterministic selection
(Phase 9), opt-in per profile via ``visual_generation.candidate_count``.

    VisualRequest
        |
    (Phase 8 parent reuse / profile_local handled entirely outside this
     module — see `visual_assets.py`)
        |
    generated_image, candidate_count > 1
        v
    VisualCandidateSet (persisted per project)
        |
    candidate slot 0..N-1  ->  AssetRegistry record each (Phase 3.x)
        |
    deterministic Selector (`selection_policy`)
        v
    selected AssetRecord

``candidate_count == 1`` (the default) never touches this module: the
single-candidate path in `VisualAssetResolver.resolve` is the unchanged
Phase 8 code, byte-for-byte, including the historical `f"{key}.png"` cache
filename and `int(key[:16], 16) % (2**32)` seed formula. Candidate slot 0
here reuses exactly that formula (see `candidate_seed`/`candidate_cache_
path` below) so any profile that later turns candidate_count up finds its
existing single-candidate cache/AssetRecord already occupying slot 0 —
no regeneration, no new record.

Identity model, kept independent of `AssetRegistry`'s own locked concepts
(`asset_id` / `content_sha256` / `generation_key` / `local_path` — see
`asset_registry.py`, unchanged by this module):

    candidate_slot_id   `f"{shot_id}::candidate-{index:02d}"` — a LOCATOR
                         into one project's candidate set, not a media
                         identity.
    candidate_index     0-based ordinal slot position within one
                         VisualCandidateSet. Never used as a substitute for
                         `asset_id`.
    candidate_seed      stable hash derivation of
                         (generation_key, candidate_index) — deterministic,
                         reproducible, independent of runtime ordering.
                         Never `random`/timestamp/PID/`hash()`.

Persistence is project-specific (`VisualCandidateStore`, one JSON file per
project — conventionally `assets/projects/<slug>/visual_candidates.json`),
deliberately separate from:

    AssetRegistry     global concrete media/provenance (every candidate,
                       selected or not, gets its own permanent record).
    VisualManifest     final Shot -> selected asset_id resolution only.
    generation cache   physical reusable generation output files.

Technical validation here is strictly non-semantic: decodable image,
non-zero dimensions. No aesthetic/person/quality scoring — real semantic
judging is explicitly deferred to Phase 10 (see `docs/handoffs/2026-08-27-
visual-candidates-phase9-handoff.md`).

Selection (`selection_policy="first_valid"`, the only Phase 9 policy) is
deterministic: the lowest-index technically-valid candidate wins. It never
mutates `AssetRegistry` provenance and never deletes an unselected-but-
valid candidate's record — those remain legitimate registered assets.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .asset_registry import AssetRegistry, content_sha256 as observed_content_sha256

logger = logging.getLogger(__name__)

RECOVERY_POLICY_VERSION = "phase12-v1"
MAX_GENERATION_ROUND = 1
MAX_CANDIDATE_SLOTS_PER_ROUND = 4


def candidate_seed(
    generation_key: str,
    candidate_index: int,
    generation_round: int = 0,
) -> int:
    """Stable per-slot seed. Index 0 == the pre-Phase-9 single-candidate
    formula exactly, so existing cache/AssetRecords stay valid as slot 0."""
    if generation_round not in {0, 1}:
        raise ValueError("generation_round phải là 0 hoặc 1.")
    if generation_round == 0 and candidate_index == 0:
        return int(generation_key[:16], 16) % (2**32)
    if generation_round == 0:
        payload = f"{generation_key}\x1fcandidate\x1f{candidate_index}"
    else:
        payload = (
            f"{generation_key}\x1fgeneration-round\x1f{generation_round}"
            f"\x1fcandidate\x1f{candidate_index}"
        )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    seed = int(digest[:16], 16) % (2**32)
    if generation_round == 0:
        return seed

    # A 32-bit digest collision is unlikely but the Phase-12 identity
    # contract is categorical. Deterministic linear probing guarantees that
    # every round-1 slot differs from all four allowed round-0 slots and all
    # earlier round-1 slots, without changing a single Phase-9 seed.
    used = {
        candidate_seed(generation_key, index, generation_round=0)
        for index in range(MAX_CANDIDATE_SLOTS_PER_ROUND)
    }
    used.update(
        candidate_seed(generation_key, index, generation_round=1)
        for index in range(candidate_index)
    )
    while seed in used:
        seed = (seed + 1) % (2**32)
    return seed


def candidate_cache_path(
    cache_dir: Path,
    generation_key: str,
    candidate_index: int,
    generation_round: int = 0,
) -> Path:
    """Slot 0 keeps the historical `{generation_key}.png` filename so an
    existing single-candidate project's cache is found unchanged. Later
    slots get a distinct suffix so they can never overwrite one another
    or slot 0."""
    if generation_round not in {0, 1}:
        raise ValueError("generation_round phải là 0 hoặc 1.")
    if generation_round == 0 and candidate_index == 0:
        return Path(cache_dir) / f"{generation_key}.png"
    if generation_round == 0:
        return Path(cache_dir) / f"{generation_key}.candidate-{candidate_index:02d}.png"
    return Path(cache_dir) / (
        f"{generation_key}.round-{generation_round:02d}.candidate-{candidate_index:02d}.png"
    )


def validate_candidate_image(path: Path) -> bool:
    """Deterministic TECHNICAL validation only: decodable, non-zero
    dimensions, non-empty file. No aesthetic/semantic/person scoring —
    that is explicitly out of scope for Phase 9 (Phase 10)."""
    try:
        target = Path(path)
        if not target.is_file() or target.stat().st_size == 0:
            return False
        from PIL import Image
        with Image.open(target) as image:
            image.verify()
        with Image.open(target) as image:
            width, height = image.size
        return width > 0 and height > 0
    except Exception:
        return False


@dataclass
class CandidateSlot:
    candidate_slot_id: str
    candidate_index: int
    seed: int
    status: str = "pending"  # pending | done | failed
    asset_id: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
    # Missing in Phase-9/10/11 JSON means round 0. Appended at the end so
    # existing positional construction remains compatible.
    generation_round: int = 0


@dataclass
class VisualCandidateSet:
    shot_id: str
    request_id: str
    request_fingerprint: str
    generation_key: str
    candidate_policy_version: str
    target_candidate_count: int
    candidates: dict[str, CandidateSlot] = field(default_factory=dict)
    selected_asset_id: str | None = None
    selection_status: str = "pending"  # pending | selected | failed
    # Phase 10 selection checkpoint. `selector_fingerprint` is intentionally
    # independent from candidate generation identity: a policy/model/
    # threshold change invalidates the selected resolution while preserving
    # all valid slots and AssetRecords. `selection_mode` records an explicit
    # infrastructure fallback; fallback selections are retried on resume.
    selection_policy: str = ""
    selection_mode: str = "policy"  # policy | fallback_first_valid
    selector_fingerprint: str = ""
    # Phase 12 recovery checkpoint. Full scores remain solely in
    # visual_evaluations.json; this state records only bounded control-flow
    # facts and the exact rejected evaluation identity.
    recovery_policy: str = "fail_closed"
    recovery_policy_version: str = RECOVERY_POLICY_VERSION
    recovery_status: str = "not_needed"  # not_needed | eligible | running | resolved | exhausted
    active_generation_round: int = 0
    semantic_rejection_rounds: list[int] = field(default_factory=list)
    rejected_evaluation_fingerprint: str = ""

    def slot(self, candidate_index: int, generation_round: int = 0) -> CandidateSlot:
        if generation_round not in {0, 1}:
            raise ValueError("generation_round phải là 0 hoặc 1.")
        slot_id = (
            f"{self.shot_id}::candidate-{candidate_index:02d}"
            if generation_round == 0
            else f"{self.shot_id}::round-{generation_round:02d}::candidate-{candidate_index:02d}"
        )
        existing = self.candidates.get(slot_id)
        if existing is not None:
            return existing
        created = CandidateSlot(
            slot_id,
            candidate_index,
            candidate_seed(self.generation_key, candidate_index, generation_round),
            generation_round=generation_round,
        )
        self.candidates[slot_id] = created
        return created

    def existing_rounds(self) -> tuple[int, ...]:
        rounds = {slot.generation_round for slot in self.candidates.values()}
        return tuple(sorted(rounds or {0}))

    def existing_slots_for_round(self, generation_round: int) -> tuple[CandidateSlot, ...]:
        return tuple(
            sorted(
                (
                    slot
                    for slot in self.candidates.values()
                    if slot.generation_round == generation_round
                    and slot.candidate_index < self.target_candidate_count
                ),
                key=lambda slot: slot.candidate_index,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "request_id": self.request_id,
            "request_fingerprint": self.request_fingerprint,
            "generation_key": self.generation_key,
            "candidate_policy_version": self.candidate_policy_version,
            "target_candidate_count": self.target_candidate_count,
            "candidates": {key: asdict(value) for key, value in self.candidates.items()},
            "selected_asset_id": self.selected_asset_id,
            "selection_status": self.selection_status,
            "selection_policy": self.selection_policy,
            "selection_mode": self.selection_mode,
            "selector_fingerprint": self.selector_fingerprint,
            "recovery_policy": self.recovery_policy,
            "recovery_policy_version": self.recovery_policy_version,
            "recovery_status": self.recovery_status,
            "active_generation_round": self.active_generation_round,
            "semantic_rejection_rounds": list(self.semantic_rejection_rounds),
            "rejected_evaluation_fingerprint": self.rejected_evaluation_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VisualCandidateSet":
        return cls(
            data["shot_id"], data["request_id"], data["request_fingerprint"], data["generation_key"],
            data["candidate_policy_version"], data["target_candidate_count"],
            {key: CandidateSlot(**value) for key, value in data.get("candidates", {}).items()},
            data.get("selected_asset_id"), data.get("selection_status", "pending"),
            data.get("selection_policy", ""), data.get("selection_mode", "policy"),
            data.get("selector_fingerprint", ""),
            data.get("recovery_policy", "fail_closed"),
            data.get("recovery_policy_version", RECOVERY_POLICY_VERSION),
            data.get("recovery_status", "not_needed"),
            data.get("active_generation_round", 0),
            list(data.get("semantic_rejection_rounds", [])),
            data.get("rejected_evaluation_fingerprint", ""),
        )


class VisualCandidateStore:
    """Project-specific persisted candidate-generation/selection state.

    Deliberately NOT `AssetRegistry` (global provenance) and NOT
    `VisualManifest` (final Shot -> selected asset). One JSON file per
    project, read fully at construction and written atomically on
    `write()` — matching every other project-scoped artifact in this
    package (`VisualManifest`, `ScenePlan`, `DerivativeLineage`).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._sets: dict[str, VisualCandidateSet] = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._sets = {key: VisualCandidateSet.from_dict(value) for key, value in data.get("shots", {}).items()}

    def get_or_create(
        self, *, shot_id: str, request_id: str, request_fingerprint: str,
        generation_key: str, candidate_policy_version: str, target_candidate_count: int,
    ) -> VisualCandidateSet:
        existing = self._sets.get(shot_id)
        if existing is not None and existing.request_fingerprint == request_fingerprint:
            # A changed target count or selection-policy version does NOT
            # invalidate already-generated candidates (items 26/27) — only
            # a changed semantic request fingerprint does (item 25).
            existing.request_id = request_id
            existing.generation_key = generation_key
            existing.candidate_policy_version = candidate_policy_version
            existing.target_candidate_count = target_candidate_count
            return existing
        created = VisualCandidateSet(
            shot_id, request_id, request_fingerprint, generation_key,
            candidate_policy_version, target_candidate_count,
        )
        self._sets[shot_id] = created
        return created

    def get(self, shot_id: str) -> VisualCandidateSet | None:
        """Return persisted candidate state without creating or mutating it."""
        return self._sets.get(shot_id)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"shots": {key: value.to_dict() for key, value in self._sets.items()}}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def candidate_is_valid(slot: CandidateSlot, registry: AssetRegistry) -> bool:
    """A `done` slot is valid only when its AssetRecord still exists, its
    physical media still matches, and it still passes technical
    validation — otherwise a rerun must retry it, not trust stale state."""
    if slot.status != "done" or not slot.asset_id:
        return False
    record = registry.find_by_asset_id(slot.asset_id)
    if record is None:
        return False
    path = Path(record["local_path"])
    if not path.is_file() or observed_content_sha256(path) != record.get("content_sha256"):
        return False
    if record.get("seed") != slot.seed:
        return False
    return validate_candidate_image(path)


def select_first_valid(candidate_set: VisualCandidateSet, registry: AssetRegistry) -> str | None:
    """Phase 9's sole selection policy: deterministic lowest-index valid
    candidate. Simple by design — Phase 10 adds real semantic judging."""
    for index in range(candidate_set.target_candidate_count):
        slot = candidate_set.candidates.get(f"{candidate_set.shot_id}::candidate-{index:02d}")
        if slot is not None and candidate_is_valid(slot, registry):
            return slot.asset_id
    return None


_SELECTION_POLICIES: dict[str, Callable[[VisualCandidateSet, AssetRegistry], str | None]] = {
    "first_valid": select_first_valid,
}


def resolve_selection_policy(name: str) -> Callable[[VisualCandidateSet, AssetRegistry], str | None]:
    try:
        return _SELECTION_POLICIES[name]
    except KeyError as exc:
        raise ValueError(f"selection_policy không hợp lệ: {name!r}") from exc
