"""Bounds contracts shared by slide and AI code-card overlays."""

from types import SimpleNamespace

from ytb_pipeline.render import compose, compose_ai


def test_ai_portrait_code_card_stays_in_frame_after_a_long_caption(monkeypatch):
    """AI's portrait overlay must reserve its card space, like the slide renderer."""
    captured_bottoms = []
    original = compose._draw_terminal

    def spy(img, draw, code, *, top, danger, width, height):
        layout = compose._terminal_layout(draw, code, width=width, top=top, height=height)
        captured_bottoms.append(layout.top + layout.card_height)
        return original(img, draw, code, top=top, danger=danger, width=width, height=height)

    monkeypatch.setattr(compose_ai.slide, "_draw_terminal", spy)
    segment = SimpleNamespace(caption="caption " * 40, code="echo " + "x" * 400, danger=False)

    compose_ai._static_overlay(segment, index=0, total=1, dims=(1080, 1920))

    assert captured_bottoms and captured_bottoms[0] <= 1920 - 48
