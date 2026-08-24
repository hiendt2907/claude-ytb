from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _health_script() -> SimpleNamespace:
    unit = (
        "Bạn đi bộ sau bữa ăn và thấy cơ thể nhẹ hơn. Cơ chế nằm ở việc vận động nhẹ "
        "giúp cơ thể xử lý năng lượng ổn định hơn trong đời sống hàng ngày. "
    )
    from conftest import chars_for_minutes
    narration = (unit * (-(-len(chars_for_minutes(1.2)) // len(unit))))[:len(chars_for_minutes(1.2))]
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


def test_resume_counts_the_requested_batch_only(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "shorts_funnel_batch_older": {"long_videos": [{"slug": "older"}]},
        "shorts_funnel_batch_week3": {"long_videos": [{"slug": "week3"}]},
    }), encoding="utf-8")
    monkeypatch.setattr(ideation_state, "_cli", lambda: SimpleNamespace(done_slugs=lambda: set()))

    assert ideation_state.count_pending_ideation(
        "long", state, batch_key="shorts_funnel_batch_week3"
    ) == (1, ["week3"])


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


def test_personal_finance_psychology_prompt_requires_a_claim_level_evidence_register():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(
        1,
        1,
        "long",
        "tâm lý tài chính cá nhân; mọi quan điểm phải có nguồn kiểm chứng",
        "",
    )

    assert "editorial_profile" in prompt
    assert "personal_finance_psychology" in prompt
    assert "evidence_register" in prompt
    assert "primary, peer-reviewed, or official source" in prompt


def test_finance_safety_exclusion_does_not_activate_finance_editorial_profile():
    from ytb_pipeline.orchestrator.ideation_prompts import is_personal_finance_psychology_request

    for requirement in (
        "Thiên kiến hiện trạng; không tư vấn tài chính hay y tế.",
        "Thiên kiến hiện trạng; tránh chủ đề tài chính, y tế.",
    ):
        assert is_personal_finance_psychology_request(requirement) is False


def test_financial_evidence_gate_rejects_an_unverifiable_register():
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_financial_evidence_register

    with pytest.raises(ValueError, match="evidence_register"):
        validate_financial_evidence_register(
            {
                "editorial_profile": "personal_finance_psychology",
                "compliance": {"accuracy": "PASS"},
                "evidence_register": [{"claim": "Tiêu tiền theo cảm xúc"}],
            },
            required=True,
        )


def test_financial_repair_prompt_preserves_evidence_contract():
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt(
        {
            "editorial_profile": "personal_finance_psychology",
            "evidence_register": [{"claim": "A sourced claim"}],
        },
        None,
        "Financial script phải khai editorial_profile=personal_finance_psychology.",
    )

    assert "Preserve editorial_profile=personal_finance_psychology" in prompt
    assert "Preserve the complete evidence_register" in prompt
    assert "source_long_slug, source_section_index, source_excerpt" in prompt


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

    assert observed == [3600, 3600]


def test_batch_start_uses_xkiro_cascade_provider_by_default(monkeypatch):
    """Amendment 2026-08-24 (PROJECT_VISION.md Amendment Log): settings.llm_provider
    == "xkiro" (default) phải route qua CascadeScriptProvider (xKiro -> Codex CLI
    -> Claude CLI), không raise SystemExit."""
    from ytb_pipeline.orchestrator import ideation_cmd
    from ytb_pipeline.orchestrator.ideation_provider_cascade import CascadeScriptProvider

    monkeypatch.setattr(ideation_cmd, "_cli", lambda: type("CLI", (), {
        "settings": type("Settings", (), {"llm_provider": "xkiro"})(),
    })())

    captured: dict = {}

    async def fake_cmd_start_local(args):
        captured["provider"] = args._provider
        captured["strict_qa"] = args._strict_qa

    monkeypatch.setattr(ideation_cmd, "_cmd_start_local", fake_cmd_start_local)

    ideation_cmd.cmd_start(type("Args", (), {
        "num_of_vid": 1,
        "type_of_vid": "long",
        "type_of_rules": "auto",
        "resume": False,
        "cloud": False,
        "local": False,
        "llm_provider": None,
        "clear_ledger": False,
    })())

    assert isinstance(captured["provider"], CascadeScriptProvider)
    assert captured["provider"].name == "xkiro"
    assert captured["strict_qa"] is True


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


def test_system_prompt_makes_strategy_v1_non_negotiable_for_every_new_short():
    from ytb_pipeline.orchestrator.ideation_prompts import SCRIPT_GENERATION_SYSTEM_PROMPT

    assert "core_answer_first_v1" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert "answer_by_sec" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert "core_answer" in SCRIPT_GENERATION_SYSTEM_PROMPT


def test_system_prompt_does_not_require_removed_central_mechanism_scanner():
    """Qwen must not be constrained by a QA rule that no longer exists."""
    from ytb_pipeline.orchestrator.ideation_prompts import SCRIPT_GENERATION_SYSTEM_PROMPT

    prompt = SCRIPT_GENERATION_SYSTEM_PROMPT.casefold()

    assert "automated scanner reads every distinct phrase" not in prompt
    assert "never write \"cơ chế\" followed by" not in prompt


def test_short_prompt_uses_a_safe_length_buffer_and_immediate_answer_contract():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(
        1, 1, "short", "một cơ chế hành vi", "", funnel={
            "long_form_slug": "long-a", "playlist": "playlist-a", "cta_target": "long-a",
        }
    )

    from ytb_pipeline.orchestrator.ideation_prompts import (
        SHORT_SAFE_MAX_CHARS,
        SHORT_SAFE_MIN_CHARS,
        SHORT_SITUATION_MAX_CHARS,
    )

    assert f"{SHORT_SAFE_MIN_CHARS:,}-{SHORT_SAFE_MAX_CHARS:,}" in prompt
    # The hook budget must track the active narration rate; a fixed literal here
    # told the model it could spend 120 characters that xKiro cannot afford.
    assert f"{SHORT_SITUATION_MAX_CHARS} characters" in prompt
    assert "concrete tension marker" in prompt
    assert "exactly six sections" in prompt
    assert "immediate answer contract" in prompt


def test_short_prompt_requires_one_valueful_curiosity_source_from_its_long():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(
        1, 1, "short", "một cơ chế hành vi", "", funnel={
            "long_form_slug": "long-a", "playlist": "playlist-a", "cta_target": "long-a",
        }, source_long_context={
            "slug": "long-a",
            "title": "Long A",
            "candidates": [{
                "section_index": 4,
                "purpose": "giải thích điều bất ngờ",
                "excerpt": "Đây là một insight có giá trị và còn một câu hỏi cần mở rộng.",
            }],
        },
    )

    assert "Long-derived Short contract" in prompt
    assert "source_long_slug" in prompt
    assert "source_section_index" in prompt
    assert "Đây là một insight có giá trị" in prompt
    assert "Do not add a new factual claim" in prompt


def test_short_strategy_rejects_a_source_not_present_in_its_long_context():
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_short_strategy_v1

    payload = {
        "strategy": {
            "format_id": "core_answer_first_v1", "core_mechanism": "bất hòa nhận thức",
            "audience_problem": "một lựa chọn lệch giá trị", "angle": "câu ngoại lệ",
            "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a",
            "source_long_slug": "long-a", "source_section_index": 9,
            "source_excerpt": "Đoạn không thuộc Long nguồn.",
            "hook": {
                "situation": "Mua đồ uống", "core_answer": "Đó là bất hòa nhận thức",
                "open_loop": "Vì sao?", "answer_by_sec": 5,
            },
        },
        "sections": [
            {"purpose": "situation", "voiceover": "Mua đồ uống sau giờ làm."},
            {"purpose": "core_answer", "voiceover": "Đó là bất hòa nhận thức."},
        ],
    }

    with pytest.raises(ValueError, match="source_excerpt"):
        validate_short_strategy_v1(payload, source_long_context={
            "slug": "long-a",
            "candidates": [{"section_index": 4, "excerpt": "Đoạn nguồn đã được chọn."}],
        })


def test_short_strategy_rejects_a_core_answer_that_is_not_immediately_after_situation():
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_short_strategy_v1

    payload = {
        "strategy": {
            "format_id": "core_answer_first_v1", "core_mechanism": "bất hòa nhận thức",
            "audience_problem": "một lựa chọn lệch giá trị", "angle": "câu ngoại lệ",
            "long_form_slug": "long-a", "playlist": "playlist-a", "cta_target": "long-a",
            "hook": {
                "situation": "Mua đồ uống", "core_answer": "Đó là bất hòa nhận thức",
                "open_loop": "Vì sao?", "answer_by_sec": 5,
            },
        },
        "sections": [
            {"purpose": "situation", "voiceover": "Mua đồ uống sau giờ làm."},
            {"purpose": "evidence", "voiceover": "Một câu giải thích xuất hiện."},
            {"purpose": "core_answer", "voiceover": "Đó là bất hòa nhận thức."},
        ],
    }

    with pytest.raises(ValueError, match="immediately after situation"):
        validate_short_strategy_v1(payload)


def test_cmd_start_rejects_a_short_without_a_v1_batch_funnel_before_calling_an_llm(monkeypatch):
    from ytb_pipeline.orchestrator import ideation_cmd

    monkeypatch.setattr(
        ideation_cmd.asyncio,
        "run",
        lambda _coroutine: pytest.fail("a Short without a v1 funnel must fail before starting the LLM"),
    )
    with pytest.raises(SystemExit, match="batch-key.*long-form-slug.*playlist.*cta-target"):
        ideation_cmd.cmd_start(type("Args", (), {
            "num_of_vid": 1,
            "type_of_vid": "short",
            "type_of_rules": "auto",
            "resume": False,
            "cloud": False,
            "local": False,
        })())


def test_long_prompt_declares_a_safe_runtime_floor():
    from ytb_pipeline.orchestrator.ideation_prompts import SCRIPT_GENERATION_SYSTEM_PROMPT, local_script_prompt

    prompt = local_script_prompt(1, 1, "long", "auto", "")

    assert '"target_minutes": 12 (declare EXACTLY 12)' in prompt
    assert "actual audio stays 12-15 minutes" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert "first 28 spoken words after the greeting" in SCRIPT_GENERATION_SYSTEM_PROMPT


def test_long_prompt_uses_the_active_contract_not_legacy_duration_or_section_counts():
    """The E2E 3-minute contract must not inherit production's 12-minute prose."""
    from ytb_pipeline.orchestrator.ideation_prompts import (
        LONG_CONTRACT,
        LONG_MAX_MINUTES,
        LONG_MIN_MINUTES,
        PLANNING_CHARS_PER_MIN,
        local_script_prompt,
    )

    prompt = local_script_prompt(1, 1, "long", "một cơ chế tâm lý", "")
    expected_max_sections = int(LONG_CONTRACT.minimum_sections * 1.5)

    assert f"{LONG_MIN_MINUTES}-{LONG_MAX_MINUTES} min at {PLANNING_CHARS_PER_MIN:.0f}" in prompt
    assert f"{LONG_CONTRACT.minimum_sections}-{expected_max_sections} rich sections" in prompt
    assert "always exceed the declared" not in prompt
    assert "~12.25-14.5 min" not in prompt


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


def test_short_normalization_preserves_the_exact_core_answer_prefix():
    from ytb_pipeline.orchestrator.ideation_script_fix import normalize_short_narration

    core_answer = (
        "Cơ chế này xuất hiện để làm dịu khoảng cách giữa điều bạn chọn và điều bạn muốn tin, "
        "trước khi bạn vội dùng một lý do dễ chịu để khép lại sự khó chịu đó."
    )
    payload = {
        "strategy": {"hook": {"core_answer": core_answer}},
        "sections": [
            {"purpose": "situation", "voiceover": "Bạn vừa mua món này, nhưng vẫn thấy cấn. " * 20},
            {"purpose": "core_answer", "voiceover": core_answer + " " + "Diễn giải tiếp. " * 90},
            *[
                {"purpose": "evidence", "voiceover": "Một chi tiết cụ thể giúp bạn nhìn rõ hơn. " * 80}
                for _ in range(4)
            ],
        ],
    }

    fixed, note = normalize_short_narration(payload)

    assert note is not None
    assert fixed["sections"][1]["voiceover"].startswith(core_answer)


def test_preassigned_short_source_provenance_fills_only_the_declared_candidate():
    from ytb_pipeline.orchestrator.ideation_cmd import attach_preassigned_short_source_provenance

    payload = {"strategy": {"long_form_slug": "long-a"}}
    source_context = {
        "slug": "long-a",
        "candidates": [{"section_index": 4, "excerpt": "Đoạn Long đã được chọn."}],
    }

    result = attach_preassigned_short_source_provenance(payload, source_context)

    assert result["strategy"] == {
        "long_form_slug": "long-a",
        "source_long_slug": "long-a",
        "source_section_index": 4,
        "source_excerpt": "Đoạn Long đã được chọn.",
    }


def test_preassigned_short_source_provenance_rejects_a_model_claiming_another_source():
    from ytb_pipeline.orchestrator.ideation_cmd import attach_preassigned_short_source_provenance

    with pytest.raises(ValueError, match="provenance mâu thuẫn"):
        attach_preassigned_short_source_provenance(
            {"strategy": {"source_section_index": 9}},
            {"slug": "long-a", "candidates": [{"section_index": 4, "excerpt": "Đoạn Long."}]},
        )


def test_long_repair_prompt_requires_target_minutes_and_preserves_valid_narration():
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt({"video_type": "long"}, None, "nội dung quá mỏng")

    assert '"target_minutes" is required for a Long' in prompt
    assert "Do not shorten or delete valid existing narration" in prompt
    assert "Rewrite the first narration section" in prompt
    assert "legacy narration=voiceover" not in prompt


def test_long_extension_prompt_requests_only_new_sections_for_the_missing_runtime():
    from ytb_pipeline.orchestrator.ideation_prompts import long_extension_prompt

    prompt = long_extension_prompt(
        {"slug": "thien-kien-nhin-lai", "title": "Biết ngay mà", "sections": []},
        missing_chars=10_000,
    )

    assert "Return ONLY one JSON object with a `sections` array" in prompt
    assert "Do not rewrite, repeat, or summarize the existing sections" in prompt
    assert "10,000" in prompt
    assert "voiceover" in prompt


def test_append_long_extension_inserts_before_conclusion_without_mutating_source():
    from ytb_pipeline.orchestrator.ideation_script_fix import append_long_extension

    source = {
        "sections": [
            {"purpose": "hook", "voiceover": "Mở đầu."},
            {"purpose": "conclusion", "voiceover": "Kết thúc."},
        ]
    }
    result = append_long_extension(
        source,
        {"sections": [{"purpose": "evidence", "voiceover": "Phần bổ sung."}]},
    )

    assert [section["voiceover"] for section in result["sections"]] == [
        "Mở đầu.", "Phần bổ sung.", "Kết thúc."
    ]
    assert len(source["sections"]) == 2


def test_short_expansion_delta_only_changes_named_middle_sections_without_mutating_source():
    from ytb_pipeline.orchestrator.ideation_script_fix import apply_short_expansion

    source = {
        "sections": [
            {"purpose": "situation", "voiceover": "Tình huống."},
            {"purpose": "core_answer", "voiceover": "Đáp án."},
            {"purpose": "evidence", "voiceover": "Bằng chứng."},
            {"purpose": "application", "voiceover": "Áp dụng."},
            {"purpose": "payoff", "voiceover": "Kết."},
        ]
    }

    result = apply_short_expansion(
        source,
        {"section_updates": [{"index": 2, "append_voiceover": " Chi tiết đúng chủ đề."}]},
    )

    assert result["sections"][2]["voiceover"] == "Bằng chứng. Chi tiết đúng chủ đề."
    assert result["sections"][0]["voiceover"] == "Tình huống."
    assert source["sections"][2]["voiceover"] == "Bằng chứng."


def test_short_expansion_prompt_forbids_full_script_regeneration():
    from ytb_pipeline.orchestrator.ideation_prompts import short_expansion_prompt

    prompt = short_expansion_prompt(
        {"slug": "co-che-test", "sections": [{"purpose": "evidence", "voiceover": "Nội dung."}]},
        missing_chars=900,
    )

    assert "`section_updates` array" in prompt
    assert "Do not return the full script" in prompt
    assert "900" in prompt


def test_script_prompt_uses_canonical_section_fields_without_alias_duplication():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(1, 1, "long", "một cơ chế tâm lý", "")

    assert "voiceover" in prompt
    assert "pexels_query" in prompt
    assert "Keep legacy narration equal to voiceover" not in prompt


def test_long_overflow_is_trimmed_without_touching_opening_or_final_cta():
    from ytb_pipeline.orchestrator.ideation_prompts import LONG_SAFE_MAX_CHARS
    from ytb_pipeline.orchestrator.ideation_script_fix import (
        normalize_long_overflow,
        short_narration_chars,
    )

    opening = "Mến chào các bạn, " + "mở đầu có chủ đề. " * 60
    final = "Hãy làm một việc trong mười phút. Hãy like và subscribe. " * 50
    payload = {
        "sections": [{"voiceover": opening}]
        + [{"voiceover": "nội dung cụ thể. " * 1000} for _ in range(4)]
        + [{"voiceover": final}],
    }

    fixed, note = normalize_long_overflow(payload, expected_video_type="long")

    assert note is not None
    assert short_narration_chars(fixed) <= LONG_SAFE_MAX_CHARS
    assert fixed["sections"][0]["voiceover"] == opening
    assert fixed["sections"][-1]["voiceover"] == final


def test_short_normalizer_keeps_original_when_sentence_trim_would_undershoot(monkeypatch):
    from ytb_pipeline.orchestrator import ideation_script_fix as fixer

    payload = {"sections": [{"voiceover": "nội dung đủ dài. " * 400}]}
    original = json.loads(json.dumps(payload))
    monkeypatch.setattr(fixer, "trim_to_sentence", lambda _text, _limit: "quá ngắn.")

    fixed, note = fixer.normalize_short_narration(payload)

    assert fixed == original
    assert note is None


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


def test_json_parser_heals_unescaped_quote_from_qwen(monkeypatch):
    """Qwen/Ollama local đôi khi để lọt quote chưa escape bên trong string —
    json.loads/raw_decode chuẩn thất bại, heal_json (json_repair) phải cứu được."""
    from ytb_pipeline.orchestrator.ideation_script_fix import json_from_llm

    broken = '{"title": "Vì sao "não" lại né việc?", "slug": "vi-sao-nao-lai-ne-viec"}'

    result = json_from_llm(broken)

    assert result["slug"] == "vi-sao-nao-lai-ne-viec"
    assert "não" in result["title"]


def test_json_parser_heals_vietnamese_slug_with_diacritics(monkeypatch):
    """A missing closing brace is structural and must not be silently healed."""
    from ytb_pipeline.orchestrator.ideation_script_fix import json_from_llm

    broken = '{"slug": "vì sao "trì hoãn" là cơ chế sinh tồn", "ok": true'  # thiếu `}` cuối

    with pytest.raises(json.JSONDecodeError):
        json_from_llm(broken)


def test_json_parser_rejects_the_recorded_xkiro_structural_corruption():
    """The real extra quote must never expand six sections into repaired garbage."""
    from pathlib import Path
    from ytb_pipeline.orchestrator.ideation_script_fix import json_from_llm

    raw = (
        Path(__file__).resolve().parents[1]
        / "assets/script_revisions/failed_ideation/candidate_1_20260824_160432_629562.raw.txt"
    ).read_text(encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        json_from_llm(raw)


def test_json_parser_still_raises_original_error_when_unhealable(monkeypatch):
    """heal_json không cứu được (không phải JSON) -> giữ nguyên lỗi gốc, không nuốt lỗi."""
    from ytb_pipeline.orchestrator.ideation_script_fix import json_from_llm

    with pytest.raises(json.JSONDecodeError):
        json_from_llm("hoàn toàn không phải JSON, chỉ là văn xuôi tự do.")
