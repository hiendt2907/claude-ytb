"""Đăng ký các LLMProvider vào llm_registry khi module này được import."""

from ..registry import llm_registry
from .claude_provider import ClaudeProvider
from .xkiro_provider import XkiroLLMProvider

llm_registry.register("claude", ClaudeProvider)
llm_registry.register("xkiro", XkiroLLMProvider)

__all__ = ["ClaudeProvider", "XkiroLLMProvider"]
