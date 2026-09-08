"""Lớp heal JSON hỏng cho output LLM.

Claude/Codex hiếm khi trả JSON hỏng cú pháp; một số model free qua xKiro dễ
trả unescaped quote hoặc ký tự lạc bên trong string hơn (amendment 2026-07-23
trong docs/TOOL_UPGRADE_PLAN.md, mở rộng 2026-08-24 cho xKiro). `json_from_llm`
trong ideation_script_fix.py gọi `heal_json` làm phương án CUỐI CÙNG, chỉ khi
`json.loads`/`raw_decode` chuẩn đã thất bại — không thay đổi hành vi cho
response đã hợp lệ (Claude/Codex không bị ảnh hưởng).
"""

from __future__ import annotations

import re


def _is_unescaped_quote_inside_complete_json_container(raw: str, error_pos: int) -> bool:
    """Allow repair only for a quote that prematurely ends a JSON string.

    This deliberately rejects missing delimiters/braces and an extra quote
    between JSON values.  `json_repair` is useful for one local escaping typo,
    but is unsafe as a general structural parser for a publish pipeline.
    """
    if not (0 <= error_pos < len(raw)):
        return False
    # Python's decoder reports the character *after* a premature quote for
    # ``Expecting ',' delimiter``.  Accept that one-position form only.
    quote_pos = error_pos if raw[error_pos] == '"' else error_pos - 1
    if quote_pos < 0 or raw[quote_pos] != '"':
        return False
    if raw.count("{") != raw.count("}") or raw.count("[") != raw.count("]"):
        return False
    # `,"{"key` is an extra quote between values, not a quote inside text.
    # The recorded xKiro failure has exactly this shape.
    if re.search(r',\s*"\s*\{\s*"', raw[max(0, quote_pos - 4):quote_pos + 4]):
        return False
    in_string = False
    escaped = False
    for char in raw[:quote_pos]:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
    return in_string


def heal_json(raw: str, *, error_pos: int | None = None) -> dict:
    """Repair only one unescaped quote inside an otherwise complete JSON string.

    Raise `ValueError` nếu không heal được thành `dict` — caller (`json_from_llm`)
    coi đây như JSON không parse được, giữ nguyên lỗi gốc cho người vận hành.
    """
    import json
    import json_repair

    if error_pos is None:
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            error_pos = exc.pos
        else:
            raise ValueError("heal_json chỉ nhận JSON đang hỏng.")
    if not _is_unescaped_quote_inside_complete_json_container(raw, error_pos):
        raise ValueError("JSON lỗi cấu trúc; không dùng json_repair.")

    data = json_repair.repair_json(raw, return_objects=True)
    if not isinstance(data, dict):
        raise ValueError("json_repair không trả về object hợp lệ.")
    return data


def strip_code_fence(text: str) -> str:
    """Nội dung bên trong rào markdown ```json, nếu có.

    `json_from_llm` biết bỏ rào từ lâu, nhưng `process_and_sanitize` — chạy
    TRƯỚC nó trên mọi candidate mới — thì parse thẳng text thô. Model nào chỉ
    mắc mỗi lỗi bọc rào cũng bị vứt cả phản hồi và trả tiền sinh lại, dù JSON
    bên trong hoàn toàn hợp lệ. Một hàm dùng chung để hai lớp không lệch nhau
    lần nữa.
    """
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return raw
