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
        from ..registry import get_image_provider, get_video_provider

        if settings.broll_strategy == "pexels":
            return bool(getattr(settings, "pexels_api_key", None))
        if settings.broll_strategy in {"local_video", "mixed", "ai_video"}:
            return get_video_provider(settings.video_provider).is_available()
        return get_image_provider(settings.image_provider).is_available()
