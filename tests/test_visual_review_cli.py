"""Operator CLI for Phase-13 visual review dispositions."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ytb_pipeline.config.settings import settings
from ytb_pipeline.orchestrator import batch_cli
from ytb_pipeline.render.asset_registry import AssetRegistry
from ytb_pipeline.render.visual_assets import VisualManifest, VisualManifestEntry, VisualRequest
from ytb_pipeline.render.visual_candidates import VisualCandidateStore
from ytb_pipeline.render.visual_evaluation_store import ShotEvaluationSet, VisualEvaluationStore
from ytb_pipeline.render.visual_judge import CandidateEvaluation
from ytb_pipeline.render.visual_review import ReviewReason, VisualReviewStore


def _project(tmp_path, monkeypatch, *, slug: str = "video"):
    projects = tmp_path / "projects"
    project = projects / slug
    project.mkdir(parents=True)
    registry_path = tmp_path / "registry.json"
    monkeypatch.setattr(settings, "projects_dir", projects)
    monkeypatch.setattr(settings, "asset_registry_path", registry_path)

    image = tmp_path / f"{slug}.png"
    Image.new("RGB", (8, 8), (10, 20, 30)).save(image)
    registry = AssetRegistry(registry_path)
    generation_key = "0123456789abcdef" + ("0" * 48)
    asset_id = registry.record_generated(
        generation_key=generation_key,
        local_path=image,
        is_fresh_generation=True,
        profile_id="story",
        profile_version="1",
        seed=7,
        prompt="Minh đứng trước cửa quán",
        width=8,
        height=8,
        scene_id="scene-001",
        shot_id="shot-001",
        video_slug=slug,
    )
    request = VisualRequest(
        request_id="vr-1",
        request_fingerprint="request-v1",
        scene_id="scene-001",
        shot_id="shot-001",
        visual_intent="Minh đứng trước cửa quán",
        characters=("minh",),
        dimensions=(1920, 1080),
        resolution_kind="generated_image",
    )
    candidate_store = VisualCandidateStore(project / "visual_candidates.json")
    candidate_set = candidate_store.get_or_create(
        shot_id=request.shot_id,
        request_id=request.request_id,
        request_fingerprint=request.request_fingerprint,
        generation_key=generation_key,
        candidate_policy_version="phase9-v1",
        target_candidate_count=1,
    )
    slot = candidate_set.slot(0)
    slot.seed = 7
    slot.status = "done"
    slot.asset_id = asset_id
    candidate_set.selection_status = "failed"
    candidate_store.write()
    review = VisualReviewStore(project / "visual_review.json").ensure_pending(
        request,
        reason=ReviewReason.SEMANTIC_FAIL_CLOSED,
        candidate_asset_ids=(asset_id,),
        evaluation_fingerprint="eval-1",
        recovery_status="eligible",
    )
    evaluation_store = VisualEvaluationStore(project / "visual_evaluations.json")
    evaluation_store.save(ShotEvaluationSet(
        shot_id="shot-001",
        request_fingerprint="request-v1",
        judge_provider="fake",
        judge_model="vision-v1",
        judge_policy_version="judge-v1",
        judge_contract_version="phase10-v1",
        candidate_identity={asset_id: registry.find_by_asset_id(asset_id)["content_sha256"]},
        evaluations={asset_id: CandidateEvaluation(
            asset_id, 0.2, 0.3, 0.4, 0.5, ("semantic_contradiction",), ("wrong scene",),
        )},
    ))
    evaluation_store.write()
    VisualManifest(
        "plan-1", {"shot-001": VisualManifestEntry("vr-1", "request-v1")}
    ).write_json(project / "visual_manifest.json")
    return project, review, asset_id


def test_review_list_and_show_present_operator_friendly_context(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)

    batch_cli.main(["review", "list", "video"])
    listed = capsys.readouterr().out
    batch_cli.main(["review", "show", "video", "shot-001"])
    shown = capsys.readouterr().out

    assert "shot-001" in listed
    assert "semantic_fail_closed" in listed
    assert "candidates=1" in listed
    assert "Minh đứng trước cửa quán" in shown
    assert "semantic=0.200" in shown
    assert "semantic_contradiction" in shown
    assert "wrong scene" in shown


def test_review_accept_command_validates_and_persists(tmp_path, monkeypatch, capsys):
    project, _review, asset_id = _project(tmp_path, monkeypatch)

    batch_cli.main([
        "review", "accept", "video", "shot-001", "--asset-id", asset_id,
    ])

    output = capsys.readouterr().out
    entry = VisualReviewStore(project / "visual_review.json").current_for_shot("shot-001")
    manifest = VisualManifest.read_json(project / "visual_manifest.json")
    assert "operator_override" in output
    assert entry.status.value == "resolved"
    assert manifest.shots["shot-001"].asset_id == asset_id


def test_review_regenerate_command_only_persists_human_instruction(tmp_path, monkeypatch, capsys):
    project, _review, _asset_id = _project(tmp_path, monkeypatch)

    batch_cli.main([
        "review", "regenerate", "video", "shot-001",
        "--instruction", "Bỏ đám đông phía sau",
    ])

    output = capsys.readouterr().out
    entry = VisualReviewStore(project / "visual_review.json").current_for_shot("shot-001")
    assert "next pipeline run" in output
    assert entry.manual_override.instruction == "Bỏ đám đông phía sau"
    assert entry.manual_override.candidates == ()


def test_review_abandon_command_persists_operator_stop(tmp_path, monkeypatch, capsys):
    project, _review, _asset_id = _project(tmp_path, monkeypatch)

    batch_cli.main(["review", "abandon", "video", "shot-001"])

    assert "ABANDONED" in capsys.readouterr().out
    assert VisualReviewStore(project / "visual_review.json").current_for_shot("shot-001").status.value == "abandoned"


@pytest.mark.parametrize(
    "argv",
    [
        ["review", "show", "missing", "shot-001"],
        ["review", "accept", "video", "missing-shot", "--asset-id", "ast-nope"],
        ["review", "regenerate", "video", "shot-001", "--instruction", ""],
    ],
)
def test_review_cli_invalid_identifiers_and_payload_exit_two(tmp_path, monkeypatch, argv):
    if argv[2] == "video":
        _project(tmp_path, monkeypatch)
    else:
        monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    with pytest.raises(SystemExit) as exc_info:
        batch_cli.main(argv)
    assert exc_info.value.code == 2
