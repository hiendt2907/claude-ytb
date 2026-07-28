"""Regression coverage for F5 acoustic-speed propagation and cache invalidation."""

from __future__ import annotations

import json
from pathlib import Path

from ytb_pipeline.voiceover import f5_provider, tts


def test_direct_f5_cli_forwards_the_duration_calibration(monkeypatch, tmp_path):
    output = tmp_path / "voice.wav"
    captured: dict[str, list[str]] = {}

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(command, **_kwargs):
        captured["command"] = command
        output.write_bytes(b"wav")
        return Result()

    monkeypatch.setattr(f5_provider.subprocess, "run", fake_run)

    f5_provider._f5_once("Một câu kiểm thử.", "ref", output)

    speed_index = captured["command"].index("--speed")
    assert captured["command"][speed_index + 1] == str(f5_provider.F5_INFERENCE_SPEED)


def test_batch_manifest_forwards_the_duration_calibration(monkeypatch, tmp_path):
    output = tmp_path / "voice.wav"
    captured: dict[str, object] = {}

    monkeypatch.setattr(f5_provider, "_require", lambda *_args: None)

    class FakeProcess:
        stdout: list[str] = []

        def __init__(self, command, **_kwargs):
            manifest_path = Path(command[-1])
            captured["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))

        def wait(self):
            return 0

    monkeypatch.setattr(f5_provider.subprocess, "Popen", FakeProcess)

    f5_provider.run_batch([{"text": "Một câu kiểm thử.", "out": str(output)}])

    assert captured["manifest"]["inference_speed"] == f5_provider.F5_INFERENCE_SPEED


def test_f5_segment_cache_path_changes_with_acoustic_speed(monkeypatch):
    monkeypatch.setattr(tts.settings, "tts_provider", "f5")
    monkeypatch.setattr(f5_provider, "F5_INFERENCE_SPEED", 0.30)
    slow = tts._segment_audio_path("video", tts.VOICE_KNOWLEDGE, 0)

    monkeypatch.setattr(f5_provider, "F5_INFERENCE_SPEED", 0.85)
    fast = tts._segment_audio_path("video", tts.VOICE_KNOWLEDGE, 0)

    assert slow != fast
