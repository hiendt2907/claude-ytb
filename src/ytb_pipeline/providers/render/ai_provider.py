"""Adapter — bọc `render/compose_ai.py` (B-roll Pexels) thành RenderProvider."""

from pathlib import Path

from ...pkg.models import RenderedVideo, Voiceover


class AiRenderProvider:
    name = "ai"

    async def render(self, voiceover: Voiceover, output_dir: Path) -> RenderedVideo:
        from ...render.compose_ai import render_video_ai

        return render_video_ai(voiceover)

    def is_available(self) -> bool:
        from ...config.settings import settings

        return settings.broll_strategy == "pexels" and bool(getattr(settings, "pexels_api_key", None))
