"""Test resume (skip job đã có) trong worker F5-TTS batch.

`scripts/f5_batch_worker.py` không phải package (chạy trong `.venv-tts`), nạp
qua importlib từ đường dẫn file để test được trong `.venv` chính.
"""

import importlib.util
import json
import sys
import wave
from pathlib import Path

import pytest

_WORKER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "f5_batch_worker.py"
_spec = importlib.util.spec_from_file_location("f5_batch_worker", _WORKER_PATH)
worker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker)


def _write_valid_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00\x00" * 100)


@pytest.mark.unit
def test_is_valid_wav_true_for_real_wav(tmp_path):
    p = tmp_path / "ok.wav"
    _write_valid_wav(p)
    assert worker._is_valid_wav(p) is True


@pytest.mark.unit
def test_is_valid_wav_false_for_corrupt_file(tmp_path):
    p = tmp_path / "bad.wav"
    p.write_bytes(b"not a wav")
    assert worker._is_valid_wav(p) is False


@pytest.mark.unit
def test_is_valid_wav_false_for_missing_file(tmp_path):
    assert worker._is_valid_wav(tmp_path / "missing.wav") is False


@pytest.mark.unit
def test_main_skips_job_with_existing_valid_wav(tmp_path, monkeypatch, capsys):
    done = tmp_path / "done.wav"
    _write_valid_wav(done)
    pending = tmp_path / "pending.wav"

    manifest = {
        "model": "F5TTS_Base", "ckpt": "ckpt", "vocab": "vocab", "device": "cpu",
        "ref_audio": "ref.wav", "ref_text": "ref",
        "jobs": [
            {"text": "đã xong", "out": str(done)},
            {"text": "chưa xong", "out": str(pending)},
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    calls = []

    class _FakeTTS:
        def __init__(self, **kwargs):
            pass

        def infer(self, **kwargs):
            calls.append(kwargs["file_wave"])
            _write_valid_wav(Path(kwargs["file_wave"]))

    fake_module = type(sys)("f5_tts.api")
    fake_module.F5TTS = _FakeTTS
    monkeypatch.setitem(sys.modules, "f5_tts.api", fake_module)
    monkeypatch.setattr(sys, "argv", ["f5_batch_worker.py", str(manifest_path)])

    code = worker.main()

    assert code == 0
    assert calls == [str(pending)]  # job "done" KHÔNG được render lại
    out = capsys.readouterr().out
    assert "JOB 1/2 skip (đã có)" in out
    assert "JOB 2/2 ok" in out
