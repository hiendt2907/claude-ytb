"""Video provider disabled for hardware-safe image-motion rendering."""

from pathlib import Path

from ..errors import ProviderUnavailableError


class DisabledVideoProvider:
    """Sentinel provider used when local video generation is intentionally off."""

    name = "disabled"

    def availability_status(self) -> tuple[bool, str]:
        return (
            False,
            "local video generation disabled; dùng BROLL_STRATEGY=local_image_motion "
            "hoặc cấu hình VIDEO_PROVIDER=wan trên máy GPU phù hợp",
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
