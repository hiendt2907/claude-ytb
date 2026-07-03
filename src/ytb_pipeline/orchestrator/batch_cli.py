"""CLI gọi tay để sản xuất tiếp batch sau khi kịch bản đã viết xong — không cần Claude.

Mô phỏng lại đúng việc Claude làm tay trong session: đọc queue từ
assets/auto_state.json, bỏ qua slug đã done trong data/ledger.md, chạy
pipeline với env đúng (đặc biệt TELEGRAM_APPROVAL=false để khỏi đụng listener
daemon -> lỗi 409), tự retry lỗi tạm thời, xác minh video thật qua YouTube
Data API (không tin stdout), và bắn MỌI cảnh báo về Telegram + ghi log để
đưa cho Claude fix sau.

Gọi tắt qua `ytb batch <lệnh>` (xem bin/ytb) hoặc:
    python -m ytb_pipeline.orchestrator.batch_cli <lệnh>

Xem `ytb batch <lệnh> --help` để biết chi tiết + ví dụ từng lệnh.

Lưu ý cấu trúc module: logic cụ thể đã tách sang queue_manager.py (queue/ledger),
pipeline_runner.py (chạy subprocess + retry + verify), doctor.py (`ytb batch
doctor`) và ideation_cmd.py (`ytb batch start`). File này import lại toàn bộ tên
đó để giữ đúng interface cũ (`ytb_pipeline.orchestrator.batch_cli.<tên>` vẫn
dùng được, kể cả để monkeypatch trong test) + giữ phần PID management, global
state điều khiển dừng graceful, và `main()`/argparse.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime

from ..claude_cli import build_claude_cmd
from ..config.settings import settings
from ..notify import telegram
from ..publish.youtube_auth import DRIVE_SCOPES, YOUTUBE_SCOPES, ReauthRequiredError
from .cli_args import build_parser
from .doctor import _check_oauth_token, _check_recent_published, cmd_doctor, run_doctor_checks, run_local_doctor_checks
from .ideation_cmd import (
    _build_resume_prompt,
    _build_start_prompt,
    _count_pending_ideation,
    _prompt_start_interactive,
    cmd_start,
)
from .local_benchmark import format_benchmark_report, run_local_benchmark
from .pipeline_runner import (
    RETRY_BACKOFF_SEC,
    STAGE_START_MARKERS,
    TRANSIENT_ERROR_PATTERNS,
    build_env,
    check_schedule_drift,
    detect_stage_marker,
    extract_claimed_video_id,
    is_transient_error,
    log_path_for,
    process_next,
    run_pipeline_once,
    run_with_retry,
    verify_youtube_video,
)
from .queue_manager import (
    AUTO_STATE_PATH,
    LEDGER_PATH,
    PID_PATH,
    PIPELINE_LOG_DIR,
    ROOT,
    WARN_LOG_PATH,
    QueueItem,
    current_running_slug,
    done_slugs,
    emit_warning,
    last_stage_for_slug,
    load_queue,
    next_pending,
    tail_text,
    update_ledger,
)

# Subcommand nào ghi pid file (để `stop` tìm đúng process cần SIGTERM) — chỉ
# những lệnh chạy lâu, lồng subprocess pipeline con (run/retry). `start` (gọi
# Claude) và các lệnh đọc-only khác không cần.
PID_TRACKED_COMMANDS = {"run", "retry"}

# Tiến trình `python -m ytb_pipeline <script>` đang chạy lồng bên trong (nếu
# có) — signal handler forward SIGTERM xuống đây để không bỏ orphan, và cờ
# báo cho run_with_retry/process_next/cmd_run biết là dừng CHỦ ĐỘNG (không
# phải lỗi) để không retry/không ghi cảnh báo trùng.
_current_proc: subprocess.Popen | None = None
_stop_requested = False


def _handle_stop_signal(signum, frame) -> None:  # noqa: ANN001 — chữ ký bắt buộc của signal.signal
    """Bắt SIGTERM/SIGINT: đặt cờ dừng + kill NGAY tiến trình pipeline con (nếu có).

    Không có bước này, tiến trình con `python -m ytb_pipeline <script>` (render/
    upload) sẽ thành orphan khi process cha bị kill — đã xảy ra thật với `/stop`
    qua Telegram (proc.terminate() ở listener.py chỉ kill được batch_cli.py,
    không propagate xuống cây con vì không cùng process group).
    """
    global _stop_requested
    _stop_requested = True
    if _current_proc is not None and _current_proc.poll() is None:
        # killpg (không phải .terminate()) — `_current_proc` được spawn với
        # start_new_session=True nên là leader của 1 process group riêng, gồm cả
        # cháu sâu hơn 1 cấp như worker F5-TTS (.venv-tts/bin/python
        # scripts/f5_batch_worker.py) và ffmpeg do compose_ai.py gọi. .terminate()
        # chỉ kill đúng PID này, để lại các tiến trình cháu chạy mồ côi.
        try:
            os.killpg(_current_proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def check_not_already_running() -> None:
    """Chặn `run`/`retry` chồng lên 1 tiến trình cũ chưa thoát -- 2 process đua nhau
    ghi cùng file audio/render gây hỏng dữ liệu (đã xảy ra thật, xem ledger 23/06)."""
    if not PID_PATH.exists():
        return
    old_pid_text = PID_PATH.read_text(encoding="utf-8").strip()
    if old_pid_text and _pid_alive(int(old_pid_text)):
        raise SystemExit(
            f"✗ Đã có `ytb batch run`/`retry` đang chạy (PID {old_pid_text}). "
            "Dùng `ytb batch stop` để dừng graceful trước, hoặc đợi nó xong."
        )
    PID_PATH.unlink(missing_ok=True)  # pid file cũ, tiến trình đã chết -- dọn rồi chạy tiếp


def write_pid_file() -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid_file() -> None:
    """Chỉ xoá pid file nếu nó vẫn còn ghi đúng PID của tiến trình hiện tại --
    nếu không (1 tiến trình khác đã ghi đè đè lên), giữ nguyên, tránh xoá nhầm
    "dấu vết đang chạy" của tiến trình kia (xem check_not_already_running)."""
    try:
        if PID_PATH.read_text(encoding="utf-8").strip() != str(os.getpid()):
            return
    except FileNotFoundError:
        return
    PID_PATH.unlink(missing_ok=True)


def cmd_status(args: argparse.Namespace) -> None:
    queue = load_queue()
    done = done_slugs()
    for item in queue:
        mark = "✓ done" if item.slug in done else "… pending"
        print(f"day {item.day:>2}  {mark:<10}  {item.slug}  (publish_at={item.publish_at})")


def cmd_run(args: argparse.Namespace) -> None:
    while True:
        processed = process_next()
        if _stop_requested:
            print(
                "⏸ Đã dừng graceful theo yêu cầu (`ytb batch stop`) — chạy lại "
                "`ytb batch run`/`run --loop` để tiếp tục đúng video đang dở."
            )
            break
        if not processed or not args.loop:
            break


def cmd_verify(args: argparse.Namespace) -> None:
    result = verify_youtube_video(args.youtube_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_retry(args: argparse.Namespace) -> None:
    queue = load_queue()
    item = next((i for i in queue if i.slug == args.slug), None)
    if item is None:
        print(f"Không tìm thấy slug '{args.slug}' trong queue.")
        return
    ok, _output = run_with_retry(item)
    if _stop_requested:
        print(
            "⏸ Đã dừng graceful theo yêu cầu (`ytb batch stop`) — chạy lại lệnh "
            "retry này (hoặc `ytb batch run`) để tiếp tục đúng video."
        )
        return
    print("✓ Thành công" if ok else "✗ Thất bại — xem assets/batch_cli_warnings.log")


def cmd_stop(args: argparse.Namespace) -> None:
    if not PID_PATH.exists():
        print("Không có `ytb batch run`/`retry` nào đang chạy (không thấy assets/batch_cli.pid).")
        return
    pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"Process {pid} đã không còn chạy (pid file cũ) — dọn pid file.")
        PID_PATH.unlink(missing_ok=True)  # đã xác nhận chết hẳn -- xoá vô điều kiện
        return
    print(
        f"✓ Đã gửi lệnh dừng graceful tới process {pid}. Tiến trình con (render/upload) sẽ bị "
        "kill an toàn ngay, ledger ghi nhận stage hiện tại với status 'stopped'. Chạy lại "
        "`ytb batch run --loop` (hoặc `ytb batch retry <slug>`) để tiếp tục ĐÚNG video này."
    )


def cmd_ps(args: argparse.Namespace) -> None:
    if not PID_PATH.exists():
        print("Không có `ytb batch run`/`retry` nào đang chạy.")
        return
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (ValueError, FileNotFoundError):
        print("Không có `ytb batch run`/`retry` nào đang chạy.")
        return
    if not _pid_alive(pid):
        print(f"Không có tiến trình nào đang chạy (pid file cũ PID {pid} — tiến trình đã chết).")
        PID_PATH.unlink(missing_ok=True)
        return
    elapsed_sec = int((datetime.now() - datetime.fromtimestamp(PID_PATH.stat().st_ctime)).total_seconds())
    elapsed = f"{elapsed_sec // 60}m {elapsed_sec % 60}s"
    slug = current_running_slug()
    if slug:
        print(f"▶ đang chạy: {slug}")
        print(f"  PID: {pid}  |  thời gian: {elapsed}")
        print(f"  xem log: ytb batch logs {slug} -f")
    else:
        print(f"▶ batch đang chạy (PID {pid}, {elapsed}) — chưa có log file (có thể đang ở bước start/khởi tạo).")


def cmd_reset(args: argparse.Namespace) -> None:
    queue = load_queue()
    if not any(i.slug == args.slug for i in queue):
        print(f"✗ '{args.slug}' không có trong queue (auto_state.json) — không thể reset.")
        return
    running = current_running_slug()
    if running == args.slug:
        print(f"✗ '{args.slug}' đang được xử lý. Dùng `ytb batch stop` trước.")
        return
    update_ledger(args.slug, "", "reset", "reset", "Reset thủ công về pending qua `ytb batch reset`")
    print(f"✓ Đã reset '{args.slug}' về pending — sẽ được `ytb batch run` nhặt ở lượt kế tiếp.")


def cmd_cancel(args: argparse.Namespace) -> None:
    running = current_running_slug()
    if running == args.slug:
        print(f"✗ '{args.slug}' đang được xử lý. Dùng `ytb batch stop` trước rồi cancel.")
        return
    data = json.loads(AUTO_STATE_PATH.read_text(encoding="utf-8"))
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
    AUTO_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    update_ledger(args.slug, "", "cancel", "cancelled", "Huỷ thủ công qua `ytb batch cancel`")
    print(f"✓ Đã huỷ '{args.slug}' khỏi queue — ghi ledger (stage=cancel, status=cancelled).")


def cmd_logs(args: argparse.Namespace) -> None:
    if getattr(args, "current", False):
        slug = current_running_slug()
        if not slug:
            print("Không có tiến trình nào đang chạy.")
            return
        args.slug = slug
        args.follow = True
    path = WARN_LOG_PATH if args.warnings else log_path_for(args.slug)
    if args.follow:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        subprocess.run(["tail", "-f", str(path)])
        return
    text = tail_text(path, args.tail)
    print(text or f"(trống — chưa có log tại {path})")


def cmd_ledger(args: argparse.Namespace) -> None:
    print(tail_text(LEDGER_PATH, args.tail))


def cmd_queue(args: argparse.Namespace) -> None:
    queue = load_queue()
    done = done_slugs()
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


def cmd_auth(args: argparse.Namespace) -> None:
    """Đăng nhập lại tương tác (mở browser) cho cả YouTube + Drive — chạy TAY khi
    `ytb doctor` báo token hết hạn, hoặc sau khi đổi publishing status trên Cloud Console."""
    from ..publish.youtube_auth import get_drive_client, get_youtube_client

    print("▶ Đăng nhập YouTube (brand channel)...")
    get_youtube_client(allow_interactive=True)
    print("✓ YouTube OK.")
    print("▶ Đăng nhập Drive (tài khoản cá nhân)...")
    get_drive_client(allow_interactive=True)
    print("✓ Drive OK.")
    print("\n✓ Token đã lưu — chạy `ytb batch doctor` để xác nhận.")


def cmd_benchmark_local(args: argparse.Namespace) -> None:
    report = run_local_benchmark(args.output)
    print(format_benchmark_report(report))
    print(f"\n✓ Đã ghi benchmark: {args.output}")


def main(argv: list[str] | None = None) -> None:
    cmd_funcs = {
        "start": cmd_start,
        "status": cmd_status,
        "run": cmd_run,
        "verify": cmd_verify,
        "retry": cmd_retry,
        "logs": cmd_logs,
        "ledger": cmd_ledger,
        "queue": cmd_queue,
        "ps": cmd_ps,
        "reset": cmd_reset,
        "cancel": cmd_cancel,
        "stop": cmd_stop,
        "doctor": cmd_doctor,
        "auth": cmd_auth,
        "benchmark-local": cmd_benchmark_local,
    }
    parser = build_parser(doc=__doc__, cmd_funcs=cmd_funcs)

    args = parser.parse_args(argv)
    if args.command == "logs" and not args.warnings and not args.slug and not getattr(args, "current", False):
        parser.error("logs cần 1 slug, hoặc dùng --warnings / --current")

    try:
        if args.command in PID_TRACKED_COMMANDS:
            check_not_already_running()
            _install_signal_handlers()
            write_pid_file()
            try:
                args.func(args)
            finally:
                remove_pid_file()
        else:
            args.func(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
