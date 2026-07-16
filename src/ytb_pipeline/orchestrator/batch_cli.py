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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

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
    YOUTUBE_VERIFY_TIMEOUT_SEC,
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
    failed_slugs,
    emit_warning,
    last_stage_for_slug,
    load_queue,
    next_pending,
    notify_progress,
    tail_text,
    update_ledger,
)
from .state_io import locked_json_update

# Subcommand nào ghi pid file (để `stop` tìm đúng process cần SIGTERM) — chỉ
# những lệnh chạy lâu, lồng subprocess pipeline con (run/retry). `start` (gọi
# Claude) và các lệnh đọc-only khác không cần.
PID_TRACKED_COMMANDS = {"run", "retry"}
VN_TZ = timezone(timedelta(hours=7))
DEFAULT_SCHEDULE_SLOTS = "06:00,20:30"
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


def _handle_stop_signal(signum, frame) -> None:  # noqa: ANN001 — chữ ký bắt buộc của signal.signal
    """Bắt SIGTERM/SIGINT: đặt cờ dừng + kill NGAY tiến trình pipeline con (nếu có).

    Không có bước này, tiến trình con `python -m ytb_pipeline <script>` (render/
    upload) sẽ thành orphan khi process cha bị kill — đã xảy ra thật với `/stop`
    qua Telegram (proc.terminate() ở listener.py chỉ kill được batch_cli.py,
    không propagate xuống cây con vì không cùng process group).
    """
    global _stop_requested
    _stop_requested = True
    processes = list(_current_procs.values())
    if not processes and _current_proc is not None:
        processes = [_current_proc]
    for proc in processes:
        if proc.poll() is not None:
            continue
        # killpg (không phải .terminate()) — `_current_proc` được spawn với
        # start_new_session=True nên là leader của 1 process group riêng, gồm cả
        # cháu sâu hơn 1 cấp như worker F5-TTS (.venv-tts/bin/python
        # scripts/f5_batch_worker.py) và ffmpeg do compose_ai.py gọi. .terminate()
        # chỉ kill đúng PID này, để lại các tiến trình cháu chạy mồ côi.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
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
    for worker_id, state in worker_states().items():
        slug = state.get("slug") or "-"
        stage = state.get("stage") or "idle"
        elapsed = worker_elapsed(state)
        error = state.get("last_error") or "-"
        print(f"worker {worker_id}: {slug}  stage={stage}  elapsed={elapsed}  last_error={error}")
    queue = load_queue()
    done = done_slugs()
    for item in queue:
        mark = "✓ done" if item.slug in done else "… pending"
        print(f"day {item.day:>2}  {mark:<10}  {item.slug}  (publish_at={item.publish_at})")


def worker_states() -> dict[str, dict]:
    if not WORKER_STATE_PATH.exists():
        return {}
    data = json.loads(WORKER_STATE_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def update_worker_state(
    worker_id: int, *, slug: str, stage: str, last_error: str = "", started_at: str | None = None
) -> None:
    with locked_json_update(WORKER_STATE_PATH) as data:
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


def select_pending_batch(
    queue: list[QueueItem], blocked_slugs: set[str], *, worker_count: int
) -> list[QueueItem]:
    """Choose distinct pending items for one controlled worker wave.

    The hard cap is intentional: rendering and local inference are expensive, and
    P0 starts with at most two concurrent videos regardless of caller input.
    """
    limit = min(MAX_BATCH_WORKERS, max(1, worker_count))
    selected: list[QueueItem] = []
    for item in queue:
        if item.slug in blocked_slugs:
            continue
        selected.append(item)
        if len(selected) == limit:
            break
    return selected


def _parse_schedule_slots(raw: str) -> list[time]:
    slots: list[time] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            hour_text, minute_text = value.split(":", 1)
            slots.append(time(hour=int(hour_text), minute=int(minute_text)))
        except ValueError as exc:
            raise SystemExit(f"✗ Slot schedule không hợp lệ: '{value}'. Dùng dạng HH:MM, vd 11:30,20:30.") from exc
    if not slots:
        raise SystemExit("✗ Cần ít nhất 1 slot schedule, vd --schedule-slots 11:30,20:30.")
    return slots


def _latest_batch_key(data: dict) -> str:
    batch_keys = sorted(k for k in data if k.startswith("shorts_funnel_batch_"))
    if not batch_keys:
        raise SystemExit("✗ Không tìm thấy batch shorts_funnel_batch_* trong assets/auto_state.json.")
    return batch_keys[-1]


def schedule_pending_videos(args: argparse.Namespace, *, now: datetime | None = None) -> int:
    """Gán publish_at cho video pending chưa có lịch trong batch mới nhất.

    Không ghi đè video đã có publish_at để tránh đổi lịch đã set tay/đã upload.
    """
    if not AUTO_STATE_PATH.exists():
        raise SystemExit(f"✗ Không tìm thấy queue: {AUTO_STATE_PATH}")

    done = done_slugs()
    slots = _parse_schedule_slots(getattr(args, "schedule_slots", DEFAULT_SCHEDULE_SLOTS))
    start_days = getattr(args, "schedule_start_days", 1)
    if start_days < 0:
        raise SystemExit("✗ --schedule-start-days không được âm.")

    base_now = now or datetime.now(VN_TZ)
    start_date = base_now.astimezone(VN_TZ).date() + timedelta(days=start_days)
    with locked_json_update(AUTO_STATE_PATH) as data:
        batch_key = _latest_batch_key(data)
        batch = data[batch_key]
        def eligible(video: dict) -> bool:
            return (
                video.get("slug") not in done
                and video.get("status", "ok") not in {"needs_review", "error"}
                and video.get("quality_status") != "needs_review"
                and video.get("assets_valid") is not False
                and not str(video.get("publish_at", "")).strip()
            )

        long_pending = [video for video in batch.get("long_videos", []) if eligible(video)]
        short_pending = [
            video
            for video in sorted(batch.get("short_videos", []), key=lambda v: int(v.get("day", 0)))
            if eligible(video)
        ]

        # Default channel policy: two Shorts Mon-Sat; one long-form every Sunday.
        # An explicitly customised slot list retains the generic queue behaviour.
        if getattr(args, "schedule_slots", DEFAULT_SCHEDULE_SLOTS) == DEFAULT_SCHEDULE_SLOTS:
            sunday = start_date + timedelta(days=(6 - start_date.weekday()) % 7)
            for video in long_pending:
                video["publish_at"] = datetime.combine(sunday, slots[-1], tzinfo=VN_TZ).isoformat(timespec="seconds")
                sunday += timedelta(days=7)
            date_cursor = start_date
            for index, video in enumerate(short_pending):
                while date_cursor.weekday() == 6:
                    date_cursor += timedelta(days=1)
                slot = slots[index % len(slots)]
                video["publish_at"] = datetime.combine(date_cursor, slot, tzinfo=VN_TZ).isoformat(timespec="seconds")
                if index % len(slots) == len(slots) - 1:
                    date_cursor += timedelta(days=1)
        else:
            pending = sorted(long_pending + short_pending, key=lambda v: int(v.get("day", 0)))
            for index, video in enumerate(pending):
                slot = slots[index % len(slots)]
                scheduled_date = start_date + timedelta(days=index // len(slots))
                video["publish_at"] = datetime.combine(scheduled_date, slot, tzinfo=VN_TZ).isoformat(timespec="seconds")

    slot_text = ",".join(f"{slot.hour:02d}:{slot.minute:02d}" for slot in slots)
    count = len(long_pending) + len(short_pending)
    print(f"✓ Đã schedule {count} video pending trong {batch_key} từ {start_date.isoformat()} (slots={slot_text}).")
    return count


def cmd_run(args: argparse.Namespace) -> None:
    if getattr(args, "schedule", False):
        schedule_pending_videos(args)
    worker_count = min(MAX_BATCH_WORKERS, max(1, getattr(args, "workers", 1)))
    slots = worker_count if args.loop else 1
    with ThreadPoolExecutor(max_workers=slots, thread_name_prefix="ytb-batch") as executor:
        running = {
            executor.submit(process_next, worker_id=worker_id): worker_id
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
                    emit_warning(message)
                    update_worker_state(worker_id, slug="-", stage="error", last_error=str(exc))
                    continue
                if args.loop and processed and not _stop_requested:
                    running[executor.submit(process_next, worker_id=worker_id)] = worker_id

    if _stop_requested:
        print(
            "⏸ Đã dừng graceful theo yêu cầu (`ytb batch stop`) — chạy lại "
            "`ytb batch run`/`run --loop` để tiếp tục đúng video đang dở."
        )


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
    # Xoá checkpoint project.json — nếu giữ, WorkflowGraph sẽ skip node DONE cũ
    # và "chạy lại từ đầu" thành no-op.
    project_dir = Path(settings.projects_dir) / args.slug
    if project_dir.exists():
        shutil.rmtree(project_dir)
        print(f"✓ Đã xoá checkpoint {project_dir} (chạy lại từ đầu thật sự).")
    print(f"✓ Đã reset '{args.slug}' về pending — sẽ được `ytb batch run` nhặt ở lượt kế tiếp.")


def cmd_cancel(args: argparse.Namespace) -> None:
    running = current_running_slug()
    if running == args.slug:
        print(f"✗ '{args.slug}' đang được xử lý. Dùng `ytb batch stop` trước rồi cancel.")
        return
    with locked_json_update(AUTO_STATE_PATH) as data:
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
