"""Durable Phase-13 operator review and manual visual-override contracts.

This module owns project-local human disposition state.  It deliberately does
not own AssetRegistry provenance, semantic evaluations, VisualManifest, or
rendering.  Reads do not create ``visual_review.json``; mutations use the
repository's process-safe sidecar lock plus atomic replacement.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from ..orchestrator.state_io import file_lock, locked_json_update
from .visual_candidates import candidate_seed

if TYPE_CHECKING:
    from .visual_assets import VisualRequest


REVIEW_CONTRACT_VERSION = "phase13-review-v1"
MANUAL_OVERRIDE_CONTRACT_VERSION = "phase13-manual-override-v1"
MAX_MANUAL_INSTRUCTION_CHARS = 1000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stable_fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class VisualPreparationState(str, Enum):
    SUCCESS = "success"
    REVIEW_REQUIRED = "review_required"
    ABANDONED = "abandoned"
    INFRASTRUCTURE_FAILED = "infrastructure_failed"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"
    STALE = "stale"


class ReviewReason(str, Enum):
    SEMANTIC_FAIL_CLOSED = "semantic_fail_closed"
    SEMANTIC_RECOVERY_EXHAUSTED = "semantic_recovery_exhausted"
    MANUAL_SEMANTIC_REJECTION = "manual_semantic_rejection"
    ACCEPTED_ASSET_INVALID = "accepted_asset_invalid"


class ReviewDisposition(str, Enum):
    ACCEPT_EXISTING = "accept_existing"
    MANUAL_REGENERATE = "manual_regenerate"
    ABANDON = "abandon"


class VisualReviewError(ValueError):
    """Review contract or state-transition violation."""


class ReviewRequiredError(VisualReviewError):
    """Domain halt: automation stopped and an operator must decide."""

    state = VisualPreparationState.REVIEW_REQUIRED
    workflow_node_status = "review_required"
    project_status = "review_required"

    def __init__(self, entry: "VisualReviewEntry") -> None:
        self.entry = entry
        super().__init__(
            "REVIEW_REQUIRED: "
            f"shot={entry.shot_id} reason={entry.review_reason.value} "
            f"review_id={entry.review_id}"
        )


class VisualAbandonedError(VisualReviewError):
    """Domain halt: an operator intentionally abandoned the Shot."""

    state = VisualPreparationState.ABANDONED
    workflow_node_status = "abandoned"
    project_status = "abandoned"

    def __init__(self, entry: "VisualReviewEntry") -> None:
        self.entry = entry
        super().__init__(
            f"ABANDONED: shot={entry.shot_id} review_id={entry.review_id}"
        )


@dataclass(frozen=True)
class ManualCandidateSlot:
    candidate_slot_id: str
    candidate_index: int
    seed: int
    status: str = "pending"  # pending | running | done | failed
    asset_id: str | None = None
    attempt_count: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class ManualVisualOverride:
    override_id: str
    shot_id: str
    base_request_fingerprint: str
    instruction: str
    override_fingerprint: str
    derived_request_id: str
    derived_request_fingerprint: str
    status: str = "pending"  # pending | running | resolved | rejected | stale
    candidate_count: int = 0
    generation_key: str = ""
    evaluation_store_key: str = ""
    candidates: tuple[ManualCandidateSlot, ...] = ()
    selected_asset_id: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["candidates"] = [asdict(slot) for slot in self.candidates]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ManualVisualOverride":
        payload = dict(data)
        payload["candidates"] = tuple(
            ManualCandidateSlot(**item) for item in payload.get("candidates", ())
        )
        return cls(**payload)


@dataclass(frozen=True)
class VisualReviewEntry:
    review_id: str
    shot_id: str
    request_id: str
    request_fingerprint: str
    visual_intent: str
    characters: tuple[str, ...]
    semantic_constraints: tuple[str, ...]
    status: ReviewStatus
    review_reason: ReviewReason
    candidate_asset_ids: tuple[str, ...]
    evaluation_fingerprint: str
    recovery_status: str
    disposition: ReviewDisposition | None = None
    selected_asset_id: str | None = None
    selection_mode: str = ""
    manual_override: ManualVisualOverride | None = None
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["review_reason"] = self.review_reason.value
        data["disposition"] = self.disposition.value if self.disposition else None
        data["characters"] = list(self.characters)
        data["semantic_constraints"] = list(self.semantic_constraints)
        data["candidate_asset_ids"] = list(self.candidate_asset_ids)
        data["manual_override"] = (
            self.manual_override.to_dict() if self.manual_override else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "VisualReviewEntry":
        payload = dict(data)
        payload["status"] = ReviewStatus(payload["status"])
        payload["review_reason"] = ReviewReason(payload["review_reason"])
        disposition = payload.get("disposition")
        payload["disposition"] = ReviewDisposition(disposition) if disposition else None
        payload["characters"] = tuple(payload.get("characters", ()))
        payload["semantic_constraints"] = tuple(
            payload.get("semantic_constraints", ())
        )
        payload["candidate_asset_ids"] = tuple(
            payload.get("candidate_asset_ids", ())
        )
        manual = payload.get("manual_override")
        payload["manual_override"] = (
            ManualVisualOverride.from_dict(manual) if manual else None
        )
        return cls(**payload)


def _validate_instruction(instruction: str) -> str:
    normalized = instruction.strip()
    if not normalized:
        raise VisualReviewError("Manual override instruction không được rỗng.")
    if len(normalized) > MAX_MANUAL_INSTRUCTION_CHARS:
        raise VisualReviewError(
            "Manual override instruction không được vượt quá "
            f"{MAX_MANUAL_INSTRUCTION_CHARS} ký tự."
        )
    return normalized


def derive_manual_override(
    request: "VisualRequest", instruction: str
) -> ManualVisualOverride:
    """Build a deterministic human-authored lineage without mutating request."""
    normalized = _validate_instruction(instruction)
    override_fingerprint = _stable_fingerprint(
        MANUAL_OVERRIDE_CONTRACT_VERSION,
        request.request_fingerprint,
        request.shot_id,
        normalized,
    )
    derived_fingerprint = _stable_fingerprint(
        MANUAL_OVERRIDE_CONTRACT_VERSION,
        "derived-request",
        request.request_fingerprint,
        override_fingerprint,
    )
    return ManualVisualOverride(
        override_id=f"mvo_{override_fingerprint[:24]}",
        shot_id=request.shot_id,
        base_request_fingerprint=request.request_fingerprint,
        instruction=normalized,
        override_fingerprint=override_fingerprint,
        derived_request_id=f"mvr_{derived_fingerprint[:24]}",
        derived_request_fingerprint=derived_fingerprint,
        evaluation_store_key=(
            f"{request.shot_id}::manual::mvo_{override_fingerprint[:24]}"
        ),
    )


def derive_manual_visual_request(
    request: "VisualRequest", override: ManualVisualOverride
) -> "VisualRequest":
    if override.base_request_fingerprint != request.request_fingerprint:
        raise VisualReviewError("Manual override stale: base request đã thay đổi.")
    from .visual_assets import VisualRequest

    return VisualRequest(
        request_id=override.derived_request_id,
        request_fingerprint=override.derived_request_fingerprint,
        scene_id=request.scene_id,
        shot_id=request.shot_id,
        visual_intent=(
            f"{request.visual_intent.strip()}\n"
            f"Operator instruction: {override.instruction}"
        ),
        characters=request.characters,
        dimensions=request.dimensions,
        resolution_kind=request.resolution_kind,
        semantic_constraints=request.semantic_constraints,
    )


def manual_generation_key(
    automated_generation_key: str, override: ManualVisualOverride
) -> str:
    return _stable_fingerprint(
        MANUAL_OVERRIDE_CONTRACT_VERSION,
        "manual-generation",
        automated_generation_key,
        override.override_fingerprint,
    )


def manual_candidate_seed(generation_key: str, candidate_index: int) -> int:
    return candidate_seed(generation_key, candidate_index, generation_round=0)


def manual_candidate_cache_path(
    cache_dir: Path, generation_key: str, candidate_index: int
) -> Path:
    return Path(cache_dir) / (
        f"{generation_key}.manual-candidate-{candidate_index:02d}.png"
    )


class VisualReviewStore:
    """Process-safe project-local ``visual_review.json`` store."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read_unlocked(self) -> dict[str, VisualReviewEntry]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        reviews = payload.get("reviews", {})
        if not isinstance(reviews, dict):
            raise VisualReviewError(f"Review store không hợp lệ: {self.path}")
        return {
            key: VisualReviewEntry.from_dict(value)
            for key, value in reviews.items()
        }

    def entries(self) -> tuple[VisualReviewEntry, ...]:
        with file_lock(self.path):
            values = self._read_unlocked().values()
            return tuple(sorted(values, key=lambda item: (item.created_at, item.review_id)))

    def get(self, review_id: str) -> VisualReviewEntry | None:
        with file_lock(self.path):
            return self._read_unlocked().get(review_id)

    def current_for_shot(self, shot_id: str) -> VisualReviewEntry | None:
        matches = [
            entry
            for entry in self.entries()
            if entry.shot_id == shot_id and entry.status != ReviewStatus.STALE
        ]
        return matches[-1] if matches else None

    @staticmethod
    def _write_entry(data: dict, entry: VisualReviewEntry) -> None:
        reviews = data.setdefault("reviews", {})
        if not isinstance(reviews, dict):
            raise VisualReviewError("Review store reviews phải là object.")
        reviews[entry.review_id] = entry.to_dict()

    def ensure_pending(
        self,
        request: "VisualRequest",
        *,
        reason: ReviewReason,
        candidate_asset_ids: tuple[str, ...],
        evaluation_fingerprint: str,
        recovery_status: str,
    ) -> VisualReviewEntry:
        review_fingerprint = _stable_fingerprint(
            REVIEW_CONTRACT_VERSION,
            request.shot_id,
            request.request_fingerprint,
            reason.value,
            evaluation_fingerprint,
        )
        review_id = f"vrw_{review_fingerprint[:24]}"
        now = _now_iso()
        with locked_json_update(self.path) as data:
            reviews = data.setdefault("reviews", {})
            if not isinstance(reviews, dict):
                raise VisualReviewError("Review store reviews phải là object.")
            existing_payload = reviews.get(review_id)
            if existing_payload is not None:
                existing = VisualReviewEntry.from_dict(existing_payload)
                if existing.status == ReviewStatus.STALE:
                    existing = replace(
                        existing,
                        status=ReviewStatus.PENDING,
                        disposition=None,
                        selected_asset_id=None,
                        selection_mode="",
                        manual_override=None,
                        last_error=None,
                        updated_at=now,
                    )
                candidate_ids = tuple(
                    dict.fromkeys((*existing.candidate_asset_ids, *candidate_asset_ids))
                )
                updated = replace(
                    existing,
                    candidate_asset_ids=candidate_ids,
                    evaluation_fingerprint=evaluation_fingerprint,
                    recovery_status=recovery_status,
                    updated_at=now,
                )
                reviews[review_id] = updated.to_dict()
                return updated

            for key, payload in tuple(reviews.items()):
                item = VisualReviewEntry.from_dict(payload)
                if item.shot_id == request.shot_id and item.status != ReviewStatus.STALE:
                    reviews[key] = replace(
                        item,
                        status=ReviewStatus.STALE,
                        updated_at=now,
                    ).to_dict()
            created = VisualReviewEntry(
                review_id=review_id,
                shot_id=request.shot_id,
                request_id=request.request_id,
                request_fingerprint=request.request_fingerprint,
                visual_intent=request.visual_intent,
                characters=request.characters,
                semantic_constraints=request.semantic_constraints,
                status=ReviewStatus.PENDING,
                review_reason=reason,
                candidate_asset_ids=tuple(dict.fromkeys(candidate_asset_ids)),
                evaluation_fingerprint=evaluation_fingerprint,
                recovery_status=recovery_status,
                created_at=now,
                updated_at=now,
            )
            reviews[review_id] = created.to_dict()
            return created

    def mark_stale_for_changed_request(
        self, shot_id: str, current_request_fingerprint: str
    ) -> tuple[VisualReviewEntry, ...]:
        if not self.path.is_file():
            return ()
        changed: list[VisualReviewEntry] = []
        now = _now_iso()
        with locked_json_update(self.path) as data:
            reviews = data.setdefault("reviews", {})
            for key, payload in tuple(reviews.items()):
                entry = VisualReviewEntry.from_dict(payload)
                if (
                    entry.shot_id == shot_id
                    and entry.status != ReviewStatus.STALE
                    and entry.request_fingerprint != current_request_fingerprint
                ):
                    entry = replace(
                        entry,
                        status=ReviewStatus.STALE,
                        updated_at=now,
                    )
                    reviews[key] = entry.to_dict()
                    changed.append(entry)
        return tuple(changed)

    def _transition(
        self,
        review_id: str,
        *,
        request_fingerprint: str,
        update: Callable[[VisualReviewEntry], VisualReviewEntry],
    ) -> VisualReviewEntry:
        with locked_json_update(self.path) as data:
            reviews = data.setdefault("reviews", {})
            payload = reviews.get(review_id)
            if payload is None:
                raise VisualReviewError(f"Không tìm thấy review {review_id!r}.")
            entry = VisualReviewEntry.from_dict(payload)
            if entry.request_fingerprint != request_fingerprint:
                raise VisualReviewError("Review stale: request fingerprint không còn khớp.")
            if entry.status == ReviewStatus.STALE:
                raise VisualReviewError("Review stale; cần operator disposition mới.")
            if entry.status != ReviewStatus.PENDING:
                raise VisualReviewError(
                    f"Review đã có trạng thái kết thúc: {entry.status.value}."
                )
            updated = replace(update(entry), updated_at=_now_iso())
            reviews[review_id] = updated.to_dict()
            return updated

    def resolve_accept_existing(
        self, review_id: str, *, request_fingerprint: str, asset_id: str
    ) -> VisualReviewEntry:
        def update(entry: VisualReviewEntry) -> VisualReviewEntry:
            if asset_id not in entry.candidate_asset_ids:
                raise VisualReviewError(
                    f"Asset {asset_id!r} không thuộc candidate history của Shot."
                )
            return replace(
                entry,
                status=ReviewStatus.RESOLVED,
                disposition=ReviewDisposition.ACCEPT_EXISTING,
                selected_asset_id=asset_id,
                selection_mode="operator_override",
                last_error=None,
            )

        return self._transition(
            review_id,
            request_fingerprint=request_fingerprint,
            update=update,
        )

    def submit_manual_regenerate(
        self,
        review_id: str,
        *,
        request: "VisualRequest",
        instruction: str,
    ) -> VisualReviewEntry:
        override = derive_manual_override(request, instruction)

        def update(entry: VisualReviewEntry) -> VisualReviewEntry:
            if entry.shot_id != request.shot_id:
                raise VisualReviewError("Review không thuộc Shot được yêu cầu.")
            if entry.manual_override is not None:
                raise VisualReviewError(
                    "Manual regeneration budget đã được sử dụng cho review này."
                )
            return replace(
                entry,
                disposition=ReviewDisposition.MANUAL_REGENERATE,
                manual_override=override,
                last_error=None,
            )

        return self._transition(
            review_id,
            request_fingerprint=request.request_fingerprint,
            update=update,
        )

    def abandon(
        self, review_id: str, *, request_fingerprint: str
    ) -> VisualReviewEntry:
        return self._transition(
            review_id,
            request_fingerprint=request_fingerprint,
            update=lambda entry: replace(
                entry,
                status=ReviewStatus.ABANDONED,
                disposition=ReviewDisposition.ABANDON,
                selected_asset_id=None,
                selection_mode="operator_abandon",
                last_error=None,
            ),
        )

    def update_pending(
        self,
        review_id: str,
        *,
        request_fingerprint: str,
        update: Callable[[VisualReviewEntry], VisualReviewEntry],
    ) -> VisualReviewEntry:
        """Process-safe pipeline update for one still-pending review."""
        return self._transition(
            review_id,
            request_fingerprint=request_fingerprint,
            update=update,
        )
