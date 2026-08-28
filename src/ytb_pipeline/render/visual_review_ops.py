"""Operator disposition application services shared by CLI and tests."""
from __future__ import annotations

from pathlib import Path

from .asset_registry import AssetRegistry, content_sha256 as observed_content_sha256
from .visual_assets import VisualManifest
from .visual_candidates import VisualCandidateStore, validate_candidate_image
from .visual_review import (
    ReviewStatus,
    VisualReviewEntry,
    VisualReviewError,
    VisualReviewStore,
    request_from_review_entry,
)


def _current_pending(project_dir: Path, shot_id: str) -> tuple[VisualReviewStore, VisualReviewEntry]:
    store = VisualReviewStore(Path(project_dir) / "visual_review.json")
    entry = store.current_for_shot(shot_id)
    if entry is None:
        raise VisualReviewError(f"Shot {shot_id!r} không có review hiện hành.")
    if entry.status != ReviewStatus.PENDING:
        raise VisualReviewError(
            f"Shot {shot_id!r} không ở trạng thái pending: {entry.status.value}."
        )
    return store, entry


def _candidate_history_ids(
    project_dir: Path, entry: VisualReviewEntry
) -> tuple[set[str], VisualCandidateStore]:
    candidate_store = VisualCandidateStore(Path(project_dir) / "visual_candidates.json")
    candidate_set = candidate_store.get(entry.shot_id)
    automated: set[str] = set()
    if candidate_set is not None and candidate_set.request_fingerprint == entry.request_fingerprint:
        automated = {
            slot.asset_id
            for slot in candidate_set.candidates.values()
            if slot.asset_id is not None
        }
    manual = {
        slot.asset_id
        for slot in (entry.manual_override.candidates if entry.manual_override else ())
        if slot.asset_id is not None
    }
    return automated | manual, candidate_store


def validate_review_candidate(
    project_dir: Path,
    entry: VisualReviewEntry,
    asset_id: str,
    *,
    registry: AssetRegistry,
) -> dict:
    """Require an intact managed candidate belonging to this review/Shot."""
    history_ids, _candidate_store = _candidate_history_ids(project_dir, entry)
    if asset_id not in entry.candidate_asset_ids or asset_id not in history_ids:
        raise VisualReviewError(
            f"Asset {asset_id!r} không thuộc candidate history của Shot {entry.shot_id}."
        )
    record = registry.find_by_asset_id(asset_id)
    if record is None:
        raise VisualReviewError(f"AssetRecord không tồn tại: {asset_id}.")
    path = Path(record.get("local_path", ""))
    if not path.is_file():
        raise VisualReviewError(f"Candidate physical file không tồn tại: {path}.")
    if observed_content_sha256(path) != record.get("content_sha256"):
        raise VisualReviewError(f"Candidate SHA-256 đã thay đổi: {asset_id}.")
    if not validate_candidate_image(path):
        raise VisualReviewError(f"Candidate technical validation thất bại: {asset_id}.")
    return record


def accept_existing_candidate(
    project_dir: Path,
    shot_id: str,
    asset_id: str,
    *,
    registry: AssetRegistry | None = None,
) -> VisualReviewEntry:
    project_dir = Path(project_dir)
    registry = registry or AssetRegistry()
    store, entry = _current_pending(project_dir, shot_id)
    validate_review_candidate(project_dir, entry, asset_id, registry=registry)
    resolved = store.resolve_accept_existing(
        entry.review_id,
        request_fingerprint=entry.request_fingerprint,
        asset_id=asset_id,
    )

    # Keep the existing candidate selection checkpoint auditable. This does
    # not alter AssetRegistry or evaluation history.
    candidate_store = VisualCandidateStore(project_dir / "visual_candidates.json")
    candidate_set = candidate_store.get(shot_id)
    if candidate_set is not None:
        candidate_set.selected_asset_id = asset_id
        candidate_set.selection_status = "selected"
        candidate_set.selection_mode = "operator_override"
        candidate_store.write()

    manifest_path = project_dir / "visual_manifest.json"
    if not manifest_path.is_file():
        raise VisualReviewError("Thiếu visual_manifest.json cho operator acceptance.")
    manifest = VisualManifest.read_json(manifest_path)
    manifest.mark_done(
        shot_id,
        request_id=entry.request_id,
        request_fingerprint=entry.request_fingerprint,
        asset_id=asset_id,
    )
    manifest.write_json(manifest_path)
    return resolved


def request_manual_regeneration(
    project_dir: Path, shot_id: str, instruction: str
) -> VisualReviewEntry:
    store, entry = _current_pending(Path(project_dir), shot_id)
    history_ids, _candidate_store = _candidate_history_ids(Path(project_dir), entry)
    if not history_ids:
        raise VisualReviewError("Review không còn candidate history hợp lệ để neo request.")
    return store.submit_manual_regenerate(
        entry.review_id,
        request=request_from_review_entry(entry),
        instruction=instruction,
    )


def abandon_visual_review(project_dir: Path, shot_id: str) -> VisualReviewEntry:
    store, entry = _current_pending(Path(project_dir), shot_id)
    return store.abandon(
        entry.review_id,
        request_fingerprint=entry.request_fingerprint,
    )
