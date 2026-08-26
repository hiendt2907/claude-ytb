"""Đăng ký các ImageProvider vào image_registry khi module này được import."""

from ..registry import image_registry, story_image_registry
from .codex_image_provider import CodexImageProvider
from .comfyui_story_provider import ComfyUIStoryProvider
from .flux_provider import FluxImageProvider
from .pillow_provider import PillowImageProvider

image_registry.register("pillow", PillowImageProvider)
image_registry.register("flux", FluxImageProvider)

# Story-scene providers (profile + named characters + seed) — separate
# registry, see providers/registry.py::story_image_registry.
story_image_registry.register("comfyui", ComfyUIStoryProvider)
story_image_registry.register("codex", CodexImageProvider)

__all__ = [
    "PillowImageProvider", "FluxImageProvider", "ComfyUIStoryProvider", "CodexImageProvider",
]
