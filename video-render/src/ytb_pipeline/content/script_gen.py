"""Sinh kịch bản bằng Claude (`claude -p` headless) — output JSON có cấu trúc.

Không parse free text bằng regex ad-hoc: Claude được yêu cầu trả JSON thuần,
ta chỉ bóc fence markdown (```...```) nếu lỡ có, rồi json.loads thẳng.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import research
from .config import load_content_settings
from .ledger import LedgerEntry, filter_new_topics
from .models import Script, ScriptSegment

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "script_gen.md"
PROMPT_AUTO_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "script_gen_auto.md"
PROMPT_REPAIR_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "script_repair.md"
DEFAULT_NUM_SEGMENTS = 6
DEFAULT_TIMEOUT_SEC = 180
DEFAULT_TOPIC_CANDIDATES = 8


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
    return _run_claude_for_script(prompt, timeout_sec)


def generate_script_auto(
    ledger: list[LedgerEntry],
    *,
    region: str = "VN",
    num_candidates: int = DEFAULT_TOPIC_CANDIDATES,
    num_segments: int = DEFAULT_NUM_SEGMENTS,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> Script:
    """Tự tìm chủ đề trending (YouTube mostPopular + autocomplete), loại chủ đề
    đã có trong `ledger`, rồi để Claude chọn 1 + viết kịch bản trong 1 lần gọi.

    Ném RuntimeError nếu mọi chủ đề trending đều đã có trong ledger.
    """
    data = research.research_trending(region=region, max_results=num_candidates)
    topics = [item["topic"] for item in data["research"]]
    candidates = filter_new_topics(topics, ledger)
    if not candidates:
        raise RuntimeError(
            "Tất cả chủ đề trending hiện tại đều đã có trong ledger — thử lại "
            "sau hoặc tăng num_candidates."
        )

    template = PROMPT_AUTO_TEMPLATE_PATH.read_text(encoding="utf-8")
    prompt = template.format(
        candidates="\n".join(f"- {t}" for t in candidates),
        seo_keywords=", ".join(data["seo_pool"]["keywords"][:20]),
        num_segments=num_segments,
    )
    return _run_claude_for_script(prompt, timeout_sec)


def repair_script(
    script: Script,
    violations: list[dict[str, str]],
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> Script:
    """Yêu cầu Claude sửa lại đúng các lỗi QA liệt kê, giữ nguyên chủ đề/câu chuyện."""
    script_json = json.dumps(script_to_dict(script), ensure_ascii=False, indent=2)
    violations_text = "\n".join(f"- [{v['rule']}] {v['detail']}" for v in violations)

    template = PROMPT_REPAIR_TEMPLATE_PATH.read_text(encoding="utf-8")
    prompt = template.format(script_json=script_json, violations=violations_text)
    return _run_claude_for_script(prompt, timeout_sec)


def _run_claude_for_script(prompt: str, timeout_sec: int) -> Script:
    cmd = _build_claude_cmd(prompt)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    if result.returncode != 0:
        raise RuntimeError(f"claude -p thất bại (exit {result.returncode}): {result.stderr.strip()}")
    return parse_script_json(result.stdout)


def script_to_dict(script: Script) -> dict:
    return {
        "title": script.title,
        "description": script.description,
        "segments": [
            {"narration": s.narration, "visual_keywords": list(s.visual_keywords)}
            for s in script.segments
        ],
    }
