# Content profile authoring template

Mục đích: dựng một profile mới **chỉ bằng dữ liệu** (`profile.json` + prompt
markdown), không sửa một dòng code engine nào — đúng nguyên tắc "Một DAG, N
content profile" trong `CLAUDE.md` và Giai đoạn 5 của
`docs/handoffs/2026-08-27-content-profile-engine-refactor-plan.md`.

File này được một test tự-kiểm-chứng
(`tests/test_content_profile_template.py::test_template_guide_documents_every_declared_field`)
đối chiếu với chính danh sách field trong `content_profiles.py` — nếu code
thêm field mới mà tài liệu này không được cập nhật, test đó FAIL. Đừng sửa
danh sách field bên dưới mà không chạy lại test đó.

Fixture loadable minh hoạ (chỉ field bắt buộc): `tests/fixtures/content_profiles/template-fixture/`.

## Khung tối thiểu (chỉ field bắt buộc)

```json
{
  "schema_version": 1,
  "profile_id": "ten-profile-cua-ban",
  "version": "1.0.0",
  "display_name": "Tên hiển thị",
  "topic": "Chủ đề tổng quát của profile",
  "narrative_mode": "mechanism_explainer",
  "prompts": { "editorial": "prompts/editorial.md" },
  "formats": {
    "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
    "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10}
  },
  "providers": {
    "llm": "xkiro", "tts": "xkiro", "render": "ai",
    "broll_strategy": "pexels", "broll_allow_downloads": false
  },
  "voice_cast": { "narrator": "confident-male-vietnamese" },
  "content_rules": {
    "require_pexels_query": true,
    "require_short_source_trace": true
  },
  "render": {
    "assets_dir": "assets",
    "show_captions": false,
    "inter_segment_gap_sec": 0.0,
    "transition_overlap_sec": 0.4
  }
}
```

`narrative_mode`: `"mechanism_explainer"` (không nhân vật tái diễn) hoặc
`"character_story"` (có cast tái diễn qua nhiều tập).

## Field-by-field (mọi field dataclass hiện có trong `content_profiles.py`)

### `formats.<short|long>` → `FormatProfile`
- `viewer_min_sec`, `viewer_max_sec` — cửa sổ thời lượng cho phép (giây).
- `min_sections` — số section tối thiểu.
- `max_sections` — tối đa; **bỏ qua thì mặc định bằng `min_sections`**.
- `runtime_tolerance_sec` (tuỳ chọn, mặc định `0.0`) — dung sai đo thời lượng
  thật so với sàn, dùng khi có sai lệch hệ thống đã đo được (không phải chỗ
  để nới lỏng gate tuỳ tiện).

### `providers` → `ProviderProfile`
- `llm`, `tts` — tên provider (hiện chỉ `"xkiro"`).
- `render` — chiến lược render: `"ai"` (mechanism_explainer), `"story"`
  (character_story), `"slide"` (legacy).
- `broll_strategy` — `"pexels"` hoặc `"none"`. Pexels KHÔNG BAO GIỜ là mặc
  định ngầm cho profile mới nếu không cố ý chọn (xem Key Invariants trong
  `CLAUDE.md`).
- `broll_allow_downloads` — luôn `false` trừ khi có lý do rõ ràng.
- `tts_pace_factor` (tuỳ chọn, mặc định `1.0`, khoảng `(0, 2]`) — hệ số bù
  tốc độ đọc thật đo được của giọng/kịch bản profile này so với hằng số CPM
  chung; chỉ đổi khi đã đo thật qua vài lần render, không đoán.

### `content_rules` → `ContentRules`
- `require_pexels_query` (bắt buộc) — mỗi section có cần `pexels_query`.
- `require_short_source_trace` (bắt buộc) — Short có cần trace về đúng một
  đoạn Long nguồn (strategy-v1) hay không.
- `require_conversation_turns` (mặc định `false`) — có cần cấu trúc lượt
  hội thoại (`turn`) giữa các cast hay không; thường `true` cho
  `character_story`.
- `allow_short_generation` (mặc định `true`) — `false` nếu series này chỉ
  còn sinh Long, không sinh Short mới (Short cũ vẫn đọc được).
- `story_primary_speaker_id` / `story_supporting_speaker_id` (mặc định
  rỗng) — key trong `voice_cast` cho vai chính/phụ của một
  `character_story`; để trống giữ hợp đồng cast cũ, lỏng hơn.
- `require_next_episode_bridge` (mặc định `false`) — đoạn kết một Long có
  bắt buộc nhắc điều tiếp diễn ở tập sau hay không.
- `narrator_lesson_closing` (mặc định `false`) — opt-in: đoạn kết là NGƯỜI
  DẪN CHUYỆN đúc kết bài học nói thẳng với người xem, thay vì hành động cụ
  thể của nhân vật. Chỉ bật cho `character_story`.
- `long_opening_mode` (mặc định `"channel_greeting"`, hoặc `"pain_first"` /
  `"story_context"`) — cách một Long mở đầu.
- `short_ending_mode` (mặc định `"final_action"`, hoặc `"funnel_bridge"`) —
  Short kết bằng hành động ngay hay bằng vòng lặp mở + CTA về Long nguồn.

### `voice_cast` — map `speaker_id` (lowercase) → tên giọng TTS.
Phải có ít nhất `"narrator"` (hoặc đúng tên đã khai ở
`editorial_contract.narration_speaker_id` nếu đổi khỏi mặc định).

### `render` → `RenderProfile`
- `assets_dir` — tên thư mục con chứa asset của profile (thường `"assets"`).
- `show_captions` — có hiện caption trên video không.
- `inter_segment_gap_sec`, `transition_overlap_sec` — khoảng trong `[0, 2]`
  giây, canh giữa các section khi ghép render.
- `scene_assets` (tuỳ chọn) — danh sách cố định tên file asset hợp lệ; bỏ

- `audio` (tuỳ chọn) — local background music và SFX rõ ràng cho story render;
  gồm `background_music` (`asset`, `gain_db`, fade, `mode`) và `sfx` events
  (`asset`, `at_sec`, `gain_db`, `duration_sec`). Không có `audio` giữ narration-only.
  trống thì mọi file trong `assets_dir` đều hợp lệ.

### `editorial_contract` (tuỳ chọn — bỏ qua thì dùng bộ mặc định legacy)
- `purpose_vocabulary` — tập purpose hợp lệ cho section (mặc định legacy:
  `situation, core_answer, evidence, application, payoff`).
- `required_purposes.short` / `.long` — purpose bắt buộc phải có theo format.
- `narration_speaker_id` (mặc định `"narrator"`) — speaker_id được coi là
  "người dẫn chuyện" xuyên suốt engine (QA, purpose gate, closing check).
- `short_expansion_purposes` — purpose được phép nhận thêm câu khi Short
  thiếu thời lượng cần vá.

### `format_prompts` (tuỳ chọn) → `{"short": "<tên prompt>", "long": "<tên prompt>"}`
Cho Long và Short dùng prompt cấu trúc RIÊNG thay vì gộp chung
`editorial`. Tên phải là một key đã khai trong `prompts`.

### `editorial_review` (tuỳ chọn) → `EditorialReviewProfile`
Cổng LLM chấm điểm rubric — đọc
`docs/constitution/38-EDITORIAL_QUALITY_LAYERS.md` trước khi bật, để biết
luật nào nên nằm ở đây thay vì ở QA heuristic.
- `enabled` — bật/tắt.
- `rubric_prompt_name` — key trong `prompts` chứa nội dung rubric.
- `minimum_score` (mặc định `0`) — điểm sàn `[0, 10]`.
- `max_rewrites` (mặc định `0`) — số lần cho phép LLM viết lại theo phản hồi
  rubric.

### `visual_generation` (tuỳ chọn, chỉ hợp lệ khi `narrative_mode == "character_story"`)
Sinh ảnh cảnh local qua ComfyUI/IPAdapter, neo danh tính nhân vật —
`enabled`, `style_prompt`, `negative_prompt`, `steps` (≥1), `cfg` `(0,30]`,
`solo_weight`/`duo_weight` `[0,2]`, `duo_denoise` `(0,1]`, `characters` (map
character id → đường dẫn ảnh neo trong `assets_dir`), `duo_reference_image`.

Phase 9 — đa candidate (tuỳ chọn, mặc định giữ nguyên hành vi 1-candidate cũ):
`candidate_count` (mặc định `1`, tối đa `4` — sinh N ứng viên tuần tự cho mỗi
shot thay vì 1 ảnh; ChỈ bật khi profile thực sự cần "sinh vài, chọn ảnh tốt
nhất", vì mỗi candidate tăng thời gian ComfyUI tuyến tính), `selection_policy`
(mặc định `"first_valid"` — duy nhất chính sách hợp lệ ở Phase 9, chọn
candidate hợp lệ theo index thấp nhất; chấm điểm ngữ nghĩa/VLM thật là Phase
10), `candidate_policy_version` (mặc định `"phase9-v1"` — nhận diện policy sinh
candidate nhưng không tự xoá candidate đã hợp lệ). Trạng thái
candidate lưu riêng mỗi project tại
`assets/projects/<slug>/visual_candidates.json` — không ghi vào
`AssetRegistry` hay `visual_manifest.json`. Xem
`docs/handoffs/2026-08-27-visual-candidates-phase9-handoff.md`.

Phase 10 — `selection_policy: "vlm_ranked"` (tuỳ chọn, yêu cầu khối
`visual_judge` con): `enabled`, `provider`, `model`, `policy_version` (bắt
buộc khi `enabled=true`), `minimum_score` (mặc định `0.5`, khoảng
`[0.0, 1.0]` — candidate dưới ngưỡng này không đủ điều kiện được chọn dù kỹ
thuật hợp lệ), `hard_fail_on_judge_error` (mặc định `false` — khi `false`,
lỗi hạ tầng VisualJudge (timeout/provider lỗi/response hỏng sau 1 lần repair)
rơi về `first_valid`; khi `true`, `visual_assets` fail closed thay vì fallback).
VisualJudge KHÔNG chấm điểm vẻ đẹp/sức hấp dẫn/tuổi/giới tính/chủng tộc — chỉ
chấm mức khớp yêu cầu và bố cục/kỹ thuật. Kết quả đánh giá lưu riêng mỗi
project tại `assets/projects/<slug>/visual_evaluations.json` — không ghi vào
`AssetRegistry` (provenance bất biến) hay `visual_manifest.json` (chỉ giữ
asset đã chọn cuối cùng). Xem
`docs/handoffs/2026-08-27-visual-judge-phase10-handoff.md`.

Phase 11 — production vision opt-in: đặt `provider: "xkiro"` và một `model`
được live xKiro catalog xác nhận `vision=true` (operator smoke đã xác minh
`qwen/qwen3.8-max:free`). Adapter dùng `XKIRO_API_KEY` hiện hữu, gửi byte
PNG/JPEG thật dưới dạng base64 `image_url`, và từ chối model text-only (bao gồm
model ideation mặc định `deepseek/deepseek-v4-pro`). Không profile nào tự động
được bật Judge; `candidate_count=1`, `first_valid`, `profile_local`, parent
reuse và prepared render vẫn zero-Judge. Kiểm tra ngoài test suite:

```bash
PYTHONPATH=src VISUAL_JUDGE_PROVIDER=xkiro \
VISUAL_JUDGE_MODEL='qwen/qwen3.8-max:free' \
.venv/bin/python -m ytb_pipeline.tools.smoke_visual_judge --generate-probe
```

Phase 12 — phục hồi semantic rejection có giới hạn: field
`semantic_rejection_recovery` nằm trực tiếp trong `visual_generation`, nhận
đúng hai giá trị:

- `"fail_closed"` (mặc định): giữ nguyên Phase 11, không sinh thêm ảnh.
- `"regenerate_once"`: chỉ khi Judge trả response hợp lệ nhưng toàn bộ
  candidate bị hard-fail/dưới ngưỡng, sinh đúng một round candidate mới với
  cùng `VisualRequest` và seed deterministic khác, rồi Judge lại whole-set
  round 0 + round 1. Lần từ chối thứ hai là `exhausted` và fail closed.

Policy này chỉ có hiệu lực với multi-candidate `vlm_ranked`. Lỗi hạ tầng
Judge, lỗi generation/technical validation, `first_valid`, `profile_local`,
parent reuse và prepared render không kích hoạt recovery. Không dùng reasons/
scores để sửa prompt và không gọi lại Director. Với `candidate_count <= 4`,
tối đa có 8 concrete candidate slots cho mỗi Shot (2 round × 4); generation
vẫn tuần tự và slot lỗi hạ tầng được resume theo checkpoint hiện hữu.

## Quy ước version snapshot

Mỗi lần bump `version` trong `profile.json`, copy nguyên trạng thái cũ (kể cả
prompt/bible file liên quan) vào `profiles/<profile_id>/versions/<semver-cũ>/`
trước khi sửa bản active — xem `docs/constitution/03-ARCHITECTURE.md` mục
"Profile version snapshots".

## Sau khi tạo profile

1. Chạy `load_content_profile("<profile_id>")` (hoặc test tương đương) để
   xác nhận parse sạch, không lỗi `ContentProfileError`.
2. Nếu profile mới cần MỘT luật content chưa có trong `qa_agent.py` hay
   `editorial_review`, đọc `docs/constitution/38-EDITORIAL_QUALITY_LAYERS.md`
   trước khi quyết định thêm ở đâu.
3. KHÔNG sửa code trong `src/ytb_pipeline/` để "cho profile này chạy được".
   Nếu bắt buộc phải sửa code — đó là dấu hiệu bộ khung profile còn thiếu
   một field/flag generic, không phải chỗ để hardcode riêng cho profile này.
