# Ảnh neo nhận dạng (IPAdapter identity reference)

Sinh bởi crop deterministic từ hai keyframe đã duyệt, KHÔNG phải ảnh mới:

- `minh.png` — crop 62% bên trái của `../opening.png` (`(0, 0, w*0.62, h)`).
  Minh là chủ thể chính vùng đó; opening.png nguyên bản có An ở góc phải nên
  không dùng được làm neo cho An (IPAdapter sẽ lây đặc điểm của Minh sang).
- `an.png` — crop 45% bên phải của `../recognition.png` (`(w*0.55, 0, w, h)`).
  Cùng lý do ngược lại: An là chủ thể chính vùng đó.

## Vì sao không dùng `character-sheet.png` làm ảnh neo

Đã thử — hỏng. `character-sheet.png` là một bảng nhiều pose/góc nhìn, nên
IPAdapter chép lại **bố cục bảng nhiều khung** thay vì dựng một cảnh liền
mạch. Ảnh neo phải là MỘT CẢNH THẬT, không phải reference sheet.

## Cảnh có cả hai nhân vật

KHÔNG sinh mới từ số 0 bằng cách chain hai IPAdapter — đã thử, hỏng theo hai
cách khác nhau (chain toàn cục lây nhận dạng; region-mask thì SDXL bỏ qua
ranh giới vùng, gộp thành một người lai). Cách đạt: dùng chính một keyframe
2-người đã duyệt (`opening.png` hoặc `recognition.png`) làm ẢNH NỀN cho
img2img denoise thấp (~0.5), IPAdapter cả hai nhân vật chỉ ở trọng số thấp
(~0.3) để giữ nhận dạng — không phải để dựng bố cục. Bố cục hai người đã có
sẵn trong ảnh nền; model chỉ vẽ lại hành động mới lên trên.

Xem `providers/image/comfyui_story_provider.py` cho chi tiết implement.
