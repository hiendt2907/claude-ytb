# Kế hoạch 60 ngày mở kiếm tiền — 2026-07-21 → 2026-09-18

## Mục tiêu thực tế

Mục tiêu trong 60 ngày là tìm được một phễu nội dung lặp lại được: **Short tạo
nhận diện → video dài tạo giờ xem và niềm tin → playlist tạo người xem quay
lại → subscriber**. Không cam kết đạt YPP trong 60 ngày chỉ bằng tăng số lượng.

Hai mốc YouTube cần phân biệt:

- **Expanded YPP:** 500 subscribers + 3 video public trong 90 ngày + 3.000 giờ
  xem public long-form trong 12 tháng, hoặc 3 triệu lượt xem Shorts public hợp
  lệ trong 90 ngày.
- **Chia sẻ doanh thu quảng cáo:** 1.000 subscribers + 4.000 giờ xem public
  long-form trong 12 tháng, hoặc 10 triệu lượt xem Shorts public hợp lệ trong
  90 ngày. Giờ xem từ Shorts Feed không tính vào 4.000 giờ.

Nguồn chính thức: [YPP overview & eligibility](https://support.google.com/youtube/answer/72851?hl=en)
và [expanded YPP](https://support.google.com/youtube/answer/13429240?hl=en).

Vì vậy, chỉ số đích của kế hoạch này là **public watch hours của long-form**,
không phải tổng Watch Time trong Analytics hay lượt xem Shorts.

## Trạng thái bắt đầu: Batch 3 là nhóm đối chứng

- **Batch đang chạy:** `shorts_funnel_batch_2026-07-20` (Batch 3).
- **Trạng thái:** `active`, gồm **28 Shorts + 2 video dài**.
- **Quyết định:** giữ nguyên script, queue và `publish_at` của Batch 3. Đây là
  nhóm đối chứng cho cấu trúc Short cũ; không trộn Short strategy-v1 vào đó.
- **Việc cần làm ngay:** sau khi mỗi Short đủ 48–72 giờ, lưu retained/viewed,
  AVD, subscriber và Short→long clicks. Batch 3 cho baseline thực tế để đánh
  giá cohort mới; chưa phải lý do tăng nhịp đăng.

## Chuẩn nội dung áp dụng từ batch mới

### Short: `core_answer_first_v1`

Mỗi Short mới phải khai báo một `strategy` có cơ chế, nỗi đau, angle, đích
long-form, playlist và CTA. Bố cục bắt buộc:

1. **0–2 giây:** tình huống nhìn thấy được.
2. **Không muộn hơn giây 5:** nói đáp án lõi; không hỏi chung chung hay dẫn
   nhập kiểu “Bạn đã bao giờ…”.
3. Phần còn lại: bằng chứng/cảm giác đời thường → một áp dụng nhỏ → cầu nối
   có lý do sang long-form.

Ví dụ: “Mở laptop rồi lại cầm điện thoại? Không phải bạn lười; não đang né
khoảnh khắc chưa biết bắt đầu từ đâu.”

### Video dài

Mỗi video chỉ giải thích một cơ chế: hook nghịch lý → vấn đề → cơ chế → 2–3 ví
dụ đời thường → khung áp dụng → cầu nối tập sau. Mục tiêu biên tập là 10–12
phút; engine kiểm tra thời lượng an toàn 12–15 phút theo audio F5 đã hiệu chuẩn.
Short cùng cơ chế phải mở một câu hỏi mà long-form trả lời sâu hơn, không phải
cắt lại nguyên xi.

## Nhịp xuất bản và tổng sản lượng

Nhịp chuẩn sau Batch 3 là **mỗi ngày 1 video dài + đúng 2 Shorts cùng Long**.
Short thứ ba trong ngày chỉ được phép khi cohort đã nhận nhãn `scale`; tool sẽ
chặn batch strategy-v1 vượt giới hạn này nếu chưa được ủy quyền.

| Phần kế hoạch | Video dài | Shorts | Mục đích |
|---|---:|---:|---|
| Batch 3 đang chạy | 2 | 28 | Nhóm đối chứng, không sửa queue |
| Ngày 1–3 | 0 | 0 | Audit và chốt baseline |
| Ngày 4–17 | 2 | 24 | Cohort `core_answer_first_v1` đầu tiên |
| Ngày 18–38 | 3 | 36 | Đo tối thiểu 4 mẫu/format rồi sửa có chủ đích |
| Ngày 39–60 | 3 | 36 | Nhân rộng có điều kiện format thắng |
| **Tổng trong cửa sổ 60 ngày** | **10** | **124** | 2 long + 28 Short đối chứng; 8 long + 96 Short strategy-v1 |

Không bù chỉ tiêu bằng video mỏng. Nếu quality gate, asset hay review chưa đạt,
giảm số lượng và giữ khoảng trống để sửa cohort.

## Step by step

### Ngày 1–3 — Audit Batch 3, chưa sản xuất batch mới

1. Trong YouTube Studio, chụp baseline: subscriber, Earn/public long watch
   hours, returning viewers, views/video dài, Shorts Viewed/Stayed to watch,
   AVD, retention mốc 3 giây và 10 giây.
2. Lưu baseline Shorts vào tool, ví dụ:

   ```bash
   ytb batch analytics baseline --stayed-to-watch 0.22
   ```

3. Khi từng video đủ 48–72 giờ, lưu snapshot. Đây là dữ liệu nhập tay vì
   YouTube Analytics API không trả đủ chỉ số swipe/Stayed to watch:

   ```bash
   ytb batch analytics snapshot --slug <slug> \
     --format-id legacy_batch_3 --age-hours 72 --stayed-to-watch 0.22 \
     --short-to-long-clicks 0 --subscribers-gained 0
   ```

4. Ghi riêng nội dung đã xảy ra trong giây 0–10 của mỗi Short có drop mạnh.
   Kết luận phải chỉ rõ: lời hứa sai, đáp án lõi đến muộn, hay hình ảnh đứng
   yên/nhịp dựng chậm. Không kết luận từ một video.

**Gate sang batch mới:** có baseline, Batch 3 vẫn nguyên vẹn, và biết rõ một
giả thuyết cần kiểm tra: “đáp án lõi trước 5 giây”.

### Ngày 4–17 — Chạy cohort strategy-v1 đầu tiên

1. Tạo **batch mới**, tách hoàn toàn Batch 3: 2 long + 24 Short.
2. Mỗi Long có đúng 2 Short cùng ngày, liên kết bằng `long_form_slug`, `playlist` và
   `cta_target`.
3. Giữ cùng `format_id=core_answer_first_v1`, nhưng mỗi cơ chế có nhiều angle
   khác nhau: trang trắng, hộp thư chưa trả lời, tab cũ, cuộc họp sắp bắt đầu.
4. Duyệt Telegram trước render: kiểm tra cơ chế, nỗi đau, câu trả lời lõi
   0–5 giây và long đích hiển thị ngay trong bản xem trước.
5. Render chỉ qua khi Short có cảnh `situation` và `core_answer` với mô tả
   hình/b-roll cụ thể; tránh khung text tĩnh ở điểm rơi 4–10 giây.

**Gate:** không có Short nào thiếu strategy hoặc đích long-form; không quá 2
Short/ngày; không scale trước tối thiểu 4 Short cùng format đủ 48 giờ.

### Ngày 18–38 — Ra quyết định theo cohort, không theo một video viral

1. Mỗi ngày xuất bản 1 Long + 2 Short phễu mới.
2. Sau 48–72 giờ, nhập snapshot cho từng Short và chạy:

   ```bash
   ytb batch analytics summary
   ```

3. Tool đánh giá theo **median của ít nhất 4 Short cùng format**:
   - `revise_hook`: Stayed to watch thấp hơn baseline.
   - `scale`: Stayed to watch cao hơn baseline ít nhất 20%, đồng thời có click
     sang long và subscriber.
   - `revise_value`: hook không tệ nhưng chưa tạo click long/subscriber.
   - `needs_more_data`: chưa đủ bốn mẫu hoặc chưa đủ 48 giờ.
4. Với `revise_hook`, đổi cảnh đầu và câu đáp án; không chỉ đổi caption. Với
   `revise_value`, giữ hook nhưng làm rõ ví dụ, payoff và lý do phải xem long.

**Gate:** chỉ format `scale` mới mở quyền Short thứ ba/ngày; nếu không có format
nào scale, tiếp tục 2/ngày và thay đổi một biến cho cohort sau.

### Ngày 39–60 — Củng cố series và giờ xem long-form

1. Giữ 1 long/tuần từ cơ chế/angle đã tạo returning viewers hoặc long watch
   hours tốt nhất; tiêu đề và thumbnail nói về vấn đề cụ thể, không nói chung
   chung về “tập trung hơn”.
2. Các Short thắng được nhân thành 3 angle mới, không nhân bản narration hoặc
   chuỗi cảnh.
3. Trước publish long: kiểm tra playlist, end screen, pinned comment và CTA từ
   Short cùng cơ chế.
4. Cuối ngày 60, audit toàn kênh: originality/commentary, nguồn và license,
   metadata, policy, 2-Step Verification, advanced features và trạng thái
   Earn. Chỉ nộp Expanded YPP/YPP khi tab Earn cho thấy đã đủ điều kiện.

## Dashboard và quy tắc quyết định hằng tuần

| Tín hiệu | Đo ở đâu | Hành động |
|---|---|---|
| Stayed to watch, retention 3s/10s | Shorts Studio | Sửa cảnh/câu trả lời đầu nếu dưới baseline |
| AVD, average percentage viewed | Analytics | Cắt phần giảng; tăng ví dụ cụ thể |
| Short→long clicks | Link/related video + Studio | Làm rõ khoảng trống và CTA nếu bằng 0 |
| Public watch hours long-form | Tab Earn | Ưu tiên long có retention/returning viewer tốt |
| Subscriber/video, returning viewers | Analytics | Giữ cơ chế/series mang người xem quay lại |
| CTR long-form | Reach | Chỉnh lời hứa title + thumbnail, không suy diễn từ mẫu impressions nhỏ |

## Tool đã được dùng để ép kế hoạch

- `ContentStrategy` + `HookPlan`: Short mới mang contract rõ về cơ chế, hook
  và đường sang long-form; dữ liệu bất biến đi xuyên pipeline.
- QA + voiceover gate: từ chối strategy Short thiếu `core_answer`, hoặc nói
  đáp án lõi sau hạn 5 giây.
- Render gate: từ chối Short strategy-v1 không có hình minh hoạ riêng cho
  tình huống và đáp án lõi.
- Queue/funnel audit: Batch 3 legacy được giữ nguyên; batch strategy-v1 phải
  có metadata đầy đủ và đúng 2 Short/ngày đi cùng một Long trước khi scale.
- Telegram preview: hiển thị format, cơ chế, hook 0–5 giây và long đích để
  duyệt bằng nội dung, không chỉ đọc cả kịch bản.
- `ytb batch analytics`: lưu baseline/snapshot nhập từ Studio và đưa nhãn
  cohort vào prompt ideation của batch kế tiếp.

## Nguyên tắc không phá monetization

- Shorts là reach và phễu; không dùng giờ xem Shorts Feed để dự báo 4.000 giờ.
- Không mass-produce một template rồi chỉ đổi footage hoặc tiêu đề.
- Không coi view cao là thắng nếu không có subscriber, click long hoặc returning
  viewer.
- Không sửa/xáo Batch 3 để “đẹp dữ liệu”; cohort cũ và cohort mới phải tách.
- Threshold không đồng nghĩa tự động được duyệt: YouTube review toàn kênh về
  tính nguyên bản, giá trị bình luận và chính sách.
