"""Đăng ký các RenderProvider vào render_registry khi module này được import."""

from ..registry import render_registry
from .ai_provider import AiRenderProvider
from .slide_provider import SlideRenderProvider
from .story_provider import StoryRenderProvider

render_registry.register("slide", SlideRenderProvider)
render_registry.register("ai", AiRenderProvider)
render_registry.register("story", StoryRenderProvider)

__all__ = ["SlideRenderProvider", "AiRenderProvider", "StoryRenderProvider"]
