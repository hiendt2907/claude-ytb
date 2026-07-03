"""Đăng ký các VideoProvider vào video_registry khi module này được import."""

from ..registry import video_registry
from .disabled_provider import DisabledVideoProvider
from .pexels_provider import PexelsVideoProvider
from .wan_provider import WanVideoProvider

video_registry.register("disabled", DisabledVideoProvider)
video_registry.register("pexels", PexelsVideoProvider)
video_registry.register("wan", WanVideoProvider)

__all__ = ["DisabledVideoProvider", "PexelsVideoProvider", "WanVideoProvider"]
