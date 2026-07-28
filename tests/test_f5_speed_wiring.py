"""Regression coverage for F5 acoustic-speed propagation and cache invalidation."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import socket
import threading
import tempfile
import uuid

import pytest

from ytb_pipeline.voiceover import f5_provider, tts


def _worker_module():
    worker_path = Path(__file__).resolve().parents[1] / "scripts" / "f5_batch_worker.py"
    spec = importlib.util.spec_from_file_location("f5_batch_worker_speed_wiring", worker_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_worker_legacy_manifest_defaults_to_the_calibrated_speed():
    assert _worker_module()._inference_speed({}) == 0.30


def test_daemon_worker_fails_closed_when_client_speed_differs():
    worker = _worker_module()

    with pytest.raises(ValueError, match="inference_speed.*không khớp"):
        worker._validate_daemon_request_speed(
            {"inference_speed": 0.85}, {"inference_speed": 0.30}
        )


def test_daemon_client_sends_speed_and_surfaces_a_mismatch(tmp_path):
    socket_path = Path(tempfile.gettempdir()) / f"ytb-f5-speed-{uuid.uuid4().hex[:8]}.sock"
    socket_path.unlink(missing_ok=True)
    received: dict[str, object] = {}
    ready = threading.Event()

    def serve_once():
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        server.listen(1)
        ready.set()
        conn, _ = server.accept()
        with conn, conn.makefile("rwb") as stream:
            received.update(json.loads(stream.readline()))
            stream.write(b'{"event":"error","detail":"inference_speed khong khop"}\n')
            stream.flush()
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    assert ready.wait(timeout=1)

    with pytest.raises(RuntimeError, match="inference_speed khong khop"):
        f5_provider.run_daemon_batch(socket_path, [{"text": "xin chao", "out": "out.wav"}])

    thread.join(timeout=1)
    socket_path.unlink(missing_ok=True)
    assert received["inference_speed"] == f5_provider.F5_INFERENCE_SPEED
