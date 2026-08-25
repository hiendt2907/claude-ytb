# Brief ảnh — Tập 1 "Bảy lần mở laptop"

Sinh từ `visual_intent` của 13 section trong `scripts/bay-lan-mo-laptop.json`.
Sau khi có ảnh đã duyệt: đặt vào `profiles/ban-so-6/assets/`, khai đúng
filename vào `render.scene_assets` trong `profile.json`, tăng `version` lên
`1.1.0`, rồi sinh lại kịch bản (script cũ khai `1.0.0` sẽ fail-closed ở renderer).

## Quy tắc chung cho MỌI frame

Theo `prompts/visual-assets.md`:

- **Input 1 (identity anchor):** `assets/character-sheet.png` — giữ nguyên khuôn
  mặt, tuổi, tỉ lệ, tóc, trang phục, đạo cụ nhận diện.
- **Input 2 (style anchor):** `assets/opening.png` — giữ nguyên kiến trúc quán,
  bảng màu, logic ánh sáng, chất giấy (paper texture).
- **Ràng buộc:** đúng số nhân vật xuất hiện; không thiết kế lại nhân vật; không
  chữ đọc được trong hình; không logo/watermark; an toàn crop cả 16:9 lẫn 9:16.
- **Tránh:** trôi khuôn mặt, đổi trang phục, tư thế "người thầy", biểu cảm anime
  cường điệu, ảnh chụp thật, 3D bóng bẩy, người/đạo cụ không được yêu cầu.
- **Định danh cố định:** Minh — tóc đen hơi rối, kính chữ nhật mảnh, áo thun
  navy, sơ-mi be khoác ngoài, túi canvas cam đất, đồng hồ điện tử cũ. An — tóc
  bob ngang cằm, sơ-mi xanh xám, tạp dề nâu, bút chì cài túi áo. Bàn số 6 — gỗ
  sẫm cạnh cửa kính, vết xước dài ở góc phải.

## 13 frame

| # | Tên file đề xuất | Beat | Mô tả hành động (chỉ tả cái MỚI) |
|---|---|---|---|
| 0 | `ep01-01-arrival.png` | 6h07 | Minh đặt túi canvas xuống bàn số 6, chưa ngồi hẳn; hơi nước mờ trên cửa kính sau lưng; quán còn vắng. |
| 1 | `ep01-02-blank-file.png` | 6h11 | Cận màn hình laptop trắng tinh với con trỏ đơn độc; tay Minh đã đặt lên mép nắp máy chuẩn bị gập. |
| 2 | `ep01-03-first-outline.png` | 6h20 | Tờ giấy trắng mới lấy từ túi canvas, ba cột đầu mục viết bằng bút chì cũ; laptop đóng đẩy sang bên. |
| 3 | `ep01-04-colored-outline.png` | 6h33 | Tờ giấy đã kín chữ ba màu mực xanh–đen–đỏ; Minh nghiêng đầu tựa lên tay, hài lòng với tờ giấy. |
| 4 | `ep01-05-old-project.png` | 7h05 | Màn hình hiện cấu trúc một dự án cũ; Minh lướt nhanh, một tay đã chạm nắp máy. |
| 5 | `ep01-06-one-line-erased.png` | 7h18 | Màn hình gần như trắng, còn dấu vết một dòng vừa bị xoá; Minh ngồi im, hai tay rời bàn phím. |
| 6 | `ep01-07-coffee-arrives.png` | 7h30 | An đặt ly cà phê xuống bàn; trước mặt Minh là tờ giấy đầy chữ và laptop đã đóng. |
| 7 | `ep01-08-an-leak.png` | 7h35 | An đứng cạnh bàn, tay chạm bút chì trên tạp dề; qua khung cửa kho phía sau thấy một cái xô hứng nước. |
| 8 | `ep01-09-recognition.png` | 7h44 | Bố cục chia đôi: tờ giấy kín chữ bên trái, màn hình trắng bên phải; Minh nhìn cả hai cùng lúc. |
| 9 | `ep01-10-folding-paper.png` | 7h55 | Minh gập đôi tờ giấy, ánh mắt hướng ra ngoài cửa kính — đang nhớ lại chuyện cũ. |
| 10 | `ep01-11-three-lines-sent.png` | 8h12 | Cận màn hình: một thư ngắn ba dòng đã gửi; Minh ngồi thẳng lưng, tay rời chuột. |
| 11 | `ep01-12-standing-up.png` | 8h20 | Minh đứng dậy khỏi bàn số 6, túi canvas đã lên vai, tờ giấy gấp nhét trong túi. |
| 12 | `ep01-13-leaving.png` | kết | Minh bước ra khỏi cửa quán, ánh sáng buổi sáng phía sau lưng, dáng nhẹ hơn lúc vào. |

## Ghi chú bố cục

- Frame 1, 4, 5, 10 là cận màn hình → cần bố cục an toàn cho crop dọc; đừng đặt
  chi tiết quan trọng sát mép trái/phải.
- Frame 8 là beat quan trọng nhất của tập (nhận ra cơ chế) → nên là frame được
  duyệt kỹ nhất và có thể dùng lại làm thumbnail.
- Frame 0 và 12 tạo cặp mở–đóng: cùng góc máy, khác trạng thái nhân vật.
