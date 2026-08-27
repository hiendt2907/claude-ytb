from pathlib import Path
from types import SimpleNamespace

from ytb_pipeline.render.scene_plan import Scene, ScenePlan, Shot

from ytb_pipeline.render.visual_assets import (
    VisualManifest, VisualRequest, build_visual_requests,
)


def test_visual_request_identity_is_semantic_and_provider_neutral():
    profile = SimpleNamespace(profile_id="story", version="1", visual_generation=SimpleNamespace(enabled=True))
    shot = Shot("scene-000-shot-00", 0, 2, "generated", "Minh looks up", "", ("minh",))
    plan = ScenePlan((Scene("scene-000", 0, 0, 2, "hook", "Minh looks up", ("minh",), (shot,)),))
    requests = build_visual_requests(plan, profile, dimensions=(1920, 1080))
    request = requests[0]
    assert request.shot_id == plan.scenes[0].shots[0].shot_id
    assert request.visual_intent == "Minh looks up"
    assert request.characters == ("minh",)
    assert request.dimensions == (1920, 1080)
    assert not (set(vars(request)) & {"sampler", "scheduler", "checkpoint", "workflow"})


def test_manifest_done_entry_validates_registered_bytes(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"valid image")
    manifest = VisualManifest(source_fingerprint="source")
    manifest.mark_done("shot-1", request_id="req", request_fingerprint="fp", asset_id="ast")
    assert manifest.is_reusable("shot-1", request_fingerprint="fp", asset_path=image, content_sha256="invalid") is False
