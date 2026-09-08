# Triển khai tuần 1 — 2026-07-16 đến 2026-07-22

**Nhịp mới:** 2 long-form + 4 Shorts/ngày = 28 Shorts trong tuần.

## Trạng thái bắt đầu

- Batch ideation đã dừng; `ytb batch ps` không còn `run/retry`.
- Listener Telegram vẫn chạy như daemon riêng.
- Queue cũ vẫn có Shorts đã schedule, nhưng không có long-form target hợp lệ.
- Không thêm video vào queue cũ. Tạo batch tuần 1 độc lập sau khi có đủ 2
  long-form/28 Shorts/playlist/CTA.
- `.env` đang `DRY_RUN=true`, `TELEGRAM_APPROVAL=true`; render thử phải giữ nguyên.

## Hai cụm thử nghiệm tuần 1

**Cơ chế trung tâm:** attentional residue — dư âm chú ý khi chuyển việc.

Lý do chọn:

- Đúng ngách tâm lý/hành vi, không phải self-help hay mẹo buổi sáng.
- Đã có draft Short hợp lệ tại
  `scripts/du-am-chu-y-sau-khi-doi-viec.json`.
- Có nguồn truy được: Sophie Leroy, “Why Is It So Hard to Do My Work? The
  Challenge of Attention Residue When Switching Between Work Tasks”, 2009,
  DOI `10.1016/j.obhdp.2009.04.002`.
- Có thể giải thích bằng ví dụ công việc đời thường mà không cần claim sức khỏe,
  tài chính hoặc con số trang trí.

**Long-form trung tâm dự kiến:**

`Bạn Đã Đổi Việc, Nhưng Tâm Trí Vẫn Chưa Rời Đi`

**Long-form thứ hai:**

`Vì Sao Bạn Nghĩ Ai Cũng Đồng Ý Với Mình?`

Cơ chế dự kiến: false consensus effect — ảo giác đồng thuận. Trước khi viết,
đối chiếu ledger và nguồn; nếu trùng ngữ nghĩa thì thay bằng một cơ chế khác,
không dùng lại attentional residue.

**Hai mươi tám Shorts dẫn phễu:**

14 Shorts xoay quanh attentional residue: tin nhắn, tab mới, chuyển cuộc họp,
nghi thức đóng việc, đa nhiệm, thông báo, email, điện thoại, deadline, làm việc
sâu, nghỉ giữa task, câu hỏi cuối ngày, ví dụ học tập và ví dụ gia đình.

14 Shorts xoay quanh false consensus effect: nhóm chat, lựa chọn ăn trưa,
đánh giá đồng nghiệp, tranh luận online, họp nhóm, im lặng bị hiểu nhầm, vote,
quảng cáo, lựa chọn mua hàng, sở thích, phản hồi, ví dụ gia đình, ví dụ nơi làm
việc và cách kiểm tra giả định.

Mỗi Short là một ví dụ/hook khác nhau, trỏ về đúng một trong hai long-form;
không được biến thành 28 lời khuyên rời rạc hoặc cắt máy móc cùng một đoạn.

## Lịch thực thi

### 16/07 — Dọn và khóa phạm vi

- Giữ batch cũ ở trạng thái không nhận thêm.
- Ghi baseline YouTube Studio: subscribers, public watch hours, Shorts views
  90 ngày, returning viewers.
- Xác minh danh sách Shorts cũ đã schedule; đánh dấu video lệch ngách hoặc thiếu
  CTA để không dùng làm chuẩn so sánh.
- Không sửa `publish_at` đã tồn tại.

**Đạt khi:** không còn worker production; audit funnel báo đỏ cho batch cũ nhưng
được ghi nhận rõ là batch legacy.

### 17/07 — Viết hai long-form

- Viết hai script 10–12 phút, mỗi script tối thiểu 20 section.
- Cấu trúc: hook nghịch lý → vấn đề → cơ chế → 3 ví dụ → framework áp dụng →
  sai lầm → cầu nối tập sau → CTA câu hỏi.
- Ghi nguồn Sophie Leroy trong `compliance.notes`/`accuracy`.
- Chạy `load_script()` và QA; chưa render nếu fail.

### 18/07 — Viết 28 Shorts theo hai phễu

- Dùng draft `du-am-chu-y-sau-khi-doi-viec` làm baseline hook cho phễu A.
- Viết 14 Short cho phễu A và 14 Short cho phễu B, mỗi Short 0,8–1,2 phút,
  1.000–1.400 ký tự.
- Tất cả khai báo đúng `long_form_slug`, `playlist`, `cta_target`.
- Không thêm badge “Tập n”, không mở đầu bằng lời chào.

### 19/07 — QA và approval theo batch

- Kiểm 0c: cơ chế, nguồn, không khẩu hiệu, không claim tuyệt đối.
- Kiểm 0d: một cơ chế, cùng series, có cầu nối.
- Gửi theo hai đợt: 2 long + 7 Shorts/đợt; sửa bằng `replace()`/bản sao nếu có
  feedback, không mutate bản gốc.
- Chưa render khi chưa có `APPROVED`.

### 20/07 — Render thử hai long + hai Short mẫu

- Render local hai long + hai Short mẫu với `DRY_RUN=true`.
- Kiểm audio duration, orientation, subtitle, hook 5–8 giây đầu và thumbnail.
- Xử lý lỗi custom thumbnail/verification; không coi thumbnail đã thành công nếu
  API trả 403.
- Chỉ render 24 Shorts còn lại sau khi mẫu đạt gate.

### 21/07 — Đóng gói phễu

- Gán playlist và CTA target cho cả 6 video.
- Description 1–2 dòng đầu nêu đúng vấn đề; CTA trỏ tới long-form.
- Kiểm tra `ytb doctor`, đặc biệt `Short → long funnel`.
- Nếu vẫn lỗi, giữ ở `needs_review`, không đưa vào publish.

### 22/07 — Review dữ liệu và quyết định publish

- Nếu bản render đạt QA: duyệt lịch publish theo slot 06:00/20:30, không ghi đè
  lịch cũ.
- Nếu chưa đạt: giữ DRY_RUN, sửa hook/thumbnail/CTA.
- Tạo mốc analytics sau 48–72 giờ; không kết luận từ views 24 giờ đầu.

## Gate bắt buộc trước khi mở queue tuần 1

```text
2 long-form + 28 Shorts
28/28 Shorts có long_form_slug hợp lệ
28/28 Shorts có playlist + cta_target
30/30 script load được và compliance.passed = true
30/30 qua QA ngách/series
2 long + 2 short render local thành công
DRY_RUN/approval state được ghi rõ
```

Nếu bất kỳ gate nào fail, tuần 1 vẫn được xem là đạt mục tiêu học hỏi khi đã xác
định đúng lỗi; không tăng sản lượng để che lỗi phễu.
