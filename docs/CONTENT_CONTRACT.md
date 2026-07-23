# Content Contract — 1 Cốc Café 6h

**Ruleset:** `2026-07-23.1`  
**Machine authority:** `src/ytb_pipeline/content_contract.py`

Đây là nguồn chuẩn duy nhất cho prompt, loader, Script QA, TTS QA, Render QA và
release. Tài liệu kỹ năng chỉ diễn giải; nếu có khác biệt, code ruleset này thắng.

## Format và timeline

| Format | Khung người xem thấy | Audio trước crossfade | Cấu trúc tối thiểu |
| --- | --- | --- | --- |
| Short | 60–90 giây, dọc | cộng `0.4s × (số section − 1)` | 6 section |
| Long | 12–15 phút, ngang | cộng `0.4s × (số section − 1)` | 24 section |

Audio phải được bù phần overlap của renderer để video cuối vẫn nằm đúng khung.
Character budget luôn được tính theo provider TTS đang bật; F5 hiện 2.000 ký tự/phút,
Edge 1.197 ký tự/phút. Duration đo từ file là quyết định cuối cùng.

## Nội dung và funnel

- Một video chỉ giải thích một cơ chế trung tâm, không khẩu hiệu self-help hay claim tuyệt đối.
- Long: tension/problem → cơ chế + bằng chứng → ví dụ → áp dụng/sai lầm → payoff + cầu nối.
- Short: visual tension bắt đầu ngay 0–2s; `core_answer` là section thứ hai và bắt đầu không muộn hơn 5s (prompt nhắm 4s).
- Mỗi Short mới bắt buộc có strategy, Long đích, playlist, CTA và source trace
  (`source_long_slug`, `source_section_index`, `source_excerpt`). Hai Short cùng Long phải lấy hai section nguồn khác nhau.
- Mọi script publishable cần `thumbnail_brief` gồm visual contradiction, subject, emotion và headline tối đa bốn từ.
- Claim số liệu, nghiên cứu, y tế, tài chính, pháp lý phải có nguồn truy được; finance psychology dùng `evidence_register` bắt buộc.

## Quality/release gates

1. **Trước TTS:** loader schema + strict Script QA: duration planning, hook, mechanism, compliance, funnel/source trace, thumbnail, CTA/payoff, visual query.
2. **Trước render:** audio file/segment, duration bù transition, hook onset thật, stage-direction leak, volume/silence; STT local là evidence có cache, không gọi cloud.
3. **Trước publish:** đúng orientation/duration, audio/video stream, thumbnail tồn tại và không blank, metadata hợp lệ, Script QA hash/ruleset khớp artifact hiện tại.
4. **Resume:** mọi thay đổi byte của script hoặc ruleset invalidate toàn bộ node downstream; không tái sử dụng audio/render cũ với script mới.

`report` chỉ lưu đo lường. Không được dùng nó để bỏ qua các structural/release gate.

## Lịch publish

Lịch là quyết định vận hành riêng và chỉ được gán bằng lệnh schedule rõ ràng **sau**
QA, render và asset hợp lệ. Không suy diễn cadence từ contract này.

# Recovery

Xem [RECOVERY_CONTRACT.md](RECOVERY_CONTRACT.md) để biết action tự động, retry limit và điều kiện escalation ở từng khâu. Recovery không được thay thế bất kỳ quality gate nào trong tài liệu này.
