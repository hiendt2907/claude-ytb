"""The long-form extension must not break the section cap it is repairing into.

A profile declares `max_sections`.  When a Long came back too thin, the repair
step asked the model for extra sections and appended all of them blindly, so the
extension pushed the script past the cap and the very next validation rejected
it — after two paid LLM calls.
"""

from __future__ import annotations

import pytest

from ytb_pipeline.orchestrator.ideation_script_fix import append_long_extension


def _payload(count: int) -> dict:
    return {
        "sections": [
            {"purpose": "situation", "voiceover": f"Câu mở {index}."}
            for index in range(count)
        ]
    }


def _extension(count: int) -> dict:
    return {
        "sections": [
            {"purpose": "evidence", "voiceover": f"Đoạn thêm {index}."}
            for index in range(count)
        ]
    }


def test_extension_below_the_cap_is_inserted_before_the_conclusion():
    merged = append_long_extension(_payload(4), _extension(2), max_sections=24)

    voiceovers = [section["voiceover"] for section in merged["sections"]]
    assert len(voiceovers) == 6
    assert voiceovers[-1] == "Câu mở 3."
    assert voiceovers[3:5] == ["Đoạn thêm 0.", "Đoạn thêm 1."]


def test_overflow_is_folded_into_text_instead_of_new_sections():
    """The extension exists to add characters; the cap must not discard them."""
    merged = append_long_extension(_payload(23), _extension(4), max_sections=24)

    sections = merged["sections"]
    assert len(sections) == 24
    combined = " ".join(section["voiceover"] for section in sections)
    for index in range(4):
        assert f"Đoạn thêm {index}." in combined


def test_no_cap_keeps_the_previous_behaviour():
    merged = append_long_extension(_payload(23), _extension(4))

    assert len(merged["sections"]) == 27


def test_extension_never_mutates_the_original_payload():
    original = _payload(4)

    append_long_extension(original, _extension(2), max_sections=24)

    assert len(original["sections"]) == 4


def test_full_script_at_the_cap_still_receives_the_extension_text():
    merged = append_long_extension(_payload(24), _extension(2), max_sections=24)

    assert len(merged["sections"]) == 24
    combined = " ".join(section["voiceover"] for section in merged["sections"])
    assert "Đoạn thêm 0." in combined and "Đoạn thêm 1." in combined


def test_story_profile_ignores_a_strategy_it_never_asked_for(tmp_path, monkeypatch):
    """`strategy` carries no meaning for a character-story profile.

    The prompt tells such a profile to omit it, but a model that adds a partial
    `strategy` anyway used to fail the loader on `strategy.hook` — rejecting a
    perfectly valid episode over a field its own contract does not use.
    """
    import json

    from ytb_pipeline.ideation.generator import load_script

    payload = json.loads(
        (
            __import__("pathlib").Path("profiles/ban-so-6/fixtures/episode-01-short.json")
        ).read_text(encoding="utf-8")
    )
    payload["strategy"] = {"format_id": "core_answer_first_v1"}  # no `hook`
    path = tmp_path / "story.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    script = load_script(path)

    assert script.strategy is None
