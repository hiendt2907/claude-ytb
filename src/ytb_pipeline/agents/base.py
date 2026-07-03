"""Agent Protocol + result types — base cho 5 agent độc lập (Phase 5).

Mỗi agent wrap logic sẵn có (research/series/claude_cli/platform...) thành
một đơn vị test-được riêng: nhận `context` dict, trả `AgentResult`, KHÔNG bao
giờ raise — lỗi luôn được bọc thành `AgentResult(status=FAILED)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class AgentStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class AgentResult:
    """Output chuẩn hoá của mọi agent — immutable."""

    agent_name: str
    status: AgentStatus
    output: Any
    error: str | None = None
    token_cost: int = 0
    latency_ms: int = 0


@runtime_checkable
class Agent(Protocol):
    """Giao diện chung mọi agent phải tuân theo."""

    name: str

    async def run(self, context: dict[str, Any]) -> AgentResult:
        """Chạy agent với `context` cho sẵn. KHÔNG BAO GIỜ raise."""
        ...

    def can_run(self, context: dict[str, Any]) -> bool:
        """True nếu context đủ key bắt buộc để chạy."""
        ...

    @property
    def required_context_keys(self) -> list[str]:
        """Các key bắt buộc phải có trong context."""
        ...
