"""Test content/qa.py — cổng chất lượng rule-based, không gọi LLM."""

from __future__ import annotations

from ytb_pipeline.content import qa
from ytb_pipeline.content.ledger import LedgerEntry, slugify
from ytb_pipeline.content.models import Script, ScriptSegment


def _script(title="Thói quen dậy sớm", narration_repeat=24, visual_keywords=("sunrise walk",)):
    narration = "Đây là một câu ví dụ để đo độ dài đoạn văn bản. " * narration_repeat
    return Script(
        title=title,
        description="d",
        segments=(ScriptSegment(narration=narration, visual_keywords=visual_keywords),),
    )


def test_check_script_passes_for_well_formed_script():
    result = qa.check_script(_script())

    assert result["passed"] is True
    assert result["violations"] == []


def test_check_script_flags_too_short():
    script = Script(
        title="t",
        description="",
        segments=(ScriptSegment(narration="Ngắn quá.", visual_keywords=("a b",)),),
    )

    result = qa.check_script(script)

    assert result["passed"] is False
    assert any(v["rule"] == "length" for v in result["violations"])


def test_check_script_flags_self_help_mantra():
    script = Script(
        title="t",
        description="",
        segments=(
            ScriptSegment(
                narration="Hãy tin vào bản thân, " * 20,
                visual_keywords=("a b",),
            ),
        ),
    )

    result = qa.check_script(script)

    assert any(v["rule"] == "niche_self_help" for v in result["violations"])


def test_check_script_flags_stage_direction_leak():
    script = _script()
    leaked = Script(
        title=script.title,
        description=script.description,
        segments=(
            ScriptSegment(
                narration="Cú hình tiếp theo: " + script.segments[0].narration,
                visual_keywords=script.segments[0].visual_keywords,
            ),
        ),
    )

    result = qa.check_script(leaked)

    assert any(v["rule"] == "stage_direction" for v in result["violations"])


def test_check_script_flags_weak_visual_keywords():
    script = _script(visual_keywords=("video",))

    result = qa.check_script(script)

    assert any(v["rule"] == "visual_keywords" for v in result["violations"])


def test_check_script_flags_ledger_dedup():
    ledger = [LedgerEntry(slug=slugify("Thói quen dậy sớm"), title="Thói quen dậy sớm", created_at="2026-07-01")]

    result = qa.check_script(_script(title="Thói Quen Dậy Sớm"), ledger)

    assert any(v["rule"] == "ledger_dedup" for v in result["violations"])


def test_check_script_warns_on_unsourced_claim_without_blocking():
    script = _script()
    with_claim = Script(
        title=script.title,
        description=script.description,
        segments=(
            ScriptSegment(
                narration="Nghiên cứu cho thấy điều này đúng. " + script.segments[0].narration,
                visual_keywords=script.segments[0].visual_keywords,
            ),
        ),
    )

    result = qa.check_script(with_claim)

    assert any(w["rule"] == "sourced_claims" for w in result["warnings"])
    assert result["passed"] is True


def test_check_script_no_warning_when_source_cited():
    script = _script()
    with_source = Script(
        title=script.title,
        description=script.description,
        segments=(
            ScriptSegment(
                narration="Nghiên cứu cho thấy (nguồn: abc.com) " + script.segments[0].narration,
                visual_keywords=script.segments[0].visual_keywords,
            ),
        ),
    )

    result = qa.check_script(with_source)

    assert result["warnings"] == []
