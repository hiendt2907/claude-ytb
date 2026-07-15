from __future__ import annotations

import pytest

from ytb_pipeline.pkg.models import RenderedVideo
from ytb_pipeline.publish.validation import MonetizationReviewError, validate_monetization_ready


@pytest.mark.asyncio
async def test_monetization_failure_writes_audit_and_marks_exact_project(tmp_path, monkeypatch):
    from ytb_pipeline.publish import multiplatform
    from ytb_pipeline.config.settings import settings

    video = RenderedVideo(topic="x", title="Title", description="too short", tags=())
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(multiplatform, "mark_needs_review", lambda slug, reason: (slug, reason))
    monkeypatch.setattr(multiplatform, "get_publish_provider", lambda _name: object())

    with pytest.raises(MonetizationReviewError):
        await multiplatform.publish_to_platforms(video, project_id="exact-queue-slug")

    audit = tmp_path / "projects" / "exact-queue-slug" / "monetization_audit.json"
    assert audit.exists()
    assert "description" in audit.read_text(encoding="utf-8")


def test_monetization_gate_rejects_thin_or_absolute_claim_content():
    video = RenderedVideo(
        topic="sức khỏe", title="Chữa khỏi lo âu", description="Chắc chắn chữa khỏi mọi người.",
        tags=(),
    )

    with pytest.raises(MonetizationReviewError):
        validate_monetization_ready(video)


def test_monetization_gate_accepts_original_educational_metadata():
    video = RenderedVideo(
        topic="trì hoãn", title="Vì sao não né việc khó", tags=("tâm lý", "trì hoãn"),
        description=("Ví dụ khi mở laptop rồi cầm điện thoại, não đang né cảm giác mơ hồ. "
                     "Hãy đặt điện thoại ngoài bàn trong mười phút để thử một bước nhỏ."),
    )

    validate_monetization_ready(video)


def test_monetization_gate_requires_substantive_original_narration():
    video = RenderedVideo(
        topic="trì hoãn", title="Vì sao não né việc khó", tags=("tâm lý",),
        description="Một phần giải thích có nguồn và hành động áp dụng cụ thể cho người xem.",
        body="quá ngắn",
    )

    with pytest.raises(MonetizationReviewError, match="narration"):
        validate_monetization_ready(video)
