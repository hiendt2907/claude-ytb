"""Persistent F5 daemon pool: one resident model per batch lane."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .f5_provider import (
    F5_BATCH_WORKER,
    F5_CKPT,
    F5_DEVICE,
    F5_MAX_CHARS,
    F5_MODEL_ARCH,
    F5_PYTHON,
    F5_REF_AUDIO,
    F5_REF_TEXT_FILE,
    F5_VOCAB,
)


class F5DaemonPool:
    """Own daemon processes for independent batch lanes.

    Each daemon owns one loaded F5 model and listens on its own Unix socket.
    The pool deliberately has no shared work queue: lane 1 and lane 2 can keep
    producing audio independently while their render consumers work downstream.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._processes: dict[int, subprocess.Popen] = {}

    def socket_for(self, lane: int) -> Path:
        return self.root / f"f5-lane-{lane}.sock"

    def start(self, lanes: int) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        ref_text = F5_REF_TEXT_FILE.read_text(encoding="utf-8").strip()
        for lane in range(1, lanes + 1):
            existing = self._processes.get(lane)
            if existing is not None and existing.poll() is None:
                continue
            socket_path = self.socket_for(lane)
            socket_path.unlink(missing_ok=True)
            manifest_path = self.root / f"f5-lane-{lane}.json"
            manifest_path.write_text(json.dumps({
                "model": F5_MODEL_ARCH,
                "ckpt": str(F5_CKPT),
                "vocab": str(F5_VOCAB),
                "device": F5_DEVICE,
                "ref_audio": str(F5_REF_AUDIO),
                "ref_text": ref_text,
                "max_chars": F5_MAX_CHARS,
            }, ensure_ascii=False), encoding="utf-8")
            self._processes[lane] = subprocess.Popen(
                [str(F5_PYTHON), str(F5_BATCH_WORKER), "--serve", str(socket_path), str(manifest_path)],
                env={**os.environ, "PYTHONHASHSEED": "0"},
                start_new_session=True,
            )

    def stop(self) -> None:
        for process in self._processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self._processes.values():
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for lane in self._processes:
            self.socket_for(lane).unlink(missing_ok=True)
        self._processes.clear()
