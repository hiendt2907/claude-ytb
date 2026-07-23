"""Worker state (assets/batch_workers.json) + vòng lặp xử lý queue.

Mọi tên "có thể bị test patch qua `batch_cli.<TÊN>`" (WORKER_STATE_PATH,
MAX_BATCH_WORKERS, _stop_requested, _claimed_slugs, _queue_claim_lock, và các
hàm dùng chung như load_queue/done_slugs/run_with_retry/process_next/...)
đọc qua `_cli()` tại thời điểm gọi — xem `queue_manager.py::_cli()`.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path


def _cli():
    """Import trễ package batch_cli — xem queue_manager._cli() cho lý do."""
    from .. import batch_cli

    return batch_cli


def worker_states() -> dict[str, dict]:
    path = _cli().WORKER_STATE_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def update_worker_state(
    worker_id: int | str, *, slug: str, stage: str, last_error: str = "", started_at: str | None = None
) -> None:
    cli = _cli()
    with cli.locked_json_update(cli.WORKER_STATE_PATH) as data:
        data[str(worker_id)] = {
            "slug": slug,
            "stage": stage,
            "started_at": started_at or datetime.now().astimezone().isoformat(timespec="seconds"),
            "last_error": last_error,
        }


def worker_elapsed(state: dict) -> str:
    started_at = state.get("started_at")
    if not started_at:
        return "-"
    try:
        seconds = max(0, int((datetime.now().astimezone() - datetime.fromisoformat(started_at)).total_seconds()))
    except ValueError:
        return "?"
    return f"{seconds // 60}m {seconds % 60}s"


def select_pending_batch(queue: list, blocked_slugs: set, *, worker_count: int) -> list:
    """Choose distinct pending items for one controlled worker wave.

    The hard cap is intentional: rendering and local inference are expensive, and
    P0 starts with at most two concurrent videos regardless of caller input.
    """
    limit = min(_cli().MAX_BATCH_WORKERS, max(1, worker_count))
    selected = []
    for item in queue:
        if item.slug in blocked_slugs:
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


def _claim_next_staged():
    """Reserve one pending video until its render/upload consumer finalizes it."""
    cli = _cli()
    with cli._queue_claim_lock:
        queue = cli.load_queue()
        done = cli.done_slugs()
        failed = cli.failed_slugs()
        item = cli.next_pending(queue, done | failed | cli._claimed_slugs)
        if item is not None:
            cli._claimed_slugs.add(item.slug)
        return item


def _release_staged_claim(item) -> None:
    cli = _cli()
    with cli._queue_claim_lock:
        cli._claimed_slugs.discard(item.slug)


def _record_stage_failure(item, output: str, *, worker_id: str) -> None:
    cli = _cli()
    if cli._stop_requested:
        return
    cli.update_worker_state(worker_id, slug=item.slug, stage="error", last_error=output[-500:])
    failed_stage = cli.last_stage_for_slug(item.slug).removeprefix("running-") or "voiceover"
    cli.update_ledger(item.slug, "", failed_stage, "error", "Tự động: thất bại, xem assets/batch_cli_warnings.log")


def _run_f5_voiceover_lane(item, lane: int, socket_path: Path):
    """Produce audio only; the daemon remains resident for the lane's next item."""
    cli = _cli()
    worker_id = f"tts-{lane}"
    print(f"▶ TTS lane {lane}: '{item.slug}'")
    result = cli.run_with_retry(
        item,
        worker_id=worker_id,
        run_fn=lambda queued, **_kwargs: cli.run_pipeline_once(
            queued,
            worker_id=worker_id,
            through="voiceover",
            f5_daemon_socket=socket_path,
            initial_stage="starting-voiceover",
        ),
    )
    return item, *result


def _run_render_publish_lane(item, lane: int) -> None:
    """Consume one completed voiceover while its paired F5 lane moves on."""
    cli = _cli()
    worker_id = f"render-{lane}"
    try:
        print(f"▶ Render/upload lane {lane}: '{item.slug}'")
        ok, output = cli.run_with_retry(
            item,
            worker_id=worker_id,
            run_fn=lambda queued, **_kwargs: cli.run_pipeline_once(
                queued,
                worker_id=worker_id,
                through="publish",
                initial_stage="starting-render",
            ),
        )
        if cli._stop_requested:
            return
        if not ok:
            cli._record_stage_failure(item, output, worker_id=worker_id)
            return
        cli.finalize_published_item(item, output, worker_id=worker_id)
    finally:
        cli._release_staged_claim(item)


def cmd_run_f5_staged(args: argparse.Namespace) -> None:
    """Run two persistent F5 producers and one render/upload consumer per lane.

    A lane is intentionally not a full pipeline worker.  When its voiceover
    finishes, the video enters that lane's render/upload queue and the same
    resident F5 daemon immediately accepts the next script.
    """
    cli = _cli()
    pool = cli.F5DaemonPool(cli.ROOT / "assets" / "f5-daemons")
    voice_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ytb-f5")
    render_executors = {
        lane: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"ytb-render-{lane}")
        for lane in (1, 2)
    }
    voice_futures: dict[object, tuple[int, object]] = {}
    render_futures: dict[object, int] = {}

    def schedule_voice(lane: int) -> bool:
        if cli._stop_requested:
            return False
        item = cli._claim_next_staged()
        if item is None:
            return False
        future = voice_executor.submit(cli._run_f5_voiceover_lane, item, lane, pool.socket_for(lane))
        voice_futures[future] = (lane, item)
        return True

    try:
        pool.start(2)
        active = sum(schedule_voice(lane) for lane in (1, 2))
        if not active:
            print("✓ Queue đã hết — không còn video pending.")

        while voice_futures or render_futures:
            completed, _ = wait(set(voice_futures) | set(render_futures), return_when=FIRST_COMPLETED)
            for future in completed:
                if future in voice_futures:
                    lane, claimed_item = voice_futures.pop(future)
                    try:
                        item, ok, output = future.result()
                    except Exception as exc:  # noqa: BLE001 -- preserve the other lane
                        message = f"TTS lane {lane} dừng vì lỗi không bắt được: {exc}"
                        print(f"⚠ {message}")
                        cli.emit_warning(message)
                        cli.update_worker_state(f"tts-{lane}", slug=claimed_item.slug, stage="error", last_error=str(exc))
                        cli.update_ledger(claimed_item.slug, "", "voiceover", "error", "Tự động: worker TTS lỗi không bắt được")
                        cli._release_staged_claim(claimed_item)
                    else:
                        if cli._stop_requested:
                            cli._release_staged_claim(item)
                        elif ok:
                            render = render_executors[lane].submit(cli._run_render_publish_lane, item, lane)
                            render_futures[render] = lane
                        else:
                            cli._record_stage_failure(item, output, worker_id=f"tts-{lane}")
                            cli._release_staged_claim(item)
                    schedule_voice(lane)
                else:
                    lane = render_futures.pop(future)
                    try:
                        future.result()
                    except Exception as exc:  # noqa: BLE001 -- render failure must not stop TTS lane
                        message = f"Render/upload lane {lane} dừng vì lỗi không bắt được: {exc}"
                        print(f"⚠ {message}")
                        cli.emit_warning(message)
    finally:
        pool.stop()
        voice_executor.shutdown(wait=True)
        for executor in render_executors.values():
            executor.shutdown(wait=True)


def cmd_run(args: argparse.Namespace) -> None:
    cli = _cli()
    through = getattr(args, "through", "publish")
    batch_key = str(getattr(args, "batch_key", "") or "").strip() or None
    if batch_key is not None:
        try:
            known_batches = json.loads(cli.AUTO_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"✗ Không đọc được queue batch: {exc}") from exc
        if batch_key not in known_batches:
            raise SystemExit(f"✗ Không tìm thấy batch '{batch_key}' trong assets/auto_state.json.")
    if getattr(args, "schedule", False):
        cli.schedule_pending_videos(args)
    worker_count = min(cli.MAX_BATCH_WORKERS, max(1, getattr(args, "workers", 1)))
    if args.loop and worker_count == 2 and cli.settings.tts_provider == "f5" and batch_key is None:
        cli.cmd_run_f5_staged(args)
        return
    # Render-only runs are smoke tests, not terminal queue completion.  Keep a
    # per-invocation set so --loop reaches every item once without marking any
    # video published/done or rerendering the first item forever.
    completed_render_slugs: set[str] | None = set() if through == "render" else None
    slots = worker_count if args.loop else 1
    with ThreadPoolExecutor(max_workers=slots, thread_name_prefix="ytb-batch") as executor:
        running = {
            executor.submit(
                cli.process_next, worker_id=worker_id, through=through, batch_key=batch_key,
                completed_render_slugs=completed_render_slugs,
            ): worker_id
            for worker_id in range(1, slots + 1)
        }
        while running:
            completed, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in completed:
                worker_id = running.pop(future)
                try:
                    processed = future.result()
                except Exception as exc:  # noqa: BLE001 — một worker hỏng không được khoá worker còn lại
                    message = f"Worker {worker_id} dừng vì lỗi không bắt được: {exc}"
                    print(f"⚠ {message}")
                    cli.emit_warning(message)
                    cli.update_worker_state(worker_id, slug="-", stage="error", last_error=str(exc))
                    continue
                if args.loop and processed and not cli._stop_requested:
                    running[executor.submit(
                        cli.process_next, worker_id=worker_id, through=through, batch_key=batch_key,
                        completed_render_slugs=completed_render_slugs,
                    )] = worker_id

    if cli._stop_requested:
        print(
            "⏸ Đã dừng graceful theo yêu cầu (`ytb batch stop`) — chạy lại "
            "`ytb batch run`/`run --loop` để tiếp tục đúng video đang dở."
        )
