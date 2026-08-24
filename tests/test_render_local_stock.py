"""Rollback 2026-08-24 (xem docs/TOOL_UPGRADE_PLAN.md): render production
quay lại `ai` (compose_ai, B-roll thật) nhưng LOCAL-ONLY — asset lấy từ
AssetCatalog/cache local đã có sẵn, KHÔNG gọi Pexels online,
KHÔNG cần PEXELS_API_KEY, và KHÔNG fallback âm thầm sang motion/slide."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ytb_pipeline.pkg.models import Segment, Voiceover


def _make_audio(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds:.3f}",
         "-ar", "44100", "-ac", "2", "-b:a", "128k", str(path)],
        capture_output=True, check=True,
    )


def _make_local_broll(path: Path, seconds: float = 3.0) -> None:
    """1 clip B-roll local giả lập — đóng vai 'asset Pexels đã tải sẵn trên Mac'."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:size=480x854:duration={seconds:.3f}:rate=25",
         "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=True,
    )


def _write_catalog(catalog_path: Path, *, asset_id: str, local_path: Path,
                   orientation: str, topics: list[str]) -> None:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps({
        "assets": {
            asset_id: {
                "asset_id": asset_id,
                "source": "pexels",
                "license": "Pexels License",
                "source_url": f"https://example.test/{asset_id}",
                "local_path": str(local_path),
                "topics": topics,
                "orientation": orientation,
                "duration_sec": 3.0,
                "uses": [],
            }
        }
    }), encoding="utf-8")


def _segment(tmp_path: Path, index: int, *, duration: float, broll: str = "van phong may tinh") -> Segment:
    audio = tmp_path / f"seg_{index:02d}.mp3"
    _make_audio(audio, duration)
    return Segment(
        caption="Đoạn kịch bản",
        narration="Đoạn kịch bản",
        broll=broll,
        audio_path=audio,
        duration_sec=duration,
    )


def _voiceover(segments: tuple[Segment, ...]) -> Voiceover:
    return Voiceover(
        topic="chu de test",
        title="Video Local Stock Demo",
        description="mo ta",
        video_type="short",
        segments=segments,
        audio_path=segments[0].audio_path,
        duration_sec=sum(s.duration_sec for s in segments),
    )


def _configure_local_only(monkeypatch, tmp_path, *, catalog_path: Path):
    from ytb_pipeline.config.settings import settings

    monkeypatch.setattr(settings, "orientation", "portrait")
    monkeypatch.setattr(settings, "broll_strategy", "pexels")
    monkeypatch.setattr(settings, "broll_allow_downloads", False)
    monkeypatch.setattr(settings, "pexels_api_key", "")
    monkeypatch.setattr(settings, "asset_catalog_path", catalog_path)

    from ytb_pipeline.render import stock

    monkeypatch.setattr(stock, "CACHE_DIR", tmp_path / "broll_cache")


def _forbid_network(monkeypatch):
    """Mọi entrypoint network Pexels phải raise nếu bị gọi — chứng minh
    local-only path không bao giờ chạm mạng."""
    import urllib.request

    from ytb_pipeline.render import stock

    def _forbidden(*_a, **_kw):
        raise AssertionError("local-only render không được gọi network/Pexels")

    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)
    monkeypatch.setattr(stock, "_search", _forbidden)
    monkeypatch.setattr(stock, "_search_links", _forbidden)
    monkeypatch.setattr(stock, "_download", _forbidden)


# ---------------------------------------------------------------------------
# 1. Default provider — ai
# ---------------------------------------------------------------------------

def test_default_render_provider_is_ai():
    from ytb_pipeline.config.settings import settings

    assert settings.render_provider == "ai"


def test_motion_provider_removed_from_registry():
    from ytb_pipeline.providers.registry import get_render_provider

    with pytest.raises(ValueError):
        get_render_provider("motion")


def test_get_render_provider_defaults_to_ai_when_unset(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.registry import get_render_provider
    from ytb_pipeline.providers.render.ai_provider import AiRenderProvider

    monkeypatch.setattr(settings, "render_provider", "ai")
    provider = get_render_provider()

    assert isinstance(provider, AiRenderProvider)


# ---------------------------------------------------------------------------
# 2. AiRenderProvider.is_available() — không gắn cứng API key
# ---------------------------------------------------------------------------

def test_ai_provider_available_local_only_without_key(monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.providers.render.ai_provider import AiRenderProvider

    monkeypatch.setattr(settings, "broll_strategy", "pexels")
    monkeypatch.setattr(settings, "broll_allow_downloads", False)
    monkeypatch.setattr(settings, "pexels_api_key", "")

    assert AiRenderProvider().is_available() is True


# ---------------------------------------------------------------------------
# 3. Render thật bằng local asset — không network, không API key
# ---------------------------------------------------------------------------

def test_render_video_ai_uses_local_catalog_asset_without_network_or_key(tmp_path, monkeypatch):
    from ytb_pipeline.render import compose_ai

    broll = tmp_path / "library" / "office.mp4"
    broll.parent.mkdir(parents=True)
    _make_local_broll(broll)
    catalog_path = tmp_path / "asset_catalog.json"
    _write_catalog(catalog_path, asset_id="office01", local_path=broll,
                   orientation="portrait", topics=["van phong may tinh"])

    _configure_local_only(monkeypatch, tmp_path, catalog_path=catalog_path)
    _forbid_network(monkeypatch)
    monkeypatch.setattr(compose_ai, "OUTPUT_DIR", tmp_path / "output")

    segs = (
        _segment(tmp_path, 0, duration=3.0),
        _segment(tmp_path, 1, duration=3.0),
    )
    voiceover = _voiceover(segs)

    result = compose_ai.render_video_ai(voiceover)

    assert result.video_path is not None and result.video_path.exists()
    assert result.thumbnail_path is not None and result.thumbnail_path.exists()

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(result.video_path)],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "1080x1920"


def test_ai_provider_render_end_to_end_via_registry(tmp_path, monkeypatch):
    """Đường thật pipeline sẽ đi qua: get_render_provider() -> .render()."""
    from ytb_pipeline.providers.registry import get_render_provider
    from ytb_pipeline.render import compose_ai
    from ytb_pipeline.config.settings import settings

    broll = tmp_path / "library" / "office.mp4"
    broll.parent.mkdir(parents=True)
    _make_local_broll(broll)
    catalog_path = tmp_path / "asset_catalog.json"
    _write_catalog(catalog_path, asset_id="office01", local_path=broll,
                   orientation="portrait", topics=["van phong"])

    _configure_local_only(monkeypatch, tmp_path, catalog_path=catalog_path)
    _forbid_network(monkeypatch)
    monkeypatch.setattr(compose_ai, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "render_provider", "ai")

    seg = _segment(tmp_path, 0, duration=2.5)
    voiceover = _voiceover((seg,))

    provider = get_render_provider()
    assert provider.is_available() is True

    import asyncio

    result = asyncio.run(provider.render(voiceover, tmp_path / "output"))

    assert result.video_path is not None and result.video_path.exists()


# ---------------------------------------------------------------------------
# 4. Fail-fast khi thiếu local asset — không fallback âm thầm
# ---------------------------------------------------------------------------

def test_render_fails_fast_with_clear_message_when_no_local_asset(tmp_path, monkeypatch):
    from ytb_pipeline.render import compose_ai

    empty_catalog = tmp_path / "does_not_exist_catalog.json"
    _configure_local_only(monkeypatch, tmp_path, catalog_path=empty_catalog)
    _forbid_network(monkeypatch)
    monkeypatch.setattr(compose_ai, "OUTPUT_DIR", tmp_path / "output")

    seg = _segment(tmp_path, 0, duration=3.0)
    voiceover = _voiceover((seg,))

    with pytest.raises(RuntimeError, match="(?i)broll_allow_downloads"):
        compose_ai.render_video_ai(voiceover)


def test_render_does_not_fall_back_to_slide_when_asset_missing(tmp_path, monkeypatch):
    from ytb_pipeline.render import compose_ai
    from ytb_pipeline.render import compose as slide_module

    def _forbidden(*_a, **_kw):
        raise AssertionError("ai renderer không được âm thầm fallback sang renderer khác")

    monkeypatch.setattr(slide_module, "render_video", _forbidden)

    empty_catalog = tmp_path / "does_not_exist_catalog.json"
    _configure_local_only(monkeypatch, tmp_path, catalog_path=empty_catalog)
    _forbid_network(monkeypatch)
    monkeypatch.setattr(compose_ai, "OUTPUT_DIR", tmp_path / "output")

    seg = _segment(tmp_path, 0, duration=3.0)
    voiceover = _voiceover((seg,))

    with pytest.raises(RuntimeError):
        compose_ai.render_video_ai(voiceover)


# ---------------------------------------------------------------------------
# 5. Batch environment không vô tình bật downloads/network
# ---------------------------------------------------------------------------

def test_settings_defaults_keep_downloads_off_and_no_key_required():
    from ytb_pipeline.config.settings import settings

    assert settings.broll_allow_downloads is False
    assert settings.render_provider == "ai"
    assert settings.broll_strategy == "pexels"
    # PEXELS_API_KEY có thể rỗng hoặc có sẵn trong .env cá nhân — điều bắt buộc
    # là renderer KHÔNG yêu cầu nó khi downloads tắt (đã test riêng ở trên).


def test_fetch_broll_variants_reuses_local_asset_when_dedup_exhausts_catalog(tmp_path, monkeypatch):
    """Catalog chỉ có 1 cảnh local nhưng video có 2 segment (dedup xuyên video
    loại cảnh đã dùng) — local-only phải TÁI DÙNG cảnh đó, không fail-fast,
    vì thư viện thật sự có cảnh phù hợp (chỉ là đã dùng ở segment trước)."""
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.render import stock

    broll = tmp_path / "office.mp4"
    _make_local_broll(broll)
    catalog_path = tmp_path / "asset_catalog.json"
    _write_catalog(catalog_path, asset_id="office01", local_path=broll,
                   orientation="portrait", topics=["van phong"])

    monkeypatch.setattr(settings, "asset_catalog_path", catalog_path)
    monkeypatch.setattr(settings, "broll_allow_downloads", False)
    monkeypatch.setattr(settings, "pexels_api_key", "")
    monkeypatch.setattr(stock, "CACHE_DIR", tmp_path / "cache")
    _forbid_network(monkeypatch)

    used: set[str] = set()
    first = stock.fetch_broll_variants("van phong", 1, min_duration=1.0, landscape=False, exclude=used)
    second = stock.fetch_broll_variants("van phong", 1, min_duration=1.0, landscape=False, exclude=used)

    assert first == [broll]
    assert second == [broll]  # tái dùng, không rỗng, không raise


def test_fetch_broll_variants_never_calls_network_when_downloads_disabled(tmp_path, monkeypatch):
    """batch runner (fetch_broll_variants trực tiếp) cũng phải tôn trọng
    local-only — không phụ thuộc việc gọi qua AiRenderProvider."""
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.render import stock

    broll = tmp_path / "office.mp4"
    _make_local_broll(broll)
    catalog_path = tmp_path / "asset_catalog.json"
    _write_catalog(catalog_path, asset_id="office01", local_path=broll,
                   orientation="portrait", topics=["van phong"])

    monkeypatch.setattr(settings, "asset_catalog_path", catalog_path)
    monkeypatch.setattr(settings, "broll_allow_downloads", False)
    monkeypatch.setattr(settings, "pexels_api_key", "")
    monkeypatch.setattr(stock, "CACHE_DIR", tmp_path / "cache")
    _forbid_network(monkeypatch)

    result = stock.fetch_broll_variants("van phong", 2, min_duration=1.0, landscape=False)

    assert len(result) >= 1
    assert all(p.exists() for p in result)
