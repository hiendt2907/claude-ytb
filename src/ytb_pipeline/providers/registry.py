"""ProviderRegistry — đăng ký + tra cứu provider theo tên, thay cho
`if x_provider == "...": ... elif ...` rải rác khắp pipeline.

Adapter module (vd `providers/voice/edge_provider.py`) tự đăng ký mình vào
registry tương ứng khi `providers/voice/__init__.py` được import. Pipeline
gọi `get_voice_provider()` / `get_render_provider()` / `get_publish_provider()`
— không còn biết tên provider cụ thể nào đang chạy.
"""

from typing import Generic, Type, TypeVar

from ..config.settings import settings
from .base import (
    ImageProvider,
    LLMProvider,
    PublishProvider,
    RenderProvider,
    VideoProvider,
    VoiceProvider,
)

T = TypeVar("T")


class ProviderRegistry(Generic[T]):
    """Registry tên→class cho một capability (voice/render/publish)."""

    def __init__(self, provider_type: str) -> None:
        self.provider_type = provider_type
        self._providers: dict[str, Type[T]] = {}

    def register(self, name: str, provider_class: Type[T]) -> None:
        self._providers[name] = provider_class

    def get(self, name: str) -> T:
        try:
            provider_class = self._providers[name]
        except KeyError as exc:
            raise ValueError(
                f"Không có {self.provider_type} provider tên '{name}'. "
                f"Các provider khả dụng: {self.available()}"
            ) from exc
        return provider_class()

    def available(self) -> list[str]:
        return sorted(self._providers.keys())


voice_registry: ProviderRegistry[VoiceProvider] = ProviderRegistry("voice")
render_registry: ProviderRegistry[RenderProvider] = ProviderRegistry("render")
publish_registry: ProviderRegistry[PublishProvider] = ProviderRegistry("publish")
image_registry: ProviderRegistry[ImageProvider] = ProviderRegistry("image")
video_registry: ProviderRegistry[VideoProvider] = ProviderRegistry("video")
llm_registry: ProviderRegistry[LLMProvider] = ProviderRegistry("llm")


def get_voice_provider(name: str | None = None) -> VoiceProvider:
    """Trả provider theo tên, hoặc settings.tts_provider làm mặc định."""
    from . import voice  # noqa: F401  — đảm bảo đã đăng ký

    return voice_registry.get(name or settings.tts_provider)


def get_render_provider(name: str | None = None) -> RenderProvider:
    """Trả provider theo tên, hoặc settings.render_provider làm mặc định."""
    from . import render  # noqa: F401  — đảm bảo đã đăng ký

    return render_registry.get(name or settings.render_provider)


def get_publish_provider(name: str | None = None) -> PublishProvider:
    """Trả provider theo tên; mặc định "youtube" (khâu publish chính)."""
    from . import publish  # noqa: F401  — đảm bảo đã đăng ký

    return publish_registry.get(name or "youtube")


def get_image_provider(name: str | None = None) -> ImageProvider:
    """Trả provider theo tên, hoặc settings.image_provider làm mặc định."""
    from . import image  # noqa: F401  — đảm bảo đã đăng ký

    return image_registry.get(name or settings.image_provider)


def get_video_provider(name: str | None = None) -> VideoProvider:
    """Trả provider theo tên, hoặc settings.video_provider làm mặc định ("pexels")."""
    from . import video  # noqa: F401  — đảm bảo đã đăng ký

    return video_registry.get(name or settings.video_provider)


def get_llm_provider(name: str | None = None) -> LLMProvider:
    """Trả provider theo tên, hoặc settings.llm_provider làm mặc định ("claude")."""
    from . import llm  # noqa: F401  — đảm bảo đã đăng ký

    return llm_registry.get(name or settings.llm_provider)
