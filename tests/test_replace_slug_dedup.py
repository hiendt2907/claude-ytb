"""Replacing a slug must not trip the anti-duplication rule with itself.

`--replace-slug` regenerates the script for a slot that already exists, so its
own slug is by definition already in the ledger.  Without an exemption the
dedup gate rejects every replacement — the operator asks to rewrite an episode
and the pipeline answers that the episode already exists.
"""

from __future__ import annotations

from types import SimpleNamespace

from ytb_pipeline.agents import qa_agent


def _script(title: str):
    return SimpleNamespace(
        title=title, topic=title, video_type="short", target_minutes=None,
        content_profile_id="one-cup-cafe-6h", content_profile_version="",
        segments=(SimpleNamespace(narration="x", purpose="situation"),),
    )


def test_dedup_still_rejects_a_genuinely_repeated_topic():
    violations = qa_agent._check_dedup(_script("Bảy lần mở laptop"), ["Bảy lần mở laptop"])

    assert [v["rule"] for v in violations] == ["series_dedup"]


def test_dedup_skips_the_slug_being_replaced():
    violations = qa_agent._check_dedup(
        _script("Bảy lần mở laptop"),
        ["Bảy lần mở laptop"],
        exempt_slugs=("bay-lan-mo-laptop",),
    )

    assert violations == []


def test_exempting_one_slug_does_not_exempt_another():
    violations = qa_agent._check_dedup(
        _script("Bảy lần mở laptop"),
        ["Bảy lần mở laptop"],
        exempt_slugs=("mot-slug-khac",),
    )

    assert [v["rule"] for v in violations] == ["series_dedup"]


def test_derivative_short_skips_semantic_comparison_with_its_exact_source_long():
    violations = qa_agent._check_dedup(
        _script("Im lặng hay nói thật trước con số sai trong cuộc họp"),
        ["Chậm Hơn Trong Cuộc Họp: Im Lặng Hay Nói Thật?"],
        exempt_slugs=("Chậm Hơn Trong Cuộc Họp: Im Lặng Hay Nói Thật?",),
    )

    assert violations == []
