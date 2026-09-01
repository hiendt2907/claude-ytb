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
# Workflow cua chinh he thong la "Judge chi ra sai o dau, operator sua lai",
# nen mot lan thu la qua it: do tren hang that, lan sua dau tien cua operator
# da dat character=1.000 composition=0.900 continuity=1.000 va chi hong dung
# mot menh de hanh dong. Van phai HUU HAN de khong dot vo han luot sinh anh.
MAX_MANUAL_OVERRIDES_PER_REVIEW = 3


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
    # Mặc định instruction NỐI THÊM vào visual_intent, giữ ngữ cảnh cảnh. Nhưng
    # nối thêm thì chỉ thêm được ràng buộc, không rút được cái nào — và một
    # visual_intent đòi thứ image model không dựng nổi sẽ hard-fail vĩnh viễn dù
    # operator nói gì. Cờ này cho operator THAY luôn mệnh đề bất khả thi.
    replaces_intent: bool = False

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
    scene_id: str
    visual_intent: str
    characters: tuple[str, ...]
    dimensions: tuple[int, int]
    resolution_kind: str
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
    # Dem so override DA TIEU CONG, de bound tinh theo cong chu khong theo so
    # lan go lenh (xem `submit_manual_regenerate`).
    manual_override_spent: int = 0
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["review_reason"] = self.review_reason.value
        data["disposition"] = self.disposition.value if self.disposition else None
        data["characters"] = list(self.characters)
        data["dimensions"] = list(self.dimensions)
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
        payload["dimensions"] = tuple(payload.get("dimensions", ()))
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
    request: "VisualRequest", instruction: str, *, replaces_intent: bool = False
) -> ManualVisualOverride:
    """Build a deterministic human-authored lineage without mutating request."""
    normalized = _validate_instruction(instruction)
    override_fingerprint = _stable_fingerprint(
        MANUAL_OVERRIDE_CONTRACT_VERSION,
        request.request_fingerprint,
        request.shot_id,
        normalized,
        # Cùng instruction nhưng thay-thế và nối-thêm cho ra hai visual_intent
        # khác nhau, nên phải là hai lineage khác nhau.
        "replace" if replaces_intent else "append",
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
        replaces_intent=replaces_intent,
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
        # Nối thêm là mặc định: giữ ngữ cảnh cảnh, operator chỉ chỉnh thêm.
        # Khi `replaces_intent`, instruction THAY hẳn — đó là cách duy nhất rút
        # được một mệnh đề mà image model không dựng nổi. Judge chấm đúng văn
        # bản này, nên nối thêm một câu phủ định chỉ tạo ra mâu thuẫn
        # ("tay cầm khay gỗ" + "không cầm vật gì") và vẫn hard-fail.
        visual_intent=(
            override.instruction.strip()
            if override.replaces_intent
            else f"{request.visual_intent.strip()}\nOperator instruction: {override.instruction}"
        ),
        characters=request.characters,
        dimensions=request.dimensions,
        resolution_kind=request.resolution_kind,
        semantic_constraints=request.semantic_constraints,
    )


def request_from_review_entry(entry: VisualReviewEntry) -> "VisualRequest":
    """Rehydrate the bounded base request snapshot used by operator CLI."""
    from .visual_assets import VisualRequest

    return VisualRequest(
        request_id=entry.request_id,
        request_fingerprint=entry.request_fingerprint,
        scene_id=entry.scene_id,
        shot_id=entry.shot_id,
        visual_intent=entry.visual_intent,
        characters=entry.characters,
        dimensions=entry.dimensions,
        resolution_kind=entry.resolution_kind,
        semantic_constraints=entry.semantic_constraints,
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
                scene_id=request.scene_id,
                visual_intent=request.visual_intent,
                characters=request.characters,
                dimensions=request.dimensions,
                resolution_kind=request.resolution_kind,
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
        replaces_intent: bool = False,
    ) -> VisualReviewEntry:
        override = derive_manual_override(
            request, instruction, replaces_intent=replaces_intent,
        )

        def update(entry: VisualReviewEntry) -> VisualReviewEntry:
            if entry.shot_id != request.shot_id:
                raise VisualReviewError("Review không thuộc Shot được yêu cầu.")
            existing = entry.manual_override
            # Ngân sách tính theo CÔNG ĐÃ TIÊU, không theo số lần gõ lệnh. Một
            # override còn `pending` và chưa sinh candidate nào thì chưa tốn gì,
            # nên operator phải sửa được lệnh mình vừa gõ sai — trước đây gõ sai
            # là khoá review vĩnh viễn, mà không có CLI reset ở mức node và
            # `abandon` thì dừng hẳn pipeline chứ không bỏ qua shot.
            spent = existing is not None and (
                existing.status != "pending" or bool(existing.candidates)
            )
            spent_total = entry.manual_override_spent + (1 if spent else 0)
            if spent_total >= MAX_MANUAL_OVERRIDES_PER_REVIEW:
                raise VisualReviewError(
                    "Manual regeneration budget đã được sử dụng cho review này "
                    f"({spent_total}/{MAX_MANUAL_OVERRIDES_PER_REVIEW})."
                )
            return replace(
                entry,
                disposition=ReviewDisposition.MANUAL_REGENERATE,
                manual_override=override,
                manual_override_spent=spent_total,
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

    def initialize_manual_attempt(
        self,
        review_id: str,
        *,
        request_fingerprint: str,
        candidate_count: int,
        generation_key: str,
    ) -> VisualReviewEntry:
        if not 1 <= candidate_count <= 4:
            raise VisualReviewError("Manual candidate_count phải nằm trong [1, 4].")

        def update(entry: VisualReviewEntry) -> VisualReviewEntry:
            override = entry.manual_override
            if override is None or entry.disposition != ReviewDisposition.MANUAL_REGENERATE:
                raise VisualReviewError("Review không có manual regeneration disposition.")
            if override.base_request_fingerprint != entry.request_fingerprint:
                raise VisualReviewError("Manual override stale: base request đã thay đổi.")
            if override.candidates:
                if (
                    override.candidate_count != candidate_count
                    or override.generation_key != generation_key
                ):
                    raise VisualReviewError("Manual attempt identity không còn khớp.")
                return entry
            slots = tuple(
                ManualCandidateSlot(
                    candidate_slot_id=(
                        f"{entry.shot_id}::manual::{override.override_id}::"
                        f"candidate-{index:02d}"
                    ),
                    candidate_index=index,
                    seed=manual_candidate_seed(generation_key, index),
                )
                for index in range(candidate_count)
            )
            return replace(
                entry,
                manual_override=replace(
                    override,
                    status="running",
                    candidate_count=candidate_count,
                    generation_key=generation_key,
                    candidates=slots,
                ),
            )

        return self.update_pending(
            review_id,
            request_fingerprint=request_fingerprint,
            update=update,
        )

    def update_manual_slot(
        self,
        review_id: str,
        *,
        request_fingerprint: str,
        candidate_index: int,
        status: str,
        asset_id: str | None = None,
        last_error: str | None = None,
        increment_attempt: bool = False,
    ) -> VisualReviewEntry:
        if status not in {"pending", "running", "done", "failed"}:
            raise VisualReviewError(f"Manual slot status không hợp lệ: {status!r}.")

        def update(entry: VisualReviewEntry) -> VisualReviewEntry:
            override = entry.manual_override
            if override is None:
                raise VisualReviewError("Review thiếu manual override.")
            slots = list(override.candidates)
            try:
                slot_index = next(
                    index
                    for index, slot in enumerate(slots)
                    if slot.candidate_index == candidate_index
                )
            except StopIteration as exc:
                raise VisualReviewError(
                    f"Manual candidate slot không tồn tại: {candidate_index}."
                ) from exc
            slot = slots[slot_index]
            slots[slot_index] = replace(
                slot,
                status=status,
                asset_id=asset_id,
                attempt_count=slot.attempt_count + (1 if increment_attempt else 0),
                last_error=last_error,
            )
            return replace(
                entry,
                manual_override=replace(override, candidates=tuple(slots)),
            )

        return self.update_pending(
            review_id,
            request_fingerprint=request_fingerprint,
            update=update,
        )

    def resolve_manual_attempt(
        self,
        review_id: str,
        *,
        request_fingerprint: str,
        selected_asset_id: str,
        selection_mode: str,
        evaluation_fingerprint: str,
    ) -> VisualReviewEntry:
        def update(entry: VisualReviewEntry) -> VisualReviewEntry:
            override = entry.manual_override
            if override is None:
                raise VisualReviewError("Review thiếu manual override.")
            manual_ids = tuple(
                slot.asset_id for slot in override.candidates if slot.asset_id
            )
            if selected_asset_id not in manual_ids:
                raise VisualReviewError("Manual winner không thuộc manual candidate set.")
            return replace(
                entry,
                status=ReviewStatus.RESOLVED,
                candidate_asset_ids=tuple(
                    dict.fromkeys((*entry.candidate_asset_ids, *manual_ids))
                ),
                evaluation_fingerprint=evaluation_fingerprint,
                selected_asset_id=selected_asset_id,
                selection_mode=selection_mode,
                manual_override=replace(
                    override,
                    status="resolved",
                    selected_asset_id=selected_asset_id,
                ),
                last_error=None,
            )

        return self.update_pending(
            review_id,
            request_fingerprint=request_fingerprint,
            update=update,
        )

    def mark_manual_rejected(
        self,
        review_id: str,
        *,
        request_fingerprint: str,
        evaluation_fingerprint: str,
    ) -> VisualReviewEntry:
        def update(entry: VisualReviewEntry) -> VisualReviewEntry:
            override = entry.manual_override
            if override is None:
                raise VisualReviewError("Review thiếu manual override.")
            manual_ids = tuple(
                slot.asset_id for slot in override.candidates if slot.asset_id
            )
            return replace(
                entry,
                review_reason=ReviewReason.MANUAL_SEMANTIC_REJECTION,
                candidate_asset_ids=tuple(
                    dict.fromkeys((*entry.candidate_asset_ids, *manual_ids))
                ),
                evaluation_fingerprint=evaluation_fingerprint,
                recovery_status="manual_rejected",
                manual_override=replace(override, status="rejected"),
                last_error=None,
            )

        return self.update_pending(
            review_id,
            request_fingerprint=request_fingerprint,
            update=update,
        )

    def reopen_invalid_selection(
        self,
        review_id: str,
        *,
        request_fingerprint: str,
        error: str,
    ) -> VisualReviewEntry:
        with locked_json_update(self.path) as data:
            reviews = data.setdefault("reviews", {})
            payload = reviews.get(review_id)
            if payload is None:
                raise VisualReviewError(f"Không tìm thấy review {review_id!r}.")
            entry = VisualReviewEntry.from_dict(payload)
            if entry.request_fingerprint != request_fingerprint:
                raise VisualReviewError("Review stale: request fingerprint không còn khớp.")
            if entry.status != ReviewStatus.RESOLVED:
                raise VisualReviewError("Chỉ resolved review mới có thể reopen.")
            updated = replace(
                entry,
                status=ReviewStatus.PENDING,
                review_reason=ReviewReason.ACCEPTED_ASSET_INVALID,
                last_error=error,
                updated_at=_now_iso(),
            )
            reviews[review_id] = updated.to_dict()
            return updated
