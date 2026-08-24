# Runbook E2E dry-run — 1 Long + 1 Short

**Last updated:** 2026-07-28  
**Scope:** chạy đầy đủ bốn khâu `input → voiceover → render → publish-prep` cho
một Long và một Short, nhưng tuyệt đối không upload/schedule/cập nhật queue sản
xuất.

Đây là runbook vận hành, không phải biên bản một lượt chạy đã pass. Chỉ gọi một
lượt là **PASS** khi toàn bộ evidence bên dưới tồn tại và các gate tương ứng
pass; không suy luận từ exit code hay stdout đơn lẻ.

## Ranh giới an toàn

- Dùng **direct CLI** `python -m ytb_pipeline`, không dùng `ytb batch run`.
  Batch runner là đường publish đã được ủy quyền và không thuộc bài E2E dry-run.
- Mỗi lệnh phải có `DRY_RUN=true` và `--through publish`. Stage publish vẫn chạy
  publish-prep, nhưng kết quả bắt buộc là `uploaded=False`; không được có URL hay
  YouTube ID.
- Không dùng `--schedule`, `--loop`, `ytb batch retry`, `ytb batch reset`, hay
  `ytb batch verify`. Chúng là workflow queue/publish, không phải E2E cô lập.
- Chạy Long và Short **tách lệnh**, với orientation đặt ngay trên lệnh. Không
  dùng queue làm cách nối hai video trong bài này.

`.venv` hiện không cài package theo cách direct CLI có thể import được; vì vậy
phải đặt `PYTHONPATH=src` (đúng với quy ước project trong `AGENTS.md`).

## Điều kiện trước khi chạy

1. Có hai script JSON đã qua review: một Long và một Short. Short vẫn phải có
   metadata/funnel/source trace hợp lệ theo [Content Contract](CONTENT_CONTRACT.md).
2. Xác nhận không có batch hoặc render sản xuất đang chạy (`ytb batch ps`).
3. Không đổi `.env` sang `DRY_RUN=false`; truyền `DRY_RUN=true` ngay tại từng
   lệnh để giới hạn phạm vi an toàn.
4. Kiểm tra thư mục runtime ghi được và `ffmpeg` có sẵn (`ytb doctor`). Không
   cần OAuth/YouTube token cho dry-run publish.

## Chạy 1 Long và 1 Short

Thay hai placeholder bằng file script của bài E2E. `RUN_ID` chỉ dùng để giữ log
terminal của lượt chạy, không làm thay đổi queue/ledger.

```bash
set -o pipefail
export PYTHONPATH=src
export DRY_RUN=true
RUN_ID="e2e-$(date +%Y%m%d-%H%M%S)"
mkdir -p "assets/e2e_logs/$RUN_ID"

ORIENTATION=landscape .venv/bin/python -m ytb_pipeline \
  --through publish scripts/<long-script>.json \
  |& tee "assets/e2e_logs/$RUN_ID/long.log"

ORIENTATION=portrait .venv/bin/python -m ytb_pipeline \
  --through publish scripts/<short-script>.json \
  |& tee "assets/e2e_logs/$RUN_ID/short.log"
```

`--through render` chỉ là smoke test renderer nhanh hơn; nó không kiểm chứng
publish-prep và không thay thế hai lệnh trên.

## Evidence và tiêu chí pass

Lặp các kiểm tra sau cho cả hai slug. `<slug>` là `project_id` trong checkpoint
(thường là stem của script), không tự đoán từ title.

| Evidence | Vị trí / dấu hiệu cần có | PASS khi |
| --- | --- | --- |
| Log E2E | `assets/e2e_logs/<RUN_ID>/{long,short}.log` | Có dòng `Xong stage=publish: uploaded=False url=None`; không có upload URL/ID. |
| Checkpoint | `assets/projects/<slug>/project.json` | Có node input, voiceover, audio-quality, render, render-quality và publish hoàn tất; output publish ghi `uploaded: false`. |
| Audio | đường dẫn `voiceover` trong checkpoint (dưới `assets/audio/`) | File tồn tại và audio-quality không bị blocked/error. |
| Render | đường dẫn `render` và `thumbnail_path` trong checkpoint (dưới `assets/output/`) | MP4, video/audio stream và thumbnail tồn tại; Long ngang, Short dọc. |
| Pre-publish QA | `assets/quality_reports/<slug>.quality.json`, `.quality.md`, `.quality.repair.md` | Report tồn tại và `status` là `pass`; `needs_review` hoặc `blocked` phải được xử lý trước khi ghi nhận PASS. |
| Publish-prep | stdout log và node publish checkpoint | `uploaded=False`, `url=None`, không gọi xác minh YouTube và không có thay đổi publish/schedule. |

Nếu muốn kiểm tra media độc lập, đọc đúng đường dẫn từ checkpoint rồi chạy:

```bash
ffprobe -v error -show_streams -show_format -of json <video-path>
```

Không chấp nhận artefact render còn dở, report thiếu, hoặc checkpoint stale làm
bằng chứng pass.

## Debug và retry

1. Giữ nguyên log E2E, checkpoint và artefact trước khi sửa. Đừng dùng `make
   clean` trong lúc điều tra vì nó xoá audio/output/cache.
2. Nếu Script QA hoặc audio-quality chặn: sửa đúng script/voice profile đã bị
   chỉ ra. Bất kỳ thay đổi byte của script hoặc ruleset đều làm downstream
   stale; chạy lại direct CLI với cùng orientation để tạo evidence mới.
3. Nếu render/QA fail: dùng `ffprobe`, `<slug>.quality.md` và
   `<slug>.quality.repair.md` để xác định media, orientation, duration hoặc
   thumbnail thiếu. Không chạy qua publish gate bằng cách tắt QA.
4. Nếu lỗi hạ tầng cần phân loại, giữ `assets/batch_cli_warnings.log` hoặc
   recovery report (nếu có), rồi áp dụng giới hạn trong
   [Recovery Contract](RECOVERY_CONTRACT.md). Không retry publish thật: ở
   dry-run, chạy lại chỉ sau khi đã xác định nguyên nhân và vẫn giữ
   `DRY_RUN=true`.
5. Nếu summary không đúng `uploaded=False url=None`, **dừng ngay**. Không chạy
   Short còn lại, không retry, và kiểm tra biến môi trường/lệnh đã dùng trước
   bất kỳ thao tác nào khác.

## Ghi nhận kết quả

Biên bản mỗi lượt cần ghi `RUN_ID`, hai script/slug, câu summary cho từng video,
đường dẫn checkpoint/report/media và mọi gate không chạy. Nếu chưa có artefact
hay gate chưa được xác minh trên máy thật, ghi **NOT RUN** — không ghi PASS dựa
trên cấu hình hoặc mã nguồn.

Xem thêm: [Content Contract](CONTENT_CONTRACT.md) cho release gates và
[Recovery Contract](RECOVERY_CONTRACT.md) cho retry/escalation theo từng khâu.
