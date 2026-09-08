"""Test khâu publish: hashtag tự động + khai báo nội dung AI (containsSyntheticMedia)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ytb_pipeline.publish import uploader
from ytb_pipeline.pkg.models import ContentStrategy, RenderedVideo


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


# ── _published_url_for_slug ───────────────────────────────────────────────────
def test_published_url_for_slug_returns_url_for_done_ok_row(tmp_path):
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "| 2026-07-20 | long-a | Long A | done | ok | https://youtu.be/abc123 — verified. |\n",
        encoding="utf-8",
    )
    assert uploader._published_url_for_slug("long-a", ledger) == "https://youtu.be/abc123"


def test_published_url_for_slug_none_when_not_done(tmp_path):
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "| 2026-07-20 | long-a | Long A | voiceover | running | Tự động: đang chạy |\n",
        encoding="utf-8",
    )
    assert uploader._published_url_for_slug("long-a", ledger) is None


def test_published_url_for_slug_uses_latest_row(tmp_path):
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "| 2026-07-20 | long-a | Long A | done | ok | https://youtu.be/old111 |\n"
        "| 2026-07-25 | long-a | Long A | done | ok | https://youtu.be/new222 |\n",
        encoding="utf-8",
    )
    assert uploader._published_url_for_slug("long-a", ledger) == "https://youtu.be/new222"


def test_published_url_for_slug_missing_ledger_returns_none(tmp_path):
    assert uploader._published_url_for_slug("long-a", tmp_path / "missing.md") is None


# ── _post_cta_comment ─────────────────────────────────────────────────────────
def _strategy(**overrides) -> ContentStrategy:
    defaults = dict(
        format_id="core_answer_first_v1", core_mechanism="m", audience_problem="p",
        angle="a", long_form_slug="long-a", playlist="series", cta_target="long-a",
    )
    defaults.update(overrides)
    return ContentStrategy(**defaults)


def test_post_cta_comment_noop_without_cta_target():
    calls = []

    class Youtube:
        def commentThreads(self):
            calls.append(1)
            raise AssertionError("must not be called without cta_target")

    uploader._post_cta_comment(Youtube(), "VIDEO", _video())

    assert calls == []


def test_post_cta_comment_skips_when_target_not_published(monkeypatch, capsys):
    monkeypatch.setattr(uploader, "_published_url_for_slug", lambda _slug, ledger_path=None: None)
    calls = []

    class Youtube:
        def commentThreads(self):
            calls.append(1)
            raise AssertionError("must not be called when target isn't published")

    video = _video(strategy=_strategy())
    uploader._post_cta_comment(Youtube(), "VIDEO", video)

    assert calls == []
    assert "chưa publish" in capsys.readouterr().out


def test_post_cta_comment_posts_link_and_reminds_manual_pin(monkeypatch, capsys):
    monkeypatch.setattr(
        uploader, "_published_url_for_slug", lambda _slug, ledger_path=None: "https://youtu.be/target1"
    )
    captured = {}

    class Request:
        def execute(self):
            return {}

    class CommentThreads:
        def insert(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class Youtube:
        def commentThreads(self):
            return CommentThreads()

    video = _video(strategy=_strategy())
    uploader._post_cta_comment(Youtube(), "VIDEO123", video)

    assert captured["part"] == "snippet"
    body = captured["body"]
    assert body["snippet"]["videoId"] == "VIDEO123"
    assert "https://youtu.be/target1" in body["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
    out = capsys.readouterr().out
    assert "Đã tự động đăng comment" in out
    assert "ghim tay" in out


def test_post_cta_comment_failure_does_not_raise(monkeypatch, capsys):
    monkeypatch.setattr(
        uploader, "_published_url_for_slug", lambda _slug, ledger_path=None: "https://youtu.be/target1"
    )

    class CommentThreads:
        def insert(self, **_kwargs):
            raise RuntimeError("quota exceeded")

    class Youtube:
        def commentThreads(self):
            return CommentThreads()

    video = _video(strategy=_strategy())
    uploader._post_cta_comment(Youtube(), "VIDEO123", video)  # không raise

    assert "Không đăng được comment CTA" in capsys.readouterr().out


def test_post_cta_comment_failure_emits_durable_warning(monkeypatch):
    monkeypatch.setattr(
        uploader, "_published_url_for_slug", lambda _slug, ledger_path=None: "https://youtu.be/target1"
    )
    warnings: list[str] = []
    monkeypatch.setattr(uploader, "emit_warning", lambda message: warnings.append(message))

    class CommentThreads:
        def insert(self, **_kwargs):
            raise RuntimeError("missing scope")

    class Youtube:
        def commentThreads(self):
            return CommentThreads()

    uploader._post_cta_comment(Youtube(), "VIDEO123", _video(strategy=_strategy()))

    assert len(warnings) == 1
    assert "VIDEO123" in warnings[0]
    assert "CTA" in warnings[0]
