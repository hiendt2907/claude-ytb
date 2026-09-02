"""Rewrite biên tập của Long phải mang ràng buộc độ dài, như Short đã có.

Comment ngay trên `length_guard` trong `editorial_rewrite_prompt` đã nói đúng
vấn đề: "An editorial rewrite may resize several sections at once, so it is the
likeliest of all the repairs to move the whole-script total past the duration
gate." Nhưng helper nó gọi — `_short_total_length_bounds` — trả `None` cho mọi
payload không phải Short, nên một Long chưa bao giờ nhận ngân sách đó.

Đo thật, ideation 2026-09-02 19:33: Long viết ra 217.4s, `extend` kéo lên,
rewrite biên tập chạy hai lượt với `repair_brief` tự bảo "cắt bớt hoặc nén mục
11" mà không có sàn nào, và lượt cuối chết ở 278.1s trên sàn 297.0s — thiếu 19
giây. Cả một lượt sinh 16 phút mất vì bản sửa không biết mình đang cắt vào đâu.

Cổng thời lượng không đổi. Thứ đổi là bản sửa được cho biết hai đầu ngân sách
trước khi viết, thay vì bị chấm sau khi đã viết xong.
"""

from __future__ import annotations

import re

import pytest


def _long_payload() -> dict:
    """Long 6 section, mỗi section ~600 ký tự — dưới sàn, đúng tình huống thật."""
    body = "Minh ngồi xuống bàn số 6 và mở laptop ra như mọi sáng. " * 11
    return {
        "profile_id": "ban-so-6",
        "video_type": "long",
        "slug": "cau-hoi-ngoai-hanh-lang",
        "title": "Câu hỏi ngoài hành lang",
        "sections": [
            {"purpose": "situation", "voiceover": body},
            {"purpose": "core_answer", "voiceover": body},
            {"purpose": "evidence", "voiceover": body},
            {"purpose": "application", "voiceover": body},
            {"purpose": "evidence", "voiceover": body},
            {"purpose": "payoff", "voiceover": body},
        ],
    }


class _Review:
    overall_score = 5
    dimension_scores = {
        "human_truth": 6, "spoken_naturalness": 5,
        "causal_coherence": 5, "role_fidelity": 4, "useful_restraint": 5,
    }
    section_refs = (2, 5)
    blocking_findings = ("An phân tích động cơ như chuyên gia.",)
    repair_brief = "Cắt bớt hoặc nén mục 5; An chỉ hỏi ngắn từ điều cô thấy."


def test_long_editorial_rewrite_states_both_ends_of_the_length_budget():
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    prompt = editorial_rewrite_prompt(_long_payload(), _Review())

    assert "LENGTH BUDGET" in prompt
    lowered = prompt.casefold()
    # Hai đầu, không phải một. Chỉ nêu sàn thì bản sửa vọt qua trần.
    assert "between" in lowered
    assert "both ends are rejected" in lowered


def test_budget_is_computed_against_the_sections_left_untouched():
    """Bản sửa chỉ trả về section được trích dẫn, nên ngân sách của nó là
    tổng trừ đi phần không đụng tới — giống hệt cách hook repair tính."""
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    payload = _long_payload()
    prompt = editorial_rewrite_prompt(payload, _Review())

    untouched = sum(
        len(section["voiceover"])
        for index, section in enumerate(payload["sections"], start=1)
        if index not in {2, 5}
    )
    assert str(untouched) in prompt


def test_repair_brief_asking_to_shorten_does_not_override_the_floor():
    """`repair_brief` do chính reviewer viết và có thể bảo 'cắt bớt'. Ngân sách
    phải thắng — đó là lý do nó được đánh dấu overrides."""
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    prompt = editorial_rewrite_prompt(_long_payload(), _Review())

    assert "Cắt bớt hoặc nén mục 5" in prompt  # vẫn truyền nguyên văn
    budget_at = prompt.index("LENGTH BUDGET")
    brief_at = prompt.index("Cắt bớt hoặc nén mục 5")
    assert budget_at > brief_at, "ngân sách phải đứng sau và ghi đè lời cắt bớt"
    assert "overrides any conflicting repair wording" in prompt[budget_at - 120:budget_at + 120]


def test_short_budget_is_unchanged():
    """Không được đụng vào đường Short đã có bằng chứng và đang chạy đúng."""
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    short = {
        "profile_id": "ban-so-6",
        "video_type": "short",
        "sections": [
            {"purpose": "situation", "voiceover": "Còn 48 phút, Minh chưa biết nên im hay nói."},
            {"purpose": "core_answer", "voiceover": "Im lặng làm mất chỗ để người khác xác nhận lại."},
            {"purpose": "payoff", "voiceover": "Cậu sẽ chọn gì?"},
        ],
    }

    prompt = editorial_rewrite_prompt(short, _Review())

    assert "SHORT LENGTH BUDGET" in prompt


def test_long_narrator_reflection_repair_also_states_its_budget():
    """Cùng một lớp lỗi, cùng một cổng.

    Repair này viết lại section cuối, và comment của chính nó ghi nhận đã từng
    làm mất 69 ký tự của một Short rồi bị chặn ở 28.4s/30.0s. Cơ chế đó không
    khác gì với Long — chỉ là ngân sách chưa bao giờ được nói ra. Trong lượt
    ideation 19:33 nó chạy ngay trước khi độ dài tụt xuống dưới sàn.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import narrator_reflection_repair_prompt

    prompt = narrator_reflection_repair_prompt(
        _long_payload(), "Lời chốt chưa là phản chiếu trực tiếp."
    )

    # Long ở fixture thiếu chữ nhiều, nên phần thiếu KHÔNG được dồn vào lời
    # chốt — nhánh chỉ-nêu-trần là đúng ở đây. Xem test bên dưới về lý do.
    assert "LENGTH BUDGET" in prompt
    assert "Long" in prompt
    assert "2-3 spoken sentences" in prompt


def test_reflection_repair_never_demands_more_than_2_3_sentences_can_hold():
    """Ngân sách không được đánh nhau với ràng buộc cấu trúc của cùng section.

    Bản sửa này viết section cuối và cùng lúc bị buộc "exactly 2-3 natural
    spoken sentences". Khi tôi thêm ngân sách độ dài cho Long (76213e5), một
    Long thiếu chữ đã đẩy TOÀN BỘ phần thiếu của cả kịch bản vào đúng section
    đó:

        "the other sections already carry 5013, so your rewritten final section
         must be between 879 and 2346 characters"

    879 ký tự chia cho 2-3 câu là ~300 ký tự một câu. Model chọn con số thay vì
    cấu trúc, trả về một câu lê thê, và `narrator_reflection` loại đúng thứ đó
    — run 2026-09-02 20:28 chết vì chính bản sửa đáng lẽ cứu nó.

    Phần thiếu của cả kịch bản là việc của `extend` (thêm section), không phải
    của lời chốt. Ở đây trần vẫn phải nêu — vượt trần là hỏng thật — nhưng sàn
    chỉ được nêu khi nó nằm vừa trong 2-3 câu.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import (
        REFLECTION_MAX_CHARS,
        narrator_reflection_repair_prompt,
    )

    prompt = narrator_reflection_repair_prompt(
        _long_payload(), "Lời chốt chưa là phản chiếu trực tiếp."
    )

    assert "LENGTH BUDGET" in prompt
    assert REFLECTION_MAX_CHARS <= 600, "2-3 câu tiếng Việt không thể dài hơn thế"
    # Bất biến thật: con số ĐÒI HỎI không bao giờ vượt thứ 2-3 câu chứa nổi.
    # Đọc thẳng hai đầu ra khỏi prompt thay vì tin vào một cụm từ.
    demanded = re.search(r"must be between (\d+) and (\d+) characters", prompt)
    assert demanded is not None
    low, high = int(demanded.group(1)), int(demanded.group(2))
    assert high <= REFLECTION_MAX_CHARS
    assert low <= REFLECTION_MAX_CHARS
    # Và phải nói rõ phần thiếu của cả kịch bản không phải việc của section này.
    assert "do not make that up here" in prompt


def test_reflection_repair_still_states_a_floor_when_it_fits():
    """Sàn vẫn phải được nêu khi nó vừa 2-3 câu.

    Đã đo: một Short mất 69 ký tự ở đây và chết ở 28.4s trên sàn 30.0s. Bản sửa
    cho trần-mọi-lúc không được nuốt mất ca đó.

    Kích thước fixture suy ra TỪ chính bounds đang hiệu lực, không ghim số:
    ngưỡng phụ thuộc profile và TTS provider, nên một fixture ghim cứng sẽ đo
    nhầm nhánh khi cấu hình đổi.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import (
        REFLECTION_MAX_CHARS,
        _total_length_bounds,
        narrator_reflection_repair_prompt,
    )

    probe = {
        "profile_id": "ban-so-6",
        "video_type": "short",
        "sections": [{"purpose": "situation", "voiceover": "x"}] * 3,
    }
    floor, _cap = _total_length_bounds(probe)
    # Chừa lại đúng một khoảng nhỏ để lời chốt lấp — vừa trong 2-3 câu.
    wanted_others = floor - (REFLECTION_MAX_CHARS // 2)
    filler = "Còn bốn tám phút, Minh vẫn chưa biết nên im hay nói. "
    body = (filler * (wanted_others // len(filler) + 1))[: wanted_others // 2]

    short = {
        "profile_id": "ban-so-6",
        "video_type": "short",
        "sections": [
            {"purpose": "situation", "voiceover": body},
            {"purpose": "core_answer", "voiceover": body},
            {"purpose": "payoff", "voiceover": "Cậu sẽ chọn gì?"},
        ],
    }

    prompt = narrator_reflection_repair_prompt(short, "Lời chốt chưa đạt.")

    assert "LENGTH BUDGET" in prompt
    assert "must be between" in prompt


def test_a_payload_without_sections_asks_for_no_budget():
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    prompt = editorial_rewrite_prompt(
        {"profile_id": "ban-so-6", "video_type": "long", "sections": []}, _Review()
    )

    assert "LENGTH BUDGET" not in prompt
