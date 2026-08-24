"""Fixture & helper dùng chung cho test ideation/cổng nạp kịch bản.

Gom phần build script JSON + khối `compliance` (trước đây lặp ở test_compliance,
test_length_gate, test_intro_gate) về một chỗ để DRY.
"""

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_batch_state(tmp_path, monkeypatch):
    """Unit/E2E tests must never mutate operational batch state."""
    from ytb_pipeline.orchestrator import batch_cli

    ledger_path = tmp_path / "ledger.md"
    auto_state_path = tmp_path / "auto_state.json"
    monkeypatch.setattr(batch_cli, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr(batch_cli, "WORKER_STATE_PATH", tmp_path / "batch_workers.json")
    monkeypatch.setattr(batch_cli, "AUTO_STATE_PATH", auto_state_path)
    ledger_path.write_text("| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n", encoding="utf-8")
    auto_state_path.write_text(
        '{"shorts_funnel_batch_test": {"long_videos": [], "short_videos": []}}', encoding="utf-8"
    )

from ytb_pipeline.ideation.generator import chars_per_min_for_provider


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

    - `target_minutes=None` -> Short (cổng độ dài 1–1.5 phút).
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
    """Chuỗi narration theo tốc độ của TTS provider đang được cấu hình."""
    return "x" * int(chars_per_min_for_provider() * minutes)


@pytest.fixture
def write_script(tmp_path):
    """Ghi dict kịch bản ra file tạm, trả về Path để truyền vào load_script."""

    def _write(data: dict, name: str = "script.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _write
