Bạn là biên kịch YouTube. Trong danh sách chủ đề đang TRENDING sau, hãy CHỌN
đúng 1 chủ đề phù hợp nhất với kênh (nội dung truyền cảm hứng / xây dựng thói
quen / chia sẻ kiến thức về tâm lý-hành vi con người) — hoặc lấy cảm hứng từ
1 chủ đề để biến tấu thành góc nhìn thói quen/tâm lý riêng của kênh. KHÔNG
chọn chủ đề giải trí thuần tuý/tin tức thời sự/lùm xùm nghệ sĩ.

CHỦ ĐỀ ĐANG TRENDING (chưa từng làm trước đây, chọn 1):
{candidates}

Từ khoá SEO liên quan (tham khảo, không bắt buộc dùng hết): {seo_keywords}

Sau khi chọn xong, viết kịch bản với yêu cầu:
- Chia thành đúng {num_segments} đoạn (segments), mỗi đoạn 1-3 câu narration
  tiếng Việt, mạch lạc, nối tiếp nhau thành một câu chuyện hoàn chỉnh.
- Mỗi đoạn kèm 2-4 từ khoá tiếng Anh (visual_keywords) mô tả hình ảnh/B-roll
  khớp với nội dung đoạn đó, dùng để tìm kiếm trên Pexels (vd: "sunrise walk",
  "person journaling", "city morning commute").
- KHÔNG chèn chỉ dẫn dàn cảnh (không viết "Cảnh:", "Beat:", "Cú hình tiếp
  theo:"...) vào narration — chỉ lời thoại thuần.
- `title` PHẢI là tiêu đề của chủ đề bạn chọn/biến tấu (không phải nguyên văn
  chủ đề trending nếu bạn biến tấu góc nhìn).

CHỈ trả về JSON đúng schema sau, không kèm text giải thích, không bọc trong
```:

{{
  "title": "...",
  "description": "...",
  "segments": [
    {{"narration": "...", "visual_keywords": ["...", "..."]}}
  ]
}}
