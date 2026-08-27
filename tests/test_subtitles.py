from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.render.subtitle import (
    SubtitleCue, SubtitleTrack, build_subtitle_track, write_subtitle_artifacts,
)
from ytb_pipeline.render.timeline import NarrationClip, Timeline, VideoClip


def _timeline() -> Timeline:
    clips = tuple(VideoClip(i, i, float(i * 2), 2.0) for i in range(2))
    narration = tuple(NarrationClip(i, i, float(i * 2), 2.0, Path(f"{i}.wav")) for i in range(2))
    return Timeline(30, 1920, 1080, clips, narration, (), 4.0)


def test_subtitles_are_deterministic_and_follow_narration_timing():
    voiceover = SimpleNamespace(segments=(SimpleNamespace(narration="Xin chào\nViệt Nam"), SimpleNamespace(narration="Cảm ơn <bạn>")))
    track = build_subtitle_track(voiceover, _timeline(), language="vi")
    assert track.cues == (
        SubtitleCue(0.0, 2.0, "Xin chào\nViệt Nam"),
        SubtitleCue(2.0, 4.0, "Cảm ơn <bạn>"),
    )
    assert track.to_srt().startswith("1\n00:00:00,000 --> 00:00:02,000")
    assert track.to_vtt().startswith("WEBVTT\n\n")


def test_subtitle_serializers_preserve_unicode_and_write_both_artifacts(tmp_path: Path):
    track = SubtitleTrack("vi", (SubtitleCue(0.0, 1.25, "Đúng & rõ"),))
    srt, vtt = write_subtitle_artifacts(track, tmp_path / "video")
    assert srt.read_text(encoding="utf-8").endswith("Đúng & rõ\n")
    assert "00:00:00.000 --> 00:00:01.250" in vtt.read_text(encoding="utf-8")


def test_subtitle_contract_rejects_invalid_cues():
    with pytest.raises(ValueError):
        SubtitleCue(1.0, 1.0, "x")
    with pytest.raises(ValueError):
        SubtitleTrack("vi", (SubtitleCue(1.0, 2.0, "later"), SubtitleCue(0.0, 1.0, "earlier")))
