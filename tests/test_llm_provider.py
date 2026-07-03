"""Tests cho LLMProvider — OllamaProvider + ClaudeProvider (Phase 6)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ytb_pipeline.providers.errors import ProviderUnavailableError
from ytb_pipeline.providers.llm.claude_provider import ClaudeProvider
from ytb_pipeline.providers.llm.ollama_provider import OllamaProvider


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------

def test_ollama_available_when_ping_succeeds(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read = lambda: json.dumps({"models": [{"name": "qwen"}]}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(
        "ytb_pipeline.providers.llm.ollama_provider.urllib.request.urlopen",
        lambda url, timeout: mock_resp,
    )
    monkeypatch.setattr("ytb_pipeline.providers.llm.ollama_provider.settings",
                        MagicMock(ollama_url="http://localhost:11434", ollama_model="qwen"))
    p = OllamaProvider()
    assert p.is_available() is True


def test_ollama_unavailable_when_model_missing(monkeypatch):
    class _MockResp:
        status = 200

        def read(self):
            return json.dumps({"models": [{"name": "other"}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(
        "ytb_pipeline.providers.llm.ollama_provider.urllib.request.urlopen",
        lambda url, timeout: _MockResp(),
    )
    monkeypatch.setattr("ytb_pipeline.providers.llm.ollama_provider.settings",
                        MagicMock(ollama_url="http://localhost:11434", ollama_model="qwen"))
    p = OllamaProvider()
    assert p.is_available() is False


def test_ollama_unavailable_when_ping_fails(monkeypatch):
    import urllib.error
    monkeypatch.setattr(
        "ytb_pipeline.providers.llm.ollama_provider.urllib.request.urlopen",
        lambda url, timeout: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    monkeypatch.setattr("ytb_pipeline.providers.llm.ollama_provider.settings",
                        MagicMock(ollama_url="http://localhost:11434", ollama_model="qwen"))
    p = OllamaProvider()
    assert p.is_available() is False


async def test_ollama_complete_raises_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        "ytb_pipeline.providers.llm.ollama_provider.urllib.request.urlopen",
        lambda url, timeout=None, **kw: (_ for _ in ()).throw(OSError("fail")),
    )
    monkeypatch.setattr("ytb_pipeline.providers.llm.ollama_provider.settings",
                        MagicMock(ollama_url="http://localhost:11434", ollama_model="qwen"))
    p = OllamaProvider()
    with pytest.raises(ProviderUnavailableError):
        await p.complete("hello")


async def test_ollama_complete_returns_response(monkeypatch):
    calls = []

    class _MockResp:
        status = 200
        def read(self): return json.dumps({"response": "test output"}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return _MockResp()

    # ping passes, then complete passes
    ping_count = [0]
    def smart_urlopen(req_or_url, timeout=None):
        if isinstance(req_or_url, str):
            ping_count[0] += 1
            ping = _MockResp()
            ping.read = lambda: json.dumps({"models": [{"name": "qwen"}]}).encode()
            return ping
        return _MockResp()

    monkeypatch.setattr(
        "ytb_pipeline.providers.llm.ollama_provider.urllib.request.urlopen",
        smart_urlopen,
    )
    monkeypatch.setattr("ytb_pipeline.providers.llm.ollama_provider.settings",
                        MagicMock(ollama_url="http://localhost:11434", ollama_model="qwen"))
    p = OllamaProvider()
    result = await p.complete("say hello")
    assert result == "test output"


def test_ollama_model_name(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.llm.ollama_provider.settings",
                        MagicMock(ollama_url="http://localhost:11434", ollama_model="llama3"))
    p = OllamaProvider()
    assert p.model_name() == "llama3"


def test_ollama_provider_name():
    assert OllamaProvider.name == "ollama"


# ---------------------------------------------------------------------------
# ClaudeProvider
# ---------------------------------------------------------------------------

def test_claude_available_when_binary_in_path(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.shutil.which",
                        lambda x: "/usr/local/bin/claude")
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.settings",
                        MagicMock(claude_bin="claude"))
    p = ClaudeProvider()
    assert p.is_available() is True


def test_claude_unavailable_when_binary_missing(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.shutil.which",
                        lambda x: None)
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.settings",
                        MagicMock(claude_bin="claude"))
    p = ClaudeProvider()
    assert p.is_available() is False


async def test_claude_complete_raises_when_unavailable(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.shutil.which",
                        lambda x: None)
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.settings",
                        MagicMock(claude_bin="claude"))
    p = ClaudeProvider()
    with pytest.raises(ProviderUnavailableError):
        await p.complete("hello")


async def test_claude_complete_returns_subprocess_stdout(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.shutil.which",
                        lambda x: "/usr/local/bin/claude")
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.settings",
                        MagicMock(claude_bin="claude"))
    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.build_claude_cmd",
                        lambda prompt: ["echo", prompt])

    def fake_invoke(self, cmd):
        return "claude output here"

    monkeypatch.setattr(ClaudeProvider, "_invoke", fake_invoke)

    p = ClaudeProvider()
    result = await p.complete("write a story")
    assert result == "claude output here"


def test_claude_provider_name():
    assert ClaudeProvider.name == "claude"


def test_claude_model_name():
    p = ClaudeProvider()
    assert p.model_name() == "claude-via-cli"
