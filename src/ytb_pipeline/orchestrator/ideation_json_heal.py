"""Lớp heal JSON hỏng cho output LLM local (Ollama/Qwen).

Claude/Codex hiếm khi trả JSON hỏng cú pháp; Qwen local dễ trả unescaped
quote hoặc ký tự lạc bên trong string hơn (xem amendment 2026-07-23 trong
docs/TOOL_UPGRADE_PLAN.md cho phép Ollama sinh kịch bản). `json_from_llm`
trong ideation_script_fix.py gọi `heal_json` làm phương án CUỐI CÙNG, chỉ khi
`json.loads`/`raw_decode` chuẩn đã thất bại — không thay đổi hành vi cho
response đã hợp lệ (Claude/Codex không bị ảnh hưởng).
"""

from __future__ import annotations


def heal_json(raw: str) -> dict:
    """Best-effort repair cho JSON hỏng cú pháp (unescaped quote, ký tự lạc).

    Raise `ValueError` nếu không heal được thành `dict` — caller (`json_from_llm`)
    coi đây như JSON không parse được, giữ nguyên lỗi gốc cho người vận hành.
    """
    import json_repair

    data = json_repair.repair_json(raw, return_objects=True)
    if not isinstance(data, dict):
        raise ValueError("json_repair không trả về object hợp lệ.")
    return data
