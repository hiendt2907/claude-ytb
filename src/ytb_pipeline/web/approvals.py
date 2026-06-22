"""Cổng duyệt kịch bản qua dashboard — provider thay Telegram trong tiến trình web.

Khi pipeline chạy NỀN trong tiến trình dashboard, ``gate()`` gọi
``web_request_approval`` (đăng ký qua ideation.approval.set_approval_provider).
Hàm này tạo 1 mục chờ rồi BLOCK tới khi user bấm Duyệt/Sửa trên web.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..notify.telegram import Decision, Verdict

_APPROVAL_TIMEOUT_SEC = 60 * 60  # 1 giờ — quá hạn coi như từ chối, tránh treo job


@dataclass
class Pending:
    """Một kịch bản đang chờ duyệt trên dashboard."""

    id: int
    title: str
    body: str
    event: threading.Event = field(default_factory=threading.Event)
    verdict: Verdict | None = None


_lock = threading.Lock()
_pending: dict[int, Pending] = {}
_next_id = 0


def web_request_approval(title: str, body: str) -> Verdict:
    """Provider cổng duyệt: tạo mục chờ, block tới khi user quyết định."""
    global _next_id
    with _lock:
        _next_id += 1
        item = Pending(id=_next_id, title=title, body=body)
        _pending[item.id] = item

    approved = item.event.wait(timeout=_APPROVAL_TIMEOUT_SEC)
    with _lock:
        _pending.pop(item.id, None)

    if not approved or item.verdict is None:
        return Verdict(decision=Decision.REVISE, instruction="Hết hạn chờ duyệt")
    return item.verdict


def list_pending() -> list[Pending]:
    with _lock:
        return list(_pending.values())


def resolve(item_id: int, *, approved: bool, instruction: str = "") -> bool:
    """User quyết định 1 mục chờ. Trả về True nếu tìm thấy mục."""
    with _lock:
        item = _pending.get(item_id)
        if item is None:
            return False
        item.verdict = (
            Verdict(decision=Decision.APPROVED)
            if approved
            else Verdict(decision=Decision.REVISE, instruction=instruction)
        )
    item.event.set()
    return True
