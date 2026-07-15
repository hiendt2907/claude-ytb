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
        description=("Ví dụ đời thường giúp giải thích cơ chế tâm lý này rõ ràng, "
                     "kèm một hành động nhỏ người xem có thể áp dụng ngay hôm nay."),
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


# ── _build_hashtags / _build_seo_tags ────────────────────────────────────────
def test_build_hashtags_uses_only_content_relevant_terms():
    video = _video(tags=("a", "b", "c", "d"))
    hashtags = uploader._build_hashtags(video, is_short=False)
    assert hashtags[:4] == ["#a", "#b", "#c", "#d"]
    assert "#giảitrí" not in hashtags
    assert "#memeviệt" not in hashtags
    assert len(hashtags) <= uploader.HASHTAG_LIMIT


def test_build_hashtags_shorts_always_first():
    video = _video(tags=("a", "b"))
    hashtags = uploader._build_hashtags(video, is_short=True)
    assert hashtags[:3] == ["#Shorts", "#a", "#b"]
    assert "#youtubeshorts" in hashtags


def test_build_hashtags_dedupes_case_insensitive():
    video = _video(tags=("Shorts", "a"))
    hashtags = uploader._build_hashtags(video, is_short=True)
    assert hashtags.count("#Shorts") == 1
    assert "#a" in hashtags


def test_build_seo_tags_does_not_inject_unrelated_entertainment_terms():
    video = _video(
        title="Người Que Và Cây Nhà",
        description="Một clip người que hài hước.",
        tags=("người que", "giải trí"),
    )

    tags = uploader._build_seo_tags(video, is_short=True)

    assert "người que" in tags
    assert "stickman" not in tags
    assert "hoạt hình" not in tags
    assert "youtube shorts" in tags
    assert len(tags) <= uploader.YOUTUBE_TAG_LIMIT


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
    assert "viral shorts" not in captured_body["snippet"]["tags"]


def test_publish_real_marks_portrait_under_three_minutes_as_short(monkeypatch, tmp_path):
    monkeypatch.setattr(uploader.settings, "dry_run", False)
    monkeypatch.setattr(uploader.settings, "youtube_contains_synthetic_media", True)
    monkeypatch.setattr(uploader.settings, "youtube_publish_at", "")

    video_path = tmp_path / "short.mp4"
    video_path.write_bytes(b"fake")
    video = _video(video_path=video_path, duration_sec=75.0, tags=("giải trí", "người que"))

    captured_body = {}

    class _FakeRequest:
        def next_chunk(self):
            return None, {"id": "SHORTID"}

    class _FakeVideos:
        def insert(self, part, body, media_body):
            captured_body.update(body)
            return _FakeRequest()

    class _FakeYoutube:
        def videos(self):
            return _FakeVideos()

    monkeypatch.setattr(uploader, "_dimensions", lambda path: (1080, 1920))
    monkeypatch.setattr("ytb_pipeline.publish.youtube_auth.get_youtube_client", lambda: _FakeYoutube())
    monkeypatch.setattr("googleapiclient.http.MediaFileUpload", lambda *a, **kw: object())

    result = uploader.publish(video)

    assert result.uploaded is True
    assert "#Shorts" in captured_body["snippet"]["description"]
    assert "#giảitrí" in captured_body["snippet"]["description"]
    assert "#ngườique" in captured_body["snippet"]["description"]
    assert "stickman" not in captured_body["snippet"]["tags"]


def test_publish_real_assigns_configured_playlist(monkeypatch, tmp_path):
    monkeypatch.setattr(uploader.settings, "dry_run", False)
    monkeypatch.setattr(uploader.settings, "youtube_publish_at", "")
    monkeypatch.setattr(uploader.settings, "youtube_playlist_id", "PLAYLIST")
    path = tmp_path / "video.mp4"
    path.write_bytes(b"fake")
    calls = []

    class Request:
        def next_chunk(self): return None, {"id": "VIDEO"}
    class Videos:
        def insert(self, **_kwargs): return Request()
    class PlaylistItems:
        def insert(self, **kwargs): calls.append(kwargs); return type("R", (), {"execute": lambda self: {}})()
    class Youtube:
        def videos(self): return Videos()
        def playlistItems(self): return PlaylistItems()

    monkeypatch.setattr(uploader, "_dimensions", lambda _path: (1920, 1080))
    monkeypatch.setattr("ytb_pipeline.publish.youtube_auth.get_youtube_client", lambda: Youtube())
    monkeypatch.setattr("googleapiclient.http.MediaFileUpload", lambda *a, **kw: object())
    uploader.publish(_video(video_path=path))

    assert calls[0]["body"]["snippet"]["playlistId"] == "PLAYLIST"
