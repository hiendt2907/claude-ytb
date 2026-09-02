"""XkiroLLMProvider — bọc endpoint OpenAI-compatible `/v1/chat/completions`
của xKiro. Tách hẳn khỏi `XkiroVoiceProvider` (TTS) dù dùng chung API key.

Ideation cố ý chỉ gọi model được cấu hình (`deepseek/deepseek-v4-pro` trên
xKiro, tức DeepSeek V4 Pro).
Một lỗi phải được trả thẳng về operator: không thử model khác và không che
nguồn gốc/năng lực thực tế của kịch bản.
"""

from __future__ import annotations

import asyncio
import json
from urllib import error as urllib_error
from urllib import request as urllib_request

from ...config.settings import settings
from ..errors import ProviderUnavailableError

# Production 2026-08-27: `run_editorial_review()` asks for only 1024 output
# tokens (small) but sends a full script + rubric as INPUT — xKiro can take
# a long time to finish reading that context before producing any output,
# and the formula below only scales with requested OUTPUT size. A flat 60s
# floor is too tight for that prefill latency; 600s covers it while still
# scaling further up for genuinely large output requests below.
_REQUEST_TIMEOUT_S = 600.0
# Slowest sustained generation rate we are willing to wait through.  A flat
# 60s budget was sized for Short-scale requests; a Long asks for ~14k tokens.
_MIN_OUTPUT_TOKENS_PER_SEC = 40.0


def request_timeout_for(*, max_tokens: int) -> float:
    """Read budget that grows with the size of the answer being asked for."""
    return max(_REQUEST_TIMEOUT_S, max_tokens / _MIN_OUTPUT_TOKENS_PER_SEC)


# Gateway thỉnh thoảng cắt một ký tự nhiều byte giữa chừng. Đo trên production:
# hai lượt sinh Long liên tiếp hỏng vì đúng lỗi đó ("câu trả l\ufffd\ufffd\ufffdi",
# "gi\ufffd\ufffd này"), mỗi lần mất trọn vài phút sinh. Byte đã mất không đoán lại
# được, nên cách duy nhất đúng là hỏi lại provider — có trần, không quay vòng.
MAX_CORRUPT_RESPONSE_RETRIES = 2


class _CorruptResponseError(RuntimeError):
    """Body không phải UTF-8 hợp lệ — byte hỏng trên đường truyền."""


class _ResponseFormatUnsupportedError(RuntimeError):
    """The gateway rejected `response_format`, not the selected model."""


class _ResponseFormatGatewayError(RuntimeError):
    """The gateway crashes only when an OpenAI response format is supplied."""


class XkiroLLMProvider:
    """LLM cloud qua xKiro, gọi đúng một model đã được cấu hình."""

    name = "xkiro"

    def is_available(self) -> bool:
        return bool(settings.xkiro_api_key.strip())

    def model_name(self) -> str:
        return settings.xkiro_llm_model

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

        model = self.model_name()
        response_format = self._response_format(json_output, response_schema)
        for attempt in range(MAX_CORRUPT_RESPONSE_RETRIES + 1):
            try:
                return await self._complete_once(
                    model, prompt, system, max_tokens, temperature, response_format
                )
            except _CorruptResponseError as exc:
                if attempt == MAX_CORRUPT_RESPONSE_RETRIES:
                    raise ProviderUnavailableError(str(exc)) from exc
                continue
        raise AssertionError("unreachable")

    async def _complete_once(
        self, model, prompt, system, max_tokens, temperature, response_format
    ) -> str:
        try:
            try:
                return await asyncio.to_thread(
                    self._request, model, prompt, system, max_tokens, temperature, response_format
                )
            except _ResponseFormatGatewayError:
                # Some xKiro gateways acknowledge OpenAI-compatible structured
                # output yet return HTTP 500 for both json_schema and
                # json_object. The ideation pipeline still validates/parses
                # JSON deterministically after this call, so retry plain text
                # on the SAME pinned model/provider rather than failing every
                # generation or swapping models.
                return await asyncio.to_thread(
                    self._request, model, prompt, system, max_tokens, temperature, None
                )
            except _ResponseFormatUnsupportedError:
                if response_format is None or response_format["type"] != "json_schema":
                    raise
                # Retry JSON mode on the same pinned model only. This changes
                # the transport format, never the model or provider.
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
            raise ProviderUnavailableError(str(exc)) from exc
        except _CorruptResponseError:
            # Để `complete` quyết định retry; đây là RuntimeError nên phải chặn
            # TRƯỚC nhánh gom RuntimeError bên dưới, nếu không nó bị đổi thành
            # ProviderUnavailableError và vòng retry không bao giờ thấy.
            raise
        except (RuntimeError, urllib_error.URLError, TimeoutError) as exc:
            raise ProviderUnavailableError(f"xKiro LLM ({model}) lỗi: {exc}") from exc

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
                raw = response.read()
        except urllib_error.HTTPError as exc:
            if exc.code == 400 and response_format is not None:
                raise _ResponseFormatUnsupportedError(
                    f"xKiro LLM ({model}) từ chối response_format={response_format['type']}."
                ) from exc
            if exc.code >= 500 and response_format is not None:
                raise _ResponseFormatGatewayError(
                    f"xKiro LLM ({model}) lỗi gateway khi gửi response_format="
                    f"{response_format['type']}."
                ) from exc
            raise RuntimeError(f"xKiro LLM ({model}) trả HTTP {exc.code}.") from exc
        try:
            # Decode NGHIÊM NGẶT: "replace" biến byte hỏng thành U+FFFD rồi đi
            # tiếp như text thường, và chỗ hỏng chỉ lộ ra ở tận cổng encoding
            # sau khi đã tốn cả lượt sinh.
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _CorruptResponseError(
                f"xKiro LLM ({model}) trả byte UTF-8 hỏng: {exc}"
            ) from exc
        if not text.strip():
            # HTTP 200 mà body trống là lỗi truyền, không phải câu trả lời của
            # model — gặp thật trên production ngay sau khi thêm retry cho byte
            # hỏng. Cùng lớp sự cố, cùng cách xử lý: hỏi lại, có trần.
            raise _CorruptResponseError(
                f"xKiro LLM ({model}) trả HTTP 200 với body rỗng."
            )
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            # HTTP 200 nhưng body không phải JSON hợp lệ là lỗi model/gateway.
            # Surface it as a provider error rather than leaking JSONDecodeError
            # out of the batch command.
            snippet = raw.decode("utf-8", "replace")[:300]
            raise RuntimeError(
                f"xKiro LLM ({model}) trả HTTP 200 nhưng body không phải JSON hợp lệ: {snippet!r}"
            ) from exc

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"xKiro LLM ({model}) trả response không có choices.")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError(f"xKiro LLM ({model}) trả content rỗng.")
        if "\ufffd" in content:
            # Kiểm tra ở ĐÂY, không phải trên body thô: JSON mã hoá U+FFFD thành
            # escape "\\ufffd", nên ký tự thật chỉ xuất hiện sau khi parse.
            #
            # Đây là ca UTF-8 HỢP LỆ mang sẵn ký tự thay thế — chữ mất TRƯỚC khi
            # tới HTTP, trong model hoặc gateway, nên strict decode không thấy
            # gì. Đo trên production: 'đi h\ufffd\ufffdp' thay cho 'đi họp',
            # đúng một lời gọi, decode trót lọt.
            raise _CorruptResponseError(
                f"xKiro LLM ({model}) trả content chứa ký tự thay thế U+FFFD."
            )
        return content
