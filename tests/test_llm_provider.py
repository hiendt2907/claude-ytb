"""Tests cho LLMProvider — ClaudeProvider.

Ollama/MLX-LM bị gỡ khỏi codebase (amendment 2026-08-24, PROJECT_VISION.md
Amendment Log): xKiro là LLM provider chính, xem test_xkiro_llm_provider.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ytb_pipeline.providers.errors import ProviderUnavailableError
from ytb_pipeline.providers.llm.claude_provider import ClaudeProvider


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


def test_claude_invoke_allows_editorial_repair_budget(monkeypatch):
    """Large JSON script repairs must not die at the former 120-second limit."""
    seen: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return MagicMock(stdout="{}")

    monkeypatch.setattr("ytb_pipeline.providers.llm.claude_provider.subprocess.run", fake_run)

    assert ClaudeProvider()._invoke(["claude", "-p", "large editorial repair"]) == "{}"
    assert seen["timeout"] >= 300
