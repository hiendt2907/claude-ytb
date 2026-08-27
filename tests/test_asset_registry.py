"""Durable provenance/catalog registry for character_story generated visuals.

Phase 3 is additive observability: these tests exercise `AssetRegistry` in
isolation (no ComfyUI, no real render). `render/story.py`'s existing
generation/caching behaviour staying unchanged is verified separately by
`tests/test_story_auto_generate_cache.py` (unmodified, still passing) and
the real-ffmpeg story renderer integration tests.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from ytb_pipeline.render.asset_registry import (
    AssetRegistry,
    asset_id_for_generation_key,
    asset_id_for_local_path,
    content_sha256,
)


def _write_png(path: Path, payload: bytes = b"fake-png-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


# 1 & 3. Durable contract exists; asset_id/content_sha256/generation_key are distinct ---

def test_asset_id_content_sha256_and_generation_key_are_three_distinct_values():
    generation_key = "some-deterministic-cache-key"
    asset_id = asset_id_for_generation_key(generation_key)
    path_bytes = b"scene-image-bytes"

    assert asset_id != generation_key
    sha = hashlib.sha256(path_bytes).hexdigest()
    assert asset_id != sha
    assert generation_key != sha


def test_asset_id_for_generation_key_is_deterministic():
    key = "abc123"
    assert asset_id_for_generation_key(key) == asset_id_for_generation_key(key)


def test_content_sha256_matches_actual_file_bytes(tmp_path):
    path = _write_png(tmp_path / "scene.png", b"hello-scene")
    assert content_sha256(path) == hashlib.sha256(b"hello-scene").hexdigest()


# 2. Generated assets retain actual generation provenance, including seed -----------------

def test_record_generated_retains_seed_and_generation_parameters(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_png(tmp_path / "generated.png")

    asset_id = registry.record_generated(
        generation_key="gen-key-1", local_path=image,
        profile_id="ban-so-6", profile_version="1.0.0",
        seed=123456789, prompt="minh dang doc tin nhan",
        style_prompt="cinematic, soft light", negative_prompt="blurry",
        steps=28, cfg=6.5, width=1344, height=768,
        characters=("an", "minh"),
        scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="video-a",
    )

    [record] = registry.assets()
    assert record["asset_id"] == asset_id
    assert record["seed"] == 123456789
    assert record["prompt"] == "minh dang doc tin nhan"
    assert record["steps"] == 28
    assert record["cfg"] == 6.5
    assert record["characters"] == ["an", "minh"]
    assert record["provenance_complete"] is True
    assert record["generation_key"] == "gen-key-1"


# 5 & 8. Fixed/legacy local assets, no fake generation metadata ---------------------------

def test_record_local_asset_has_no_fake_generation_metadata(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_png(tmp_path / "opening.png")

    registry.record_local_asset(
        profile_id="ban-so-6", profile_version="1.0.0",
        relative_path="opening.png", local_path=image,
        scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="video-a",
    )

    [record] = registry.assets()
    assert record["generation_key"] is None
    assert record["provenance_complete"] is False
    assert record["source"] == "profile_local_asset"
    assert "seed" not in record or record.get("seed") is None


# 4. asset_id distinct from generation_key/content hash in a REAL registered record --------

def test_registered_asset_id_is_not_the_generation_key_or_content_hash(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_png(tmp_path / "generated.png", b"specific-bytes")
    generation_key = "gen-key-distinct-check"

    registry.record_generated(
        generation_key=generation_key, local_path=image,
        profile_id="p", profile_version="1.0.0", seed=1, prompt="x",
        style_prompt="", negative_prompt="", steps=1, cfg=1.0,
        width=1, height=1, characters=(),
        scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="v",
    )

    [record] = registry.assets()
    assert record["asset_id"] != record["generation_key"]
    assert record["asset_id"] != record["content_sha256"]
    assert record["generation_key"] != record["content_sha256"]


# 6. Scene/Shot associations use Phase-2 deterministic IDs ---------------------------------

def test_reused_asset_records_multiple_scene_shot_usages(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_png(tmp_path / "generated.png")

    registry.record_generated(
        generation_key="shared-key", local_path=image,
        profile_id="p", profile_version="1.0.0", seed=1, prompt="x",
        style_prompt="", negative_prompt="", steps=1, cfg=1.0,
        width=1, height=1, characters=(),
        scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="video-a",
    )
    # Same physical asset reused by a DIFFERENT project/video — audit
    # confirmed generated images are keyed by content, not by project.
    registry.record_generated(
        generation_key="shared-key", local_path=image,
        profile_id="p", profile_version="1.0.0", seed=1, prompt="x",
        style_prompt="", negative_prompt="", steps=1, cfg=1.0,
        width=1, height=1, characters=(),
        scene_id="scene-004", shot_id="scene-004-shot-00", video_slug="video-b",
    )

    [record] = registry.assets()  # one physical asset, one record
    assert len(record["uses"]) == 2
    assert {u["video_slug"] for u in record["uses"]} == {"video-a", "video-b"}
    assert {u["scene_id"] for u in record["uses"]} == {"scene-000", "scene-004"}


def test_repeated_identical_use_is_not_duplicated(tmp_path):
    registry = AssetRegistry(path=tmp_path / "registry.json")
    image = _write_png(tmp_path / "generated.png")
    kwargs = dict(
        generation_key="k", local_path=image,
        profile_id="p", profile_version="1.0.0", seed=1, prompt="x",
        style_prompt="", negative_prompt="", steps=1, cfg=1.0,
        width=1, height=1, characters=(),
        scene_id="scene-000", shot_id="scene-000-shot-00", video_slug="video-a",
    )
    registry.record_generated(**kwargs)
    registry.record_generated(**kwargs)

    [record] = registry.assets()
    assert len(record["uses"]) == 1


# 7. Shared registry writes are process-safe (concurrent-style upserts) -------------------

def test_concurrent_upserts_from_multiple_registry_instances_do_not_lose_uses(tmp_path):
    """Simulates two batch workers touching the shared registry file at once:
    each worker gets its own AssetRegistry instance (as a real worker
    process would), all pointed at the same path, and all usages must
    survive — the registry composes with the same `locked_json_update`
    exclusive-lock helper `asset_catalog.py` already relies on for this."""
    path = tmp_path / "registry.json"
    image = _write_png(tmp_path / "generated.png")
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            AssetRegistry(path=path).record_generated(
                generation_key="shared-key", local_path=image,
                profile_id="p", profile_version="1.0.0", seed=1, prompt="x",
                style_prompt="", negative_prompt="", steps=1, cfg=1.0,
                width=1, height=1, characters=(),
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
    data = json.loads(path.read_text(encoding="utf-8"))
    [record] = data["assets"].values()
    assert len(record["uses"]) == 8
    assert {u["video_slug"] for u in record["uses"]} == {f"video-{i}" for i in range(8)}


# 9 & 10. Registry file absence never blocks anything -------------------------------------

def test_reading_an_absent_registry_returns_empty_list(tmp_path):
    registry = AssetRegistry(path=tmp_path / "does-not-exist.json")
    assert registry.assets() == []


def test_local_asset_id_is_stable_and_distinct_from_generation_asset_id():
    local_id = asset_id_for_local_path("ban-so-6", "opening.png")
    generation_id = asset_id_for_generation_key("opening.png")

    assert local_id == asset_id_for_local_path("ban-so-6", "opening.png")
    assert local_id != generation_id
