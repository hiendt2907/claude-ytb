import pytest


def test_short_contract_budgets_audio_for_transition_loss_but_keeps_viewer_runtime():
    from ytb_pipeline.content_contract import contract_for

    contract = contract_for("short")

    assert contract.viewer_runtime_bounds_sec == (60.0, 90.0)
    assert contract.audio_runtime_bounds_sec(segment_count=6) == (62.0, 92.0)
    contract.validate_audio_runtime(62.0, segment_count=6)
    contract.validate_viewer_runtime(60.0)
    with pytest.raises(ValueError, match="Short quá ngắn"):
        contract.validate_audio_runtime(61.9, segment_count=6)


def test_long_contract_has_one_12_to_15_minute_viewer_standard_across_stages():
    from ytb_pipeline.content_contract import contract_for

    contract = contract_for("long")

    assert contract.viewer_runtime_bounds_sec == (720.0, 900.0)
    assert contract.minimum_sections == 24
    contract.validate_audio_runtime(729.2, segment_count=24)
    contract.validate_viewer_runtime(720.0)
    with pytest.raises(ValueError, match="Long quá ngắn"):
        contract.validate_viewer_runtime(719.9)


def test_contract_is_the_single_source_for_hook_deadline_and_prompt_budget():
    from ytb_pipeline.content_contract import contract_for

    contract = contract_for("short")

    assert contract.answer_start_target_sec == 4.0
    assert contract.answer_start_deadline_sec == 5.0
    assert contract.situation_max_chars == 120
    assert contract.safe_character_bounds(chars_per_minute=2000.0, segment_count=6) == (2200, 2800)
