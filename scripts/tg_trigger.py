#!/usr/bin/env python3
"""Listener Telegram — chạy nền, chờ bạn nhắn lệnh để bật pipeline.

Mô hình: bật máy → LaunchAgent tự chạy script này → bạn nhắn `/run` (hoặc bấm nút)
trên Telegram → script mở Claude Code ở thư mục dự án và chạy skill /youtube-auto.
Bạn ngồi cafe vẫn điều khiển được qua điện thoại.

Lệnh Telegram:
  /run     — bắt đầu 1 lượt sản xuất (youtube-auto)
  /status  — đang chạy hay rảnh
  /stop    — dừng lượt đang chạy

Chỉ dùng stdlib + module notify.telegram sẵn có (urllib). Không thêm dependency.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from ytb_pipeline.notify import telegram as tg

PROJECT_DIR = Path(__file__).resolve().parent.parent
CLAUDE_BIN = "/Users/hiendang/.local/bin/claude"
LOG_DIR = PROJECT_DIR / "data" / "auto_logs"
SKILL_PROMPT = "/youtube-auto"

RUN_WORDS = {"/run", "run", "chạy", "chay", "start", "/start", "bắt đầu", "bat dau"}
STATUS_WORDS = {"/status", "status", "trạng thái", "trang thai"}
STOP_WORDS = {"/stop", "stop", "dừng", "dung"}


def _launch_claude() -> subprocess.Popen:
    """Mở Claude Code headless chạy /youtube-auto trong thư mục dự án.

    Bypass permission (theo lựa chọn của user) để chạy không người canh.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # tên log cố định theo thời điểm — không dùng Date.now ở đây vì là python thuần
    log_path = LOG_DIR / "run-latest.log"
    log_fh = open(log_path, "w")  # noqa: SIM115 — giữ mở suốt vòng đời tiến trình con
    proc = subprocess.Popen(
        [
            CLAUDE_BIN,
            "--dangerously-skip-permissions",
            "-p",
            SKILL_PROMPT,
        ],
        cwd=str(PROJECT_DIR),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    return proc


def _drain_command(after_update_id: int) -> tuple[int, str | None]:
    """Long-poll 1 vòng, trả về (offset mới, lệnh chuẩn hoá hoặc None)."""
    _, chat_id = tg._require_config()
    offset = after_update_id + 1
    updates = tg._call("getUpdates", {"timeout": tg._POLL_TIMEOUT, "offset": offset}) or []
    cmd: str | None = None
    for upd in updates:
        offset = upd["update_id"] + 1
        # nút bấm
        cb = upd.get("callback_query")
        if cb and str(cb.get("message", {}).get("chat", {}).get("id")) == str(chat_id):
            tg._call("answerCallbackQuery", {"callback_query_id": cb["id"]})
            cmd = cb.get("data", "").strip().lower()
            continue
        # text
        msg = upd.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != str(chat_id):
            continue
        text = (msg.get("text") or "").strip().lower()
        if text:
            cmd = text
    return offset - 1, cmd


def _classify(cmd: str | None) -> str | None:
    if cmd is None:
        return None
    if cmd in RUN_WORDS:
        return "run"
    if cmd in STATUS_WORDS:
        return "status"
    if cmd in STOP_WORDS:
        return "stop"
    return None


def main() -> None:
    tg.send_message(
        "🤖 Listener đã sẵn sàng.\n"
        "Gửi /run để bắt đầu sản xuất, /status để xem trạng thái, /stop để dừng."
    )
    last = tg._latest_update_id()
    proc: subprocess.Popen | None = None

    while True:
        # báo khi lượt chạy vừa kết thúc
        if proc is not None and proc.poll() is not None:
            code = proc.returncode
            tg.send_message(
                f"✅ Lượt sản xuất kết thúc (exit={code}). Gửi /run để chạy tiếp."
                if code == 0
                else f"⚠️ Lượt sản xuất dừng với exit={code}. Xem data/auto_logs/run-latest.log."
            )
            proc = None

        # Khi 1 lượt đang chạy, pipeline con tự long-poll getUpdates để chờ duyệt.
        # Telegram chỉ cho 1 consumer getUpdates -> listener PHẢI ngừng poll, tránh
        # 409 Conflict. Chỉ theo dõi tiến trình con, không đụng getUpdates.
        if proc is not None and proc.poll() is None:
            time.sleep(2)
            continue

        try:
            last, raw = _drain_command(last)
        except Exception as exc:  # noqa: BLE001 — listener phải sống sót lỗi mạng tạm thời
            time.sleep(3)
            continue

        action = _classify(raw)
        if action == "run":
            if proc is not None and proc.poll() is None:
                tg.send_message("⏳ Đang có 1 lượt chạy rồi. Gửi /stop nếu muốn dừng.")
            else:
                proc = _launch_claude()
                tg.send_message("🚀 Đã bật Claude chạy /youtube-auto. Chờ câu hỏi cấu hình…")
        elif action == "status":
            running = proc is not None and proc.poll() is None
            tg.send_message("🟢 Đang chạy 1 lượt." if running else "⚪ Đang rảnh. Gửi /run.")
        elif action == "stop":
            if proc is not None and proc.poll() is None:
                proc.terminate()
                tg.send_message("🛑 Đã gửi tín hiệu dừng lượt đang chạy.")
            else:
                tg.send_message("Không có lượt nào đang chạy.")

        time.sleep(0.2)


if __name__ == "__main__":
    main()
