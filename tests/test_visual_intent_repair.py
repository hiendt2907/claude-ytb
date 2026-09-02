"""Sửa hẹp cho `unrenderable_visual_intent`.

Ba luật trong `_UNRENDERABLE_VISUAL_INTENT` đã được nêu rõ trong prompt sinh
kịch bản, nhưng model vẫn vi phạm — docstring của chính cổng đó ghi nhận điều
này ("nêu luật không đủ"). Cái chưa có là hệ quả: `hook` và
`narrator_reflection` đều có đường sửa hẹp, còn luật này thì không, nên MỘT
mệnh đề sai trong MỘT section giết cả lượt sinh vài phút.

Đo trên log production thật (2026-09-01..02, đã lọc bỏ log test): 3 trong 5
lượt bị từ chối thuộc đúng lớp này. Đó là chi phí đang làm Gate 1 không về
đích, không phải chất lượng nội dung.

`visual_intent` KHÔNG phải lời đọc. Viết lại nó không đụng vào narration, nên
thanh biên tập 9/10 và mọi thứ khán giả nghe được giữ nguyên. Cổng vẫn
fail-closed: bản sửa phải tự qua lại cổng, không được cấp phép đặc biệt.
"""

from __future__ import annotations

import pytest


def _payload_with_unrenderable_intents() -> dict:
    return {
        "slug": "minh-noi-chua-xac-nhan",
        "title": "Minh nói chưa xác nhận",
        "topic": "Một lựa chọn trước cuộc họp",
        "video_type": "long",
        "sections": [
            {
                "purpose": "hook",
                "time_goal": 0.5,
                "voiceover": "Sáu giờ mười lăm, quán chưa có ai khác.",
                "visual_intent": "Minh ngồi ở bàn số 6, ánh sáng sớm qua cửa kính.",
            },
            {
                "purpose": "beat",
                "time_goal": 0.5,
                "voiceover": "An đặt tách cà phê xuống.",
                "visual_intent": "An tay cầm khay gỗ đi tới bàn số 6.",
            },
            {
                "purpose": "beat",
                "time_goal": 0.5,
                "voiceover": "Minh nhìn vào bản kế hoạch.",
                "visual_intent": "Màn hình hiện dòng cảnh báo màu vàng.",
            },
        ],
    }


def _as_qa_script(payload: dict) -> dict:
    """Hình dạng QAAgent đọc: `segments`, không phải `sections`.

    `generator._section_to_segment` chép thẳng `visual_intent` sang, nên hai
    hình dạng mang cùng một chuỗi — test này chỉ đổi tên khoá, không đổi dữ
    liệu, để cổng và bản sửa vẫn nói về đúng một thứ.
    """
    return {**payload, "segments": payload["sections"]}


def test_qa_gate_still_rejects_both_offending_sections():
    """Điểm neo: cổng phải chỉ đúng section nào hỏng, để bản sửa nhắm đúng chỗ."""
    from ytb_pipeline.agents.qa_agent import _check_unrenderable_visual_intent

    violations = _check_unrenderable_visual_intent(
        _as_qa_script(_payload_with_unrenderable_intents())
    )

    assert len(violations) == 2
    details = " ".join(v["detail"] for v in violations)
    assert "Section 2" in details
    assert "Section 3" in details
    assert "Section 1" not in details


def test_repair_prompt_asks_only_for_the_flagged_sections():
    """Sửa hẹp: đủ ngữ cảnh để viết lại, nhưng chỉ được trả về section bị gắn cờ.

    Cùng kỷ luật với `hook_repair_prompt` — một delta JSON nhỏ, mọi field khác
    đi thẳng qua, để một lần sửa hình không bao giờ thành viết lại cả kịch bản.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import visual_intent_repair_prompt

    prompt = visual_intent_repair_prompt(
        _payload_with_unrenderable_intents(),
        section_indexes=(2, 3),
    )

    assert '"section_index"' in prompt
    assert '"visual_intent"' in prompt
    # Ngữ cảnh: section hỏng phải có mặt để model biết cảnh đang kể gì.
    assert "tay cầm khay gỗ" in prompt
    assert "dòng cảnh báo" in prompt
    # Ba luật phải được nêu lại ngay tại điểm sửa, không chỉ ở prompt gốc.
    lowered = prompt.casefold()
    assert "readable" in lowered
    assert "hand" in lowered
    # Lời đọc được đưa vào làm NGỮ CẢNH (model phải biết cảnh nằm dưới câu nào),
    # nhưng schema trả về chỉ được có hai khoá — không có đường nào để bản sửa
    # hình chạm vào narration.
    assert '"voiceover": "An đặt tách cà phê xuống."' in prompt
    schema_line = next(ln for ln in prompt.splitlines() if "Return ONLY" in ln)
    assert "voiceover" not in schema_line
    assert "section_index" in schema_line and "visual_intent" in schema_line


def test_repair_replaces_only_visual_intent_of_named_sections():
    from ytb_pipeline.orchestrator.ideation_script_fix import apply_visual_intent_repair

    payload = _payload_with_unrenderable_intents()
    repaired = apply_visual_intent_repair(
        payload,
        {
            "sections": [
                {"section_index": 2, "visual_intent": "An đứng cạnh bàn số 6, khay gỗ đặt trên mặt bàn."},
                {"section_index": 3, "visual_intent": "Minh ngồi trước laptop mở, ánh sáng hắt lên mặt."},
            ]
        },
    )

    assert repaired["sections"][1]["visual_intent"].startswith("An đứng cạnh bàn")
    assert repaired["sections"][2]["visual_intent"].startswith("Minh ngồi trước laptop")
    # Lời đọc, tiêu đề, số section: không đổi.
    assert repaired["sections"][1]["voiceover"] == payload["sections"][1]["voiceover"]
    assert repaired["sections"][2]["voiceover"] == payload["sections"][2]["voiceover"]
    assert repaired["title"] == payload["title"]
    assert len(repaired["sections"]) == len(payload["sections"])
    # Bản gốc không bị mutate.
    assert payload["sections"][1]["visual_intent"] == "An tay cầm khay gỗ đi tới bàn số 6."


def test_repaired_script_passes_the_gate_that_rejected_it():
    """Vòng khép kín: bản sửa phải tự qua cổng, không được miễn trừ."""
    from ytb_pipeline.agents.qa_agent import _check_unrenderable_visual_intent
    from ytb_pipeline.orchestrator.ideation_script_fix import apply_visual_intent_repair

    repaired = apply_visual_intent_repair(
        _payload_with_unrenderable_intents(),
        {
            "sections": [
                {"section_index": 2, "visual_intent": "An đứng cạnh bàn số 6, khay gỗ đặt trên mặt bàn."},
                {"section_index": 3, "visual_intent": "Minh ngồi trước laptop mở, ánh sáng hắt lên mặt."},
            ]
        },
    )

    assert _check_unrenderable_visual_intent(_as_qa_script(repaired)) == []


def test_repair_rejects_a_delta_that_is_still_unrenderable():
    """Không nhận bản sửa vẫn vi phạm — nếu không, vòng lặp sẽ 'sửa' mãi mà
    cổng vẫn chặn, đốt hết ngân sách vào cùng một lỗi."""
    from ytb_pipeline.orchestrator.ideation_script_fix import apply_visual_intent_repair

    with pytest.raises(ValueError, match="vẫn vi phạm"):
        apply_visual_intent_repair(
            _payload_with_unrenderable_intents(),
            {"sections": [{"section_index": 2, "visual_intent": "An tay cầm khay gỗ."}]},
        )


def test_repair_rejects_an_out_of_range_or_empty_delta():
    from ytb_pipeline.orchestrator.ideation_script_fix import apply_visual_intent_repair

    with pytest.raises(ValueError):
        apply_visual_intent_repair(_payload_with_unrenderable_intents(), {"sections": []})

    with pytest.raises(ValueError):
        apply_visual_intent_repair(
            _payload_with_unrenderable_intents(),
            {"sections": [{"section_index": 99, "visual_intent": "Minh ngồi ở bàn số 6."}]},
        )
