# Triển khai tuần 2 — trạng thái chờ dữ liệu publish

## Trạng thái

Batch tuần 1 đã được đồng bộ từ `data/ledger.md` vào `assets/auto_state.json`:

- 30/30 video ở trạng thái `publish` + `done` và giữ nguyên `publish_at`.
- Batch `shorts_funnel_batch_2026-07-16` chuyển sang `awaiting_publish`.
- Không tạo queue/video mới khi batch tuần 1 còn đang chờ publish.

Tuần 2 sẽ dùng cùng khung giờ vàng đã schedule cho tuần 1:

- Shorts: `06:00`, `11:30`, `18:00`, `22:00` (Asia/Ho_Chi_Minh), từ 02/08 đến 08/08.
- Long-form: `20:30`, ngày 04/08 và 07/08.
- Upload lên YouTube ở `private`, đặt `publishAt`; không chuyển public thủ công trước lịch.

## Việc tuần 2

Tuần 2 bắt đầu bằng chuẩn bị và schedule batch mới; analytics tuần 1 chỉ dùng sau khi
video chuyển public:

1. Hoàn thiện 2 long + 28 Shorts, QA và funnel trước khi upload.
2. Upload/schedule private theo các slot tuần 2; không sửa lịch batch tuần 1.
3. Chờ video tuần 1 chuyển public theo lịch đã khóa.
4. Thu analytics ở mốc 48 giờ và 72 giờ.
5. Gắn nhãn từng video: `scale`, `revise_hook`, `revise_value`, `drop_format`, hoặc `needs_more_data`.

## Cổng mở queue

Chỉ mở queue khi đã có dữ liệu tối thiểu cho các video đã public và có quyết định
format dựa trên retention, viewed-vs-swiped-away, subscriber gained và chuyển đổi
Short → long. `DRY_RUN` và Telegram approval vẫn giữ nguyên trong giai đoạn này.
