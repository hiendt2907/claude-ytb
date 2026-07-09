"""Sinh kịch bản bằng Claude (`claude -p` headless) — output JSON có cấu trúc.

Không parse free text bằng regex ad-hoc: Claude được yêu cầu trả JSON thuần,
ta chỉ bóc fence markdown (```...```) nếu lỡ có, rồi json.loads thẳng.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import load_content_settings
from .models import Script, ScriptSegment

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "script_gen.md"
DEFAULT_NUM_SEGMENTS = 6
DEFAULT_TIMEOUT_SEC = 180


def _build_claude_cmd(prompt: str) -> list[str]:
    settings = load_content_settings()
    return [
        settings.claude_bin,
        "--model",
        settings.claude_model,
        "--fallback-model",
        settings.claude_fallback_model,
        "-p",
        prompt,
    ]


def _build_prompt(topic: str, num_segments: int) -> str:
    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(topic=topic, num_segments=num_segments)


def _strip_markdown_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_script_json(raw: str) -> Script:
    data = json.loads(_strip_markdown_fence(raw))
    segments = tuple(
        ScriptSegment(
            narration=segment["narration"],
            visual_keywords=tuple(segment["visual_keywords"]),
        )
        for segment in data["segments"]
    )
    if not segments:
        raise ValueError("Script JSON không có segment nào")
    return Script(title=data["title"], description=data.get("description", ""), segments=segments)


def generate_script(
    topic: str,
    num_segments: int = DEFAULT_NUM_SEGMENTS,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> Script:
    """Gọi Claude sinh kịch bản cho `topic`. Ném lỗi rõ ràng nếu claude -p thất bại."""
    prompt = _build_prompt(topic, num_segments)
    cmd = _build_claude_cmd(prompt)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    if result.returncode != 0:
        raise RuntimeError(f"claude -p thất bại (exit {result.returncode}): {result.stderr.strip()}")
    return parse_script_json(result.stdout)
