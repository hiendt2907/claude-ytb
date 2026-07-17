"""Protocol between pipeline voiceover and a resident F5 daemon."""

from __future__ import annotations

import json
import socket
import threading


def test_daemon_client_sends_jobs_and_streams_progress(tmp_path, capsys):
    from ytb_pipeline.voiceover.f5_provider import run_daemon_batch

    socket_path = tmp_path / "f5.sock"
    received: dict = {}

    def serve_once():
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        server.listen(1)
        conn, _ = server.accept()
        with conn, conn.makefile("rwb") as stream:
            received.update(json.loads(stream.readline()))
            stream.write(b'{"event":"progress","line":"JOB 1/1 ok out.wav"}\n')
            stream.write(b'{"event":"done"}\n')
            stream.flush()
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    while not socket_path.exists():
        pass

    run_daemon_batch(socket_path, [{"text": "xin chao", "out": "out.wav"}])
    thread.join(timeout=1)

    assert received["jobs"] == [{"text": "xin chao", "out": "out.wav"}]
    assert "JOB 1/1 ok out.wav" in capsys.readouterr().out
