"""Đăng ký các ImageProvider vào image_registry khi module này được import."""

from ..registry import image_registry
from .flux_provider import FluxImageProvider
from .pillow_provider import PillowImageProvider

image_registry.register("pillow", PillowImageProvider)
image_registry.register("flux", FluxImageProvider)

__all__ = ["PillowImageProvider", "FluxImageProvider"]
