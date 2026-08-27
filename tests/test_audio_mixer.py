from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.render.audio_mixer import mix_timeline_audio
from ytb_pipeline.render.timeline import AudioLayerClip, NarrationClip, Timeline, VideoClip


def _timeline(*, music=(), sfx=()):
    return Timeline(30, 1920, 1080, (VideoClip(0, 0, 0, 4),), (NarrationClip(0, 0, 0, 4, Path("n.wav")),), (), 4, music_clips=music, sfx_clips=sfx)


def test_narration_only_mixer_is_a_noop(tmp_path):
    video = tmp_path / "video.mp4"
    assert mix_timeline_audio("ffmpeg", video, tmp_path / "out.mp4", _timeline()) == video


def test_mixer_builds_single_narration_mix_with_music_and_sfx(tmp_path, monkeypatch):
    music, sfx = tmp_path / "music.wav", tmp_path / "sfx.wav"
    music.write_bytes(b"x"); sfx.write_bytes(b"x")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="audio\n")
    monkeypatch.setattr("ytb_pipeline.render.audio_mixer.subprocess.run", run)
    timeline = _timeline(music=(AudioLayerClip(music, 0, 4, gain_db=-20, loop=True),), sfx=(AudioLayerClip(sfx, 3.5, .5, gain_db=-8),))
    mix_timeline_audio("ffmpeg", tmp_path / "video.mp4", tmp_path / "out.mp4", timeline)
    command = calls[-1]
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:a]" in graph and "amix=inputs=3:duration=first" in graph
    assert "volume=-20dB" in graph and "adelay=3500|3500" in graph


def test_configured_missing_media_fails_clearly(tmp_path):
    timeline = _timeline(music=(AudioLayerClip(tmp_path / "missing.wav", 0, 4),))
    with pytest.raises(ValueError, match="thiếu"):
        mix_timeline_audio("ffmpeg", tmp_path / "video.mp4", tmp_path / "out.mp4", timeline)
