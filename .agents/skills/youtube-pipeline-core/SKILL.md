---
name: youtube-pipeline-core
description: Quy ước cốt lõi của pipeline Codex-ytb — kiến trúc 4 khâu tuyến tính, chuỗi dataclass bất biến làm giàu dần qua dataclasses.replace(), config fail-fast và DRY_RUN. Dùng cho MỌI thay đổi đụng tới pipeline.py, pkg/models.py, hoặc khi nối/thêm khâu.
version: 1.0.0
source: project-architecture
---

# YouTube Pipeline Core

Skill nền tảng — phải tuân theo khi chạm vào bất kỳ khâu nào của pipeline.

## Kiến trúc 4 khâu

`src/ytb_pipeline/pipeline.py::run(topic)` nối tuyến tính:

```
ideation → voiceover → render → publish
```

Mỗi khâu là **hàm thuần**: nhận model của khâu trước, trả model làm giàu thêm.
Không có state toàn cục giữa các khâu ngoài `settings`.

## Invariant CỐT LÕI: dataclass bất biến, làm giàu dần

`pkg/models.py` định nghĩa chuỗi `frozen=True` kế thừa nối tiếp:

```
VideoIdea → Script → Voiceover → RenderedVideo → PublishResult
```

Khi một khâu cần thêm field cho khâu sau, **tạo bản sao bằng `dataclasses.replace()`** —
TUYỆT ĐỐI không mutate input.

```python
from dataclasses import replace

def write_script(idea: VideoIdea) -> Script:
    body = call_llm(idea)
    # Nâng cấp VideoIdea -> Script, giữ nguyên idea gốc
    return replace(Script(**vars(idea)), body=body, sections=tuple(...))
```

Lý do: tránh side-effect ẩn, dễ debug, an toàn khi chạy song song nhiều video.

## Config — fail fast tại ranh giới

Mọi cấu hình đọc từ singleton `settings` (`config/settings.py`, pydantic-settings nạp `.env`).
KHÔNG hardcode API key, path, provider rải rác.

## DRY_RUN là hợp đồng an toàn

`settings.dry_run` mặc định `True` = render local, KHÔNG upload thật. Mọi tác dụng phụ
ra ngoài (upload, gọi API tốn tiền) phải kiểm tra `settings.dry_run` trước.

## Checklist khi thêm/sửa khâu

- [ ] Khâu trả bản sao làm giàu qua `replace()`, không mutate input
- [ ] Validate input (API response, file) tại đầu khâu
- [ ] Đọc cấu hình từ `settings`, không hardcode
- [ ] Tác dụng phụ ngoài tôn trọng `dry_run`
- [ ] Có test trước khi hiện thực (TDD, coverage ≥ 80%)
- [ ] File nhỏ, tách theo khâu
