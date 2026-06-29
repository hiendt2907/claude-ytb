"""Test khâu publish: hashtag tự động + khai báo nội dung AI (containsSyntheticMedia)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ytb_pipeline.publish import uploader
from ytb_pipeline.pkg.models import RenderedVideo


def _video(**overrides) -> RenderedVideo:
    defaults = dict(
        topic="t",
        title="Tiêu đề",
        description="Mô tả video.",
        tags=("tâm lý học", "self help", "phát triển bản thân"),
        duration_sec=600.0,
        video_path=None,
        thumbnail_path=None,
    )
    defaults.update(overrides)
    return RenderedVideo(**defaults)


# ── _to_hashtag ───────────────────────────────────────────────────────────────
def test_to_hashtag_strips_spaces_and_keeps_unicode():
    assert uploader._to_hashtag("tâm lý học") == "#tâmlýhọc"


def test_to_hashtag_empty_for_blank_tag():
    assert uploader._to_hashtag("   ") == ""


# ── _build_hashtags ───────────────────────────────────────────────────────────
def test_build_hashtags_caps_at_three():
    video = _video(tags=("a", "b", "c", "d"))
    hashtags = uploader._build_hashtags(video, is_short=False)
    assert hashtags == ["#a", "#b", "#c"]


def test_build_hashtags_shorts_always_first():
    video = _video(tags=("a", "b"))
    hashtags = uploader._build_hashtags(video, is_short=True)
    assert hashtags == ["#Shorts", "#a", "#b"]


def test_build_hashtags_dedupes_case_insensitive():
    video = _video(tags=("Shorts", "a"))
    hashtags = uploader._build_hashtags(video, is_short=True)
    assert hashtags == ["#Shorts", "#a"]


# ── _with_hashtags ────────────────────────────────────────────────────────────
def test_with_hashtags_appends_missing():
    out = uploader._with_hashtags("Mô tả.", ["#a", "#b"])
    assert out == "Mô tả.\n\n#a #b"


def test_with_hashtags_skips_already_present():
    out = uploader._with_hashtags("Mô tả có #a rồi.", ["#a"])
    assert out == "Mô tả có #a rồi."


def test_with_hashtags_noop_when_no_hashtags():
    assert uploader._with_hashtags("Mô tả.", []) == "Mô tả."


# ── publish() dry-run: in đúng hashtag + cờ AI ───────────────────────────────
def test_dry_run_prints_hashtags_and_ai_flag(monkeypatch, capsys):
    monkeypatch.setattr(uploader.settings, "dry_run", True)
    monkeypatch.setattr(uploader.settings, "youtube_contains_synthetic_media", True)
    video = _video()

    uploader.publish(video)

    out = capsys.readouterr().out
    assert "Hashtag:" in out
    assert "#tâmlýhọc" in out
    assert "Made with AI (containsSyntheticMedia): True" in out


# ── publish() thật: body gửi lên API có containsSyntheticMedia + hashtag ────
def test_publish_real_sets_synthetic_media_flag_and_hashtags(monkeypatch, tmp_path):
    monkeypatch.setattr(uploader.settings, "dry_run", False)
    monkeypatch.setattr(uploader.settings, "youtube_contains_synthetic_media", True)
    monkeypatch.setattr(uploader.settings, "youtube_publish_at", "")

    video_path = tmp_path / "v.mp4"
    video_path.write_bytes(b"fake")
    video = _video(video_path=video_path, duration_sec=600.0)

    captured_body = {}

    class _FakeRequest:
        def next_chunk(self):
            return None, {"id": "FAKEID"}

    class _FakeVideos:
        def insert(self, part, body, media_body):
            captured_body.update(body)
            return _FakeRequest()

    class _FakeYoutube:
        def videos(self):
            return _FakeVideos()

    monkeypatch.setattr(uploader, "_dimensions", lambda path: (1920, 1080))
    monkeypatch.setattr("ytb_pipeline.publish.youtube_auth.get_youtube_client", lambda: _FakeYoutube())
    monkeypatch.setattr("googleapiclient.http.MediaFileUpload", lambda *a, **kw: object())

    result = uploader.publish(video)

    assert result.uploaded is True
    assert captured_body["status"]["containsSyntheticMedia"] is True
    assert "#tâmlýhọc" in captured_body["snippet"]["description"]
