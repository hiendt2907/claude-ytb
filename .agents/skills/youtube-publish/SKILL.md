---
name: youtube-publish
description: Khâu 4 — upload video lên YouTube qua Data API (OAuth), set title/tags/thumbnail, theo dõi analytics. Dùng khi làm việc với publish/uploader.py, OAuth flow, hoặc bất kỳ tác dụng phụ ra ngoài. BẮT BUỘC tôn trọng DRY_RUN. Liên quan [[youtube-pipeline-core]], [[youtube-monetization]].
version: 1.0.0
source: project-architecture
---

# YouTube Publish

Khâu cuối: `RenderedVideo → PublishResult`. File: `publish/uploader.py`.
Đây là khâu DUY NHẤT gây tác dụng phụ ra ngoài (upload, gọi API tài khoản thật).

## DRY_RUN — bắt buộc kiểm tra trước

```python
def publish(video: RenderedVideo) -> PublishResult:
    if settings.dry_run:
        log_intent(video)  # chỉ log dự định, KHÔNG gọi API
        return replace(PublishResult(**vars(video)), uploaded=False)
    # ... mới gọi videos.insert / thumbnails.set
```

Mặc định `settings.dry_run=True`. Không bao giờ upload thật khi dry_run bật.

## OAuth & secrets

- Client secret: `settings.youtube_client_secrets` (mặc định `secrets/client_secret.json`)
- Token cache: `settings.youtube_token_file`
- Thư mục `secrets/` đã gitignore — TUYỆT ĐỐI không commit credential/token.
- Dùng `google-auth-oauthlib` cho OAuth installed-app flow; refresh token tự động.

## Upload flow

1. `videos.insert` với title/description/tags từ `script` (đã tối ưu SEO)
2. `thumbnails.set` với `video.thumbnail_path`
3. Lưu `youtube_id` + `url` vào `PublishResult` qua `replace()`

## Quota & lỗi

- YouTube Data API có quota theo ngày (upload tốn ~1600 đơn vị). Xử lý quota-exceeded tường minh.
- Retry có backoff cho lỗi tạm thời; không retry mù lỗi 4xx (sai quyền/quota).

## Checklist

- [ ] Kiểm tra `settings.dry_run` TRƯỚC mọi lời gọi API
- [ ] Credential đọc từ `secrets/`, không hardcode/commit
- [ ] Xử lý quota & lỗi OAuth tường minh
- [ ] Trả `PublishResult` làm giàu qua `replace()` ([[youtube-pipeline-core]])
