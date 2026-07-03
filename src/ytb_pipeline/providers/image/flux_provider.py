"""Flux txt2img qua ComfyUI local API.

Provider này kiểm tra cả service ComfyUI lẫn checkpoint Flux đã khai báo trong
settings. Nếu thiếu runtime hoặc model, `is_available()` trả False và
`generate()` raise `ProviderUnavailableError` với hướng xử lý cụ thể.

Workflow JSON gửi tới ComfyUI (`POST /prompt`) theo cấu trúc node chuẩn:

    CheckpointLoaderSimple(ckpt_name=settings.flux_checkpoint_name)
      -> CLIPTextEncode(text=prompt)          # positive
      -> CLIPTextEncode(text=negative_prompt) # negative
      -> EmptyLatentImage(width, height)
      -> KSampler(seed, steps, cfg, sampler_name, scheduler, denoise)
      -> VAEDecode
      -> SaveImage

Workflow mặc định dùng bản FP8 checkpoint một-file để bootstrap dễ hơn trên
máy local. Có thể đổi `FLUX_CHECKPOINT_NAME` khi dùng checkpoint khác.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ...config.settings import settings
from ..errors import ProviderUnavailableError

_PING_TIMEOUT_S = 2.0
_REQUEST_TIMEOUT_S = 60.0
_POLL_INTERVAL_S = 0.5
_POLL_ATTEMPTS = 120


def _build_workflow(prompt: str, negative_prompt: str, width: int,
                    height: int, seed: int | None) -> dict:
    """Workflow txt2img tối giản cho ComfyUI (Flux checkpoint)."""
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed if seed is not None else 0,
                "steps": 20,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": settings.flux_checkpoint_name},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ytb_pipeline", "images": ["8", 0]},
        },
    }


class FluxImageProvider:
    """ComfyUI/Flux provider — chỉ chạy khi server và checkpoint đều sẵn sàng."""

    name = "flux"

    def availability_status(self) -> tuple[bool, str]:
        base = settings.comfyui_url.rstrip("/")
        try:
            with urllib.request.urlopen(f"{base}/system_stats", timeout=_PING_TIMEOUT_S) as response:
                if response.status != 200:
                    return False, f"ComfyUI trả HTTP {response.status} tại {base}"

            checkpoints = self._checkpoint_names()
            checkpoint = settings.flux_checkpoint_name
            if checkpoint not in checkpoints:
                found = ", ".join(sorted(checkpoints)[:5]) or "không có checkpoint nào"
                return (
                    False,
                    f"thiếu Flux checkpoint `{checkpoint}` trong ComfyUI/models/checkpoints "
                    f"(đang thấy: {found})",
                )
            return True, f"ComfyUI tại {base}, checkpoint={checkpoint}"
        except (urllib.error.URLError, OSError, ValueError):
            return False, f"ComfyUI không phản hồi tại {base}"

    def is_available(self) -> bool:
        ok, _detail = self.availability_status()
        return ok

    def _checkpoint_names(self) -> set[str]:
        url = f"{settings.comfyui_url.rstrip('/')}/object_info/CheckpointLoaderSimple"
        with urllib.request.urlopen(url, timeout=_PING_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
        node = body.get("CheckpointLoaderSimple", {})
        required = node.get("input", {}).get("required", {})
        ckpt_spec = required.get("ckpt_name", [])
        names = ckpt_spec[0] if ckpt_spec and isinstance(ckpt_spec[0], list) else []
        return {str(name) for name in names}

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
        ok, detail = self.availability_status()
        if not ok:
            raise ProviderUnavailableError(f"FluxImageProvider không khả dụng: {detail}")

        workflow = _build_workflow(prompt, negative_prompt, width, height, seed)
        payload = json.dumps({"prompt": workflow}).encode("utf-8")
        url = f"{settings.comfyui_url.rstrip('/')}/prompt"
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise ProviderUnavailableError(f"ComfyUI không trả prompt_id: {body}")

        image_meta = self._wait_for_image(prompt_id)
        image_bytes = self._download_image(image_meta)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return output_path

    def _wait_for_image(self, prompt_id: str) -> dict:
        base = settings.comfyui_url.rstrip("/")
        url = f"{base}/history/{urllib.parse.quote(prompt_id)}"
        for _ in range(_POLL_ATTEMPTS):
            with urllib.request.urlopen(url, timeout=_PING_TIMEOUT_S) as response:
                history = json.loads(response.read().decode("utf-8"))
            outputs = history.get(prompt_id, {}).get("outputs", {})
            for node in outputs.values():
                images = node.get("images") or []
                if images:
                    return images[0]
            time.sleep(_POLL_INTERVAL_S)
        raise ProviderUnavailableError(f"ComfyUI không sinh ảnh sau {_POLL_ATTEMPTS * _POLL_INTERVAL_S:.0f}s")

    def _download_image(self, meta: dict) -> bytes:
        query = urllib.parse.urlencode({
            "filename": meta.get("filename", ""),
            "subfolder": meta.get("subfolder", ""),
            "type": meta.get("type", "output"),
        })
        url = f"{settings.comfyui_url.rstrip('/')}/view?{query}"
        with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT_S) as response:
            return response.read()
