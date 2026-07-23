"""OllamaScriptProvider — Ollama/Qwen làm provider sinh kịch bản mặc định,
fallback tự động về Claude CLI khi Ollama không sẵn sàng hoặc lỗi giữa chừng.

Amendment 2026-07-23 (docs/TOOL_UPGRADE_PLAN.md): đảo ngược invariant cũ
"Không gọi Ollama cho việc viết kịch bản" sau khi Qwen3.6:27b + lớp heal JSON
(`ideation_json_heal.py`) đạt chất lượng đủ dùng. Fallback về Claude là một
adapter bình thường, không phải nhánh đặc biệt — theo đúng Provider Pattern.
"""

from __future__ import annotations

from ..providers.errors import ProviderUnavailableError


class OllamaScriptProvider:
    """Bọc một `LLMProvider` Ollama đã dựng sẵn — fallback về `claude_fallback`
    khi lỗi. Nhận `ollama_provider` qua tham số (không tự tra registry) để
    caller/test tiêm được fake provider mà không cần patch import ở đây."""

    name = "ollama"

    def __init__(self, ollama_provider, claude_fallback):
        self._ollama = ollama_provider
        self._claude_fallback = claude_fallback

    def is_available(self) -> bool:
        return self._ollama.is_available() or self._claude_fallback.is_available()

    def model_name(self) -> str:
        if self._ollama.is_available():
            return self._ollama.model_name()
        return self._claude_fallback.model_name()

    async def complete(self, prompt: str, **kwargs) -> str:
        if self._ollama.is_available():
            try:
                return await self._ollama.complete(prompt, **kwargs)
            except (ProviderUnavailableError, RuntimeError, OSError) as exc:
                # OSError bao gồm urllib.error.URLError. In lý do thật ra để vận
                # hành viên phân biệt "Ollama down" với lỗi khác đang bị nuốt —
                # không log thì fallback không kiểm chứng được khi Ollama flaky.
                print(
                    f"⚠ Ollama lỗi giữa chừng ({type(exc).__name__}: {exc}) — "
                    "fallback sang Claude CLI.",
                    flush=True,
                )
        return await self._claude_fallback.complete(prompt, **kwargs)
