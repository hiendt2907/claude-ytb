"""Đăng ký các LLMProvider vào llm_registry khi module này được import."""

from ..registry import llm_registry
from .claude_provider import ClaudeProvider
from .ollama_provider import OllamaProvider

llm_registry.register("claude", ClaudeProvider)
llm_registry.register("ollama", OllamaProvider)

__all__ = ["ClaudeProvider", "OllamaProvider"]
