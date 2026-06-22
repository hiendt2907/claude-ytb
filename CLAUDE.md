# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Dự án

Pipeline tự động hoá sản xuất nội dung và kiếm tiền từ YouTube, chạy trên **macOS**.
Ngôn ngữ chính: **Python**. Phụ thuộc hệ thống bắt buộc: `ffmpeg` (`brew install ffmpeg`).

Trạng thái: scaffold khởi đầu — các khâu pipeline hiện là stub `raise NotImplementedError`,
chờ triển khai. Hợp đồng dữ liệu (`pkg/models.py`) và orchestrator (`pipeline.py`) đã định hình.

## Lệnh thường dùng

```bash
make setup                       # tạo .venv + cài requirements.txt
make run TOPIC="<chủ đề>"        # chạy pipeline 1 chủ đề (mặc định DRY_RUN)
make test                        # pytest + coverage
make clean                       # xoá output/audio/cache

# Chạy 1 test:
.venv/bin/pytest tests/test_models.py::test_script_enriches_idea_without_mutation
```

Tất cả lệnh python phải chạy trong `.venv` (hoặc `PYTHONPATH=src`); `pytest.ini` đã set
`pythonpath = src`, `asyncio_mode = auto`, và bật coverage `--cov=ytb_pipeline`.

## Kiến trúc

Pipeline tuyến tính 4 khâu, nối trong `src/ytb_pipeline/pipeline.py::run(script_source)`:

```
ideation → voiceover → render → publish
```

| Khâu | Module | Vai trò |
|------|--------|---------|
| 1. Ideation | `ideation/generator.py` | Nạp + validate kịch bản (`scripts/*.json`) do **Claude viết tay** trong chat |
| 2. Voiceover | `voiceover/tts.py` | TTS (edge-tts free / ElevenLabs) + media |
| 3. Render | `render/compose.py` | moviepy/ffmpeg dựng .mp4 + thumbnail (Pillow) |
| 4. Publish | `publish/uploader.py` | YouTube Data API upload + SEO + analytics |

### Quy ước cốt lõi: dataclass bất biến, làm giàu dần

`pkg/models.py` định nghĩa chuỗi dataclass `frozen=True` **kế thừa nối tiếp**:
`VideoIdea → Script → Voiceover → RenderedVideo → PublishResult`.

Mỗi khâu nhận model của khâu trước và trả về **bản sao làm giàu thêm** qua
`dataclasses.replace()` — **KHÔNG BAO GIỜ mutate bản gốc**. Đây là invariant trung tâm:
khi một khâu cần thêm field cho khâu sau, dùng `replace()` để tạo copy, giữ nguyên input.

### Config — fail fast tại ranh giới

`config/settings.py` nạp toàn bộ cấu hình từ env (`.env`) qua pydantic-settings,
expose singleton `settings`. Mọi key (API keys, paths, provider, `dry_run`) đọc từ đây,
không hardcode rải rác. `DRY_RUN=true` (mặc định) = render local, không upload thật —
giữ nguyên hành vi này khi triển khai khâu publish.

**Config động (dashboard):** ưu tiên nguồn là env shell > `data/config.json`
(dashboard ghi, gitignored) > `.env` > secrets — xem `settings_customise_sources`.
Thêm key sửa-được-trên-web: khai báo field trong `Settings` + thêm vào
`web/config_store.py::FIELDS`. `config_store.save()` ghi atomic rồi reload singleton
tại chỗ (`settings.__dict__.update`) để mọi module đã import thấy ngay.

### Dashboard web (`web/`)

FastAPI + Jinja2/HTMX, gọi thẳng module pipeline. `make dashboard` (uvicorn); đăng
nhập bằng `DASHBOARD_PASSWORD` (session cookie). Cổng duyệt kịch bản chạy song song
web + Telegram: `web/approvals.py` đăng ký qua `ideation.approval.set_approval_provider`.
Job nền single-flight trong `web/jobs.py`. Từ xa qua Cloudflare Tunnel `ytb.nginxwaf.xyz`
(README). KHÔNG commit `data/config.json` (chứa secrets).

## Ngách & series (định hướng nội dung)

Kênh chạy theo **series một ngách xuyên suốt**: "**phát triển bản thân THẬT, không
self-help**" — giải thích *cơ chế* con người (tâm lý/hành vi học ứng dụng + mental models),
tiếng Việt, giọng kể ẩn danh. Long-form 10–12 phút = mỗi tập **một cơ chế**, cấu trúc 5 phần
(hook nghịch lý → vấn đề → cơ chế tại sao → khung áp dụng → chốt + **cầu nối tập sau**). Short
cắt "cơ chế gây sốc" từ long, cùng ngách, làm phễu kéo về long.

Mọi kịch bản đi qua bộ rule + các cổng verify (ép ở code) trong
`.claude/skills/youtube-ideation/video-quality-rules.md` — đặc biệt **mục 0c** (3 gate ngách:
không self-help / mật độ ý / nguồn truy được) và **mục 0d** (ràng buộc series: một cơ chế/tập,
liên kết tập, không badge "Tập n", gán playlist). Chống trùng: đối chiếu `data/ledger.md` trước
khi viết. Tránh mảng "buổi sáng/dậy sớm" đã bão hoà.

## Khi triển khai stub

- Validate input tại ranh giới (API response, file) trước khi xử lý.
- Khâu publish phải kiểm tra `settings.dry_run` trước khi gọi API thật.
- Audio → `assets/audio/`, video cuối → `assets/output/` (đã gitignore).
- Secrets (OAuth client, token) nằm trong `secrets/` — đã gitignore, không commit.
- Giữ file nhỏ, tách theo khâu/feature; thêm test trước khi hiện thực (TDD, coverage ≥ 80%).
