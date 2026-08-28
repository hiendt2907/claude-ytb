"""Phase 13 durable operator-review domain and process-safe store."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from ytb_pipeline.render.visual_assets import VisualRequest
from ytb_pipeline.render.visual_review import (
    MAX_MANUAL_INSTRUCTION_CHARS,
    ReviewDisposition,
    ReviewReason,
    ReviewStatus,
    VisualReviewError,
    VisualReviewStore,
    derive_manual_override,
    derive_manual_visual_request,
    manual_candidate_cache_path,
    manual_candidate_seed,
    manual_generation_key,
)


def _request(fingerprint: str = "request-v1") -> VisualRequest:
    return VisualRequest(
        request_id=f"vr-{fingerprint}",
        request_fingerprint=fingerprint,
        scene_id="scene-001",
        shot_id="shot-001",
        visual_intent="Minh đứng một mình trước cửa quán",
        characters=("minh",),
        dimensions=(1920, 1080),
        resolution_kind="generated_image",
        semantic_constraints=("không có đám đông",),
    )


def _pending(store: VisualReviewStore, *, fingerprint: str = "request-v1"):
    return store.ensure_pending(
        _request(fingerprint),
        reason=ReviewReason.SEMANTIC_RECOVERY_EXHAUSTED,
        candidate_asset_ids=("ast-a", "ast-b"),
        evaluation_fingerprint="eval-1",
        recovery_status="exhausted",
    )


def test_reading_empty_review_store_does_not_create_artifact(tmp_path):
    path = tmp_path / "visual_review.json"

    assert VisualReviewStore(path).entries() == ()
    assert not path.exists()


def test_review_creation_is_idempotent_for_same_semantic_context(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")

    first = _pending(store)
    second = _pending(store)

    assert first.review_id == second.review_id
    assert len(store.entries()) == 1
    assert second.status == ReviewStatus.PENDING
    assert second.candidate_asset_ids == ("ast-a", "ast-b")


def test_changed_request_marks_old_review_stale_and_creates_distinct_review(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")
    old = _pending(store)

    store.mark_stale_for_changed_request("shot-001", "request-v2")
    new = _pending(store, fingerprint="request-v2")

    assert store.get(old.review_id).status == ReviewStatus.STALE
    assert new.review_id != old.review_id
    assert store.current_for_shot("shot-001").review_id == new.review_id


def test_manual_override_instruction_is_non_empty_and_bounded():
    with pytest.raises(VisualReviewError, match="không được rỗng"):
        derive_manual_override(_request(), "   ")
    with pytest.raises(VisualReviewError, match=str(MAX_MANUAL_INSTRUCTION_CHARS)):
        derive_manual_override(_request(), "x" * (MAX_MANUAL_INSTRUCTION_CHARS + 1))


def test_manual_override_has_stable_identity_and_keeps_base_request_immutable():
    base = _request()
    instruction = "Giữ Minh một mình ở tiền cảnh. Bỏ đám đông phía sau."

    first = derive_manual_override(base, instruction)
    second = derive_manual_override(base, instruction)
    derived = derive_manual_visual_request(base, first)

    assert first == second
    assert first.base_request_fingerprint == base.request_fingerprint
    assert derived.request_fingerprint == first.derived_request_fingerprint
    assert derived.request_fingerprint != base.request_fingerprint
    assert derived.request_id != base.request_id
    assert base.visual_intent == "Minh đứng một mình trước cửa quán"
    assert instruction in derived.visual_intent


def test_manual_generation_identity_seed_and_cache_do_not_collide_with_automation(tmp_path):
    override = derive_manual_override(_request(), "Bỏ đám đông")
    key = manual_generation_key("automated-generation-key", override)

    assert key != "automated-generation-key"
    assert manual_candidate_seed(key, 0) != manual_candidate_seed(key, 1)
    assert manual_candidate_cache_path(tmp_path, key, 0) != tmp_path / f"{key}.png"
    assert ".manual-candidate-00.png" in manual_candidate_cache_path(tmp_path, key, 0).name


def test_submit_accept_persists_explicit_operator_disposition(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")
    pending = _pending(store)

    resolved = store.resolve_accept_existing(
        pending.review_id,
        request_fingerprint="request-v1",
        asset_id="ast-b",
    )
    loaded = VisualReviewStore(store.path).get(pending.review_id)

    assert resolved.status == ReviewStatus.RESOLVED
    assert resolved.disposition == ReviewDisposition.ACCEPT_EXISTING
    assert resolved.selected_asset_id == "ast-b"
    assert loaded == resolved


def test_manual_regenerate_disposition_persists_before_generation(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")
    pending = _pending(store)

    updated = store.submit_manual_regenerate(
        pending.review_id,
        request=_request(),
        instruction="Bỏ đám đông phía sau",
    )

    assert updated.status == ReviewStatus.PENDING
    assert updated.disposition == ReviewDisposition.MANUAL_REGENERATE
    assert updated.manual_override is not None
    assert updated.manual_override.status == "pending"
    assert VisualReviewStore(store.path).get(pending.review_id) == updated


def test_only_one_manual_override_is_allowed_for_one_review(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")
    pending = _pending(store)
    store.submit_manual_regenerate(
        pending.review_id,
        request=_request(),
        instruction="Bỏ đám đông phía sau",
    )

    with pytest.raises(VisualReviewError, match="đã được sử dụng"):
        store.submit_manual_regenerate(
            pending.review_id,
            request=_request(),
            instruction="Đổi góc máy",
        )


def test_abandon_is_durable_and_distinct_from_failure(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")
    pending = _pending(store)

    abandoned = store.abandon(pending.review_id, request_fingerprint="request-v1")

    assert abandoned.status == ReviewStatus.ABANDONED
    assert abandoned.disposition == ReviewDisposition.ABANDON
    assert abandoned.last_error is None
    assert VisualReviewStore(store.path).get(pending.review_id) == abandoned


def test_stale_review_rejects_every_disposition(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")
    pending = _pending(store)
    store.mark_stale_for_changed_request("shot-001", "request-v2")

    with pytest.raises(VisualReviewError, match="stale"):
        store.resolve_accept_existing(
            pending.review_id,
            request_fingerprint="request-v1",
            asset_id="ast-a",
        )


def test_concurrent_operator_updates_are_atomic_and_only_one_wins(tmp_path):
    store = VisualReviewStore(tmp_path / "visual_review.json")
    pending = _pending(store)

    def accept():
        return store.resolve_accept_existing(
            pending.review_id,
            request_fingerprint="request-v1",
            asset_id="ast-a",
        )

    def abandon():
        return store.abandon(pending.review_id, request_fingerprint="request-v1")

    outcomes: list[object] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(accept), pool.submit(abandon))
        for future in futures:
            try:
                outcomes.append(future.result())
            except VisualReviewError as exc:
                outcomes.append(exc)

    winners = [item for item in outcomes if not isinstance(item, Exception)]
    assert len(winners) == 1
    final = store.get(pending.review_id)
    assert final.status in {ReviewStatus.RESOLVED, ReviewStatus.ABANDONED}
    assert len(store.entries()) == 1
