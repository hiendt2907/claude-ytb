# Handoff — ScenePlan Phase 2 MVP (story renderer)

Ngày: 2026-08-27
Người viết: Claude
Trạng thái: implement + test xong. `make test`: 1084 passed, 3 skipped, 1
deselected, 0 failed. Nối tiếp: `docs/handoffs/2026-08-27-timeline-phase1-
handoff.md` (Timeline Phase 1) → chỉ thị "Implementation Directive — Phase
2: Explicit ScenePlan v1" từ user.

## Audit trước khi implement (yêu cầu của Directive)

1. `story.py` không còn tự tính duration/end-time/transition arithmetic
   nào có thể bất đồng với Timeline — `expected_story_duration_sec()` vẫn
   tồn tại nhưng chỉ còn được gọi bởi test (grep xác nhận không còn call
   site production), nên không có nguy cơ hai nguồn tính bất đồng trong
   runtime thật.
2. `Timeline.source_fingerprint` đã phủ đủ: narration timing (`audio_path`+
   `duration_sec` từng segment), profile render timing (gap/overlap), fps,
   width/height.
3. Không có mâu thuẫn đặt tên `timeline.json` vs `<slug>_timeline.json` —
   dòng docstring trong `timeline.py` chỉ bị word-wrap, nội dung thực đã
   đúng `<slug>_timeline.json`, khớp `story.py` và `03-ARCHITECTURE.md`.

Kết luận: không có lỗi correctness → vào thẳng Phase 2 theo đúng chỉ dẫn.

## Việc đã làm

1. **File mới `src/ytb_pipeline/render/scene_plan.py`** — `Shot`, `Scene`,
   `ScenePlan` (frozen dataclass, dữ liệu domain thuần: không FFmpeg, không
   ComfyUI config, không asset path bắt buộc), `build_story_scene_plan(
   voiceover, profile) -> ScenePlan` (ranh giới "ScenePlanBuilder", THUẦN —
   không LLM, không DirectorAgent). v1: đúng 1 scene/segment, đúng 1
   shot/scene, phủ trọn narration window của segment — không đổi hành vi
   sản xuất hiện tại, chỉ tường minh hoá quyết định renderer đã ngầm làm.
2. **Sửa `src/ytb_pipeline/render/timeline.py`** — thêm
   `build_story_timeline_from_scene_plan(scene_plan, voiceover, profile,
   *, fps, width, height) -> Timeline`, đây là builder THẬT giờ đây tiêu
   thụ ranh giới scene của `ScenePlan` thay vì tự đọc lại `voiceover.
   segments` để suy ra ranh giới. `build_story_timeline(...)` (chữ ký công
   khai Phase 1) trở thành compatibility wrapper: build ScenePlan ngầm rồi
   gọi hàm mới — chữ ký/test Phase 1 không đổi, hành vi số học giống hệt
   (v1 ScenePlan window == segment.duration_sec 1:1).
3. **Sửa `src/ytb_pipeline/render/story.py`** — build `ScenePlan` trước
   Timeline, ghi `assets/projects/<slug>/scene_plan.json` (thư mục
   per-project đã có sẵn `project.json`), rồi gọi
   `build_story_timeline_from_scene_plan(scene_plan, ...)` thay vì
   `build_story_timeline(...)` — Timeline giờ thật sự tiêu thụ ScenePlan,
   không phải dead metadata.
4. **Test mới `tests/test_render_scene_plan.py`** — 20 test đơn vị thuần,
   phủ đủ 14 case Directive yêu cầu (1 segment→1 scene, nhiều segment→scene
   có thứ tự xác định, alignment narration window, scene/shot ID xác định,
   fingerprint ổn định + đổi theo semantic input + đổi theo narration
   timing, character/visual_intent propagation, KHÔNG bị caption card làm
   phồng số scene, tương thích ScenePlan→Timeline, round-trip JSON, rebuild
   không cần đọc file nào) + case biên (thiếu segment, shot rỗng, shot
   duration không khớp window, segment_index trùng/sai thứ tự).
5. **Test sửa `tests/test_render_timeline.py`** — fixture `_segment()`
   thêm các field ScenePlan cần (`purpose`, `visual_intent`, `video_type`,
   `visual_asset`, `scene_characters`); 1 test đổi kỳ vọng exception từ
   `TimelineError` sang `ScenePlanError` (ranh giới raise sớm hơn 1 bước
   khi segments rỗng — vẫn `ValueError`, vẫn raise trước mọi ffmpeg call).
6. **Test sửa `tests/test_profile_multivoice_render.py`** — thêm
   `monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")`
   vào cả 3 test tích hợp thật gọi `render_story_video`/`StoryRenderProvider
   .render` (xem mục "Sự cố phát hiện khi test thật" dưới), và thêm
   assertion `scene_plan.json` được ghi đúng + số scene khớp số section
   thật (2), không bị 162-card fixture làm phồng.
7. **Tài liệu** — thêm mục "ScenePlan — story renderer (Phase 2 MVP)" vào
   `docs/constitution/03-ARCHITECTURE.md`, phát biểu đúng 5 tầng
   Script/Narration/ScenePlan/Timeline/Renderer.

## Sự cố phát hiện khi test thật (đã fix trong phiên này)

Lần chạy test tích hợp thật đầu tiên sau khi thêm `story.py` ghi
`scene_plan.json` đã **ghi thật vào `assets/projects/timeline/scene_plan.
json` trong chính repo** — vì 3 test tích hợp thật trong
`test_profile_multivoice_render.py` monkeypatch `content_profiles_dir`
nhưng KHÔNG monkeypatch `projects_dir` (mặc định `assets/projects`, path
tương đối, KHÔNG trỏ vào `tmp_path`). Đã: xoá thư mục rò rỉ
(`assets/projects/timeline/`) ngay lập tức, và thêm monkeypatch
`projects_dir` vào cả 3 test để cách ly hoàn toàn khỏi filesystem thật.
Xác nhận lại bằng `git status --short assets/` sau khi chạy lại toàn bộ
`test_profile_multivoice_render.py` — không còn thư mục nào rò rỉ.

## Bằng chứng zero-behavior-change

Cả 3 test tích hợp ffmpeg thật (`test_story_renderer_uses_profile_assets_
and_real_segment_audio`, `..._preserves_audio_timeline_when_a_section_has_
many_caption_cards`, `..._keeps_video_and_audio_streams_in_sync_with_many_
cards_and_asymmetric_gap`) pass y nguyên với assertion cũ, chỉ thêm
assertion mới (scene_plan.json tồn tại + đúng nội dung). `make test`:
1084 passed (tăng từ 1065 baseline Phase 1 + test mới), 0 failed.

## Checklist "Definition of Done" đối chiếu

1. ✅ `ScenePlan` domain contract tường minh (`Shot`/`Scene`/`ScenePlan`).
2. ✅ Derive thuần từ Script + narration timing thật, không LLM.
3. ✅ Hành vi story render không đổi — test tích hợp thật pass nguyên vẹn.
4. ✅ `story.py` không còn tự suy ranh giới scene từ vòng lặp segment ngầm
   — build `ScenePlan` tường minh trước, Timeline đọc lại ranh giới đó.
5. ✅ Timeline tiêu thụ ScenePlan thật (`build_story_timeline_from_scene_
   plan`), không phải dead metadata.
6. ✅ Scene/Shot ID xác định (`scene-{index:03d}`, không UUID ngẫu nhiên).
7. ✅ Persist/rebuild được, không phải nguồn sự thật thứ hai — luôn rebuild
   mới mỗi lần render, file chỉ là debug artifact.
8. ✅ Project cũ (không có `scene_plan.json`) không hỏng gì — không có
   stage nào đọc lại file này.
9. ✅ Test hồi quy giữ đúng bất biến "số scene khớp số segment ngữ nghĩa,
   không khớp số caption card" — cả ở tầng đơn vị (`test_scene_count_
   never_depends_on_caption_card_count`) lẫn tích hợp thật (assertion mới).
10. ✅ `make test`: 1084 passed, 0 failed.
11. ✅ Không thêm LLM/provider/editorial behaviour nào.
12. ✅ Dừng lại sau Phase 2 — không tự ý làm AssetRegistry/VisualRequest.

## Việc CHƯA làm trong phase này (đúng theo non-goals của Directive)

Không đụng: DirectorAgent, LLM call mới, AssetRegistry, VisualRequest,
ComfyUI workflow, seed/reproduction registry, semantic visual QC, subtitle/
music/SFX/AudioMixer, Short asset reuse, smart crop, Flux/Wan/LTX,
ResearchAgent, `compose_ai.py`/`compose.py` Timeline migration (vẫn tự tính
timing arithmetic inline như trước — phạm vi Directive cố tình loại trừ),
frontend/MCP, provider defaults, editorial behaviour.
