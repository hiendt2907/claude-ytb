# Handoff — Timeline Phase 1 MVP (story renderer)

Ngày: 2026-08-27
Người viết: Claude
Trạng thái: implement + test xong. `make test`: 1065 passed, 3 skipped, 1
deselected, 0 failed. Chưa commit khi viết file này (commit ngay sau).
Nối tiếp: `docs/handoffs/2026-08-27-ai-content-factory-architecture-assessment.md`
(đánh giá kiến trúc) → chỉ thị implementation "Phase 1: Explicit Timeline
MVP" từ user, giới hạn nghiêm ngặt (đã liệt kê 13 điều KHÔNG làm trong phase
này — xem checklist cuối file).

## Việc đã làm

1. **File mới `src/ytb_pipeline/render/timeline.py`** — `VideoClip`,
   `NarrationClip`, `Transition`, `Timeline` (frozen dataclass, dữ liệu domain
   thuần: không chuỗi shell, không FFmpeg filter graph, không LLM prose,
   không config ComfyUI), `build_story_timeline(voiceover, profile, *, fps,
   width, height) -> Timeline` (hàm thuần, đây là ranh giới "TimelineBuilder"),
   `Timeline.write_json()`/`read_json()` cho persistence.
2. **Sửa `src/ytb_pipeline/render/story.py`** — CHỈ file này bị đổi hành vi
   nội bộ (không đổi output ffmpeg/ảnh/caption):
   - Build + validate `Timeline` ngay đầu `render_story_video()`, trước khi
     bất kỳ lệnh ffmpeg nào chạy.
   - Ghi `timeline.json` cạnh `<slug>.mp4`/`<slug>_thumb.jpg` trong
     `output_dir` (không đụng `assets/projects/<slug>/`).
   - `gap` trong vòng lặp per-section giờ đọc từ `timeline.transitions[i].gap_sec`
     thay vì tính lại bằng điều kiện `index < len(segments)-1` tại chỗ.
   - Thêm 1 assertion cấu trúc ngay trước `_compose_clips()`: số section clip
     thật dựng được phải khớp `len(timeline.video_clips)` — chặn đúng lớp lỗi
     lịch sử (card bị coi là section) một lần nữa, sát điểm encode cuối nhất.
3. **Test mới `tests/test_render_timeline.py`** — 12 test đơn vị thuần (không
   ffmpeg/TTS/network), phủ đủ 9 case Directive yêu cầu + case biên
   (thiếu audio, round-trip JSON).
4. **Test sửa `tests/test_profile_multivoice_render.py`** — thêm assertion
   vào test tích hợp thật đã có (`..._preserves_audio_timeline_when_a_section_
   has_many_caption_cards`) xác nhận `timeline.json` được ghi ra đúng, khớp
   công thức `expected_story_duration_sec` đã được test này tin cậy từ trước
   — đây là bằng chứng tương thích (case #10), không viết fixture render mới.
5. **Tài liệu** — thêm mục "Timeline — story renderer" vào
   `docs/constitution/03-ARCHITECTURE.md`, phát biểu đúng câu Directive yêu
   cầu: *Narration = timing authority; Timeline = deterministic derived
   execution plan; Renderer = Timeline consumer.*

## Bằng chứng hồi quy lớp lỗi lịch sử

`test_excessive_cumulative_transitions_cannot_silently_shorten_the_output`
(`tests/test_render_timeline.py`) dựng thẳng một `Timeline` 3-clip đúng, rồi
thử nhét thêm 1 transition trùng vào cùng ranh giới (đúng hình dạng lỗi thật:
nhiều transition hơn số ranh giới section thật) — `Timeline(...)` phải raise
`TimelineError` ngay tại construction, trước khi chạm ffmpeg. Không cần tái
tạo asset lịch sử thật, theo đúng yêu cầu Directive.

## Quyết định persistence: B (persist), không phải A (ephemeral)

Lý do: cải thiện debug/postmortem/reproducibility mà Directive liệt kê,
đúng như đề xuất ở §C/§N của bản đánh giá kiến trúc trước đó. Ghi
`assets/output/<slug>_timeline.json` — cùng thư mục, cùng quy ước đặt tên với
`<slug>_thumb.jpg` đã có — **không** ghi vào `assets/projects/<slug>/` để
tránh tạo thêm phụ thuộc mới từ `render/story.py` vào cấu trúc project
directory, và không tạo 2 nguồn sự thật cạnh tranh: `Timeline` không được đọc
lại bởi bất kỳ bước nào khác trong pipeline ở Phase 1 này — thuần là artifact
debug, rebuild lại mỗi lần render (`source_fingerprint` field ghi lại hash
input để biết file đã lạc hậu hay chưa nếu người xem lại sau này).

## Checklist "Definition of Done" đối chiếu

1. ✅ `story.py` đọc `gap`/số clip từ Timeline, không tự tính index-boundary.
2. ✅ Timeline dựng thuần, có test đơn vị.
3. ✅ Có test hồi quy đúng lớp lỗi lịch sử.
4. ✅ Hành vi video/ảnh/caption không đổi — 2 test tích hợp thật (ffmpeg
   thật) đã có từ trước vẫn pass y nguyên, chỉ thêm assertion mới, không sửa
   assertion cũ.
5. ✅ Không đụng `project.json`/`scripts/<slug>.json`/Script dataclass nào.
6. ✅ `render_validation_max_drift_sec` (kiểm tra cuối pipeline) không đổi,
   không đụng `pipeline.py`/`render/validation.py`.
7. ✅ Không thêm provider mới, không đổi hành vi editorial.
8. ✅ `make test`: 1065 passed, 0 failed.
9. ✅ Tài liệu ghi đúng 3 câu Narration/Timeline/Renderer (mục trên).
10. ✅ Dừng lại sau Phase 1 — không tự ý làm ScenePlan/AssetRegistry.

## Việc CHƯA làm trong phase này (đúng theo 13 điều cấm của Directive)

Không đụng: ComfyUI integration, ScenePlan, AssetRegistry, VisualRequest,
subtitle/music/SFX/AudioMixer, vertical recomposition, provider default,
editorial behaviour, Short generation, `ResearchAgent`, `compose_ai.py` (chỉ
đọc để hiểu bối cảnh, không sửa — không cần thiết cho Timeline v1 vì
`compose_ai.py` không dùng `render/story.py`).

## Việc ghi nhận làm nợ kỹ thuật (follow-up, không mở rộng phạm vi phase này)

- `compose_ai.py`/`compose.py` (renderer mechanism_explainer) vẫn chưa có
  Timeline — vẫn tự tính timing arithmetic inline như trước. Đây là phạm vi
  Directive cố tình loại trừ ("The first renderer migration target is
  render/story.py"), không phải bị bỏ sót.
- `Timeline` hiện chưa được `pipeline.py`/`render_evidence_for` đọc lại để
  làm cổng validate cấp pipeline (chỉ là artifact debug đứng riêng) — nếu
  muốn Timeline trở thành input CHÍNH cho `validate_final_video`/`render_
  evidence_for` sau này, đó là quyết định Phase 2+ cần duyệt riêng.
