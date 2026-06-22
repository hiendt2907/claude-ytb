---
name: youtube-render-ai
description: Khâu 3 (biến thể AI) — sinh hình ảnh/clip nền bằng AI (text→image, image→video, Veo/Runway/Kling…) theo từng đoạn kịch bản, rồi ghép thành .mp4 thay cho slide tĩnh. Dùng khi muốn video có B-roll/cảnh động sinh bằng AI. Liên quan [[youtube-render]], [[youtube-pipeline-core]].
version: 1.0.0
source: project-architecture
---

# YouTube Render AI — dựng hình bằng AI

Biến thể của khâu Render: thay vì slide tĩnh, **sinh visual bằng AI cho từng đoạn**
(`Segment`) rồi ghép theo timeline của `Voiceover`. Vẫn xuất `RenderedVideo` đúng
hợp đồng dữ liệu — chỉ khác nguồn hình. File gợi ý: `render/compose_ai.py`.

## Luồng

1. **Per-segment prompt** — từ `seg.narration` sinh prompt hình ảnh (mô tả cảnh,
   phong cách, palette). Giữ prompt template tách khỏi code (như [[youtube-ideation]]).
2. **Sinh visual**:
   - *text→image* cho cảnh tĩnh chất lượng cao, rồi thêm chuyển động Ken Burns
     (zoom/pan) khi ghép — rẻ, nhanh, ổn định.
   - *image→video / text→video* (Veo, Runway, Kling, Luma…) cho cảnh động thật.
     Đắt + chậm hơn; dùng cho hook/cao trào, không cho mọi đoạn.
3. **Cache** — visual sinh ra lưu `assets/ai/<script_slug>/<seg_idx>.<ext>`; nếu đã
   có và prompt không đổi thì **không sinh lại** (tốn tiền/thời gian). Dùng hash
   prompt làm key.
4. **Ghép** — đặt mỗi visual đúng `seg.start/duration` khớp audio, ghép qua
   moviepy/ffmpeg (giống [[youtube-render]]), overlay phụ đề, xuất .mp4 + thumbnail.

## Provider — fail fast, đọc từ settings

- Provider + API key đọc từ `settings` (vd `ai_visual_provider`, `*_api_key`),
  KHÔNG hardcode. Thêm key tương ứng vào `.env.example`.
- **Kiểm tra docs hiện hành trước khi code**: API text→video (Veo/Runway/Kling)
  đổi nhanh — endpoint, model id, giá, định dạng output, thời gian chờ job async.
- Nhiều API là **async job**: submit → poll trạng thái → tải kết quả. Xử lý timeout,
  retry, và lỗi kiểm duyệt nội dung tường minh.

## Chi phí & DRY_RUN

- Sinh video AI tốn tiền thật → tôn trọng cờ giống `DRY_RUN`: khi bật, dùng
  ảnh placeholder/cache cũ thay vì gọi API trả phí.
- Ưu tiên ảnh tĩnh + motion; chỉ dùng text→video cho vài cảnh chủ chốt để khống
  chế chi phí mỗi video.

## Hợp đồng dữ liệu

Trả `RenderedVideo` qua `replace()` từ `Voiceover` (không mutate) — y như
[[youtube-render]], để [[youtube-publish]] dùng tiếp.

```python
def render_video_ai(vo: Voiceover) -> RenderedVideo:
    clips = [ai_clip_for(seg) for seg in vo.segments]  # sinh/lấy-cache visual
    mp4, thumb = compose(clips, vo.audio_path)
    return replace(RenderedVideo(**vars(vo)), video_path=mp4, thumbnail_path=thumb)
```

## Checklist

- [ ] Mỗi segment có visual khớp đúng `start/duration` của audio
- [ ] Visual AI được cache theo hash prompt; không sinh lại khi không đổi
- [ ] Provider/key đọc từ `settings`, không hardcode; thêm vào `.env.example`
- [ ] Job async: poll trạng thái, xử lý timeout/retry/kiểm duyệt tường minh
- [ ] Cờ DRY_RUN/no-cost: không gọi API trả phí khi bật
- [ ] Trả `RenderedVideo` qua `replace()` ([[youtube-pipeline-core]])
- [ ] Kiểm tra docs provider hiện hành trước khi viết code gọi API
