"""Đăng ký các RenderProvider vào render_registry khi module này được import."""

from ..registry import render_registry
from .ai_provider import AiRenderProvider
from .slide_provider import SlideRenderProvider

render_registry.register("slide", SlideRenderProvider)
render_registry.register("ai", AiRenderProvider)

__all__ = ["SlideRenderProvider", "AiRenderProvider"]
