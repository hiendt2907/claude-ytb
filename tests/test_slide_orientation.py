"""Orientation contract for the local, offline slide renderer."""

from ytb_pipeline.config.settings import settings
from PIL import Image, ImageDraw
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


def test_landscape_terminal_card_fits_within_the_frame():
    """Long code cards must never extend below a 1080px landscape frame."""
    width, height, top = 1920, 1080, 400
    draw = ImageDraw.Draw(Image.new("RGB", (width, height)))

    layout = compose._terminal_layout(
        draw, "echo " + "x" * 400, width=width, top=top, height=height
    )

    assert layout.top + layout.card_height <= height - 48


def test_landscape_terminal_caption_reserves_space_for_the_code_card():
    """A long caption is shortened rather than overlapped by a Long code card."""
    width, height = 1920, 1080
    draw = ImageDraw.Draw(Image.new("RGB", (width, height)))

    lines, caption_bottom, layout = compose._fit_terminal_caption(
        draw,
        "caption " * 100,
        "echo " + "x" * 400,
        width=width,
        height=height,
    )

    assert lines[-1].endswith("…")
    assert layout.top >= caption_bottom + 90
    assert layout.top + layout.card_height <= height - 48
