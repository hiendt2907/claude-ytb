"""Test cho ProviderRegistry — Phase 1 migration (xem 29-MIGRATION_PLAN.md).

Bao gồm: register/get/available cơ bản, default qua settings, lỗi tên không
tồn tại, và kiểm tra các Protocol (VoiceProvider/RenderProvider) qua
`isinstance` (runtime_checkable).
"""

import pytest

from ytb_pipeline.providers.base import RenderProvider, VoiceProvider
from ytb_pipeline.providers.registry import (
    ProviderRegistry,
    get_render_provider,
    get_voice_provider,
)
from ytb_pipeline.providers.voice.edge_provider import EdgeVoiceProvider
from ytb_pipeline.providers.voice.f5_provider import F5VoiceProvider
from ytb_pipeline.providers.render.slide_provider import SlideRenderProvider


def test_register_and_get_returns_instance():
    registry: ProviderRegistry = ProviderRegistry("test")
    registry.register("foo", EdgeVoiceProvider)

    provider = registry.get("foo")

    assert isinstance(provider, EdgeVoiceProvider)


def test_available_lists_registered_names_sorted():
    registry: ProviderRegistry = ProviderRegistry("test")
    registry.register("zeta", EdgeVoiceProvider)
    registry.register("alpha", F5VoiceProvider)

    assert registry.available() == ["alpha", "zeta"]


def test_get_unknown_name_raises_value_error():
    registry: ProviderRegistry = ProviderRegistry("test")
    registry.register("foo", EdgeVoiceProvider)

    with pytest.raises(ValueError, match="foo"):
        registry.get("bar")


def test_get_voice_provider_defaults_to_settings_tts_provider(settings_patch=None):
    from ytb_pipeline.config.settings import settings

    original = settings.tts_provider
    try:
        settings.tts_provider = "edge"
        provider = get_voice_provider()
        assert provider.name == "edge"
        assert isinstance(provider, EdgeVoiceProvider)
    finally:
        settings.tts_provider = original


def test_get_voice_provider_explicit_name_overrides_settings():
    provider = get_voice_provider("f5")

    assert provider.name == "f5"
    assert isinstance(provider, F5VoiceProvider)


def test_get_render_provider_defaults_to_settings_render_provider():
    from ytb_pipeline.config.settings import settings

    original = settings.render_provider
    try:
        settings.render_provider = "slide"
        provider = get_render_provider()
        assert provider.name == "slide"
        assert isinstance(provider, SlideRenderProvider)
    finally:
        settings.render_provider = original


def test_get_render_provider_invalid_name_raises():
    with pytest.raises(ValueError):
        get_render_provider("does-not-exist")


def test_edge_voice_provider_satisfies_voice_provider_protocol():
    provider = EdgeVoiceProvider()

    assert isinstance(provider, VoiceProvider)


def test_slide_render_provider_satisfies_render_provider_protocol():
    provider = SlideRenderProvider()

    assert isinstance(provider, RenderProvider)


def test_new_voice_provider_requires_only_one_file_and_one_registry_line():
    """Acceptance check (29-MIGRATION_PLAN.md, Phase 1): thêm 1 VoiceProvider
    mới chỉ cần 1 class + 1 dòng register — KHÔNG sửa registry.py/pipeline.py."""

    class NullVoiceProvider:
        name = "null"

        async def synthesise(self, script, output_dir):
            from dataclasses import replace

            from ytb_pipeline.pkg.models import Voiceover

            return Voiceover(**vars(script))

        def is_available(self) -> bool:
            return True

    registry: ProviderRegistry = ProviderRegistry("voice")
    registry.register("null", NullVoiceProvider)

    provider = registry.get("null")

    assert isinstance(provider, VoiceProvider)
    assert provider.name == "null"
