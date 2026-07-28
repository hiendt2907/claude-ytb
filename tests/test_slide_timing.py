"""Timeline contract for static slide clips."""

import subprocess
import wave

from PIL import Image

from ytb_pipeline.render import compose


def test_static_slide_clip_caps_video_to_measured_audio_duration(monkeypatch, tmp_path):
    """Looped still frames must not outlast their segment audio."""
    command = []

    def run(args, **kwargs):
        command.extend(args)

    monkeypatch.setattr(compose, "_audio_duration", lambda audio: 19.222517)
    monkeypatch.setattr(compose.subprocess, "run", run)

    compose._image_audio_clip(tmp_path / "frame.png", tmp_path / "segment.mp3", tmp_path / "clip.mp4")

    image_input = command.index("-i")
    assert command[image_input - 2:image_input] == ["-t", "19.262517"]


def test_static_slide_clip_does_not_truncate_non_frame_aligned_audio(tmp_path):
    """A 25fps still image must outlast audio that ends between video frames."""
    frame = tmp_path / "frame.png"
    audio = tmp_path / "segment.wav"
    clip = tmp_path / "clip.mp4"
    Image.new("RGB", (32, 32), "black").save(frame)
    sample_rate, samples = 44_100, 44_673  # 1.012993s, not divisible by a 25fps frame.
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * samples)

    compose._image_audio_clip(frame, audio, clip)

    source_duration = _stream_duration(audio, "a")
    output_duration = _stream_duration(clip, "a")
    assert output_duration >= source_duration - 0.001


def _stream_duration(path, stream: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", f"{stream}:0",
         "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())
