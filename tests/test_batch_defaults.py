from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def _health_script() -> SimpleNamespace:
    narration = (
        "Bạn đi bộ sau bữa ăn và thấy cơ thể nhẹ hơn. Cơ chế nằm ở việc vận động nhẹ "
        "giúp cơ thể xử lý năng lượng ổn định hơn trong đời sống hàng ngày. "
    ) * 8
    return SimpleNamespace(
        slug="di-bo-sau-bua-an",
        topic="thói quen đi bộ sau bữa ăn",
        title="Đi Bộ Sau Bữa Ăn",
        description="Một thói quen sức khỏe đơn giản.",
        tags=["sức khỏe", "thói quen"],
        video_type="short",
        sections=[],
        segments=[SimpleNamespace(narration=narration, broll="person walking after meal")],
        compliance=SimpleNamespace(passed=True),
    )


@pytest.mark.asyncio
async def test_health_script_is_not_sent_to_legacy_entertainment_gate():
    from ytb_pipeline.agents.qa_agent import QAAgent

    result = await QAAgent().run({"script": _health_script(), "strict": False})

    assert result.output["passed"] is True
    assert not any(
        violation["rule"].startswith("entertainment_")
        for violation in result.output["violations"]
    )


def test_claude_batch_provider_uses_cli_default_model(monkeypatch):
    from ytb_pipeline.orchestrator import ideation_cmd

    captured: list[list[str]] = []
    monkeypatch.setattr(ideation_cmd, "build_claude_cmd", lambda prompt, **kwargs: captured.append(kwargs) or ["claude"])

    provider = ideation_cmd._ClaudeStartProvider()
    provider._invoke = lambda cmd: "{}"
    import asyncio

    asyncio.run(provider.complete("write JSON"))

    assert captured == [{}]
    assert provider.model_name() == "default"


def test_codex_batch_provider_uses_exec_json_prompt(monkeypatch):
    from ytb_pipeline.orchestrator import ideation_cmd

    monkeypatch.setattr(ideation_cmd, "_cli", lambda: type("CLI", (), {
        "settings": type("Settings", (), {"codex_bin": "codex"})(),
        "ROOT": ".",
    })())
    provider = ideation_cmd._CodexStartProvider()
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return type("Result", (), {"stdout": "{}"})()

    monkeypatch.setattr(ideation_cmd.subprocess, "run", fake_run)

    import asyncio
    asyncio.run(provider.complete("write JSON"))

    assert captured["cmd"] == ["codex", "exec", "--full-auto", "write JSON"]
    assert provider.model_name() == "default"


def test_batch_start_rejects_ollama_script_provider(monkeypatch):
    from ytb_pipeline.orchestrator import ideation_cmd

    monkeypatch.setattr(ideation_cmd, "_cli", lambda: type("CLI", (), {
        "settings": type("Settings", (), {"llm_provider": "ollama"})(),
    })())

    with pytest.raises(SystemExit, match="Chỉ hỗ trợ Claude hoặc Codex"):
        ideation_cmd.cmd_start(type("Args", (), {
            "num_of_vid": 1,
            "type_of_vid": "short",
            "type_of_rules": "auto",
            "resume": False,
            "cloud": False,
            "local": False,
        })())


def test_repair_prompt_requires_a_concrete_narrated_example():
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt({}, {"passed": False}, None)

    assert "Ví dụ cụ thể:" in prompt
    assert "bối cảnh" in prompt
    assert "hậu quả" in prompt


def test_json_parser_accepts_one_trailing_closing_brace():
    from ytb_pipeline.orchestrator.ideation_script_fix import json_from_llm

    assert json_from_llm('{"slug":"demo"}}') == {"slug": "demo"}
