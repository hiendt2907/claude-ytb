"""CascadeScriptProvider — xKiro (primary) -> Codex CLI -> Claude CLI khi lỗi.

Thay thế test_ideation_local_provider.py (OllamaScriptProvider, gỡ cùng
Ollama/MLX-LM — amendment 2026-08-24, PROJECT_VISION.md Amendment Log)."""

from __future__ import annotations

import pytest

from ytb_pipeline.orchestrator.ideation_provider_cascade import CascadeScriptProvider
from ytb_pipeline.providers.errors import ProviderUnavailableError


class _FakeProvider:
    def __init__(self, name: str, *, available: bool, raises: Exception | None = None, response: str = "ok"):
        self.name = name
        self._available = available
        self._raises = raises
        self._response = response
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def model_name(self) -> str:
        return f"{self.name}-model"

    async def complete(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._response


def _make_provider(monkeypatch, providers, *, fallback_enabled: bool = True):
    from ytb_pipeline.config.settings import settings

    monkeypatch.setattr(settings, "llm_fallback_enabled", fallback_enabled, raising=False)
    return CascadeScriptProvider(providers, name="xkiro")


async def test_uses_primary_when_available(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=True, response="xkiro-script-json")
    codex = _FakeProvider("codex", available=True)
    claude = _FakeProvider("claude", available=True)

    provider = _make_provider(monkeypatch, [xkiro, codex, claude])
    result = await provider.complete("prompt")

    assert result == "xkiro-script-json"
    assert xkiro.calls == 1
    assert codex.calls == 0
    assert claude.calls == 0


async def test_falls_back_to_codex_then_claude_on_error(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=True, raises=ProviderUnavailableError("mọi model lỗi"))
    codex = _FakeProvider("codex", available=True, raises=RuntimeError("codex lỗi"))
    claude = _FakeProvider("claude", available=True, response="claude-script-json")

    provider = _make_provider(monkeypatch, [xkiro, codex, claude])
    result = await provider.complete("prompt")

    assert result == "claude-script-json"
    assert xkiro.calls == 1
    assert codex.calls == 1
    assert claude.calls == 1


async def test_skips_unavailable_provider_in_chain(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=False)
    codex = _FakeProvider("codex", available=True, response="codex-script-json")
    claude = _FakeProvider("claude", available=True)

    provider = _make_provider(monkeypatch, [xkiro, codex, claude])
    result = await provider.complete("prompt")

    assert result == "codex-script-json"
    assert xkiro.calls == 0
    assert codex.calls == 1
    assert claude.calls == 0


async def test_raises_when_every_provider_fails(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=True, raises=RuntimeError("a"))
    codex = _FakeProvider("codex", available=True, raises=RuntimeError("b"))
    claude = _FakeProvider("claude", available=True, raises=RuntimeError("c"))

    provider = _make_provider(monkeypatch, [xkiro, codex, claude])
    with pytest.raises(ProviderUnavailableError):
        await provider.complete("prompt")


async def test_does_not_cascade_when_fallback_disabled(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=True, raises=RuntimeError("xkiro lỗi"))
    codex = _FakeProvider("codex", available=True, response="codex-script-json")

    provider = _make_provider(monkeypatch, [xkiro, codex], fallback_enabled=False)
    with pytest.raises(ProviderUnavailableError):
        await provider.complete("prompt")

    assert xkiro.calls == 1
    assert codex.calls == 0


def test_is_available_true_if_any_provider_ready(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=False)
    claude = _FakeProvider("claude", available=True)

    provider = _make_provider(monkeypatch, [xkiro, claude])

    assert provider.is_available() is True


def test_is_available_false_if_none_ready(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=False)
    claude = _FakeProvider("claude", available=False)

    provider = _make_provider(monkeypatch, [xkiro, claude])

    assert provider.is_available() is False


def test_model_name_reports_first_available_provider(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=False)
    codex = _FakeProvider("codex", available=True)

    provider = _make_provider(monkeypatch, [xkiro, codex])

    assert provider.model_name() == "codex-model"


def test_model_name_raises_when_none_available(monkeypatch):
    xkiro = _FakeProvider("xkiro", available=False)

    provider = _make_provider(monkeypatch, [xkiro])

    with pytest.raises(ProviderUnavailableError):
        provider.model_name()


def test_configured_script_provider_wires_only_xkiro():
    from ytb_pipeline.orchestrator import ideation_cmd
    from ytb_pipeline.providers.llm.xkiro_provider import XkiroLLMProvider

    provider = ideation_cmd._configured_script_provider("xkiro")

    assert isinstance(provider, XkiroLLMProvider)
    assert provider.name == "xkiro"
