"""Protocol between pipeline voiceover and a resident F5 daemon."""

from __future__ import annotations

import json
import os
import socket
import threading
import tempfile
from pathlib import Path


def test_daemon_client_sends_jobs_and_streams_progress(tmp_path, capsys):
    from ytb_pipeline.voiceover.f5_provider import run_daemon_batch

    socket_path = Path(tempfile.gettempdir()) / f"ytb-f5-{os.getpid()}.sock"
    socket_path.unlink(missing_ok=True)
    received: dict = {}
    ready = threading.Event()

    def serve_once():
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        server.listen(1)
        ready.set()
        conn, _ = server.accept()
        with conn, conn.makefile("rwb") as stream:
            received.update(json.loads(stream.readline()))
            stream.write(b'{"event":"progress","line":"JOB 1/1 ok out.wav"}\n')
            stream.write(b'{"event":"done"}\n')
            stream.flush()
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    assert ready.wait(timeout=1)

    run_daemon_batch(socket_path, [{"text": "xin chao", "out": "out.wav"}])
    thread.join(timeout=1)
    socket_path.unlink(missing_ok=True)

    assert received["jobs"] == [{"text": "xin chao", "out": "out.wav"}]
    assert "JOB 1/1 ok out.wav" in capsys.readouterr().out
