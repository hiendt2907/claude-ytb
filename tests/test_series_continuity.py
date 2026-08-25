"""A series must remember what already aired.

The profile's continuity ledger was read into the generation prompt but never
written back: `current_episode` stayed 0 forever, so episode 2 would be written
as if episode 1 had not happened.  The script itself declares what changed; the
write-back is then a pure function over that declaration.
"""

from __future__ import annotations

import json

import pytest

from ytb_pipeline.ideation.continuity import (
    ContinuityError,
    apply_episode,
    episode_from_payload,
)


def _ledger() -> dict:
    return {
        "series": "ban-so-6",
        "season": 1,
        "current_episode": 0,
        "immutable_facts": {"minh": {"age": 29}},
        "episodes": [],
    }


def _declaration() -> dict:
    return {
        "episode_summary": "Minh sắp lại đầu mục thay vì viết, và gửi bản chưa hoàn chỉnh.",
        "character_changes": {"minh": "Chấp nhận gửi một bản chưa gọn."},
        "threads_opened": ["Chị Hương chưa phản hồi bản đề xuất."],
        "threads_closed": [],
    }


def test_apply_episode_advances_the_counter_and_appends_a_record():
    ledger = apply_episode(
        _ledger(),
        slug="ban-so-6-bay-lan-mo-laptop",
        title="Bảy Lần Mở Laptop",
        declaration=_declaration(),
        published_at="2026-08-26T06:00:00+07:00",
        url="https://youtu.be/abc",
    )

    assert ledger["current_episode"] == 1
    assert len(ledger["episodes"]) == 1
    record = ledger["episodes"][0]
    assert record["episode"] == 1
    assert record["slug"] == "ban-so-6-bay-lan-mo-laptop"
    assert record["url"] == "https://youtu.be/abc"
    assert record["character_changes"] == {"minh": "Chấp nhận gửi một bản chưa gọn."}
    assert record["threads_opened"] == ["Chị Hương chưa phản hồi bản đề xuất."]


def test_apply_episode_does_not_mutate_the_original_ledger():
    original = _ledger()

    apply_episode(
        original,
        slug="s",
        title="t",
        declaration=_declaration(),
        published_at="2026-08-26T06:00:00+07:00",
        url="",
    )

    assert original["current_episode"] == 0
    assert original["episodes"] == []


def test_reapplying_the_same_slug_is_idempotent():
    """A resumed publish must not count one episode twice."""
    first = apply_episode(
        _ledger(), slug="s", title="t", declaration=_declaration(),
        published_at="2026-08-26T06:00:00+07:00", url="",
    )

    second = apply_episode(
        first, slug="s", title="t", declaration=_declaration(),
        published_at="2026-08-26T06:00:00+07:00", url="",
    )

    assert second["current_episode"] == 1
    assert len(second["episodes"]) == 1


def test_open_thread_is_removed_when_a_later_episode_closes_it():
    first = apply_episode(
        _ledger(), slug="ep1", title="t", declaration=_declaration(),
        published_at="2026-08-26T06:00:00+07:00", url="",
    )
    assert first["open_threads"] == ["Chị Hương chưa phản hồi bản đề xuất."]

    second = apply_episode(
        first, slug="ep2", title="t2",
        declaration={
            "episode_summary": "Chị Hương trả lời.",
            "character_changes": {},
            "threads_opened": [],
            "threads_closed": ["Chị Hương chưa phản hồi bản đề xuất."],
        },
        published_at="2026-08-27T06:00:00+07:00", url="",
    )

    assert second["open_threads"] == []


def test_episode_from_payload_rejects_a_declaration_that_is_not_an_object():
    with pytest.raises(ContinuityError):
        episode_from_payload({"continuity": "xong rồi"})


def test_episode_from_payload_returns_none_when_the_script_declares_nothing():
    assert episode_from_payload({"slug": "s"}) is None


def test_character_changes_must_name_someone(monkeypatch):
    with pytest.raises(ContinuityError):
        episode_from_payload({"continuity": {
            "episode_summary": "x",
            "character_changes": {"": "y"},
            "threads_opened": [],
            "threads_closed": [],
        }})


def test_story_generation_schema_requires_a_continuity_declaration():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.ideation.generation_schema import script_generation_schema

    schema = script_generation_schema(
        "short", content_profile=load_content_profile("ban-so-6")
    )

    assert "continuity" in schema["required"]
    assert set(schema["properties"]["continuity"]["required"]) == {
        "episode_summary", "character_changes", "threads_opened", "threads_closed",
    }


def test_explainer_schema_has_no_continuity_requirement():
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.ideation.generation_schema import script_generation_schema

    schema = script_generation_schema(
        "short", content_profile=load_content_profile("one-cup-cafe-6h")
    )

    assert "continuity" not in schema["required"]
