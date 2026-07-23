"""Các subcommand đơn giản của `ytb batch <lệnh>` (status/verify/retry/stop/...).

Đọc hằng số mutable (PID_PATH, LEDGER_PATH, AUTO_STATE_PATH, ROOT, ...) và các
hàm dùng chung qua `_cli()` tại thời điểm gọi — xem `queue_manager.py::_cli()`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def _cli():
    """Import trễ package batch_cli — xem queue_manager._cli() cho lý do."""
    from .. import batch_cli

    return batch_cli


def cmd_status(args: argparse.Namespace) -> None:
    cli = _cli()
    for worker_id, state in cli.worker_states().items():
        slug = state.get("slug") or "-"
        stage = state.get("stage") or "idle"
        elapsed = cli.worker_elapsed(state)
        error = state.get("last_error") or "-"
        print(f"worker {worker_id}: {slug}  stage={stage}  elapsed={elapsed}  last_error={error}")
    queue = cli.load_queue()
    done = cli.done_slugs()
    for item in queue:
        mark = "✓ done" if item.slug in done else "… pending"
        print(f"day {item.day:>2}  {mark:<10}  {item.slug}  (publish_at={item.publish_at})")


def cmd_verify(args: argparse.Namespace) -> None:
    result = _cli().verify_youtube_video(args.youtube_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_retry(args: argparse.Namespace) -> None:
    cli = _cli()
    queue = cli.load_queue()
    item = next((i for i in queue if i.slug == args.slug), None)
    if item is None:
        print(f"Không tìm thấy slug '{args.slug}' trong queue.")
        return
    ok, _output = cli.run_with_retry(item)
    if cli._stop_requested:
        print(
            "⏸ Đã dừng graceful theo yêu cầu (`ytb batch stop`) — chạy lại lệnh "
            "retry này (hoặc `ytb batch run`) để tiếp tục đúng video."
        )
        return
    print("✓ Thành công" if ok else "✗ Thất bại — xem assets/batch_cli_warnings.log")


def cmd_stop(args: argparse.Namespace) -> None:
    cli = _cli()
    if not cli.PID_PATH.exists():
        print("Không có `ytb batch run`/`retry` nào đang chạy (không thấy assets/batch_cli.pid).")
        return
    pid = int(cli.PID_PATH.read_text(encoding="utf-8").strip())
    try:
        targets = cli._terminate_tracked_batch_tree(pid)
    except ProcessLookupError:
        print(f"Process {pid} đã không còn chạy (pid file cũ) — dọn pid file.")
        cli.PID_PATH.unlink(missing_ok=True)  # đã xác nhận chết hẳn -- xoá vô điều kiện
        return
    print(
        f"✓ Đã gửi lệnh dừng graceful tới {len(targets)} process trong batch tree (root {pid}). "
        "Tiến trình con (render/upload/TTS) được dừng cùng lúc, ledger ghi nhận stage hiện tại "
        "với status 'stopped'. Chạy lại "
        "`ytb batch run --loop` (hoặc `ytb batch retry <slug>`) để tiếp tục ĐÚNG video này."
    )


def cmd_ps(args: argparse.Namespace) -> None:
    cli = _cli()
    if not cli.PID_PATH.exists():
        print("Không có `ytb batch run`/`retry` nào đang chạy.")
        return
    try:
        pid = int(cli.PID_PATH.read_text(encoding="utf-8").strip())
    except (ValueError, FileNotFoundError):
        print("Không có `ytb batch run`/`retry` nào đang chạy.")
        return
    if not cli._pid_alive(pid):
        print(f"Không có tiến trình nào đang chạy (pid file cũ PID {pid} — tiến trình đã chết).")
        cli.PID_PATH.unlink(missing_ok=True)
        return
    elapsed_sec = int((datetime.now() - datetime.fromtimestamp(cli.PID_PATH.stat().st_ctime)).total_seconds())
    elapsed = f"{elapsed_sec // 60}m {elapsed_sec % 60}s"
    slug = cli.current_running_slug()
    if slug:
        print(f"▶ đang chạy: {slug}")
        print(f"  PID: {pid}  |  thời gian: {elapsed}")
        print(f"  xem log: ytb batch logs {slug} -f")
    else:
        print(f"▶ batch đang chạy (PID {pid}, {elapsed}) — chưa có log file (có thể đang ở bước start/khởi tạo).")


def cmd_reset(args: argparse.Namespace) -> None:
    cli = _cli()
    queue = cli.load_queue()
    if not any(i.slug == args.slug for i in queue):
        print(f"✗ '{args.slug}' không có trong queue (auto_state.json) — không thể reset.")
        return
    running = cli.current_running_slug()
    if running == args.slug:
        print(f"✗ '{args.slug}' đang được xử lý. Dùng `ytb batch stop` trước.")
        return
    cli.update_ledger(args.slug, "", "reset", "reset", "Reset thủ công về pending qua `ytb batch reset`")
    # Xoá checkpoint project.json — nếu giữ, WorkflowGraph sẽ skip node DONE cũ
    # và "chạy lại từ đầu" thành no-op.
    project_dir = Path(cli.settings.projects_dir) / args.slug
    if project_dir.exists():
        shutil.rmtree(project_dir)
        print(f"✓ Đã xoá checkpoint {project_dir} (chạy lại từ đầu thật sự).")
    print(f"✓ Đã reset '{args.slug}' về pending — sẽ được `ytb batch run` nhặt ở lượt kế tiếp.")


def cmd_cancel(args: argparse.Namespace) -> None:
    cli = _cli()
    running = cli.current_running_slug()
    if running == args.slug:
        print(f"✗ '{args.slug}' đang được xử lý. Dùng `ytb batch stop` trước rồi cancel.")
        return
    with cli.locked_json_update(cli.AUTO_STATE_PATH) as data:
        batch_keys = sorted(k for k in data if k.startswith("shorts_funnel_batch_"))
        if not batch_keys:
            print("✗ Không tìm thấy batch nào trong auto_state.json.")
            return
        bk = batch_keys[-1]
        removed = False
        for key in ("long_videos", "short_videos"):
            videos = data[bk].get(key, [])
            filtered = [v for v in videos if v["slug"] != args.slug]
            if len(filtered) != len(videos):
                data[bk][key] = filtered
                removed = True
        if not removed:
            print(f"✗ Không tìm thấy slug '{args.slug}' trong queue (batch {bk}).")
            return
    cli.update_ledger(args.slug, "", "cancel", "cancelled", "Huỷ thủ công qua `ytb batch cancel`")
    print(f"✓ Đã huỷ '{args.slug}' khỏi queue — ghi ledger (stage=cancel, status=cancelled).")


def cmd_logs(args: argparse.Namespace) -> None:
    cli = _cli()
    if getattr(args, "current", False):
        slug = cli.current_running_slug()
        if not slug:
            print("Không có tiến trình nào đang chạy.")
            return
        args.slug = slug
        args.follow = True
    path = cli.WARN_LOG_PATH if args.warnings else cli.log_path_for(args.slug)
    if args.follow:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        subprocess.run(["tail", "-f", str(path)])
        return
    text = cli.tail_text(path, args.tail)
    print(text or f"(trống — chưa có log tại {path})")


def cmd_ledger(args: argparse.Namespace) -> None:
    cli = _cli()
    print(cli.tail_text(cli.LEDGER_PATH, args.tail))


def cmd_queue(args: argparse.Namespace) -> None:
    cli = _cli()
    queue = cli.load_queue()
    done = cli.done_slugs()
    rows = [
        {
            "day": item.day,
            "slug": item.slug,
            "publish_at": item.publish_at,
            "status": "done" if item.slug in done else "pending",
        }
        for item in queue
    ]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_analytics(args: argparse.Namespace) -> None:
    """Lưu chỉ số Shorts nhập từ Studio và in quyết định cohort cho ideation."""
    store = _cli().AnalyticsStore()
    if args.action == "baseline":
        store.record_channel_baseline(stayed_to_watch=args.stayed_to_watch)
        print(f"✓ Đã lưu baseline Stayed to watch: {args.stayed_to_watch:.1%}")
        return
    if args.action == "snapshot":
        store.record_snapshot(
            args.slug,
            {
                "format_id": args.format_id,
                "age_hours": args.age_hours,
                "stayed_to_watch": args.stayed_to_watch,
                "short_to_long_clicks": args.short_to_long_clicks,
                "subscribers_gained": args.subscribers_gained,
            },
        )
        print(f"✓ Đã lưu snapshot Short: {args.slug}")
        return
    summaries = store.feedback_summary()
    print("\n".join(summaries) if summaries else "Chưa có dữ liệu đủ 48 giờ để kết luận.")


def cmd_reconcile(args: argparse.Namespace) -> None:
    summary = _cli().reconcile_batch_state(getattr(args, "batch_key", "") or None)
    print(f"✓ Reconciled: done={summary['done']} pending={summary['pending']} error={summary['error']}")


def cmd_auth(args: argparse.Namespace) -> None:
    """Đăng nhập lại tương tác (mở browser) cho cả YouTube + Drive — chạy TAY khi
    `ytb doctor` báo token hết hạn, hoặc sau khi đổi publishing status trên Cloud Console."""
    from ...publish.youtube_auth import get_drive_client, get_youtube_client

    print("▶ Đăng nhập YouTube (brand channel)...")
    get_youtube_client(allow_interactive=True)
    print("✓ YouTube OK.")
    print("▶ Đăng nhập Drive (tài khoản cá nhân)...")
    get_drive_client(allow_interactive=True)
    print("✓ Drive OK.")
    print("\n✓ Token đã lưu — chạy `ytb batch doctor` để xác nhận.")


def cmd_benchmark_local(args: argparse.Namespace) -> None:
    cli = _cli()
    report = cli.run_local_benchmark(args.output)
    print(cli.format_benchmark_report(report))
    print(f"\n✓ Đã ghi benchmark: {args.output}")
