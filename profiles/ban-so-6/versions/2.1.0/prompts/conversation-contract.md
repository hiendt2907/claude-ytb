# Conversation Contract

Đây là bản chuẩn hoá **trước khi viết thoại**, không phải một mẫu câu để đọc
nguyên văn. Trước khi trả JSON, hãy lập thầm từng cảnh theo sáu điểm sau:

1. **Ở đâu, khi nào, vật gì đang ở trước mặt?** Cảnh phải có một chi tiết có
   thể nhìn thấy hoặc nghe thấy, không mở bằng kết luận tâm lý.
2. **Mỗi người biết gì và chưa biết gì?** Không để An biết hộ Minh, hoặc để
   Minh đáp lại một ý An chưa nói.
3. **Người đang nói muốn gì ở lượt này?** Mỗi lượt chỉ chọn một động từ:
   hỏi, né, kiểm tra, thừa nhận, đề nghị, phản bác, hoặc quyết định.
4. **Lời vừa nghe làm người kế tiếp đổi gì?** Lượt sau phải trả lời, làm khó,
   hoặc đẩy lựa chọn đi tiếp; không được đổi giọng để lặp một đoạn thuyết minh.
5. **Hành động nằm ở đâu?** Người kể hoặc `visual_intent` ghi hành động;
   Minh và An chỉ nói điều một người trong cảnh có lý do nói thành tiếng.
6. **Cảnh kết thúc bằng thay đổi nào?** Một thông tin mới, một lựa chọn, hoặc
   một hệ quả — điều đã thay đổi trong câu chuyện, thứ narrator chỉ được phản
   chiếu sau khi câu chuyện đã kiếm được nó.

## Quy ước cho Bàn số 6

- Minh nói ngắn, cụ thể, có xu hướng né vào việc sửa thêm, kiểm tra thêm hoặc
  tính cái giá trước mắt. Khi cậu tiến lên, đó là một lựa chọn có người/thực tế
  để phản hồi, không phải một câu tự khích lệ.
- An là chủ quán đã thấy Minh ngồi bàn số 6 đủ lâu để nhận ra điều khác thường.
  Cô không diễn vai chuyên gia và không nói thay người xem. An hỏi về vật,
  thời gian hoặc lựa chọn đang diễn ra; cô có đời sống riêng, có thể không đồng
  ý, và có thể chưa có đáp án ngay.
- Narrator là người dẫn chuyện bắt buộc, không phải một nhãn hành động câm.
  Người kể mở cảnh, giữ nhịp qua các thay đổi thời gian/không gian, cho thấy
  chi tiết mà nhân vật chưa nói ra, và dẫn dắt người xem đi hết câu chuyện.
  Giữa các lượt thoại, giọng kể có thể quan sát và gợi mở, nhưng không dịch
  lại nghĩa của câu thoại vừa nói, không đọc hộ lời trực tiếp của Minh/An, và
  không rút đạo lý thay khán giả trước khi hành động có hệ quả.
- Một đoạn hội thoại cần có tối thiểu hai lượt trực tiếp có quan hệ nhân quả
  khi có Minh hoặc An trong cảnh. Tách từng lượt thành section riêng với đúng
  `speaker_id`; không ghép cả hai người vào cùng một `voiceover`.
- Câu thoại phải có thể đọc thành tiếng một hơi, dùng đại từ và từ nối tự
  nhiên. Ưu tiên: “Vậy em thử gửi ba dòng này trước nhé. Nếu họ thấy chưa rõ,
  mình còn biết phải sửa ở đâu.” Tránh: “Gửi thứ nhỏ nhất để người khác chỉ ra
  chỗ sai.”

Sau khi viết xong, tự đọc liên tiếp tất cả section có Minh/An: nếu đổi tên hai
nhân vật mà nghĩa không đổi, hoặc bỏ một lượt mà đoạn vẫn y nguyên, hội thoại
chưa có quan hệ người-với-người và phải viết lại.

## Phản chiếu cuối tập — bắt buộc ở section cuối cùng

Section cuối cùng phải có `speaker_id` là narrator (`"narrator"`). Sau khi câu
chuyện đã đi tới lựa chọn và hệ quả, narrator nói trực tiếp với người xem trong
2–3 câu để phản chiếu điều vừa xảy ra. Đây là phản chiếu khiêm tốn, không phải
một quy luật cho mọi người, chẩn đoán hay lời khuyên tuyệt đối.

- Có thể dùng "bạn", "có lẽ", "trong những lúc như vậy" hoặc "lần tới" để
  mở khoảng cho góc nhìn của người xem. Không biến đoạn chốt thành "cách duy
  nhất", "ai cũng", hay mệnh lệnh hành động tức thời.
- Phản chiếu phải bắt nguồn từ chính lựa chọn/hệ quả của tập; không lặp slogan
  tách khỏi cảnh vừa xem và không gọi tên Minh/An trong phần phản chiếu.
- Cầu nối tập sau chỉ được nhắc sau phản chiếu, từ một vật, câu hỏi hoặc lựa
  chọn đã xuất hiện trong tập. Phải có tinh thần hẹn gặp lại, không dán trailer
  rỗng lên một câu chuyện đã kết.

## Turn card bắt buộc trong JSON

Mỗi section phải có field `turn`. Với narrator, luôn ghi `"turn": null`.
Với Minh hoặc An, ghi object dạng `{"scene": "một_mốc_cảnh_ngắn",
"intent": "một_hành_động_hội_thoại", "responds_to": <số section trước đó hoặc
null>}`. `intent` mô tả đúng việc câu nói đang làm — ví dụ `ask_for_context`,
`admit_fear`, `make_small_offer`, `push_back`, `decide_next_step` — không phải
tên cảm xúc chung chung. `responds_to` trỏ đến section có lời/cảnh mà lượt này
đang phản ứng; lượt mở một cuộc hội thoại mới dùng null. Turn card là kế hoạch
ngữ cảnh cho lời thoại, không được đọc bởi TTS.

## Voiceover ownership — bắt buộc trước khi xuất JSON

`voiceover` đi thẳng vào TTS. Section của Minh/An chỉ chứa đúng câu họ nói.
Hành động, nét mặt, giọng nói, vật dụng, hoặc người nghe nằm trong
`visual_intent` hay narrator section.

Section narrator vẫn có `voiceover` là lời dẫn truyện tự nhiên — ví dụ:
“Sáu giờ mười lăm. Con trỏ vẫn chớp ở cuối dòng tiêu đề, còn Minh đã mở hộp
thư lần thứ tư.” Đó là lời quan sát của người kể, không phải câu thoại được
đeo vào giọng narrator.

**Đúng**

```json
{"speaker_id":"an","voiceover":"Cậu mở hộp thư lần thứ mấy rồi?","visual_intent":"An đặt tách cà phê xuống trước mặt Minh.","turn":{"scene":"ban_06_0615","intent":"ask_about_behavior","responds_to":null}}
```

**FORBIDDEN IN CHARACTER VOICEOVER**

```text
An đặt tách cà phê xuống: "Cậu mở hộp thư lần thứ mấy rồi?"
Minh ngước lên, cười gượng: "Em chưa gửi."
```

Không dùng dấu `:` để dẫn câu thoại trong `voiceover` nhân vật; không bọc câu
thoại bằng dấu nháy. Nếu cần động tác giữa hai câu, tách narrator section rồi
mới đến lượt nhân vật tiếp theo.
