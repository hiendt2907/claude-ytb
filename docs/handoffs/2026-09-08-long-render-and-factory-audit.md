# Handoff cho Claude audit — Long render và hướng factory

**Branch:** `codex/production-readiness-e2e-gate1`  
**Phạm vi audit:** các commit từ `0977602` đến `3a0aa82`, cùng run thật
`cuoc-goi-ban-luc-bay-gio-muoi`. Không có upload YouTube mới trong run này.

## Kết quả có bằng chứng

Video Long **"Cuộc Gọi Bận Lúc Bảy Giờ Mười"** đã đi qua providers thật đến
MP4:

| Hạng mục | Kết quả |
| --- | --- |
| Script/editorial | pass; overall 8/10, không blocking finding |
| Voiceover | 362.38 s; transcript similarity 0.9862; audio-quality pass |
| Scene plan | 16 cảnh |
| Visual assets | 16/16 asset được chọn |
| Render | h264 1920×1080 @30 fps + aac, 362.55 s, 31,596,394 B |
| Render quality | pass; 0 error, 0 warning |
| Publish | **chưa chạy**; mốc 20:00 ngày 07/09 đã qua trước khi MP4 sẵn sàng |

Artifacts để kiểm tra trực tiếp:

- `assets/output/cuoc-goi-ban-luc-bay-gio-muoi.mp4`
- `assets/output/cuoc-goi-ban-luc-bay-gio-muoi_thumb.jpg`
- `assets/quality_reports/cuoc-goi-ban-luc-bay-gio-muoi.quality.md`
- `assets/projects/cuoc-goi-ban-luc-bay-gio-muoi/project.json`
- `assets/projects/cuoc-goi-ban-luc-bay-gio-muoi/visual_review.json`

Lệnh tái xác minh media:

```bash
ffprobe -v error -show_entries \
  format=duration,size:stream=codec_name,codec_type,width,height,avg_frame_rate \
  -of json assets/output/cuoc-goi-ban-luc-bay-gio-muoi.mp4
```

## Những thay đổi nguồn cần audit

| Commit | Mục đích |
| --- | --- |
| `0977602` | Chỉ settle những visual review đủ điều kiện |
| `26b00d3` | Thêm identity reference sạch cho Minh |
| `c57d53b` | Invalidate visual candidate khi profile release thay đổi |
| `b159297` | Giới hạn kích cỡ transport image gửi Vision Judge, giữ nguyên asset gốc |
| `8a8712c` | Dùng một định nghĩa thống nhất về judge provider/evaluation |
| `fc3d20f` | Không quyết định số phận script từ một lần judge nhiễu |
| `3a0aa82` | Ép ràng buộc số nhân vật theo scene generation mode |

`make test` tại HEAD: **1.611 passed, 3 skipped, 1 deselected; coverage 83.81%**.

## Phát hiện quan trọng: MP4 hợp lệ không đồng nghĩa visual factory sẵn sàng

Đây là điểm Claude cần audit thẳng tay. Trong 16 shot của run này:

- 5 shot được chọn tự động (2 không cần recovery, 3 recovery thành công).
- **9 shot** phải dùng `operator_override` sau khi semantic recovery cạn.
- Các lỗi lặp lại: ComfyUI thêm laptop thay vì điện thoại, không tái tạo được
  hành động/đạo cụ nhỏ, hoặc bố cục hai nhân vật không đúng yêu cầu.

Những override đã giúp hoàn tất MP4 nhưng không chứng minh được khả năng sản
xuất Long không người canh. Hãy audit đặc biệt các quyết định trong
`visual_review.json`: có shot nào thay đổi ý nghĩa kể chuyện đến mức phải
render lại thay vì được chấp nhận không?

## Ranh giới commit

Đã **không** đưa vào commit:

- toàn bộ test WIP hiện có trong working tree — theo yêu cầu trước đó của user;
- `assets/quarantine/corrupt_scripts_20260907/` — archive dữ liệu nguồn, không
  phải source code hay output của run này;
- media, cache, secrets và state runtime.

Điều này giữ commit audit chỉ chứa tài liệu handoff; không đánh cắp hoặc đóng
gói thay đổi WIP của phiên Claude trước.

## Phương án factory đề xuất

### 1. Tách hai dây chuyền thay vì scale ngay Long AI-image

**Dây chuyền A — nội dung/hàng đợi (có thể batch):** mỗi tuần research + dedup
10 chủ đề; sinh và editorial-review 5 Long, chỉ đưa các script đã pass vào
queue. Từ mỗi Long đã khoá script, tạo 2–3 Short derivative cùng cơ chế. Đây
là phần có thể chạy song song và không đụng GPU.

**Dây chuyền B — visual/render (GPU tuần tự):** không sinh 16 prompt hành động
khác nhau cho mỗi Long. Xây trước một catalog 20–30 visual đã duyệt cho `Bàn
số 6`: Minh solo, Minh+An, quầy, cửa sổ, phone close-up, exterior, các góc máy
rộng/cận. Scene plan chỉ map tới asset catalog; chỉ scene có bối cảnh/nhân vật
mới mới được sinh AI và yêu cầu review.

Đạo cụ/chuyển động nhỏ như “tay rút khỏi điện thoại” phải được kể bằng audio,
caption và cắt cảnh — không đưa vào hard requirement của một still image.

### 2. Điều kiện trước khi bật sản xuất không người canh

Chạy canary 3 Long với catalog và đo các chỉ số sau:

| Gate | Ngưỡng để scale |
| --- | --- |
| Operator override visual | ≤1 shot/Long |
| Visual semantic hard-failure | không có lỗi nhân vật/bối cảnh |
| E2E render pass | ≥95% trong một lần chạy |
| Time-to-ready Long | ≤45 phút, không kể lịch publish |
| Editorial admission | ≥60% script được đưa vào queue pass ngay |

Nếu một gate trượt, dừng tăng volume và sửa grammar/catalog trước; không hạ
ngưỡng judge để chạy qua.

### 3. Nhịp scale thực tế

1. **Tuần canary:** 3 Long/tuần, tối đa 2 derivative Short/ngày; tất cả upload
   private + schedule sau khi review.
2. **Khi 3 canary đạt đủ gate:** 1 Long/ngày + 2 Short/ngày, buffer tối thiểu
   7 Long script đã duyệt và 3 MP4 đã render.
3. **Chỉ sau 14 ngày ổn định:** cân nhắc 2 Long/ngày. Mỗi upload phải có
   `private + publishAt` riêng; không để worker tự chuyển video public ngay.

## Quyết định cần từ user sau audit

1. Claude có chấp nhận 9 visual override của MP4 hiện tại không, hay shot nào
   phải render lại?
2. Chốt mốc `publishAt` mới cho video hiện tại (ngày + giờ VN). Khi có mốc,
   upload sẽ dùng `DRY_RUN=false`, `YOUTUBE_PRIVACY=private` và RFC3339 cụ thể.
3. Có duyệt triển khai catalog visual + canary 3 Long trước khi bật factory
   1 Long/ngày không?
