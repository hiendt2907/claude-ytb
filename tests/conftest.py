"""Fixture & helper dùng chung cho test ideation/cổng nạp kịch bản.

Gom phần build script JSON + khối `compliance` (trước đây lặp ở test_compliance,
test_length_gate, test_intro_gate) về một chỗ để DRY.
"""

import importlib
import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Pin the format runtime window BEFORE any pipeline module is imported.
#
# The window is operator-configurable by design (`SHORT_VIEWER_MIN_SEC` & co.),
# so retuning the channel from a 60-90s Short to a 30-45s Short turned two dozen
# unrelated tests red without a single code change.  Several modules also freeze
# their character budgets at import time, so patching `settings` inside a fixture
# would leave the test module and the code under test disagreeing.  Setting the
# environment here — conftest is imported before the test modules — makes every
# later import see the same documented defaults.  A test that cares about a
# specific window sets it explicitly and reloads what it needs.
# ---------------------------------------------------------------------------
_WINDOW_ENV = {
    "SHORT_VIEWER_MIN_SEC": "short_viewer_min_sec",
    "SHORT_VIEWER_MAX_SEC": "short_viewer_max_sec",
    "SHORT_MIN_SECTIONS": "short_min_sections",
    "LONG_VIEWER_MIN_SEC": "long_viewer_min_sec",
    "LONG_VIEWER_MAX_SEC": "long_viewer_max_sec",
    "LONG_MIN_SECTIONS": "long_min_sections",
    # Operator escape hatches, same reasoning one step further out. A developer
    # whose `.env` overrides the visual judge or the disposition policy was
    # silently running a different pipeline than the suite describes: once the
    # evaluation-reuse check started resolving the judge target instead of
    # reading the profile, a stray `VISUAL_JUDGE_MODEL` turned four unrelated
    # reuse tests red. A test that cares about an override sets it explicitly.
    "VISUAL_JUDGE_PROVIDER": "visual_judge_provider",
    "VISUAL_JUDGE_MODEL": "visual_judge_model",
    "VISUAL_AUTO_DISPOSITION": "visual_auto_disposition",
    "VISUAL_AUTO_ACCEPT_MINIMUM_SCORE": "visual_auto_accept_minimum_score",
    "VISUAL_AUTO_ACCEPT_WAIVED_FAILURES": "visual_auto_accept_waived_failures",
}


def _pin_runtime_window_env() -> None:
    from ytb_pipeline.config import settings as settings_module

    fields = settings_module.Settings.model_fields
    for env_name, field in _WINDOW_ENV.items():
        os.environ[env_name] = str(fields[field].default)
    importlib.reload(settings_module)


_pin_runtime_window_env()


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


def chars_for_minutes(minutes: float, *, video_type: str | None = None) -> str:
    """Chuỗi narration theo tốc độ của TTS provider đang được cấu hình.

    `video_type` phải khớp loại video mà fixture đang dựng: Long có nhịp đọc
    riêng, nên dựng narration Long bằng rate của Short sẽ sinh thiếu ký tự và
    cổng độ dài chặn oan.
    """
    return "x" * int(chars_per_min_for_provider(video_type=video_type) * minutes)


@pytest.fixture
def write_script(tmp_path):
    """Ghi dict kịch bản ra file tạm, trả về Path để truyền vào load_script."""

    def _write(data: dict, name: str = "script.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _write
