# Conversation Contract

Trước khi trả JSON, lập thầm từng cảnh: ở đâu/khi nào/vật gì đang ở trước mặt; mỗi người biết gì và chưa biết gì; người đang nói muốn gì; lời vừa nghe làm người kế tiếp đổi gì; hành động nằm ở narrator hoặc visual intent; cảnh kết thúc bằng thông tin mới, lựa chọn hoặc hệ quả.

Minh nói ngắn, cụ thể, hay trì hoãn bằng sửa thêm hoặc kiểm tra thêm. An không diễn vai chuyên gia; cô hỏi về vật, thời gian, hoặc lựa chọn đang diễn ra và có thể không đồng ý/chưa có đáp án. Narrator mở cảnh, giữ nhịp, cho thấy chi tiết nhân vật chưa nói; section cuối narrator khái quát câu chuyện thành bài học nói trực tiếp với người xem.

Section cuối phải có `speaker_id` là narrator, 2-3 câu nói trực tiếp với người xem, bắt nguồn từ lựa chọn/hệ quả vừa xảy ra; không là mệnh lệnh tức thời hay lời của Minh/An. Mỗi section nhân vật có `turn`; voiceover của nhân vật chỉ là đúng câu họ nói, không mang action/stage direction.
