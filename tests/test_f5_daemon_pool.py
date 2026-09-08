"""F5 daemon pool keeps one model resident per batch lane."""

from __future__ import annotations


def test_f5_daemon_pool_starts_one_daemon_per_lane_and_exposes_its_socket(tmp_path, monkeypatch):
    from ytb_pipeline.voiceover import f5_daemon_pool

    calls = []

    class FakeProcess:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            calls.append(("wait", timeout))

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(f5_daemon_pool.subprocess, "Popen", fake_popen)
    pool = f5_daemon_pool.F5DaemonPool(tmp_path)

    pool.start(2)

    assert pool.socket_for(1) != pool.socket_for(2)
    assert len([entry for entry in calls if isinstance(entry, tuple)]) == 2
    assert all("--serve" in entry[0] for entry in calls if isinstance(entry, tuple))

    pool.stop()
    assert calls.count("terminate") == 2
