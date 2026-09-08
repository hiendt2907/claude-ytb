from pathlib import Path
from types import SimpleNamespace

from ytb_pipeline.render.asset_registry import AssetRegistry
from ytb_pipeline.render.derivative_lineage import DerivativeLineage, ReuseSource
from ytb_pipeline.render.scene_plan import Scene, ScenePlan, Shot
from ytb_pipeline.render.visual_assets import prepare_visual_assets


def _plan(shot_id: str, intent: str = "same"):
    shot = Shot(shot_id, 0, 2, "generated", intent, "", ())
    return ScenePlan((Scene("scene-000", 0, 0, 2, "core", intent, (), (shot,)),), "plan")


def test_explicit_lineage_reuses_valid_parent_asset_without_duplicate_record(tmp_path):
    image = tmp_path / "parent.png"; image.write_bytes(b"parent")
    registry = AssetRegistry(tmp_path / "registry.json")
    asset_id = registry.record_generated(generation_key="parent", local_path=image, is_fresh_generation=True,
        profile_id="p", profile_version="1", width=832, height=1216, scene_id="scene-000", shot_id="parent-shot", video_slug="long")
    lineage = DerivativeLineage("long", {"child-shot": ReuseSource("long", "scene-000", "parent-shot")})
    profile = SimpleNamespace(profile_id="p", version="1", visual_generation=SimpleNamespace(enabled=True))
    voiceover = SimpleNamespace(project_id="short", segments=(SimpleNamespace(visual_intent="same", scene_characters=()),))
    _, manifest, prepared = prepare_visual_assets(voiceover, profile, project_dir=tmp_path / "short", dimensions=(1080, 1920),
        scene_plan=_plan("child-shot"), registry=registry, lineage=lineage)
    assert manifest.shots["child-shot"].asset_id == asset_id
    assert prepared["child-shot"] == image
    assert len(registry.assets()) == 1
    assert {use["video_slug"] for use in registry.find_by_asset_id(asset_id)["uses"]} == {"long", "short"}


def test_incompatible_parent_asset_falls_back_to_normal_resolver(tmp_path):
    image = tmp_path / "parent.png"; image.write_bytes(b"parent")
    registry = AssetRegistry(tmp_path / "registry.json")
    registry.record_generated(generation_key="parent", local_path=image, is_fresh_generation=True,
        profile_id="p", profile_version="1", width=1344, height=768, scene_id="scene-000", shot_id="parent-shot", video_slug="long")
    class Provider:
        calls = 0
        def generate_scene(self, profile, **kwargs):
            self.calls += 1; kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True); kwargs["output_path"].write_bytes(b"child")
    provider = Provider()
    lineage = DerivativeLineage("long", {"child-shot": ReuseSource("long", "scene-000", "parent-shot")})
    profile = SimpleNamespace(profile_id="p", version="1", visual_generation=SimpleNamespace(enabled=True, style_prompt="", negative_prompt="", steps=1, cfg=1, solo_weight=1, duo_weight=1, duo_denoise=1))
    voiceover = SimpleNamespace(project_id="short", segments=(SimpleNamespace(visual_intent="same", scene_characters=()),))
    _, manifest, _ = prepare_visual_assets(voiceover, profile, project_dir=tmp_path / "short", dimensions=(1080, 1920), scene_plan=_plan("child-shot"), registry=registry, lineage=lineage, cache_dir=tmp_path / "cache", provider=provider)
    assert provider.calls == 1 and manifest.shots["child-shot"].asset_id != ""
