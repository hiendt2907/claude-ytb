> **SUPERSEDED 2026-08-27 bởi Phase 3.2** (`docs/handoffs/2026-08-27-asset-
> registry-phase3.2-handoff.md`). Phase 3.1 sửa đúng defect `asset_id`
> nhưng lại dùng `content_sha256` MỘT MÌNH làm khoá upsert toàn cục — cùng
> lớp lỗi một tầng thấp hơn ("cùng bytes" bị coi là "cùng định danh
> record"). Giữ file này nguyên vẹn làm lịch sử; đọc Phase 3.2 handoff để
> biết trạng thái ĐÚNG hiện tại (matching theo "exact observation":
> path + content_sha256 + asset_class tương thích + generation_key/seed).

# Handoff — Asset Registry Phase 3.1 (corrective: identity & provenance fix)

Ngày: 2026-08-27
Người viết: Claude
Trạng thái: implement + test xong. `make test`: 1098 passed, 3 skipped, 1
deselected, 0 failed. Nối tiếp: `docs/handoffs/2026-08-27-asset-registry-
phase3-handoff.md` (Phase 3, nay đã superseded) → chỉ thị "Corrective
Directive — Phase 3.1: Asset Identity & Provenance Fix" từ user, sau khi
review phát hiện defect kiến trúc trong Phase 3.

## Defect của Phase 3 (đã sửa)

Phase 3 dùng `asset_id_for_generation_key(generation_key)` — một hash
DETERMINISTIC của `generation_key`. Dù `asset_id != generation_key` xét về
chuỗi ký tự, hai giá trị này vẫn 1:1 về mặt ngữ nghĩa: cùng 1 `generation_
key` LUÔN cho ra đúng 1 `asset_id`, nên không thể biểu diễn tương lai
"cùng 1 generation request, seed khác nhau → nhiều AssetRecord khác nhau"
(Phase 4/DirectorAgent sẽ cần điều này). User yêu cầu sửa TRƯỚC KHI cho
phép tiếp tục sang Phase 4.

## Mô hình định danh ĐÃ SỬA

```
asset_id        định danh cơ hội (uuid4) của MỘT record cụ thể đã đăng ký
content_sha256  định danh của BYTES thật tại thời điểm đăng ký — khoá
                matching "đây có phải cùng 1 physical asset không"
generation_key  định danh của REQUEST sinh/tái dùng (công thức
                _generation_cache_key cũ, không đổi)
local_path      chỉ là LOCATOR, không phải định danh
```

Bốn khái niệm này ĐỘC LẬP hoàn toàn:
- `asset_id` không còn derive từ bất kỳ input nào — là `uuid4` thuần, gán 1
  lần rồi bất biến. Test `test_asset_id_is_not_a_deterministic_function_
  of_generation_key` chứng minh trực tiếp: cùng `generation_key`, bytes
  khác nhau → 2 `asset_id` khác nhau chắc chắn (không thể trùng do
  collision xác suất gần 0 của uuid4, và đằng nào implementation cũng
  không hề dùng generation_key để tính asset_id).
- Matching "đây là cùng 1 physical asset đã có record chưa" giờ dùng DUY
  NHẤT `content_sha256` (`AssetRegistry._upsert_by_content`), KHÔNG dùng
  `generation_key` hay `local_path`. Điều này trực tiếp sửa mục 13 của
  Directive: đổi bytes tại cùng 1 path (`test_replacing_bytes_at_the_same_
  path_creates_a_new_record_not_a_rewrite`) tạo record MỚI, record cũ giữ
  nguyên bất biến — không bị "path giống nhau" âm thầm ghi đè provenance
  lịch sử.
- `find_by_generation_key()` trả về LIST (0, 1, hoặc nhiều record) — không
  còn API nào giả định 1 generation_key → đúng 1 record.

## Ba asset_class rõ ràng (thay cho `source`/`provenance_complete` cũ)

```
generated         fresh ComfyUI result vừa sinh   -> provenance_status=complete
legacy_generated  cache hit, KHÔNG có record cũ    -> provenance_status=legacy_unknown
profile_local     asset cố định, chưa từng generate -> provenance_status=complete
```

Điểm mấu chốt sửa mục 5/6/9/10 của Directive: **cache hit + CÓ record cũ**
→ chỉ thêm `uses`, KHÔNG đụng field provenance nào (bất biến lịch sử).
**Cache hit + KHÔNG có record** → phân loại `legacy_generated`/`legacy_
unknown`, KHÔNG bịa seed/prompt/checkpoint dù công thức `generation_key`
hiện tại có thể tái tạo đúng các tham số ấy — vì file có thể được sinh
trước Phase 3, hoặc bởi checkpoint/code cũ khác, nên "tái tạo được tham số
request hiện tại" không đồng nghĩa "chắc chắn đó là tham số đã tạo ra file
này". Một record `legacy_generated` KHÔNG BAO GIỜ được nâng cấp lên
`complete` ở lần cache-hit sau, kể cả khi lần đó biết đầy đủ config hiện
tại (`test_legacy_generated_is_never_silently_upgraded_to_complete_on_a_
later_hit`).

`legacy_generated` và `profile_local` giờ tách bạch rõ (mục 6 Directive):
route khác hàm (`record_generated(is_fresh_generation=False)` vs `record_
local_asset()`), tên field không còn dùng chung `"profile local asset"`
cho cả hai.

## Provenance đầy đủ cho fresh generation (mục 7/8 Directive)

`record_generated(is_fresh_generation=True)` giờ ghi thêm so với Phase 3:
`generation_mode` (establishing/solo/duo, suy từ số nhân vật — mirror đúng
nhánh rẽ trong `ComfyUIStoryProvider.generate_scene`, KHÔNG đổi logic sinh
ảnh), `checkpoint`/`clip_vision_model`/`ipadapter_model` (đọc từ
`settings.comfyui_*`, tên model cấu hình — KHÔNG hash file model nhiều GB,
đúng mục 8: "model identity = configured name, exact weight hash
unknown"), `solo_weight`/`duo_weight`/`duo_denoise`, `sampler`/`scheduler`
(nâng `_SAMPLER`/`_SCHEDULER` trong `comfyui_story_provider.py` thành
`SAMPLER`/`SCHEDULER` public — ĐỔI TÊN, KHÔNG đổi giá trị, không đổi hành
vi sinh ảnh).

## Việc đã làm

1. **Viết lại `src/ytb_pipeline/render/asset_registry.py`** — bỏ hẳn
   `asset_id_for_generation_key()`/`asset_id_for_local_path()` (deterministic
   ID); thêm `_new_asset_id()` (`f"ast_{uuid.uuid4().hex}"`); thêm `find_by_
   content_sha256()`/`find_by_generation_key()` (list); `_upsert_by_content()`
   là lõi dùng chung cho cả `record_generated()`/`record_local_asset()` —
   match theo `content_sha256` TRƯỚC, chỉ tạo record mới khi miss, provenance
   record cũ không bao giờ bị `update()` lại. `record_generated()` nhận
   `is_fresh_generation: bool` bắt buộc, quyết định ghi đủ metadata
   (`generated`/`complete`) hay tối giản (`legacy_generated`/`legacy_
   unknown`).
2. **Sửa `src/ytb_pipeline/providers/image/comfyui_story_provider.py`** —
   đổi tên `_SAMPLER`→`SAMPLER`, `_SCHEDULER`→`SCHEDULER` (public, giá trị
   không đổi: `"dpmpp_2m"`/`"karras"`), để `story.py` import được cho mục
   đích ghi provenance mà không cần đoán lại literal.
3. **Sửa `src/ytb_pipeline/render/story.py`** — `resolve_scene_image()`'s
   `_record_generated()` giờ truyền `is_fresh_generation=False` ở nhánh
   cache-hit, `True` ở nhánh vừa gọi provider xong; luôn kèm đủ
   `generation_mode`/`checkpoint`/`clip_vision_model`/`ipadapter_model`/
   `solo_weight`/`duo_weight`/`duo_denoise`/`sampler`/`scheduler` — registry
   tự quyết định phần nào được PERSIST dựa trên `is_fresh_generation`, caller
   không cần tính 2 payload khác nhau. Thêm helper `_generation_mode()`.
4. **Viết lại hoàn toàn `tests/test_asset_registry.py`** — 14 test phủ đủ
   11 case A–K của Directive (2 record chung 1 generation_key với asset_id
   khác nhau; asset_id không phải hàm xác định của generation_key; cache
   hit có record cũ → tái dùng + không đổi provenance; cache hit không có
   record → legacy_generated không phải complete; legacy KHÔNG được nâng
   cấp; fresh generation giữ đủ metadata gồm checkpoint/clip_vision/
   ipadapter; legacy_generated ≠ profile_local; đổi bytes tại cùng path
   không ghi đè record cũ; 1 physical asset dùng ở 2 project → 1 record
   nhiều `uses`; lặp use giống hệt không nhân đôi; **1 test đa TIẾN TRÌNH
   THẬT** dùng `multiprocessing.get_context("fork")` — 4 process thật cùng
   ghi vào 1 file registry, xác nhận cả 4 sống sót, không chỉ đa luồng).
5. **Sửa `tests/test_profile_multivoice_render.py`** — assertion registry
   trong test tích hợp thật đổi từ field cũ (`source`/`generation_key`)
   sang field mới (`asset_class == "profile_local"`, `provenance_status ==
   "complete"`).
6. **Tài liệu** — viết lại mục "Asset Registry" trong `03-ARCHITECTURE.md`
   phản ánh đúng mô hình 4 khái niệm độc lập + 3 asset_class + tính bất
   biến provenance; thêm ghi chú "SUPERSEDED" đầu file handoff Phase 3 cũ,
   trỏ sang file này.

## Bằng chứng zero-behavior-change

`tests/test_story_auto_generate_cache.py` (8 test, không truyền `scene_id`)
pass y nguyên không sửa 1 dòng. Cả 3 test tích hợp ffmpeg thật của story
renderer pass, chỉ đổi tên field trong assertion registry (hành vi render/
cache/ComfyUI-call không đổi). `make test`: 1098 passed (tăng từ 1095
Phase 3 + 3 test net mới sau khi viết lại bộ test), 0 failed. Không rò rỉ
ra `assets/` thật (`git status --short assets/` sạch sau khi chạy full
suite).

## Checklist "Definition of Done" đối chiếu

1. ✅ `generation_key` map được tới nhiều `AssetRecord` — `find_by_
   generation_key()` trả list, test A/B/C xác nhận.
2. ✅ `asset_id` độc lập với `generation_key`/content hash/path — `uuid4`
   thuần, test xác nhận trực tiếp trên record thật.
3. ✅ Physical asset đã có không bị tạo record trùng — `_upsert_by_content`
   match theo `content_sha256` trước khi tạo mới.
4. ✅ Cache cũ không có registry record KHÔNG bị gắn nhãn "fully
   reproducible" — `legacy_generated`/`legacy_unknown`, không bịa field.
5. ✅ `profile_local` và `legacy_generated` là 2 class tách biệt.
6. ✅ Fresh generation giữ đủ metadata khả dụng (seed, prompt, style/
   negative prompt, steps, cfg, dims, characters, generation_mode,
   checkpoint, clip_vision, ipadapter, weights, sampler, scheduler) —
   KHÔNG đổi cache key/generation behaviour.
7. ✅ Provenance lịch sử bất biến — cache-hit vào record đã có chỉ thêm
   `uses`, không `update()` field provenance nào; test xác nhận cả 2
   hướng (legacy giữ legacy, generated giữ đúng seed cũ).
8. ✅ Registry vẫn process-safe — giữ nguyên `locked_json_update`, thêm
   test đa TIẾN TRÌNH thật (fork), không thay cơ chế khoá.
9. ✅ Hành vi render/cache/timing/editorial hiện tại không đổi.
10. ✅ `make test`: 1098 passed, 0 failed.
11. ✅ Dừng lại sau Phase 3.1 — KHÔNG bắt đầu Phase 4.

## Việc CHƯA làm (đúng theo non-goals của Directive)

Không đụng: VisualRequest, VisualProvider port chung, asset-generation DAG,
multi-candidate generation/ranking, DirectorAgent, per-shot checkpoint,
semantic visual QC, Short asset reuse, đổi cache-key formula, model-file
hashing service, migrate `AssetCatalog` (Pexels) sang registry mới,
subtitle/music/SFX, `compose_ai.py` migration, provider mới, thay đổi
editorial.
