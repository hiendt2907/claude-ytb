"""configure_local_stack() — chuyển pipeline sang local inference phù hợp máy Mac.

Gọi khi `settings.local_mode=True` (vd `OMNI_LOCAL=true` trong .env). Đổi
provider selection cho các khâu chính sang bản local, không cần cloud key:
ollama/f5/pillow + ffmpeg image-motion render. Wan video local là opt-in riêng vì cần
GPU/VRAM lớn hơn profile M4 Pro 24GB. Provider nào không khả dụng (model chưa
tải, service chưa chạy) chỉ log warning — KHÔNG raise, vì pipeline vẫn phải
khởi động được (graceful degrade), lỗi thật sự chỉ lộ ra khi agent dùng provider đó.
"""

from __future__ import annotations

import logging

from ..config.settings import settings
from .registry import get_image_provider, get_llm_provider

logger = logging.getLogger(__name__)

_LOCAL_LLM = "ollama"
_LOCAL_TTS = "f5"
_LOCAL_IMAGE = "pillow"
_LOCAL_VIDEO = "disabled"


def configure_local_stack() -> None:
    """Override settings để dùng stack local an toàn phần cứng."""
    settings.llm_provider = _LOCAL_LLM
    settings.tts_provider = _LOCAL_TTS
    settings.image_provider = _LOCAL_IMAGE
    settings.video_provider = _LOCAL_VIDEO
    settings.broll_strategy = "local_image_motion"

    _warn_if_unavailable("llm", get_llm_provider, _LOCAL_LLM)
    _warn_if_unavailable("image", get_image_provider, _LOCAL_IMAGE)


def _warn_if_unavailable(kind: str, getter, name: str) -> None:
    try:
        provider = getter(name)
        if not provider.is_available():
            logger.warning("Local stack: %s provider '%s' chưa khả dụng.", kind, name)
    except Exception as exc:  # noqa: BLE001 — configure KHÔNG BAO GIỜ raise
        logger.warning("Local stack: không khởi tạo được %s provider '%s': %s", kind, name, exc)
