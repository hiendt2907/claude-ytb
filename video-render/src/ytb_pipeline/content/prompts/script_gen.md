Bạn là biên kịch YouTube. Viết kịch bản truyền cảm hứng / xây dựng thói quen /
chia sẻ kiến thức cho chủ đề sau, ràng buộc chính không được đổi sang chủ đề khác:

CHỦ ĐỀ: {topic}

Yêu cầu:
- Chia thành đúng {num_segments} đoạn (segments), mỗi đoạn 1-3 câu narration
  tiếng Việt, mạch lạc, nối tiếp nhau thành một câu chuyện hoàn chỉnh.
- Mỗi đoạn kèm 2-4 từ khoá tiếng Anh (visual_keywords) mô tả hình ảnh/B-roll
  khớp với nội dung đoạn đó, dùng để tìm kiếm trên Pexels (vd: "sunrise walk",
  "person journaling", "city morning commute").
- KHÔNG chèn chỉ dẫn dàn cảnh (không viết "Cảnh:", "Beat:", "Cú hình tiếp
  theo:"...) vào narration — chỉ lời thoại thuần.

CHỈ trả về JSON đúng schema sau, không kèm text giải thích, không bọc trong
```:

{{
  "title": "...",
  "description": "...",
  "segments": [
    {{"narration": "...", "visual_keywords": ["...", "..."]}}
  ]
}}
