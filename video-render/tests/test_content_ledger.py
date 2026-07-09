"""Test content/ledger.py — dedup theo lịch sử chủ đề đã tạo."""

from __future__ import annotations

from ytb_pipeline.content import ledger


def test_slugify_strips_accents_and_spaces():
    assert ledger.slugify("Thói Quen Dậy Sớm!") == "thoi-quen-day-som"


def test_load_ledger_returns_empty_list_when_file_missing(tmp_path):
    assert ledger.load_ledger(tmp_path / "nope.json") == []


def test_append_then_load_roundtrip(tmp_path):
    path = tmp_path / "ledger.json"

    ledger.append_ledger("Thói quen dậy sớm", "2026-07-09", path=path)
    entries = ledger.load_ledger(path)

    assert len(entries) == 1
    assert entries[0].slug == "thoi-quen-day-som"
    assert entries[0].title == "Thói quen dậy sớm"
    assert entries[0].created_at == "2026-07-09"


def test_is_duplicate_true_when_slug_matches(tmp_path):
    path = tmp_path / "ledger.json"
    ledger.append_ledger("Thói quen dậy sớm", "2026-07-09", path=path)
    entries = ledger.load_ledger(path)

    assert ledger.is_duplicate("Thói Quen Dậy Sớm", entries) is True
    assert ledger.is_duplicate("Chủ đề khác hẳn", entries) is False


def test_filter_new_topics_removes_ledger_and_internal_duplicates(tmp_path):
    path = tmp_path / "ledger.json"
    ledger.append_ledger("Thói quen dậy sớm", "2026-07-09", path=path)
    entries = ledger.load_ledger(path)

    topics = ["Thói quen dậy sớm", "Chủ đề mới A", "Chủ đề mới A", "Chủ đề mới B"]
    kept = ledger.filter_new_topics(topics, entries)

    assert kept == ["Chủ đề mới A", "Chủ đề mới B"]


def test_append_ledger_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "ledger.json"

    ledger.append_ledger("x", "2026-07-09", path=path)

    assert path.exists()
