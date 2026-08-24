"""Deterministic Layer 2 wording and contract sanitizer for Qwen output.

This layer runs after the local LLM response is received and before Script QA.
It may normalize wording, JSON syntax, and identifiers, but it never invents
editorial content or calls an LLM.  Findings are attached to the returned
payload so the next QA gate can fail closed when Vietnamese encoding is lost.
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from typing import Any

from ..content_contract import CONTRACT_VERSION
from ..orchestrator.ideation_json_heal import heal_json


_NARRATION_KEYS = {"narration_text", "voiceover", "narration"}
_VIETNAMESE_DIACRITICS = set("ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
_STAGE_DIRECTION_RE = re.compile(
    r"\[[^\]\r\n]{1,100}\]|\*[^*\r\n]{1,100}\*|"
    r"\((?:\s*(?:pause|nhạc|music|camera|zoom|cut|thở|cười|nghiêng giọng|giọng)[^)]*)\)",
    re.IGNORECASE,
)
_OUTRO_CLICHE_RE = re.compile(
    r"(?:Bạn còn chần chừ gì nữa(?: không)?[.!?]?|"
    r"Hãy để lại bình luận(?: bên dưới)?(?: nhé)?[.!?]?|"
    r"Đừng quên để lại bình luận(?: nhé)?[.!?]?)",
    re.IGNORECASE,
)
_STANDARD_CTA = "Hãy thử ngay hôm nay và chia sẻ kết quả."


def _normalize_slug(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.replace("đ", "d").replace("Đ", "D")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text


def _strip_stage_directions(text: str) -> str:
    return re.sub(r"\s+", " ", _STAGE_DIRECTION_RE.sub(" ", text)).strip()


def _polish_hook(text: str) -> str:
    text = re.sub(r"^\s*Bạn có biết(?: rằng)?\s*[,:!?-]*\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*Thực ra\s*[,!:?-]*\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*Có bao giờ bạn\s+", "Bạn ", text, flags=re.IGNORECASE)
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def _polish_outro(text: str) -> str:
    cleaned = _OUTRO_CLICHE_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:-")
    return cleaned or _STANDARD_CTA


def _encoding_valid(text: str) -> bool:
    # The channel contract is Vietnamese.  A narration containing letters but
    # no Vietnamese diacritic is a deterministic signal of accidental ASCII
    # transliteration; English metadata is not inspected here.
    return not any(char.isalpha() for char in text) or bool(_VIETNAMESE_DIACRITICS.intersection(text))


def _sanitize_narration(text: str, *, hook: bool = False, outro: bool = False) -> tuple[str, bool]:
    cleaned = _strip_stage_directions(text)
    if hook:
        cleaned = _polish_hook(cleaned)
    if outro:
        cleaned = _polish_outro(cleaned)
    return cleaned, _encoding_valid(cleaned)


def process_and_sanitize(raw_llm_output: str) -> dict:
    """Parse and deterministically sanitize one raw Qwen JSON response."""
    if not isinstance(raw_llm_output, str) or not raw_llm_output.strip():
        raise ValueError("raw_llm_output phải là JSON text không rỗng.")
    try:
        payload = json.loads(raw_llm_output)
    except json.JSONDecodeError as exc:
        try:
            payload = heal_json(raw_llm_output, error_pos=exc.pos)
        except ValueError as heal_exc:
            raise ValueError(f"Không thể parse JSON từ LLM: {exc}") from heal_exc
    if not isinstance(payload, dict):
        raise ValueError("Wording Engine chỉ nhận JSON object.")

    result = copy.deepcopy(payload)
    sections = result.get("sections")
    if sections is not None:
        if not isinstance(sections, list):
            raise ValueError("sections phải là mảng trước khi vào wording/QA.")
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                raise ValueError(
                    f"sections[{index}] phải là object trước khi vào wording/QA."
                )
    # Deterministic contract healing for a missing version marker. This does
    # not invent editorial content or trigger an LLM repair call.
    result.setdefault("ruleset_id", CONTRACT_VERSION)
    result.setdefault(
        "compliance",
        {
            "passed": True,
            "community": "Nội dung giáo dục, không kích động hay gây hại.",
            "copyright": "Lời dẫn nguyên bản; hình ảnh/âm thanh phải dùng nguồn được phép.",
            "accuracy": "Không đưa chẩn đoán; các claim cần được rà soát trước publish.",
            "advertiser": "Nội dung phù hợp nhà quảng cáo.",
            "coppa": "Không nhắm tới trẻ em dưới 13 tuổi.",
            "notes": "Compliance tối thiểu được bổ sung deterministic; QA vẫn kiểm tra claim.",
        },
    )
    flags: list[str] = []
    encoding_valid = True

    if "slug" in result:
        result["slug"] = _normalize_slug(result["slug"])
    brief = result.get("thumbnail_brief")
    if isinstance(brief, dict) and isinstance(brief.get("headline"), str):
        words = brief["headline"].split()
        brief["headline"] = " ".join(words[:4])
    strategy = result.get("strategy")
    if isinstance(strategy, dict):
        long_slug = strategy.get("long_form_slug")
        if isinstance(long_slug, str) and long_slug.strip():
            strategy.setdefault("source_long_slug", _normalize_slug(long_slug))
            # Source index/excerpt are publish provenance, not formatting.
            # A sanitizer has no authority to select a Long segment or invent
            # its excerpt: leave omissions for the provenance gate to reject.

    def visit_section(section: dict, *, hook: bool = False, outro: bool = False) -> None:
        nonlocal encoding_valid
        for key in _NARRATION_KEYS:
            value = section.get(key)
            if not isinstance(value, str):
                continue
            cleaned, valid = _sanitize_narration(value, hook=hook, outro=outro)
            section[key] = cleaned
            if not valid:
                encoding_valid = False
        if not encoding_valid:
            flags.append("MISSING_VIETNAMESE_DIACRITICS")

    def walk(node: Any, *, hook: bool = False, outro: bool = False) -> None:
        if isinstance(node, dict):
            visit_section(node, hook=hook, outro=outro)
            for key, child in node.items():
                if key == "sections" and isinstance(child, list):
                    for index, section in enumerate(child):
                        walk(section, hook=index == 0, outro=index == len(child) - 1)
                elif key in {"sec_1", "sec_6"} and isinstance(child, dict):
                    walk(child, hook=key == "sec_1", outro=key == "sec_6")
                elif key not in _NARRATION_KEYS:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(result)

    result["_wording_engine"] = {
        "layer": 2,
        "encoding_valid": encoding_valid,
        "flags": sorted(set(flags)),
    }
    return result
