Kênh là "1 Cốc Café 6h", theo hướng phát triển bản thân thật, không self-help.
Mỗi video giải thích một cơ chế tâm lý, hành vi hoặc mental model bằng tình
huống đời thường cụ thể. Không dùng khẩu hiệu, mẹo chữa nhanh hoặc lời hứa
tuyệt đối.

Cấu trúc bắt buộc cho MỌI video (Long lẫn Short) gồm đúng 3 lớp nội dung —
nỗi đau, triệu chứng, cách xử lý — ánh xạ vào purpose có sẵn của profile như
sau:
- `situation` = NỖI ĐAU: tình huống hoặc cảm giác khó chịu cụ thể mà người
  xem đang thật sự gặp trong đời sống hằng ngày (không phải mô tả chung
  chung, không phải định nghĩa khái niệm).
- `evidence` = TRIỆU CHỨNG + CƠ CHẾ: biểu hiện cụ thể, dễ nhận ra của nỗi đau
  đó, và lý do/cơ chế tâm lý hoặc hành vi đứng sau nó (có nguồn/nghiên cứu
  hoặc quan sát kiểm chứng được khi Long yêu cầu evidence).
- `application` = CÁCH XỬ LÝ: một bước áp dụng cụ thể, ít rào cản, có lý do
  cơ chế đi kèm giải thích vì sao bước đó tác động đúng vào nguyên nhân vừa
  nêu — không phải khẩu hiệu, không phải mẹo hô hào kiểu "hãy tích cực lên",
  không phải lời hứa tuyệt đối.
- `core_answer`/`payoff` giữ nguyên vai trò hiện có của Strategy-v1 (đưa câu
  trả lời cốt lõi sớm cho Short, chốt lại giá trị cho Long).

## Video dài (Long)

Bắt buộc đi theo đúng thứ tự: NỖI ĐAU → TRIỆU CHỨNG (kèm cơ chế) → CÁCH XỬ
LÝ. Không được đảo thứ tự hay bỏ qua lớp nào:
1. Mở bằng nỗi đau — tình huống cụ thể người xem đang gặp, không mở bằng
   định nghĩa thuật ngữ.
2. Trình bày triệu chứng — liệt kê biểu hiện dễ nhận ra, sau đó giải thích
   cơ chế đứng sau (vì sao lại vậy), có nguồn hoặc quan sát cụ thể khi
   purpose là evidence.
3. Đưa cách xử lý — bước áp dụng cụ thể, giải thích rõ lý do cơ chế vì sao
   bước này hiệu quả, không phải mẹo hô khẩu hiệu. Nêu rõ giới hạn của cơ
   chế (khi nào KHÔNG áp dụng được) nếu có.
Người xem phải hiểu vì sao hành vi xảy ra, giới hạn của cơ chế, và một bước
áp dụng ít rào cản.

## Video ngắn (Short)

Bắt buộc theo đúng thứ tự: NỖI ĐAU trước tiên → CÂU HỎI MỞ → DẪN VỀ LONG:
1. Câu mở đầu phải là nỗi đau cụ thể (1-2 câu), tuyệt đối không mở bằng lời
   chào hỏi hay định nghĩa khái niệm. Đây chính là `situation` trong strategy
   hook, phải xuất hiện ở segment đầu tiên.
2. Đặt một câu hỏi mở gợi tò mò (`open_loop`) ngay sau nỗi đau — câu hỏi này
   KHÔNG được trả lời trọn vẹn trong Short.
3. `core_answer` chỉ hé lộ MỘT PHẦN cơ chế — đủ hấp dẫn để người xem tò mò,
   nhưng cố ý để lại phần triệu chứng chi tiết và cách xử lý đầy đủ chưa
   được giải quyết.
4. Kết thúc bằng CTA dẫn rõ ràng, cụ thể về đúng video Long cùng chủ đề/cơ
   chế (dùng `long_form_slug`, `playlist`, `cta_target` trong strategy) —
   không phải CTA chung chung kiểu "theo dõi kênh để xem thêm", mà phải nêu
   rõ phần còn thiếu (triệu chứng đầy đủ hoặc cách xử lý) đang chờ trong
   video dài.
Short là phễu cho Long cùng cơ chế — không bao giờ tự đứng độc lập như một
video hoàn chỉnh.
