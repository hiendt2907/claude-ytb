"""Orientation contract for the local, offline slide renderer."""

from ytb_pipeline.config.settings import settings
from ytb_pipeline.providers.image.pillow_provider import PillowImageProvider
from ytb_pipeline.render import compose


def test_slide_renderer_uses_landscape_dimensions_for_long_frames(monkeypatch):
    """A Long slide frame must be native 1920x1080, not a rotated Short."""
    calls = []
    fallback = PillowImageProvider()

    class SpyProvider:
        def generate(self, prompt, width, height, output_path, **kwargs):
            calls.append((width, height))
            return fallback.generate(prompt, width, height, output_path, **kwargs)

    monkeypatch.setattr(settings, "orientation", "landscape")
    monkeypatch.setattr(compose, "get_image_provider", lambda: SpyProvider())

    frame = compose._background_image(0, 1, prompt="mechanism explainer")

    assert calls == [(1920, 1080)]
    assert frame.size == (1920, 1080)


def test_slide_renderer_keeps_portrait_dimensions_for_short_frames(monkeypatch):
    """The orientation fix must not change Short's established 1080x1920 output."""
    calls = []
    fallback = PillowImageProvider()

    class SpyProvider:
        def generate(self, prompt, width, height, output_path, **kwargs):
            calls.append((width, height))
            return fallback.generate(prompt, width, height, output_path, **kwargs)

    monkeypatch.setattr(settings, "orientation", "portrait")
    monkeypatch.setattr(compose, "get_image_provider", lambda: SpyProvider())

    frame = compose._background_image(0, 1, prompt="mechanism explainer")

    assert calls == [(1080, 1920)]
    assert frame.size == (1080, 1920)
