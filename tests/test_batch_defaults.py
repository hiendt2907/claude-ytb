from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _health_script() -> SimpleNamespace:
    narration = (
        "Bạn đi bộ sau bữa ăn và thấy cơ thể nhẹ hơn. Cơ chế nằm ở việc vận động nhẹ "
        "giúp cơ thể xử lý năng lượng ổn định hơn trong đời sống hàng ngày. "
    ) * 10
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

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        ideation_cmd,
        "build_claude_cmd",
        lambda prompt, **kwargs: captured.append((prompt, kwargs)) or ["claude"],
    )

    provider = ideation_cmd._ClaudeStartProvider()
    provider._invoke = lambda cmd: "{}"
    import asyncio

    asyncio.run(provider.complete("write JSON", system="editorial contract"))

    assert captured == [("editorial contract\n\nUser task:\nwrite JSON", {})]
    assert provider.model_name() == "default"


def test_script_prompts_define_numeric_positive_time_goal():
    from ytb_pipeline.orchestrator.ideation_prompts import (
        SCRIPT_GENERATION_SYSTEM_PROMPT,
        build_start_prompt,
        repair_prompt,
    )

    for prompt in (
        SCRIPT_GENERATION_SYSTEM_PROMPT,
        build_start_prompt(1, "long", "auto"),
        repair_prompt({}, {}, "time_goal phải > 0"),
    ):
        assert "positive JSON number" in prompt
        assert "never 0/null/string/timestamp/range" in prompt


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
    asyncio.run(provider.complete("write JSON", system="editorial contract"))

    assert captured["cmd"][:4] == ["codex", "exec", "--full-auto", "--output-last-message"]
    assert captured["cmd"][-1] == "editorial contract\n\nUser task:\nwrite JSON"
    assert provider.model_name() == "default"


def test_codex_batch_provider_reads_only_last_message_file(monkeypatch):
    """Codex startup logs must never be mixed into a JSON script response."""
    from ytb_pipeline.orchestrator import ideation_cmd

    monkeypatch.setattr(ideation_cmd, "_cli", lambda: type("CLI", (), {
        "settings": type("Settings", (), {"codex_bin": "codex"})(),
        "ROOT": ".",
    })())

    def fake_run(cmd, **_kwargs):
        output_index = cmd.index("--output-last-message") + 1
        Path(cmd[output_index]).write_text('{"slug":"clean"}', encoding="utf-8")
        return type("Result", (), {"stdout": "noisy startup logs\n{wrong json}"})()

    monkeypatch.setattr(ideation_cmd.subprocess, "run", fake_run)

    assert ideation_cmd._CodexStartProvider()._invoke(["codex", "exec", "prompt"]) == '{"slug":"clean"}'


def test_script_providers_allow_long_generation_budget(monkeypatch):
    """Long-form generation must not be killed at the legacy five-minute ceiling."""
    from ytb_pipeline.orchestrator import ideation_cmd

    monkeypatch.setattr(ideation_cmd, "_cli", lambda: type("CLI", (), {"ROOT": "."})())
    observed: list[int] = []

    def fake_run(*_args, **kwargs):
        observed.append(kwargs["timeout"])
        return type("Result", (), {"stdout": "{}"})()

    monkeypatch.setattr(ideation_cmd.subprocess, "run", fake_run)
    ideation_cmd._ClaudeStartProvider()._invoke(["claude", "prompt"])
    ideation_cmd._CodexStartProvider()._invoke(["codex", "exec", "prompt"])

    assert observed == [900, 900]


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


def test_repair_prompt_requires_a_natural_concrete_narrated_example():
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt({}, {"passed": False}, None)

    assert "specific everyday context" in prompt
    assert "natural Vietnamese" in prompt
    assert "fixed labels" in prompt


def test_system_prompt_requires_an_immediate_action_in_final_narration():
    from ytb_pipeline.orchestrator.ideation_prompts import SCRIPT_GENERATION_SYSTEM_PROMPT

    prompt = SCRIPT_GENERATION_SYSTEM_PROMPT

    assert "final narration section" in prompt
    assert '"Hãy "' in prompt


def test_long_prompt_declares_a_safe_runtime_floor():
    from ytb_pipeline.orchestrator.ideation_prompts import SCRIPT_GENERATION_SYSTEM_PROMPT, local_script_prompt

    prompt = local_script_prompt(1, 1, "long", "auto", "")

    assert '"target_minutes": 12 (declare EXACTLY 12)' in prompt
    assert "measured minutes fall below the declared target_minutes" in SCRIPT_GENERATION_SYSTEM_PROMPT


def test_custom_long_prompt_does_not_describe_the_long_as_a_short():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(1, 1, "long", "một cơ chế tâm lý", "")

    assert "knowledge short" not in prompt
    assert "knowledge long-form video" in prompt


def test_long_prompt_makes_target_minutes_an_explicit_json_field():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(1, 1, "long", "một cơ chế tâm lý", "")

    assert '"target_minutes" is required for a Long' in prompt


def test_expected_long_is_never_normalized_as_a_short_when_target_is_missing():
    from ytb_pipeline.orchestrator.ideation_script_fix import normalize_short_narration

    payload = {
        "video_type": "long",
        "sections": [{"voiceover": "Mến chào các bạn, " + "nội dung " * 500}],
    }

    fixed, note = normalize_short_narration(payload, expected_video_type="long")

    assert fixed == payload
    assert note is None


def test_long_repair_prompt_requires_target_minutes_and_preserves_valid_narration():
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt({"video_type": "long"}, None, "nội dung quá mỏng")

    assert '"target_minutes" is required for a Long' in prompt
    assert "Do not shorten or delete valid existing narration" in prompt
    assert "legacy narration=voiceover" not in prompt


def test_script_prompt_uses_canonical_section_fields_without_alias_duplication():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(1, 1, "long", "một cơ chế tâm lý", "")

    assert "voiceover" in prompt
    assert "pexels_query" in prompt
    assert "Keep legacy narration equal to voiceover" not in prompt


def test_expected_long_contract_rejects_a_short_payload():
    """A long queue slot must never accept a JSON document shaped as a Short."""
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_expected_video_type

    with pytest.raises(ValueError, match="expected long"):
        validate_expected_video_type(
            {"video_type": "short", "sections": []},
            expected_video_type="long",
            script_name="week2-long.json",
        )


def test_json_parser_accepts_one_trailing_closing_brace():
    from ytb_pipeline.orchestrator.ideation_script_fix import json_from_llm

    assert json_from_llm('{"slug":"demo"}}') == {"slug": "demo"}


def test_json_parser_accepts_prose_wrapped_fenced_json():
    from ytb_pipeline.orchestrator.ideation_script_fix import json_from_llm

    response = 'Đây là JSON đã sửa:\n\n```json\n{"slug":"demo"}\n```'

    assert json_from_llm(response) == {"slug": "demo"}
