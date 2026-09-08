"""A model that wraps its JSON in a markdown fence must not be treated as broken.

`json_from_llm` has stripped ```json fences for a long time, but
`process_and_sanitize` — which runs FIRST, on every fresh candidate — parsed the
raw text directly.  So a model whose only sin was fencing its output had its
whole response discarded and a full regeneration paid for, even though the JSON
inside was valid.
"""

from __future__ import annotations

import json

import pytest

from ytb_pipeline.ideation.wording_engine import process_and_sanitize


def _payload() -> dict:
    return {
        "slug": "bay-lan-mo-laptop",
        "title": "Bảy lần mở laptop",
        "topic": "Cơ chế chuẩn bị",
        "video_type": "short",
        "sections": [
            {"purpose": "situation", "voiceover": "Sáu giờ bảy, Minh mở laptop rồi đóng lại."},
        ],
    }


@pytest.mark.parametrize("fence", ["```json\n{body}\n```", "```\n{body}\n```", "```JSON\n{body}\n```"])
def test_fenced_response_is_parsed(fence):
    text = fence.format(body=json.dumps(_payload(), ensure_ascii=False))

    result = process_and_sanitize(text)

    assert result["slug"] == "bay-lan-mo-laptop"


def test_unfenced_response_still_works():
    result = process_and_sanitize(json.dumps(_payload(), ensure_ascii=False))

    assert result["slug"] == "bay-lan-mo-laptop"


def test_prose_before_a_fence_is_tolerated():
    body = json.dumps(_payload(), ensure_ascii=False)
    text = f"Đây là kịch bản bạn yêu cầu:\n```json\n{body}\n```"

    assert process_and_sanitize(text)["slug"] == "bay-lan-mo-laptop"


def test_text_that_is_not_json_at_all_still_fails():
    with pytest.raises(ValueError):
        process_and_sanitize("xin lỗi, tôi không thể làm việc này")


def test_replacement_characters_anywhere_fail_the_encoding_gate():
    """Byte hỏng từ gateway thành U+FFFD rồi đi tiếp như text bình thường.

    `xkiro_provider` giải mã bằng `decode("utf-8", "replace")`, nên một token bị
    cắt giữa chuỗi nhiều byte biến thành "Năm l��n" và chạy tiếp. Lớp
    tất định trước đây chỉ bắt "mất dấu tiếng Việt" và chỉ soi
    narration/voiceover, nên mojibake trong `caption` lọt hết — chỉ có rubric
    LLM bắt được, mà rubric là lớp sai cho một lỗi cơ học (§38): nó không tất
    định và có thể chấm khác ở lượt sau.
    """
    payload = json.dumps({
        "slug": "nam-lan-do-chuong",
        "title": "Năm Lần Đổ Chuông",
        "sections": [
            {
                "caption": "Năm l��n đổ chuông trước giờ họp",
                "voiceover": "Cậu gọi năm lần nhưng không ai xác nhận con số.",
            },
        ],
    }, ensure_ascii=False)

    result = process_and_sanitize(payload)

    meta = result["_wording_engine"]
    assert meta["encoding_valid"] is False
    assert "REPLACEMENT_CHARACTER" in meta["flags"]


def test_clean_vietnamese_still_passes_the_encoding_gate():
    payload = json.dumps({
        "slug": "nam-lan-do-chuong",
        "title": "Năm Lần Đổ Chuông",
        "sections": [
            {
                "caption": "Năm lần đổ chuông trước giờ họp",
                "voiceover": "Cậu gọi năm lần nhưng không ai xác nhận con số.",
            },
        ],
    }, ensure_ascii=False)

    result = process_and_sanitize(payload)

    assert result["_wording_engine"]["encoding_valid"] is True
    assert "REPLACEMENT_CHARACTER" not in result["_wording_engine"]["flags"]
