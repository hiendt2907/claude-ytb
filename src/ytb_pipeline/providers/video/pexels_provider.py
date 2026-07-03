"""Adapter — bọc `render/stock.py` (Pexels B-roll) thành VideoProvider.

Pexels không sinh video từ prompt thật — nó TÌM một clip B-roll khớp từ khoá
(`prompt` đóng vai trò query tìm kiếm). Vẫn hữu ích như "video provider" mặc
định vì luôn khả dụng (chỉ cần free API key), không cần GPU/model local.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ...config.settings import settings
from ...render import stock
from ..errors import ProviderUnavailableError


class PexelsVideoProvider:
    """Tìm + tải B-roll Pexels khớp `prompt`, không sinh video thật từ text."""

    name = "pexels"

    def is_available(self) -> bool:
        return bool(settings.pexels_api_key)

    def generate(
        self,
        prompt: str,
        duration_sec: float,
        width: int,
        height: int,
        output_path: Path,
        *,
        image_path: Path | None = None,
        seed: int | None = None,
    ) -> Path:
        if not self.is_available():
            raise ProviderUnavailableError(
                "Thiếu PEXELS_API_KEY — PexelsVideoProvider không khả dụng."
            )

        landscape = width >= height
        cached = stock.fetch_broll(
            prompt, min_duration=duration_sec, landscape=landscape
        )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, output_path)
        return output_path
