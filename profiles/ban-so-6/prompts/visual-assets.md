# Asset generation notes

## Asset đã giữ lại

1. `assets/character-sheet-v1.png`
   - Hai identity Minh và An.
   - Pose, biểu cảm và trang phục dùng làm anchor cho các lần tạo tiếp theo.

2. `assets/keyframe-01-opening-v1.png`
   - Cảnh mở lúc 06:07.
   - Minh ở bàn số 6; An ở quầy; xe buýt và cửa kính làm lớp chiều sâu.

3. `assets/keyframe-02-recognition-v1.png`
   - Cảnh 07:18 khi An đứng cạnh bàn.
   - Hũ đường và xô hứng nước xuất hiện như continuity props.

## Kết quả consistency test

Lần sinh keyframe đầu tiên giữ Minh đúng nhưng biến An thành một người đàn ông có nhiều nét giống Minh. Khung đó bị loại.

Một lượt identity-preserving edit đã thay đúng riêng nhân vật phía quầy bằng An và giữ nguyên bố cục. Keyframe thứ hai, khi dùng cả character sheet và opening frame làm reference, giữ được:

- khuôn mặt và tóc của hai nhân vật;
- trang phục;
- túi canvas;
- bảng màu;
- kiến trúc quán;
- ánh sáng và paper texture.

Điều này cho thấy mô hình khả thi cho keyframe ít chuyển động, nhưng không nên sinh mỗi scene từ text thuần. Mỗi lần tạo scene phải dùng:

1. character sheet làm identity anchor;
2. một keyframe đã duyệt làm environment/style anchor;
3. continuity ledger cho props và trạng thái câu chuyện;
4. visual QA trước khi asset được đưa vào render.

## Prompt pattern — scene mới

```text
Use case: illustration-story
Asset type: new key story frame for the same episode
Input images:
- Image 1: immutable character sheet
- Image 2: approved environment and style anchor

Primary request:
Describe only the new story action and emotional beat.

Subject:
Preserve the same character identities, ages, proportions, facial features,
hair, clothing and recognition props from Image 1.

Scene/backdrop:
Preserve the same architecture, palette, lighting logic and paper texture
from Image 2. Include only continuity props required by the current beat.

Constraints:
- exact number of visible characters;
- no character redesign;
- no readable generated text;
- no logos or watermark;
- center-safe for both 16:9 and 9:16 when required.

Avoid:
face drift, wardrobe changes, mentor poses, exaggerated anime expressions,
photorealism, glossy 3D, unrequested people or props.
```

## Gate đề xuất trước khi scale

Không tạo cả season ngay. Trước tiên thử 6–8 keyframe của tập 1 và chấm thủ công:

- identity consistency;
- location consistency;
- story accuracy;
- crop safety;
- khả năng tái sử dụng pose/background;
- số lượt sửa trung bình trên mỗi frame.

Nếu mỗi frame liên tục cần nhiều lượt sửa identity, phương án nên chuyển sang character cutout cố định trên background thay vì sinh nguyên scene.

## Quy trình cho một tập mới (áp dụng trong claude-ytb)

Đây là tài liệu vận hành, KHÔNG phải prompt gửi cho LLM viết kịch bản — nó
không nằm trong `profile.json → prompts`. Kịch bản chỉ được dùng những
filename đã khai trong `render.scene_assets`.

1. Đọc `continuity-ledger.json` để biết trạng thái nhân vật và các thread
   đang mở; đọc `visual-bible.md` để biết ngôn ngữ hình.
2. Sinh 5–8 keyframe cho tập, mỗi lần dùng `assets/character-sheet.png` làm
   identity anchor và một keyframe ĐÃ DUYỆT làm environment/style anchor,
   theo prompt pattern ở trên.
3. Duyệt tay từng frame theo checklist: identity, bối cảnh, đúng cảnh trong
   kịch bản, crop an toàn cả 16:9 lẫn 9:16.
4. Đặt frame đã duyệt vào `assets/` với tên mô tả beat (`empty-outline.png`,
   không phải `frame-03.png`).
5. Khai đúng những filename đó vào `render.scene_assets` trong `profile.json`
   và tăng `version` của profile — script cũ khai version cũ sẽ fail-closed
   ở renderer thay vì render nhầm bộ ảnh.

Bước 5 là lý do phải khai tường minh: một tập chỉ được dùng đúng bộ ảnh mà
nó được viết cho, và pipeline phát hiện lệch trước khi tốn render.
