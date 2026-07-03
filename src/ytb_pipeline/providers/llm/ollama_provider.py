"""OllamaProvider — local LLM qua Ollama HTTP API (`/api/generate`).

Chỉ dùng stdlib (`urllib`) — không thêm dependency. `is_available()` ping
`/api/tags` với timeout ngắn; nếu Ollama không chạy, provider coi như không
khả dụng và `complete()` raise `ProviderUnavailableError` để caller fallback
(vd về "claude").
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ...config.settings import settings
from ..errors import ProviderUnavailableError

_PING_TIMEOUT_S = 2.0
_REQUEST_TIMEOUT_S = 120.0


class OllamaProvider:
    """LLM local qua Ollama (`ollama serve`), model mặc định qwen2.5-coder:7b."""

    name = "ollama"

    def is_available(self) -> bool:
        url = f"{settings.ollama_url.rstrip('/')}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=_PING_TIMEOUT_S) as resp:
                if resp.status != 200:
                    return False
                body = json.loads(resp.read().decode("utf-8"))
                models = body.get("models", [])
                names = {m.get("name", "") for m in models if isinstance(m, dict)}
                return settings.ollama_model in names
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def model_name(self) -> str:
        return settings.ollama_model

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        json_output: bool = False,
    ) -> str:
        if not self.is_available():
            raise ProviderUnavailableError(
                f"Ollama không phản hồi tại {settings.ollama_url} — "
                "OllamaProvider không khả dụng."
            )

        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload: dict = {
            "model": settings.ollama_model,
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_output:
            payload["format"] = "json"

        url = f"{settings.ollama_url.rstrip('/')}/api/generate"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body.get("response", "")
