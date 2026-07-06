"""configure_local_stack() — chuyển LLM/TTS sang local inference phù hợp máy Mac.

Gọi khi `settings.local_mode=True` (vd `OMNI_LOCAL=true` trong .env). Đổi
provider selection cho phần inference local: ollama + f5. Render vẫn dùng Pexels
footage thật; không còn fallback Pillow image-motion trong production. Provider nào
không khả dụng (model chưa tải, service chưa chạy) chỉ log warning — KHÔNG raise,
vì pipeline vẫn phải khởi động được (graceful degrade), lỗi thật sự chỉ lộ ra khi
agent dùng provider đó.
"""

from __future__ import annotations

import logging

from ..config.settings import settings
from .registry import get_llm_provider

logger = logging.getLogger(__name__)

_LOCAL_LLM = "ollama"
_LOCAL_TTS = "f5"


def configure_local_stack() -> None:
    """Override settings để dùng local LLM/TTS, giữ render bằng Pexels footage."""
    settings.llm_provider = _LOCAL_LLM
    settings.tts_provider = _LOCAL_TTS

    _warn_if_unavailable("llm", get_llm_provider, _LOCAL_LLM)


def _warn_if_unavailable(kind: str, getter, name: str) -> None:
    try:
        provider = getter(name)
        if not provider.is_available():
            logger.warning("Local stack: %s provider '%s' chưa khả dụng.", kind, name)
    except Exception as exc:  # noqa: BLE001 — configure KHÔNG BAO GIỜ raise
        logger.warning("Local stack: không khởi tạo được %s provider '%s': %s", kind, name, exc)
