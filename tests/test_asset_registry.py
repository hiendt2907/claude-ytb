"""Durable provenance/catalog registry for character_story generated visuals.

Phase 3.1 corrective tests. Phase 3's first attempt derived `asset_id`
deterministically from `generation_key`, making the two 1:1 in practice —
this violated the locked architecture (a `generation_key` must be free to
map to zero, one, or many `AssetRecord`s over the asset's history, e.g. the
same semantic request regenerated after a checkpoint change). This file
proves the corrected identity model. No ComfyUI, no real render.
`render/story.py`'s existing generation/caching behaviour staying unchanged
is verified separately by `tests/test_story_auto_generate_cache.py`
(unmodified, still passing) and the real-ffmpeg story renderer integration
tests.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
from pathlib import Path

from ytb_pipeline.render.asset_registry import AssetRegistry, content_sha256


def _write_bytes(path: Path, payload: bytes = b"fake-png-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _generated_kwargs(**overrides) -> dict:
    base = dict(
        generation_key="gen-key-1", is_fresh_generation=True,
        profile_id="ban-so-6", profile_version="1.0.0",
        seed=1, prompt="x", style_prompt="", negative_prompt="",
        steps=1, cfg=1.0, width=1, height=1, characters=(),
        generation_mode="solo", checkpoint="sdxl.safetensors",
        clip_vision_model="clip.safetensors", ipadapter_model="ipa.safetensors",
        solo_weight=0.8, duo_weight=0.6, duo_denoise=0.5,
        sampler="dpmpp_2m", scheduler="karras",
        scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="video-a",
    )
    base.update(overrides)
    return base


# A/B/C. One generation_key may map to MULTIPLE AssetRecords, with distinct IDs ----------

def test_two_records_can_share_one_generation_key_with_different_asset_ids(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image_a = _write_bytes(tmp_path / "a.png", b"result-A")
    image_b = _write_bytes(tmp_path / "b.png", b"result-B")

    id_a = registry.record_generated(**_generated_kwargs(local_path=image_a, seed=111))
    id_b = registry.record_generated(**_generated_kwargs(
        local_path=image_b, seed=222, scene_id="scene-001", shot_id="scene-001-shot-00",
    ))

    assert id_a != id_b
    records = registry.find_by_generation_key("gen-key-1")
    assert len(records) == 2
    assert {r["asset_id"] for r in records} == {id_a, id_b}


def test_asset_id_is_not_a_deterministic_function_of_generation_key(tmp_path):
    """Registering the SAME generation_key against two DIFFERENT physical
    files (different bytes) must not collide on asset_id — proving asset_id
    is not simply derived from generation_key."""
    registry_one = AssetRegistry(path=tmp_path / "one" / "registry.json")
    registry_two = AssetRegistry(path=tmp_path / "two" / "registry.json")
    image_one = _write_bytes(tmp_path / "one.png", b"bytes-one")
    image_two = _write_bytes(tmp_path / "two.png", b"bytes-two")

    id_one = registry_one.record_generated(**_generated_kwargs(local_path=image_one))
    id_two = registry_two.record_generated(**_generated_kwargs(local_path=image_two))

    # Same generation_key, same every other kwarg, different bytes -> if
    # asset_id were a deterministic function of generation_key alone, these
    # would be forced equal. They must not be.
    assert id_one != id_two


# D. Cache hit with an EXISTING AssetRecord reuses that record ----------------------------

def test_cache_hit_with_existing_record_reuses_asset_id_and_provenance(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "generated.png")

    fresh_id = registry.record_generated(**_generated_kwargs(local_path=image, seed=999))
    # A later render section reuses the exact same cache file (cache hit).
    reuse_id = registry.record_generated(**_generated_kwargs(
        local_path=image, is_fresh_generation=False, seed=None, prompt=None,
        style_prompt=None, negative_prompt=None, steps=None, cfg=None,
        width=None, height=None, characters=(), generation_mode=None,
        checkpoint=None, clip_vision_model=None, ipadapter_model=None,
        solo_weight=None, duo_weight=None, duo_denoise=None,
        sampler=None, scheduler=None,
        scene_id="scene-005", shot_id="scene-005-shot-00", video_slug="video-b",
    ))

    assert reuse_id == fresh_id
    [record] = registry.assets()
    assert record["asset_class"] == "generated"
    assert record["provenance_status"] == "complete"
    assert record["seed"] == 999  # untouched by the cache-hit call's None values
    assert len(record["uses"]) == 2


# E. Cache hit with NO existing record becomes legacy_generated/incomplete ----------------

def test_cache_hit_with_no_existing_record_is_legacy_generated_not_complete(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "pre-existing-cache-file.png")

    registry.record_generated(**_generated_kwargs(
        local_path=image, is_fresh_generation=False, seed=None, prompt=None,
        style_prompt=None, negative_prompt=None, steps=None, cfg=None,
        width=None, height=None, characters=(), generation_mode=None,
        checkpoint=None, clip_vision_model=None, ipadapter_model=None,
        solo_weight=None, duo_weight=None, duo_denoise=None,
        sampler=None, scheduler=None,
    ))

    [record] = registry.assets()
    assert record["asset_class"] == "legacy_generated"
    assert record["provenance_status"] == "legacy_unknown"
    # No fabricated historical seed/model/prompt certainty.
    assert "seed" not in record
    assert "checkpoint" not in record


def test_legacy_generated_is_never_silently_upgraded_to_complete_on_a_later_hit(tmp_path):
    """A later cache hit against an already-legacy record, even though the
    CURRENT request's full generation config is known, must not rewrite the
    record's provenance_status — historical provenance is immutable."""
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "pre-existing.png")

    registry.record_generated(**_generated_kwargs(
        local_path=image, is_fresh_generation=False, seed=None, prompt=None,
        style_prompt=None, negative_prompt=None, steps=None, cfg=None,
        width=None, height=None, characters=(), generation_mode=None,
        checkpoint=None, clip_vision_model=None, ipadapter_model=None,
        solo_weight=None, duo_weight=None, duo_denoise=None,
        sampler=None, scheduler=None,
    ))
    # A later hit that happens to know full current config — still a cache
    # hit against an existing (legacy) record, not a fresh generation.
    registry.record_generated(**_generated_kwargs(
        local_path=image, is_fresh_generation=False,
        scene_id="scene-009", shot_id="scene-009-shot-00", video_slug="video-z",
    ))

    [record] = registry.assets()
    assert record["asset_class"] == "legacy_generated"
    assert record["provenance_status"] == "legacy_unknown"
    assert len(record["uses"]) == 2


# F & G. Fresh generation records complete metadata, including model identity ------------

def test_fresh_generation_retains_full_generation_metadata(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "generated.png")

    registry.record_generated(**_generated_kwargs(
        local_path=image, seed=42, prompt="minh doc tin nhan",
        style_prompt="cinematic", negative_prompt="blurry",
        steps=28, cfg=6.5, width=1344, height=768,
        characters=("an", "minh"), generation_mode="duo",
        checkpoint="sd_xl_base_1.0.safetensors",
        clip_vision_model="CLIP-ViT-H-14.safetensors",
        ipadapter_model="ip-adapter-plus_sdxl_vit-h.safetensors",
        solo_weight=0.8, duo_weight=0.55, duo_denoise=0.45,
        sampler="dpmpp_2m", scheduler="karras",
    ))

    [record] = registry.assets()
    assert record["asset_class"] == "generated"
    assert record["provenance_status"] == "complete"
    assert record["seed"] == 42
    assert record["prompt"] == "minh doc tin nhan"
    assert record["characters"] == ["an", "minh"]
    assert record["generation_mode"] == "duo"
    assert record["checkpoint"] == "sd_xl_base_1.0.safetensors"
    assert record["clip_vision_model"] == "CLIP-ViT-H-14.safetensors"
    assert record["ipadapter_model"] == "ip-adapter-plus_sdxl_vit-h.safetensors"
    assert record["solo_weight"] == 0.8
    assert record["duo_weight"] == 0.55
    assert record["duo_denoise"] == 0.45
    assert record["sampler"] == "dpmpp_2m"
    assert record["scheduler"] == "karras"


# H. legacy_generated is distinct from profile_local ---------------------------------------

def test_legacy_generated_and_profile_local_are_distinct_asset_classes(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    legacy_image = _write_bytes(tmp_path / "legacy.png", b"legacy-bytes")
    local_image = _write_bytes(tmp_path / "local.png", b"local-bytes")

    registry.record_generated(**_generated_kwargs(
        local_path=legacy_image, is_fresh_generation=False, seed=None, prompt=None,
        style_prompt=None, negative_prompt=None, steps=None, cfg=None,
        width=None, height=None, characters=(), generation_mode=None,
        checkpoint=None, clip_vision_model=None, ipadapter_model=None,
        solo_weight=None, duo_weight=None, duo_denoise=None,
        sampler=None, scheduler=None,
    ))
    registry.record_local_asset(
        profile_id="ban-so-6", profile_version="1.0.0",
        relative_path="opening.png", local_path=local_image,
        scene_id="scene-002", shot_id="scene-002-shot-00", video_slug="video-a",
    )

    records = {r["asset_class"]: r for r in registry.assets()}
    assert set(records) == {"legacy_generated", "profile_local"}
    assert records["legacy_generated"]["provenance_status"] == "legacy_unknown"
    assert records["profile_local"]["provenance_status"] == "complete"
    assert records["profile_local"]["generation_key"] is None


def test_profile_local_asset_has_no_fake_generation_metadata(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "opening.png")

    registry.record_local_asset(
        profile_id="ban-so-6", profile_version="1.0.0",
        relative_path="opening.png", local_path=image,
        scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="video-a",
    )

    [record] = registry.assets()
    assert record["generation_key"] is None
    assert "seed" not in record
    assert "checkpoint" not in record


# I. Replacing bytes at the same local path cannot rewrite immutable provenance ------------

def test_replacing_bytes_at_the_same_path_creates_a_new_record_not_a_rewrite(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    path = tmp_path / "opening.png"
    _write_bytes(path, b"original-bytes")

    original_id = registry.record_local_asset(
        profile_id="p", profile_version="1.0.0", relative_path="opening.png",
        local_path=path, scene_id="scene-000", shot_id="scene-000-shot-00",
        video_slug="video-a",
    )

    # The file at the SAME path is replaced (profile artist swapped the art).
    path.write_bytes(b"replaced-bytes")
    replaced_id = registry.record_local_asset(
        profile_id="p", profile_version="1.0.0", relative_path="opening.png",
        local_path=path, scene_id="scene-006", shot_id="scene-006-shot-00",
        video_slug="video-c",
    )

    assert replaced_id != original_id
    records = {r["asset_id"]: r for r in registry.assets()}
    assert len(records) == 2
    assert records[original_id]["content_sha256"] == hashlib.sha256(b"original-bytes").hexdigest()
    assert records[replaced_id]["content_sha256"] == hashlib.sha256(b"replaced-bytes").hexdigest()
    # The original record's provenance is untouched by the path being reused.
    assert records[original_id]["local_path"] == str(path)


# J. Same concrete cached asset reused by two projects -> one record, many uses -----------

def test_reused_asset_records_multiple_scene_shot_usages(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "generated.png")

    registry.record_generated(**_generated_kwargs(
        local_path=image, scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="video-a",
    ))
    registry.record_generated(**_generated_kwargs(
        local_path=image, is_fresh_generation=False, seed=None, prompt=None,
        style_prompt=None, negative_prompt=None, steps=None, cfg=None,
        width=None, height=None, characters=(), generation_mode=None,
        checkpoint=None, clip_vision_model=None, ipadapter_model=None,
        solo_weight=None, duo_weight=None, duo_denoise=None,
        sampler=None, scheduler=None,
        scene_id="scene-004", shot_id="scene-004-shot-00", video_slug="video-b",
    ))

    [record] = registry.assets()
    assert len(record["uses"]) == 2
    assert {u["video_slug"] for u in record["uses"]} == {"video-a", "video-b"}


def test_repeated_identical_use_is_not_duplicated(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "generated.png")
    kwargs = _generated_kwargs(local_path=image)
    registry.record_generated(**kwargs)
    registry.record_generated(**kwargs)

    [record] = registry.assets()
    assert len(record["uses"]) == 1


# K. Shared writes remain safe --------------------------------------------------------------

def _mp_register_local_asset(registry_path: str, image_path: str, index: int) -> None:
    """Module-level so a `fork`ed child process can run it directly."""
    AssetRegistry(path=Path(registry_path)).record_local_asset(
        profile_id="p", profile_version="1.0.0",
        relative_path=f"asset-{index}.png", local_path=Path(image_path),
        scene_id=f"scene-{index:03d}", shot_id=f"scene-{index:03d}-shot-00",
        video_slug=f"video-{index}",
    )


def test_concurrent_registration_across_real_os_processes_is_safe(tmp_path):
    """Production has multiple batch worker PROCESSES, not just threads.
    `AssetRegistry` composes with `locked_json_update` (`fcntl.flock` +
    atomic rename), the same primitive `render/asset_catalog.py` already
    relies on and `tests/test_state_io.py` already proves — this test
    proves the composition holds across real OS processes, not just that
    the lock primitive itself works."""
    registry_path = tmp_path / "registry.json"
    images = [_write_bytes(tmp_path / f"asset-{i}.png", f"bytes-{i}".encode()) for i in range(4)]

    ctx = multiprocessing.get_context("fork")
    processes = [
        ctx.Process(target=_mp_register_local_asset, args=(str(registry_path), str(images[i]), i))
        for i in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    data = json.loads(registry_path.read_text(encoding="utf-8"))
    assert len(data["assets"]) == 4


def test_reading_an_absent_registry_returns_empty_list(tmp_path):
    registry = AssetRegistry(path=tmp_path / "does-not-exist.json")
    assert registry.assets() == []


def test_content_sha256_matches_actual_file_bytes(tmp_path):
    path = _write_bytes(tmp_path / "scene.png", b"hello-scene")
    assert content_sha256(path) == hashlib.sha256(b"hello-scene").hexdigest()
