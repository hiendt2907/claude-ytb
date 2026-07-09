# CLAUDE.md

> **Mission đã amend 2026-07-09** (lần 2) — xem `PROJECT_VISION.md` Amendment
> Log. Bản amend 2026-07-07 (render-only tool) đã hết hiệu lực về mặt "ngoài
> phạm vi": dự án này giờ là **core render engine của 1 luồng content
> xuyên suốt** (script → voice → pexels → render → publish), copy từ
> `~/Documents/video-render` về `claude-ytb/video-render/` — bản gốc ở
> Documents **CẤM thao tác**, chỉ dùng làm tham chiếu.
>
> Lý do amend: user muốn 1 luồng UI liền mạch từ ý tưởng tới video đã đăng —
> thay vì 2 tool tách rời (`claude-ytb` lo ideation/voiceover/publish,
> `video-render` chỉ lo ghép). Thay vì viết lại render engine (đã chín,
> nhiều test, nhiều profile hiệu ứng), ta GIỮ NGUYÊN `assembler/*` 100% và
> bọc thêm 3 bước quanh nó trong module `content/` mới (xem bên dưới) — root
> cause: 2 tool trùng lặp ideation/Pexels/publish nếu tách riêng, còn thuật
> toán N-variant của `assembler/assignment.py` vẫn dùng được nguyên vẹn nếu
> Pexels tự tải NHIỀU candidate/cảnh thay vì user tự kéo thư mục.

## Dự án này là gì

Một công cụ **dựng video từ video source có sẵn** — thay thế CapCut cho use
case KOL/KOC/affiliate cần ra nhiều video biến thể từ cùng một buổi quay
(mission gốc, KHÔNG đổi). Từ 2026-07-09, dự án còn là core render của luồng
content tự động: Claude viết kịch bản → edge-tts đọc → Pexels tự tải B-roll
theo từng đoạn (đổ vào đúng cấu trúc scene folder bên dưới) → engine
`assembler/*` này ghép y như cũ → publish thẳng lên YouTube có lịch.

**Input (không đổi):**
- Một loạt **thư mục cảnh** (scene folders) theo đúng thứ tự cảnh trong video
  cuối cùng. Mỗi thư mục chứa nhiều video source ứng viên cho đúng cảnh đó —
  giờ có thể do user tự kéo (dùng như cũ) HOẶC do `content/pexels_fetch.py`
  tự tải về (dùng trong luồng content mới).
- **Một voice track** cho toàn bộ video — do user cung cấp (dùng như cũ)
  HOẶC do `content/voiceover.py` tự sinh từ kịch bản (edge-tts).
- Số lượng output **N** do user chọn (VD: 5, 10, 15) — luồng content mới mặc
  định N=1 (1 kịch bản → 1 video) nhưng vẫn cho tăng N khi cần nhiều biến thể.

**Output:** N video hoàn chỉnh, mỗi video ghép 1 clip/cảnh (khác tổ hợp giữa
các output) đồng bộ với voice track cố định.

## Module `content/` (mới, 2026-07-09) — bọc quanh assembler, KHÔNG sửa assembler

- `content/script_gen.py` — gọi `claude -p` sinh kịch bản (title/description/
  segments{narration, visual_keywords}) từ 1 topic. Prompt template ở
  `content/prompts/script_gen.md` (versioned artifact, không hardcode).
- `content/voiceover.py` — port rút gọn từ `claude-ytb/voiceover/tts.py`:
  edge-tts, sinh song song (ThreadPoolExecutor), ghép 1 voice track duy nhất
  cho cả kịch bản, trả kèm duration/segment để `assembler/duration.py` mode
  `voice_silence` đồng bộ độ dài cảnh.
- `content/pexels_fetch.py` — mỗi segment → tìm+tải N candidate Pexels (stdlib
  `urllib`, cache theo hash link, giống cách `claude-ytb/render/stock.py`
  làm) → đổ vào `scene_XX/{i}.{j}.mp4` đúng convention `assembler/scanning.py`
  đọc — **không cần sửa gì ở assembler**.
- `content/publish.py` + `content/youtube_auth.py` — port rút gọn từ
  `claude-ytb/publish/uploader.py`/`youtube_auth.py`: upload YouTube Data API
  (OAuth), hỗ trợ `publish_at` (RFC3339) để lên lịch tự công khai. Credentials/
  token **dùng lại của `claude-ytb`** (đã chốt với user, copy vật lý vào
  `video-render/secrets/`, KHÔNG commit — xem `.gitignore`).
- `webui/content_routes.py` — nối 4 module trên với `webui/jobs.py` có sẵn:
  `POST /api/content/generate-script`, `POST /api/content/jobs` (script→voice→
  pexels→ tự kích hoạt render job cũ), `GET /api/content/jobs/{id}`,
  `POST /api/content/publish/{render_job_id}/{index}`.
- `webui/store.py` — tách `JobStore` singleton ra khỏi `app.py` để
  `content_routes.py` dùng chung mà không circular-import với `app.py`.

## Ngoài phạm vi (vẫn giữ)

- Multi-platform publish khác YouTube (TikTok/Reels...) — chưa làm, chỉ
  YouTube Data API.
- Sinh ảnh/video AI thật (Flux/Wan2.2...) cho B-roll — vẫn dùng Pexels
  (stock), không sinh từ prompt.

## Thuật toán chọn/ghép (spec đã chốt 2026-07-07)

- Mỗi cảnh có thể dùng 1 hoặc nhiều clip liên tiếp (theo sub_index tên file)
  cho 1 output; việc chia nhóm/ranh giới nhóm được **random hoá qua từng
  output** (không lặp mô-típ chia nhóm giống hệt nhau).
- Trong 1 nhóm, thứ tự nối clip **luôn theo sub_index** (VD `1.1` trước
  `1.2`) — không random.
- Sau N output, **mọi clip trong mọi thư mục cảnh phải được dùng ít nhất 1
  lần**; nếu N nhỏ hơn số clip, cho phép lặp lại clip giữa các output để đảm
  bảo coverage (không báo lỗi/chặn).
- Output đặt tên `output/<product_name>/variant_01.mp4` ... zero-pad theo N.
- Thời lượng mỗi cảnh: user chọn 1 trong 2 chế độ — `clip_length` (theo độ
  dài tự nhiên clip đã chọn) hoặc `voice_silence` (tách từ khoảng lặng trong
  voice track). Xem `src/ytb_pipeline/assembler/duration.py`.

Xem chi tiết đầy đủ tại `PROJECT_VISION.md` §Amendment Log (2026-07-07).

## Coding Standards (vẫn áp dụng)

- **Python 3.13+.** Type hints bắt buộc, `mypy --strict` sạch.
- **Async-first** cho I/O; `asyncio.run()` chỉ 1 điểm vào top-level.
- **Immutable.** `@dataclass(frozen=True)` cho domain object. Enrich qua
  `dataclasses.replace()` — không mutate bản gốc.
- **Structured logging** (`structlog`), không `print()`/`logging.info(f"...")`.
- **File size** tối đa 400 dòng/file.
- **No hardcoded path** — qua `settings.<field>`.
- **Naming:** `snake_case` hàm/biến, `PascalCase` class, `UPPER_SNAKE_CASE`
  constant.

## Review & Testing (vẫn áp dụng)

- Code review bắt buộc (`code-reviewer` agent) trước khi commit.
- Security review nếu đụng tới input từ bên ngoài (upload file, path do user
  nhập).
- Test pyramid: unit 70% / integration 20% / e2e 10%. Không gọi FFmpeg thật
  trong unit test — để `@pytest.mark.integration`.

## Repository Evolution Rules

Giữ nguyên tinh thần từ bản cũ: chủ động phát hiện code trùng lặp/module quá
lớn/technical debt và ghi nhận lại; không tự ý mở rộng lớn ngoài phạm vi yêu
cầu mà không giải thích + chờ phê duyệt; ưu tiên thay đổi nhỏ, incremental.

## COMMUNICATION

- **Code trước.** Viết code ngay, không hỏi lại trừ khi thiếu thông tin
  chặn cứng.
- **Giải thích tối đa 100 chữ** khi thật sự cần giải thích.
