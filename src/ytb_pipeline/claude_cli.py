"""Dựng lệnh gọi `claude -p` headless — dùng chung cho listener.py và batch_cli.py."""

from __future__ import annotations

import shlex

from .config.settings import settings


def build_claude_cmd(prompt: str, *, cont: bool = False) -> list[str]:
    """`claude [extra-args] [--continue] -p "<prompt>"`."""
    cmd = [settings.claude_bin]
    extra = settings.listener_claude_args.strip()
    if extra:
        cmd += shlex.split(extra)
    if cont:
        cmd.append("--continue")
    cmd += ["-p", prompt]
    return cmd
