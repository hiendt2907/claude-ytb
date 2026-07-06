"""Wan2.2 video generation local (txt2video / img2video).

`is_available()` kiểm tra model path và runner CLI có tồn tại, nhưng KHÔNG load
model (model load tốn VRAM/RAM, chỉ làm khi `generate()` thực sự được gọi).

Khi tích hợp thật, lệnh CLI mong đợi dạng:

    wan2.2 --prompt "<prompt>" --duration 6 --width 1080 --height 1920 \
        --output path.mp4 [--image path/to/start_frame.png] [--seed 42]

hoặc tương đương qua Python API (`wan2.2` package, chưa cài). Import
torch/wan KHÔNG được đặt ở module level — model nặng, instantiate provider
không nên kéo theo load torch.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ...config.settings import settings
from ..errors import ProviderUnavailableError

logger = logging.getLogger(__name__)


class WanVideoProvider:
    """Wan2.2 local video generation qua runner CLI cấu hình được."""

    name = "wan"

    def availability_status(self) -> tuple[bool, str]:
        path = settings.wan_model_path
        if not path:
            return False, "chưa cấu hình WAN_MODEL_PATH"
        model_path = Path(path)
        if not model_path.exists():
            return False, f"WAN_MODEL_PATH không tồn tại: {model_path}"
        cli = settings.wan_cli
        if shutil.which(cli) is None and not Path(cli).exists():
            return False, f"Wan CLI `{cli}` chưa có trong PATH hoặc không tồn tại"
        return True, f"model={model_path}, cli={cli}"

    def is_available(self) -> bool:
        ok, _detail = self.availability_status()
        return ok

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
        ok, detail = self.availability_status()
        if not ok:
            raise ProviderUnavailableError(
                f"WanVideoProvider không khả dụng: {detail}. "
                "Cài Wan/LTX runner hoặc dùng BROLL_STRATEGY=pexels cho footage thật."
            )

        cli = settings.wan_cli
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            cli,
            "--model",
            settings.wan_model_path,
            "--prompt",
            prompt,
            "--duration",
            f"{duration_sec:.3f}",
            "--width",
            str(width),
            "--height",
            str(height),
            "--output",
            str(output_path),
        ]
        if image_path is not None:
            cmd += ["--image", str(image_path)]
        if seed is not None:
            cmd += ["--seed", str(seed)]
        logger.info("Generating Wan clip: %s", output_path)
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        if not output_path.exists():
            raise ProviderUnavailableError(f"Wan CLI không tạo output: {output_path}")
        return output_path
