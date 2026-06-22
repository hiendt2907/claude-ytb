"""Cổng phê duyệt qua Telegram — gửi nội dung cho user duyệt, nhận phản hồi.

Dùng cho khâu Ideation: sau khi sinh kịch bản, gửi sang Telegram để user duyệt.
User trả lời:
  - "OK" / "duyệt" / "ok" -> chấp nhận (Decision.approved)
  - bất kỳ text khác        -> coi là YÊU CẦU SỬA (Decision.revise, .instruction)

Chỉ dùng HTTP Bot API qua urllib (stdlib) — không thêm dependency.
Token + chat_id đọc từ settings (env), KHÔNG hardcode secret.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum

from ..config.settings import settings

API_BASE = "https://api.telegram.org/bot{token}/{method}"
_HTTP_TIMEOUT = 65  # > long-poll timeout của getUpdates
_POLL_TIMEOUT = 50  # giây mỗi vòng long-poll
APPROVE_WORDS = {"ok", "duyệt", "duyet", "yes", "đồng ý", "dong y", "approve"}


class Decision(str, Enum):
    APPROVED = "approved"
    REVISE = "revise"


@dataclass(frozen=True)
class Verdict:
    """Kết quả duyệt từ Telegram."""

    decision: Decision
    instruction: str = ""  # nội dung yêu cầu sửa (rỗng nếu approved)


def _require_config() -> tuple[str, str]:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        raise RuntimeError(
            "Thiếu TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID trong .env — "
            "không thể gửi duyệt qua Telegram."
        )
    return token, chat_id


def _call(method: str, params: dict) -> dict:
    """Gọi Bot API, trả về 'result'. Raise nếu Telegram báo lỗi."""
    token, _ = _require_config()
    url = API_BASE.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode())
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API lỗi ({method}): {payload}")
    return payload.get("result")


def send_message(text: str) -> None:
    """Gửi 1 tin nhắn cho user. Tự cắt nếu vượt 4096 ký tự (giới hạn Telegram)."""
    _, chat_id = _require_config()
    for chunk in _split(text, 4096):
        _call("sendMessage", {"chat_id": chat_id, "text": chunk})


def request_approval(title: str, body: str, *, poll_until_reply: bool = True) -> Verdict:
    """Gửi nội dung cho user duyệt và CHỜ phản hồi.

    Trả về Verdict: APPROVED nếu user gõ từ đồng ý; REVISE + instruction nếu khác.
    Bỏ qua mọi message cũ trước thời điểm gửi (chỉ nhận reply MỚI).
    """
    baseline = _latest_update_id()
    send_message(
        f"🎬 *Kịch bản chờ duyệt*\n\n{title}\n\n{body}\n\n"
        "Trả lời *OK* để duyệt, hoặc nhắn yêu cầu sửa."
    )
    if not poll_until_reply:
        return Verdict(Decision.REVISE, "")
    reply = _wait_for_reply(after_update_id=baseline)
    if reply.strip().lower() in APPROVE_WORDS:
        return Verdict(Decision.APPROVED)
    return Verdict(Decision.REVISE, reply.strip())


def ask_choice(question: str, options: list[str]) -> str:
    """Gửi câu hỏi kèm NÚT BẤM inline, CHỜ user bấm, trả về nhãn đã chọn.

    Mỗi option là 1 nút (callback_data = chỉ số). Bỏ qua mọi callback cũ trước
    thời điểm hỏi — chỉ nhận lựa chọn MỚI cho đúng câu hỏi này.
    """
    _, chat_id = _require_config()
    baseline = _latest_update_id()
    keyboard = [[{"text": opt, "callback_data": str(i)}] for i, opt in enumerate(options)]
    _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": f"❓ {question}",
            "reply_markup": json.dumps({"inline_keyboard": keyboard}),
        },
    )
    idx = _wait_for_choice(after_update_id=baseline, num_options=len(options))
    return options[idx]


def _wait_for_choice(*, after_update_id: int, num_options: int) -> int:
    """Long-poll tới khi user bấm 1 nút hợp lệ. Trả về chỉ số option đã chọn."""
    _, chat_id = _require_config()
    offset = after_update_id + 1
    while True:
        updates = (
            _call("getUpdates", {"timeout": _POLL_TIMEOUT, "offset": offset}) or []
        )
        for upd in updates:
            offset = upd["update_id"] + 1
            cb = upd.get("callback_query")
            if not cb:
                continue
            if str(cb.get("message", {}).get("chat", {}).get("id")) != str(chat_id):
                continue
            data = cb.get("data", "")
            # xác nhận để Telegram tắt trạng thái "loading" trên nút
            _call("answerCallbackQuery", {"callback_query_id": cb["id"]})
            if data.isdigit() and 0 <= int(data) < num_options:
                return int(data)
        time.sleep(0.1)


def _latest_update_id() -> int:
    """update_id mới nhất hiện có (để chỉ nhận message gửi SAU lời mời duyệt)."""
    updates = _call("getUpdates", {"timeout": 0, "limit": 100, "offset": -1}) or []
    return updates[-1]["update_id"] if updates else 0


def _wait_for_reply(*, after_update_id: int) -> str:
    """Long-poll cho tới khi user gửi 1 text message mới. Trả về text đó."""
    _, chat_id = _require_config()
    offset = after_update_id + 1
    while True:
        updates = (
            _call("getUpdates", {"timeout": _POLL_TIMEOUT, "offset": offset}) or []
        )
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != str(chat_id):
                continue
            text = msg.get("text")
            if text:
                return text
        # không có reply trong vòng poll này -> lặp tiếp (Telegram đã chờ sẵn)
        time.sleep(0.1)


def latest_update_id() -> int:
    """API công khai: update_id mới nhất hiện có (để bỏ qua backlog cũ).

    Listener dùng để RESYNC offset sau mỗi phiên `claude -p` — vì subprocess đó đã
    tự ăn (advance) các update trong lúc duyệt, listener phải nhảy qua để khỏi xử
    lý lại lệnh cũ.
    """
    return _latest_update_id()


def poll_messages(*, offset: int, timeout: int = _POLL_TIMEOUT) -> tuple[list[str], int]:
    """Long-poll MỘT vòng, trả về (danh sách text mới từ đúng chat, offset kế tiếp).

    Không vòng lặp vô hạn như `_wait_for_reply`: trả ngay sau 1 lần getUpdates để
    caller (listener) tự điều phối. Chỉ lấy text message từ `telegram_chat_id`.
    """
    _, chat_id = _require_config()
    updates = _call("getUpdates", {"timeout": timeout, "offset": offset}) or []
    texts: list[str] = []
    next_offset = offset
    for upd in updates:
        next_offset = upd["update_id"] + 1
        msg = upd.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != str(chat_id):
            continue
        text = msg.get("text")
        if text:
            texts.append(text)
    return texts, next_offset


def _split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
