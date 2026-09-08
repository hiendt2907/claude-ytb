"""`ytb batch review ...` operator commands for Phase 13."""
from __future__ import annotations

import sys
from pathlib import Path

from ..config.settings import settings
from ..render.asset_registry import AssetRegistry, content_sha256
from ..render.visual_candidates import validate_candidate_image
from ..render.visual_evaluation_store import VisualEvaluationStore
from ..render.visual_review import VisualReviewError, VisualReviewStore
from ..render.visual_review_ops import (
    abandon_visual_review,
    accept_existing_candidate,
    request_manual_regeneration,
)


def _project_dir(project_id: str) -> Path:
    root = Path(settings.projects_dir).resolve()
    project = (root / project_id).resolve()
    if project.parent != root or not project_id.strip():
        raise VisualReviewError(f"Project identifier không hợp lệ: {project_id!r}.")
    if not project.is_dir():
        raise VisualReviewError(f"Project không tồn tại: {project_id!r}.")
    return project


def _current(project_dir: Path, shot_id: str):
    entry = VisualReviewStore(project_dir / "visual_review.json").current_for_shot(shot_id)
    if entry is None:
        raise VisualReviewError(f"Shot {shot_id!r} không có review hiện hành.")
    return entry


def _candidate_line(asset_id: str, registry: AssetRegistry) -> str:
    record = registry.find_by_asset_id(asset_id)
    if record is None:
        return f"  {asset_id} path=- technical=missing_asset_record"
    path = Path(record.get("local_path", ""))
    if not path.is_file():
        technical = "missing_file"
    elif content_sha256(path) != record.get("content_sha256"):
        technical = "sha_mismatch"
    elif not validate_candidate_image(path):
        technical = "invalid_media"
    else:
        technical = "valid"
    return f"  {asset_id} path={path} technical={technical}"


def _print_list(project_dir: Path) -> None:
    entries = VisualReviewStore(project_dir / "visual_review.json").entries()
    current = {}
    for entry in entries:
        if entry.status.value != "stale":
            current[entry.shot_id] = entry
    if not current:
        print("No visual reviews.")
        return
    for shot_id in sorted(current):
        entry = current[shot_id]
        disposition = entry.disposition.value if entry.disposition else "-"
        print(
            f"{entry.shot_id} status={entry.status.value} "
            f"reason={entry.review_reason.value} "
            f"candidates={len(entry.candidate_asset_ids)} "
            f"recovery={entry.recovery_status} disposition={disposition}"
        )


def _print_show(project_dir: Path, shot_id: str) -> None:
    entry = _current(project_dir, shot_id)
    registry = AssetRegistry()
    print(f"shot={entry.shot_id} review_id={entry.review_id}")
    print(
        f"status={entry.status.value} reason={entry.review_reason.value} "
        f"recovery={entry.recovery_status}"
    )
    print(f"visual_intent={entry.visual_intent}")
    print(f"characters={','.join(entry.characters) or '-'}")
    print(f"semantic_constraints={' | '.join(entry.semantic_constraints) or '-'}")
    print("candidates:")
    for asset_id in entry.candidate_asset_ids:
        print(_candidate_line(asset_id, registry))

    evaluation_store = VisualEvaluationStore(project_dir / "visual_evaluations.json")
    evaluation_keys = [entry.shot_id]
    if entry.manual_override is not None:
        evaluation_keys.append(entry.manual_override.evaluation_store_key)
    print("judge:")
    seen: set[str] = set()
    for key in evaluation_keys:
        evaluation_set = evaluation_store.get(key)
        if evaluation_set is None:
            continue
        for asset_id, evaluation in evaluation_set.evaluations.items():
            if asset_id in seen:
                continue
            seen.add(asset_id)
            print(
                f"  {asset_id} semantic={evaluation.semantic_score:.3f} "
                f"character={evaluation.character_score:.3f} "
                f"composition={evaluation.composition_score:.3f} "
                f"continuity={evaluation.continuity_score:.3f} "
                f"hard_failures={','.join(evaluation.hard_failures) or '-'} "
                f"reasons={' | '.join(evaluation.reasons) or '-'}"
            )
    disposition = entry.disposition.value if entry.disposition else "-"
    print(f"disposition={disposition} selection_mode={entry.selection_mode or '-'}")
    if entry.manual_override is not None:
        print(
            f"manual_override={entry.manual_override.override_id} "
            f"status={entry.manual_override.status} "
            f"instruction={entry.manual_override.instruction}"
        )


def cmd_review(args) -> None:
    """Apply one state-only review command; never run ComfyUI/Judge here."""
    try:
        project_dir = _project_dir(args.project)
        action = args.review_action
        if action == "list":
            _print_list(project_dir)
            return
        if action == "show":
            _print_show(project_dir, args.shot_id)
            return
        if action == "accept":
            entry = accept_existing_candidate(
                project_dir,
                args.shot_id,
                args.asset_id,
                registry=AssetRegistry(),
            )
            print(
                f"RESOLVED shot={entry.shot_id} asset_id={entry.selected_asset_id} "
                f"selection_mode={entry.selection_mode}"
            )
            return
        if action == "regenerate":
            entry = request_manual_regeneration(
                project_dir, args.shot_id, args.instruction,
                replaces_intent=bool(getattr(args, "replace_intent", False)),
            )
            print(
                f"PENDING shot={entry.shot_id} manual_override="
                f"{entry.manual_override.override_id}; generation starts on next pipeline run"
            )
            return
        if action == "abandon":
            entry = abandon_visual_review(project_dir, args.shot_id)
            print(f"ABANDONED shot={entry.shot_id} review_id={entry.review_id}")
            return
        raise VisualReviewError(f"Review action không hợp lệ: {action!r}.")
    except VisualReviewError as exc:
        print(f"review error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
