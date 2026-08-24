from __future__ import annotations

import json

import pytest


def test_process_and_sanitize_heals_quotes_slug_hook_outro_and_stage_directions():
    from ytb_pipeline.ideation.wording_engine import process_and_sanitize

    raw = '''{"slug":"Nguy hiểm của việc cố gắng quá mức", "sec_1":{"narration_text":"Bạn có biết? [Pause] Bạn đang bỏ qua tín hiệu này.", "purpose":"situation"}, "sec_6":{"narration_text":"Bạn còn chần chừ gì nữa? Hãy để lại bình luận nhé!", "purpose":"payoff"}, "claim":"Câu có "đền bù" bên trong"}'''

    result = process_and_sanitize(raw)

    assert result["slug"] == "nguy-hiem-cua-viec-co-gang-qua-muc"
    assert result["sec_1"]["narration_text"].startswith("Bạn đang bỏ qua")
    assert "[Pause]" not in result["sec_1"]["narration_text"]
    assert "Bạn còn chần chừ gì nữa" not in result["sec_6"]["narration_text"]
    assert len(result["sec_6"]["narration_text"].split()) < 12
    assert result["claim"] == 'Câu có "đền bù" bên trong'
    assert result["_wording_engine"]["encoding_valid"] is True


def test_process_and_sanitize_never_invents_long_source_provenance():
    from ytb_pipeline.ideation.wording_engine import process_and_sanitize

    result = process_and_sanitize(
        '''{"strategy":{"long_form_slug":"long-a"},"sections":[
        {"purpose":"situation","voiceover":"Một tình huống có dấu."}
        ]}'''
    )

    assert result["strategy"]["long_form_slug"] == "long-a"
    assert "source_section_index" not in result["strategy"]
    assert "source_excerpt" not in result["strategy"]


def test_process_and_sanitize_handles_pipeline_sections_and_removes_all_stage_cues():
    from ytb_pipeline.ideation.wording_engine import process_and_sanitize

    raw = json.dumps({
        "slug": "co-che-moi",
        "sections": [
            {"purpose": "situation", "voiceover": "Thực ra, [camera zoom] bạn đang né sự mơ hồ."},
            {"purpose": "core_answer", "voiceover": "Đây là câu trả lời."},
            {"purpose": "payoff", "voiceover": "Hãy thử ngay hôm nay."},
        ],
    }, ensure_ascii=False)

    result = process_and_sanitize(raw)

    assert result["sections"][0]["voiceover"].startswith("Bạn đang né")
    assert "[camera zoom]" not in result["sections"][0]["voiceover"]


def test_process_and_sanitize_flags_ascii_only_vietnamese_narration():
    from ytb_pipeline.ideation.wording_engine import process_and_sanitize

    result = process_and_sanitize(json.dumps({
        "slug": "test",
        "sections": [{"narration_text": "Ban dang tri hoan cong viec."}],
    }))

    assert result["_wording_engine"]["encoding_valid"] is False
    assert "MISSING_VIETNAMESE_DIACRITICS" in result["_wording_engine"]["flags"]


def test_process_and_sanitize_rejects_non_object_json():
    from ytb_pipeline.ideation.wording_engine import process_and_sanitize

    with pytest.raises(ValueError, match="object"):
        process_and_sanitize("[1, 2, 3]")


def test_process_and_sanitize_rejects_non_object_sections_before_downstream_qa():
    from ytb_pipeline.ideation.wording_engine import process_and_sanitize

    raw = json.dumps({
        "slug": "test",
        "video_type": "short",
        "sections": [
            {"purpose": "situation", "voiceover": "Bạn đang né việc khó."},
            "Đây là một section bị hỏng.",
        ],
    }, ensure_ascii=False)

    with pytest.raises(ValueError, match="sections\[1\].*object"):
        process_and_sanitize(raw)
