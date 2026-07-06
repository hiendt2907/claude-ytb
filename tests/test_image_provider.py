"""Test cho ImageProvider — Phase 3 (PillowImageProvider + FluxImageProvider stub).

Bao gồm: PillowImageProvider sinh PNG đúng kích thước, FluxImageProvider
is_available() false khi ComfyUI không chạy + raise ProviderUnavailableError
khi generate() bị gọi lúc unavailable, registry get_image_provider(), Protocol
isinstance check, và slide renderer dùng image provider.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from ytb_pipeline.providers.base import ImageProvider
from ytb_pipeline.providers.errors import ProviderUnavailableError
from ytb_pipeline.providers.image.flux_provider import FluxImageProvider
from ytb_pipeline.providers.image.pillow_provider import PillowImageProvider
from ytb_pipeline.providers.registry import get_image_provider, image_registry


def test_pillow_provider_is_available_true():
    assert PillowImageProvider().is_available() is True


def test_pillow_provider_generate_creates_file(tmp_path):
    provider = PillowImageProvider()
    out = tmp_path / "bg.png"

    provider.generate(prompt="dark theme", width=200, height=300, output_path=out)

    assert out.exists()
    img = Image.open(out)
    assert img.format == "PNG"


def test_pillow_provider_generate_returns_output_path(tmp_path):
    provider = PillowImageProvider()
    out = tmp_path / "bg.png"

    result = provider.generate(prompt="", width=100, height=100, output_path=out)

    assert result == out


def test_pillow_provider_generate_respects_dimensions(tmp_path):
    provider = PillowImageProvider()
    out = tmp_path / "bg.png"

    provider.generate(prompt="", width=400, height=600, output_path=out)

    with Image.open(out) as img:
        assert img.size == (400, 600)


def test_pillow_provider_generate_default_dimensions(tmp_path):
    provider = PillowImageProvider()
    out = tmp_path / "bg.png"

    provider.generate(prompt="", width=1080, height=1920, output_path=out)

    with Image.open(out) as img:
        assert img.size == (1080, 1920)


def test_pillow_provider_stickman_prompt_draws_non_flat_scene(tmp_path):
    provider = PillowImageProvider()
    out = tmp_path / "stickman.png"

    provider.generate(
        prompt="người que chạy đuổi theo cánh cửa rồi trượt chân",
        width=360,
        height=640,
        output_path=out,
    )

    with Image.open(out).convert("RGB") as img:
        colors = img.getcolors(maxcolors=1_000_000)
        central = img.crop((80, 260, 260, 540))
        bright_pixels = sum(1 for r, g, b in central.getdata() if r + g + b > 680)

    assert colors is not None
    assert len(colors) > 20
    assert bright_pixels > 250


def test_flux_provider_is_available_false_when_comfyui_unreachable():
    provider = FluxImageProvider()

    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert provider.is_available() is False


def test_flux_provider_is_available_false_when_checkpoint_missing(monkeypatch):
    provider = FluxImageProvider()
    monkeypatch.setattr(
        "ytb_pipeline.providers.image.flux_provider.settings.flux_checkpoint_name",
        "flux1-dev-fp8.safetensors",
    )

    class Response:
        status = 200

        def __init__(self, body: bytes = b"{}"):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    def fake_urlopen(url, timeout=0):  # noqa: ARG001
        if str(url).endswith("/system_stats"):
            return Response()
        return Response(
            b'{"CheckpointLoaderSimple":{"input":{"required":{"ckpt_name":[["other.safetensors"]]}}}}'
        )

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        ok, detail = provider.availability_status()

    assert ok is False
    assert "flux1-dev-fp8.safetensors" in detail


def test_flux_provider_is_available_true_when_checkpoint_exists(monkeypatch):
    provider = FluxImageProvider()
    monkeypatch.setattr(
        "ytb_pipeline.providers.image.flux_provider.settings.flux_checkpoint_name",
        "flux1-dev-fp8.safetensors",
    )

    class Response:
        status = 200

        def __init__(self, body: bytes = b"{}"):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    def fake_urlopen(url, timeout=0):  # noqa: ARG001
        if str(url).endswith("/system_stats"):
            return Response()
        return Response(
            b'{"CheckpointLoaderSimple":{"input":{"required":{"ckpt_name":[["flux1-dev-fp8.safetensors"]]}}}}'
        )

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        assert provider.is_available() is True


def test_flux_provider_generate_raises_when_unavailable(tmp_path):
    provider = FluxImageProvider()
    out = tmp_path / "bg.png"

    with patch.object(FluxImageProvider, "is_available", return_value=False):
        with pytest.raises(ProviderUnavailableError):
            provider.generate(prompt="a city", width=100, height=100, output_path=out)


def test_get_image_provider_pillow_returns_instance():
    provider = get_image_provider("pillow")

    assert isinstance(provider, PillowImageProvider)


def test_get_image_provider_flux_returns_instance():
    provider = get_image_provider("flux")

    assert isinstance(provider, FluxImageProvider)


def test_get_image_provider_defaults_to_settings_image_provider():
    from ytb_pipeline.config.settings import settings

    original = settings.image_provider
    try:
        settings.image_provider = "pillow"
        provider = get_image_provider()
        assert isinstance(provider, PillowImageProvider)
    finally:
        settings.image_provider = original


def test_image_registry_available_includes_pillow_and_flux():
    from ytb_pipeline.providers import image  # noqa: F401 — ensure registered

    assert "pillow" in image_registry.available()
    assert "flux" in image_registry.available()


def test_pillow_provider_satisfies_image_provider_protocol():
    provider = PillowImageProvider()

    assert isinstance(provider, ImageProvider)


def test_slide_renderer_uses_image_provider(tmp_path, monkeypatch):
    from ytb_pipeline.render import compose

    fake_provider = PillowImageProvider()
    calls = []

    class SpyProvider:
        name = "pillow"

        def generate(self, prompt, width, height, output_path, **kwargs):
            calls.append(prompt)
            return fake_provider.generate(prompt, width, height, output_path, **kwargs)

        def is_available(self):
            return True

    monkeypatch.setattr(compose, "get_image_provider", lambda *a, **k: SpyProvider())

    img = compose._background_image(0, 1, prompt="hello")

    assert calls == ["hello"]
    assert img.size == (compose.W, compose.H)
