# Kế hoạch phát triển kênh YouTube

**Trạng thái:** Đã chốt, cập nhật 2026-07-22
**Chủ sở hữu quyết định:** User
**Đối tượng đọc:** Codex, Claude và mọi agent vận hành kênh

## 1. Mục tiêu 30 ngày

- Tìm 2–3 format có khả năng kéo người xem quay lại.
- Xuất bản khoảng 40–50 Shorts chất lượng và 4 video dài.
- Xây phễu `Short → video dài → playlist → subscriber`.
- Tạo thư viện footage Pexels có thể tái sử dụng mà không làm video trở nên lặp lại.
- Không sản xuất nội dung hàng loạt thiếu giá trị, trùng chủ đề hoặc rủi ro monetization.

Batch đang chạy phải được để hoàn tất. Không thêm queue mới cho tới khi batch hiện tại được audit.

**Phạm vi áp dụng (thêm 2026-08-27):** mục tiêu và mô hình phễu Short→Long
trong tài liệu này áp dụng cho content profile giải thích cơ chế
(`one-cup-cafe-6h`). Series kể chuyện `ban-so-6` (content_rules
`allow_short_generation: false`) là **ngoại lệ vĩnh viễn, Long-only theo
quyết định chủ sở hữu** — không chạy phễu Short→Long, không cần
`--long-form-slug`/`--playlist`/`--cta-target` khi lên batch. Đừng áp mục
tiêu "40-50 Shorts + 4 Long" hay lịch "1 Long + 2 Short/ngày" ở mục 1 và 3
cho series này. Bối cảnh quyết định:
`docs/handoffs/2026-08-27-content-profile-engine-refactor-plan.md`.

## 2. Định vị kênh

Lời hứa của kênh:

> Giải thích cơ chế tâm lý, hành vi và thói quen đời thường bằng ví dụ dễ hiểu để người xem áp dụng ngay.

Bốn trụ cột nội dung:

1. Tâm lý và hành vi.
2. Tập trung, trì hoãn và năng suất.
3. Thói quen sức khỏe đơn giản, an toàn và không phóng đại.
4. Tiền bạc và quyết định đời thường.

Mỗi video chỉ có **một cơ chế hoặc một vấn đề trung tâm**.

## 3. Lịch xuất bản thử nghiệm

Mỗi ngày sản xuất một cụm nội dung hoàn chỉnh:

- 1 video dài, một cơ chế trung tâm, xuất bản lúc 20:30.
- 2 Shorts cùng cơ chế nhưng khác góc khai thác, xuất bản lúc 06:00 và 12:30; từng Short phải dẫn về đúng video dài của ngày đó.
- Mỗi Short phải bắt đầu từ đúng một phân đoạn đã truy được trong Long: phân đoạn đó vừa đem lại một insight cụ thể, vừa để lại một câu hỏi đáng xem tiếp. Short bổ sung hook, bối cảnh, bước quan sát an toàn và CTA; không tự thêm claim chưa có nguồn.
- Chỉ tăng số Short khi dữ liệu chứng minh chất lượng không giảm và chủ sở hữu quyết định.

Không thay đổi lịch của video đã upload hoặc đã schedule.
Chính sách này không tự gán `publish_at`: chỉ lên lịch sau khi cả Long, hai Short, nguồn và QA đều hợp lệ.

## 4. Tiêu chuẩn một Short

Mỗi Short phải có đủ:

1. Hook rõ trong 2 giây đầu.
2. Một tình huống đời thường cụ thể.
3. Một cơ chế giải thích ngắn gọn.
4. Ví dụ có bối cảnh, hành động và hậu quả.
5. Một hành động người xem áp dụng được trong ngày.
6. Câu chốt/payoff đáng nhớ.
7. CTA dẫn sang video liên quan hoặc video dài.
8. Dấu vết nguồn: slug Long, chỉ mục phân đoạn và trích đoạn nguồn phải có trong metadata để audit.

Không dùng lời mở đầu chung chung, danh sách mẹo không có cơ chế, hoặc kết thúc chỉ bằng “hãy like và subscribe”.

## 5. Tiêu chuẩn video dài

Video dài 12–15 phút, một cơ chế mỗi tập:

1. Hook nghịch lý.
2. Vấn đề người xem gặp.
3. Cơ chế đứng sau.
4. Hai hoặc ba ví dụ đời thường.
5. Framework áp dụng.
6. Sai lầm thường gặp.
7. Tóm tắt và cầu nối sang tập sau.

Short dùng một phân đoạn của Long làm hạt nhân, rồi viết lại cho nhịp dọc; không phải bản cắt máy móc hoặc bản tóm tắt cả Long.

## 6. Quy tắc chống trùng

Trước khi duyệt chủ đề mới, đọc toàn bộ `data/ledger.md` và đối chiếu cả video đã `done`, `error` và `cancelled`.

Không chấp nhận:

- Đổi tiêu đề nhưng giữ nguyên cơ chế.
- Đổi “3 mẹo” thành “5 mẹo” cho cùng vấn đề.
- Dùng lại cùng thông điệp chỉ với footage khác.

Nếu chủ đề gần với nội dung cũ, phải đổi sang cơ chế lõi hoặc góc nhìn khác đủ rõ.

## 7. Quy tắc dùng lại footage Pexels

Phân loại thư viện theo: điện thoại/laptop, làm việc, vận động, ăn uống, ngủ/thư giãn, thành phố/thiên nhiên/ánh sáng.

Một clip có thể dùng lại khi mỗi lần sử dụng thay đổi ít nhất ba yếu tố:

- Crop hoặc bố cục.
- Tốc độ và điểm cắt.
- Caption/annotation.
- Vai trò trong câu chuyện.
- Voiceover và thông điệp.

Không dùng lại cùng chuỗi cảnh cho cùng một hook hoặc payoff. Giá trị chính phải đến từ phân tích, narration và ví dụ gốc của kênh.

## 8. Đánh giá sau 48–72 giờ

Theo dõi cho từng video:

- Views.
- Retention ở 3 giây đầu.
- Viewed vs swiped away.
- Average percentage viewed.
- Subscriber gained.
- Bình luận có chất lượng.
- Lượt chuyển từ Short sang video dài.

Quyết định:

- View tốt và subscriber tốt: làm thêm 3 góc khác.
- View tốt nhưng subscriber thấp: sửa giá trị và CTA.
- Retention thấp: sửa hook hoặc cấu trúc.
- Chủ đề lặp: loại khỏi ideation.

Không quyết định chỉ dựa vào lượt xem 24 giờ đầu.

## 9. Lộ trình 4 tuần

### Tuần 1 — Kiểm kê và thử nghiệm

- Để batch hiện tại hoàn tất.
- Audit video đã upload và footage Pexels.
- Thử bốn trụ cột, mỗi trụ cột ít nhất hai Shorts.
- Viết video dài đầu tiên.

### Tuần 2 — Đo phản ứng

- Đăng 12 Shorts.
- So sánh hook, retention và subscriber.
- Chọn hai trụ cột có tín hiệu tốt nhất.

### Tuần 3 — Nhân rộng format thắng

- Mỗi trụ cột thắng tạo ba góc mới.
- Xuất bản video dài đầu tiên từ chủ đề thắng.
- Tạo playlist và CTA liên kết.

### Tuần 4 — Tối ưu sản lượng

- Loại format yếu.
- Giữ 2–3 format mạnh nhất.
- Quyết định có tăng sản lượng hay không dựa trên dữ liệu.
- Lập series 30 ngày tiếp theo.

## 10. Điều kiện monetization

Nội dung phải nguyên bản, có bình luận/phân tích đáng kể, không mass-produced và không dùng footage lại theo cách tối thiểu. Đây là điều kiện cấp kênh, không chỉ cấp từng video.

Shorts dùng để tiếp cận; video dài dùng để tạo watch time và niềm tin. Mọi quyết định nội dung phải ưu tiên giá trị thật trước sản lượng.
