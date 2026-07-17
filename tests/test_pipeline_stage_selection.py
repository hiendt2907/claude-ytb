"""Production stages are independently runnable after batch-start approval."""

from ytb_pipeline import pipeline


def test_voiceover_stage_runs_only_approved_input_and_voiceover():
    assert pipeline.stage_names("voiceover") == ("input", "voiceover")


def test_publish_stage_runs_the_full_production_chain():
    assert pipeline.stage_names("publish") == ("input", "voiceover", "render", "publish")
