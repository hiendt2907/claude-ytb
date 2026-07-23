from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import make_script


def _brief() -> dict[str, str]:
    return {
        "visual_contradiction": "Mở laptop nhưng lại lướt điện thoại",
        "subject": "Người đi làm trước laptop",
        "emotion": "bối rối",
        "headline": "NÃO ĐANG TRỐN",
    }


def test_thumbnail_brief_enriches_a_script_without_mutating_the_original():
    from ytb_pipeline.pkg.models import Script, ThumbnailBrief

    script = Script(topic="Trì hoãn", title="Mở laptop", description="")
    brief = ThumbnailBrief(**_brief())

    enriched = replace(script, thumbnail_brief=brief)

    assert enriched.thumbnail_brief == brief
    assert script.thumbnail_brief is None


def test_thumbnail_brief_rejects_a_headline_with_more_than_four_words():
    from ytb_pipeline.pkg.models import ThumbnailBrief

    invalid = _brief() | {"headline": "ĐỪNG ĐỂ NÃO LỪA BẠN"}

    with pytest.raises(ValueError, match="4 từ"):
        ThumbnailBrief(**invalid)


def test_loader_hydrates_a_structured_thumbnail_brief(write_script):
    from ytb_pipeline.ideation.generator import CHARS_PER_MIN, load_script

    data = make_script([{"caption": "c", "voiceover": "x" * int(CHARS_PER_MIN)}])
    data["thumbnail_brief"] = _brief()

    script = load_script(write_script(data))

    assert script.thumbnail_brief is not None
    assert script.thumbnail_brief.visual_contradiction == _brief()["visual_contradiction"]
    assert script.thumbnail_brief.headline == "NÃO ĐANG TRỐN"


def test_loader_keeps_legacy_script_readable_when_thumbnail_brief_is_absent(write_script):
    from ytb_pipeline.ideation.generator import CHARS_PER_MIN, load_script

    data = make_script([{"caption": "c", "voiceover": "x" * int(CHARS_PER_MIN)}])

    assert load_script(write_script(data)).thumbnail_brief is None


@pytest.mark.parametrize(
    "brief",
    [
        "NÃO ĐANG TRỐN",
        {"subject": "Người đi làm", "emotion": "bối rối", "headline": "NÃO ĐANG TRỐN"},
    ],
)
def test_loader_rejects_a_present_but_incomplete_thumbnail_brief(write_script, brief):
    from ytb_pipeline.ideation.generator import CHARS_PER_MIN, load_script

    data = make_script([{"caption": "c", "voiceover": "x" * int(CHARS_PER_MIN)}])
    data["thumbnail_brief"] = brief

    with pytest.raises(ValueError, match="thumbnail_brief"):
        load_script(write_script(data))


def test_first_generation_prompt_requires_compact_thumbnail_brief_json():
    from ytb_pipeline.orchestrator.ideation_prompts import (
        SCRIPT_GENERATION_SYSTEM_PROMPT,
        local_script_prompt,
    )

    prompt = local_script_prompt(1, 1, "short", "auto", "")

    assert '"thumbnail_brief"' in prompt
    assert "visual_contradiction" in prompt
    assert "headline" in prompt
    assert "4 words" in prompt
    assert "thumbnail_brief" in SCRIPT_GENERATION_SYSTEM_PROMPT
