---
name: youtube-ideation
description: Khâu 1 — sinh ý tưởng video + kịch bản bằng Claude (Anthropic SDK), kèm cổng DUYỆT qua Telegram. Dùng khi làm việc với ideation/generator.py, thiết kế prompt nghiên cứu xu hướng, hoặc sinh title/description/tags/script. Liên quan [[youtube-pipeline-core]].
version: 1.3.0
source: project-architecture
---

# YouTube Ideation (LLM) + Cổng duyệt Telegram

Khâu đầu pipeline: từ `topic` → `VideoIdea` → `Script` → **DUYỆT qua Telegram** → tiếp.
File: `ideation/generator.py`. Module duyệt: `notify/telegram.py`.

## Ba bước

1. `generate_idea(topic) -> VideoIdea` — nghiên cứu chủ đề, sinh metadata (title, description, tags).
2. `write_script(idea) -> Script` — sinh body + sections; trả bản sao làm giàu qua `replace()`.
3. **Duyệt qua Telegram** — gửi kịch bản đầy đủ cho user, chờ phản hồi. Nếu user
   yêu cầu sửa → sửa prompt theo yêu cầu, sinh lại, gửi LẠI bản đầy đủ đã sửa,
   lặp tới khi user duyệt.

## Gọi Claude

Dùng Anthropic SDK với `settings.anthropic_api_key` và `settings.llm_model`
(mặc định `claude-opus-4-8`). Trước khi viết code gọi API, kiểm tra docs hiện hành —
model id, pricing, prompt caching, tool use thay đổi theo thời gian (xem skill claude-api nếu có).

```python
from anthropic import Anthropic
from ..config.settings import settings

client = Anthropic(api_key=settings.anthropic_api_key)
```

## Bộ rules chất lượng — BẮT BUỘC áp cho mọi video

Trước khi sinh/duyệt kịch bản, đọc và tuân thủ [video-quality-rules.md](./video-quality-rules.md).
**CỔNG VERIFY (mục 0) chạy ĐẦU TIÊN:** mọi nội dung phải được kiểm tiêu chuẩn cộng đồng
YouTube, bản quyền (nhạc/hình/B-roll/quote), an toàn quảng cáo + COPPA, tính chính xác &
nguồn — TRƯỚC khi lên kịch bản. Mục FAIL thì dừng/sửa/loại ý tưởng, không viết script.
Sau đó mới tới các rule chất lượng:
hook gây sốc 3s đầu, cấu trúc có trục logic + câu "tại sao", nhịp cắt sớm, B-roll bám
nội dung (hình "cấm/nguy hiểm" cho điều cần tránh), CTA kết bằng câu hỏi mời comment.
Đưa các rule này vào prompt sinh kịch bản và rà checklist cuối file đó trước khi gửi
Telegram. Đây là rule CHUNG cho mọi chủ đề, không hard-code cho video lẻ.

**SERIES — một ngách xuyên suốt, các tập móc vào nhau (mục 0d):** kênh chạy theo series ngách
"phát triển bản thân THẬT, không self-help" (cơ chế con người). Mỗi tập đào **một cơ chế** chưa
trùng `data/ledger.md`, giọng/cấu trúc nhất quán, kết bằng **cầu nối tập sau** để kéo người xem
quay lại, gán playlist series. KHÔNG render badge "Tập n" trên hình. Đối chiếu ledger trước khi
viết để chống trùng.

**Cổng verify được ÉP ở code:** mỗi `scripts/*.json` PHẢI có khối `compliance`
với `passed: true` và ghi chú từng mục; `generator.load_script()` fail-fast nếu
thiếu khối này hoặc `passed != true` (nội dung FAIL phải sửa/loại, không nạp).

**Short (dọc) — ÉP độ dài 1–2 phút & KHÔNG badge số thứ tự:** Short KHÔNG khai báo
`target_minutes`; `load_script()` **fail-fast** nếu narration ước lượng ≤ 1 phút hoặc
≥ 2 phút (nhắm ~1.3–1.8 phút ≈ 1.600–2.150 ký tự). Renderer đã gỡ badge "n/total" — không
hiển thị đếm phần/tổng trên khung hình. Nội dung dù ngắn vẫn phải chi tiết, cụ thể (cơ
chế + con số/ví dụ thật + bước áp dụng), KHÔNG chung chung — xem mục **0b**, **2a** trong
video-quality-rules.md.

**Video dài (ngang) — ÉP độ dài & độ sâu:** khi lệnh yêu cầu video ngang/dài, kịch bản
PHẢI đặt `"target_minutes"` (10–30) ở gốc JSON và viết narration đủ dày (~1.200 ký tự/phút,
10 phút ≈ 12.000 ký tự, chia 20–40+ section). `load_script()` **fail-fast** nếu nội dung
mỏng hơn target. Bắt buộc đào sâu mỗi luận điểm (cơ chế → bằng chứng có nguồn → ví dụ thực
tế → bước áp dụng), KHÔNG nói chung chung — xem mục **2b** trong video-quality-rules.md.

```json
"compliance": {
  "passed": true,
  "community": "PASS — không bạo lực/thù ghét/nguy hiểm",
  "copyright": "PASS — TTS tự sinh, B-roll stock/AI có license",
  "accuracy": "PASS — đã kiểm số liệu/tuyên bố + nguồn",
  "advertiser": "PASS — advertiser-friendly",
  "coppa": "made for kids = no",
  "notes": "ghi chú/nguồn"
}
```

## Nguyên tắc prompt

- **Tách prompt khỏi code**: giữ template ở module riêng/constant, không nhúng chuỗi dài rải rác.
- **Yêu cầu output có cấu trúc** (JSON / tool use) để parse an toàn thay vì regex text tự do.
- **Validate output LLM** trước khi đưa vào `VideoIdea`/`Script` — không tin dữ liệu sinh ra.
- Tối ưu title/tags cho SEO ngay từ khâu này (đồng bộ với [[youtube-monetization]]).
- **`tags` PHẢI có 5–8 từ khoá** (không cần gõ dấu `#`, viết tag thường, không
  ký tự đặc biệt) — `publish/uploader.py::_build_hashtags()` TỰ ĐỘNG biến 3 tag
  ĐẦU TIÊN thành hashtag chèn vào mô tả (Short luôn có thêm `#Shorts` đứng đầu).
  Vì vậy đặt 2–3 tag **rộng + đúng ngách nhất** lên đầu mảng `tags` (vd
  `"tâm lý học"`, `"phát triển bản thân"`), các tag ngách hẹp/đặc thù tập đó
  để sau — thứ tự trong JSON quyết định hashtag nào lên hiển thị phía trên tiêu đề.

## Pattern dữ liệu

```python
def write_script(idea: VideoIdea) -> Script:
    result = client.messages.create(...)   # output có cấu trúc
    body, sections = parse_and_validate(result)
    return replace(Script(**vars(idea)), body=body, sections=tuple(sections))
```

## Cổng duyệt Telegram (bước 3)

Sau khi có `Script`, **không render ngay**. Gửi bản đầy đủ cho user duyệt và chờ.
Vòng lặp duyệt–sửa:

```python
from ..config.settings import settings
from ..notify.telegram import request_approval, Decision, send_message

def approve_script(script: Script, regenerate) -> Script:
    """Chờ user duyệt qua Telegram. `regenerate(instruction)` sửa prompt + sinh lại."""
    if not settings.telegram_approval:
        return script  # tắt cổng -> qua luôn
    current = script
    while True:
        body = _format_full(current)            # title + tags + toàn bộ sections
        verdict = request_approval(current.title, body)
        if verdict.decision is Decision.APPROVED:
            send_message("✅ Đã duyệt. Bắt đầu render.")
            return current
        # user yêu cầu sửa -> đưa instruction vào prompt, sinh lại
        current = regenerate(current, verdict.instruction)
        send_message("✏️ Đã sửa theo yêu cầu, gửi lại bản đầy đủ để duyệt…")
```

Quy ước phản hồi (xem `notify/telegram.py`):
- User gõ `OK` / `duyệt` / `yes` … → `Decision.APPROVED`.
- Mọi text khác → `Decision.REVISE`, nội dung = `verdict.instruction` (yêu cầu sửa).

Khi sửa: **đưa `instruction` vào prompt** (ví dụ append "Yêu cầu chỉnh sửa từ
biên tập: …"), gọi lại LLM, build `Script` mới qua `replace()` (không mutate bản cũ),
rồi gửi **bản đầy đủ đã sửa** — không chỉ gửi phần thay đổi.

`_format_full` phải gửi đủ: title, tags, và toàn bộ narration từng đoạn — để user
duyệt được trên điện thoại mà không cần mở máy.

## Checklist

- [ ] Kịch bản thoả [video-quality-rules.md](./video-quality-rules.md) (hook/CTA/B-roll/nhịp)
- [ ] Output LLM được validate trước khi build model
- [ ] Tôn trọng chuỗi dataclass bất biến ([[youtube-pipeline-core]])
- [ ] API key đọc từ `settings`, không hardcode
- [ ] Xử lý lỗi API (rate limit, refusal, cutoff) tường minh
- [ ] Cổng Telegram: gửi BẢN ĐẦY ĐỦ, chờ duyệt, sửa theo yêu cầu rồi gửi lại
- [ ] Token/chat_id Telegram đọc từ `settings`, không hardcode
- [ ] Tôn trọng `settings.telegram_approval` (tắt được khi chạy CI/test)
