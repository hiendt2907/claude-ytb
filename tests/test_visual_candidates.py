"""Phase 9 — multi-candidate visual generation + deterministic selection.

Unit-level coverage of `render/visual_candidates.py` in isolation: candidate
identity/seed determinism, cache-path non-collision, checkpoint/resume
semantics, technical validation, and `first_valid` selection. The end-to-end
generation/selection flow through `VisualAssetResolver` is covered in
`tests/test_visual_assets.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ytb_pipeline.render.asset_registry import AssetRegistry
from ytb_pipeline.render.visual_candidates import (
    VisualCandidateSet,
    VisualCandidateStore,
    candidate_cache_path,
    candidate_is_valid,
    candidate_seed,
    resolve_selection_policy,
    select_first_valid,
    validate_candidate_image,
)


def _write_png(path: Path, *, size=(4, 4), color=(10, 20, 30)) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


# --- Candidate identity / seed determinism (§39) ---------------------------

def test_candidate_slot_zero_seed_matches_the_pre_phase9_single_candidate_formula():
    key = "abcdef0123456789abcdef0123456789"
    assert candidate_seed(key, 0) == int(key[:16], 16) % (2**32)


def test_candidate_seeds_are_deterministic_across_repeated_calls():
    key = "deadbeefdeadbeefdeadbeefdeadbeef"
    seeds_a = [candidate_seed(key, i) for i in range(4)]
    seeds_b = [candidate_seed(key, i) for i in range(4)]
    assert seeds_a == seeds_b


def test_candidate_seeds_differ_across_slots_for_the_same_generation_key():
    key = "cafefeedcafefeedcafefeedcafefeed"
    seeds = [candidate_seed(key, i) for i in range(4)]
    assert len(set(seeds)) == 4


def test_same_request_and_policy_reproduces_the_same_slot_identities():
    a = VisualCandidateSet("shot-1", "req", "fp", "abc1230123456789abcdef0123456789", "phase9-v1", 3)
    b = VisualCandidateSet("shot-1", "req", "fp", "abc1230123456789abcdef0123456789", "phase9-v1", 3)
    for index in range(3):
        assert a.slot(index).candidate_slot_id == b.slot(index).candidate_slot_id
        assert a.slot(index).seed == b.slot(index).seed


def test_asset_id_is_independent_of_candidate_slot_identity(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    image = _write_png(tmp_path / "a.png")
    asset_id = registry.record_generated(
        generation_key="abc1230123456789abcdef0123456789", local_path=image, is_fresh_generation=True,
        profile_id="p", profile_version="1", seed=candidate_seed("abc1230123456789abcdef0123456789", 0),
        scene_id="scene-000", shot_id="shot-1", video_slug="vid",
    )
    assert not asset_id.startswith("shot-1")
    assert "candidate" not in asset_id


def test_same_generation_key_may_be_shared_by_many_candidate_asset_records(tmp_path):
    """Phase 3's own contract, finally exercised intentionally (§3, §12)."""
    registry = AssetRegistry(tmp_path / "registry.json")
    asset_ids = []
    for index in range(3):
        image = _write_png(tmp_path / f"cand-{index}.png", color=(index, index, index))
        asset_ids.append(registry.record_generated(
            generation_key="abcfeed0123456789abcdef012345678", local_path=image, is_fresh_generation=True,
            profile_id="p", profile_version="1", seed=candidate_seed("abcfeed0123456789abcdef012345678", index),
            scene_id="scene-000", shot_id="shot-1", video_slug="vid",
        ))
    assert len(set(asset_ids)) == 3
    assert len(registry.find_by_generation_key("abcfeed0123456789abcdef012345678")) == 3


# --- Cache storage (§40) ----------------------------------------------------

def test_candidate_slot_zero_preserves_the_legacy_cache_filename(tmp_path):
    path = candidate_cache_path(tmp_path, "the-key", 0)
    assert path == tmp_path / "the-key.png"


def test_additional_candidate_slots_use_distinct_physical_paths(tmp_path):
    paths = {candidate_cache_path(tmp_path, "the-key", i) for i in range(4)}
    assert len(paths) == 4


def test_candidate_slots_never_collide_with_slot_zero_or_each_other(tmp_path):
    slot0 = candidate_cache_path(tmp_path, "the-key", 0)
    slot1 = candidate_cache_path(tmp_path, "the-key", 1)
    slot2 = candidate_cache_path(tmp_path, "the-key", 2)
    assert slot0 != slot1 != slot2 != slot0


# --- Phase 12: generation-round identity -----------------------------------

def test_round_zero_identity_remains_phase9_compatible(tmp_path):
    key = "abcdef0123456789abcdef0123456789"
    candidate_set = VisualCandidateSet("shot-1", "req", "fp", key, "phase9-v1", 2)

    assert candidate_set.slot(0, generation_round=0).candidate_slot_id == "shot-1::candidate-00"
    assert candidate_set.slot(0, generation_round=0).seed == int(key[:16], 16) % (2**32)
    assert candidate_cache_path(tmp_path, key, 0, generation_round=0) == tmp_path / f"{key}.png"


def test_round_one_slot_seed_and_cache_identity_is_deterministic_and_distinct(tmp_path):
    key = "abcdef0123456789abcdef0123456789"
    first = VisualCandidateSet("shot-1", "req", "fp", key, "phase9-v1", 3)
    second = VisualCandidateSet("shot-1", "req", "fp", key, "phase9-v1", 3)

    round_one_ids = []
    round_one_seeds = []
    round_one_paths = []
    for index in range(3):
        slot = first.slot(index, generation_round=1)
        matching = second.slot(index, generation_round=1)
        round_one_ids.append(slot.candidate_slot_id)
        round_one_seeds.append(slot.seed)
        round_one_paths.append(candidate_cache_path(tmp_path, key, index, generation_round=1))
        assert slot.candidate_slot_id == matching.candidate_slot_id
        assert slot.seed == matching.seed
        assert slot.seed != candidate_seed(key, index, generation_round=0)

    assert round_one_ids == [
        "shot-1::round-01::candidate-00",
        "shot-1::round-01::candidate-01",
        "shot-1::round-01::candidate-02",
    ]
    assert len(set(round_one_seeds)) == 3
    assert len(set(round_one_paths)) == 3
    assert not set(round_one_paths) & {
        candidate_cache_path(tmp_path, key, index, generation_round=0)
        for index in range(3)
    }


def test_legacy_candidate_json_loads_as_round_zero_without_migration(tmp_path):
    path = tmp_path / "visual_candidates.json"
    path.write_text(json.dumps({
        "shots": {
            "shot-1": {
                "shot_id": "shot-1",
                "request_id": "req",
                "request_fingerprint": "fp",
                "generation_key": "abcdef0123456789abcdef0123456789",
                "candidate_policy_version": "phase9-v1",
                "target_candidate_count": 1,
                "candidates": {
                    "shot-1::candidate-00": {
                        "candidate_slot_id": "shot-1::candidate-00",
                        "candidate_index": 0,
                        "seed": 123,
                        "status": "done",
                        "asset_id": "ast_legacy",
                        "attempt_count": 1,
                        "last_error": None,
                    }
                },
            }
        }
    }), encoding="utf-8")

    restored = VisualCandidateStore(path).get("shot-1")

    assert restored is not None
    assert restored.slot(0).candidate_slot_id == "shot-1::candidate-00"
    assert restored.slot(0).generation_round == 0
    assert restored.active_generation_round == 0
    assert restored.recovery_status == "not_needed"


def test_recovery_state_and_both_rounds_persist_across_reload(tmp_path):
    path = tmp_path / "visual_candidates.json"
    store = VisualCandidateStore(path)
    candidate_set = store.get_or_create(
        shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="abcdef0123456789abcdef0123456789",
        candidate_policy_version="phase9-v1", target_candidate_count=2,
    )
    candidate_set.recovery_policy = "regenerate_once"
    candidate_set.recovery_status = "running"
    candidate_set.active_generation_round = 1
    candidate_set.semantic_rejection_rounds = [0]
    candidate_set.rejected_evaluation_fingerprint = "eval-round-0"
    candidate_set.slot(0, generation_round=1).status = "done"
    store.write()

    restored = VisualCandidateStore(path).get("shot-1")

    assert restored is not None
    assert restored.recovery_policy == "regenerate_once"
    assert restored.recovery_status == "running"
    assert restored.active_generation_round == 1
    assert restored.semantic_rejection_rounds == [0]
    assert restored.rejected_evaluation_fingerprint == "eval-round-0"
    assert restored.slot(0, generation_round=1).status == "done"


def test_changed_request_resets_recovery_chain_to_fresh_round_zero(tmp_path):
    store = VisualCandidateStore(tmp_path / "visual_candidates.json")
    previous = store.get_or_create(
        shot_id="shot-1", request_id="req-1", request_fingerprint="fp-1",
        generation_key="aaa1230123456789abcdef0123456789",
        candidate_policy_version="phase9-v1", target_candidate_count=2,
    )
    previous.recovery_status = "exhausted"
    previous.semantic_rejection_rounds = [0, 1]
    previous.slot(0, generation_round=1).status = "done"

    current = store.get_or_create(
        shot_id="shot-1", request_id="req-2", request_fingerprint="fp-2",
        generation_key="bbb1230123456789abcdef0123456789",
        candidate_policy_version="phase9-v1", target_candidate_count=2,
    )

    assert current is not previous
    assert current.recovery_status == "not_needed"
    assert current.semantic_rejection_rounds == []
    assert current.slot(0).generation_round == 0
    assert all(slot.generation_round == 0 for slot in current.candidates.values())


def test_candidate_count_change_preserves_historical_round_slots(tmp_path):
    store = VisualCandidateStore(tmp_path / "visual_candidates.json")
    original = store.get_or_create(
        shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="aaa1230123456789abcdef0123456789",
        candidate_policy_version="phase9-v1", target_candidate_count=3,
    )
    for generation_round in (0, 1):
        for index in range(3):
            original.slot(index, generation_round=generation_round).status = "done"
    original.recovery_status = "exhausted"
    original.semantic_rejection_rounds = [0, 1]

    resized = store.get_or_create(
        shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="aaa1230123456789abcdef0123456789",
        candidate_policy_version="phase9-v1", target_candidate_count=2,
    )

    assert resized is original
    assert resized.target_candidate_count == 2
    assert len(resized.candidates) == 6
    assert resized.recovery_status == "exhausted"
    assert resized.slot(2, generation_round=0).status == "done"
    assert resized.slot(2, generation_round=1).status == "done"


# --- Technical validation (§18) --------------------------------------------

def test_a_real_decodable_image_passes_technical_validation(tmp_path):
    image = _write_png(tmp_path / "ok.png")
    assert validate_candidate_image(image) is True


def test_corrupt_bytes_fail_technical_validation(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a real image")
    assert validate_candidate_image(bad) is False


def test_an_empty_file_fails_technical_validation(tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    assert validate_candidate_image(empty) is False


def test_a_missing_file_fails_technical_validation(tmp_path):
    assert validate_candidate_image(tmp_path / "missing.png") is False


# --- Persistence / checkpoint / resume (§41) --------------------------------

def test_candidate_store_persists_progress_across_reload(tmp_path):
    path = tmp_path / "visual_candidates.json"
    store = VisualCandidateStore(path)
    candidate_set = store.get_or_create(
        shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="abc1230123456789abcdef0123456789", candidate_policy_version="phase9-v1", target_candidate_count=3,
    )
    slot0 = candidate_set.slot(0)
    slot0.status, slot0.asset_id = "done", "ast_0"
    slot1 = candidate_set.slot(1)
    slot1.status, slot1.asset_id = "done", "ast_1"
    slot2 = candidate_set.slot(2)
    slot2.status, slot2.last_error = "failed", "ComfyUI down"
    store.write()

    reloaded = VisualCandidateStore(path)
    restored = reloaded.get_or_create(
        shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="abc1230123456789abcdef0123456789", candidate_policy_version="phase9-v1", target_candidate_count=3,
    )
    assert restored.slot(0).status == "done" and restored.slot(0).asset_id == "ast_0"
    assert restored.slot(1).status == "done" and restored.slot(1).asset_id == "ast_1"
    assert restored.slot(2).status == "failed" and restored.slot(2).last_error == "ComfyUI down"


def test_changed_request_fingerprint_starts_a_fresh_candidate_set(tmp_path):
    store = VisualCandidateStore(tmp_path / "visual_candidates.json")
    first = store.get_or_create(shot_id="shot-1", request_id="req", request_fingerprint="fp-1",
        generation_key="aaa1230123456789abcdef0123456789", candidate_policy_version="phase9-v1", target_candidate_count=1)
    first.slot(0).status = "done"
    second = store.get_or_create(shot_id="shot-1", request_id="req", request_fingerprint="fp-2",
        generation_key="bbb1230123456789abcdef0123456789", candidate_policy_version="phase9-v1", target_candidate_count=1)
    assert second.slot(0).status == "pending"


def test_policy_version_change_alone_preserves_existing_candidate_progress(tmp_path):
    """Item 26: a selector-version bump must not force regeneration of
    already-valid candidates — only a request fingerprint change does."""
    store = VisualCandidateStore(tmp_path / "visual_candidates.json")
    first = store.get_or_create(shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="aaa1230123456789abcdef0123456789", candidate_policy_version="phase9-v1", target_candidate_count=1)
    first.slot(0).status, first.slot(0).asset_id = "done", "ast_0"
    second = store.get_or_create(shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="aaa1230123456789abcdef0123456789", candidate_policy_version="phase9-v2", target_candidate_count=1)
    assert second.slot(0).status == "done" and second.slot(0).asset_id == "ast_0"
    assert second.candidate_policy_version == "phase9-v2"


def test_candidate_count_increase_only_creates_new_slots_not_reuse_of_existing(tmp_path):
    store = VisualCandidateStore(tmp_path / "visual_candidates.json")
    first = store.get_or_create(shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="aaa1230123456789abcdef0123456789", candidate_policy_version="phase9-v1", target_candidate_count=1)
    first.slot(0).status, first.slot(0).asset_id = "done", "ast_0"
    grown = store.get_or_create(shot_id="shot-1", request_id="req", request_fingerprint="fp",
        generation_key="aaa1230123456789abcdef0123456789", candidate_policy_version="phase9-v1", target_candidate_count=3)
    assert grown.slot(0).status == "done" and grown.slot(0).asset_id == "ast_0"
    assert grown.slot(1).status == "pending"
    assert grown.slot(2).status == "pending"


# --- Selection (§43) ---------------------------------------------------------

def test_first_valid_selection_is_deterministic(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    candidate_set = VisualCandidateSet("shot-1", "req", "fp", "abc1230123456789abcdef0123456789", "phase9-v1", 3)
    for index in range(3):
        image = _write_png(tmp_path / f"c{index}.png", color=(index, index, index))
        seed = candidate_seed("abc1230123456789abcdef0123456789", index)
        asset_id = registry.record_generated(generation_key="abc1230123456789abcdef0123456789", local_path=image, is_fresh_generation=True,
            profile_id="p", profile_version="1", seed=seed, scene_id="scene", shot_id="shot-1", video_slug="v")
        slot = candidate_set.slot(index)
        slot.status, slot.asset_id = "done", asset_id
    assert select_first_valid(candidate_set, registry) == candidate_set.slot(0).asset_id


def test_an_invalid_earlier_candidate_is_skipped_in_favour_of_the_next_valid_one(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    candidate_set = VisualCandidateSet("shot-1", "req", "fp", "abc1230123456789abcdef0123456789", "phase9-v1", 2)
    candidate_set.slot(0).status = "failed"
    image1 = _write_png(tmp_path / "c1.png")
    asset_id_1 = registry.record_generated(generation_key="abc1230123456789abcdef0123456789", local_path=image1, is_fresh_generation=True,
        profile_id="p", profile_version="1", seed=candidate_seed("abc1230123456789abcdef0123456789", 1), scene_id="scene", shot_id="shot-1", video_slug="v")
    slot1 = candidate_set.slot(1)
    slot1.status, slot1.asset_id = "done", asset_id_1
    assert select_first_valid(candidate_set, registry) == asset_id_1


def test_zero_valid_candidates_yields_no_selection(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    candidate_set = VisualCandidateSet("shot-1", "req", "fp", "abc1230123456789abcdef0123456789", "phase9-v1", 2)
    candidate_set.slot(0).status = "failed"
    candidate_set.slot(1).status = "failed"
    assert select_first_valid(candidate_set, registry) is None


def test_a_done_slot_whose_registry_record_disappeared_is_not_valid(tmp_path):
    registry = AssetRegistry(tmp_path / "registry.json")
    candidate_set = VisualCandidateSet("shot-1", "req", "fp", "abc1230123456789abcdef0123456789", "phase9-v1", 1)
    slot = candidate_set.slot(0)
    slot.status, slot.asset_id = "done", "ast_missing"
    assert candidate_is_valid(slot, registry) is False


def test_unknown_selection_policy_name_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        resolve_selection_policy("best_of_n_vlm")
