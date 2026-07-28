"""Regression coverage for the measured native-F5 planning rate."""

from pathlib import Path

import pytest

from ytb_pipeline.config.settings import settings
from ytb_pipeline.content_contract import contract_for
from ytb_pipeline.ideation.generator import chars_per_min_for_provider, load_script


FIXTURE = Path(__file__).parent / "fixtures" / "f5_e2e_long_calibrated.json"


def _require_e2e_contract() -> None:
    if not settings.e2e_test:
        pytest.skip("E2E-only Long fixture; run with E2E_TEST=true")


def test_f5_planning_rate_matches_measured_native_f5_pacing():
    # 3,276 prepared Vietnamese characters / 145.975 measured seconds =
    # 1,346.55 chars per minute; use the nearest whole character rate.
    assert chars_per_min_for_provider("f5") == 1347.0


def test_e2e_long_safe_character_window_uses_calibrated_f5_rate():
    _require_e2e_contract()

    contract = contract_for("long")
    assert contract.audio_runtime_bounds_sec(segment_count=8) == (182.8, 242.8)
    assert contract.safe_character_bounds(chars_per_minute=1347.0, segment_count=8) == (4193, 5271)


def test_calibrated_e2e_long_fixture_loads_inside_safe_character_window():
    _require_e2e_contract()

    script = load_script(FIXTURE)
    characters = sum(len(segment.narration) for segment in script.segments)
    minimum, maximum = contract_for("long").safe_character_bounds(
        chars_per_minute=chars_per_min_for_provider("f5"),
        segment_count=len(script.segments),
    )

    assert script.video_type == "long"
    assert script.target_minutes == 3
    assert len(script.segments) == 8
    assert minimum <= characters <= maximum
