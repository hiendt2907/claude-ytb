"""OllamaScriptProvider — Ollama/Qwen làm default sinh kịch bản, fallback
Claude khi không sẵn sàng/lỗi giữa chừng (amendment 2026-07-23, xem
docs/TOOL_UPGRADE_PLAN.md)."""

from __future__ import annotations

import pytest

from ytb_pipeline.orchestrator.ideation_local_provider import OllamaScriptProvider
from ytb_pipeline.providers.errors import ProviderUnavailableError


class _FakeOllama:
    name = "ollama"

    def __init__(self, *, available: bool, raises: Exception | None = None, response: str = "ok"):
        self._available = available
        self._raises = raises
        self._response = response
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def model_name(self) -> str:
        return "qwen3.6:27b"

    async def complete(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeClaude:
    name = "claude"

    def __init__(self, *, available: bool = True, response: str = "claude-output"):
        self._available = available
        self._response = response
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def model_name(self) -> str:
        return "claude-via-cli"

    async def complete(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        return self._response


def _make_provider(monkeypatch, ollama, claude):
    return OllamaScriptProvider(ollama, claude_fallback=claude)


async def test_uses_ollama_when_available(monkeypatch):
    ollama = _FakeOllama(available=True, response="qwen-script-json")
    claude = _FakeClaude()

    provider = _make_provider(monkeypatch, ollama, claude)
    result = await provider.complete("prompt")

    assert result == "qwen-script-json"
    assert ollama.calls == 1
    assert claude.calls == 0


async def test_falls_back_to_claude_when_ollama_unavailable(monkeypatch):
    ollama = _FakeOllama(available=False)
    claude = _FakeClaude(response="claude-script-json")

    provider = _make_provider(monkeypatch, ollama, claude)
    result = await provider.complete("prompt")

    assert result == "claude-script-json"
    assert ollama.calls == 0
    assert claude.calls == 1


async def test_falls_back_to_claude_when_ollama_errors_mid_call(monkeypatch):
    ollama = _FakeOllama(available=True, raises=ProviderUnavailableError("connection dropped"))
    claude = _FakeClaude(response="claude-script-json")

    provider = _make_provider(monkeypatch, ollama, claude)
    result = await provider.complete("prompt")

    assert result == "claude-script-json"
    assert ollama.calls == 1
    assert claude.calls == 1


async def test_falls_back_to_claude_on_network_oserror(monkeypatch):
    ollama = _FakeOllama(available=True, raises=OSError("connection refused"))
    claude = _FakeClaude(response="claude-script-json")

    provider = _make_provider(monkeypatch, ollama, claude)
    result = await provider.complete("prompt")

    assert result == "claude-script-json"


def test_is_available_true_if_either_provider_ready(monkeypatch):
    ollama = _FakeOllama(available=False)
    claude = _FakeClaude(available=True)

    provider = _make_provider(monkeypatch, ollama, claude)

    assert provider.is_available() is True


def test_is_available_false_if_neither_ready(monkeypatch):
    ollama = _FakeOllama(available=False)
    claude = _FakeClaude(available=False)

    provider = _make_provider(monkeypatch, ollama, claude)

    assert provider.is_available() is False


def test_model_name_reports_ollama_when_available(monkeypatch):
    ollama = _FakeOllama(available=True)
    claude = _FakeClaude()

    provider = _make_provider(monkeypatch, ollama, claude)

    assert provider.model_name() == "qwen3.6:27b"


def test_model_name_reports_claude_when_ollama_unavailable(monkeypatch):
    ollama = _FakeOllama(available=False)
    claude = _FakeClaude()

    provider = _make_provider(monkeypatch, ollama, claude)

    assert provider.model_name() == "claude-via-cli"
