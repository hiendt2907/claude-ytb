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


def test_extension_can_choose_a_timeline_safe_insertion_boundary():
    """An extension may belong before an existing time jump, not the ending."""
    source = {
        "sections": [
            {"purpose": "situation", "voiceover": "Sáu giờ sáng."},
            {"purpose": "payoff", "voiceover": "Cuộc họp kết thúc."},
            {"purpose": "payoff", "voiceover": "Sáng hôm sau."},
            {"purpose": "payoff", "voiceover": "Bàn trống."},
        ]
    }
    result = append_long_extension(
        source,
        {
            "insert_before_section_index": 2,
            "sections": [{"purpose": "evidence", "voiceover": "Một việc xảy ra sau cuộc họp."}],
        },
    )

    assert [section["voiceover"] for section in result["sections"]] == [
        "Sáu giờ sáng.",
        "Một việc xảy ra sau cuộc họp.",
        "Cuộc họp kết thúc.",
        "Sáng hôm sau.",
        "Bàn trống.",
    ]


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


def test_long_only_story_profile_rejects_new_short_generation_but_reads_archives(tmp_path):
    """Long-only restricts ideation, never an archived artifact reader."""
    import json

    from ytb_pipeline.ideation.generator import load_script

    payload = json.loads(
        (
            __import__("pathlib").Path("profiles/ban-so-6/fixtures/episode-01-short.json")
        ).read_text(encoding="utf-8")
    )
    from ytb_pipeline.content_profiles import load_content_profile
    payload["profile_version"] = "2.0.0"
    path = tmp_path / "story.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    import pytest
    from ytb_pipeline.content_profiles import ContentProfileError
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    assert load_script(path).video_type == "short"
    with pytest.raises(ContentProfileError, match="không cho sinh short"):
        local_script_prompt(
            1,
            1,
            "short",
            "auto",
            "",
            content_profile=load_content_profile("ban-so-6", version="2.0.0"),
        )
