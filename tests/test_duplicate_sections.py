"""No script may ship the same narration twice.

The long-form repair step asks the model for extra sections when a Long comes
back thin.  A real run answered by re-emitting the opening verbatim: sections
16-22 were byte-identical to sections 0-6.  Every gate passed — duration, section
count, purposes, preflight — because none of them compares sections to each
other, so the video would have replayed its first two minutes.
"""

from __future__ import annotations

from ytb_pipeline.ideation.script_contract import validate_script_payload


def _payload(voiceovers) -> dict:
    return {
        "ruleset_id": "2026-07-28.1",
        "video_type": "short",
        "title": "t",
        "topic": "x",
        "sections": [
            {
                "purpose": "situation",
                "voiceover": text,
                "visual_intent": "v",
                "pexels_query": "office desk",
                "caption": "c",
                "time_goal": 0.2,
            }
            for text in voiceovers
        ],
    }


def _rules(payload) -> set[str]:
    return {finding.rule for finding in validate_script_payload(payload).findings}


def test_identical_sections_are_rejected():
    line = "Sáu giờ bảy phút, Minh đẩy cửa bước vào quán và đặt túi canvas xuống ghế."

    assert "sections.duplicate" in _rules(_payload([line, "Một câu khác hẳn.", line]))


def test_sections_differing_only_in_whitespace_and_case_are_still_duplicates():
    line = "Sáu giờ bảy phút, Minh đẩy cửa bước vào quán và đặt túi canvas xuống ghế."

    payload = _payload([line, "  sáu GIỜ bảy phút,  Minh đẩy cửa bước vào quán và đặt túi canvas xuống ghế. "])

    assert "sections.duplicate" in _rules(payload)


def test_distinct_sections_pass():
    payload = _payload([
        "Sáu giờ bảy phút, Minh đẩy cửa bước vào quán và đặt túi canvas xuống ghế.",
        "Bảy giờ mười tám, file vẫn trống còn tờ giấy thì đã kín chữ.",
    ])

    assert "sections.duplicate" not in _rules(payload)


def test_a_short_repeated_refrain_is_not_treated_as_a_duplicate_section():
    """Deliberate repetition of a short beat is a style choice, not a defect."""
    payload = _payload([
        "Minh mở laptop.",
        "Bảy giờ mười tám, file vẫn trống còn tờ giấy thì đã kín chữ.",
        "Minh mở laptop.",
    ])

    assert "sections.duplicate" not in _rules(payload)
