"""Test lưu/tải template cấu hình render (đặt tên, lưu global)."""

from __future__ import annotations

import pytest

from ytb_pipeline.webui import templates_store as ts


@pytest.fixture(autouse=True)
def _isolate_templates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ts.Path, "home", staticmethod(lambda: tmp_path))
    yield


def test_save_and_load_template_roundtrip() -> None:
    ts.save_template(
        "skincare_9x16",
        {
            "aspect_ratio": "9:16",
            "fit_mode": "crop",
            "duration_mode": "voice_silence",
            "mode": "random",
            "edit_profile_name": "beauty_skincare",
            "ignored_extra_field": "should not be saved",
        },
    )

    loaded = ts.load_template("skincare_9x16")

    assert loaded == {
        "aspect_ratio": "9:16",
        "fit_mode": "crop",
        "duration_mode": "voice_silence",
        "mode": "random",
        "edit_profile_name": "beauty_skincare",
    }


def test_list_templates_returns_sorted_names() -> None:
    ts.save_template("b_template", {"aspect_ratio": "16:9"})
    ts.save_template("a_template", {"aspect_ratio": "9:16"})

    assert ts.list_templates() == ["a_template", "b_template"]


def test_load_missing_template_raises() -> None:
    with pytest.raises(FileNotFoundError):
        ts.load_template("does_not_exist")


@pytest.mark.parametrize("bad_name", ["", "  ", "..", ".", "a/b", "a\\b"])
def test_save_template_rejects_invalid_names(bad_name: str) -> None:
    with pytest.raises(ValueError):
        ts.save_template(bad_name, {"aspect_ratio": "16:9"})


def test_save_template_overwrites_existing() -> None:
    ts.save_template("t", {"aspect_ratio": "16:9"})
    ts.save_template("t", {"aspect_ratio": "9:16"})
    assert ts.load_template("t")["aspect_ratio"] == "9:16"
