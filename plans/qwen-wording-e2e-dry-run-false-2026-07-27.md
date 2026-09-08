# Kế hoạch E2E Qwen3.6:27b + Wording Layer

## Mục tiêu và giới hạn

Kiểm chứng một video Short đi qua toàn bộ luồng thật:

`Qwen3.6:27b → Wording Layer 2 → QA contract → TTS → STT verify → render → publish`

`DRY_RUN=false` chỉ được bật ở cổng publish cuối cùng, cho đúng **một video test**. Đây là upload thật lên YouTube; không chạy `--loop`, không chạy nhiều worker, không dùng lại queue sản xuất.

## Các bước thực hiện

1. **Cô lập bài test**
   - Tạo batch key mới, ví dụ `qwen_wording_e2e_2026-07-27`.
   - Không resume các batch cũ và không dùng `shorts_funnel_batch_2026-08-06`/`week5`.
   - Chụp snapshot `assets/auto_state.json`, `data/ledger.md`, `assets/batch_cli_warnings.log`; xác nhận không có worker đang chạy.
   - Chọn một chủ đề đúng ngách, chưa trùng ledger; chỉ tạo 1 Short.

2. **Preflight Qwen thật**
   - Xác nhận Ollama đang có `qwen3.6:27b`, provider là `ollama`, model trả response không rỗng.
   - Ghi nhận model, latency, token usage (nếu có), prompt hash và raw response hash.
   - Nếu Qwen lỗi/empty/timeout: dừng tại đây; không tự fallback sang Claude/Codex vì sẽ làm bài test mất giá trị.

3. **Chạy Wording Layer 2 ngay sau raw generation**
   - Gọi `process_and_sanitize(raw_llm_output)` đúng một lần trước QA.
   - Kiểm tra định lượng: JSON hợp lệ; slug ASCII kebab-case; không còn stage direction; hook không cliché; CTA cuối dưới 12 từ; narration giữ dấu tiếng Việt.
   - Chạy lần hai để kiểm tra tính idempotent (kết quả không đổi). Ghi lại mọi flag `_wording_engine`.
   - Nếu flag encoding hoặc contract còn lỗi: fail closed trước TTS, chỉ sửa đúng field cần sửa; không sinh lại toàn bộ script.

4. **QA contract và traceability**
   - Xác nhận ruleset hiện hành, một cơ chế duy nhất, core answer xuất hiện trong 5 giây đầu, đủ section/time goal, source trace và liên kết Short→Long.
   - Kiểm tra không trùng ledger, đúng định dạng Short dọc, metadata/thumbnail contract đầy đủ.
   - Lưu báo cáo QA trước khi cho phép TTS.

5. **TTS thật + STT kiểm chứng**
   - Dùng provider/voice đang cấu hình, sinh audio một lần.
   - Chạy STT cục bộ trên audio; so transcript với narration đã sanitize (chuẩn hóa khoảng trắng và dấu câu trước khi tính sai khác).
   - Gate: không mất câu/đoạn, không có khoảng lặng bất thường, core answer vẫn đến sớm, âm lượng và duration nằm trong contract.
   - Nếu lỗi, chỉ sửa audio/nhịp hoặc field liên quan; không gọi lại LLM và không voiceover lại toàn bộ nếu không có phê duyệt riêng.

6. **Render và kiểm tra hình ảnh**
   - Chạy `--through render --workers 1`, vẫn giữ `DRY_RUN=true` ở giai đoạn này.
   - Dùng `ffprobe`/QA để xác nhận portrait, fps, duration 60–90 giây, có audio, thumbnail đọc được và không có khung Long bị render dọc.
   - Xem preview thực tế; nếu fail thì sửa render asset/config và render lại cùng script/audio đã đạt gate.

7. **Publish preflight (chưa upload)**
   - Xác nhận OAuth đúng channel, title có tiền tố dễ nhận diện `[E2E TEST]`, privacy mặc định `private` hoặc `scheduled` theo quyết định của người dùng.
   - Kiểm tra chính xác file mp4/thumbnail, description, tags, publishAt (nếu schedule), và đảm bảo chỉ có 1 item pending.
   - Đây là cổng bắt buộc để người dùng xác nhận trước side effect ngoài hệ thống.

8. **Upload thật có kiểm soát**
   - Sau khi confirm: `DRY_RUN=false`, `--through publish`, `--workers 1`, batch key test, không `--loop`.
   - Chỉ upload một video; không retry tự động nếu API trả kết quả không rõ.
   - Ghi video ID, URL, privacyStatus, publishAt và request/result hash.

9. **Verify sau publish và kết thúc**
   - Đọc lại video qua API để xác minh ID/title/privacy/schedule; đối chiếu ledger và auto_state.
   - Xác nhận đúng 1 upload, không duplicate, không thay đổi queue sản xuất.
   - Lưu artifact: raw Qwen, sanitized JSON, wording flags, QA, STT diff, ffprobe, publish response, log và latency.
   - Nếu upload thành công nhưng verify thất bại: không upload lại; chuyển sang reconcile thủ công.

## Acceptance criteria

- Model thực tế đúng `qwen3.6:27b`, raw output không rỗng.
- Wording Layer sửa deterministic và idempotent; không còn flag lỗi nghiêm trọng.
- QA, TTS/STT và render đều pass trước publish.
- Có đúng một upload thật, trạng thái/quy lịch xác minh được.
- Không gọi LLM repair toàn bộ script; không voiceover lại ngoài phạm vi lỗi được chỉ định.

## Điểm dừng an toàn

Bất kỳ lỗi nào ở Qwen, wording, contract, OAuth, render hoặc verify đều dừng tại gate tương ứng. Không đổi lịch, không xoá video, không retry publish và không chạm batch sản xuất nếu chưa có quyết định mới.
