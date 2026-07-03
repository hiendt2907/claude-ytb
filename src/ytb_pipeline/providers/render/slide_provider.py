"""Adapter — bọc `render/compose.py` (caption Pillow + audio ffmpeg) thành
RenderProvider."""

from pathlib import Path

from ...pkg.models import RenderedVideo, Voiceover


class SlideRenderProvider:
    name = "slide"

    async def render(self, voiceover: Voiceover, output_dir: Path) -> RenderedVideo:
        from ...render.compose import render_video

        return render_video(voiceover)

    def is_available(self) -> bool:
        try:
            import PIL  # noqa: F401

            return True
        except ImportError:
            return False
