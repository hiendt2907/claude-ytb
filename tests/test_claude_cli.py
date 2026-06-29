"""Test dựng lệnh `claude -p` headless dùng chung (listener.py + batch_cli.py)."""

from __future__ import annotations

from ytb_pipeline import claude_cli
from ytb_pipeline.config.settings import settings


def test_build_claude_cmd_default_bypass_permissions(monkeypatch):
    monkeypatch.setattr(settings, "claude_bin", "claude")
    monkeypatch.setattr(settings, "listener_claude_args", "--dangerously-skip-permissions")

    cmd = claude_cli.build_claude_cmd("xin chào")

    assert cmd == ["claude", "--dangerously-skip-permissions", "-p", "xin chào"]


def test_build_claude_cmd_continue_flag(monkeypatch):
    monkeypatch.setattr(settings, "claude_bin", "claude")
    monkeypatch.setattr(settings, "listener_claude_args", "")

    cmd = claude_cli.build_claude_cmd("tiếp", cont=True)

    assert cmd == ["claude", "--continue", "-p", "tiếp"]
