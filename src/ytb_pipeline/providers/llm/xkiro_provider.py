"""XkiroLLMProvider — bọc endpoint OpenAI-compatible `/v1/chat/completions`
của xKiro. Tách hẳn khỏi `XkiroVoiceProvider` (TTS) dù dùng chung API key.

Tài khoản free chỉ truy cập được một tập con model trong `GET /v1/models`
(model gắn nhãn thương hiệu lớn trả HTTP 403). `xkiro_llm_model` +
`xkiro_llm_fallback_models` được chốt qua benchmark thật (xem
docs/TOOL_UPGRADE_PLAN.md), không đoán — model nào lỗi/HTTP xấu thì loại.
"""

from __future__ import annotations

import asyncio
import json
from urllib import error as urllib_error
from urllib import request as urllib_request

from ...config.settings import settings
from ..errors import ProviderUnavailableError

_REQUEST_TIMEOUT_S = 60.0


class XkiroLLMProvider:
    """LLM cloud qua xKiro; thử `xkiro_llm_model` trước, rồi lần lượt các
    model trong `xkiro_llm_fallback_models` (CSV) khi model trước lỗi."""

    name = "xkiro"

    def is_available(self) -> bool:
        return bool(settings.xkiro_api_key.strip())

    def model_name(self) -> str:
        return settings.xkiro_llm_model

    def _candidate_models(self) -> list[str]:
        fallbacks = [
            m.strip()
            for m in settings.xkiro_llm_fallback_models.split(",")
            if m.strip()
        ]
        return [settings.xkiro_llm_model, *fallbacks]

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        json_output: bool = False,
        response_schema: dict | None = None,
    ) -> str:
        if not self.is_available():
            raise ProviderUnavailableError(
                "xKiro chưa khả dụng — cấu hình XKIRO_API_KEY trong .env."
            )

        last_error: Exception | None = None
        for model in self._candidate_models():
            try:
                return await asyncio.to_thread(
                    self._request, model, prompt, system, max_tokens, temperature
                )
            except (RuntimeError, urllib_error.URLError, TimeoutError) as exc:
                last_error = exc
                continue
        raise ProviderUnavailableError(
            f"xKiro LLM: mọi model trong danh sách đều lỗi. Lỗi cuối: {last_error}"
        )

    def _request(
        self, model: str, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        ).encode("utf-8")
        request = urllib_request.Request(
            settings.xkiro_llm_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.xkiro_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ytb-pipeline/1.0 (+https://xkiro.com)",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            raise RuntimeError(f"xKiro LLM ({model}) trả HTTP {exc.code}.") from exc

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"xKiro LLM ({model}) trả response không có choices.")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError(f"xKiro LLM ({model}) trả content rỗng.")
        return content
