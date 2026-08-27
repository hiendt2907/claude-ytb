> **SUPERSEDED 2026-08-27 bởi Phase 3.1** (`docs/handoffs/2026-08-27-asset-
> registry-phase3.1-handoff.md`). User phát hiện defect kiến trúc: `asset_id`
> ở phiên bản Phase 3 này derive DETERMINISTIC từ `generation_key`, khiến
> hai khái niệm 1:1 trong thực tế — vi phạm yêu cầu "một `generation_key`
> phải cho phép map tới nhiều `AssetRecord`". Giữ file này nguyên vẹn làm
> lịch sử; đọc Phase 3.1 handoff để biết trạng thái ĐÚNG hiện tại của
> `asset_registry.py` (asset_id giờ là uuid4 cơ hội, matching theo
> content_sha256, 3 asset_class rõ ràng, provenance immutable).

# Handoff — Asset Registry Phase 3 v1 (character_story generated visuals)

Ngày: 2026-08-27
Người viết: Claude
Trạng thái: implement + test xong. `make test`: 1095 passed, 3 skipped, 1
deselected, 0 failed. Nối tiếp: `docs/handoffs/2026-08-27-scene-plan-phase2-
handoff.md` (Phase 2 ScenePlan) → chỉ thị "Implementation Directive — Phase
3: Asset Registry v1" từ user.

## Audit trước khi implement (yêu cầu §0 của Directive)

1. **Asset sinh ở đâu**: `render/story.py::resolve_scene_image()`. Nhánh cố
   định (`segment.visual_asset` non-empty) trả `_asset_path(profile, ...)`
   thẳng, không generate. Nhánh generate gọi
   `providers/image/comfyui_story_provider.py::ComfyUIStoryProvider.
   generate_scene()`.
2. **Cache hit resolve ở đâu**: `resolve_scene_image()` tự check
   `cached.is_file()` trước khi gọi provider — `cache_dir` mặc định
   `settings.assets_dir / "generated_visuals" / profile.profile_id`.
3. **Tham số có sẵn trước khi gọi ComfyUI**: `profile_id`, `profile.version`,
   `dims` (render dims), `segment.scene_characters`, `segment.visual_intent`,
   `vg.style_prompt`/`negative_prompt`/`steps`/`cfg`/`solo_weight`/
   `duo_weight`/`duo_denoise`, và `gen_width`/`gen_height` (SDXL dims thật,
   khác `dims`) — đều có trong `_generation_cache_key()`/`resolve_scene_image
   ()` TRƯỚC lúc gọi provider.
4. **Tham số bị bỏ qua**: checkpoint/clip-vision/ipadapter model name
   (`settings.comfyui_*`, global không theo profile — đổi checkpoint KHÔNG
   invalidate cache hiện tại, ghi nhận là nợ kỹ thuật đã biết, KHÔNG sửa
   trong phase này vì Directive yêu cầu giữ nguyên hành vi cache); sampler/
   scheduler (`_SAMPLER`/`_SCHEDULER`, hằng số, không cấu hình được).
5. **Seed sinh ở đâu**: TẠI CALLER (`resolve_scene_image()`), derive từ
   `int(key[:16], 16) % (2**32)` — provider chỉ nhận seed đã tính sẵn, không
   tự sinh.
6. **Asset sinh ra có tái dùng được xuyên project không**: CÓ — `cache_dir`
   chỉ khoá theo `profile.profile_id`, KHÔNG theo slug/project; nội dung
   cache key chỉ phụ thuộc nhân vật + visual_intent + tham số style, nên 2
   project khác nhau dùng cùng segment nội dung sẽ trúng đúng 1 file — đây
   chính là case "reused asset" registry phải phản ánh đúng (1 record, nhiều
   `uses`), không phải mỗi project 1 record.
7. **`asset_catalog.json` khoá/ghi thế nào**: qua
   `orchestrator/state_io.py::locked_json_update` — `fcntl.flock` exclusive
   trên file `.lock` sidecar, ghi atomic (tmpfile + `os.replace`).
8. **2 batch worker chạm shared state đồng thời**: cùng cơ chế `locked_json_
   update` ở trên — đây là pattern đã có sẵn, tái dùng nguyên cho registry
   mới, không phát minh cơ chế khoá riêng.

Kết luận: không có correctness blocker → implement thẳng, không audit
thành refactor riêng.

## Việc đã làm

1. **File mới `src/ytb_pipeline/render/asset_registry.py`** —
   `AssetRegistry` (đọc/ghi qua `locked_json_update`, cùng cơ chế
   `asset_catalog.py`), `asset_id_for_generation_key()`, `asset_id_for_
   local_path()`, `content_sha256()`. Ba khái niệm `asset_id`/`content_
   sha256`/`generation_key` TÁCH BIỆT rõ: `asset_id` derive từ
   `generation_key` qua hash namespace riêng (`"asset-registry:v1:
   generation:" + generation_key`), KHÔNG BAO GIỜ bằng `generation_key`
   hay `content_sha256` (test xác nhận trực tiếp). `record_generated()`
   ghi đủ provenance thật (seed, prompt, style/negative prompt, steps, cfg,
   width/height, characters) — gọi CẢ khi fresh-generate lẫn cache-hit, vì
   cùng công thức `generation_key` tái tạo đúng y tham số request dù file
   đã có sẵn hay chưa. `record_local_asset()` cho asset cố định
   (`segment.visual_asset`) — `generation_key=None`, `provenance_complete=
   False`, KHÔNG bịa seed/prompt.
2. **Sửa `src/ytb_pipeline/config/settings.py`** — thêm `asset_registry_path
   : Path = Path("assets/asset_registry.json")`, sibling độc lập với
   `asset_catalog_path` (`asset_catalog.json` chỉ theo dõi tái dùng Pexels
   licensed, không liên quan).
3. **Sửa `src/ytb_pipeline/render/story.py`** — `resolve_scene_image()`
   thêm 4 keyword-only param MỚI, tất cả optional: `scene_id: str | None =
   None`, `shot_id`, `video_slug`, `registry`. Chỉ khi `scene_id is not
   None` mới ghi registry — MỌI caller cũ (kể cả toàn bộ test hiện có
   trong `tests/test_story_auto_generate_cache.py`) không truyền tham số
   này, nên hành vi + I/O giữ nguyên 100%. Call site DUY NHẤT truyền đủ 4
   tham số là vòng lặp chính trong `render_story_video()`, lấy `scene_id`/
   `shot_id` từ `scene_plan.scenes[index]` (Phase 2) và `video_slug=slug`.
4. **Test mới `tests/test_asset_registry.py`** — 11 test đơn vị thuần
   (không ComfyUI/ffmpeg/network), phủ: 3 định danh tách biệt thật sự (kể
   cả trên 1 record đã ghi thật, không chỉ ở tầng hàm), seed/tham số
   generation được giữ nguyên, asset cố định không bịa metadata, cùng 1
   physical asset dùng ở 2 project khác nhau → 1 record với 2 `uses`, gọi
   lặp cùng 1 use không nhân đôi, 8 "worker" (thread) ghi đồng thời vào
   cùng file không mất use nào (chứng minh compose đúng với
   `locked_json_update`), file chưa tồn tại đọc ra rỗng an toàn.
5. **Test sửa `tests/test_profile_multivoice_render.py`** — thêm
   `monkeypatch.setattr(settings, "asset_registry_path", tmp_path / ...)`
   vào cả 3 test tích hợp thật (cùng chỗ đã patch `projects_dir` ở Phase
   2 — xem mục sự cố dưới), thêm assertion registry ghi đúng 2 record
   `profile_local_asset` cho fixture 2-section dùng `visual_asset` cố
   định, mỗi record đúng 1 use khớp slug video, KHÔNG bị 4 caption card
   của narration dài làm phồng số record.
6. **Tài liệu** — thêm mục "Asset Registry — character_story visuals
   (Phase 3 v1)" vào `docs/constitution/03-ARCHITECTURE.md`.

## Sự cố phát hiện khi test thật (đã fix trong phiên này)

Lặp lại đúng lớp sự cố Phase 2: sau khi wire `resolve_scene_image()` vào
`story.py` nhưng TRƯỚC KHI thêm monkeypatch `asset_registry_path` vào 3
test tích hợp thật, một lần `make test` đã ghi thật
`assets/asset_registry.json` + `assets/.asset_registry.json.lock` vào
chính repo (path mặc định tương đối `assets/asset_registry.json`, không
trỏ `tmp_path`). Đã xoá cả 2 file rò rỉ ngay lập tức, thêm monkeypatch vào
đúng 3 vị trí, chạy lại `make test` + `git status --short assets/` xác
nhận sạch — không còn rò rỉ.

## Bằng chứng zero-behavior-change

Toàn bộ `tests/test_story_auto_generate_cache.py` (8 test gọi `resolve_
scene_image()` trực tiếp, không truyền `scene_id`) pass y nguyên không sửa
gì. Cả 3 test tích hợp ffmpeg thật của story renderer pass với assertion
cũ nguyên vẹn, chỉ thêm assertion mới. `make test`: 1095 passed (tăng từ
1084 baseline Phase 2 + 11 test registry mới), 0 failed.

## Checklist "Definition of Done" đối chiếu

1. ✅ `AssetRecord`/`AssetRegistry` contract bền, tồn tại (`asset_registry.py`).
2. ✅ Asset generate mới giữ provenance thật, gồm seed — `record_generated()`.
3. ✅ `asset_id`/`content_sha256`/`generation_key` là 3 khái niệm tách biệt —
   test khẳng định trực tiếp trên record thật, không chỉ ở tầng hàm hash.
4. ✅ Hành vi cache generate hiện tại KHÔNG đổi — `test_story_auto_generate_
   cache.py` pass nguyên, không sửa 1 dòng.
5. ✅ Asset cố định/local biểu diễn được KHÔNG bịa metadata generate —
   `record_local_asset()`, `generation_key=None`.
6. ✅ Liên kết Scene/Shot dùng ID xác định Phase 2 (`scene_plan.scenes[
   index].scene_id`/`.shots[0].shot_id`).
7. ✅ Ghi registry chia sẻ an toàn theo tiến trình — tái dùng `locked_json_
   update` (đã kiểm chứng qua `tests/test_state_io.py`) + test 8-thread
   riêng cho registry.
8. ✅ Asset cache cũ (đã tồn tại trước Phase 3) vẫn dùng được, biểu diễn
   được ở dạng provenance chưa đầy đủ khi cần (route qua `record_local_
   asset` cho case không rõ nguồn gốc generate).
9. ✅ Hành vi render/timing/editorial hiện tại không đổi — test tích hợp
   thật pass nguyên với assertion cũ.
10. ✅ Project cũ không có registry entry vẫn hoạt động — registry chỉ ghi
    thêm, không stage nào đọc lại nó để quyết định logic render.
11. ✅ `make test`: 1095 passed, 0 failed.
12. ✅ Tài liệu ghi đúng bất biến mới (`03-ARCHITECTURE.md`).
13. ✅ Dừng lại sau Phase 3 — không tự ý làm VisualRequest/asset-generation
    DAG.

## Việc CHƯA làm trong phase này (đúng theo non-goals của Directive)

Không đụng: `Shot -> VisualRequest -> VisualProvider -> AssetRecord`
boundary (Phase 4), provider redesign, đổi logic cache/generation hiện có,
đổi ComfyUI workflow, invalidate cache theo checkpoint model (nợ kỹ thuật
đã ghi nhận ở audit mục 4, không sửa trong phase này).
