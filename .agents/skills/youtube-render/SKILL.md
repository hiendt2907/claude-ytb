---
name: youtube-render
description: Khâu 3 — dựng video .mp4 bằng moviepy/ffmpeg, ghép audio + hình ảnh/nhạc + phụ đề, sinh thumbnail bằng Pillow. Dùng khi làm việc với render/compose.py hoặc xử lý media/ffmpeg trên macOS. Liên quan [[youtube-pipeline-core]].
version: 1.0.0
source: project-architecture
---

# YouTube Render

Khâu 3: `Voiceover → RenderedVideo`. File: `render/compose.py`.

## Phụ thuộc hệ thống

`ffmpeg` BẮT BUỘC: `brew install ffmpeg`. moviepy gọi ffmpeg ngầm —
kiểm tra ffmpeg tồn tại tại startup/đầu khâu và báo lỗi rõ nếu thiếu.

## Đầu ra

- Video cuối → `assets/output/` (gitignored)
- Thumbnail → sinh bằng Pillow, lưu cạnh video
- Trả `RenderedVideo` làm giàu từ `voiceover` qua `replace()` (gồm `video_path`, `thumbnail_path`)

## Nguyên tắc media

- **Đặt kích thước/độ phân giải tường minh** (vd 1920×1080, 30fps) — không để default mơ hồ.
- **Khớp duration**: timeline video bám theo `voiceover.duration_sec`.
- **Phụ đề**: burn từ `script.sections`/body; cân nhắc style dễ đọc trên mobile.
- **Đóng tài nguyên**: moviepy clip phải `.close()` để tránh rò rỉ file handle/bộ nhớ.
- **Tạm thời → temp dir**, dọn sau khi export (xem `make clean`).

## Pattern

```python
def render_video(voiceover: Voiceover) -> RenderedVideo:
    ensure_ffmpeg()
    out = settings.output_dir / f"{slug(voiceover.title)}.mp4"
    # ghép audio + visuals + phụ đề, export
    thumb = make_thumbnail(voiceover)  # Pillow
    return replace(RenderedVideo(**vars(voiceover)),
                   video_path=out, thumbnail_path=thumb)
```

## Checklist

- [ ] Kiểm tra ffmpeg trước khi render
- [ ] Kích thước/fps tường minh, không default ngầm
- [ ] Đóng clip, dọn temp
- [ ] Output vào `assets/output/`, không commit
- [ ] Trả bản sao làm giàu ([[youtube-pipeline-core]])
