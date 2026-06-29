"""Daemon Telegram ⇄ Claude trên Mac — ra lệnh từ bất kỳ đâu, máy Mac còn mở.

Bộ công cụ điều khiển Claude qua chat:

  (gõ tự do)      → hỏi/giao việc cho Claude trong dự án (1 phiên mới, context sạch)
  /ask <prompt>   → như trên, tường minh
  /cont <prompt>  → tiếp nối phiên Claude gần nhất (--continue), GIỮ context
  /auto <lệnh>    → chạy skill /youtube-auto (pipeline sản xuất video)
  /batch <lệnh>   → chạy `ytb batch <lệnh>` thuần CLI (status/run/retry/...), không tốn token
  /ytb-cmd        → liệt kê toàn bộ lệnh `ytb batch` có thể gõ qua /batch
  /sh <cmd>       → chạy lệnh shell trong thư mục dự án
  /stop           → hủy job đang chạy nền
  /status         → tiến độ hàng đợi + ledger + job hiện tại
  /logs [n]       → n dòng cuối log listener
  /ping /help

Thiết kế chống giành getUpdates với cổng duyệt của skill:
  - Job THƯỜNG (claude/-ask/-cont/-sh/-batch <khác start>): chạy NỀN, listener vẫn
    poll ⇒ /stop, /status được.
  - Job TƯƠNG TÁC (/auto, /batch start — cả hai tự đọc Telegram để duyệt): listener
    TẠM DỪNG poll, chạy đồng bộ để subprocess độc quyền luồng update, xong RESYNC
    offset rồi nghe tiếp.
Đơn-luồng (single-flight): mỗi lúc chỉ 1 job; lệnh mới khi đang bận bị từ chối.

Mặc định `claude -p` chạy với --dangerously-skip-permissions (xem settings).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
from pathlib import Path

from .claude_cli import build_claude_cmd
from .config.settings import settings
from .notify import telegram

_PROJECT_DIR = Path(__file__).resolve().parents[2]
_LEDGER = _PROJECT_DIR / "data/ledger.md"
_STATE = _PROJECT_DIR / "assets/auto_state.json"
_OUT_LOG = _PROJECT_DIR / "assets/listener.out.log"
_BATCH_PYTHON = _PROJECT_DIR / ".venv" / "bin" / "python"

_HELP_WORDS = {"/help", "help", "/start", "?"}
_PING_WORDS = {"/ping", "ping"}
_STATUS_WORDS = {"/status", "status", "/queue"}
_STOP_WORDS = {"/stop", "stop", "/cancel", "huỷ", "hủy"}
_YTB_CMD_WORDS = {"/ytb-cmd", "/ytb", "ytb-cmd"}

_YTB_CMD_TEXT = (
    "🧰 *Lệnh `ytb batch` qua Telegram* — gõ `/batch <lệnh>`:\n\n"
    "• `/batch start -n 5 --type-of-vid long` — Claude viết N kịch bản (TỐN TOKEN, "
    "chạy đồng bộ, mất nhiều phút, --type-of-vid long|short, --type-of-rules auto|<mô tả>)\n"
    "• `/batch status` — video nào done/pending trong queue\n"
    "• `/batch run` — chạy video kế tiếp (thêm `--loop` để chạy hết queue)\n"
    "• `/batch retry <slug>` — chạy lại tay 1 slug cụ thể\n"
    "• `/batch verify <youtube_id>` — xác minh video có thật trên YouTube\n"
    "• `/batch logs <slug>` — log của 1 video (`/batch logs --warnings` để xem cảnh báo)\n"
    "• `/batch ledger` — N dòng cuối data/ledger.md\n"
    "• `/batch queue` — toàn bộ queue dạng JSON\n"
    "• `/batch doctor` — kiểm tra môi trường trước khi chạy batch\n"
    "• `/batch stop` — dừng graceful `run`/`retry` (cũng dùng `/stop` chung được)\n\n"
    "Mọi lệnh trừ `start` chạy NỀN, không tốn token, không cần Claude còn hạn mức.\n"
    "`/stop` (hoặc `/batch stop`) giờ kill SẠCH cả tiến trình con render/upload — "
    "resume bằng `run`/`retry` sẽ tự tiếp tục đúng video đang dở (ledger ghi 'stopped')."
)

_MAX_OUT = 1200  # ký tự output gửi về Telegram (tránh spam)

_HELP_TEXT = (
    "🤖 *Claude trên Mac — điều khiển qua Telegram*\n\n"
    "Gõ tự do để giao việc cho Claude. Hoặc:\n"
    "• `/ask <prompt>` — hỏi/giao việc (phiên mới, context sạch)\n"
    "• `/cont <prompt>` — tiếp nối phiên gần nhất (giữ context)\n"
    "• `/auto <lệnh>` — chạy pipeline /youtube-auto\n"
    "• `/batch <lệnh>` — chạy `ytb batch <lệnh>` (status/run/retry/...), không tốn token\n"
    "• `/ytb-cmd` — menu NÚT BẤM chọn lệnh `ytb batch` từng bước, không cần nhớ cú pháp\n"
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


def _batch_run_summary() -> str:
    """Tóm tắt done/pending/lỗi thật từ queue+ledger — dùng để Telegram không báo
    "✅ Xong" mơ hồ khi 1+ video trong batch dừng giữa đường (lỗi) và bị bỏ qua."""
    try:
        from .orchestrator import batch_cli

        queue = batch_cli.load_queue()
        done = batch_cli.done_slugs()
        pending = [item.slug for item in queue if item.slug not in done]
        if not pending:
            return f"📦 Batch: {len(done)}/{len(queue)} video done (publish xong, đã verify qua YouTube API)."
        return (
            f"📦 Batch: {len(done)}/{len(queue)} done — còn {len(pending)} chưa publish "
            f"(pending hoặc lỗi giữa đường, xem `ytb batch status`): {', '.join(pending)}"
        )
    except Exception as exc:  # noqa: BLE001 — không để lỗi đọc summary che mất kết quả job chính
        return f"(không đọc được tóm tắt batch: {exc})"


def _reap(proc: subprocess.Popen, label: str) -> None:
    out, _ = proc.communicate()
    with _Job.lock:
        _Job.proc, _Job.label = None, None
    tail = (out or "").strip()[-_MAX_OUT:] or "(không có output)"
    status = "✅ Xong" if proc.returncode == 0 else f"⚠️ Mã {proc.returncode}"
    extra = f"\n\n{_batch_run_summary()}" if label.startswith("batch:") and "run" in label else ""
    telegram.send_message(f"{status}: {label}\n\n{tail}{extra}")


def _batch_cmd(args_str: str) -> list[str]:
    """`<venv python> -m ytb_pipeline.orchestrator.batch_cli <args>` — giống bin/ytb."""
    return [str(_BATCH_PYTHON), "-m", "ytb_pipeline.orchestrator.batch_cli", *shlex.split(args_str)]


def _stop() -> None:
    with _Job.lock:
        proc, label = _Job.proc, _Job.label
    if not proc or proc.poll() is not None:
        telegram.send_message("Không có job nào đang chạy.")
        return
    proc.terminate()
    telegram.send_message(f"🛑 Đã yêu cầu dừng: {label}")


# ── Router ────────────────────────────────────────────────────────────────────
def _dispatch(cmd: str) -> tuple[str, str] | None:
    """Xử lý 1 lệnh. Trả về (kind, payload) nếu là job TƯƠNG TÁC (caller chạy đồng
    bộ — kind "auto", "batch_start" hoặc "ytb_wizard"), None nếu đã xử lý xong
    (control hoặc đã spawn job nền)."""
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
    if low in _YTB_CMD_WORDS:
        if _busy():
            telegram.send_message(f"⏳ Đang bận: {_Job.label}. `/stop` trước.")
            return None
        return ("ytb_wizard", "")  # → caller chạy đồng bộ (hỏi từng bước qua nút bấm)

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
        return ("auto", rest)  # → caller chạy đồng bộ (tương tác Telegram)
    if v == "/batch":
        if not rest:
            telegram.send_message(_YTB_CMD_TEXT)
            return None
        subv = rest.split(maxsplit=1)[0]
        if subv == "start":
            if _busy():
                telegram.send_message(f"⏳ Đang bận: {_Job.label}. `/stop` trước.")
                return None
            return ("batch_start", rest)  # → caller chạy đồng bộ (Claude có thể duyệt qua Telegram)
        _spawn(f"batch: {rest[:60]}", _batch_cmd(rest))
        return None
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
            _spawn(f"claude --continue: {rest[:60]}", build_claude_cmd(rest, cont=True))
        else:
            telegram.send_message("Cú pháp: `/cont <prompt>`")
        return None
    if v in ("/ask", "/run", "/claude"):
        if rest:
            _spawn(f"claude: {rest[:60]}", build_claude_cmd(rest))
        else:
            telegram.send_message("Cú pháp: `/ask <prompt>`")
        return None

    # Mặc định: coi toàn bộ text là prompt cho Claude (phiên mới).
    _spawn(f"claude: {cmd[:60]}", build_claude_cmd(cmd))
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
            build_claude_cmd(prompt), cwd=_PROJECT_DIR, env=env,
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        telegram.send_message(f"❌ Không tìm thấy `{settings.claude_bin}`. Đặt CLAUDE_BIN.")
        return
    tail = (result.stdout or "").strip()[-_MAX_OUT:] or "(không có output)"
    status = "✅ Xong lô" if result.returncode == 0 else f"⚠️ Mã {result.returncode}"
    telegram.send_message(f"{status}: {instruction}\n\n{tail}\n\nSẵn sàng nhận lệnh tiếp.")


def _run_batch_start_sync(args_str: str) -> None:
    """Chạy ĐỒNG BỘ `ytb batch <args_str>` (vd "start -n 5 --type-of-vid long").

    Bên trong gọi `claude -p` để viết kịch bản — skill ideation có thể tự đọc
    Telegram (cổng duyệt), nên phải tạm dừng poll như /auto để tránh giành
    getUpdates với subprocess.
    """
    telegram.send_message(f"▶️ ytb batch {args_str}")
    try:
        result = subprocess.run(
            _batch_cmd(args_str), cwd=_PROJECT_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
        )
    except FileNotFoundError:
        telegram.send_message("❌ Không tìm thấy .venv (chưa `make setup`?).")
        return
    tail = (result.stdout or "").strip()[-_MAX_OUT:] or "(không có output)"
    status = "✅ Xong" if result.returncode == 0 else f"⚠️ Mã {result.returncode}"
    telegram.send_message(f"{status}: ytb batch {args_str}\n\n{tail}")


_BATCH_MENU = ["start", "status", "run", "retry", "verify", "logs", "ledger", "queue", "doctor"]
_CANCEL = "❌ Huỷ"


def _run_ytb_wizard() -> None:
    """Hỏi từng bước qua NÚT BẤM/Telegram để dựng lệnh `ytb batch ...` (cho /ytb-cmd).

    Dùng `telegram.ask_choice`/`ask_text` — cả hai tự long-poll riêng, nên phải
    chạy ĐỒNG BỘ (tạm dừng poll chính của listener) như /auto, /batch start.
    """
    choice = telegram.ask_choice("Chọn lệnh `ytb batch`:", [*_BATCH_MENU, _CANCEL])
    if choice == _CANCEL:
        telegram.send_message("Đã hủy.")
        return

    if choice == "start":
        vid_type = telegram.ask_choice("Loại video?", ["long", "short"])
        num_raw = telegram.ask_text("Bao nhiêu video? (nhập số, vd 5)")
        while not num_raw.isdigit() or int(num_raw) < 1:
            num_raw = telegram.ask_text("Nhập 1 số nguyên > 0, vd 5:")
        rules_choice = telegram.ask_choice(
            "Chủ đề?", ["Tự để Claude chọn (auto)", "Tự nhập chủ đề/định hướng"]
        )
        rules = (
            telegram.ask_text("Nhập chủ đề/định hướng:")
            if rules_choice.startswith("Tự nhập")
            else "auto"
        )
        args = ["start", "-n", num_raw, "--type-of-vid", vid_type, "--type-of-rules", rules]
        _run_batch_start_sync(shlex.join(args))
        return

    if choice == "run":
        mode = telegram.ask_choice("Chạy bao nhiêu?", ["1 video", "Hết queue (--loop)"])
        args = ["run"] if mode == "1 video" else ["run", "--loop"]
    elif choice == "retry":
        slug = telegram.ask_text("Nhập slug cần retry (xem `/batch status`):")
        args = ["retry", slug]
    elif choice == "verify":
        yid = telegram.ask_text("Nhập youtube_id cần verify:")
        args = ["verify", yid]
    elif choice == "logs":
        sub = telegram.ask_choice("Xem log gì?", ["1 video", "Cảnh báo (--warnings)"])
        if sub == "1 video":
            args = ["logs", telegram.ask_text("Nhập slug:")]
        else:
            args = ["logs", "--warnings"]
    else:  # status / ledger / queue / doctor — không cần hỏi thêm
        args = [choice]

    _spawn(f"batch: {' '.join(args)[:60]}", _batch_cmd(shlex.join(args)))


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
            result = _dispatch(cmd)
            if result is not None:  # job tương tác: chạy đồng bộ + resync
                kind, payload = result
                if kind == "auto":
                    _run_interactive(payload)
                elif kind == "batch_start":
                    _run_batch_start_sync(payload)
                else:
                    _run_ytb_wizard()
                offset = telegram.latest_update_id() + 1


if __name__ == "__main__":  # pragma: no cover
    run()
