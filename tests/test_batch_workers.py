from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from ytb_pipeline.orchestrator import batch_cli as cli


def test_select_pending_batch_returns_distinct_items_up_to_worker_limit():
    queue = [
        cli.QueueItem(1, "done", "", "queued"),
        cli.QueueItem(2, "first", "", "queued"),
        cli.QueueItem(3, "second", "", "queued"),
        cli.QueueItem(4, "third", "", "queued"),
    ]

    selected = cli.select_pending_batch(queue, {"done"}, worker_count=2)

    assert [item.slug for item in selected] == ["first", "second"]


def test_select_pending_batch_never_exceeds_two_workers():
    queue = [cli.QueueItem(day, f"video-{day}", "", "queued") for day in range(4)]

    selected = cli.select_pending_batch(queue, set(), worker_count=99)

    assert [item.slug for item in selected] == ["video-0", "video-1"]


def test_cmd_run_starts_at_most_two_controlled_workers(monkeypatch):
    calls: list[int] = []
    results = iter([True, True, False, False])

    def fake_process_next(**_kwargs) -> bool:
        calls.append(1)
        return next(results)

    monkeypatch.setattr(cli, "process_next", fake_process_next)

    cli.cmd_run(argparse.Namespace(loop=True, workers=99, schedule=False))

    assert len(calls) == 4


def test_cmd_run_refills_finished_worker_without_waiting_for_slow_worker(monkeypatch):
    """Worker rảnh phải nhận việc mới trước khi worker khác hoàn tất wave cũ."""
    slow_started = threading.Event()
    release_slow_worker = threading.Event()
    fast_worker_refilled = threading.Event()
    scheduler_finished = threading.Event()
    calls_by_worker: dict[int, int] = {}

    def fake_process_next(*, worker_id: int, **_kwargs) -> bool:
        calls_by_worker[worker_id] = calls_by_worker.get(worker_id, 0) + 1
        call_number = calls_by_worker[worker_id]
        if worker_id == 1 and call_number == 1:
            slow_started.set()
            assert release_slow_worker.wait(timeout=1)
            return True
        if worker_id == 2 and call_number == 1:
            return True
        if worker_id == 2 and call_number == 2:
            fast_worker_refilled.set()
        return False

    monkeypatch.setattr(cli, "process_next", fake_process_next)
    cli._stop_requested = False
    runner = threading.Thread(
        target=lambda: (cli.cmd_run(argparse.Namespace(loop=True, workers=2, schedule=False)), scheduler_finished.set()),
    )
    runner.start()

    try:
        assert slow_started.wait(timeout=1)
        assert fast_worker_refilled.wait(timeout=0.3)
    finally:
        release_slow_worker.set()
        assert scheduler_finished.wait(timeout=1)
        runner.join(timeout=1)


def test_cmd_run_keeps_other_worker_running_when_one_future_crashes(tmp_path, monkeypatch):
    calls_by_worker: dict[int, int] = {}

    def fake_process_next(*, worker_id: int, **_kwargs) -> bool:
        calls_by_worker[worker_id] = calls_by_worker.get(worker_id, 0) + 1
        if worker_id == 1:
            raise OSError("verify transport failed")
        return calls_by_worker[worker_id] == 1

    monkeypatch.setattr(cli, "process_next", fake_process_next)
    monkeypatch.setattr(cli, "WORKER_STATE_PATH", tmp_path / "batch_workers.json")
    cli._stop_requested = False

    cli.cmd_run(argparse.Namespace(loop=True, workers=2, schedule=False))

    assert calls_by_worker[1] == 1
    assert calls_by_worker[2] == 2


def test_parallel_process_next_claims_each_slug_once(tmp_path, monkeypatch):
    queue_path = tmp_path / "auto_state.json"
    queue_path.write_text(json.dumps({
        "shorts_funnel_batch_test": {
            "long_videos": [
                {"day": 1, "slug": "first", "publish_at": ""},
                {"day": 2, "slug": "second", "publish_at": ""},
            ]
        }
    }), encoding="utf-8")
    ledger_path = tmp_path / "ledger.md"
    ledger_path.write_text("| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n", encoding="utf-8")
    barrier = threading.Barrier(2)
    claimed: list[str] = []

    def fake_run(item, **_kwargs):
        claimed.append(item.slug)
        barrier.wait(timeout=1)
        return False, "intentional test failure"

    monkeypatch.setattr(cli, "run_with_retry", fake_run)
    cli._claimed_slugs.clear()
    cli._stop_requested = False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: cli.process_next(queue_path, ledger_path), range(2)))

    assert results == [True, True]
    assert set(claimed) == {"first", "second"}


def test_cmd_status_reports_active_worker_stage_elapsed_and_last_error(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "batch_workers.json"
    state_path.write_text(json.dumps({
        "1": {
            "slug": "focus-loop",
            "stage": "running-render",
            "started_at": "2026-07-15T10:00:00+07:00",
            "last_error": "",
        },
        "2": {
            "slug": "old-video",
            "stage": "idle",
            "started_at": "",
            "last_error": "missing audio",
        },
    }), encoding="utf-8")
    monkeypatch.setattr(cli, "WORKER_STATE_PATH", state_path)
    monkeypatch.setattr(cli, "load_queue", lambda: [])
    monkeypatch.setattr(cli, "done_slugs", lambda: set())

    cli.cmd_status(argparse.Namespace())

    output = capsys.readouterr().out
    assert "worker 1" in output
    assert "focus-loop" in output
    assert "running-render" in output
    assert "elapsed=" in output
    assert "missing audio" in output
