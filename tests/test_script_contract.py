from __future__ import annotations

from copy import deepcopy

import pytest
from ytb_pipeline.content_contract import CONTRACT_VERSION


def _current_short_payload() -> dict:
    return {
        "ruleset_id": CONTRACT_VERSION,
        "video_type": "short",
        "thumbnail_brief": {
            "visual_contradiction": "A crowded desk beside one clear task.",
            "subject": "A distracted office worker.",
            "emotion": "Relief.",
            "headline": "Chọn một việc",
        },
        "strategy": {
            "format_id": "mechanism_short_v1",
            "core_mechanism": "decision overload",
            "audience_problem": "cannot start a task",
            "angle": "the hidden cost of options",
            "long_form_slug": "decision-overload",
            "playlist": "mechanisms",
            "cta_target": "decision-overload",
            "source_long_slug": "decision-overload",
            "source_section_index": 4,
            "source_excerpt": "Too many options delay the first action.",
            "hook": {
                "situation": "You open a long task list.",
                "core_answer": "Too many choices delay action.",
                "open_loop": "Here is how to spot it.",
                "answer_by_sec": 5,
            },
        },
        "sections": [
            {
                "narration": "You open a list and cannot choose the first task.",
                "purpose": "situation",
                "visual_intent": "Hand hovering over a long task list.",
                "pexels_query": "hand scrolling task list phone",
                "time_goal": 4,
            },
            {
                "narration": "Too many choices delay action.",
                "purpose": "core_answer",
                "visual_intent": "Person pauses before several doors.",
                "pexels_query": "person choosing between doors",
                "time_goal": 4,
            },
            {
                "narration": "Each extra option makes you compare again.",
                "purpose": "evidence",
                "visual_intent": "Sticky notes multiply on a desk.",
                "pexels_query": "sticky notes desk planning",
                "time_goal": 8,
            },
            {
                "narration": "That comparison happens when your energy is already low.",
                "purpose": "evidence",
                "visual_intent": "Tired person at a laptop.",
                "pexels_query": "tired worker laptop night",
                "time_goal": 8,
            },
            {
                "narration": "Choose one visible first action before the moment arrives.",
                "purpose": "application",
                "visual_intent": "A person writes one first step.",
                "pexels_query": "writing first step notebook",
                "time_goal": 8,
            },
            {
                "narration": "The full mechanism is in the linked long video.",
                "purpose": "payoff",
                "visual_intent": "Phone points to a related video.",
                "pexels_query": "phone related video screen",
                "time_goal": 8,
            },
        ],
    }


def test_current_payload_is_publishable_without_mutating_the_input():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    payload = _current_short_payload()
    before = deepcopy(payload)

    result = validate_script_payload(payload)

    assert result.profile == "current"
    assert result.publishable is True
    assert result.findings == ()
    assert payload == before


def test_current_contract_accepts_the_canonical_voiceover_key_from_the_generator_prompt():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    payload = _current_short_payload()
    for section in payload["sections"]:
        section["voiceover"] = section.pop("narration")

    assert validate_script_payload(payload).publishable is True


def test_legacy_payload_is_explicitly_nonpublishable_not_a_compatibility_pass():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    result = validate_script_payload({"video_type": "short", "sections": []})

    assert result.profile == "legacy"
    assert result.publishable is False
    assert {finding.rule for finding in result.findings} == {"ruleset_id.current"}


def test_current_payload_rejects_type_target_mismatch_and_missing_contract_fields():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    payload = _current_short_payload()
    payload["target_minutes"] = 12
    payload["thumbnail_brief"] = {"headline": "Missing the rest"}
    payload["sections"][2]["time_goal"] = True
    payload["sections"][3]["visual_intent"] = ""

    result = validate_script_payload(payload)

    assert result.publishable is False
    rules = {finding.rule for finding in result.findings}
    assert "target_minutes.short_absent" in rules
    assert "thumbnail_brief.subject.required" in rules
    assert "sections[2].time_goal.positive_number" in rules
    assert "sections[3].visual_intent.required" in rules


def test_short_contract_requires_minimum_sections_ordered_hook_and_source_trace():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    payload = _current_short_payload()
    payload["sections"] = payload["sections"][:5]
    payload["sections"][0]["purpose"] = "evidence"
    payload["strategy"]["source_long_slug"] = "different-long"
    payload["strategy"]["source_section_index"] = -1

    result = validate_script_payload(payload)

    rules = {finding.rule for finding in result.findings}
    assert "sections.minimum_count" in rules
    assert "sections.short_opening_order" in rules
    assert "strategy.source_long_slug.matches_long_form_slug" in rules
    assert "strategy.source_section_index.nonnegative_integer" in rules


@pytest.mark.parametrize(
    ("video_type", "target_minutes", "expected_rule"),
    [
        ("long", None, "target_minutes.long_required"),
        ("long", 10, "target_minutes.long_within_contract"),
        ("other", None, "video_type.supported"),
    ],
)
def test_video_type_and_target_follow_the_content_contract(video_type, target_minutes, expected_rule):
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    payload = _current_short_payload()
    payload["video_type"] = video_type
    if target_minutes is None:
        payload.pop("target_minutes", None)
    else:
        payload["target_minutes"] = target_minutes

    result = validate_script_payload(payload)

    assert expected_rule in {finding.rule for finding in result.findings}
