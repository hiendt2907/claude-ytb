"""Dựng lệnh gọi `claude -p` headless — dùng chung cho listener.py và batch_cli.py."""

from __future__ import annotations

import shlex

from .config.settings import settings


def build_claude_cmd(prompt: str, *, cont: bool = False, model: str | None = None) -> list[str]:
    """`claude [extra-args] [--continue] -p "<prompt>"`."""
    cmd = [settings.claude_bin]
    extra = settings.listener_claude_args.strip()
    if extra:
        parts = shlex.split(extra)
        if model:
            cleaned: list[str] = []
            skip = False
            for index, part in enumerate(parts):
                if skip:
                    skip = False
                    continue
                if part == "--model":
                    skip = True
                    continue
                if part.startswith("--model="):
                    continue
                cleaned.append(part)
            parts = cleaned
        cmd += parts
    if model:
        cmd += ["--model", model]
    if cont:
        cmd.append("--continue")
    cmd += ["-p", prompt]
    return cmd
