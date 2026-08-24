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
    from conftest import make_script
    from ytb_pipeline.ideation.generator import load_script

    payload = make_script(
        [
            {"purpose": "situation", "voiceover": "x" * 180},
            {"purpose": "core_answer", "voiceover": "Đó là câu trả lời. " + "x" * 900},
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
