"""CodexImageProvider — Codex CLI (`codex exec`) as a config-selectable
ALTERNATIVE to ComfyUIStoryProvider for character_story scene generation.

Verified manually (not asserted here) that `codex exec` with the built-in
`image_gen` tool (feature `image_generation`, stable) really writes a PNG
under `~/.codex/generated_images/<session>/<file>.png` — see the P1 report.
No unit test may shell out to the real `codex` binary (CLAUDE.md: no real
LLM/TTS calls in unit tests); every test here injects a fake subprocess
runner and a temp "generated images" directory.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ytb_pipeline.providers.errors import ProviderUnavailableError


def _write_story_profile(root: Path, profile_id: str = "codex-provider-fixture") -> "object":
    from ytb_pipeline.content_profiles import load_content_profile

    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets" / "identity").mkdir(parents=True)
    (folder / "prompts" / "editorial.md").write_text("Editorial.", encoding="utf-8")
    (folder / "prompts" / "spoken-language.md").write_text("Spoken.", encoding="utf-8")
    (folder / "assets" / "identity" / "minh.png").write_bytes(b"fake-ref-png")
    payload = {
        "schema_version": 1, "profile_id": profile_id, "version": "1.0.0",
        "display_name": profile_id, "topic": "t", "narrative_mode": "character_story",
        "prompts": {"editorial": "prompts/editorial.md", "spoken_language": "prompts/spoken-language.md"},
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10},
        },
        "providers": {
            "llm": "xkiro", "tts": "xkiro", "render": "story",
            "broll_strategy": "none", "broll_allow_downloads": False,
        },
        "voice_cast": {"narrator": "standard-female-vietnamese", "minh": "confident-male-vietnamese"},
        "content_rules": {"require_pexels_query": False, "require_short_source_trace": False},
        "render": {
            "assets_dir": "assets", "show_captions": True,
            "inter_segment_gap_sec": 0.4, "transition_overlap_sec": 0.2,
        },
        "visual_generation": {
            "enabled": True, "style_prompt": "2D editorial illustration",
            "negative_prompt": "photo, 3d", "steps": 20, "cfg": 6.0,
            "solo_weight": 0.4, "duo_weight": 0.3, "duo_denoise": 0.5,
            "characters": {"minh": "identity/minh.png"}, "duo_reference_image": "",
        },
    }
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return load_content_profile(profile_id, profiles_dir=root)


class _FakeCompleted:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def test_unavailable_when_codex_binary_is_missing(tmp_path, monkeypatch):
    from ytb_pipeline.providers.image.codex_image_provider import CodexImageProvider

    monkeypatch.setattr("shutil.which", lambda name: None)
    provider = CodexImageProvider()

    ok, detail = provider.availability_status()
    assert ok is False
    assert "codex" in detail.lower()


def test_generate_scene_shells_out_and_copies_the_newest_generated_png(tmp_path, monkeypatch):
    from ytb_pipeline.providers.image.codex_image_provider import CodexImageProvider

    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/codex")
    profile = _write_story_profile(tmp_path)
    generated_dir = tmp_path / "generated_images"
    generated_dir.mkdir()

    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        # Simulate codex exec producing a real file, the way the verified
        # manual run did (~/.codex/generated_images/<session>/<file>.png).
        session_dir = generated_dir / "session-1"
        session_dir.mkdir(exist_ok=True)
        (session_dir / "result.png").write_bytes(_tiny_png())
        return _FakeCompleted(returncode=0)

    provider = CodexImageProvider(runner=fake_runner, generated_images_dir=generated_dir)
    output_path = tmp_path / "out" / "scene.png"

    result = provider.generate_scene(
        profile, characters_present=("minh",), prompt="Minh mo hop thu.",
        width=64, height=64, seed=1, output_path=output_path,
    )

    assert result == output_path
    assert output_path.is_file()
    assert calls, "codex exec must actually be invoked"
    cmd = calls[0]
    assert "codex" in cmd[0]
    assert "exec" in cmd
    assert str(profile.character_reference_path("minh")) in cmd


def test_generate_scene_raises_when_profile_has_no_visual_generation(tmp_path, monkeypatch):
    from ytb_pipeline.providers.image.codex_image_provider import CodexImageProvider
    from ytb_pipeline.content_profiles import load_content_profile
    from tests.test_visual_generation_profile import _write_profile

    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/codex")
    _write_profile(tmp_path, "no-vg-fixture", visual_generation=None)
    profile = load_content_profile("no-vg-fixture", profiles_dir=tmp_path)

    provider = CodexImageProvider(runner=lambda cmd, **kw: _FakeCompleted(), generated_images_dir=tmp_path)

    with pytest.raises(ProviderUnavailableError):
        provider.generate_scene(
            profile, characters_present=(), prompt="x", width=64, height=64,
            seed=1, output_path=tmp_path / "o.png",
        )


def test_generate_scene_raises_when_codex_exits_nonzero(tmp_path, monkeypatch):
    from ytb_pipeline.providers.image.codex_image_provider import CodexImageProvider

    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/codex")
    profile = _write_story_profile(tmp_path)
    generated_dir = tmp_path / "generated_images"
    generated_dir.mkdir()

    provider = CodexImageProvider(
        runner=lambda cmd, **kw: _FakeCompleted(returncode=1, stderr="boom"),
        generated_images_dir=generated_dir,
    )

    with pytest.raises(ProviderUnavailableError):
        provider.generate_scene(
            profile, characters_present=(), prompt="x", width=64, height=64,
            seed=1, output_path=tmp_path / "o.png",
        )


def test_generate_scene_raises_when_no_new_image_appears(tmp_path, monkeypatch):
    from ytb_pipeline.providers.image.codex_image_provider import CodexImageProvider

    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/codex")
    profile = _write_story_profile(tmp_path)
    generated_dir = tmp_path / "generated_images"
    generated_dir.mkdir()

    provider = CodexImageProvider(
        runner=lambda cmd, **kw: _FakeCompleted(returncode=0),
        generated_images_dir=generated_dir,
    )

    with pytest.raises(ProviderUnavailableError):
        provider.generate_scene(
            profile, characters_present=(), prompt="x", width=64, height=64,
            seed=1, output_path=tmp_path / "o.png",
        )


def test_rejects_more_than_two_characters(tmp_path, monkeypatch):
    from ytb_pipeline.providers.image.codex_image_provider import CodexImageProvider

    monkeypatch.setattr("shutil.which", lambda name: "/opt/homebrew/bin/codex")
    profile = _write_story_profile(tmp_path)
    provider = CodexImageProvider(runner=lambda cmd, **kw: _FakeCompleted(), generated_images_dir=tmp_path)

    with pytest.raises(ValueError):
        provider.generate_scene(
            profile, characters_present=("minh", "an", "third"), prompt="x",
            width=64, height=64, seed=1, output_path=tmp_path / "o.png",
        )


def test_story_image_registry_selects_codex_by_settings(tmp_path, monkeypatch):
    from ytb_pipeline.providers.registry import get_story_image_provider
    from ytb_pipeline.providers.image.codex_image_provider import CodexImageProvider
    from ytb_pipeline.providers.image.comfyui_story_provider import ComfyUIStoryProvider
    from ytb_pipeline.config.settings import settings

    monkeypatch.setattr(settings, "story_image_provider", "codex", raising=False)
    assert isinstance(get_story_image_provider(), CodexImageProvider)

    monkeypatch.setattr(settings, "story_image_provider", "comfyui", raising=False)
    assert isinstance(get_story_image_provider(), ComfyUIStoryProvider)


def _tiny_png() -> bytes:
    import io
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()
