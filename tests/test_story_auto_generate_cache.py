"""Auto-generated scene images: content-hash cache, fail-closed on ComfyUI down.

Mirrors the write-through pattern already used for TTS segment caching: check
the cache file first, only call the (expensive, networked) provider on a miss,
write through immediately. A fake provider stands in for ComfyUI — no real
network call in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ytb_pipeline.content_profiles import load_content_profile
from ytb_pipeline.pkg.models import Segment
from ytb_pipeline.providers.errors import ProviderUnavailableError
from ytb_pipeline.render import story


class _FakeProvider:
    def __init__(self, *, fail: bool = False):
        self.calls: list[tuple] = []
        self.fail = fail

    def generate_scene(self, profile, *, characters_present, prompt, width, height, seed, output_path):
        self.calls.append((characters_present, prompt, width, height, seed))
        if self.fail:
            raise ProviderUnavailableError("ComfyUI không phản hồi")
        Path(output_path).write_bytes(b"fake-generated-png")
        return Path(output_path)


@pytest.fixture
def profile(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    # `resolve_scene_image` with no `scene_id` defaults `AssetRegistry()` to
    # `settings.asset_registry_path` — without this, these unit tests would
    # write into the real repository's `assets/asset_registry.json`.
    monkeypatch.setattr(settings, "asset_registry_path", tmp_path / "asset_registry.json", raising=False)
    return load_content_profile("ban-so-6")


def _segment(**overrides):
    base = dict(
        caption="c", narration="n", voiceover="n", visual_intent="Minh sitting at a table",
        speaker_id="minh", visual_asset="", scene_characters=("minh",),
    )
    base.update(overrides)
    return Segment(**base)


def test_fixed_visual_asset_bypasses_generation_entirely(profile, tmp_path):
    provider = _FakeProvider()
    segment = _segment(visual_asset="opening.png")

    path = story.resolve_scene_image(
        segment, profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider,
    )

    assert path == profile.visual_asset_path("opening.png")
    assert provider.calls == []


def test_missing_asset_and_cache_calls_the_provider_and_writes_through(profile, tmp_path):
    provider = _FakeProvider()
    segment = _segment()

    path = story.resolve_scene_image(
        segment, profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider,
    )

    assert path.is_file()
    assert path.read_bytes() == b"fake-generated-png"
    assert len(provider.calls) == 1
    characters, prompt, width, height, seed = provider.calls[0]
    assert characters == ("minh",)
    assert prompt == "Minh sitting at a table"


def test_a_cached_generation_is_reused_without_calling_the_provider_again(profile, tmp_path):
    provider = _FakeProvider()
    segment = _segment()

    first = story.resolve_scene_image(segment, profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider)
    second = story.resolve_scene_image(segment, profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider)

    assert first == second
    assert len(provider.calls) == 1


def test_different_visual_intent_produces_a_different_cache_entry(profile, tmp_path):
    provider = _FakeProvider()
    a = story.resolve_scene_image(_segment(visual_intent="Minh reading"), profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider)
    b = story.resolve_scene_image(_segment(visual_intent="Minh writing"), profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider)

    assert a != b
    assert len(provider.calls) == 2


def test_portrait_and_landscape_of_the_same_section_do_not_collide(profile, tmp_path):
    provider = _FakeProvider()
    segment = _segment()
    landscape = story.resolve_scene_image(segment, profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider)
    portrait = story.resolve_scene_image(segment, profile, story.PORTRAIT, cache_dir=tmp_path, provider=provider)

    assert landscape != portrait
    assert len(provider.calls) == 2


def test_seed_is_deterministic_for_the_same_inputs(profile, tmp_path):
    provider = _FakeProvider()
    segment = _segment()

    story.resolve_scene_image(segment, profile, story.LANDSCAPE, cache_dir=tmp_path, provider=provider)
    seed_one = provider.calls[0][-1]

    provider2 = _FakeProvider()
    (tmp_path / "elsewhere").mkdir()
    story.resolve_scene_image(
        segment, profile, story.LANDSCAPE, cache_dir=tmp_path / "elsewhere", provider=provider2,
    )
    seed_two = provider2.calls[0][-1]

    assert seed_one == seed_two


def test_comfyui_unavailable_fails_closed_and_leaves_no_partial_cache_file(profile, tmp_path):
    provider = _FakeProvider(fail=True)
    segment = _segment()
    cache_dir = tmp_path / "cache"

    with pytest.raises(ProviderUnavailableError):
        story.resolve_scene_image(segment, profile, story.LANDSCAPE, cache_dir=cache_dir, provider=provider)

    assert not cache_dir.is_dir() or list(cache_dir.iterdir()) == []


def test_section_with_neither_visual_asset_nor_generation_enabled_raises(tmp_path):
    from tests.test_visual_generation_profile import _write_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=None)
    from ytb_pipeline.content_profiles import load_content_profile as load

    disabled_profile = load("ban-so-6", profiles_dir=tmp_path)
    segment = _segment()
    provider = _FakeProvider()

    with pytest.raises(ValueError):
        story.resolve_scene_image(
            segment, disabled_profile, story.LANDSCAPE, cache_dir=tmp_path / "cache", provider=provider,
        )
