"""Tests cho VideoProvider — PexelsVideoProvider + WanVideoProvider (Phase 6)."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytb_pipeline.providers.errors import ProviderUnavailableError
from ytb_pipeline.providers.video.disabled_provider import DisabledVideoProvider
from ytb_pipeline.providers.video.pexels_provider import PexelsVideoProvider
from ytb_pipeline.providers.video.wan_provider import WanVideoProvider


# ---------------------------------------------------------------------------
# DisabledVideoProvider
# ---------------------------------------------------------------------------

def test_disabled_video_provider_is_intentional_image_motion_mode(tmp_path):
    p = DisabledVideoProvider()

    ok, detail = p.availability_status()

    assert ok is False
    assert "local_image_motion" in detail
    assert p.is_available() is False
    with pytest.raises(ProviderUnavailableError):
        p.generate("prompt", 5.0, 1080, 1920, tmp_path / "out.mp4")


# ---------------------------------------------------------------------------
# PexelsVideoProvider
# ---------------------------------------------------------------------------

def test_pexels_available_when_api_key_set(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.video.pexels_provider.settings",
                        MagicMock(pexels_api_key="key123"))
    p = PexelsVideoProvider()
    assert p.is_available() is True


def test_pexels_unavailable_when_no_api_key(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.video.pexels_provider.settings",
                        MagicMock(pexels_api_key=""))
    p = PexelsVideoProvider()
    assert p.is_available() is False


def test_pexels_generate_raises_when_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("ytb_pipeline.providers.video.pexels_provider.settings",
                        MagicMock(pexels_api_key=""))
    p = PexelsVideoProvider()
    with pytest.raises(ProviderUnavailableError):
        p.generate("cats", 6.0, 1920, 1080, tmp_path / "out.mp4")


def test_pexels_generate_copies_broll_to_output(monkeypatch, tmp_path):
    fake_broll = tmp_path / "broll.mp4"
    fake_broll.write_bytes(b"FAKE_VIDEO")
    out = tmp_path / "output.mp4"

    monkeypatch.setattr("ytb_pipeline.providers.video.pexels_provider.settings",
                        MagicMock(pexels_api_key="key123"))
    monkeypatch.setattr(
        "ytb_pipeline.providers.video.pexels_provider.stock.fetch_broll",
        lambda query, min_duration, landscape: fake_broll,
    )

    p = PexelsVideoProvider()
    result = p.generate("nature", 5.0, 1920, 1080, out)

    assert result == out
    assert out.read_bytes() == b"FAKE_VIDEO"


def test_pexels_provider_name():
    assert PexelsVideoProvider.name == "pexels"


# ---------------------------------------------------------------------------
# WanVideoProvider
# ---------------------------------------------------------------------------

def test_wan_unavailable_when_model_path_empty(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.settings",
                        MagicMock(wan_model_path="", wan_cli="wan2.2"))
    p = WanVideoProvider()
    assert p.is_available() is False


def test_wan_unavailable_when_path_not_exist(monkeypatch, tmp_path):
    missing = tmp_path / "nonexistent"
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.settings",
                        MagicMock(wan_model_path=str(missing), wan_cli="wan2.2"))
    p = WanVideoProvider()
    assert p.is_available() is False


def test_wan_unavailable_when_cli_missing(monkeypatch, tmp_path):
    model_dir = tmp_path / "wan_weights"
    model_dir.mkdir()
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.settings",
                        MagicMock(wan_model_path=str(model_dir), wan_cli="missing-wan-cli"))
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.shutil.which", lambda _name: None)
    p = WanVideoProvider()
    assert p.is_available() is False


def test_wan_available_when_path_and_cli_exist(monkeypatch, tmp_path):
    model_dir = tmp_path / "wan_weights"
    model_dir.mkdir()
    runner = tmp_path / "wan2.2-ytb"
    runner.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.settings",
                        MagicMock(wan_model_path=str(model_dir), wan_cli=str(runner)))
    p = WanVideoProvider()
    assert p.is_available() is True


def test_wan_generate_raises_unavailable_when_no_model(monkeypatch, tmp_path):
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.settings",
                        MagicMock(wan_model_path="", wan_cli="wan2.2"))
    p = WanVideoProvider()
    with pytest.raises(ProviderUnavailableError):
        p.generate("sunset", 6.0, 1080, 1920, tmp_path / "out.mp4")


def test_wan_generate_raises_unavailable_when_cli_missing(monkeypatch, tmp_path):
    model_dir = tmp_path / "wan_weights"
    model_dir.mkdir()
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.settings",
                        MagicMock(wan_model_path=str(model_dir), wan_cli="missing-wan-cli"))
    monkeypatch.setattr("ytb_pipeline.providers.video.wan_provider.shutil.which", lambda _name: None)
    p = WanVideoProvider()
    with pytest.raises(ProviderUnavailableError):
        p.generate("sunset", 6.0, 1080, 1920, tmp_path / "out.mp4")


def test_wan_provider_name():
    assert WanVideoProvider.name == "wan"
