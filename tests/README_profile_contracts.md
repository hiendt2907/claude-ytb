# Bản đồ test theo content-profile contract

Mục đích: trả lời nhanh "loại contract nào đã có test, cho profile nào" mà
không phải đọc lại 71 commit lịch sử. Cập nhật file này khi thêm test mới
liên quan tới một trong hai profile thật (`one-cup-cafe-6h`, `ban-so-6`) hoặc
tới engine chung. Không phải danh sách đầy đủ mọi test trong repo — chỉ những
file test có liên quan trực tiếp tới content-profile contract.

Quy ước cột "Profile": **generic** = dùng fixture profile giả (không phải
`one-cup-cafe-6h`/`ban-so-6`), đúng tinh thần "engine học từ profile data,
không học từ tên series". **cả hai** = có assertion riêng cho từng profile
thật trong cùng file.

## Engine chung (loader, schema, format contract) — nên luôn dùng fixture generic

| File | Profile | Kiểm tra |
|---|---|---|
| `test_content_profiles.py` | generic + cả hai | Parse `profile.json`, validate field, lỗi khi thiếu/sai kiểu |
| `test_content_profile_template.py` | generic (`template-fixture`) | Guide tác giả profile không lạc hậu so với dataclass thật |
| `test_editorial_contract_profile.py` | generic | `purpose_policy`/`narration_speaker_id`/`short_expansion_purposes` |
| `test_transcript_format_contracts.py` | generic + ban-so-6 | `format_prompts`, `allow_short_generation`, `supports_generation()` |
| `test_visual_generation_profile.py` | cả hai | Schema `visual_generation`, gate chỉ hợp lệ với `character_story` |
| `test_narration_speaker_migration.py` | ban-so-6 | `narration_speaker_id` không hardcode literal `"narrator"` |

## Editorial / creative contract (nội dung prompt lắp ráp)

| File | Profile | Kiểm tra |
|---|---|---|
| `test_profile_creative_contracts.py` | cả hai (đa số assertion: one-cup-cafe-6h) | Prompt hệ thống lắp ráp chứa đúng persona/kỷ luật câu chữ đã duyệt |
| `test_one_cup_cafe_editorial_structure.py` | one-cup-cafe-6h | Nội dung `editorial.md`: nỗi đau/triệu chứng/cách xử lý |
| `test_story_hook_prompt_contract.py` | generic (office-thread-fixture) | `STORY_HOOK_CONTRACT` được đưa vào đúng prompt |
| `test_narrator_lesson_closing.py` | generic | `content_rules.narrator_lesson_closing` — prompt + QA |

**Chưa cân xứng đã biết:** `one-cup-cafe-6h` có 1 file riêng soi kỹ nội dung
`editorial.md` theo tên (`test_one_cup_cafe_editorial_structure.py`);
`ban-so-6` không có file tương đương cùng tên, nhưng có vùng phủ tương đương
về mặt *chức năng* qua các file hook/closing bên dưới. Đây không hẳn là lỗ
hổng — `character_story` có contract khác hình dạng (hook mở đầu, đóng bằng
bài học) chứ không phải thiếu test — nhưng nếu `ban-so-6` có thêm một quy tắc
editorial mới, ưu tiên viết test bằng fixture generic (`office-thread-fixture`
hoặc tương đương) như các file hook đã làm, thay vì test thẳng trên
`ban-so-6`.

## QA heuristic tất định (`qa_agent.py`, hook/closing) — nên dùng fixture generic

| File | Profile | Kiểm tra |
|---|---|---|
| `test_story_hook_rule.py` | cả hai | Neo + stake mở đầu, đóng bằng hành động bounded |
| `test_story_hook_stake_semantics.py` | generic | Lớp marker nghĩa vụ vs rủi ro/hệ quả |
| `test_hook_repair_recovery.py` | generic | `series_dedup` + `hook` cùng vi phạm, cả hai đều được vá trong 1 attempt |
| `test_long_extension_cap.py` | ban-so-6 | Vá thiếu thời lượng Long không vượt trần section |

## `editorial_review` (LLM rubric, opt-in) — xem `docs/constitution/38-EDITORIAL_QUALITY_LAYERS.md`

| File | Profile | Kiểm tra |
|---|---|---|
| `test_editorial_review_agent.py` | cả hai | Cache theo fingerprint, enforce `minimum_score`, 5 dimension bắt buộc |

## Pipeline / DAG / preflight

| File | Profile | Kiểm tra |
|---|---|---|
| `test_pipeline_dag_wiring.py` | ban-so-6 | DAG node cho `render=story` |
| `test_pipeline_quality_integration.py` | cả hai | Gate editorial_review trước render lúc resume |
| `test_preflight.py` | ban-so-6 | Cổng offline trước khi nhận vào queue |
| `test_replace_slug_dedup.py` | one-cup-cafe-6h | `--replace-slug` không tự chặn chống trùng |
| `test_series_continuity.py` | cả hai | Continuity ledger, tập kế tiếp |
| `test_batch_defaults.py` | generic | Mặc định CLI, không phụ thuộc profile cụ thể |

## Render riêng cho `render=story` (chỉ liên quan `character_story`)

| File | Profile | Kiểm tra |
|---|---|---|
| `test_story_captions.py` | ban-so-6 | Caption hiện lời đọc, không hiện mô tả hình |
| `test_profile_multivoice_render.py` | ban-so-6 | Nhiều giọng theo `voice_cast`/turn |
| `test_comfyui_story_provider.py` | ban-so-6 | Sinh ảnh cảnh qua ComfyUI, neo danh tính nhân vật |
| `test_story_auto_generate_cache.py` | ban-so-6 | Cache ảnh cảnh theo content-hash |
| `test_voice_quality.py` | ban-so-6 | `tts_pace_factor`, cửa sổ thời lượng theo `video_type` |

`one-cup-cafe-6h` dùng `render=ai` (chung với các profile mechanism_explainer
khác), nên không có test render riêng theo tên profile trong nhóm này —
renderer AI không đặc thù theo profile, đã có test ở nơi khác của repo ngoài
phạm vi bảng này.

## Khi thêm profile thứ 3

Trước khi viết bất kỳ test mới nào cho profile thật, hỏi: "cái này có phải
một contract engine chung (mọi profile cùng narrative_mode phải theo) hay là
nội dung editorial riêng của chính profile này?" Nếu là contract chung → viết
bằng fixture generic và thêm một dòng vào bảng "Engine chung"/"QA heuristic"
ở trên. Nếu là nội dung riêng (persona, hook, lời thoại cụ thể) → test thẳng
trên profile đó, thêm dòng vào bảng tương ứng, và cập nhật file này.
