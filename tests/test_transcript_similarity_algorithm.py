"""Regression coverage for deterministic Vietnamese transcript matching."""

from ytb_pipeline.voiceover import quality


def test_long_near_verbatim_vietnamese_transcript_does_not_trigger_autojunk_false_negative():
    expected = (
        "Hãy hình dung cả nhóm đồng ý thay công cụ quản lý việc. Bạn đã dùng nó vài tháng, "
        "xem hướng dẫn và từng giới thiệu nó. Khi sếp hỏi dữ liệu cũ sẽ đi đâu, ai nhận thông "
        "báo, hai người sửa cùng một việc thì sao, và làm sao hoàn tác lỗi, bạn chỉ trả lời được "
        "vài mảnh. Điều này không làm công cụ đó tệ. Kinh nghiệm sử dụng tạo cảm giác trơn tru, "
        "còn chuỗi nguyên nhân phía sau vẫn nằm ngoài đầu bạn. Ta mượn cấu trúc của giao diện, "
        "người hướng dẫn và cả nhóm rồi vô tình tính chúng như kiến thức cá nhân. Nếu nhập nhầm "
        "trạng thái rồi khách hàng nhận thông báo sai, hãy hỏi dữ liệu đã qua quy tắc nào."
    )
    transcript = (
        "Hình dung cả nhóm đồng ý thấy công cụ quản lý việc. Bạn đã dùng nó vài tháng, xem hướng "
        "dẫn và từng giới thiệu nó. Khi xếp hỏi dữ liệu củ sẽ đi đâu? Thì nhận thông báo, hai người "
        "sửa cùng một việc thì sao? Và làm sao hoàn tác lổi? Bạn chỉ trả lời được vài mảnh. Từ nay "
        "không làm công củ đó tệ. Nghiệm sử dụng tạo cảm giác trân tru, còn chủ nguyên nhân phía "
        "sau vẫn nằm ngoài đầu bạn. Ta mượn cấu trúc của giao diện, hư hướng dẫn và cả nhóm rồi vô "
        "tình tính chúng như kiến thức cá nhân. Nếu nhập nhầm trạng thái rồi khách hàng nhận thông "
        "báo sai, hãy hỏi dữ liệu đã qua quy tắc nào?"
    )

    assert quality._transcript_similarity(expected, transcript) >= 0.82


def test_vietnamese_clock_time_variants_normalise_before_similarity():
    expected = (
        "Sáu giờ bảy phút sáng, Minh đẩy cửa quán. "
        "Bảy giờ ba mươi, An đặt ly cà phê xuống bàn. "
        "Tám giờ mười hai phút, Minh mở hộp thư mới."
    )
    transcript = (
        "6 giờ 7 phút sáng, Bình đẩy cửa quán. "
        "7h30, anh đặt ly cà phê xuống bàn. "
        "8 giờ 12 phút, Minh mở hộp thư mới."
    )

    assert quality._transcript_similarity(expected, transcript) >= 0.82


def test_quality_cache_context_identifies_the_similarity_algorithm():
    context = quality._gate_cache_context(
        _AvailableAdapter(),
        quality.SttAvailability(True, "local-test"),
        duration_tolerance_sec=30.0,
        transcript_similarity_threshold=0.82,
        max_silence_ratio=0.65,
        require_transcript=True,
    )

    assert context["transcript_similarity_algorithm"] == "sequence-matcher-no-autojunk-v1"
    assert context["version"] >= 3


class _AvailableAdapter:
    name = "local-test"

    def availability(self):
        return quality.SttAvailability(True, self.name)


def test_cache_version_was_bumped_for_the_clock_time_normalisation_change():
    """A quality result cached under the OLD (pre-clock-normalisation)
    algorithm must not be silently reused now that narration containing
    "6h07"-style clock shorthand normalises differently. `quality_cache_key`
    folds `_CACHE_VERSION` into its hash, so bumping it is what actually
    invalidates any pre-existing cache entry with the same audio+script
    content hash — leaving it at the old value would let a stale mismatch
    verdict (computed before this fix existed) go on being served forever.
    """
    assert quality._CACHE_VERSION >= 7
