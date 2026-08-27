from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.render.scene_plan import Scene, ScenePlan, Shot

from ytb_pipeline.render.visual_assets import (
    VisualAssetResolver, VisualManifest, VisualRequest, build_visual_requests,
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


def test_manifest_round_trip_preserves_failed_checkpoint(tmp_path: Path):
    path = tmp_path / "project" / "visual_manifest.json"
    manifest = VisualManifest(source_fingerprint="source")
    manifest.mark_failed("shot-1", request_id="req", request_fingerprint="fp", error="ComfyUI down")
    manifest.write_json(path)
    restored = VisualManifest.read_json(path)
    assert restored.shots["shot-1"].status == "failed"
    assert restored.shots["shot-1"].attempt_count == 1
    assert restored.shots["shot-1"].last_error == "ComfyUI down"


def test_resolver_is_controlled_component():
    """The resolver is the explicit Phase-4 generation boundary."""
    assert callable(VisualAssetResolver.resolve)


# --- Phase 9: VisualAssetResolver multi-candidate wiring -------------------

from types import SimpleNamespace as _NS

from ytb_pipeline.render.asset_registry import AssetRegistry
from ytb_pipeline.render.visual_candidates import VisualCandidateStore


def _real_png(path: Path, color=(1, 2, 3)) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), color).save(path)


class _CountingProvider:
    def __init__(self):
        self.calls = 0

    def generate_scene(self, profile, **kwargs):
        self.calls += 1
        _real_png(kwargs["output_path"], color=(self.calls, self.calls, self.calls))


def _story_visual_generation(**overrides):
    base = dict(
        enabled=True, style_prompt="s", negative_prompt="n", steps=10, cfg=5.0,
        solo_weight=1.0, duo_weight=1.0, duo_denoise=0.5, candidate_count=1,
        selection_policy="first_valid", candidate_policy_version="phase9-v1",
    )
    base.update(overrides)
    return _NS(**base)


def _story_request(shot_id="shot-1"):
    return VisualRequest(
        request_id=f"vr_{shot_id}", request_fingerprint=f"fp_{shot_id}",
        scene_id="scene-000", shot_id=shot_id, visual_intent="minh nhìn xa xăm",
        characters=(), dimensions=(1080, 1920), resolution_kind="generated_image",
    )


def _story_segment():
    return _NS(visual_intent="minh nhìn xa xăm", scene_characters=())


def test_candidate_count_one_preserves_legacy_cache_path_and_seed_formula(tmp_path):
    from ytb_pipeline.render.visual_assets import VisualAssetResolver, _generation_key

    profile = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=1))
    registry = AssetRegistry(tmp_path / "registry.json")
    provider = _CountingProvider()
    resolver = VisualAssetResolver(profile, registry=registry, cache_dir=tmp_path / "cache", provider=provider)
    request = _story_request()
    segment = _story_segment()
    key = _generation_key(segment, profile, request.dimensions)

    record = resolver.resolve(request, segment, None, video_slug="vid")

    assert provider.calls == 1
    assert record["local_path"] == str(tmp_path / "cache" / f"{key}.png")
    assert record["seed"] == int(key[:16], 16) % (2**32)
    assert not (tmp_path / "cache" / "visual_candidates.json").exists()

    # Cache hit: resolving again must not call the provider a second time.
    resolver.resolve(request, segment, None, video_slug="vid")
    assert provider.calls == 1


def test_multi_candidate_generates_every_slot_and_selects_slot_zero_deterministically(tmp_path):
    profile = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=3))
    registry = AssetRegistry(tmp_path / "registry.json")
    provider = _CountingProvider()
    store = VisualCandidateStore(tmp_path / "project" / "visual_candidates.json")
    resolver = VisualAssetResolver(profile, registry=registry, cache_dir=tmp_path / "cache", provider=provider, candidate_store=store)
    request = _story_request()

    record = resolver.resolve(request, _story_segment(), None, video_slug="vid")

    assert provider.calls == 3
    generation_key = record["generation_key"]
    assert len(registry.find_by_generation_key(generation_key)) == 3
    candidate_set = store.get_or_create(shot_id=request.shot_id, request_id=request.request_id,
        request_fingerprint=request.request_fingerprint, generation_key=generation_key,
        candidate_policy_version="phase9-v1", target_candidate_count=3)
    assert candidate_set.selection_status == "selected"
    assert candidate_set.selected_asset_id == record["asset_id"]
    assert record["asset_id"] == candidate_set.slot(0).asset_id


def test_multi_candidate_resume_skips_valid_slots_and_only_retries_the_failed_one(tmp_path):
    profile = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=3))
    registry = AssetRegistry(tmp_path / "registry.json")
    store = VisualCandidateStore(tmp_path / "project" / "visual_candidates.json")

    class _FailThenSucceedProvider:
        def __init__(self):
            self.calls = 0

        def generate_scene(self, profile, **kwargs):
            self.calls += 1
            if kwargs["seed"] == self._fail_seed:
                raise RuntimeError("ComfyUI down")
            _real_png(kwargs["output_path"], color=(self.calls, self.calls, self.calls))

    from ytb_pipeline.render.visual_candidates import candidate_seed
    from ytb_pipeline.render.visual_assets import _generation_key
    request = _story_request()
    key = _generation_key(_story_segment(), profile, request.dimensions)
    provider = _FailThenSucceedProvider()
    provider._fail_seed = candidate_seed(key, 2)

    resolver = VisualAssetResolver(profile, registry=registry, cache_dir=tmp_path / "cache", provider=provider, candidate_store=store)
    # minimum_valid_candidates=1 (item 29): slot 2 failing does not fail the
    # whole resolution — slots 0/1 already give a valid candidate to select.
    first_record = resolver.resolve(request, _story_segment(), None, video_slug="vid")
    assert provider.calls == 3
    candidate_set = store.get_or_create(shot_id=request.shot_id, request_id=request.request_id,
        request_fingerprint=request.request_fingerprint, generation_key=key,
        candidate_policy_version="phase9-v1", target_candidate_count=3)
    assert candidate_set.slot(0).status == "done"
    assert candidate_set.slot(1).status == "done"
    assert candidate_set.slot(2).status == "failed"
    assert first_record["asset_id"] == candidate_set.slot(0).asset_id

    # Resume: only the failed slot must be retried; 0/1 stay untouched.
    provider._fail_seed = None
    record = resolver.resolve(request, _story_segment(), None, video_slug="vid")
    assert provider.calls == 4  # exactly one more call — for slot 2 only
    assert record["asset_id"] == candidate_set.slot(0).asset_id


def test_zero_valid_candidates_fails_closed(tmp_path):
    profile = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=2))
    registry = AssetRegistry(tmp_path / "registry.json")

    class _AlwaysFailProvider:
        def generate_scene(self, profile, **kwargs):
            raise RuntimeError("ComfyUI down")

    resolver = VisualAssetResolver(profile, registry=registry, cache_dir=tmp_path / "cache", provider=_AlwaysFailProvider())
    with pytest.raises(ValueError, match="Không có candidate hợp lệ"):
        resolver.resolve(_story_request(), _story_segment(), None, video_slug="vid")


def test_candidate_count_increase_reuses_slot_zero_without_regenerating(tmp_path):
    """Item 27: bumping candidate_count from 1 to 3 must reuse the already
    generated/cached slot 0 and only generate the newly added slots."""
    registry = AssetRegistry(tmp_path / "registry.json")
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()

    profile1 = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=1))
    resolver1 = VisualAssetResolver(profile1, registry=registry, cache_dir=cache_dir, provider=provider)
    request = _story_request()
    baseline = resolver1.resolve(request, _story_segment(), None, video_slug="vid")
    assert provider.calls == 1

    profile3 = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=3))
    resolver3 = VisualAssetResolver(profile3, registry=registry, cache_dir=cache_dir, provider=provider,
        candidate_store=VisualCandidateStore(tmp_path / "project" / "visual_candidates.json"))
    grown = resolver3.resolve(request, _story_segment(), None, video_slug="vid")

    assert provider.calls == 3  # only the 2 NEW slots generated, slot 0 reused
    assert grown["asset_id"] == baseline["asset_id"]


def test_candidate_count_decrease_does_not_delete_prior_candidate_records(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    cache_dir = tmp_path / "cache"
    provider = _CountingProvider()

    profile3 = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=3))
    resolver3 = VisualAssetResolver(profile3, registry=registry, cache_dir=cache_dir, provider=provider,
        candidate_store=VisualCandidateStore(tmp_path / "project" / "visual_candidates.json"))
    request = _story_request()
    resolver3.resolve(request, _story_segment(), None, video_slug="vid")
    assert len(registry.assets()) == 3

    profile1 = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=1))
    resolver1 = VisualAssetResolver(profile1, registry=registry, cache_dir=cache_dir, provider=provider)
    resolver1.resolve(request, _story_segment(), None, video_slug="vid")

    assert len(registry.assets()) == 3  # no candidate record deleted


# --- Phase 9: acceptance test (§45) + default-behavior regression (§46) ----

from ytb_pipeline.render.visual_assets import prepare_visual_assets


def _acceptance_plan(shot_id="scene-000-shot-00"):
    shot = Shot(shot_id, 0, 3.0, "generated", "minh nhìn xa xăm", "", ())
    return ScenePlan((Scene("scene-000", 0, 0, 3.0, "core_answer", "minh nhìn xa xăm", (), (shot,)),), "acceptance-plan")


def test_multi_candidate_acceptance_prepare_persist_select_then_rerender_without_regeneration(tmp_path):
    plan = _acceptance_plan()
    profile = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=3))
    voiceover = _NS(project_id="acceptance", segments=(_story_segment(),))
    registry = AssetRegistry(tmp_path / "registry.json")
    provider = _CountingProvider()
    project_dir = tmp_path / "project"

    _, manifest, prepared = prepare_visual_assets(
        voiceover, profile, project_dir=project_dir, dimensions=(1080, 1920),
        scene_plan=plan, registry=registry, cache_dir=tmp_path / "cache", provider=provider,
    )

    shot_id = plan.scenes[0].shots[0].shot_id
    assert provider.calls == 3
    assert len(registry.assets()) == 3
    selected_asset_id = manifest.shots[shot_id].asset_id
    assert selected_asset_id is not None
    assert prepared[shot_id] == Path(registry.find_by_asset_id(selected_asset_id)["local_path"])
    assert (project_dir / "visual_candidates.json").is_file()

    class _NoGenerationProvider:
        def generate_scene(self, *a, **k):
            raise AssertionError("Rerender phải không gọi ComfyUI lần nào.")

    _, manifest2, prepared2 = prepare_visual_assets(
        voiceover, profile, project_dir=project_dir, dimensions=(1080, 1920),
        scene_plan=plan, registry=registry, cache_dir=tmp_path / "cache", provider=_NoGenerationProvider(),
    )

    assert prepared2[shot_id] == prepared[shot_id]
    assert len(registry.assets()) == 3  # unselected candidates remain registered


def test_default_candidate_count_one_end_to_end_matches_phase8_generated_visual_behavior(tmp_path):
    """Mandatory regression (§46): candidate_count=1 profiles must observe
    exactly the pre-Phase-9 `prepare_visual_assets` behaviour."""
    plan = _acceptance_plan()
    profile = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=1))
    voiceover = _NS(project_id="regression", segments=(_story_segment(),))
    registry = AssetRegistry(tmp_path / "registry.json")
    provider = _CountingProvider()
    project_dir = tmp_path / "project"

    _, manifest, prepared = prepare_visual_assets(
        voiceover, profile, project_dir=project_dir, dimensions=(1080, 1920),
        scene_plan=plan, registry=registry, cache_dir=tmp_path / "cache", provider=provider,
    )

    assert provider.calls == 1  # one generation on cache miss
    assert len(registry.assets()) == 1
    assert not (project_dir / "visual_candidates.json").exists()

    class _NoGenerationProvider:
        def generate_scene(self, *a, **k):
            raise AssertionError("Cache hit không được gọi ComfyUI.")

    _, manifest2, prepared2 = prepare_visual_assets(
        voiceover, profile, project_dir=project_dir, dimensions=(1080, 1920),
        scene_plan=plan, registry=registry, cache_dir=tmp_path / "cache", provider=_NoGenerationProvider(),
    )
    assert prepared2 == prepared  # no generation on cache hit, same prepared path


# --- Phase 9: direct-resolution paths never trigger candidate machinery ----

def test_profile_local_resolution_never_creates_candidate_state(tmp_path):
    shot = Shot("scene-000-shot-00", 0, 3.0, "generated", "minh ngồi bàn", "fixed.png", ())
    plan = ScenePlan((Scene("scene-000", 0, 0, 3.0, "core_answer", "minh ngồi bàn", (), (shot,)),), "local-plan")
    assets_dir = tmp_path / "profile_assets"
    assets_dir.mkdir()
    _real_png(assets_dir / "fixed.png")

    class _Profile:
        profile_id, version = "p", "1"
        visual_generation = _story_visual_generation(candidate_count=3)

        def visual_asset_path(self, relative):
            return assets_dir / relative

    voiceover = _NS(project_id="local", segments=(_NS(visual_intent="minh ngồi bàn", scene_characters=(), visual_asset="fixed.png"),))
    registry = AssetRegistry(tmp_path / "registry.json")
    project_dir = tmp_path / "project"

    prepare_visual_assets(voiceover, _Profile(), project_dir=project_dir, dimensions=(1080, 1920), scene_plan=plan, registry=registry)

    assert not (project_dir / "visual_candidates.json").exists()
    assert registry.assets()[0]["asset_class"] == "profile_local"


def test_successful_derivative_reuse_never_creates_candidate_state(tmp_path):
    from ytb_pipeline.render.derivative_lineage import DerivativeLineage, ReuseSource

    image = tmp_path / "parent.png"
    _real_png(image)
    registry = AssetRegistry(tmp_path / "registry.json")
    registry.record_generated(generation_key="parent-key", local_path=image, is_fresh_generation=True,
        profile_id="p", profile_version="1", width=832, height=1216, scene_id="scene-000", shot_id="parent-shot", video_slug="long")
    lineage = DerivativeLineage("long", {"child-shot": ReuseSource("long", "scene-000", "parent-shot")})
    shot = Shot("child-shot", 0, 3.0, "generated", "same", "", ())
    plan = ScenePlan((Scene("scene-000", 0, 0, 3.0, "core", "same", (), (shot,)),), "child-plan")
    profile = _NS(profile_id="p", version="1", visual_generation=_story_visual_generation(candidate_count=3))
    voiceover = _NS(project_id="short", segments=(_NS(visual_intent="same", scene_characters=()),))
    project_dir = tmp_path / "project"

    class _NoGenerationProvider:
        def generate_scene(self, *a, **k):
            raise AssertionError("Reuse hợp lệ không được sinh candidate mới.")

    _, manifest, prepared = prepare_visual_assets(
        voiceover, profile, project_dir=project_dir, dimensions=(1080, 1920), scene_plan=plan,
        registry=registry, lineage=lineage, provider=_NoGenerationProvider(),
    )

    assert not (project_dir / "visual_candidates.json").exists()
    assert len(registry.assets()) == 1
    assert prepared["child-shot"] == image
