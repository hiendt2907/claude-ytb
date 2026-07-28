"""F5 device selection stays explicit across every local inference boundary."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import threading
import tempfile
import uuid

import pytest
from pydantic import ValidationError

from ytb_pipeline.config.settings import Settings
from ytb_pipeline.voiceover import f5_daemon_pool, f5_provider, tts


_WORKER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "f5_batch_worker.py"


def _worker_module():
    spec = importlib.util.spec_from_file_location("f5_batch_worker_device", _WORKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_f5_device_defaults_to_mps_and_only_accepts_cpu_or_mps(monkeypatch):
    monkeypatch.delenv("F5_DEVICE", raising=False)
    assert Settings(_env_file=None).f5_device == "mps"

    monkeypatch.setenv("F5_DEVICE", "cpu")
    assert Settings(_env_file=None).f5_device == "cpu"

    monkeypatch.setenv("F5_DEVICE", "cuda")
    with pytest.raises(ValidationError, match="f5_device"):
        Settings(_env_file=None)


def test_direct_f5_cli_forwards_selected_device(monkeypatch, tmp_path):
    out = tmp_path / "voice.wav"
    captured: dict[str, list[str]] = {}

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(command, **_kwargs):
        captured["command"] = command
        out.write_bytes(b"wav")
        return Result()

    monkeypatch.setattr(f5_provider, "F5_DEVICE", "cpu")
    monkeypatch.setattr(f5_provider.subprocess, "run", fake_run)

    f5_provider._f5_once("Một câu kiểm thử.", "ref", out)

    device_index = captured["command"].index("--device")
    assert captured["command"][device_index + 1] == "cpu"


def test_one_shot_batch_manifest_forwards_selected_device(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    monkeypatch.setattr(f5_provider, "F5_DEVICE", "cpu")
    monkeypatch.setattr(f5_provider, "_require", lambda *_args: None)

    class FakeProcess:
        stdout: list[str] = []

        def __init__(self, command, **_kwargs):
            captured["manifest"] = json.loads(Path(command[-1]).read_text(encoding="utf-8"))

        def wait(self):
            return 0

    monkeypatch.setattr(f5_provider.subprocess, "Popen", FakeProcess)
    f5_provider.run_batch([{"text": "Kiểm thử.", "out": str(tmp_path / "out.wav")}])

    assert captured["manifest"]["device"] == "cpu"


def test_daemon_pool_manifest_forwards_selected_device(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **_kwargs):
        captured["manifest"] = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        return FakeProcess()

    monkeypatch.setattr(f5_daemon_pool, "F5_DEVICE", "cpu")
    monkeypatch.setattr(f5_daemon_pool.subprocess, "Popen", fake_popen)

    f5_daemon_pool.F5DaemonPool(tmp_path).start(1)

    assert captured["manifest"]["device"] == "cpu"


def test_worker_device_boundary_rejects_unknown_device_and_daemon_mismatch():
    worker = _worker_module()

    assert worker._inference_device({"device": "mps"}) == "mps"
    assert worker._inference_device({"device": "cpu"}) == "cpu"
    with pytest.raises(ValueError, match="mps.*cpu"):
        worker._inference_device({"device": "cuda"})
    with pytest.raises(ValueError, match="device.*không khớp"):
        worker._validate_daemon_request_device({"device": "cpu"}, {"device": "mps"})


def test_daemon_client_sends_device_and_fails_closed_on_mismatch(monkeypatch, tmp_path):
    socket_path = Path(tempfile.gettempdir()) / f"f5d-{uuid.uuid4().hex[:8]}.sock"
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
            stream.write(b'{"event":"error","detail":"device khong khop"}\n')
            stream.flush()
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    assert ready.wait(timeout=1)
    monkeypatch.setattr(f5_provider, "F5_DEVICE", "cpu")

    with pytest.raises(RuntimeError, match="device khong khop"):
        f5_provider.run_daemon_batch(socket_path, [{"text": "xin chao", "out": "out.wav"}])

    thread.join(timeout=1)
    socket_path.unlink(missing_ok=True)
    assert received["device"] == "cpu"


def test_f5_cache_identity_includes_selected_device(monkeypatch, tmp_path):
    monkeypatch.setattr(tts.settings, "tts_provider", "f5")
    monkeypatch.setattr(f5_provider, "F5_DEVICE", "mps")
    segment_mps = tts._segment_audio_path("video", tts.VOICE_KNOWLEDGE, 0)
    piece_mps = tts._f5_piece_audio_path(tmp_path, "video", "knowledge", 0, 0, "nội dung")

    monkeypatch.setattr(f5_provider, "F5_DEVICE", "cpu")
    segment_cpu = tts._segment_audio_path("video", tts.VOICE_KNOWLEDGE, 0)
    piece_cpu = tts._f5_piece_audio_path(tmp_path, "video", "knowledge", 0, 0, "nội dung")

    assert segment_mps != segment_cpu
    assert piece_mps != piece_cpu
