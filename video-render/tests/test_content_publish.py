"""Test content/publish.py — mock get_youtube_client hoàn toàn, không gọi API thật."""

from __future__ import annotations

import pytest

from ytb_pipeline.content import publish as pub


class _FakeRequest:
    def __init__(self, response: dict):
        self._response = response

    def next_chunk(self):
        return None, self._response


class _FakeVideosResource:
    def __init__(self, response: dict):
        self._response = response
        self.insert_calls: list[dict] = []

    def insert(self, part, body, media_body):
        self.insert_calls.append(body)
        return _FakeRequest(self._response)


class _FakeThumbnailsResource:
    def __init__(self):
        self.set_calls: list[str] = []

    def set(self, videoId, media_body):
        self.set_calls.append(videoId)

        class _Exec:
            def execute(self_inner):
                return {}

        return _Exec()


class _FakeYoutubeClient:
    def __init__(self, response: dict):
        self.videos_resource = _FakeVideosResource(response)
        self.thumbnails_resource = _FakeThumbnailsResource()

    def videos(self):
        return self.videos_resource

    def thumbnails(self):
        return self.thumbnails_resource


def test_publish_video_raises_when_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pub.publish_video(tmp_path / "missing.mp4", "t", "d")


def test_publish_video_uploads_and_returns_result(monkeypatch, tmp_path):
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")

    fake_client = _FakeYoutubeClient({"id": "abc123"})
    monkeypatch.setattr(pub, "get_youtube_client", lambda: fake_client, raising=False)

    import ytb_pipeline.content.youtube_auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_youtube_client", lambda: fake_client)

    class _FakeMediaFileUpload:
        def __init__(self, path, **kwargs):
            self.path = path

    monkeypatch.setattr(
        "googleapiclient.http.MediaFileUpload", _FakeMediaFileUpload, raising=False
    )

    result = pub.publish_video(video_path, "Tiêu đề", "Mô tả", ("a", "b"), publish_at="2026-07-10T09:00:00Z")

    assert result.youtube_id == "abc123"
    assert result.url == "https://youtu.be/abc123"
    body = fake_client.videos_resource.insert_calls[0]
    assert body["snippet"]["title"] == "Tiêu đề"
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-07-10T09:00:00Z"


def test_publish_video_sets_thumbnail_when_provided(monkeypatch, tmp_path):
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"fake")

    fake_client = _FakeYoutubeClient({"id": "xyz"})

    import ytb_pipeline.content.youtube_auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_youtube_client", lambda: fake_client)

    class _FakeMediaFileUpload:
        def __init__(self, path, **kwargs):
            self.path = path

    monkeypatch.setattr(
        "googleapiclient.http.MediaFileUpload", _FakeMediaFileUpload, raising=False
    )

    pub.publish_video(video_path, "t", "d", thumbnail_path=thumb_path)

    assert fake_client.thumbnails_resource.set_calls == ["xyz"]


def test_publish_video_thumbnail_failure_does_not_raise(monkeypatch, tmp_path):
    video_path = tmp_path / "out.mp4"
    video_path.write_bytes(b"fake")
    thumb_path = tmp_path / "thumb.jpg"
    thumb_path.write_bytes(b"fake")

    fake_client = _FakeYoutubeClient({"id": "xyz"})

    def _boom(video_id, media_body):
        raise RuntimeError("kênh chưa verify")

    fake_client.thumbnails_resource.set = _boom  # type: ignore[method-assign]

    import ytb_pipeline.content.youtube_auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_youtube_client", lambda: fake_client)

    class _FakeMediaFileUpload:
        def __init__(self, path, **kwargs):
            self.path = path

    monkeypatch.setattr(
        "googleapiclient.http.MediaFileUpload", _FakeMediaFileUpload, raising=False
    )

    result = pub.publish_video(video_path, "t", "d", thumbnail_path=thumb_path)
    assert result.youtube_id == "xyz"
