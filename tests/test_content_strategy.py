from __future__ import annotations

import pytest


def test_loader_hydrates_optional_strategy_without_breaking_legacy_scripts(tmp_path):
    from conftest import chars_for_minutes
    from ytb_pipeline.ideation.generator import load_script

    narration = chars_for_minutes(1.2)
    source = tmp_path / "strategy-short.json"
    source.write_text(
        """{
          "title": "Mở laptop rồi cầm điện thoại",
          "video_type": "short",
              "sections": [
                {"voiceover": "Mở laptop nhưng tay lại mở điện thoại.", "purpose": "situation"},
                {"voiceover": "Não đang né sự mơ hồ%s", "purpose": "core_answer"}
              ],
          "strategy": {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "tránh né sự mơ hồ",
            "audience_problem": "mở laptop rồi cầm điện thoại",
            "angle": "trang trắng",
            "long_form_slug": "buoc-dau-mo-ho",
            "playlist": "co-che-tri-hoan",
            "cta_target": "buoc-dau-mo-ho",
            "hook": {
              "situation": "Mở laptop rồi cầm điện thoại",
              "core_answer": "Não đang né sự mơ hồ",
              "open_loop": "Vì sao nó xảy ra?",
              "answer_by_sec": 5
            }
          },
          "compliance": {
            "passed": true, "community": "PASS", "copyright": "PASS",
            "accuracy": "PASS", "advertiser": "PASS", "coppa": "PASS", "notes": "PASS"
          }
        }""" % narration,
        encoding="utf-8",
    )

    script = load_script(source)

    assert script.strategy is not None
    assert script.strategy.format_id == "core_answer_first_v1"
    assert script.segments[1].purpose == "core_answer"


def _short_voiceover(*, answer_duration: float):
    from ytb_pipeline.pkg.models import (
        ContentStrategy,
        HookPlan,
        Segment,
        Voiceover,
    )

    strategy = ContentStrategy(
        format_id="core_answer_first_v1",
        core_mechanism="tránh né sự mơ hồ của bước đầu",
        audience_problem="mở laptop rồi cầm điện thoại",
        angle="trang trắng trước khi viết báo cáo",
        long_form_slug="buoc-dau-mo-ho",
        playlist="co-che-tri-hoan",
        cta_target="buoc-dau-mo-ho",
        hook=HookPlan(
            situation="Mở laptop rồi lại cầm điện thoại",
            core_answer="Não đang né khoảnh khắc chưa biết bắt đầu từ đâu",
            open_loop="Vì sao sự mơ hồ này mạnh hơn ý chí?",
            answer_by_sec=5.0,
        ),
    )
    return Voiceover(
        topic="Trì hoãn",
        title="Mở laptop rồi cầm điện thoại",
        description="",
        video_type="short",
        strategy=strategy,
        segments=(
            Segment(
                caption="MỞ LAPTOP",
                narration="Mở laptop rồi lại cầm điện thoại.",
                purpose="situation",
                duration_sec=1.5,
            ),
            Segment(
                caption="KHÔNG PHẢI LƯỜI",
                narration="Não đang né khoảnh khắc chưa biết bắt đầu từ đâu.",
                purpose="core_answer",
                duration_sec=answer_duration,
            ),
        ),
    )


def test_hook_timing_accepts_a_core_answer_that_starts_within_five_seconds():
    from ytb_pipeline.voiceover.validation import validate_hook_timing

    validate_hook_timing(_short_voiceover(answer_duration=3.4))


def test_hook_timing_rejects_a_core_answer_that_starts_after_the_declared_deadline():
    from ytb_pipeline.voiceover.validation import validate_hook_timing

    voiceover = _short_voiceover(answer_duration=12.0)
    delayed = voiceover.segments[0].__class__(
        caption=voiceover.segments[0].caption,
        narration=voiceover.segments[0].narration,
        purpose=voiceover.segments[0].purpose,
        duration_sec=5.1,
    )
    from dataclasses import replace

    with pytest.raises(ValueError, match="bắt đầu.*5.0s"):
        validate_hook_timing(replace(voiceover, segments=(delayed, voiceover.segments[1])))


def test_loader_rejects_a_short_when_its_answer_cannot_start_by_deadline(write_script):
    from conftest import chars_for_minutes, make_script
    from ytb_pipeline.ideation.generator import load_script

    payload = make_script(
        [
            # Keep the answer deliberately after 5s while the whole Short
            # stays valid for every calibrated TTS provider.
            {"purpose": "situation", "voiceover": chars_for_minutes(0.15)},
            {"purpose": "core_answer", "voiceover": "Đó là câu trả lời. " + chars_for_minutes(1.1)},
        ]
    )
    payload["strategy"] = {
        "format_id": "core_answer_first_v1",
        "core_mechanism": "một cơ chế",
        "audience_problem": "một vấn đề",
        "angle": "một góc",
        "long_form_slug": "long-a",
        "playlist": "series-a",
        "cta_target": "long-a",
        "hook": {
            "situation": "Một tình huống",
            "core_answer": "Đó là câu trả lời.",
            "open_loop": "Vì sao?",
            "answer_by_sec": 5,
        },
    }

    with pytest.raises(ValueError, match="không thể bắt đầu trước 5.0s"):
        load_script(write_script(payload))


def test_strategy_requires_a_complete_short_to_long_funnel():
    from ytb_pipeline.pkg.models import ContentStrategy, HookPlan

    with pytest.raises(ValueError, match="cta_target"):
        ContentStrategy(
            format_id="core_answer_first_v1",
            core_mechanism="tránh né sự mơ hồ",
            audience_problem="mở laptop rồi cầm điện thoại",
            angle="trang trắng",
            long_form_slug="buoc-dau-mo-ho",
            playlist="co-che-tri-hoan",
            hook=HookPlan(
                situation="Mở laptop rồi cầm điện thoại",
                core_answer="Não đang né sự mơ hồ",
                open_loop="Điều gì khiến nó xảy ra?",
            ),
        )


def test_strategy_v1_payload_cannot_be_missing_from_a_new_short():
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_short_strategy_v1

    with pytest.raises(ValueError, match="strategy-v1"):
        validate_short_strategy_v1({"video_type": "short", "sections": []})


async def test_strict_qa_rejects_a_strategy_short_without_a_core_answer_segment():
    from ytb_pipeline.agents.qa_agent import QAAgent
    from ytb_pipeline.pkg.models import ComplianceCheck, ContentStrategy, HookPlan, Script, Segment

    script = Script(
        topic="Trì hoãn",
        title="Mở laptop rồi cầm điện thoại",
        description="",
        video_type="short",
        compliance=ComplianceCheck(True, "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
        strategy=ContentStrategy(
            format_id="core_answer_first_v1",
            core_mechanism="tránh né sự mơ hồ",
            audience_problem="mở laptop rồi cầm điện thoại",
            angle="trang trắng",
            long_form_slug="buoc-dau-mo-ho",
            playlist="co-che-tri-hoan",
            cta_target="buoc-dau-mo-ho",
            hook=HookPlan(
                situation="Mở laptop rồi cầm điện thoại",
                core_answer="Não đang né sự mơ hồ",
                open_loop="Vì sao nó xảy ra?",
            ),
        ),
        segments=(Segment(caption="", narration="Một câu mở đầu.", purpose="situation"),),
    )

    result = await QAAgent().run({"script": script, "strict": True})

    assert any(item["rule"] == "hook_contract" for item in result.output["violations"])


def test_script_prompt_requires_the_strategy_v1_hook_contract():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(1, 1, "short", "auto", "")

    assert '"strategy"' in prompt
    assert "core_answer" in prompt
    assert "answer_by_sec" in prompt
    assert "phát triển bản thân thật, không self-help" in prompt.lower()


def test_approval_preview_exposes_the_short_hook_and_long_destination():
    from ytb_pipeline.ideation.approval import _format_full

    preview = _format_full(_short_voiceover(answer_duration=3.4))

    assert "⚡ Hook 0–5s" in preview
    assert "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu" in preview
    assert "↗️ Long đích: buoc-dau-mo-ho" in preview


def test_repair_prompt_preserves_strategy_v1_instead_of_downgrading_to_legacy():
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt(
        {
            "video_type": "short",
            "strategy": {
                "format_id": "core_answer_first_v1",
                "hook": {"core_answer": "Não đang né sự mơ hồ"},
            },
        },
        {"violations": [{"rule": "hook_contract"}]},
        None,
    )

    assert '"strategy"' in prompt
    assert "core_answer" in prompt
    assert "purpose" in prompt


def _strategy_short_payload(situation: str) -> dict:
    """A minimal strategy-v1 Short shaped exactly like the production payload."""
    return {
        "video_type": "short",
        "profile_id": "",
        "strategy": {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "tránh né sự mơ hồ",
            "audience_problem": "mở laptop rồi cầm điện thoại",
            "angle": "trang trắng",
            "long_form_slug": "buoc-dau-mo-ho",
            "playlist": "co-che-tri-hoan",
            "cta_target": "buoc-dau-mo-ho",
            "hook": {
                "situation": situation,
                "core_answer": "Não đang né sự mơ hồ",
                "open_loop": "Vì sao nó xảy ra?",
                "answer_by_sec": 5,
            },
        },
        "sections": [
            {"purpose": "situation", "voiceover": situation},
            {"purpose": "core_answer", "voiceover": "Não đang né sự mơ hồ. Rồi tay mở điện thoại."},
        ],
    }


def test_short_situation_gate_accepts_only_the_markers_it_documents():
    """The gate's accepted markers are a closed lexical whitelist, not a concept.

    Production 2026-08-30: an editorially natural opening carrying explicit
    tension but none of these exact tokens is rejected outright, so any prompt
    that only asks for "a concrete tension marker" cannot reliably satisfy it.
    """
    from ytb_pipeline.orchestrator.ideation_script_fix import (
        SHORT_SITUATION_TENSION_MARKERS,
        validate_short_strategy_v1,
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        validate_short_strategy_v1(
            _strategy_short_payload(f"Còn mười phút nữa họp, {marker} dòng vẫn để nguyên.")
        )

    with pytest.raises(ValueError, match="tension marker"):
        validate_short_strategy_v1(
            _strategy_short_payload("Còn mười phút nữa họp, dòng bôi vàng vẫn để nguyên à?")
        )


def test_editorial_rewrite_guard_names_the_markers_the_short_gate_will_check():
    """A cited section 1 must be rewritable into something the gate accepts.

    Production 2026-08-30 (ideation_20260830_082534/083708/085402): the review
    cited section 1, the rewrite came back editorially better but without one of
    the whitelisted tokens, and `Editorial rewrite phá Short strategy-v1` threw
    the whole delta away. The bounded editorial budget was then spent
    re-reviewing byte-identical payloads — three reviews, one payload SHA, the
    same 3/10 — so the engine's only self-repair path never applied once.
    """
    from types import SimpleNamespace

    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt
    from ytb_pipeline.orchestrator.ideation_script_fix import SHORT_SITUATION_TENSION_MARKERS

    prompt = editorial_rewrite_prompt(
        _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên."),
        SimpleNamespace(
            blocking_findings=["An never speaks or asks a real question."],
            section_refs=[1],
            overall_score=6,
            dimension_scores={"role_fidelity": 4},
            repair_brief="Give An one real spoken question.",
        ),
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        assert marker in prompt


def test_short_generation_instruction_names_the_markers_the_gate_will_check():
    """The first generation attempt must not have to guess the whitelist either.

    Production 2026-08-30 (ideation_20260830_081943): a first-pass candidate was
    rejected for exactly this before any repair budget was even reached.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt
    from ytb_pipeline.orchestrator.ideation_script_fix import SHORT_SITUATION_TENSION_MARKERS

    prompt = local_script_prompt(
        1,
        1,
        "short",
        "auto",
        "",
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        assert marker in prompt


def test_hook_repair_names_the_markers_for_a_strategy_short():
    """The hook repair rewrites the very section the marker gate polices.

    Production 2026-08-30 (ideation_20260830_084815 and _092129): QA rejected the
    hook, the bounded repair returned a well-anchored opening carrying real
    tension, but without a whitelisted token — so contract validation killed the
    whole run. Two supervised attempts died this way at the third rewrite site.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import hook_repair_prompt
    from ytb_pipeline.orchestrator.ideation_script_fix import SHORT_SITUATION_TENSION_MARKERS

    # The production path is a character_story profile, whose hook directive is
    # STORY_HOOK_CONTRACT — it never carried the marker list that the legacy
    # Long directive happens to mention.
    prompt = hook_repair_prompt(
        _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên."),
        "Cảnh mở đầu chưa neo được khoảnh khắc hoặc chưa có gì để mất.",
        content_profile=load_content_profile("ban-so-6"),
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        assert marker in prompt


def test_hook_repair_stays_silent_about_short_markers_for_a_long():
    """A Long opening is judged by a different contract; do not leak this one."""
    from ytb_pipeline.orchestrator.ideation_prompts import hook_repair_prompt

    prompt = hook_repair_prompt(
        {"video_type": "long", "sections": [{"purpose": "intro", "voiceover": "Mến chào các bạn,"}]},
        "Cảnh mở đầu chưa neo được khoảnh khắc.",
    )

    assert "exact Vietnamese markers" not in prompt
