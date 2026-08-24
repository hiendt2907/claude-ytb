"""PID file + signal handling cho `ytb batch run`/`retry`.

Đọc/ghi các hằng số mutable (PID_PATH) và state toàn cục (_stop_requested,
_current_proc, _current_procs) đều phải qua `_cli()` tại THỜI ĐIỂM GỌI — xem
docstring `queue_manager.py::_cli()` cho lý do: test patch qua
`batch_cli.<TÊN>`, patch đó chỉ có hiệu lực nếu hàm đọc giá trị động thay vì
capture biến module-level tĩnh của riêng file này.
"""

from __future__ import annotations

import os
import signal
import subprocess


def _cli():
    """Import trễ package batch_cli — xem queue_manager._cli() cho lý do."""
    from .. import batch_cli

    return batch_cli


def _handle_stop_signal(signum, frame) -> None:  # noqa: ANN001 — chữ ký bắt buộc của signal.signal
    """Bắt SIGTERM/SIGINT: đặt cờ dừng + kill NGAY tiến trình pipeline con (nếu có).

    Không có bước này, tiến trình con `python -m ytb_pipeline <script>` (render/
    upload) sẽ thành orphan khi process cha bị kill — đã xảy ra thật với `/stop`
    qua Telegram (proc.terminate() ở listener.py chỉ kill được batch_cli.py,
    không propagate xuống cây con vì không cùng process group).
    """
    cli = _cli()
    cli._stop_requested = True
    processes = list(cli._current_procs.values())
    if not processes and cli._current_proc is not None:
        processes = [cli._current_proc]
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


def batch_process_is_alive() -> bool:
    """Return whether the PID tracked by batch CLI is still alive.

    Worker state is deliberately persisted for post-mortem debugging.  It must
    not be mistaken for a live process by the status command or an automation.
    """
    path = _cli().PID_PATH
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return False
    return _cli()._pid_alive(pid)


def _descendant_pids(root_pid: int) -> list[int]:
    """Return the current descendant process IDs of a tracked batch process.

    Staged F5 lanes deliberately run in separate process groups, so signalling
    only the batch parent cannot guarantee that its TTS daemons and pipeline
    children stop.  Resolve the tree immediately before stopping it instead of
    relying on process-group inheritance that the runner intentionally avoids.
    """
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid="],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) != 2:
            continue
        try:
            pid, parent_pid = map(int, columns)
        except ValueError:
            continue
        children.setdefault(parent_pid, []).append(pid)

    descendants: list[int] = []
    pending = list(children.get(root_pid, []))
    while pending:
        pid = pending.pop()
        descendants.append(pid)
        pending.extend(children.get(pid, []))
    return descendants


def _terminate_tracked_batch_tree(pid: int) -> list[int]:
    """Send SIGTERM to every currently owned process, children before parent."""
    targets = [*_cli()._descendant_pids(pid), pid]
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)
        except ProcessLookupError:
            if target == pid:
                raise
            continue
    return targets


def check_not_already_running() -> None:
    """Chặn `run`/`retry` chồng lên 1 tiến trình cũ chưa thoát -- 2 process đua nhau
    ghi cùng file audio/render gây hỏng dữ liệu (đã xảy ra thật, xem ledger 23/06)."""
    cli = _cli()
    if not cli.PID_PATH.exists():
        return
    old_pid_text = cli.PID_PATH.read_text(encoding="utf-8").strip()
    if old_pid_text and cli._pid_alive(int(old_pid_text)):
        raise SystemExit(
            f"✗ Đã có `ytb batch run`/`retry` đang chạy (PID {old_pid_text}). "
            "Dùng `ytb batch stop` để dừng graceful trước, hoặc đợi nó xong."
        )
    cli.PID_PATH.unlink(missing_ok=True)  # pid file cũ, tiến trình đã chết -- dọn rồi chạy tiếp


def write_pid_file() -> None:
    cli = _cli()
    cli.PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    cli.PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid_file() -> None:
    """Chỉ xoá pid file nếu nó vẫn còn ghi đúng PID của tiến trình hiện tại --
    nếu không (1 tiến trình khác đã ghi đè đè lên), giữ nguyên, tránh xoá nhầm
    "dấu vết đang chạy" của tiến trình kia (xem check_not_already_running)."""
    cli = _cli()
    try:
        if cli.PID_PATH.read_text(encoding="utf-8").strip() != str(os.getpid()):
            return
    except FileNotFoundError:
        return
    cli.PID_PATH.unlink(missing_ok=True)
