"""Test script_gen — không gọi `claude -p` thật, mock subprocess.run."""

from __future__ import annotations

import json

import pytest

from ytb_pipeline.content import script_gen


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
