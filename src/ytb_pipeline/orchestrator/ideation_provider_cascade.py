"""CascadeScriptProvider — thử lần lượt nhiều LLMProvider cho tới khi một
provider thành công, dừng ở provider đầu tiên khả dụng/không lỗi.

Thay thế `OllamaScriptProvider` (single-fallback, gỡ bỏ cùng Ollama/MLX-LM —
amendment 2026-08-24, PROJECT_VISION.md Amendment Log). Kiến trúc mới: xKiro
(cloud, primary) -> Codex CLI -> Claude CLI, tất cả đều cloud nên
`settings.llm_fallback_enabled` mặc định True (không còn ý nghĩa "cảnh báo
tốn tiền cloud khi local hỏng" như trước).
"""

from __future__ import annotations

from ..config.settings import settings
from ..providers.errors import ProviderUnavailableError


class CascadeScriptProvider:
    """Bọc danh sách `LLMProvider` theo thứ tự ưu tiên; provider đầu tiên
    `is_available()` và không lỗi giữa chừng thắng. Nhận provider đã dựng sẵn
    qua tham số (không tự tra registry) để caller/test tiêm được fake provider
    mà không cần patch import ở đây."""

    def __init__(self, providers: list, *, name: str | None = None):
        if not providers:
            raise ValueError("CascadeScriptProvider cần ít nhất 1 provider.")
        self._providers = providers
        self.name = name or providers[0].name

    def is_available(self) -> bool:
        if not settings.llm_fallback_enabled:
            return self._providers[0].is_available()
        return any(p.is_available() for p in self._providers)

    def model_name(self) -> str:
        for provider in self._candidates():
            if provider.is_available():
                return provider.model_name()
        raise ProviderUnavailableError(
            f"Không provider nào trong cascade '{self.name}' khả dụng."
        )

    def _candidates(self) -> list:
        if settings.llm_fallback_enabled:
            return self._providers
        return self._providers[:1]

    async def complete(self, prompt: str, **kwargs) -> str:
        last_error: Exception | None = None
        tried_any = False
        for provider in self._candidates():
            if not provider.is_available():
                continue
            tried_any = True
            try:
                return await provider.complete(prompt, **kwargs)
            except (ProviderUnavailableError, RuntimeError, OSError) as exc:
                # OSError bao gồm urllib.error.URLError. In lý do thật ra để vận
                # hành viên phân biệt provider nào lỗi — không nuốt lỗi khi
                # cascade flaky.
                print(
                    f"⚠ {provider.name} lỗi giữa chừng ({type(exc).__name__}: {exc}) — "
                    "thử provider kế tiếp trong cascade.",
                    flush=True,
                )
                last_error = exc
                continue
        if not tried_any:
            raise ProviderUnavailableError(
                f"Không provider nào trong cascade '{self.name}' khả dụng."
            )
        raise ProviderUnavailableError(
            f"Mọi provider trong cascade '{self.name}' đều lỗi. Lỗi cuối: {last_error}"
        )
