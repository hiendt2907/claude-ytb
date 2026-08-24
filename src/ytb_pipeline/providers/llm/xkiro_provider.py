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
# Slowest sustained generation rate we are willing to wait through.  A flat
# 60s budget was sized for Short-scale requests; a Long asks for ~14k tokens
# and every model in the cascade reported a read timeout, which the caller
# then mistook for four separate model failures.
_MIN_OUTPUT_TOKENS_PER_SEC = 40.0


def request_timeout_for(*, max_tokens: int) -> float:
    """Read budget that grows with the size of the answer being asked for."""
    return max(_REQUEST_TIMEOUT_S, max_tokens / _MIN_OUTPUT_TOKENS_PER_SEC)


class _ResponseFormatUnsupportedError(RuntimeError):
    """The gateway rejected `response_format`, not the selected model."""


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
                response_format = self._response_format(json_output, response_schema)
                try:
                    return await asyncio.to_thread(
                        self._request, model, prompt, system, max_tokens, temperature, response_format
                    )
                except _ResponseFormatUnsupportedError:
                    if response_format is None or response_format["type"] != "json_schema":
                        raise
                    # A schema rejection is a capability mismatch, not a model
                    # failure.  Retry JSON mode on this exact model first.
                    return await asyncio.to_thread(
                        self._request,
                        model,
                        prompt,
                        system,
                        max_tokens,
                        temperature,
                        {"type": "json_object"},
                    )
            except _ResponseFormatUnsupportedError as exc:
                # Both structured formats were rejected.  This is a gateway
                # capability problem, so changing model or cascading to a
                # different provider would conceal the real integration fault.
                raise ProviderUnavailableError(str(exc)) from exc
            except (RuntimeError, urllib_error.URLError, TimeoutError) as exc:
                last_error = exc
                continue
        raise ProviderUnavailableError(
            f"xKiro LLM: mọi model trong danh sách đều lỗi. Lỗi cuối: {last_error}"
        )

    @staticmethod
    def _response_format(json_output: bool, response_schema: dict | None) -> dict | None:
        if not json_output:
            return None
        if response_schema is None:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "youtube_script",
                "strict": True,
                "schema": response_schema,
            },
        }

    def _request(
        self,
        model: str,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        response_format: dict | None = None,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload_data = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format is not None:
            payload_data["response_format"] = response_format
        payload = json.dumps(payload_data).encode("utf-8")
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
            with urllib_request.urlopen(
                request, timeout=request_timeout_for(max_tokens=max_tokens),
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            if exc.code == 400 and response_format is not None:
                raise _ResponseFormatUnsupportedError(
                    f"xKiro LLM ({model}) từ chối response_format={response_format['type']}."
                ) from exc
            raise RuntimeError(f"xKiro LLM ({model}) trả HTTP {exc.code}.") from exc

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"xKiro LLM ({model}) trả response không có choices.")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError(f"xKiro LLM ({model}) trả content rỗng.")
        return content
