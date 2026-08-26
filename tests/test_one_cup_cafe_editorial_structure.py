"""Content profile `one-cup-cafe-6h` phải ép cấu trúc 3 phần đã được chủ dự
án duyệt trên bản demo transcript viết tay:

- Long: nỗi đau -> triệu chứng -> cách xử lý (có cơ chế/lý do đằng sau).
- Short: hook nỗi đau lên đầu (không chào hỏi/định nghĩa) -> câu hỏi mở
  chưa trả lời hết -> dẫn rõ về Long cùng chủ đề.

Đây là kiểm tra ở mức content (editorial.md nạp qua
`content_profile.prompt_text("editorial")`), không phải kiểm tra hành vi
LLM thật — không gọi provider nào.
"""

from __future__ import annotations

from ytb_pipeline.content_profiles import load_content_profile

PROFILE_ID = "one-cup-cafe-6h"


def test_editorial_prompt_names_pain_symptom_treatment_structure() -> None:
    profile = load_content_profile(PROFILE_ID)

    editorial_text = profile.prompt_text("editorial")

    assert "nỗi đau" in editorial_text.lower()
    assert "triệu chứng" in editorial_text.lower()
    assert "cách xử lý" in editorial_text.lower()
    # Long phải nêu rõ cơ chế/lý do đứng sau triệu chứng, không chỉ liệt kê.
    assert "cơ chế" in editorial_text.lower()


def test_editorial_prompt_requires_short_to_funnel_into_long() -> None:
    profile = load_content_profile(PROFILE_ID)

    editorial_text = profile.prompt_text("editorial").lower()

    # Short phải hook bằng nỗi đau trước, có câu hỏi mở, và dẫn rõ về Long.
    assert "câu hỏi mở" in editorial_text
    assert "long" in editorial_text
    assert "cta" in editorial_text
    assert "phễu" in editorial_text or "dẫn" in editorial_text

    # Cấu trúc vẫn dùng đúng purpose vocabulary mặc định của profile này
    # (situation/core_answer/evidence/application/payoff) — không tự ý đổi.
    purpose_policy = profile.editorial_contract.purpose_policy
    assert "situation" in purpose_policy.vocabulary
    assert "evidence" in purpose_policy.vocabulary
    assert "application" in purpose_policy.vocabulary
