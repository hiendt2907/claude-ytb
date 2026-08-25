"""Regression: Short prompt/normalizer budgets must follow the active window.

Both defects here shipped as constants sized for the 60-90s Short window and
survived the move to 30-45s: the trim target (`PLANNING_CHARS_PER_MIN * 1.25`)
rose above the cap it was meant to enforce, so `normalize_short_narration`
computed a growth ratio, changed nothing, and still reported success.
"""

from __future__ import annotations

import importlib

import pytest

from ytb_pipeline.config.settings import settings


def _reload_prompts(monkeypatch, *, min_sec: float, max_sec: float, sections: int):
    monkeypatch.setattr(settings, "short_viewer_min_sec", min_sec, raising=False)
    monkeypatch.setattr(settings, "short_viewer_max_sec", max_sec, raising=False)
    monkeypatch.setattr(settings, "short_min_sections", sections, raising=False)
    module = importlib.import_module("ytb_pipeline.orchestrator.ideation_prompts")
    return importlib.reload(module)


@pytest.mark.parametrize(
    ("min_sec", "max_sec", "sections"),
    [(30.0, 45.0, 4), (60.0, 90.0, 6), (45.0, 60.0, 5)],
)
def test_trim_target_never_exceeds_the_cap_it_enforces(monkeypatch, min_sec, max_sec, sections):
    prompts = _reload_prompts(monkeypatch, min_sec=min_sec, max_sec=max_sec, sections=sections)
    assert prompts.SHORT_MIN_CHARS <= prompts.SHORT_TARGET_CHARS <= prompts.SHORT_MAX_CHARS


@pytest.mark.parametrize(
    ("min_sec", "max_sec", "sections"),
    [(30.0, 45.0, 4), (60.0, 90.0, 6)],
)
def test_prompt_section_budgets_fit_the_total_budget(monkeypatch, min_sec, max_sec, sections):
    prompts = _reload_prompts(monkeypatch, min_sec=min_sec, max_sec=max_sec, sections=sections)
    prescribed = (
        prompts.SHORT_SITUATION_MAX_CHARS
        + prompts.SHORT_PAYOFF_MAX_CHARS
        + prompts.SHORT_BODY_SECTION_CHARS * (prompts.SHORT_PROMPT_SECTIONS - 2)
    )
    assert prescribed <= prompts.SHORT_SAFE_MAX_CHARS


def test_overlong_short_is_actually_trimmed(monkeypatch):
    prompts = _reload_prompts(monkeypatch, min_sec=30.0, max_sec=45.0, sections=4)
    fix = importlib.reload(importlib.import_module("ytb_pipeline.orchestrator.ideation_script_fix"))

    body = "Đây là một câu giải thích cơ chế đủ dài để chiếm ngân sách ký tự. " * 5
    payload = {
        "video_type": "short",
        "sections": [
            {"purpose": "situation", "voiceover": "Giày giảm giá nhưng bạn vừa trả một cái giá khác."},
            {"purpose": "core_answer", "voiceover": body},
            {"purpose": "evidence", "voiceover": body},
            {"purpose": "payoff", "voiceover": body},
        ],
    }
    before = fix.short_narration_chars(payload)
    assert before > prompts.SHORT_MAX_CHARS

    candidate, note = fix.normalize_short_narration(payload, "short")
    assert note is not None, "an overlong Short must not be reported as normalized untouched"
    assert fix.short_narration_chars(candidate) <= prompts.SHORT_MAX_CHARS
