"""Timeline contract for static slide clips."""

from pathlib import Path

from ytb_pipeline.render import compose


def test_static_slide_clip_caps_video_to_measured_audio_duration(monkeypatch, tmp_path):
    """Looped still frames must not outlast their segment audio."""
    command = []

    def run(args, **kwargs):
        command.extend(args)

    monkeypatch.setattr(compose, "_audio_duration", lambda audio: 19.222517)
    monkeypatch.setattr(compose.subprocess, "run", run)

    compose._image_audio_clip(tmp_path / "frame.png", tmp_path / "segment.mp3", tmp_path / "clip.mp4")

    assert command[command.index("-t") + 1] == "19.222517"
