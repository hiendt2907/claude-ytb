from pathlib import Path

from scripts.verify_voice import verify


def test_verify_voice_writes_metrics_and_graphics(tmp_path, monkeypatch):
    audio = tmp_path / "tone.wav"
    import wave
    import numpy as np
    rate = 16000
    samples = (0.2 * np.sin(2 * np.pi * 220 * np.arange(rate) / rate)).astype(np.float32)
    with wave.open(str(audio), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes((samples * 32767).astype(np.int16).tobytes())
    result = verify(audio, tmp_path / "report")
    assert result["duration_sec"] == 1.0
    assert result["clipping_samples"] == 0
    assert result["median_pitch_hz"] is not None
    assert Path(result["graphics"]["waveform"]).exists()
    assert Path(result["graphics"]["spectrogram"]).exists()
