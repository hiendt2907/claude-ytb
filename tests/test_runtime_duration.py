"""Runtime gates use actual F5 timing, not only pre-TTS character estimates."""

from pathlib import Path

import pytest

from ytb_pipeline.ideation.generator import chars_per_min_for_provider
from ytb_pipeline.pkg.models import RenderedVideo, Segment, Voiceover
from ytb_pipeline.render import validation as render_validation
from ytb_pipeline.voiceover import validation as voice_validation


def _voiceover(tmp_path: Path, *, video_type: str, duration_sec: float) -> Voiceover:
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    segment = Segment(caption="c", narration="n", audio_path=audio, duration_sec=duration_sec)
    return Voiceover(
        topic="t", title="T", description="d", tags=("a", "b", "c"),
        video_type=video_type, segments=(segment,), audio_path=audio,
        duration_sec=duration_sec,
    )


def _rendered(tmp_path: Path, *, video_type: str) -> RenderedVideo:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    thumbnail = tmp_path / "thumb.jpg"
    thumbnail.write_bytes(b"thumb")
    return RenderedVideo(
        topic="t", title="T", description="d", tags=("a", "b", "c"),
        video_type=video_type, audio_path=tmp_path / "audio.mp3", video_path=video,
        thumbnail_path=thumbnail,
    )


def test_f5_planning_rate_matches_measured_production_pacing():
    assert chars_per_min_for_provider("f5") == 1347.0
    assert chars_per_min_for_provider("edge") == 1197.0


def test_audio_gate_rejects_short_that_f5_spoke_too_fast(monkeypatch, tmp_path):
    voiceover = _voiceover(tmp_path, video_type="short", duration_sec=34.4)
    monkeypatch.setattr(voice_validation, "_duration", lambda _path: 34.4)
    monkeypatch.setattr(voice_validation, "_volume_and_silence", lambda _path: (-20.0, 0.0))

    with pytest.raises(ValueError, match="Short.*ít nhất 60"):
        voice_validation.validate_audio(voiceover)


def test_final_gate_accepts_f5_long_runtime_within_fifteen_minutes(monkeypatch, tmp_path):
    video = _rendered(tmp_path, video_type="long")
    monkeypatch.setattr(render_validation, "_check_not_blank", lambda _path: None)
    monkeypatch.setattr(render_validation, "_ffprobe", lambda _path: {
        "format": {"duration": "840.0"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ],
    })

    render_validation.validate_final_video(video)


def test_final_gate_rejects_long_over_fifteen_minutes(monkeypatch, tmp_path):
    video = _rendered(tmp_path, video_type="long")
    monkeypatch.setattr(render_validation, "_check_not_blank", lambda _path: None)
    monkeypatch.setattr(render_validation, "_ffprobe", lambda _path: {
        "format": {"duration": "900.1"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ],
    })

    with pytest.raises(ValueError, match="Long quá dài 900s"):
        render_validation.validate_final_video(video)
