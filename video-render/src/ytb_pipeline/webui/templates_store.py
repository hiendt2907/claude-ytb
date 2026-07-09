"""Lưu/tải template cấu hình render (tỉ lệ khung hình, fit mode, duration mode,
chiến lược chọn clip) — đặt tên, dùng lại cho nhiều sản phẩm khác nhau.

Lưu global tại ~/.video_render/templates/<name>.json (không gắn với 1 sản
phẩm/thư mục cụ thể nào), theo yêu cầu người dùng.
"""

from __future__ import annotations

import json
from pathlib import Path

_TEMPLATE_FIELDS = ("aspect_ratio", "fit_mode", "duration_mode", "mode", "edit_profile_name")


def templates_dir() -> Path:
    path = Path.home() / ".video_render" / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_name(name: str) -> str:
    name = name.strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError(f"Tên template không hợp lệ: {name!r}")
    return name


def save_template(name: str, config: dict) -> Path:
    name = _validate_name(name)
    data = {field: config[field] for field in _TEMPLATE_FIELDS if field in config}
    path = templates_dir() / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_template(name: str) -> dict:
    name = _validate_name(name)
    path = templates_dir() / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy template: {name!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_templates() -> list[str]:
    return sorted(p.stem for p in templates_dir().glob("*.json"))
