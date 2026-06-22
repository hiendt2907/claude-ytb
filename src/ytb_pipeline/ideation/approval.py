"""Cổng duyệt kịch bản qua Telegram, chèn giữa Ideation và Voiceover.

Mô hình hiện tại: kịch bản do Claude viết sẵn thành scripts/*.json (không có LLM
trong code batch). Vì vậy cổng này chỉ DUYỆT / TỪ CHỐI:

  - User duyệt  -> trả lại Script, pipeline render tiếp.
  - User yêu cầu sửa -> raise ScriptRevisionRequested(instruction); caller dừng sạch.
    Việc sửa kịch bản theo yêu cầu (qua LLM) do skill youtube-ideation thực hiện
    trong phiên chat, rồi chạy lại pipeline với JSON đã sửa.
"""

from __future__ import annotations

from typing import Callable

from ..config.settings import settings
from ..notify.telegram import Decision, Verdict, request_approval, send_message
from ..pkg.models import Script

# Cho phép thay cổng duyệt (vd dashboard web đăng ký provider riêng). Mặc định
# None = dùng Telegram. Provider nhận (title, body) trả về Verdict như Telegram.
_approval_provider: Callable[[str, str], Verdict] | None = None


def set_approval_provider(provider: Callable[[str, str], Verdict] | None) -> None:
    """Đăng ký cổng duyệt thay thế Telegram cho tiến trình hiện tại."""
    global _approval_provider
    _approval_provider = provider


class ScriptRevisionRequested(Exception):
    """User yêu cầu sửa kịch bản qua Telegram thay vì duyệt."""

    def __init__(self, instruction: str) -> None:
        super().__init__(instruction)
        self.instruction = instruction


def gate(script: Script) -> Script:
    """Chờ user duyệt kịch bản qua Telegram. Bỏ qua nếu tắt cổng.

    Raise ScriptRevisionRequested nếu user yêu cầu sửa.
    """
    if not settings.telegram_approval:
        return script

    # Cổng web (dashboard) thay Telegram nếu đã đăng ký provider.
    if _approval_provider is not None:
        verdict = _approval_provider(script.title, _format_full(script))
        if verdict.decision is Decision.APPROVED:
            return script
        raise ScriptRevisionRequested(verdict.instruction)

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print(
            "⚠️  TELEGRAM_APPROVAL bật nhưng thiếu TELEGRAM_BOT_TOKEN/CHAT_ID — "
            "bỏ qua cổng duyệt, render thẳng."
        )
        return script

    verdict = request_approval(script.title, _format_full(script))
    if verdict.decision is Decision.APPROVED:
        send_message("✅ Đã duyệt. Bắt đầu render.")
        return script

    send_message(
        "📝 Đã ghi nhận yêu cầu sửa. Cập nhật kịch bản rồi chạy lại pipeline.\n\n"
        f"Yêu cầu: {verdict.instruction}"
    )
    raise ScriptRevisionRequested(verdict.instruction)


def _format_full(script: Script) -> str:
    """Bản đầy đủ để duyệt trên điện thoại: tiêu đề, tags, toàn bộ narration."""
    tags = ", ".join(script.tags) if script.tags else "(không)"
    lines = [f"📌 {script.title}", f"🏷️ {tags}", ""]
    for i, seg in enumerate(script.segments, 1):
        lines.append(f"[{i}] {seg.narration}")
    return "\n".join(lines)
