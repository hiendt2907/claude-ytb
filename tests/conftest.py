"""Fixture & helper dùng chung cho test ideation/cổng nạp kịch bản.

Gom phần build script JSON + khối `compliance` (trước đây lặp ở test_compliance,
test_length_gate, test_intro_gate) về một chỗ để DRY.
"""

import json
from pathlib import Path

import pytest

from ytb_pipeline.ideation.generator import CHARS_PER_MIN


def passing_compliance(**overrides) -> dict:
    """Khối compliance PASS hợp lệ; truyền kwargs để override từng field."""
    base = {
        "passed": True,
        "community": "PASS",
        "copyright": "PASS — nhạc/hình tự sinh",
        "accuracy": "PASS",
        "advertiser": "PASS",
        "coppa": "không hướng tới trẻ em",
        "notes": "đã rà toàn bộ",
    }
    base.update(overrides)
    return base


def make_script(sections, *, target_minutes=None, compliance=None, **fields) -> dict:
    """Dựng dict kịch bản hợp lệ. `sections` là list dict segment.

    - `target_minutes=None` -> Short (cổng độ dài 1–2 phút).
    - `compliance=None` -> dùng khối PASS mặc định.
    - kwargs còn lại override title/topic/... ở cấp gốc.
    """
    data = {
        "topic": "t",
        "title": "Tiêu đề mẫu",
        "description": "d",
        "tags": ["a"],
        "compliance": passing_compliance() if compliance is None else compliance,
        "sections": sections,
    }
    if target_minutes is not None:
        data["target_minutes"] = target_minutes
    data.update(fields)
    return data


def chars_for_minutes(minutes: float) -> str:
    """Chuỗi narration ước lượng đúng `minutes` phút theo CHARS_PER_MIN."""
    return "x" * int(CHARS_PER_MIN * minutes)


@pytest.fixture
def write_script(tmp_path):
    """Ghi dict kịch bản ra file tạm, trả về Path để truyền vào load_script."""

    def _write(data: dict, name: str = "script.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _write
