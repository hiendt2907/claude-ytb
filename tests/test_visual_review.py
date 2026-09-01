"""Phase 13 durable operator-review domain and process-safe store."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from ytb_pipeline.render.visual_assets import VisualRequest
from ytb_pipeline.render.visual_review import (
    MAX_MANUAL_OVERRIDES_PER_REVIEW,
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
    """Ngân sách tính theo CÔNG ĐÃ TIÊU, không theo số lần gõ lệnh.

    Bất biến cần giữ là operator không đốt được vô hạn lượt sinh ảnh. Chặn ngay
    từ lần gõ thứ hai thì chặt hơn mức đó: một instruction gõ sai — chưa sinh
    ảnh nào — cũng khoá review vĩnh viễn, mà không có CLI reset ở mức node và
    `abandon` thì dừng hẳn pipeline. Ca đó đã gặp trên hàng thật.
    """
    store = VisualReviewStore(tmp_path / "visual_review.json")
    pending = _pending(store)
    store.submit_manual_regenerate(
        pending.review_id,
        request=_request(),
        instruction="Bỏ đám đông phía sau",
    )
    # Chưa tiêu công thì sửa được lệnh.
    store.submit_manual_regenerate(
        pending.review_id,
        request=_request(),
        instruction="Đổi góc máy",
    )

    # Judge chi ra sai o dau roi operator sua lai — do la workflow cua chinh
    # he thong, nen bound phai HUU HAN chu khong phai BANG MOT. Do tren hang
    # that: lan sua dau tien cua operator cho character=1.000 composition=0.900
    # continuity=1.000 va chi hong dung mot menh de hanh dong; khong cho sua
    # tiep thi shot chet han du dang rat gan.
    for attempt in range(MAX_MANUAL_OVERRIDES_PER_REVIEW - 1):
        store.initialize_manual_attempt(
            pending.review_id,
            request_fingerprint=_request().request_fingerprint,
            candidate_count=1,
            generation_key="a1b2c3d4e5f60718",
        )
        store.submit_manual_regenerate(
            pending.review_id,
            request=_request(),
            instruction=f"Sua lan {attempt + 2}",
        )

    store.initialize_manual_attempt(
        pending.review_id,
        request_fingerprint=_request().request_fingerprint,
        candidate_count=1,
        generation_key="a1b2c3d4e5f60718",
    )
    with pytest.raises(VisualReviewError, match="đã được sử dụng"):
        store.submit_manual_regenerate(
            pending.review_id,
            request=_request(),
            instruction="Vuot tran",
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


def test_operator_instruction_can_replace_an_unrenderable_intent():
    """Cửa thoát của operator không mở được khi visual_intent bất khả thi.

    `derive_manual_visual_request` NỐI THÊM instruction vào visual_intent gốc,
    nên operator chỉ thêm được ràng buộc, không bao giờ rút được một ràng buộc.

    Đo trên hàng thật: một shot khai "An đứng gần bàn, tay cầm khay gỗ, ...".
    Image model không dựng nổi cái khay trên tay; Judge chấm
    semantic=0.5 character=1.0 composition=1.0 continuity=1.0 với
    hard_failures=missing_required_object trên CẢ 8 candidate qua 2 vòng —
    mọi mệnh đề khác đều đạt, hỏng đúng cái khay. Operator ghi override "hai
    tay buông tự nhiên, không cầm vật gì" thì văn bản đem chấm thành mâu thuẫn
    với chính nó ("tay cầm khay gỗ" + "không cầm vật gì") và vẫn hard-fail.

    Lối duy nhất còn lại là `abandon`, tức bỏ hẳn shot. Operator phải rút được
    một mệnh đề bất khả thi, nếu không cổng review chỉ là ngõ cụt.
    """
    from ytb_pipeline.render.visual_assets import VisualRequest
    from ytb_pipeline.render.visual_review import (
        ManualVisualOverride, derive_manual_visual_request,
    )

    request = VisualRequest(
        request_id="vr_x", request_fingerprint="fp_base",
        scene_id="scene-001", shot_id="scene-001-shot-00",
        visual_intent="An đứng gần bàn, tay cầm khay gỗ, Minh ngồi cúi nhìn màn hình.",
        characters=("an", "minh"), dimensions=(1344, 768),
        resolution_kind="image", semantic_constraints=(),
    )
    common = dict(
        override_id="mvo_x", shot_id=request.shot_id,
        base_request_fingerprint="fp_base", override_fingerprint="fp_o",
        derived_request_id="vr_d", derived_request_fingerprint="fp_d",
    )

    appended = derive_manual_visual_request(
        request, ManualVisualOverride(instruction="Thêm ánh sáng sớm.", **common),
    )
    assert "tay cầm khay gỗ" in appended.visual_intent, "mặc định vẫn phải giữ ngữ cảnh cảnh"
    assert "Thêm ánh sáng sớm." in appended.visual_intent

    replaced = derive_manual_visual_request(
        request,
        ManualVisualOverride(
            instruction="An đứng cạnh bàn, hai tay buông tự nhiên. Minh cúi nhìn laptop.",
            replaces_intent=True, **common,
        ),
    )
    assert "khay gỗ" not in replaced.visual_intent, "phải rút được mệnh đề bất khả thi"
    assert "hai tay buông tự nhiên" in replaced.visual_intent


def test_manual_override_json_without_the_new_field_still_loads():
    """Override đã ghi trên đĩa từ trước không có trường mới — phải load được."""
    from ytb_pipeline.render.visual_review import ManualVisualOverride

    legacy = {
        "override_id": "mvo_old", "shot_id": "s", "base_request_fingerprint": "b",
        "instruction": "i", "override_fingerprint": "o",
        "derived_request_id": "d", "derived_request_fingerprint": "df",
    }
    override = ManualVisualOverride.from_dict(legacy)
    assert override.replaces_intent is False


def test_operator_can_correct_an_override_that_has_not_generated_anything_yet(tmp_path):
    """Gõ sai instruction là mất luôn cửa thoát, dù chưa tốn một ảnh nào.

    `submit_manual_regenerate` từ chối mọi override thứ hai, nên một instruction
    sai — kể cả sai do chính cơ chế lúc đó chưa rút được mệnh đề — sẽ khoá review
    vĩnh viễn. Không có CLI reset ở mức node, nên lối duy nhất còn lại là
    `abandon`, mà `abandon` dừng hẳn pipeline chứ không bỏ qua shot.

    Ngân sách vẫn phải chặn override thứ hai khi cái đầu ĐÃ tiêu công (đang chạy
    hoặc đã sinh candidate). Chỉ cái chưa động tới mới được sửa.
    """
    from ytb_pipeline.render.visual_assets import VisualRequest
    from ytb_pipeline.render.visual_review import (
        ReviewReason, VisualReviewError, VisualReviewStore,
    )

    request = VisualRequest(
        request_id="vr_x", request_fingerprint="fp_base",
        scene_id="scene-001", shot_id="scene-001-shot-00",
        visual_intent="An đứng gần bàn, tay cầm khay gỗ.",
        characters=("an",), dimensions=(1344, 768),
        resolution_kind="image", semantic_constraints=(),
    )
    store = VisualReviewStore(tmp_path / "visual_review.json")
    entry = store.ensure_pending(
        request, reason=ReviewReason.SEMANTIC_RECOVERY_EXHAUSTED,
        candidate_asset_ids=("ast_a",), evaluation_fingerprint="ef",
        recovery_status="exhausted",
    )

    store.submit_manual_regenerate(
        entry.review_id, request=request, instruction="hướng dẫn gõ nhầm",
    )
    corrected = store.submit_manual_regenerate(
        entry.review_id, request=request,
        instruction="An đứng cạnh bàn, hai tay buông tự nhiên.", replaces_intent=True,
    )
    assert corrected.manual_override is not None
    assert corrected.manual_override.replaces_intent is True
    assert "hai tay buông" in corrected.manual_override.instruction

    # Sửa khi chưa tiêu công thì KHÔNG được tính vào ngân sách.
    assert corrected.manual_override_spent == 0

    # Còn khi đã sinh ảnh rồi, lần thay tiếp theo mới bị tính.
    store.initialize_manual_attempt(
        entry.review_id, request_fingerprint=request.request_fingerprint,
        candidate_count=1, generation_key="a1b2c3d4e5f60718",
    )
    after_spend = store.submit_manual_regenerate(
        entry.review_id, request=request, instruction="lần sửa sau khi đã sinh ảnh",
    )
    assert after_spend.manual_override_spent == 1
