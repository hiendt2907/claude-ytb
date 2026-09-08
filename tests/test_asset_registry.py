"""Durable provenance/catalog registry for character_story generated visuals.

Phase 3.2 corrective tests. Phase 3.1 fixed `asset_id` being deterministically
derived from `generation_key`, but then used `content_sha256` ALONE as a
universal upsert/dedup key — the same class of mistake one level down:
"same bytes" was being treated as "same record identity", which would wrongly
collapse a `profile_local` asset and a `generated` asset that happen to share
bytes, or two genuinely distinct generation events that produced identical
output. This file proves the corrected EXACT OBSERVATION matching model
(`local_path` + `content_sha256` + a compatible provenance class, +
`generation_key`/`seed` where applicable) — see `render/asset_registry.py`'s
module docstring for the full rationale. No ComfyUI, no real render.
`render/story.py`'s existing generation/caching behaviour staying unchanged
is verified separately by `tests/test_story_auto_generate_cache.py`
(unmodified, still passing) and the real-ffmpeg story renderer integration
tests.
"""

from __future__ import annotations

import hashlib
import threading
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


# Example B / item 12. Conflicting fresh-generation provenance on otherwise --------------
# matching evidence must never silently overwrite — it creates a new record.

def test_conflicting_seed_on_matching_evidence_creates_a_new_record_not_an_overwrite(tmp_path):
    """Same path (hence same bytes, since we never touch the file), same
    generation_key, but a DIFFERENT seed claimed by a second fresh-generation
    call. This is the corrupt/misleading-provenance/race shape the directive
    calls out — the safe choice is a new record, never silently adopting the
    conflicting seed into the first one."""
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "generated.png")

    id_first = registry.record_generated(**_generated_kwargs(local_path=image, seed=100))
    id_second = registry.record_generated(**_generated_kwargs(
        local_path=image, seed=200, scene_id="scene-777", shot_id="scene-777-shot-00",
        video_slug="video-conflict",
    ))

    assert id_first != id_second
    records = {r["asset_id"]: r for r in registry.assets()}
    assert records[id_first]["seed"] == 100  # untouched by the conflicting call
    assert records[id_second]["seed"] == 200
    assert records[id_first]["content_sha256"] == records[id_second]["content_sha256"]


# Example C. generated vs profile_local with IDENTICAL bytes must never collapse -----------

def test_generated_and_profile_local_with_identical_bytes_remain_separate(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    generated_image = _write_bytes(tmp_path / "generated.png", b"same-bytes-both-classes")
    local_image = _write_bytes(tmp_path / "local.png", b"same-bytes-both-classes")

    generated_id = registry.record_generated(**_generated_kwargs(local_path=generated_image))
    local_id = registry.record_local_asset(
        profile_id="p", profile_version="1.0.0", relative_path="local.png",
        local_path=local_image, scene_id="scene-002", shot_id="scene-002-shot-00",
        video_slug="video-a",
    )

    assert generated_id != local_id
    records = registry.find_by_content_sha256(
        hashlib.sha256(b"same-bytes-both-classes").hexdigest()
    )
    assert len(records) == 2
    assert {r["asset_class"] for r in records} == {"generated", "profile_local"}


# Example D. legacy_generated vs fresh generated with IDENTICAL bytes must never collapse ---

def test_legacy_generated_and_fresh_generated_with_identical_bytes_remain_separate(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    legacy_image = _write_bytes(tmp_path / "legacy.png", b"identical-payload")
    fresh_image = _write_bytes(tmp_path / "fresh.png", b"identical-payload")

    legacy_id = registry.record_generated(**_generated_kwargs(
        local_path=legacy_image, generation_key="legacy-key", is_fresh_generation=False,
        seed=None, prompt=None, style_prompt=None, negative_prompt=None, steps=None,
        cfg=None, width=None, height=None, characters=(), generation_mode=None,
        checkpoint=None, clip_vision_model=None, ipadapter_model=None,
        solo_weight=None, duo_weight=None, duo_denoise=None, sampler=None, scheduler=None,
    ))
    fresh_id = registry.record_generated(**_generated_kwargs(
        local_path=fresh_image, generation_key="fresh-key",
        scene_id="scene-003", shot_id="scene-003-shot-00", video_slug="video-b",
    ))

    assert legacy_id != fresh_id
    records = {r["asset_id"]: r for r in registry.assets()}
    assert records[legacy_id]["asset_class"] == "legacy_generated"
    assert records[fresh_id]["asset_class"] == "generated"


# Item 6. Different paths + identical bytes do not automatically merge --------------------

def test_different_paths_with_identical_bytes_do_not_automatically_merge(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    path_a = _write_bytes(tmp_path / "opening-a.png", b"shared-bytes")
    path_b = _write_bytes(tmp_path / "opening-b.png", b"shared-bytes")

    id_a = registry.record_local_asset(
        profile_id="p", profile_version="1.0.0", relative_path="opening-a.png",
        local_path=path_a, scene_id="scene-000", shot_id="scene-000-shot-00",
        video_slug="video-a",
    )
    id_b = registry.record_local_asset(
        profile_id="p", profile_version="1.0.0", relative_path="opening-b.png",
        local_path=path_b, scene_id="scene-001", shot_id="scene-001-shot-00",
        video_slug="video-a",
    )

    assert id_a != id_b
    records = registry.find_by_content_sha256(hashlib.sha256(b"shared-bytes").hexdigest())
    assert len(records) == 2


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
#
# A real multi-PROCESS (`multiprocessing`, fork-context) variant of these two
# tests was tried and reverted: forking from inside a pytest worker process
# destabilised unrelated tests elsewhere in the suite (a fork with other
# live threads/state in the parent — e.g. pytest-cov's tracer — is a known
# hazard, not specific to this registry). Threads are the right proxy here
# regardless: `file_lock()` in `orchestrator/state_io.py` opens a FRESH file
# descriptor per call (`lock_path.open("a", ...)`), and `fcntl.flock` is
# enforced by the kernel per OPEN FILE DESCRIPTION — it does not care whether
# the two descriptors coming from separate `open()` calls belong to the same
# process or different ones. A thread-based race against the shared file
# exercises the exact same kernel-level serialization a second batch-worker
# PROCESS would. `tests/test_state_io.py` separately proves the locking
# primitive itself; this proves `AssetRegistry` composes with it correctly.

def test_concurrent_registration_of_different_observations_across_threads_is_safe(tmp_path):
    """Production has multiple batch worker processes touching this file at
    once. Simulates 8 workers each registering a DIFFERENT concrete local
    asset — every registration must survive with no lost record."""
    registry = AssetRegistry(path=tmp_path / "registry.json")
    images = [_write_bytes(tmp_path / f"asset-{i}.png", f"bytes-{i}".encode()) for i in range(8)]
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            registry.record_local_asset(
                profile_id="p", profile_version="1.0.0",
                relative_path=f"asset-{index}.png", local_path=images[index],
                scene_id=f"scene-{index:03d}", shot_id=f"scene-{index:03d}-shot-00",
                video_slug=f"video-{index}",
            )
        except BaseException as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(registry.assets()) == 8


def test_concurrent_registration_of_the_same_exact_observation_does_not_duplicate(tmp_path):
    """The match-then-insert decision must happen inside ONE locked critical
    section (`locked_json_update`), never read-unlock-decide-relock-insert —
    otherwise two racing workers observing the SAME cache hit could each
    conclude 'no existing record' and both create one. Every worker here
    registers the EXACT SAME concrete observation (path, bytes,
    generation_key, seed) — a genuine race on one cache hit — and exactly
    one record must survive with all uses kept."""
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_bytes(tmp_path / "shared.png")  # one file, every worker sees it
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            registry.record_generated(**_generated_kwargs(
                local_path=image, generation_key="race-key", seed=555,
                scene_id=f"scene-{index:03d}", shot_id=f"scene-{index:03d}-shot-00",
                video_slug=f"video-{index}",
            ))
        except BaseException as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    records = registry.assets()
    assert len(records) == 1
    assert len(records[0]["uses"]) == 8


def test_reading_an_absent_registry_returns_empty_list(tmp_path):
    registry = AssetRegistry(path=tmp_path / "does-not-exist.json")
    assert registry.assets() == []


def test_content_sha256_matches_actual_file_bytes(tmp_path):
    path = _write_bytes(tmp_path / "scene.png", b"hello-scene")
    assert content_sha256(path) == hashlib.sha256(b"hello-scene").hexdigest()
