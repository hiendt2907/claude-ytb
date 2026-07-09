"""Test pexels_fetch — mock urllib.request.urlopen, không gọi mạng thật."""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from ytb_pipeline.content import pexels_fetch as pf
from ytb_pipeline.content.models import Script, ScriptSegment


def _script() -> Script:
    return Script(
        title="t",
        description="",
        segments=(
            ScriptSegment(narration="a", visual_keywords=("sunrise", "walk")),
            ScriptSegment(narration="b", visual_keywords=("city",)),
        ),
    )


def _search_response(n: int) -> bytes:
    videos = [
        {
            "video_files": [
                {"file_type": "video/mp4", "width": 1080, "height": 1920,
                 "link": f"https://cdn.example/clip{i}.mp4"}
            ]
        }
        for i in range(n)
    ]
    return json.dumps({"videos": videos}).encode()


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _no_real_key(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "fake-key")


def test_fetch_scenes_raises_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="PEXELS_API_KEY"):
        pf.fetch_scenes(_script(), tmp_path)


def test_fetch_scenes_creates_scene_dirs_with_candidates(monkeypatch, tmp_path):
    def fake_urlopen(req, timeout=None):
        if "search" in req.full_url:
            return _FakeResponse(_search_response(5))
        return _FakeResponse(b"fake-video-bytes", headers={"Content-Length": "16"})

    monkeypatch.setattr(pf.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(pf, "CACHE_DIR", tmp_path / "cache")

    scene_dirs = pf.fetch_scenes(_script(), tmp_path / "scenes", candidates_per_scene=3)

    assert len(scene_dirs) == 2
    scene0 = tmp_path / "scenes" / "scene_00"
    assert scene0.is_dir()
    candidates = sorted(p.name for p in scene0.iterdir())
    assert candidates == ["1.1.mp4", "1.2.mp4", "1.3.mp4"]
    assert all(p.stat().st_size > 0 for p in scene0.iterdir())


def test_fetch_scenes_raises_when_no_video_found(monkeypatch, tmp_path):
    def fake_urlopen(req, timeout=None):
        return _FakeResponse(json.dumps({"videos": []}).encode())

    monkeypatch.setattr(pf.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="không có B-roll"):
        pf.fetch_scenes(_script(), tmp_path / "scenes")


def test_download_cached_skips_second_download(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResponse(b"1234", headers={"Content-Length": "4"})

    monkeypatch.setattr(pf.urllib.request, "urlopen", fake_urlopen)

    p1 = pf._download_cached("https://cdn.example/x.mp4")
    p2 = pf._download_cached("https://cdn.example/x.mp4")

    assert p1 == p2
    assert len(calls) == 1
