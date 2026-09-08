# Growth audit — 2026-07-16

## Kết luận

Batch hiện tại chưa tạo được phễu tăng subscriber. Batch mới nhất
`shorts_funnel_batch_2026-06-22` đang `active`, có 37 Shorts nhưng không có
video dài; 37 Shorts cũng không có `long_form_slug`, `playlist` hoặc
`cta_target`. Vì vậy không được thêm queue mới chỉ để tăng sản lượng.

Kết quả audit tự động:

```text
37 Shorts, 0 long, lỗi: no_long_form, shorts_without_target
```

## Hệ quả

- Shorts có thể tạo reach nhưng không có điểm đến để tạo watch time dài hoặc
  subscriber chất lượng.
- Chủ đề trong batch còn lệch sang nhóm buổi sáng/sức khỏe, trong khi định vị
  đã chốt là giải thích một cơ chế tâm lý/hành vi mỗi video.
- `assets/analytics.json` mới có một video và dữ liệu chưa đủ 48 giờ, nên chưa
  được dùng để nhân rộng format.
- Log publish cho thấy custom thumbnail nhiều lần bị YouTube trả 403; cần xử lý
  quyền/verification trước khi dùng CTR làm KPI cho video dài.

## Thay đổi tool đã thực hiện

- Thêm `ytb_pipeline.analytics.funnel.audit_batch()` — hàm thuần, bất biến,
  kiểm tra batch có long-form và quan hệ Short→long/playlist/CTA.
- `ytb doctor` thêm check `Short → long funnel`; batch lỗi sẽ bị báo đỏ nhưng
  không tự sửa state sản xuất.
- Thêm test cho batch hợp lệ, batch đứt phễu và batch hoàn tất.

## Điều kiện mở queue mới

Queue mới chỉ được duyệt khi:

1. Có ít nhất một long-form làm đích cho mỗi cụm Shorts.
2. Mỗi Short có `long_form_slug`, `playlist`, `cta_target` hợp lệ.
3. Chủ đề vượt qua kiểm tra chống trùng và đúng một cơ chế lõi.
4. Có kế hoạch đo sau 48–72 giờ: views, subscriber gained, retention,
   Short→long clicks và comments chất lượng.
