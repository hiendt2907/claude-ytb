"""Provider Protocols — hợp đồng cho từng khâu (voice/render/publish).

Mỗi Protocol mô tả tối thiểu những gì pipeline cần từ một provider: tên định
danh, hàm thực hiện việc chính (async), và `is_available()` để kiểm tra
dependency/credential trước khi dùng (vd F5 cần .venv-tts, YouTube cần OAuth).
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..pkg.models import PublishResult, RenderedVideo, Script, Voiceover


@runtime_checkable
class VoiceProvider(Protocol):
    """Synthesise narration cho 1 Script → Voiceover."""

    name: str

    async def synthesise(self, script: Script, output_dir: Path) -> Voiceover: ...

    def is_available(self) -> bool: ...


@runtime_checkable
class RenderProvider(Protocol):
    """Render 1 Voiceover → RenderedVideo."""

    name: str

    async def render(self, voiceover: Voiceover, output_dir: Path) -> RenderedVideo: ...

    def is_available(self) -> bool: ...


@runtime_checkable
class PublishProvider(Protocol):
    """Publish 1 RenderedVideo → PublishResult."""

    name: str

    async def publish(self, video: RenderedVideo) -> PublishResult: ...

    def is_available(self) -> bool: ...


@runtime_checkable
class ImageProvider(Protocol):
    """Generate a background/scene image from a text prompt."""

    name: str

    def generate(
        self,
        prompt: str,
        width: int,
        height: int,
        output_path: Path,
        *,
        negative_prompt: str = "",
        seed: int | None = None,
    ) -> Path:
        """Generate image, save to output_path, return output_path."""
        ...

    def is_available(self) -> bool:
        """Check if this provider can run (model loaded, service up, etc.)"""
        ...


@runtime_checkable
class VideoProvider(Protocol):
    """Generate a short video clip from a text prompt."""

    name: str

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
        """Generate video clip, save to output_path, return output_path."""
        ...

    def is_available(self) -> bool: ...


@runtime_checkable
class LLMProvider(Protocol):
    """Generate text from a prompt."""

    name: str

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        json_output: bool = False,
    ) -> str:
        """Return completion text."""
        ...

    def is_available(self) -> bool: ...

    def model_name(self) -> str: ...
