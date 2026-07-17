# Gate tuần 1 — 2026-07-16

## Kết quả

Batch `shorts_funnel_batch_2026-07-16` đã được tạo độc lập, không sửa
batch legacy `shorts_funnel_batch_2026-06-22`.

| Gate | Kết quả | Bằng chứng |
| --- | --- | --- |
| 2 long-form + 28 Shorts | PASS | Batch có 2 `long_videos` và 28 `short_videos`. |
| 30 script nạp được + compliance | PASS | `load_script()` + `QAAgent(strict)` đạt 30/30. |
| Liên kết Short → long | PASS | Funnel audit: 28/28 Shorts trỏ tới long hợp lệ, có playlist và CTA. |
| Lịch publish | PASS | 30/30 có `publish_at` RFC3339 `+07:00`; Shorts 26/07–01/08, 4 slot/ngày; long 28/07 và 31/07 lúc 20:30. |
| Production/upload | PASS | 30/30 project có node `publish` hoàn tất; URL đã lưu ở checkpoint và được đối chiếu qua YouTube API. Video giữ `privacy=private` cùng `publish_at` đã chốt. |
| `ytb batch doctor` | PASS | Queue, funnel, Telegram config, YouTube/Drive OAuth, process state, video verification và script pending đều xanh. |
| Test suite | PASS | `make test`: 456 passed. |

## Khắc phục state checkpoint

Đã phát hiện và sửa lỗi shared workflow: khi node `publish` đã `done`,
`project.status` vẫn là `draft`. Tái hiện bằng test RED, sau đó workflow ghi
atomically `published` khi mọi node hoàn tất; regression liên quan đạt 41 test.
66 checkpoint upload trước đó đã được đồng bộ chỉ theo bằng chứng
`publish.uploaded=true`, không đụng metadata, playlist, CTA hoặc lịch đã publish.

## Bước tiếp theo

Week 1 đã qua gate; có thể tạo batch week 2 độc lập theo lịch được giao.
