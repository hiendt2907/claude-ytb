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
   một hệ quả — điều đã thay đổi trong câu chuyện, thứ narrator sẽ khái quát
   hoá thành bài học ở section cuối cùng (xem "Đúc kết bài học").

## Quy ước cho Bàn số 6

- Minh nói ngắn, cụ thể, có xu hướng trì hoãn bằng việc sửa thêm hoặc kiểm tra
  thêm. Khi cậu tiến lên, đó phải là một đề nghị nhỏ có đối tượng nhận thật,
  không phải một câu tự khích lệ.
- An không diễn vai chuyên gia. Cô hỏi về vật, thời gian, hoặc lựa chọn đang
  diễn ra; đôi khi cô nói về việc riêng của mình. Cô có thể không đồng ý hoặc
  chưa có đáp án ngay.
- Narrator là người dẫn chuyện bắt buộc, không phải một nhãn hành động câm.
  Người kể mở cảnh, giữ nhịp qua các thay đổi thời gian/không gian, cho thấy
  chi tiết mà nhân vật chưa nói ra, và dẫn dắt người xem đi hết câu chuyện.
  Giữa các lượt thoại, giọng kể có thể quan sát và gợi mở, nhưng không dịch
  lại nghĩa của câu thoại vừa nói, và không đọc hộ lời nói trực tiếp của Minh
  hoặc An — đó là hai việc khác nhau: một là tường thuật câu chuyện, một là
  nói hộ lời nhân vật; chỉ việc thứ hai bị cấm. Riêng section chốt (xem mục
  "Đúc kết bài học" bên dưới) là ngoại lệ có chủ đích: ở đó narrator ĐƯỢC YÊU
  CẦU khái quát hoá câu chuyện thành một bài học, nói thẳng với người xem.
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

## Đúc kết bài học — bắt buộc ở section cuối cùng

Từ bản duyệt gần nhất, cấu trúc tập đã đổi: 1 narrator dẫn dắt, 1 nhân vật
chính (Minh), 1 nhân vật phụ (An), một cuộc trò chuyện có chiều sâu, và
narrator dẫn người xem đi hết câu chuyện rồi đúc kết thành một bài học —
không còn kết bằng một hành động cụ thể do Minh hoặc An làm.

- Section cuối cùng của kịch bản phải có `speaker_id` là narrator
  (`"narrator"`).
- Nội dung là 2-3 câu, nói thẳng với người xem (xưng "bạn"/ngôi thứ hai),
  khái quát hoá điều vừa xảy ra trong cảnh thành một nguyên tắc hoặc lời
  khuyên áp dụng được — ví dụ dạng "Lần tới khi [tình huống tương tự], hãy
  [nguyên tắc]" — không phải một mệnh lệnh hành động tức thời kiểu "hãy làm
  X trong 10 phút tới", và không phải lời của Minh hay An.
- Bài học phải bắt nguồn trực tiếp từ đúng chọn lựa/hệ quả vừa diễn ra trong
  cảnh (mục 6 ở trên); không lặp lại một slogan chung chung tách rời khỏi
  câu chuyện vừa kể.

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
