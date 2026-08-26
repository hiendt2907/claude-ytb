"""Multi-speaker xKiro and the local story renderer share the normal DAG ports."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image


def _profile(
    root: Path, *, profile_id: str = "ban-so-6", gap: float = 0.1, overlap: float = 0.1,
) -> None:
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "prompts" / "editorial.md").write_text("story", encoding="utf-8")
    (folder / "profile.json").write_text(json.dumps({
        "schema_version": 1,
        "profile_id": profile_id,
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
            "inter_segment_gap_sec": gap, "transition_overlap_sec": overlap,
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


@pytest.mark.skipif(not Path("/opt/homebrew/bin/ffmpeg").exists(), reason="ffmpeg required")
def test_story_renderer_preserves_audio_timeline_when_a_section_has_many_caption_cards(
    tmp_path, monkeypatch,
):
    """Caption cards are intra-section presentation, never transition boundaries.

    The production Long ``phan-hoi-dong-nghiep-nho-an-xem`` created 162 cards
    from 20 spoken sections.  Applying a 0.4-second crossfade to every card
    silently removed over a minute of TTS.  This real ffmpeg regression keeps
    multi-card sections and requires the final timeline to follow the section
    timing contract instead.
    """
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.pkg.models import Segment, Voiceover
    from ytb_pipeline.providers.render.story_provider import StoryRenderProvider
    from ytb_pipeline.render.story import expected_story_duration_sec

    profiles = tmp_path / "profiles"
    _profile(profiles)
    monkeypatch.setattr(settings, "content_profiles_dir", profiles, raising=False)
    monkeypatch.setattr(settings, "orientation", "landscape", raising=False)
    first_audio = tmp_path / "first.wav"
    second_audio = tmp_path / "second.wav"
    _tone(first_audio, duration=2.0)
    _tone(second_audio, duration=2.0)
    narration = (
        "Minh mở tin nhắn lần nữa. Cậu đọc câu đầu rất chậm. "
        "An đặt tách cà phê xuống. Bên ngoài xe bắt đầu đông hơn."
    )
    voiceover = Voiceover(
        topic="t", title="timeline", description="d", video_type="short",
        content_profile_id="ban-so-6", content_profile_version="1.0.0",
        segments=(
            Segment("", narration, speaker_id="narrator", visual_asset="opening.png",
                    audio_path=first_audio, duration_sec=2.0),
            Segment("", narration, speaker_id="an", visual_asset="reply.png",
                    audio_path=second_audio, duration_sec=2.0),
        ),
        audio_path=first_audio, duration_sec=4.0,
    )

    result = __import__("asyncio").run(
        StoryRenderProvider().render(voiceover, tmp_path / "output")
    )
    actual_duration = float(subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(result.video_path),
    ], check=True, capture_output=True, text=True).stdout)
    profile = load_content_profile("ban-so-6")
    expected_duration = expected_story_duration_sec(profile, [2.0, 2.0])

    assert actual_duration == pytest.approx(expected_duration, abs=0.20)


def _stream_duration(path: Path, stream: str) -> float:
    return float(subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", stream,
        "-show_entries", "stream=duration", "-of", "csv=p=0", str(path),
    ], check=True, capture_output=True, text=True).stdout)


def test_frame_counts_sum_exactly_to_the_rounded_total_with_no_drift():
    """Per-card frame counts must never accumulate rounding error.

    Rounding each card's length to the nearest frame independently (the old
    approach) drifted a 12-card section +76ms over its nominal length in a
    real Long. Cumulative rounding — round the RUNNING total, then take the
    difference from the previous running total — guarantees the sum of all
    per-card frame counts equals round(sum(lengths) * fps) exactly, no matter
    how many cards or how awkward their individual lengths are.
    """
    from ytb_pipeline.render.story import _frame_counts

    lengths = [2.76, 1.014, 2.929, 2.422, 2.76, 1.915, 2.816, 2.929, 1.408, 2.309, 2.76, 1.352]
    counts = _frame_counts(lengths, fps=30)

    assert len(counts) == len(lengths)
    assert all(count >= 1 for count in counts)
    assert sum(counts) == round(sum(lengths) * 30)


def test_frame_counts_preserves_total_when_an_early_card_is_subframe():
    """A card still needs one frame, without making the section longer.

    The old cumulative implementation turned 10ms + 40ms into [1, 2]
    frames: three visual frames for a two-frame section.  This is reachable
    when a profile has no transition overlap and a short caption is not
    otherwise merged.
    """
    from ytb_pipeline.render.story import _frame_counts

    counts = _frame_counts([0.01, 0.04], fps=30)

    assert counts == [1, 1]
    assert sum(counts) == round(0.05 * 30)


def test_story_cards_merge_subframe_lines_when_profile_has_no_overlap(tmp_path, monkeypatch):
    """Zero-overlap profiles need the same one-frame safety floor.

    A profile may deliberately choose hard cuts (overlap=0).  That choice
    must not let tiny caption lines bypass the renderer's frame contract.
    """
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.pkg.models import Segment
    from ytb_pipeline.render.story import LANDSCAPE, _frame_counts, _segment_cards

    profiles = tmp_path / "profiles"
    _profile(profiles)
    monkeypatch.setattr(settings, "content_profiles_dir", profiles, raising=False)
    profile = load_content_profile("ban-so-6")
    profile = replace(
        profile,
        render=replace(profile.render, inter_segment_gap_sec=0.0, transition_overlap_sec=0.0),
    )
    segment = Segment("", "Một. Hai.", duration_sec=0.05)

    cards = _segment_cards(segment, profile, LANDSCAPE)

    assert len(cards) == 1
    assert _frame_counts([card[2] for card in cards], fps=30) == [2]


@pytest.mark.skipif(not Path("/opt/homebrew/bin/ffmpeg").exists(), reason="ffmpeg required")
def test_render_video_card_produces_the_exact_requested_frame_count(tmp_path):
    from ytb_pipeline.render.story import _render_video_card

    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (640, 360), "red").save(frame)
    clip = tmp_path / "card.mp4"
    _render_video_card("ffmpeg", frame, clip, frames=23)

    nb_frames = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-count_frames", "-show_entries", "stream=nb_read_frames",
        "-of", "csv=p=0", str(clip),
    ], check=True, capture_output=True, text=True).stdout.strip()
    assert nb_frames == "23"
    # No audio input was ever given to a video-only card — no track to drift.
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
        "stream=index", "-of", "csv=p=0", str(clip),
    ], capture_output=True, text=True).stdout.strip()
    assert probe == ""


@pytest.mark.skipif(not Path("/opt/homebrew/bin/ffmpeg").exists(), reason="ffmpeg required")
def test_story_renderer_keeps_video_and_audio_streams_in_sync_with_many_cards_and_asymmetric_gap(
    tmp_path, monkeypatch,
):
    """The real bug Codex's audit caught: video and audio streams drifting apart.

    The card-vs-transition fix still sliced the ORIGINAL segment audio into
    one re-encoded piece per caption card before concatenating — each slice's
    AAC re-encode rounds independently, and that rounding compounds
    separately from the (also independently rounding) video track, so the
    two streams end up different lengths in the final MP4: video stream
    395.333s, audio stream 396.480s in the real Long, leaving ~1.1s of
    trailing audio with no new video. The fix must mux the section's REAL,
    UNSLICED audio file exactly once and drive the video timeline from
    frame-exact card counts, so both streams land within one video frame of
    each other — checked here with `inter_segment_gap_sec != transition_overlap_sec`
    so the two are never accidentally interchangeable in the compose math.
    """
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.pkg.models import Segment, Voiceover
    from ytb_pipeline.providers.render.story_provider import StoryRenderProvider
    from ytb_pipeline.render.story import expected_story_duration_sec

    profiles = tmp_path / "profiles"
    _profile(profiles, gap=0.4, overlap=0.15)
    monkeypatch.setattr(settings, "content_profiles_dir", profiles, raising=False)
    monkeypatch.setattr(settings, "orientation", "landscape", raising=False)

    solo_audio = tmp_path / "solo.wav"
    _tone(solo_audio, duration=1.517)
    multi_audio = tmp_path / "multi.wav"
    # 12 short sentences -> 12 caption cards sharing ONE underlying audio
    # file, matching the card count of the real Long section that exposed
    # the drift (27.373s across 12 cards, +64ms video/audio gap under the
    # old per-card audio-slicing design).
    multi_duration = 27.373
    _tone(multi_audio, duration=multi_duration)
    narration = (
        "Minh nhìn màn hình. Cậu gõ tiếp. An bước vào. Cậu đặt ly xuống. "
        "Minh ngẩng lên. Cả hai im lặng. Rồi cậu cười. An ngồi xuống ghế. "
        "Minh đóng laptop. Cậu thở dài nhẹ. An mở lời trước. Minh gật đầu đồng ý."
    )

    voiceover = Voiceover(
        topic="t", title="sync", description="d", video_type="short",
        content_profile_id="ban-so-6", content_profile_version="1.0.0",
        segments=(
            # Single short sentence -> one caption card.
            Segment("", "Minh gật đầu.", speaker_id="narrator", visual_asset="opening.png",
                    audio_path=solo_audio, duration_sec=1.517),
            # Twelve short sentences -> twelve caption cards, all sharing ONE
            # underlying audio file that must be muxed exactly once.
            Segment(
                "", narration,
                speaker_id="an", visual_asset="reply.png",
                audio_path=multi_audio, duration_sec=multi_duration,
            ),
        ),
        audio_path=solo_audio, duration_sec=1.517 + multi_duration,
    )

    result = __import__("asyncio").run(
        StoryRenderProvider().render(voiceover, tmp_path / "output")
    )

    video_stream_sec = _stream_duration(result.video_path, "v:0")
    audio_stream_sec = _stream_duration(result.video_path, "a:0")
    profile = load_content_profile("ban-so-6")
    expected = expected_story_duration_sec(profile, [1.517, multi_duration])
    tolerance = max(0.25, expected * 0.01)

    # No more than one 30fps frame apart — the exact regression under audit.
    assert abs(video_stream_sec - audio_stream_sec) <= 1 / 30 + 0.01
    assert video_stream_sec == pytest.approx(expected, abs=tolerance)
    assert audio_stream_sec == pytest.approx(expected, abs=tolerance)


def test_story_renderer_is_registered_without_replacing_ai_provider():
    from ytb_pipeline.providers.registry import get_render_provider

    assert get_render_provider("story").name == "story"
    assert get_render_provider("ai").name == "ai"


@pytest.mark.skipif(not Path("/opt/homebrew/bin/ffmpeg").exists(), reason="ffmpeg required")
def test_reconcile_section_streams_holds_last_frame_when_audio_outlasts_video(tmp_path):
    """Audio must never be trimmed; a video shortfall is fixed by holding
    the last frame, not by cutting the audio that outlasts it."""
    from ytb_pipeline.render.story import (
        _audio_duration, _mux_video_audio, _reconcile_section_streams, _render_video_card,
        _video_duration,
    )

    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (640, 360), "red").save(frame)
    video = tmp_path / "video.mp4"
    _render_video_card("ffmpeg", frame, video, frames=30)  # 1.0s video

    audio = tmp_path / "audio.wav"
    _tone(audio, duration=1.15)  # 0.15s longer than the video
    audio_aac = tmp_path / "audio.m4a"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(audio), "-c:a", "aac", "-b:a", "192k", str(audio_aac),
    ], check=True)

    clip = tmp_path / "clip.mp4"
    _mux_video_audio("ffmpeg", video, audio_aac, clip)
    before_audio = _audio_duration(clip)

    fixed = _reconcile_section_streams("ffmpeg", clip, tmp_path, tag="0")

    assert abs(_video_duration(fixed) - _audio_duration(fixed)) <= 1 / 30
    # Audio content itself must be untouched — same length as before fixing.
    assert _audio_duration(fixed) == pytest.approx(before_audio, abs=0.02)
