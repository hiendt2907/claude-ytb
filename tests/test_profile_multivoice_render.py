"""Multi-speaker xKiro and the local story renderer share the normal DAG ports."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image


def _profile(root: Path) -> None:
    folder = root / "ban-so-6"
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "prompts" / "editorial.md").write_text("story", encoding="utf-8")
    (folder / "profile.json").write_text(json.dumps({
        "schema_version": 1,
        "profile_id": "ban-so-6",
        "version": "1.0.0",
        "display_name": "Bàn số 6",
        "topic": "Bàn số 6",
        "narrative_mode": "character_story",
        "prompts": {"editorial": "prompts/editorial.md"},
        "formats": {
            "short": {"viewer_min_sec": 1, "viewer_max_sec": 20, "min_sections": 2},
            "long": {"viewer_min_sec": 60, "viewer_max_sec": 420, "min_sections": 2},
        },
        "providers": {
            "llm": "xkiro", "tts": "xkiro", "render": "story",
            "broll_strategy": "none", "broll_allow_downloads": False,
        },
        "voice_cast": {
            "narrator": "standard-female-vietnamese",
            "minh": "confident-male-vietnamese",
            "an": "sweet-female-vietnamese",
        },
        "content_rules": {
            "require_pexels_query": False, "require_short_source_trace": False,
        },
        "render": {
            "assets_dir": "assets", "show_captions": True,
            "inter_segment_gap_sec": 0.1,
        },
    }), encoding="utf-8")
    Image.new("RGB", (1600, 900), "#5A4032").save(folder / "assets" / "opening.png")
    Image.new("RGB", (900, 1600), "#26394A").save(folder / "assets" / "reply.png")


def _tone(path: Path, duration: float = 0.8) -> None:
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-ar", "48000", "-ac", "2", str(path),
    ], check=True)


def test_xkiro_selects_voice_per_speaker_and_cache_key(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.pkg.models import Script, Segment
    from ytb_pipeline.providers.voice.xkiro_provider import XkiroVoiceProvider

    profiles = tmp_path / "profiles"
    _profile(profiles)
    monkeypatch.setattr(settings, "content_profiles_dir", profiles, raising=False)
    provider = XkiroVoiceProvider()
    script = Script(
        topic="t", title="t", description="d",
        content_profile_id="ban-so-6", content_profile_version="1.0.0",
        segments=(Segment("", "Xin chào", speaker_id="minh"),),
    )
    minh = script.segments[0]
    an = replace(minh, speaker_id="an")

    assert provider._voice_for_segment(script, minh) == "confident-male-vietnamese"
    assert provider._voice_for_segment(script, an) == "sweet-female-vietnamese"
    assert provider._segment_path(script, minh, 0, tmp_path) != provider._segment_path(
        replace(script, segments=(an,)), an, 0, tmp_path
    )


@pytest.mark.skipif(not Path("/opt/homebrew/bin/ffmpeg").exists(), reason="ffmpeg required")
def test_story_renderer_uses_profile_assets_and_real_segment_audio(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.pkg.models import Segment, Voiceover
    from ytb_pipeline.providers.render.story_provider import StoryRenderProvider

    profiles = tmp_path / "profiles"
    _profile(profiles)
    monkeypatch.setattr(settings, "content_profiles_dir", profiles, raising=False)
    monkeypatch.setattr(settings, "orientation", "portrait", raising=False)
    first_audio = tmp_path / "first.wav"
    second_audio = tmp_path / "second.wav"
    _tone(first_audio)
    _tone(second_audio)
    video = Voiceover(
        topic="t", title="Bàn số 6", description="d", video_type="short",
        content_profile_id="ban-so-6", content_profile_version="1.0.0",
        segments=(
            Segment("Minh mở laptop", "Minh mở laptop.", speaker_id="narrator",
                    visual_asset="opening.png", audio_path=first_audio, duration_sec=0.8),
            Segment("Em chỉ sợ", "Em chỉ sợ nó sơ sài.", speaker_id="minh",
                    visual_asset="reply.png", audio_path=second_audio, duration_sec=0.8),
        ),
        audio_path=first_audio,
        duration_sec=1.6,
    )

    result = __import__("asyncio").run(StoryRenderProvider().render(video, tmp_path / "output"))

    assert result.video_path is not None and result.video_path.exists()
    assert result.thumbnail_path is not None and result.thumbnail_path.exists()
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=width,height",
        "-select_streams", "v:0", "-of", "csv=p=0", str(result.video_path),
    ], check=True, capture_output=True, text=True)
    assert probe.stdout.strip() == "1080,1920"
    assert 1.5 <= float(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(result.video_path),
    ], check=True, capture_output=True, text=True).stdout) <= 2.2


def test_story_renderer_is_registered_without_replacing_ai_provider():
    from ytb_pipeline.providers.registry import get_render_provider

    assert get_render_provider("story").name == "story"
    assert get_render_provider("ai").name == "ai"

