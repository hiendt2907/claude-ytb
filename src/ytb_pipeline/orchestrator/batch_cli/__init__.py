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

Lưu ý cấu trúc gói: đây là package (không còn là 1 file 883 dòng) — logic chia
theo mối quan tâm sang process_control.py (PID file + signal), scheduler.py
(schedule_pending_videos), workers.py (worker state + vòng lặp xử lý queue),
commands.py (các subcommand đơn giản còn lại). `__init__.py` này (module
`ytb_pipeline.orchestrator.batch_cli` — tên KHÔNG đổi dù giờ là package) vẫn
là nơi duy nhất giữ:
  - Toàn bộ import lại từ queue_manager.py/pipeline_runner.py/doctor.py/
    ideation_cmd.py để giữ đúng interface cũ
    (`ytb_pipeline.orchestrator.batch_cli.<tên>` vẫn dùng được, kể cả để
    monkeypatch trong test).
  - Các hằng số/state toàn cục có thể bị test patch (PID_TRACKED_COMMANDS,
    VN_TZ, DEFAULT_SCHEDULE_SLOTS, MAX_BATCH_WORKERS, WORKER_STATE_PATH,
    _current_proc, _current_procs, _queue_claim_lock, _claimed_slugs,
    _stop_requested, _recovery_code_streak) — mọi submodule đọc/ghi các tên này qua `_cli()` tại
    thời điểm gọi (không capture biến module-level tĩnh riêng), y hệt quy ước
    đã có sẵn ở queue_manager.py/pipeline_runner.py/doctor.py/ideation_cmd.py.
  - `main()`/argparse.

`python -m ytb_pipeline.orchestrator.batch_cli` (dùng bởi bin/ytb và
listener.py) chạy qua `batch_cli/__main__.py`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from datetime import timedelta, timezone

from ...claude_cli import build_claude_cmd
from ...analytics.feedback import AnalyticsStore
from ...content_contract import CONTRACT_VERSION
from ...config.settings import settings
from ...notify import telegram
from ...publish.youtube_auth import DRIVE_SCOPES, YOUTUBE_SCOPES, ReauthRequiredError
from ...voiceover.f5_daemon_pool import F5DaemonPool
from ..cli_args import build_parser
from ..doctor import _check_oauth_token, _check_recent_published, cmd_doctor, run_doctor_checks, run_local_doctor_checks
from ..ideation_cmd import (
    _build_resume_prompt,
    _build_start_prompt,
    _count_pending_ideation,
    _prompt_start_interactive,
    cmd_start,
)
from ..local_benchmark import format_benchmark_report, run_local_benchmark
from ..pipeline_runner import (
    RECOVERY_ESCALATION_THRESHOLD,
    RETRY_BACKOFF_SEC,
    STAGE_START_MARKERS,
    TRANSIENT_ERROR_PATTERNS,
    YOUTUBE_VERIFY_TIMEOUT_SEC,
    _maybe_escalate_recovery_streak,
    _reset_recovery_streaks,
    _track_recovery_failure,
    build_env,
    check_schedule_drift,
    detect_stage_marker,
    extract_claimed_video_id,
    finalize_published_item,
    is_transient_error,
    log_path_for,
    process_next,
    recovery_for_output,
    run_pipeline_once,
    run_with_retry,
    write_failure_recovery_report,
    verify_youtube_video,
)
from ..queue_manager import (
    AUTO_STATE_PATH,
    LEDGER_PATH,
    PID_PATH,
    PIPELINE_LOG_DIR,
    ROOT,
    WARN_LOG_PATH,
    QueueItem,
    current_running_slug,
    done_slugs,
    failed_slugs,
    emit_warning,
    last_stage_for_slug,
    load_queue,
    next_pending,
    notify_progress,
    reconcile_batch_state,
    tail_text,
    update_ledger,
)
from ..preflight import format_preflight_result, preflight_script
from ..state_io import locked_json_update
from ..visual_review_cli import cmd_review

from .commands import (
    cmd_analytics,
    cmd_auth,
    cmd_benchmark_local,
    cmd_cancel,
    cmd_ledger,
    cmd_logs,
    cmd_ps,
    cmd_queue,
    cmd_reconcile,
    cmd_reset,
    cmd_retry,
    cmd_status,
    cmd_stop,
    cmd_verify,
)
from .process_control import (
    _descendant_pids,
    _handle_stop_signal,
    _install_signal_handlers,
    _pid_alive,
    _terminate_tracked_batch_tree,
    batch_process_is_alive,
    check_not_already_running,
    remove_pid_file,
    write_pid_file,
)
from .scheduler import schedule_pending_videos
from .workers import (
    _claim_next_staged,
    _record_stage_failure,
    _release_staged_claim,
    _run_f5_voiceover_lane,
    _run_render_publish_lane,
    cmd_run,
    cmd_run_f5_staged,
    select_pending_batch,
    update_worker_state,
    worker_elapsed,
    worker_states,
)

# Subcommand nào ghi pid file (để `stop` tìm đúng process cần SIGTERM) — chỉ
# những lệnh chạy lâu, lồng subprocess pipeline con (run/retry). `start` (gọi
# Claude) và các lệnh đọc-only khác không cần.
PID_TRACKED_COMMANDS = {"run", "retry"}
VN_TZ = timezone(timedelta(hours=7))
DEFAULT_SCHEDULE_SLOTS = "06:00,12:30,20:30"
MAX_BATCH_WORKERS = 2
WORKER_STATE_PATH = ROOT / "assets" / "batch_workers.json"

# Tiến trình `python -m ytb_pipeline <script>` đang chạy lồng bên trong (nếu
# có) — signal handler forward SIGTERM xuống đây để không bỏ orphan, và cờ
# báo cho run_with_retry/process_next/cmd_run biết là dừng CHỦ ĐỘNG (không
# phải lỗi) để không retry/không ghi cảnh báo trùng.
_current_proc: subprocess.Popen | None = None
_current_procs: dict[str, subprocess.Popen] = {}
_queue_claim_lock = threading.Lock()
_claimed_slugs: set[str] = set()
_stop_requested = False
# Đếm streak lỗi liên tiếp CÙNG recovery code trong phiên --loop hiện tại —
# xem pipeline_runner.py::_maybe_escalate_recovery_streak.
_recovery_code_streak: dict[str, int] = {}


def cmd_preflight(args) -> None:
    """Check scripts before queue admission or a supervised production run."""
    paths = [ROOT / "scripts" / f"{slug}.json" for slug in getattr(args, "slugs", [])]
    if not paths:
        paths = [ROOT / "scripts" / f"{item.slug}.json" for item in load_queue()]
    results = [
        preflight_script(
            path,
            live_providers=bool(getattr(args, "live_providers", False)),
            publish=bool(getattr(args, "publish", False)),
        )
        for path in paths
    ]
    for result in results:
        print(format_preflight_result(result))
    if any(not result.passed for result in results):
        raise SystemExit(1)


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
        "analytics": cmd_analytics,
        "reconcile": cmd_reconcile,
        "ps": cmd_ps,
        "reset": cmd_reset,
        "cancel": cmd_cancel,
        "stop": cmd_stop,
        "doctor": cmd_doctor,
        "auth": cmd_auth,
        "benchmark-local": cmd_benchmark_local,
        "preflight": cmd_preflight,
        "review": cmd_review,
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
