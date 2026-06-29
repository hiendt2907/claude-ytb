"""Test resume voiceover (edge-tts): segment đã có audio hợp lệ -> bỏ qua, không gọi lại TTS."""

from pathlib import Path

import pytest

from ytb_pipeline.config.settings import settings
from ytb_pipeline.pkg.models import Script, Segment
from ytb_pipeline.voiceover import tts


@pytest.fixture(autouse=True)
def _isolate_audio_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(settings, "tts_provider", "edge")
    yield


def _script() -> Script:
    return Script(
        topic="t", title="Video Demo", description="d", voice="vi-VN-NamMinhNeural",
        segments=(
            Segment(caption="c1", narration="đoạn một"),
            Segment(caption="c2", narration="đoạn hai"),
        ),
    )


@pytest.mark.unit
def test_synthesize_skips_segment_with_existing_valid_audio(monkeypatch, tmp_path):
    script = _script()
    slug = tts._slugify(script.title)
    seg0_path = tmp_path / f"{slug}_00.mp3"
    seg0_path.write_bytes(b"fake-but-present")  # nội dung không quan trọng, ffprobe bị mock

    synth_calls = []
    monkeypatch.setattr(tts, "_synth_segment", lambda text, voice, out: synth_calls.append(out))

    def _fake_probe(path: Path) -> float:
        if path == seg0_path:
            return 3.5  # segment 0 coi như đã render hợp lệ ở lần chạy trước
        return 2.0

    monkeypatch.setattr(tts, "_probe_duration", _fake_probe)
    monkeypatch.setattr(tts, "_concat_audio", lambda parts, out: None)

    tts.synthesize(script)

    # Segment 0 đã có audio hợp lệ -> KHÔNG gọi lại _synth_segment cho nó.
    assert seg0_path not in synth_calls
    # Segment 1 chưa có file -> phải synth.
    assert tmp_path / f"{slug}_01.mp3" in synth_calls


@pytest.mark.unit
def test_synthesize_resynths_segment_with_corrupt_existing_audio(monkeypatch, tmp_path):
    script = _script()
    slug = tts._slugify(script.title)
    seg0_path = tmp_path / f"{slug}_00.mp3"
    seg0_path.write_bytes(b"corrupt")

    synth_calls = []
    monkeypatch.setattr(tts, "_synth_segment", lambda text, voice, out: synth_calls.append(out))

    import subprocess

    probe_calls = []

    def _fake_probe(path: Path) -> float:
        probe_calls.append(path)
        # Lần đầu kiểm tra file cũ (corrupt) -> raise, coi như chưa xong -> resynth.
        # Lần sau (sau khi resynth) -> trả duration thật bình thường.
        if path == seg0_path and probe_calls.count(path) == 1:
            raise subprocess.CalledProcessError(1, "ffprobe")
        return 2.0

    monkeypatch.setattr(tts, "_probe_duration", _fake_probe)
    monkeypatch.setattr(tts, "_concat_audio", lambda parts, out: None)

    tts.synthesize(script)

    # File cũ hỏng -> coi như chưa xong -> phải resynth.
    assert seg0_path in synth_calls
