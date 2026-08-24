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
    # The hook budget is derived from the active narration rate, not a literal:
    # 2,000 cpm x 4.0s = 133 characters.
    assert contract.situation_char_budget(chars_per_minute=2000.0) == 133
    # Margins are a fraction of each bound, so they stay meaningful at Short and
    # Long scale alike: 62s x 1.05 and 92s x 0.94 at 2,000 cpm.
    assert contract.safe_character_bounds(chars_per_minute=2000.0, segment_count=6) == (2170, 2882)


def test_xkiro_safe_character_window_never_estimates_past_audio_contract_ceiling():
    """The generator target must be safe before an xKiro TTS call is paid for."""
    from ytb_pipeline.content_contract import (
        XKIRO_CHARS_PER_MIN,
        contract_for,
        estimate_duration_sec,
    )

    contract = contract_for("short")
    minimum, maximum = contract.safe_character_bounds(
        chars_per_minute=XKIRO_CHARS_PER_MIN,
        segment_count=contract.minimum_sections,
    )
    lower, upper = contract.audio_runtime_bounds_sec(
        segment_count=contract.minimum_sections,
    )

    assert lower <= estimate_duration_sec(minimum, chars_per_minute=XKIRO_CHARS_PER_MIN)
    assert estimate_duration_sec(maximum, chars_per_minute=XKIRO_CHARS_PER_MIN) <= upper


@pytest.mark.parametrize("chars_per_minute", [1030.0, 1347.0, 1604.0])
def test_situation_budget_never_pushes_the_answer_past_the_hard_deadline(chars_per_minute):
    """A situation written to the stated budget must still clear the 5s gate.

    The Edge-era literal 120 silently contradicted this for xKiro and F5: a model
    that obeyed the prompt was still rejected by `_validate_short_strategy_structure`.
    """
    from ytb_pipeline.content_contract import contract_for, estimate_duration_sec

    contract = contract_for("short")
    budget = contract.situation_char_budget(chars_per_minute=chars_per_minute)

    assert budget > 0
    assert estimate_duration_sec(budget, chars_per_minute=chars_per_minute) <= (
        contract.answer_start_deadline_sec
    )


@pytest.mark.parametrize("chars_per_minute", [1030.0, 1347.0, 1604.0])
def test_situation_budget_keeps_margin_before_the_hard_gate(chars_per_minute):
    """Planning aims at the target, so a slightly long hook still lands inside."""
    from ytb_pipeline.content_contract import contract_for, estimate_duration_sec

    contract = contract_for("short")
    budget = contract.situation_char_budget(chars_per_minute=chars_per_minute)

    assert estimate_duration_sec(budget, chars_per_minute=chars_per_minute) <= (
        contract.answer_start_target_sec
    )


def test_ideation_prompt_states_the_active_situation_budget_not_a_stale_literal():
    """The prompt is what the model obeys, so it must carry the derived number."""
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.content_contract import chars_per_min_for_provider, contract_for
    from ytb_pipeline.orchestrator import ideation_prompts

    budget = contract_for("short").situation_char_budget(
        chars_per_minute=chars_per_min_for_provider(settings.tts_provider),
    )

    assert f"{budget}" in ideation_prompts.SCRIPT_GENERATION_SYSTEM_PROMPT


def test_xkiro_long_narration_rate_is_measured_separately_from_short():
    """A Long spoke 7.6% faster than a Short, so one rate cannot serve both.

    Measured 2026-08-24: Short 1,398 chars in 81.34s (1,031 cpm); Long 13,282
    chars in 718.6s (1,109 cpm).  Planning a Long at the Short rate produced
    718.6s of audio against a 730s floor and failed at the voiceover boundary.
    """
    from ytb_pipeline.content_contract import chars_per_min_for_provider

    short_rate = chars_per_min_for_provider("xkiro", video_type="short")
    long_rate = chars_per_min_for_provider("xkiro", video_type="long")

    assert long_rate > short_rate


@pytest.mark.parametrize("video_type", ["short", "long"])
def test_safety_margin_scales_with_the_contract_window(video_type):
    """A fixed second-count margin is 16% of a Short floor but 1.4% of a Long one."""
    from ytb_pipeline.content_contract import chars_per_min_for_provider, contract_for

    contract = contract_for(video_type)
    lower, upper = contract.audio_runtime_bounds_sec(
        segment_count=contract.minimum_sections,
    )
    rate = chars_per_min_for_provider("xkiro", video_type=video_type)
    minimum, maximum = contract.safe_character_bounds(
        chars_per_minute=rate, segment_count=contract.minimum_sections,
    )

    head_room = minimum / rate * 60 - lower
    tail_room = upper - maximum / rate * 60

    assert head_room / lower == pytest.approx(tail_room / upper, rel=0.35)
    assert head_room / lower >= 0.03


@pytest.mark.parametrize("video_type", ["short", "long"])
def test_planning_floor_survives_the_measured_narration_rate(video_type):
    """The regression that shipped a 718.6s Long against a 730s floor.

    A script written to the bottom of the prompt target must still clear the
    contract floor once the provider actually speaks it.
    """
    from ytb_pipeline.content_contract import (
        chars_per_min_for_provider,
        contract_for,
        estimate_duration_sec,
    )

    contract = contract_for(video_type)
    rate = chars_per_min_for_provider("xkiro", video_type=video_type)
    lower, upper = contract.audio_runtime_bounds_sec(
        segment_count=contract.minimum_sections,
    )
    minimum, maximum = contract.safe_character_bounds(
        chars_per_minute=rate, segment_count=contract.minimum_sections,
    )

    contract.validate_audio_runtime(
        estimate_duration_sec(minimum, chars_per_minute=rate),
        segment_count=contract.minimum_sections,
    )
    contract.validate_audio_runtime(
        estimate_duration_sec(maximum, chars_per_minute=rate),
        segment_count=contract.minimum_sections,
    )


@pytest.mark.parametrize("video_type,segment_count", [("short", 6), ("long", 36)])
def test_audio_quality_target_agrees_with_the_content_contract(video_type, segment_count):
    """Two duration authorities must not disagree about the same audio file.

    The voiceover node validates against `audio_runtime_bounds_sec`, while the
    audio quality gate compared the same file against `target_minutes * 60` — a
    viewer-domain number that ignores transition loss.  For a 36-section Long the
    two windows overlapped by 16s out of 180s, and a script planned to the middle
    of the contract failed the second gate every time.
    """
    from ytb_pipeline.content_contract import contract_for
    from ytb_pipeline.voiceover.quality import audio_duration_target_sec

    contract = contract_for(video_type)
    lower, upper = contract.audio_runtime_bounds_sec(segment_count=segment_count)
    target, tolerance = audio_duration_target_sec(
        video_type, segment_count=segment_count,
    )

    assert target - tolerance <= lower
    assert upper <= target + tolerance


@pytest.mark.parametrize("video_type", ["short", "long"])
def test_prompt_states_every_purpose_the_prepublish_gate_requires(video_type):
    """The gate and the prompt must name the same required section purposes.

    `_REQUIRED_PURPOSES["long"]` has always demanded situation and core_answer,
    but the sentence naming them sat inside a block opening "Every newly
    generated Short MUST...", so Long generations never applied it: 0 of 28
    archived Long scripts satisfy the gate, and a finished 14-minute render was
    blocked at the publish node for a missing core_answer section.
    """
    from ytb_pipeline.analytics.quality_report import _REQUIRED_PURPOSES
    from ytb_pipeline.orchestrator import ideation_prompts

    prompt = ideation_prompts.SCRIPT_GENERATION_SYSTEM_PROMPT
    marker = "Short" if video_type == "short" else "Long"
    scoped = [
        line for line in prompt.splitlines()
        if marker in line and "purpose" in line
    ]

    assert scoped, f"prompt không có dòng nào nêu purpose cho {marker}"
    named = " ".join(scoped)
    for purpose in _REQUIRED_PURPOSES[video_type]:
        assert purpose in named
