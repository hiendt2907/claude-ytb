# Recovery contract — batch YouTube

Mục tiêu là tiếp tục được khi lỗi hạ tầng, nhưng không che lỗi chất lượng, không
gọi lại LLM vô hạn và không bao giờ upload/sửa lịch hai lần một cách mù quáng.
Mỗi quyết định được ghi mã lỗi vào `assets/batch_cli_warnings.log`; log của slug
và artefact bị từ chối được giữ lại để resume đúng chỗ.

| Khâu | Dấu hiệu đã gặp | Xử lý tự động an toàn | Giới hạn | Khi dừng, việc cần làm |
|---|---|---|---|---|
| Ideation | LLM trả JSON lỗi/cutoff | Lưu raw response + parse error; sinh lại một response hoàn chỉnh | 1 lần, không repair hội thoại | Dùng candidate đã lưu để chỉnh system prompt hoặc chủ đề rồi start lại |
| Ideation | Hook muộn, sai độ dài, thiếu metadata/source, trùng cơ chế | Ghi QA report, đánh `needs_review`, không đưa vào queue | 0 cloud retry | Sửa brief/prompt rồi sinh candidate mới; không tái dùng script lỗi |
| Voiceover | `NoAudioReceived`, timeout/mạng | Giữ cache segment đã tốt, resume và retry | tối đa 3 lần với backoff | Kiểm tra provider/mạng nếu hết retry |
| Voiceover QA | STT lệch script, lặp câu, silence/volume/duration sai | Giữ audio report + không render tiếp ở strict gate | 0 retry tự động | Chỉnh voice profile/pacing hoặc kịch bản; synth lại phần cần thiết |
| Voiceover QA | Local STT chưa có | Ghi warning, không gọi cloud STT, không làm hỏng batch | 0 | Cài model STT local khi cần đối chứng sâu hơn |
| Render | Pexels/HTTP 5xx/mạng/ffmpeg bị gián đoạn | Giữ checkpoint, asset tải qua `.part`, resume + retry | tối đa 3 lần | Xem log renderer; không lấy artefact nửa chừng làm output |
| Render QA | sai orientation, duration, thiếu thumbnail/video stream | Invalidate node stale và chặn publish | 0 retry tự động | Sửa contract/render input rồi run lại từ checkpoint |
| Publish | OAuth revoked/reauth cần thiết | Không retry, không upload lại | 0 | Chạy `ytb auth`, sau đó verify trước khi retry slug |
| Publish | upload xong nhưng API verify lỗi/ID không tồn tại | Ghi URL/ID/log, không đánh done | 0 | `ytb batch verify` trước khi retry, tránh duplicate upload |
| Publish | lịch thực tế lệch `publish_at` | Lưu metadata đã verify; không tự đổi lịch | 0 | Người vận hành xác nhận lịch rồi sửa bằng thao tác chủ đích |

## Quy tắc resume

1. Script hash hoặc `ruleset_id` đổi: toàn bộ node downstream bị vô hiệu hoá; audio/video cũ không thể được publish kèm script mới.
2. Node render/voiceover hoàn tất nhưng artefact không còn: checkpoint tự trả node về pending.
3. Chỉ một retry được phép cho lỗi có nhãn `retryable`; lỗi không xác định fail closed, giữ log và chuyển slug tiếp theo.
4. `quality_status=blocked/error` luôn chặn publish, kể cả chế độ báo cáo. Chế độ report chỉ giảm các phép đo bổ sung, không mở đường cho artefact bị chặn.
5. Cùng một Long và hai Shorts phải giữ trace nguồn; không schedule/upload nếu batch contract chưa đủ cặp.
