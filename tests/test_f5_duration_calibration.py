"""Regression coverage for the local F5 runtime calibration."""

from ytb_pipeline.voiceover import f5_provider


def test_f5_default_inference_speed_uses_the_e2e_duration_calibration():
    """Keep generated Long narration inside the strict measured-runtime gate.

    The isolated Long E2E fixture measured only 71.6s at 0.85, despite the
    script passing the 3-minute planning budget.  The documented safe floor
    is required so F5 produces natural-duration audio; runtime QA remains the
    authoritative backstop.
    """
    assert f5_provider.F5_INFERENCE_SPEED == 0.30
