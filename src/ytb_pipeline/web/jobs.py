"""Chạy job nền cho dashboard (single-flight) + bắt log.

Hai loại job:
  - pipeline(script): gọi thẳng ytb_pipeline.pipeline.run() trong thread, cổng
    duyệt dùng web (approvals.web_request_approval).
  - auto(instruction): spawn `claude /youtube-auto ...` như listener Telegram.

Mỗi lúc chỉ 1 job (giống listener). Log gom vào buffer để hiển thị realtime.
"""

from __future__ import annotations

import io
import shlex
import subprocess
import threading
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from ..config.settings import settings
from ..ideation import approval
from . import approvals

_PROJECT_DIR = Path(__file__).resolve().parents[3]


@dataclass
class JobState:
    """Trạng thái job hiện tại (None field = chưa chạy job nào)."""

    label: str | None = None
    running: bool = False
    log: str = ""
    last_result: str = ""
    _proc: subprocess.Popen | None = field(default=None, repr=False)


_state = JobState()
_lock = threading.Lock()


def current() -> JobState:
    return _state


def is_busy() -> bool:
    return _state.running


def _start(label: str, target) -> tuple[bool, str]:
    """Khởi động 1 thread job nếu đang rảnh. Trả (ok, message)."""
    with _lock:
        if _state.running:
            return False, f"Đang bận: {_state.label}"
        _state.label = label
        _state.running = True
        _state.log = ""
        _state.last_result = ""
    threading.Thread(target=_wrap, args=(target,), daemon=True).start()
    return True, f"Đã bắt đầu: {label}"


def _wrap(target) -> None:
    try:
        target()
    except Exception as exc:  # noqa: BLE001 — báo lỗi lên dashboard, không nuốt
        _state.last_result = f"⚠️ Lỗi: {exc}"
        _append(f"\n⚠️ Lỗi: {exc}")
    finally:
        with _lock:
            _state.running = False
            _state._proc = None


def _append(text: str) -> None:
    _state.log += text


def run_pipeline(script_source: str) -> tuple[bool, str]:
    """Chạy pipeline 1 kịch bản; cổng duyệt qua web."""

    def target() -> None:
        approval.set_approval_provider(approvals.web_request_approval)
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                result = run_pipeline_inner(script_source)
            _state.last_result = f"✅ Xong: uploaded={result.uploaded}"
        finally:
            approval.set_approval_provider(None)
            _append(buf.getvalue())

    return _start(f"pipeline: {script_source}", target)


def run_pipeline_inner(script_source: str):
    from ..pipeline import run  # import trễ — moviepy nặng

    return run(script_source)


def run_auto(instruction: str) -> tuple[bool, str]:
    """Spawn `claude /youtube-auto <instruction>` (như listener), chạy nền."""

    def target() -> None:
        cmd = [settings.claude_bin]
        extra = settings.listener_claude_args.strip()
        if extra:
            cmd += shlex.split(extra)
        prompt = f"{settings.listener_skill} {instruction}".strip()
        cmd += ["-p", prompt]
        proc = subprocess.Popen(
            cmd, cwd=_PROJECT_DIR, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        _state._proc = proc
        for line in proc.stdout:  # stream realtime
            _append(line)
        proc.wait()
        _state.last_result = (
            "✅ Xong lô" if proc.returncode == 0 else f"⚠️ Mã {proc.returncode}"
        )

    return _start(f"auto: {instruction[:50]}", target)


def stop() -> tuple[bool, str]:
    """Dừng job đang chạy (chỉ job subprocess /auto có thể kill)."""
    proc = _state._proc
    if proc and proc.poll() is None:
        proc.terminate()
        return True, "Đã yêu cầu dừng."
    if _state.running:
        return False, "Job đang chạy không thể kill (đang chờ duyệt?)."
    return False, "Không có job nào đang chạy."
