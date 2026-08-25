"""RenderProvider adapter for profile-owned character story assets."""

from __future__ import annotations

import shutil
from pathlib import Path

from ...pkg.models import RenderedVideo, Voiceover


class StoryRenderProvider:
    name = "story"

    async def render(self, voiceover: Voiceover, output_dir: Path) -> RenderedVideo:
        from ...render.story import render_story_video

        return render_story_video(voiceover, output_dir)

    def is_available(self) -> bool:
        return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
