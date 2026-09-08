# Handoff — Asset Registry Phase 3.2 (corrective: concrete asset matching semantics)

Ngày: 2026-08-27
Người viết: Claude
Trạng thái: implement + test xong. `make test`: 1103 passed, 3 skipped, 1
deselected, 0 failed (chạy lặp lại 2 lần liên tiếp để xác nhận hết
flaky). Nối tiếp: `docs/handoffs/2026-08-27-asset-registry-phase3.1-
handoff.md` (Phase 3.1, nay đã superseded) → chỉ thị "Corrective Directive
— Phase 3.2: Concrete Asset Matching Semantics" từ user.

## Defect của Phase 3.1 (đã sửa)

Phase 3.1 sửa đúng vấn đề `asset_id` derive từ `generation_key`, nhưng lại
dùng `content_sha256` MỘT MÌNH làm khoá `_upsert_by_content` toàn cục —
cùng lớp lỗi một tầng thấp hơn: "cùng bytes" bị coi là "cùng định danh
record". `content_sha256` chỉ chứng minh bytes bằng nhau — KHÔNG chứng
minh cùng provenance, cùng generation event, cùng asset class, cùng seed,
cùng generation request, hay cùng physical/cache entry. Hệ quả: một
`profile_local` asset và một `generated` asset trùng bytes ngẫu nhiên sẽ
BỊ GỘP thành 1 record — sai hoàn toàn về mặt lịch sử sản xuất.

## Mô hình matching ĐÃ SỬA: "exact observation"

Thay vì match theo `content_sha256` một mình, giờ match theo tổ hợp bằng
chứng: `local_path` + `content_sha256` + `asset_class` tương thích + (khi
áp dụng) `generation_key`/`seed`:

- **Cache hit** (`is_fresh_generation=False`): tìm trong CẢ HAI class
  `generated` VÀ `legacy_generated` với `local_path`+`content_sha256`+
  `generation_key` khớp — đây là đường "cùng file cache được nhiều
  project tái dùng", giữ đúng 1 record dù record đó ban đầu được tạo bởi
  class nào.
- **Fresh generation** (`is_fresh_generation=True`): CHỈ match trong class
  `generated` (không bao giờ âm thầm "nâng cấp" một record `legacy_
  generated` — `asset_class` bất biến sau khi tạo), và YÊU CẦU THÊM
  `seed` của record cũ phải khớp. Bằng chứng locator/hash/generation_key
  giống hệt nhưng `seed` xung đột = một sự kiện sinh ảnh khác trong lịch
  sử, không phải quan sát lặp lại — tạo record MỚI, record cũ giữ nguyên.
- **Profile-local**: chỉ match trong class `profile_local` — một record
  `generated`/`legacy_generated` trùng bytes KHÔNG BAO GIỜ thoả điều kiện
  này, và ngược lại.
- **Path khác nhau + bytes giống nhau**: KHÔNG tự động gộp (thiếu bằng
  chứng path khớp).
- **Đổi bytes tại cùng path**: KHÔNG ghi đè record cũ — miss về
  `content_sha256` tại lookup luôn tạo record mới, giữ nguyên lịch sử.

Toàn bộ quyết định "match rồi insert-hoặc-reuse" nằm TRONG một khối
`locked_json_update` duy nhất (không "đọc → mở khoá → quyết định → khoá
lại → insert") — tránh race giữa 2 worker cùng quan sát 1 cache hit.

## Việc đã làm

1. **Viết lại `src/ytb_pipeline/render/asset_registry.py`** — bỏ `_upsert_
   by_content` (match theo content_sha256 đơn thuần); thêm `_match_
   generation_observation()` và `_match_profile_local_observation()` (hàm
   module-level thuần, dùng chung bởi cả `record_generated`/`record_local_
   asset` VÀ API tra cứu bên ngoài `find_exact_observation()`); thêm
   `find_by_asset_id()`; `find_by_content_sha256()` đổi trả về **list**
   (đã sai ở Phase 3.1 khi trả về 1 record đầu tiên tìm thấy — giờ đúng là
   index tìm kiếm, không phải khoá chính). `record_generated()`/`record_
   local_asset()` giờ tự thực hiện toàn bộ match+insert TRONG một
   `locked_json_update` block, không gọi lại `assets()` (vốn tự mở khoá
   riêng — sẽ phá vỡ tính atomic của quyết định).
2. **Không cần sửa `story.py`** — chữ ký public `record_generated()`/
   `record_local_asset()` không đổi, story.py vẫn gọi y hệt; chỉ logic
   match BÊN TRONG registry thay đổi.
3. **Sửa `tests/test_asset_registry.py`** — cập nhật docstring đầu file;
   thêm 5 test mới đúng các Example B/C/D + item 6/12 của Directive: xung
   đột seed trên bằng chứng khớp còn lại tạo record mới (không ghi đè);
   `generated` vs `profile_local` trùng bytes vẫn tách biệt; `legacy_
   generated` vs `generated` (fresh) trùng bytes vẫn tách biệt; 2 path
   khác nhau trùng bytes không tự gộp.
4. **Sự cố kỹ thuật phát hiện + fix trong phiên này**: lần đầu viết 2 test
   đa tiến trình dùng `multiprocessing.get_context("fork")` (đúng theo gợi
   ý "add one small multiprocessing/subprocess test") — `make test` toàn
   bộ suite bị FLAKY, fail `tests/test_batch_workers.py::test_parallel_
   process_next_claims_each_slug_once` (pass khi chạy riêng, fail khi chạy
   trong full suite). Xác nhận bằng `git stash` chạy lại baseline (không
   có thay đổi Phase 3.2) → suite sạch 1098/1098. Kết luận: fork một
   process pytest worker (vốn có thread/state sống, vd tracer của
   pytest-cov) là nguồn gốc bất ổn đã biết, không liên quan bản chất tới
   registry. **Quyết định**: bỏ `multiprocessing`/fork, thay bằng 2 test
   đa LUỒNG (thread) — về mặt kernel, `fcntl.flock` khoá theo OPEN FILE
   DESCRIPTION chứ không theo process, nên một race đa luồng (mỗi luồng tự
   `file_lock()` mở fd riêng) đã kiểm chứng ĐÚNG cơ chế serialize mà một
   process worker thứ hai sẽ gặp — không mất tính đại diện của test.
   Chạy lại `make test` 2 lần liên tiếp xác nhận hết flaky (1103/1103 cả
   2 lần).
5. **Tài liệu** — viết lại mục "Asset Registry" trong `03-ARCHITECTURE.md`
   phản ánh đúng mô hình "exact observation" + lý do bỏ multiprocessing
   test; đánh dấu handoff Phase 3.1 SUPERSEDED, trỏ sang file này.

## Bằng chứng zero-behavior-change

`tests/test_story_auto_generate_cache.py` (8 test) và cả 3 test tích hợp
ffmpeg thật của story renderer pass y nguyên, không sửa dòng nào (đã chạy
lại xác nhận riêng trong phiên này). `make test`: 1103 passed (tăng từ
1098 Phase 3.1 + 5 test mới), 0 failed, ổn định qua 2 lần chạy liên tiếp.

## Checklist "Definition of Done" đối chiếu

1. ✅ `content_sha256` không còn là khoá upsert toàn cục — thay bằng exact
   observation match.
2. ✅ Bytes giống nhau nhưng provenance khác nhau có thể cùng tồn tại như
   2 `AssetRecord` khác nhau (test seed-conflict, test Example B).
3. ✅ Đúng 1 concrete cached artifact vẫn chỉ 1 record + nhiều `uses`.
4. ✅ `profile_local`/`generated`/`legacy_generated` không bao giờ gộp chỉ
   vì trùng bytes (test Example C, D).
5. ✅ Đổi bytes tại 1 path không ghi đè record lịch sử (giữ nguyên hành vi
   đã đúng từ Phase 3.1, verify lại dưới matching mới).
6. ✅ Provenance bất biến — `asset_class` không bao giờ bị mutate sau khi
   tạo.
7. ✅ Match+insert vẫn process-safe — toàn bộ quyết định trong 1
   `locked_json_update`; 2 test race đa luồng (khác observation, cùng
   observation) đều pass.
8. ✅ Hành vi generation/cache/render hiện tại không đổi.
9. ✅ `make test`: 1103 passed, 0 failed, xác nhận ổn định qua 2 lần chạy.
10. ✅ Dừng lại sau Phase 3.2 — KHÔNG bắt đầu Phase 4.

## Việc CHƯA làm (đúng theo non-goals của Directive)

Không đụng: MediaBlob/blob store, storage-level content dedup,
VisualRequest, VisualProvider, generation DAG, candidate generation/
ranking, DirectorAgent, semantic QC, per-shot checkpoint, Short asset
reuse, migrate `AssetCatalog` (Pexels), ComfyUI redesign, đổi cache-key
formula, subtitle/music/SFX, `compose_ai.py` migration, provider mới, thay
đổi editorial.
