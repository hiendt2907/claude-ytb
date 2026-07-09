"""QA gate rút gọn — kiểm tra kịch bản trước khi vào production, thuần rule-based.

Port từ claude-ytb/agents/qa_agent.py, thu hẹp cho content.models.Script (Short
only — không có compliance/target_minutes/topic/tags/broll như bản gốc).
"""

from __future__ import annotations

from .ledger import LedgerEntry, is_duplicate
from .models import Script

CHARS_PER_MIN = 1197.0
SHORT_MIN_MINUTES = 0.8
SHORT_MAX_MINUTES = 1.2

_SELF_HELP_MANTRAS = (
    "just believe in yourself",
    "hãy tin vào bản thân",
    "bạn có thể làm được mọi thứ",
    "manifest your dreams",
)
_STAGE_DIRECTION_PATTERNS = ("cú hình tiếp theo:", "beat sau:", "chốt cảnh:", "[", "]")
_WEAK_VISUAL_KEYWORDS = {"", "video", "stock footage", "broll", "background", "abstract"}
_SOURCED_CLAIM_PHRASES = ("studies show", "nghiên cứu cho thấy", "các nhà khoa học", "research shows")
_SOURCE_HINTS = ("http://", "https://", "nguồn:", "source:", "doi:")


def estimate_minutes(script: Script) -> float:
    chars = sum(len(seg.narration) for seg in script.segments)
    return chars / CHARS_PER_MIN


def check_script(script: Script, ledger: list[LedgerEntry] | None = None) -> dict:
    """Trả {"passed": bool, "violations": [...], "warnings": [...]}.

    `violations` chặn production (caller nên gọi Claude sửa lại); `warnings`
    chỉ để cảnh báo, không chặn.
    """
    ledger = ledger or []
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    violations.extend(_check_length(script))
    violations.extend(_check_self_help(script))
    violations.extend(_check_stage_direction_leak(script))
    violations.extend(_check_visual_keywords(script))
    violations.extend(_check_dedup(script, ledger))
    warnings.extend(_check_sourced_claims(script))

    return {"passed": len(violations) == 0, "violations": violations, "warnings": warnings}


def _check_length(script: Script) -> list[dict[str, str]]:
    if not script.segments:
        return [{"rule": "length", "detail": "Script không có segment narration."}]
    est = estimate_minutes(script)
    if est <= SHORT_MIN_MINUTES:
        return [{"rule": "length", "detail": f"Short quá ngắn: ước lượng {est:.2f} phút."}]
    if est >= SHORT_MAX_MINUTES:
        return [{"rule": "length", "detail": f"Short quá dài: ước lượng {est:.2f} phút."}]
    return []


def _check_self_help(script: Script) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for segment in script.segments:
        text = segment.narration.lower()
        for mantra in _SELF_HELP_MANTRAS:
            if mantra in text:
                violations.append({
                    "rule": "niche_self_help",
                    "detail": f"Phát hiện mantra self-help chung chung: '{mantra}'.",
                })
    return violations


def _check_stage_direction_leak(script: Script) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for index, segment in enumerate(script.segments, start=1):
        text = segment.narration.lower()
        leaked = [p for p in _STAGE_DIRECTION_PATTERNS if p in text]
        if leaked:
            violations.append({
                "rule": "stage_direction",
                "detail": f"Đoạn {index} có chỉ dẫn hình ảnh lẫn vào lời đọc: {', '.join(leaked)}.",
            })
    return violations


def _check_visual_keywords(script: Script) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for index, segment in enumerate(script.segments, start=1):
        keywords = [k.strip().lower() for k in segment.visual_keywords]
        if not keywords or all(k in _WEAK_VISUAL_KEYWORDS or len(k.split()) < 2 for k in keywords):
            violations.append({
                "rule": "visual_keywords",
                "detail": f"Đoạn {index} có visual_keywords yếu/thiếu.",
            })
    return violations


def _check_dedup(script: Script, ledger: list[LedgerEntry]) -> list[dict[str, str]]:
    if is_duplicate(script.title, ledger):
        return [{
            "rule": "ledger_dedup",
            "detail": f"Tiêu đề '{script.title}' đã có trong ledger (đã tạo trước đó).",
        }]
    return []


def _check_sourced_claims(script: Script) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for segment in script.segments:
        text_lower = segment.narration.lower()
        for phrase in _SOURCED_CLAIM_PHRASES:
            if phrase in text_lower and not any(hint in text_lower for hint in _SOURCE_HINTS):
                warnings.append({
                    "rule": "sourced_claims",
                    "detail": f"Cụm '{phrase}' không kèm nguồn rõ ràng.",
                })
    return warnings
