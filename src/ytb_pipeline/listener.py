"""Daemon Telegram ⇄ Claude trên Mac — ra lệnh từ bất kỳ đâu, máy Mac còn mở.

Bộ công cụ điều khiển Claude qua chat:

  (gõ tự do)      → hỏi/giao việc cho Claude trong dự án (1 phiên mới, context sạch)
  /ask <prompt>   → như trên, tường minh
  /cont <prompt>  → tiếp nối phiên Claude gần nhất (--continue), GIỮ context
  /auto <lệnh>    → chạy skill /youtube-auto (pipeline sản xuất video)
  /sh <cmd>       → chạy lệnh shell trong thư mục dự án
  /stop           → hủy job đang chạy nền
  /status         → tiến độ hàng đợi + ledger + job hiện tại
  /logs [n]       → n dòng cuối log listener
  /ping /help

Thiết kế chống giành getUpdates với cổng duyệt của skill:
  - Job THƯỜNG (claude/-ask/-cont/-sh): chạy NỀN, listener vẫn poll ⇒ /stop, /status được.
  - Job TƯƠNG TÁC (/auto, tự đọc Telegram để duyệt): listener TẠM DỪNG poll, chạy
    đồng bộ để subprocess độc quyền luồng update, xong RESYNC offset rồi nghe tiếp.
Đơn-luồng (single-flight): mỗi lúc chỉ 1 job; lệnh mới khi đang bận bị từ chối.

Mặc định `claude -p` chạy với --dangerously-skip-permissions (xem settings).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
from pathlib import Path

from .config.settings import settings
from .notify import telegram

_PROJECT_DIR = Path(__file__).resolve().parents[2]
_LEDGER = _PROJECT_DIR / "data/ledger.md"
_STATE = _PROJECT_DIR / "assets/auto_state.json"
_OUT_LOG = _PROJECT_DIR / "assets/listener.out.log"

_HELP_WORDS = {"/help", "help", "/start", "?"}
_PING_WORDS = {"/ping", "ping"}
_STATUS_WORDS = {"/status", "status", "/queue"}
_STOP_WORDS = {"/stop", "stop", "/cancel", "huỷ", "hủy"}

_MAX_OUT = 1200  # ký tự output gửi về Telegram (tránh spam)

_HELP_TEXT = (
    "🤖 *Claude trên Mac — điều khiển qua Telegram*\n\n"
    "Gõ tự do để giao việc cho Claude. Hoặc:\n"
    "• `/ask <prompt>` — hỏi/giao việc (phiên mới, context sạch)\n"
    "• `/cont <prompt>` — tiếp nối phiên gần nhất (giữ context)\n"
    "• `/auto <lệnh>` — chạy pipeline /youtube-auto\n"
    "• `/sh <cmd>` — chạy lệnh shell trong dự án\n"
    "• `/stop` — hủy job đang chạy\n"
    "• `/status` — tiến độ + job hiện tại\n"
    "• `/logs [n]` — log gần đây\n"
    "• `/ping` `/help`"
)


# ── Trạng thái job nền (single-flight) ────────────────────────────────────────
class _Job:
    """Theo dõi job nền đang chạy (để /stop và báo bận)."""

    lock = threading.Lock()
    proc: subprocess.Popen | None = None
    label: str | None = None


def _busy() -> bool:
    return _Job.proc is not None and _Job.proc.poll() is None


# ── Dựng lệnh ─────────────────────────────────────────────────────────────────
def _claude_cmd(prompt: str, *, cont: bool = False) -> list[str]:
    """`claude [extra-args] [--continue] -p "<prompt>"`."""
    cmd = [settings.claude_bin]
    extra = settings.listener_claude_args.strip()
    if extra:
        cmd += shlex.split(extra)
    if cont:
        cmd.append("--continue")
    cmd += ["-p", prompt]
    return cmd


# ── Báo cáo trạng thái ────────────────────────────────────────────────────────
def _status_text() -> str:
    parts = ["📊 *Trạng thái*"]
    parts.append(f"Job: {'⏳ ' + _Job.label if _busy() else 'rảnh'}")
    parts.append(
        f"`auto_state.json`: {'có' if _STATE.exists() else 'chưa có'}"
    )
    if _LEDGER.exists():
        lines = [ln for ln in _LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
        parts.append("\n_Ledger (6 dòng cuối):_\n" + ("\n".join(lines[-6:]) or "(trống)"))
    return "\n".join(parts)


def _logs_text(n: int) -> str:
    if not _OUT_LOG.exists():
        return "(chưa có log)"
    lines = _OUT_LOG.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-n:]) or "(log trống)"


# ── Thực thi job nền ──────────────────────────────────────────────────────────
def _spawn(label: str, cmd: list[str]) -> None:
    """Chạy NỀN 1 job, báo Telegram khi xong. Từ chối nếu đang bận."""
    with _Job.lock:
        if _busy():
            telegram.send_message(f"⏳ Đang bận: {_Job.label}. `/stop` để hủy trước.")
            return
        telegram.send_message(f"▶️ {label}")
        proc = subprocess.Popen(
            cmd, cwd=_PROJECT_DIR, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        _Job.proc, _Job.label = proc, label
    threading.Thread(target=_reap, args=(proc, label), daemon=True).start()


def _reap(proc: subprocess.Popen, label: str) -> None:
    out, _ = proc.communicate()
    with _Job.lock:
        _Job.proc, _Job.label = None, None
    tail = (out or "").strip()[-_MAX_OUT:] or "(không có output)"
    status = "✅ Xong" if proc.returncode == 0 else f"⚠️ Mã {proc.returncode}"
    telegram.send_message(f"{status}: {label}\n\n{tail}")


def _stop() -> None:
    with _Job.lock:
        proc, label = _Job.proc, _Job.label
    if not proc or proc.poll() is not None:
        telegram.send_message("Không có job nào đang chạy.")
        return
    proc.terminate()
    telegram.send_message(f"🛑 Đã yêu cầu dừng: {label}")


# ── Router ────────────────────────────────────────────────────────────────────
def _dispatch(cmd: str) -> str | None:
    """Xử lý 1 lệnh. Trả về instruction nếu là job TƯƠNG TÁC (caller chạy đồng bộ),
    None nếu đã xử lý xong (control hoặc đã spawn job nền)."""
    low = cmd.lower()
    if low in _HELP_WORDS:
        telegram.send_message(_HELP_TEXT)
        return None
    if low in _PING_WORDS:
        telegram.send_message("🟢 Listener đang chạy." + (" (đang bận)" if _busy() else ""))
        return None
    if low in _STATUS_WORDS:
        telegram.send_message(_status_text())
        return None
    if low in _STOP_WORDS:
        _stop()
        return None

    verb, _, rest = cmd.partition(" ")
    v, rest = verb.lower(), rest.strip()

    if v == "/logs":
        n = int(rest) if rest.isdigit() else 30
        telegram.send_message(_logs_text(n))
        return None
    if v == "/auto":
        if _busy():
            telegram.send_message(f"⏳ Đang bận: {_Job.label}. `/stop` trước.")
            return None
        if not rest:
            telegram.send_message(
                "Cú pháp: `/auto <việc>` — vd `/auto làm 1 clip dài, hẹn 20h`.\n"
                "Chạy 1 lô rồi trả quyền lại cho listener."
            )
            return None
        return rest  # → caller chạy đồng bộ (tương tác Telegram)
    if v == "/sh":
        if not settings.listener_allow_shell:
            telegram.send_message("🚫 /sh bị tắt (LISTENER_ALLOW_SHELL=false).")
        elif not rest:
            telegram.send_message("Cú pháp: `/sh <lệnh>`")
        else:
            _spawn(f"sh: {rest}", ["bash", "-lc", rest])
        return None
    if v in ("/cont", "/continue"):
        if rest:
            _spawn(f"claude --continue: {rest[:60]}", _claude_cmd(rest, cont=True))
        else:
            telegram.send_message("Cú pháp: `/cont <prompt>`")
        return None
    if v in ("/ask", "/run", "/claude"):
        if rest:
            _spawn(f"claude: {rest[:60]}", _claude_cmd(rest))
        else:
            telegram.send_message("Cú pháp: `/ask <prompt>`")
        return None

    # Mặc định: coi toàn bộ text là prompt cho Claude (phiên mới).
    _spawn(f"claude: {cmd[:60]}", _claude_cmd(cmd))
    return None


def _run_interactive(instruction: str) -> None:
    """Chạy ĐỒNG BỘ /youtube-auto cho 1 lô — subprocess độc quyền Telegram khi duyệt.

    Đặt YTB_LISTENER_MANAGED=1 để skill biết đang chạy DƯỚI listener: hết lô thì THOÁT
    (trả quyền lại listener) thay vì ngủ chờ lệnh vô tận — tránh treo daemon.
    """
    prompt = f"{settings.listener_skill} {instruction}".strip()
    telegram.send_message(f"▶️ Chạy pipeline: {instruction}")
    env = {**os.environ, "YTB_LISTENER_MANAGED": "1"}
    try:
        result = subprocess.run(
            _claude_cmd(prompt), cwd=_PROJECT_DIR, env=env,
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        telegram.send_message(f"❌ Không tìm thấy `{settings.claude_bin}`. Đặt CLAUDE_BIN.")
        return
    tail = (result.stdout or "").strip()[-_MAX_OUT:] or "(không có output)"
    status = "✅ Xong lô" if result.returncode == 0 else f"⚠️ Mã {result.returncode}"
    telegram.send_message(f"{status}: {instruction}\n\n{tail}\n\nSẵn sàng nhận lệnh tiếp.")


def run() -> None:
    """Vòng lặp daemon. Chạy mãi tới khi bị kill."""
    telegram._require_config()  # fail-fast nếu thiếu token/chat_id
    telegram.send_message("🚀 Claude listener online — gõ /help.")
    offset = telegram.latest_update_id() + 1  # bỏ qua backlog cũ
    while True:
        texts, offset = telegram.poll_messages(offset=offset)
        for raw in texts:
            cmd = raw.strip()
            if not cmd:
                continue
            instruction = _dispatch(cmd)
            if instruction is not None:  # job tương tác: chạy đồng bộ + resync
                _run_interactive(instruction)
                offset = telegram.latest_update_id() + 1


if __name__ == "__main__":  # pragma: no cover
    run()
