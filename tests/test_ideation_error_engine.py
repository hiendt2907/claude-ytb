from __future__ import annotations

import json


def test_classifies_hook_and_central_mechanism_failures():
    from ytb_pipeline.orchestrator.ideation_error_engine import classify_ideation_failure

    assert classify_ideation_failure(None, {"violations": [{"rule": "hook"}]}) == "QA_HOOK_WEAK"
    assert classify_ideation_failure(None, {"violations": [{"rule": "central_mechanism"}]}) == "QA_CENTRAL_MECHANISM"


def test_semantic_duplicate_requires_a_new_mechanism_not_a_paraphrase():
    from ytb_pipeline.orchestrator.ideation_error_engine import (
        classify_ideation_failure,
        recovery_directive,
    )

    qa = {
        "violations": [
            {
                "rule": "series_semantic_dedup",
                "detail": "topic too close to an existing Short",
            }
        ]
    }

    assert classify_ideation_failure(None, qa) == "QA_SERIES_SEMANTIC_DEDUP"
    directive = recovery_directive(None, qa)
    assert "Replace the title, topic, and all narration" in directive
    assert "paraphrase" in directive


def test_terminal_quality_failure_keeps_rejected_payload_for_batch_replacement():
    from ytb_pipeline.orchestrator.ideation_script_fix import IdeationQualityFailure

    payload = {"slug": "rejected", "title": "Rejected topic"}
    error = IdeationQualityFailure("QA failed", payload)

    assert str(error) == "QA failed"
    assert error.payload is payload


def test_records_structured_failure_event(tmp_path):
    from ytb_pipeline.orchestrator.ideation_error_engine import record_ideation_failure

    report = tmp_path / "ideation_errors.jsonl"
    record_ideation_failure(
        report,
        script_name="failed-script.json",
        attempt=3,
        validation_error=None,
        qa={"violations": [{"rule": "hook", "detail": "weak"}]},
    )

    event = json.loads(report.read_text(encoding="utf-8"))
    assert event["code"] == "QA_HOOK_WEAK"
    assert event["script"] == "failed-script.json"
    assert event["attempt"] == 3


def test_invalid_json_gets_a_stable_recovery_code():
    from ytb_pipeline.orchestrator.ideation_error_engine import (
        classify_ideation_failure,
        recovery_directive,
    )

    error = "LLM không trả JSON hợp lệ: Unterminated string"

    assert classify_ideation_failure(error, None) == "IDEATION_JSON_INVALID"
    assert "Regenerate one complete JSON candidate" in recovery_directive(error, None)


def test_invalid_json_regeneration_budget_is_once_per_candidate():
    from ytb_pipeline.orchestrator.ideation_cmd import reserve_invalid_json_regeneration

    attempts: dict[int, int] = {}

    assert reserve_invalid_json_regeneration(attempts, 1) is True
    assert reserve_invalid_json_regeneration(attempts, 1) is False
    assert reserve_invalid_json_regeneration(attempts, 2) is True
