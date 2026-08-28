from dataclasses import replace
from types import SimpleNamespace

import pytest

from ytb_pipeline import __main__ as pipeline_cli
from ytb_pipeline.project.workflow import WorkflowError
from ytb_pipeline.render.visual_review import (
    ReviewDisposition,
    ReviewReason,
    ReviewRequiredError,
    ReviewStatus,
    VisualAbandonedError,
    VisualReviewEntry,
)


def _review_entry(*, abandoned: bool = False) -> VisualReviewEntry:
    entry = VisualReviewEntry(
        review_id="review-1",
        shot_id="shot-1",
        request_id="request-1",
        request_fingerprint="f" * 64,
        scene_id="scene-1",
        visual_intent="Một người đứng bên cửa sổ",
        characters=(),
        dimensions=(1920, 1080),
        resolution_kind="generated",
        semantic_constraints=(),
        status=ReviewStatus.PENDING,
        review_reason=ReviewReason.SEMANTIC_FAIL_CLOSED,
        candidate_asset_ids=("asset-1",),
        evaluation_fingerprint="e" * 64,
        recovery_status="not_attempted",
        created_at="2026-08-28T00:00:00+00:00",
        updated_at="2026-08-28T00:00:00+00:00",
    )
    if abandoned:
        return replace(
            entry,
            status=ReviewStatus.ABANDONED,
            disposition=ReviewDisposition.ABANDON,
        )
    return entry


def _raise_workflow(cause: Exception):
    async def run(*_args, **_kwargs):
        try:
            raise cause
        except Exception as exc:
            raise WorkflowError("visual_assets", str(exc)) from exc

    return run


@pytest.mark.parametrize(
    ("cause", "expected_code", "expected_state"),
    [
        (ReviewRequiredError(_review_entry()), 3, "REVIEW_REQUIRED"),
        (VisualAbandonedError(_review_entry(abandoned=True)), 4, "ABANDONED"),
        (RuntimeError("provider timeout"), 1, "INFRASTRUCTURE_FAILED"),
    ],
)
def test_pipeline_cli_reports_explicit_non_success_state(
    monkeypatch, capsys, cause, expected_code, expected_state
):
    monkeypatch.setattr(pipeline_cli.sys, "argv", ["ytb_pipeline", "project"])
    monkeypatch.setattr(pipeline_cli, "load_or_create_project", lambda *_: object())
    monkeypatch.setattr(pipeline_cli, "run_project", _raise_workflow(cause))

    assert pipeline_cli.main() == expected_code
    captured = capsys.readouterr()
    assert f"PIPELINE_STATE={expected_state}" in captured.err
    assert "node=visual_assets" in captured.err


def test_pipeline_cli_reports_success_state(monkeypatch, capsys):
    project = SimpleNamespace(project_id="project")

    async def run(*_args, **_kwargs):
        return project

    monkeypatch.setattr(pipeline_cli.sys, "argv", ["ytb_pipeline", "project"])
    monkeypatch.setattr(pipeline_cli, "load_or_create_project", lambda *_: project)
    monkeypatch.setattr(pipeline_cli, "run_project", run)
    monkeypatch.setattr(pipeline_cli, "publish_summary", lambda *_: (False, None))

    assert pipeline_cli.main() == 0
    assert "PIPELINE_STATE=SUCCESS" in capsys.readouterr().out
