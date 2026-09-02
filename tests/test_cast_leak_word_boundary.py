"""Tên nhân vật là danh từ riêng, không phải một âm tiết bất kỳ.

`_is_narrator_lesson_closing` chặn lời chốt có nhắc tên cast. Nó tách text bằng
`_story_words` rồi so token với `voice_cast`, nên MỌI từ tiếng Việt có âm tiết
trùng tên nhân vật đều bị tính là rò rỉ.

Đo thật, ideation 2026-09-02 21:05. Lời chốt hợp lệ này bị loại:

    "... còn cuộc gọi xác minh vẫn ở lại cho chiều nay."

`xác minh` tách thành ['xác', 'minh'] và khớp cast id `minh`. Tập đó nói về một
cuộc gọi xác minh, nên từ ấy có mặt khắp nơi — cổng gần như không thể qua.

Cùng lỗi với `chứng minh`, `thông minh`, `văn minh`, `minh bạch`. Tiếng Việt
viết hoa danh từ riêng, nên đó mới là thứ phân biệt được, không phải âm tiết.
"""

from __future__ import annotations


def _profile():
    from ytb_pipeline.content_profiles import load_content_profile

    return load_content_profile("ban-so-6")


def _closes(text: str) -> bool:
    from ytb_pipeline.agents.qa_agent import _is_narrator_lesson_closing

    return _is_narrator_lesson_closing(_profile(), {"speaker_id": "narrator"}, text)


def test_a_common_word_sharing_a_syllable_with_a_cast_name_is_not_a_leak():
    """Đúng đoạn đã bị loại trên hàng thật."""
    assert _closes(
        "Có lẽ bạn cũng từng nói đúng một điều, rồi nhận ra câu hỏi còn lại không "
        "phải điều mình vừa nói, mà là vì sao mình để nó chờ lâu đến vậy. Sự thật "
        "đã ra khỏi miệng, còn cuộc gọi xác minh vẫn ở lại cho chiều nay. "
        "Tập sau, hẹn gặp lại."
    )


def test_other_vietnamese_compounds_carrying_the_same_syllable_pass():
    for phrase in ("chứng minh", "thông minh", "minh bạch", "văn minh"):
        assert _closes(
            f"Có lẽ bạn cũng từng muốn {phrase} một điều gì đó trước khi người khác "
            "kịp hỏi, rồi nhận ra thứ mình cần lại là thời gian chứ không phải lời "
            "giải thích. Tập sau, hẹn gặp lại."
        ), phrase


def test_the_actual_name_is_still_a_leak():
    """Không được nới cổng: tên riêng trong phần bài học vẫn phải bị chặn."""
    assert not _closes(
        "Có lẽ bạn cũng từng như Minh, nói ra một điều đúng rồi vẫn thấy câu hỏi "
        "còn lại chưa được trả lời chút nào. Tập sau, hẹn gặp lại."
    )
    assert not _closes(
        "Có lẽ bạn cũng từng ngồi im như An, chỉ nhìn và chờ người kia tự nói ra "
        "điều họ đang giữ trong lòng từ tối qua. Tập sau, hẹn gặp lại."
    )


def test_the_name_after_the_bridge_marker_is_still_allowed():
    """Cầu nối tập sau được phép mang tên cast — luật cũ, không đổi."""
    assert _closes(
        "Có lẽ bạn cũng từng nói ra một điều đúng rồi vẫn thấy câu hỏi còn lại "
        "chưa được trả lời chút nào. Tập sau, Minh sẽ gọi cuộc điện thoại đã lùi "
        "từ tối qua."
    )


def test_the_hook_anchor_is_not_credited_to_a_lookalike_syllable():
    """Cùng gốc lỗi, chiều ngược lại — và vì thế dễ bỏ qua hơn.

    `_check_story_hook` coi việc gọi tên nhân vật là một NEO hợp lệ. Khớp theo
    âm tiết nghĩa là một cảnh mở nói "xác minh" mà không nhắc ai được ghi công
    có neo nhân vật. Ở đây lỗi không CHẶN nhầm mà CHO QUA nhầm, nên nó lặng
    lẽ hơn: một hook yếu lọt cổng thay vì một hook tốt bị loại.
    """
    from ytb_pipeline.agents.qa_agent import _check_story_hook

    class _Seg:
        def __init__(self, narration):
            self.speaker_id = "narrator"
            self.narration = narration
            self.voiceover = narration
            self.visual_intent = "Quán vắng lúc sáng sớm."

    class _Script:
        def __init__(self, segments):
            self.segments = segments

    # Không có tên ai, không có mốc giờ — chỉ có âm tiết trùng tên.
    weak = _Seg(
        "Cuộc gọi xác minh vẫn chưa được thực hiện, và bản kế hoạch thì vẫn "
        "nằm đó chờ một câu trả lời chưa ai đưa ra."
    )
    violations = _check_story_hook(_Script([weak]), _profile())
    assert violations, "hook không neo được ai mà vẫn qua cổng"
