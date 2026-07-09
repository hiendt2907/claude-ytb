"""Test script_gen — không gọi `claude -p` thật, mock subprocess.run."""

from __future__ import annotations

import json

import pytest

from ytb_pipeline.content import script_gen
from ytb_pipeline.content.ledger import LedgerEntry
from ytb_pipeline.content.models import Script, ScriptSegment


def _fake_claude_json() -> str:
    return json.dumps(
        {
            "title": "Thói quen dậy sớm",
            "description": "Video truyền cảm hứng về dậy sớm.",
            "segments": [
                {"narration": "Câu 1.", "visual_keywords": ["sunrise", "alarm clock"]},
                {"narration": "Câu 2.", "visual_keywords": ["morning walk"]},
            ],
        }
    )


def test_parse_script_json_returns_script_with_segments():
    script = script_gen.parse_script_json(_fake_claude_json())

    assert script.title == "Thói quen dậy sớm"
    assert len(script.segments) == 2
    assert script.segments[0].narration == "Câu 1."
    assert script.segments[0].visual_keywords == ("sunrise", "alarm clock")


def test_parse_script_json_strips_markdown_fence():
    fenced = "```json\n" + _fake_claude_json() + "\n```"

    script = script_gen.parse_script_json(fenced)

    assert script.title == "Thói quen dậy sớm"


def test_parse_script_json_raises_on_empty_segments():
    empty = json.dumps({"title": "x", "description": "", "segments": []})

    with pytest.raises(ValueError):
        script_gen.parse_script_json(empty)


def test_generate_script_raises_on_nonzero_exit(monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "lỗi giả lập"

    monkeypatch.setattr(script_gen.subprocess, "run", lambda *a, **k: FakeResult())

    with pytest.raises(RuntimeError, match="lỗi giả lập"):
        script_gen.generate_script("chủ đề bất kỳ")


def test_generate_script_parses_stdout_on_success(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = _fake_claude_json()
        stderr = ""

    monkeypatch.setattr(script_gen.subprocess, "run", lambda *a, **k: FakeResult())

    script = script_gen.generate_script("chủ đề bất kỳ")

    assert script.title == "Thói quen dậy sớm"


def test_generate_script_auto_raises_when_all_topics_in_ledger(monkeypatch):
    monkeypatch.setattr(
        script_gen.research,
        "research_trending",
        lambda **kw: {
            "research": [{"topic": "Chủ đề đã làm"}],
            "seo_pool": {"keywords": []},
        },
    )
    ledger = [LedgerEntry(slug="chu-de-da-lam", title="Chủ đề đã làm", created_at="2026-07-01")]

    with pytest.raises(RuntimeError, match="đã có trong ledger"):
        script_gen.generate_script_auto(ledger)


def test_generate_script_auto_picks_candidate_and_calls_claude(monkeypatch):
    monkeypatch.setattr(
        script_gen.research,
        "research_trending",
        lambda **kw: {
            "research": [{"topic": "Chủ đề mới"}, {"topic": "Chủ đề đã làm"}],
            "seo_pool": {"keywords": ["tu khoa a", "tu khoa b"]},
        },
    )
    ledger = [LedgerEntry(slug="chu-de-da-lam", title="Chủ đề đã làm", created_at="2026-07-01")]

    captured_prompt = {}

    class FakeResult:
        returncode = 0
        stdout = _fake_claude_json()
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured_prompt["prompt"] = cmd[-1]
        return FakeResult()

    monkeypatch.setattr(script_gen.subprocess, "run", fake_run)

    script = script_gen.generate_script_auto(ledger)

    assert script.title == "Thói quen dậy sớm"
    assert "Chủ đề mới" in captured_prompt["prompt"]
    assert "Chủ đề đã làm" not in captured_prompt["prompt"]


def test_repair_script_sends_violations_and_returns_fixed_script(monkeypatch):
    original = Script(
        title="t",
        description="",
        segments=(ScriptSegment(narration="a", visual_keywords=("x",)),),
    )
    violations = [{"rule": "length", "detail": "Quá ngắn."}]

    captured_prompt = {}

    class FakeResult:
        returncode = 0
        stdout = _fake_claude_json()
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured_prompt["prompt"] = cmd[-1]
        return FakeResult()

    monkeypatch.setattr(script_gen.subprocess, "run", fake_run)

    fixed = script_gen.repair_script(original, violations)

    assert fixed.title == "Thói quen dậy sớm"
    assert "length" in captured_prompt["prompt"]
    assert "Quá ngắn" in captured_prompt["prompt"]
