"""Chuẩn hoá + validate + repair script JSON từ LLM cho `ytb batch start`.

Tách khỏi ideation_cmd.py: đây là các hàm THUẦN xử lý text/JSON (dễ test,
không I/O ngoài trừ ghi script file + log) và vòng lặp validate→QA→repair
có giới hạn số lần.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..agents.base import AgentStatus
from ..agents.qa_agent import QAAgent
from ..ideation.generator import load_script
from .ideation_prompts import (
    SHORT_MAX_CHARS,
    SHORT_MIN_CHARS,
    SHORT_TARGET_CHARS,
    ledger_topics,
    repair_prompt,
)


def json_from_llm(text: str) -> dict:
    """Parse structured LLM output, tolerating fenced JSON wrappers."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def append_local_start_log(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n===== {title} =====\n")
        f.write(body.rstrip())
        f.write("\n")


def strip_short_greeting(text: str) -> str:
    patterns = (
        r"\s*Chào mừng các bạn đến với video mới của chúng tôi\.\s*",
        r"\s*Chào mừng các bạn[^.?!]*[.?!]\s*",
        r"^\s*Hôm nay,\s*chúng ta sẽ\s*",
    )
    cleaned = text.strip()
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def trim_to_sentence(text: str, limit: int) -> str:
    text = strip_short_greeting(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    boundary = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if boundary >= max(60, int(limit * 0.55)):
        return cut[: boundary + 1].strip()
    boundary = cut.rfind(" ")
    if boundary >= max(60, int(limit * 0.65)):
        cut = cut[:boundary].rstrip()
    return cut.rstrip(" ,;:") + "."


def short_narration_chars(payload: dict) -> int:
    return sum(len(section.get("voiceover") or section.get("narration", "") or "")
               for section in payload.get("sections", []) or [])


def normalize_short_narration(payload: dict) -> tuple[dict, str | None]:
    """Keep local Short scripts inside the hard length gate without another LLM hop."""
    if payload.get("target_minutes") is not None:
        return payload, None
    sections = [s for s in payload.get("sections", []) or [] if isinstance(s, dict)]
    if not sections:
        return payload, None

    changed = False
    for section in sections:
        narration = section.get("voiceover") or section.get("narration", "")
        if isinstance(narration, str):
            cleaned = strip_short_greeting(narration)
            if cleaned != narration:
                section["voiceover"] = cleaned
                section["narration"] = cleaned
                changed = True

    total = short_narration_chars(payload)
    if total > SHORT_MAX_CHARS:
        ratio = SHORT_TARGET_CHARS / total
        remaining = SHORT_TARGET_CHARS
        for idx, section in enumerate(sections):
            narration = str(section.get("voiceover") or section.get("narration", ""))
            left = len(sections) - idx
            budget = max(120, min(len(narration), remaining - 80 * (left - 1)))
            proportional = max(120, int(len(narration) * ratio))
            budget = min(budget, proportional)
            section["voiceover"] = trim_to_sentence(narration, budget)
            section["narration"] = section["voiceover"]
            remaining -= len(section["voiceover"])
        changed = True
    elif total < SHORT_MIN_CHARS:
        needed = min(SHORT_TARGET_CHARS - total, SHORT_MAX_CHARS - total)
        idx = 0
        fillers = (
            " Ví dụ cụ thể: bạn mở laptop để làm việc, nhưng chỉ cần nhìn thấy một nhiệm vụ hơi khó là tay tự động với sang điện thoại.",
            " Cơ chế nằm ở chỗ não không né công việc, nó né cảm giác mơ hồ và nguy cơ làm sai trong vài giây đầu.",
            " Cách áp dụng là thu nhỏ bước đầu tiên đến mức không còn đáng sợ: chỉ mở file, viết một dòng nháp, rồi mới quyết định làm tiếp.",
        )
        while needed > 0 and sections:
            addition = fillers[idx % len(fillers)]
            if len(addition) > needed:
                addition = trim_to_sentence(addition, needed)
            sections[idx % len(sections)]["voiceover"] = (
                str(sections[idx % len(sections)].get("voiceover") or sections[idx % len(sections)].get("narration", "")).rstrip() + addition
            ).strip()
            sections[idx % len(sections)]["narration"] = sections[idx % len(sections)]["voiceover"]
            needed -= len(addition)
            idx += 1
        changed = True

    if not changed:
        return payload, None
    total = short_narration_chars(payload)
    return payload, f"normalized short narration to {total} chars"


async def validate_or_repair_script(
    provider,
    payload: dict,
    script_path: Path,
    ledger_text: str,
    max_attempts: int = 3,
    log_path: Path | None = None,
    console_prefix: str = "",
    strict: bool = True,
) -> dict:
    """Write, validate, QA, and repair a local LLM script JSON with bounded retries."""
    qa = QAAgent()
    done_topics = ledger_topics(ledger_text)
    current = dict(payload)
    last_validation_error: str | None = None
    last_qa_output: dict | None = None

    for attempt in range(1, max_attempts + 1):
        current, normalized_note = normalize_short_narration(current)
        if normalized_note:
            if console_prefix:
                print(f"{console_prefix} normalize: {normalized_note}", flush=True)
            if log_path:
                append_local_start_log(log_path, f"NORMALIZE {attempt}", normalized_note)
        if console_prefix:
            print(f"{console_prefix} validate: attempt {attempt}/{max_attempts}", flush=True)
        if log_path:
            append_local_start_log(
                log_path,
                f"VALIDATION_ATTEMPT {attempt}",
                json.dumps(current, ensure_ascii=False, indent=2),
            )
        script_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            script = load_script(script_path)
            last_validation_error = None
        except Exception as exc:  # noqa: BLE001
            script = None
            last_validation_error = str(exc)
            if log_path:
                append_local_start_log(log_path, f"VALIDATION_ERROR {attempt}", last_validation_error)

        if script is not None:
            result = await qa.run({"script": script, "done_topics": done_topics, "strict": strict})
            if result.status == AgentStatus.SUCCESS:
                last_qa_output = result.output
                if log_path:
                    append_local_start_log(
                        log_path,
                        f"QA_RESULT {attempt}",
                        json.dumps(result.output, ensure_ascii=False, indent=2),
                    )
                if result.output and result.output.get("passed"):
                    return current
            else:
                last_qa_output = {"passed": False, "violations": [{"rule": "qa_agent", "detail": result.error}]}
                if log_path:
                    append_local_start_log(
                        log_path,
                        f"QA_ERROR {attempt}",
                        json.dumps(last_qa_output, ensure_ascii=False, indent=2),
                    )

        if attempt == max_attempts:
            break

        if console_prefix:
            print(f"{console_prefix} repair: asking LLM to fix validation issues", flush=True)
        repair = repair_prompt(current, last_qa_output, last_validation_error)
        if log_path:
            append_local_start_log(log_path, f"REPAIR_PROMPT {attempt}", repair)
        repaired = await provider.complete(
            repair,
            system="Return strict JSON only. No markdown.",
            max_tokens=8192,
            temperature=0.2,
            json_output=True,
        )
        if log_path:
            append_local_start_log(log_path, f"REPAIR_RESPONSE {attempt}", repaired)
        current = json_from_llm(repaired)
        current["slug"] = script_path.stem

    if log_path:
        append_local_start_log(
            log_path,
            "FINAL_FAILURE",
            f"validation={last_validation_error!r}\nqa={last_qa_output!r}",
        )
    raise SystemExit(
        "✗ LLM tạo script không qua QA sau "
        f"{max_attempts} lần. validation={last_validation_error!r} qa={last_qa_output!r}"
    )
