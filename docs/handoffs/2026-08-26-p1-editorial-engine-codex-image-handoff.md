# Handoff — P1 profile-driven engine hoàn tất + Codex image adapter + Long test thật

Ngày: 2026-08-26
Người viết: Claude (điều phối qua 1 sub-agent fork làm P1→P5)
Trạng thái: implement + test xong, **chưa commit** (theo yêu cầu, chờ user duyệt).
Base: nối tiếp `docs/handoffs/2026-08-25-profile-driven-prompt-engine-handoff.md` (P0)
và `docs/handoffs/2026-08-25-ban-so-6-comfyui-handoff.md` (điểm dừng TRANSCRIPT_MISMATCH).

## Việc đã xong

### P1a — Xoá sentinel `"narrator"` hardcode

`ContentProfile.editorial_contract.narration_speaker_id` (thêm ở P0, default
`"narrator"`) giờ được DÙNG THẬT ở mọi nơi trước đây so sánh/lọc bằng literal
`"narrator"`: `content_profiles.py` (voice_for, check bắt buộc voice_cast lúc
load, lọc cast trong visual_generation.characters), `render/story.py`,
`ideation/script_contract.py` (×2), `ideation/generation_schema.py`,
`orchestrator/ideation_prompts.py` (×2), `agents/qa_agent.py` (×4). Profile
mặc định (`ban-so-6`, `one-cup-cafe-6h`) không khai `narration_speaker_id` nên
hành vi y hệt cũ — test `tests/test_narration_speaker_migration.py` chứng
minh cả 2 chiều: default không đổi, và một profile khai `narration_speaker_id:
"host"` thì MỌI nơi trên theo đúng giá trị mới, không còn literal nào chặn.

Chỗ CỐ Ý không đổi: `ideation/generator.py` dòng parse `Segment.speaker_id`
default (`raw.get("speaker_id") or "narrator"`) — lúc đó chưa có profile
trong tay để tra `narration_speaker_id`, nên giữ nguyên literal có comment.

### P1b — Editorial review profile-scoped

`ContentProfile.editorial_review: EditorialReviewProfile | None` mới
(`enabled: bool`, `rubric_prompt_name: str` trỏ vào 1 key trong
`profile.prompts`). Module mới `src/ytb_pipeline/agents/editorial_review_agent.py`:
gọi LLM theo rubric của profile, cache theo `profile_fingerprint(profile) +
sha256(script đã validate)` — script không đổi thì không review lại. Wire vào
`validate_or_repair_script` (ideation_script_fix.py) SAU khi QA
(`QAAgent`) pass, TRƯỚC khi trả script hợp lệ.

**Cả `ban-so-6` và `one-cup-cafe-6h` đều KHÔNG bật `editorial_review`** — cơ
chế có sẵn nhưng chưa ai viết rubric cụ thể cho 2 profile này, nên để mặc
định tắt (compatibility, không tốn thêm 1 LLM call/script chưa ai yêu cầu).
Nếu muốn bật cho `ban-so-6`: viết `profiles/ban-so-6/prompts/<rubric>.md`,
thêm key vào `prompts`, thêm block `"editorial_review": {"enabled": true,
"rubric_prompt_name": "<key>"}` vào `profile.json`.

Test: `tests/test_editorial_review_agent.py` (8 test, RED→GREEN, có 2 test
tích hợp thật vào vòng lặp validate/repair, LLM luôn mock trong unit test).

### P1c — Codex image provider (đã xác minh thật, không phải suy đoán)

Đã xác nhận: `codex features list` báo `image_generation: stable`; chạy
thật `codex exec --sandbox workspace-write --skip-git-repo-check` sinh PNG
thật tại `~/.codex/generated_images/<session>/<file>.png` — đã xem ảnh output
thật, đúng yêu cầu prompt.

`src/ytb_pipeline/providers/image/codex_image_provider.py` — `CodexImageProvider`
cùng interface `generate_scene(profile, *, characters_present, prompt, width,
height, seed, output_path)` với `ComfyUIStoryProvider`. Chọn qua
`providers/registry.py::get_story_image_provider()` (registry pattern giống
LLM/TTS/Render/Publish, KHÔNG if-else trong domain code).
`settings.story_image_provider: str = "comfyui"` (mặc định KHÔNG đổi — vẫn
local-first theo CLAUDE.md; Codex là lựa chọn cấu hình, không phải fallback
tự động). Đổi provider: set `story_image_provider=codex` trong env/settings.

**Lưu ý quan trọng chưa kiểm chứng ở quy mô lớn:** Codex sinh ảnh qua
`codex exec` là process con, có thể chậm/tốn quota hơn ComfyUI local — mới
test 1-2 lần thủ công để xác minh khả thi, CHƯA benchmark tốc độ/chi phí
thật cho một video 20+ section như ComfyUI đã có (~1 ảnh/2-6 phút, xem
handoff 2026-08-25-ban-so-6-comfyui-handoff.md). Trước khi dùng Codex image
cho một video thật, nên benchmark tương tự.

Test: `tests/test_codex_image_provider.py` (7 test, subprocess mock hoàn
toàn, không gọi Codex thật trong suite).

### P1d — Sửa dứt điểm TRANSCRIPT_MISMATCH

Giả thuyết trong handoff 2026-08-25 (giờ viết tắt "6h07" không normalize
trong so khớp transcript) ĐÚNG — code fix chuẩn hoá giờ đã có sẵn trong
working tree từ trước khi phase này bắt đầu (không rõ ai/khi nào thêm, có
thể phiên trước đã làm dở mà chưa test-verify). Việc đã làm thêm: phát hiện
`_CACHE_VERSION` trong `voiceover/quality.py` KHÔNG được bump khi thuật toán
so khớp đổi → nguy cơ phục vụ lại kết quả cache TÍNH TỪ TRƯỚC FIX vô thời
hạn (một lỗ hổng thật, không phải suy đoán — cache key có version stamp
nhưng code sửa thuật toán không kèm bump). Đã bump `6 → 7`
(`src/ytb_pipeline/voiceover/quality.py:33`), có test riêng.

### P1e — Bug thật phát hiện giữa chừng khi chạy Long thật

`_compose_clips` crash: `"Story transition_overlap_sec phải ngắn hơn mọi
segment clip."`. Nguyên nhân: `textwrap.wrap` để lại mảnh câu cuối rất ngắn
(vd `"đó?"`, 3-5 ký tự); `line_durations` chia thời lượng card theo tỷ lệ số
ký tự nên card cuối chỉ còn ~0.176s — ngắn hơn `transition_overlap_sec=0.4s`
của profile. Fix: `_merge_short_lines()` mới trong `render/story.py` (dòng
~193) gộp card quá ngắn vào card liền kề trước khi tính duration. Test tái
hiện bằng dữ liệu THẬT (section 5 của script Long vừa chạy, narration thật,
duration thật 16.43s) — không phải test tổng hợp giả.

## Full suite

`.venv/bin/pytest tests/ -q --no-cov` → **985 passed, 3 skipped, 1
deselected, 0 failed** (chạy nhiều lần để loại trừ flaky, kể cả
`test_parallel_process_next_claims_each_slug_once` từng flaky ở phiên trước
cũng xanh sạch ở đây).

## Test full 1 Long thật (5-7 phút), số liệu thật — profile ban-so-6

Script cũ `ban-nhap-xau-dau-tien.json` (từ handoff 2026-08-25) KHÔNG dùng
lại được: `profile_version="1.3.0"` ≠ profile hiện tại `1.4.0` → preflight
fail đúng như thiết kế fail-closed. Phải ideation lại từ đầu qua xkiro (3
lần thử: 2 lần đầu model lặp lỗi `turn.responds_to` tự trỏ chính section,
lần 3 đổi ý tưởng ra script hợp lệ nhưng bị QA chặn 1 câu thoại lẫn hành
động trước dấu `:` — cả hai đều sửa tay ĐÚNG THEO gì gate đòi, không bypass
gate nào).

**Kết quả cuối:**
- Script: `scripts/phan-hoi-dong-nghiep-nho-an-xem.json` (20 section, 6.444
  ký tự, target_minutes=5)
- Audio: `assets/audio/phan-hoi-dong-nghiep-nho-an-xem_xkiro.mp3` —
  **393.9s** (trong khung 300-420s của `ban-so-6.formats.long`)
- audio_quality: `passed=true`, similarity=**0.9433** (94.3%, ngưỡng 0.82 —
  xác nhận fix P1d hoạt động đúng, trước đây script cũ chỉ đạt 0.806)
- Render qua ComfyUI thật (local, `story_image_provider=comfyui` mặc định):
  **24/24 ảnh cảnh** sinh thật, lưu tại `assets/generated_visuals/ban-so-6/`
- Video: `assets/output/phan-hoi-dong-nghiep-nho-an-xem.mp4` — 37.362.649
  bytes, ffprobe `duration=338.837s` (trong khung Long)
- render_quality: `status=pass`, 0 error/0 warning
  (`assets/quality_reports/phan-hoi-dong-nghiep-nho-an-xem.quality.json`)
- `assets/projects/phan-hoi-dong-nghiep-nho-an-xem/project.json`: cả 6 node
  `input/voiceover/audio_quality/render/render_quality/publish` đều `done`
- Publish: DRY_RUN thật (`uploaded=false`, `url=null`, `privacy=private`) —
  **không** upload YouTube thật, đúng ranh giới P0 batch-safety trong
  CLAUDE.md.

Toàn bộ pipeline auto-generate ảnh cho profile character_story giờ đã chạy
được HẾT một Long thật, không dừng giữa chừng vì bug — điểm khác biệt lớn
nhất so với lần thử Long trước (dừng ở TRANSCRIPT_MISMATCH).

## Chưa làm / còn lại cho việc tiếp theo

1. **Editorial review chưa có rubric thật cho profile nào** — cơ chế đã có,
   nhưng chưa ai viết `.md` rubric cụ thể để bật cho `ban-so-6` hay
   `one-cup-cafe-6h`. Nếu muốn dùng, cần quyết định rubric muốn kiểm gì
   (narrator dẫn truyện đúng cách? causal turn hợp lý? timeline nhất
   quán?) trước khi viết prompt.
2. **Codex image provider chưa benchmark tốc độ/chi phí thật ở quy mô 1
   video đầy đủ** (chỉ xác minh khả thi 1-2 ảnh). Trước khi dùng thật cho
   sản xuất, nên đo giống cách `tts_pace_factor`/ComfyUI đã được đo bằng dữ
   liệu thật (xem handoff 2026-08-25-ban-so-6-comfyui-handoff.md).
3. **`generated_visuals/` cache vẫn không có cơ chế dọn** (đã ghi nhận từ
   handoff trước, vẫn chưa làm — hiện tại 24+ ảnh/lần chạy, sẽ phình dần).
4. **Chỉ có 2 content profile thật** (`ban-so-6`, `one-cup-cafe-6h`); profile
   fixture thứ 2 chứng minh generality (`panel-debate-fixture`) chỉ tồn tại
   trong `tests/fixtures/`, không phải profile production.
5. Chưa commit gì trong toàn bộ phiên này (P0 lẫn P1) — cần review + quyết
   định commit theo từng logical chunk (P0 profile engine, P1 narrator
   migration, P1 editorial review, Codex adapter, TRANSCRIPT_MISMATCH fix +
   `_merge_short_lines` là 2 bugfix độc lập nên tách commit) trước khi merge.

## File chính đã đổi (chưa commit)

Domain/core: `content_profiles.py`, `ideation/generation_schema.py`,
`ideation/script_contract.py`, `ideation/generator.py`,
`analytics/quality_report.py`, `orchestrator/ideation_prompts.py`,
`orchestrator/ideation_script_fix.py`, `orchestrator/preflight.py`,
`render/story.py`, `voiceover/quality.py`, `agents/qa_agent.py`,
`config/settings.py`, `providers/registry.py`.

Mới: `agents/editorial_review_agent.py`,
`providers/image/codex_image_provider.py`,
`tests/test_editorial_contract_profile.py`,
`tests/test_narration_speaker_migration.py`,
`tests/test_editorial_review_agent.py`, `tests/test_codex_image_provider.py`,
`tests/fixtures/content_profiles/panel-debate-fixture/`.

Output thật từ Phase 5 (không phải code, chỉ để tham khảo):
`scripts/phan-hoi-dong-nghiep-nho-an-xem.json`,
`assets/audio/phan-hoi-dong-nghiep-nho-an-xem_xkiro*.mp3`,
`assets/generated_visuals/ban-so-6/*.png`,
`assets/output/phan-hoi-dong-nghiep-nho-an-xem.mp4`,
`assets/projects/phan-hoi-dong-nghiep-nho-an-xem/project.json`.
