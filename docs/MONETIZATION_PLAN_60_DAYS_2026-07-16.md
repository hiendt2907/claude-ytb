# Kế hoạch 60 ngày mở kiếm tiền — 2026-07-16 → 2026-09-13

## Mục tiêu thực tế

Mục tiêu chính là xây kênh đủ nguyên bản và đủ dữ liệu để tiến tới YPP, không
cam kết đạt ngưỡng chỉ bằng tăng số lượng.

YouTube hiện có hai mốc cần phân biệt:

- **Expanded YPP:** 500 subscribers + 3 video public trong 90 ngày + 3.000 giờ
  xem public long-form trong 12 tháng, hoặc 3 triệu lượt xem Shorts public hợp
  lệ trong 90 ngày. Mốc này mở một số tính năng fan funding/Shopping ở khu vực
  đủ điều kiện.
- **Chia sẻ doanh thu quảng cáo:** 1.000 subscribers + 4.000 giờ xem public
  long-form trong 12 tháng, hoặc 10 triệu lượt xem Shorts public hợp lệ trong
  90 ngày. Giờ xem từ Shorts Feed không tính vào 4.000 giờ.

Nguồn chính thức: [YPP overview & eligibility](https://support.google.com/youtube/answer/72851?hl=en)
và [expanded YPP](https://support.google.com/youtube/answer/13429240?hl=en).

Chiến lược ưu tiên đường long-form: 4.000 giờ tương đương khoảng 240.000 phút
xem hợp lệ. Với 16 video dài trong 60 ngày, nếu mỗi video đạt 5.000 lượt xem
và thời lượng xem trung bình 3 phút thì tạo khoảng 4.000 giờ. Đây là mô hình
tính mục tiêu, không phải dự báo; phải đo dữ liệu thật sau từng tuần.

## Nhịp sản xuất

- **2 video dài/tuần**, 8–12 phút, mỗi video đúng một cơ chế tâm lý/hành vi:
  khoảng 16 long-form trong 60 ngày.
- **4 Shorts/ngày**, khoảng 240 Shorts trong 60 ngày.
- Mỗi Short phải gắn với một trong hai long-form gần nhất qua
  `long_form_slug`, playlist và CTA. Trong 14 Shorts/long-form mỗi tuần, tối đa
  5 Short là biến thể trực tiếp; phần còn lại là ví dụ/góc khám phá mới cùng
  cơ chế, tránh cắt máy móc.
- 4 Shorts/ngày là trần vận hành, không phải lý do bỏ qua QA. Nếu hai ngày liên
  tiếp có retention/hook hoặc subscriber conversion giảm, hạ nhịp xuống 2/ngày.
- Lịch thử cho queue mới: Shorts 06:00, 11:30, 18:00, 22:00; long-form thứ
  Ba và thứ Sáu lúc 20:30. Không ghi đè `publish_at` của batch cũ.

## Mục tiêu sản lượng và quality gate

| Giai đoạn | Long | Shorts | Điều kiện tiếp tục |
|---|---:|---:|---|
| Ngày 1–7 | 2 | 28 | 2 long qua QA; 28 Shorts có đích; không lỗi phễu |
| Ngày 8–21 | 4 | 56 | retention long ổn định; không có format lặp hàng loạt |
| Ngày 22–42 | 6 | 84 | scale 2–3 format có sub conversion tốt |
| Ngày 43–60 | 4 | 72 | dọn catalog, chuẩn bị YPP, giữ chất lượng |

Tổng: **16 long-form + 240 Shorts**. Nếu không đủ người/giờ để viết và QA,
giảm số lượng nhưng giữ tỷ lệ 2 long/tuần và không publish nội dung sơ sài.

## Tuần 1 — Dọn phễu và chạy thử 2 long + 28 Shorts

- Hoàn tất audit batch hiện tại; không thêm vào queue legacy.
- Tạo một batch mới độc lập có 2 long-form và 28 Shorts; mọi Short phải trỏ về
  một trong hai long-form.
- Phân loại các video đã đăng theo: đúng ngách, lệch ngách, trùng, cần theo dõi.
- Xử lý lỗi custom thumbnail/verification.
- Tạo một playlist cho mỗi cụm cơ chế.
- Đặt baseline trong YouTube Studio: subscribers, public watch hours, Shorts
  views 90 ngày, views/video, subscribers/video, returning viewers.
- Chọn hai cơ chế không trùng: một long về attentional residue; một long về
  false consensus effect hoặc cơ chế tương đương sau khi đối chiếu ledger.

**Gate:** không chạy batch mới nếu doctor vẫn báo `no_long_form`, Short thiếu
`cta_target`, hoặc 2 long chưa có script đã QA.

## Tuần 2 — Giữ 2 long + 28 Shorts, đo format

- Viết và xuất bản 2 long-form theo cấu trúc hook nghịch lý → vấn đề → cơ chế →
  ví dụ → framework → cầu nối tập sau.
- Tạo 28 Shorts, chia đều cho hai long-form, nhưng chỉ tối đa 5 Short là cùng
  một luận điểm trực tiếp.
- So sánh 4 khung giờ Shorts; long-form giữ thứ Ba/thứ Sáu 20:30.

**KPI:** hook pass, average percentage viewed, subscribers gained/video,
Short→long clicks.

## Tuần 3–4 — Tìm format thắng với 4 long + 56 Shorts

- 4 long-form và 56 Shorts trong hai tuần.
- Thử ba format Shorts:
  1. nghịch lý đời thường;
  2. “não đang làm gì với bạn?”;
  3. một thử nghiệm hành vi trong 24 giờ.
- Mỗi format phải có ít nhất 4 mẫu trước khi kết luận.
- Sau 48–72 giờ, gắn nhãn `scale`, `revise_hook`, `revise_value` hoặc
  `drop_format`.

**Gate:** chỉ scale format có cả view và subscriber tốt; view cao nhưng sub thấp
thì sửa value/CTA.

## Tuần 5–6 — Nhân rộng có kiểm soát với 4 long + 56 Shorts

- 4 long-form và 56 Shorts từ hai hoặc ba format tốt nhất.
- Mỗi cơ chế mới phải đối chiếu ledger và queue trước khi viết.
- Tối ưu title/thumbnail theo vấn đề cụ thể, không nhồi hashtag.
- Bổ sung end screen, pinned comment và CTA nhất quán tới long-form kế tiếp.

**Mốc giữa kỳ:** nếu subscriber tăng nhưng watch hours thấp, ưu tiên nâng chất
lượng long-form; nếu views cao nhưng subscriber thấp, sửa lời hứa và cầu nối.

## Ngày 43–60 — Tối ưu theo dữ liệu và chuẩn bị nộp

- 4 long-form và 72 Shorts, chỉ giữ 2–3 format có tín hiệu.
- Dọn video lệch ngách, metadata spam hoặc asset/license không rõ; không xóa
  video chỉ vì view thấp nếu chưa có lý do chính sách/brand rõ ràng.
- Kiểm tra toàn bộ nội dung có commentary/phân tích gốc, không phải slideshow
  hoặc stock footage với narration sơ sài.
- Kiểm tra 2-Step Verification, advanced features, quốc gia đủ điều kiện và
  AdSense trong YouTube Studio.
- Nếu đạt mốc Expanded YPP: nộp mốc sớm. Nếu đạt 1.000 + 4.000 giờ hoặc
  1.000 + 10 triệu Shorts: nộp mốc chia sẻ quảng cáo.

## Bảng điều khiển hằng tuần

| Nhóm | Chỉ số | Quyết định |
|---|---|---|
| Reach | views, impressions, CTR | sửa title/thumbnail nếu reach có nhưng click thấp |
| Hook | retention 3 giây, viewed/swiped | viết lại 2 giây đầu |
| Value | average percentage viewed, retention curve | cắt đoạn giảng dài, tăng ví dụ |
| Loyalty | subscribers gained/video, returning viewers | giữ series và CTA cầu nối |
| Funnel | Short→long clicks, long watch hours | nối lại playlist/end screen/CTA |
| Safety | claim, license, AI disclosure, reused-content risk | chuyển `needs_review`, không publish |

## Nguyên tắc không phá monetization

- Không dùng 256 nội dung như mục tiêu bắt buộc nếu chất lượng giảm; con số kế
  hoạch là 16 long + 240 Shorts.
- Không mass-produce cùng template, cùng voiceover logic và chỉ đổi footage.
- Không dùng Shorts để “bù” 4.000 giờ vì Shorts Feed watch hours không được tính.
- Không coi đủ threshold là tự động được duyệt; YouTube vẫn review toàn kênh
  theo chính sách monetization.
