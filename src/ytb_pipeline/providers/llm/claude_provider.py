"""ClaudeProvider — bọc `claude -p` subprocess (claude_cli.py) thành LLMProvider.

Giữ hành vi cũ (cloud, headless qua CLI) nhưng qua interface chung LLMProvider
để pipeline có thể đổi sang OllamaProvider (local) bằng `settings.llm_provider`
mà không sửa logic agent.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess

from ...claude_cli import build_claude_cmd
from ...config.settings import settings
from ..errors import ProviderUnavailableError

_SUBPROCESS_TIMEOUT_SEC = 120


class ClaudeProvider:
    """LLM cloud qua `claude -p` headless subprocess."""

    name = "claude"

    def is_available(self) -> bool:
        return shutil.which(settings.claude_bin) is not None

    def model_name(self) -> str:
        return "claude-via-cli"

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        json_output: bool = False,
    ) -> str:
        if not self.is_available():
            raise ProviderUnavailableError(
                f"`{settings.claude_bin}` không có trong PATH — "
                "ClaudeProvider không khả dụng."
            )

        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        cmd = build_claude_cmd(full_prompt)
        return await asyncio.to_thread(self._invoke, cmd)

    def _invoke(self, cmd: list[str]) -> str:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=_SUBPROCESS_TIMEOUT_SEC, check=True,
        )
        return result.stdout
