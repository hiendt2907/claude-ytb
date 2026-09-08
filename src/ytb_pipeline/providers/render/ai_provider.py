"""Adapter — bọc `render/compose_ai.py` (B-roll thật từ asset catalog/cache
local) thành RenderProvider. Mặc định local-only: KHÔNG gọi Pexels online,
KHÔNG cần PEXELS_API_KEY — xem `render/stock.py` cho luồng chọn asset local
trước, chỉ chạm network khi `settings.broll_allow_downloads=True`."""

from pathlib import Path

from ...pkg.models import RenderedVideo, Voiceover


class AiRenderProvider:
    name = "ai"

    async def render(self, voiceover: Voiceover, output_dir: Path) -> RenderedVideo:
        from ...render.compose_ai import render_video_ai

        return render_video_ai(voiceover)

    def is_available(self) -> bool:
        """Phản ánh đúng dependency thật của renderer, không gắn cứng API key.

        - `broll_strategy` phải là "pexels" (đường compose B-roll thật).
        - Nếu `broll_allow_downloads=True`, cần `pexels_api_key` (opt-in tải
          thêm từ mạng).
        - Nếu `broll_allow_downloads=False` (mặc định, local-only), KHÔNG yêu
          cầu API key — renderer phụ thuộc asset catalog/cache local, việc đó
          được kiểm tra fail-fast tại thời điểm render (`stock.fetch_broll*`),
          không phải ở đây (is_available là capability check tĩnh, không biết
          trước từ khoá của từng video).
        """
        from ...config.settings import settings

        if settings.broll_strategy != "pexels":
            return False
        if settings.broll_allow_downloads:
            return bool(getattr(settings, "pexels_api_key", None))
        return True
