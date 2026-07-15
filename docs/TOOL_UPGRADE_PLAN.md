# Kế hoạch nâng cấp tool YouTube

**Trạng thái:** Đã chốt, áp dụng sau khi batch hiện tại hoàn tất
**Chủ sở hữu quyết định:** User
**Đối tượng đọc:** Codex, Claude và agent thực hiện thay đổi trong repo

## 1. Mục tiêu

Tool phải giúp thực hiện `CHANNEL_GROWTH_PLAN.md` nhanh hơn nhưng không đánh đổi chất lượng, tính nguyên bản, khả năng resume hoặc an toàn publish.

Không sửa tool chỉ để tăng số lượng video. Mỗi thay đổi phải gắn với một mục tiêu kênh hoặc một lỗi vận hành đo được.

## 2. Nguyên tắc bất biến

- Đọc `data/ledger.md` và `assets/auto_state.json` trước khi tạo hoặc chạy video.
- Không sản xuất chủ đề trùng nghĩa với bất kỳ dòng ledger nào.
- Không gọi Ollama cho việc viết kịch bản.
- Claude hoặc Codex là provider hợp lệ cho ideation.
- QA phải chặn script không có ví dụ cụ thể, hành động áp dụng hoặc payoff.
- Không đưa người que hoặc legacy `image_motion` vào production.
- Publish phải tôn trọng `DRY_RUN`, privacy và publish schedule.
- Mọi trạng thái phải resume được sau lỗi hoặc dừng graceful.
- Domain dataclass bất biến; khi làm giàu model dùng `dataclasses.replace()`, không mutate input.

## 3. P0 — An toàn vận hành và concurrency

Mục tiêu: cho phép chạy song song có kiểm soát, bắt đầu với tối đa 2 worker.

Yêu cầu:

- Có giới hạn worker rõ ràng, không chạy nhiều terminal thủ công.
- Mỗi slug có log, audio, render và workspace riêng.
- Ghi `ledger.md` và `auto_state.json` qua cơ chế khóa/atomic write.
- Một video lỗi không làm dừng các worker khác.
- Dừng graceful phải dừng toàn bộ worker và process con.
- `ytb batch status` hiển thị worker, slug, stage, elapsed time và lỗi gần nhất.
- Không cho hai worker nhận cùng một slug.

Điều kiện nghiệm thu: chạy thử hai video độc lập, không ghi đè artifact, không mất ledger, không upload trùng và resume được sau khi dừng.

## 4. P0 — Quality gate cho ideation

QA phải trả lỗi có cấu trúc, chỉ rõ rule và section vi phạm.

Các gate bắt buộc:

- Hook cụ thể trong phần mở đầu.
- Một cơ chế trung tâm.
- Ví dụ có bối cảnh, hành động, hậu quả và cách áp dụng.
- Hành động áp dụng ngay.
- Payoff cuối video.
- Short đúng thời lượng; long đủ độ sâu.
- Nguồn hoặc cách diễn đạt an toàn với claim sức khỏe/tài chính.
- Không trùng nghĩa với ledger.
- Không template hóa nhiều video liên tiếp.

Khi fail, tool phải giữ script ở trạng thái cần sửa, không tự publish và không lặp vô hạn cùng một lỗi.

## 5. P0 — Asset catalog và reuse Pexels

Xây thư viện asset có metadata:

- Asset ID và đường dẫn local/Drive.
- Nguồn và license.
- Chủ đề/hành động/bối cảnh.
- Orientation và độ dài.
- Lịch sử video đã sử dụng.
- Số lần dùng gần đây.

Asset selector phải ưu tiên clip chưa dùng hoặc ít dùng, đồng thời tránh lặp cùng một chuỗi cảnh, hook và payoff.

Điều kiện nghiệm thu: tạo được hai video khác nhau dùng một phần asset chung nhưng viewer vẫn nhận thấy narration, nhịp dựng và mục đích minh họa khác nhau.

## 6. P1 — Series, queue và semantic dedup

Queue phải lưu thêm:

- Series.
- Content pillar.
- Core mechanism.
- Audience problem.
- Short/long relationship.
- Playlist.
- CTA target.

Ideation phải kiểm tra chéo ledger, queue hiện tại và các tập khác trong cùng series. Nếu không chứng minh được góc mới, loại chủ đề trước khi gọi LLM/render.

## 7. P1 — SEO và packaging

Metadata phải được sinh theo trụ cột và chủ đề thật:

- Title có lời hứa rõ.
- Description có ví dụ và CTA.
- Tags liên quan trực tiếp.
- Không thêm hashtag “giải trí”, “meme”, “hài hước” nếu nội dung không thuộc nhóm đó.
- Thumbnail/frame đầu thể hiện vấn đề cụ thể.
- Playlist và video liên quan được gán trước khi publish.

## 8. P1 — Analytics feedback loop

Sau 48–72 giờ, lưu analytics cho từng video:

- Views.
- 3-second retention.
- Viewed vs swiped away.
- Average percentage viewed.
- Subscribers gained.
- Comments.
- Chuyển đổi Short → long.

Analytics phải tạo ra nhãn: `scale`, `revise_hook`, `revise_value`, `drop_format` hoặc `needs_more_data`.

Ideation lượt sau đọc các nhãn này để sinh chủ đề và format mới. Không tự động nhân rộng chỉ vì views cao.

## 9. P1 — Lịch sản xuất

Tool phải hỗ trợ cấu hình theo chiến lược kênh:

- Giai đoạn thử nghiệm: 2 Shorts/ngày.
- 1 video dài/tuần.
- Cho phép tăng lên 3–4 Shorts/ngày sau review dữ liệu.
- Short và long có lịch riêng.
- Không ghi đè `publish_at` đã tồn tại.
- Không schedule video chưa qua QA hoặc chưa có asset hợp lệ.

## 10. P2 — Monetization safety

Trước publish, kiểm tra:

- Nội dung có commentary/education gốc.
- Không phải slideshow hoặc footage Pexels với narration sơ sài.
- Không có claim sức khỏe/tài chính tuyệt đối hoặc gây hiểu nhầm.
- Không có nhạc/asset không rõ quyền sử dụng.
- Metadata không spam hoặc lệch chủ đề.

Nếu fail, chuyển sang `needs_review`, không upload thật.

## 11. Thứ tự thực hiện

1. Concurrency và state locking.
2. Quality gate kịch bản.
3. Asset catalog Pexels.
4. Series và semantic dedup.
5. SEO/thumbnail/playlist packaging.
6. Analytics feedback.
7. Adaptive scheduling và monetization review.

Không bắt đầu P1/P2 nếu P0 chưa có test nghiệm thu.

## 12. Quy trình cho Codex và Claude

Trước mỗi task:

1. Đọc file này và `CHANNEL_GROWTH_PLAN.md`.
2. Đọc `AGENTS.md`, `CLAUDE.md`, `data/ledger.md` và `assets/auto_state.json`.
3. Xác định task thuộc P0, P1 hay P2.
4. Không code ngoài phạm vi acceptance criteria của phase.
5. Sau thay đổi, cập nhật test, ledger/memory liên quan và ghi rõ trạng thái nghiệm thu.

Nếu yêu cầu mới mâu thuẫn với kế hoạch này, dừng và báo phần mâu thuẫn trước khi thực hiện.
