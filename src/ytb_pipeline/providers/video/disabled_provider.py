"""Video provider disabled for hardware-safe image-motion rendering."""

from pathlib import Path

from ..errors import ProviderUnavailableError


class DisabledVideoProvider:
    """Sentinel provider used when local video generation is intentionally off."""

    name = "disabled"

    def availability_status(self) -> tuple[bool, str]:
        return (
            False,
            "video provider disabled; production render dùng BROLL_STRATEGY=pexels "
            "và VIDEO_PROVIDER=pexels để lấy footage thật",
        )

    def is_available(self) -> bool:
        return False

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
        raise ProviderUnavailableError(self.availability_status()[1])
