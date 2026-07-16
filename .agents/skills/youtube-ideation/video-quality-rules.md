# Bộ rules chất lượng video — áp cho MỌI video

Rút ra từ phản hồi biên tập (Gemini/YouTube) và kinh nghiệm sản xuất. Đây là
**nguyên tắc chung, không gắn cứng một chủ đề**. Mọi kịch bản sinh ở khâu ideation
PHẢI thoả các rule dưới đây trước khi đưa sang duyệt Telegram. Khi viết script JSON,
ánh xạ rule → cấu trúc `segments` (caption/narration/broll).

## 0. CỔNG KIỂM DUYỆT — verify TRƯỚC khi lên kịch bản (BẮT BUỘC, chạy đầu tiên)

Trước khi sinh body/segments, MỌI ý tưởng + nội dung dự kiến PHẢI được rà soát và
ghi nhận kết quả verify. Nếu một mục FAIL → dừng, sửa hoặc loại ý tưởng, KHÔNG đưa
sang viết kịch bản. Đây là cổng chặn đặt trước tất cả rule chất lượng bên dưới.

- **Tiêu chuẩn cộng đồng YouTube (Community Guidelines):** không nội dung bạo lực/gây
  hại, thù ghét, quấy rối, thông tin sai lệch y tế/bầu cử, nguy hiểm/thử thách rủi ro,
  nội dung người lớn, spam/lừa đảo. Nội dung nhạy cảm phải xử lý đúng chính sách.
- **Bản quyền & sở hữu trí tuệ:** không sao chép kịch bản/giọng/nhạc/hình của bên khác.
  Nhạc nền, B-roll, hình ảnh phải là nguồn được phép (CC/royalty-free/tự sinh, nhãn rõ
  license). Trích dẫn/quote phải fair-use hợp lý, ghi nguồn. Không dùng logo/thương hiệu
  gây nhầm lẫn.
- **Tính chính xác & nguồn:** số liệu, tuyên bố y tế/tài chính/pháp lý phải kiểm chứng từ
  nguồn uy tín; tránh khẳng định tuyệt đối gây hiểu lầm. Ghi lại nguồn trong metadata.
- **An toàn quảng cáo (advertiser-friendly / monetization):** tránh chủ đề/ngôn từ làm mất
  kiếm tiền (bạo lực đồ hoạ, chửi thề nặng, chủ đề gây sốc tiêu cực). Nội dung cho/đụng
  tới trẻ em phải tuân thủ COPPA (đặt "made for kids" đúng).
- **Đạo nhái & trùng lặp:** không reupload, không nội dung lặp lại hàng loạt (reused content).
- **Tuyên bố minh bạch:** nếu có tài trợ/khẳng định AI-generated theo yêu cầu nền tảng → khai báo.

Ghi kết quả verify (PASS/FAIL + ghi chú nguồn) vào metadata/ý tưởng và đính kèm khi gửi
duyệt Telegram, để user thấy đã kiểm trước khi duyệt.

## 0b. KHUNG SHORT — độ dài 1–1.5 phút + KHÔNG hiện số thứ tự (ÉP ở code)

- **Short BẮT BUỘC trong 1–1.5 phút (~60–90s).** Short không khai báo
  `target_minutes`; `generator.load_script` **fail-fast** nếu narration ước lượng
  (~1.197 ký tự/phút ở tốc độ TTS 2×) ngắn hơn 1 phút (quá ngắn, sơ sài) hoặc dài hơn
  1.5 phút (lê thê, vượt khung). Narration phải trong **1.197–1.795 ký tự**, nhắm
  khoảng 1.496 ký tự — đi thẳng vào trọng tâm, không nhồi câu đệm cho đủ phút.
- **TUYỆT ĐỐI KHÔNG render badge số thứ tự** kiểu "1/5", "2/5" trên khung hình. Người
  xem không cần biết đang ở phần mấy; con số này làm rối và lộ "công thức". Renderer đã
  gỡ badge — kịch bản cũng không được yêu cầu hiển thị đếm phần/tổng.
- Nội dung dù ngắn vẫn phải **chi tiết, cụ thể** (xem mục 2) — không nhồi cho đủ phút
  bằng câu chung chung; mỗi giây phải có thông tin.

## 0c. CỔNG VERIFY NGÁCH — "phát triển bản thân THẬT, không self-help" (BẮT BUỘC, rà từng câu)

Ngách kênh: **hiểu cơ chế con người để tự vận hành tốt hơn** (tâm lý/hành vi học ứng
dụng + mental models + ra quyết định). Đây là cổng phân biệt kênh này với hàng nghìn
kênh self-help AI-gen sáo rỗng. Rà **từng câu narration**; câu nào FAIL → sửa hoặc CẮT
trước khi đính bảng verify gửi Telegram. Ba gate dưới đây **không châm chước**.

### Gate 1 — KHÔNG self-help (mỗi câu khẳng định dạy CƠ CHẾ, không hô khẩu hiệu)

Với mỗi câu mang tính khuyên/khẳng định, hỏi: *"câu này giải thích CƠ CHẾ tại sao, hay
chỉ HÔ KHẨU HIỆU?"* Khẩu hiệu → FAIL, viết lại thành cơ chế hoặc cắt.

- ❌ "Hãy tin vào bản thân." / "Kỷ luật là chìa khoá thành công." / "Chỉ cần cố gắng hơn."
- ✅ "Ý chí cạn dần trong ngày vì vỏ não trước trán tiêu glucose khi tự kiểm soát — nên
  việc khó nên xếp vào buổi sáng, lúc 'pin' còn đầy, thay vì ép mình lúc cuối ngày."
- Cấm tuyệt đối: câu động viên cảm xúc rỗng, châm ngôn không kèm lý do, hứa hẹn "thay đổi
  cuộc đời" mà không nêu được con đường nhân-quả.
- Test nhanh: nếu xoá câu đi mà người xem **không mất thông tin nào về cách-mọi-thứ-vận-hành**
  → đó là khẩu hiệu, cắt.

### Gate 2 — MẬT ĐỘ Ý: không khoảng chết, nhất là vùng "phút 4–8 tử thần"

Video 12–15 phút chết ở khúc giữa khi nội dung lặp/đệm chữ. Rà theo CHƯƠNG:

- Mỗi chương phải mang **ít nhất một ý MỚI** (cơ chế mới, bằng chứng mới, hệ quả mới).
  Chương chỉ diễn giải lại ý chương trước → gộp hoặc cắt.
- **Câu đệm không tải ý → cắt.** Câu chỉ chuyển tiếp cảm xúc ("và điều này thật sự quan
  trọng", "bạn biết không") mà không thêm dữ kiện đều là khoảng chết.
- **Re-hook mỗi 60–90s:** mỗi chương kết bằng một móc mở vòng tò mò mới ("nhưng đây mới
  là chỗ ngược đời…") để kéo qua vùng giữa. Đánh dấu `"transition": true` ở các bước ngoặt.
- Test nhanh: đọc to script, bấm giờ. Đoạn nào mình thấy muốn-tua → khán giả cũng tua, sửa.

### Gate 3 — NGUỒN TRUY ĐƯỢC, tuyệt đối không bịa (chống ảo giác AI)

Ngách này AI cực dễ bịa: tên giáo sư, năm nghiên cứu, con số "73% người…". **Một cái bịa
lọt qua là mất uy tín cả kênh.** Với mỗi số liệu / nghiên cứu / tên riêng / khái niệm dẫn ra:

- Phải có **nguồn truy được** (tên nghiên cứu/tác giả/tổ chức + có thể tìm lại). Ghi nguồn
  vào bảng verify.
- **Không truy được → CẮT câu đó**, không viết "tin tạm" hay làm tròn. Thà nói nguyên lý
  định tính đúng còn hơn bịa một con số cụ thể sai.
- Cấm "số liệu trang trí" kiểu "nghiên cứu cho thấy…", "các chuyên gia nói…" không tên.
  Nêu được đích danh thì giữ; không thì viết lại thành cơ chế không cần con số.
- Với khái niệm có thật (vd "nghịch lý lựa chọn", "hiệu ứng Zeigarnik") — nêu **đúng** định
  nghĩa, không gán sai cho tác giả/hiện tượng khác.

### Bảng verify ngách đính kèm khi gửi Telegram

Ngoài bảng compliance (mục 0), gửi kèm bảng: mỗi tuyên bố/số liệu trong script → **nguồn
gì + PASS/FAIL** ba gate trên. User thấy rõ đã rà từng câu trước khi duyệt.

## 0d. SERIES — chuỗi tập cùng ngách, liên kết tạo thói quen xem (BẮT BUỘC cho mọi tập)

Kênh chạy theo **series**: một ngách xuyên suốt, mỗi tập một cơ chế, các tập **móc vào nhau**
để biến người xem vãng lai thành người xem quay lại + đăng ký. Mỗi kịch bản mới PHẢI khớp các
ràng buộc series dưới đây trước khi lên nội dung.

- **Ngách cố định:** "**phát triển bản thân THẬT, không self-help**" — hiểu cơ chế con người
  (tâm lý/hành vi học ứng dụng + mental models + ra quyết định). Không trôi sang chủ đề lạc
  ngách (tin tức, giải trí rời rạc, mẹo vặt vô cơ chế). Mọi tập đều đi qua cổng **0c**.
- **Một cơ chế / một tập:** mỗi tập đào sâu **đúng một cơ chế** (vd hiệu ứng Zeigarnik, ý chí
  cạn glucose, nghịch lý lựa chọn…). Không gộp 5 mẹo rời. Cơ chế đã làm → KHÔNG lặp (đối chiếu
  `data/ledger.md` trước khi viết — xem luật chống trùng).
- **Giọng & nhận diện nhất quán:** cùng giọng kể ẩn danh, cùng tông (bình tĩnh, dẫn chứng, xưng
  "bạn"), cùng cấu trúc 5 phần (hook nghịch lý → vấn đề → cơ chế tại sao → khung áp dụng →
  chốt + cầu nối tập sau). Người xem phải nhận ra "đây là kênh đó" chỉ trong 10s.
- **Liên kết tập (chuỗi tò mò xuyên tập):**
  - **Mở:** được phép callback nhẹ tập trước ("Tập trước ta nói vì sao ý chí cạn; hôm nay là
    cách lách nó") — nối mạch, KHÔNG bắt buộc đã xem tập cũ mới hiểu (mỗi tập vẫn tự đứng được).
  - **Kết:** BẮT BUỘC một **cầu nối tập sau** — gieo câu hỏi/nghịch lý mà tập tiếp giải, tạo lý
    do quay lại. Đây là khác biệt chính so với video lẻ. Đặt ngay trước CTA câu hỏi (mục 5).
- **Tên tập nhất quán nhưng KHÔNG đánh số trên khung hình:** title có thể theo motif series
  (cùng kiểu đặt câu/đại từ), nhưng TUYỆT ĐỐI không badge "Tập 3", "EP05" trên video (như mục
  0b với short). Đánh số nếu cần chỉ để trong `description`/playlist, không render lên hình.
- **Gom playlist:** mỗi tập thuộc một playlist series (set ở khâu publish/metadata) để YouTube
  đẩy "tập tiếp theo" + tăng phiên xem nhiều tập.

## 1. Hook — 5-8 giây đầu phải chặn ngón tay lướt (KPI: Stayed to watch ≥ 60%)

> **Số liệu thực (video tGjjuq2QK-Y, 2026-06-16):** AVP 143% (người đã xem thì xem
> lại nhiều lần — nội dung giữ chân RẤT tốt) NHƯNG **Stayed to watch chỉ 13.11%** —
> đa số lướt qua không dừng lại. Nút thắt nằm ở phần mở đầu. Mục tiêu mọi video Short:
> kéo Stayed to watch lên **≥ 60%**.

- **Hook hành động trải trong 5-8 GIÂY đầu** (đã nới từ 2s): câu/hình đầu phải tạo
  chuyển động hoặc xung đột tức thì, không "khởi động" từ từ — nhưng cả cụm
  hook + dẫn vào vấn đề phải gói gọn trong 5-8s đầu, không lê thê hơn.
- Mở bằng **kết quả gây sốc / mất mát / lệnh cấm**, KHÔNG mở bằng định nghĩa hiền lành.
- Khung hình ĐẦU TIÊN phải có visual mạnh (chuyển động/con người/biểu tượng cấm) —
  feed Shorts quyết định trong ~1s; caption + B-roll segment đầu phải "đập vào mắt".
- Dựng "kẻ thù chung" + giải pháp tức thì ngay câu đầu.
  - ❌ "Cách bạn bắt đầu buổi sáng quyết định cả ngày."
  - ✅ "Dừng ngay việc cầm điện thoại khi vừa ngủ dậy — đây là 3 việc làm thay thế."
- Câu hook ≤ 2 dòng, động từ mệnh lệnh, đại từ "bạn".
- Áp dụng cho cả tiêu đề: ưu tiên động từ cấm/cảnh báo/con số.

## 1b. MỞ ĐẦU LONG-FORM — lời chào + đọc tiêu đề (CHỈ video dài, KHÔNG áp short)

Tách hẳn short ↔ long. **Short:** vào hook thẳng theo mục 1, KHÔNG chào, KHÔNG đọc tiêu
đề. **Video dài (ngang):** mở đầu chỉn chu theo 3 nhịp dưới, gói trong **một segment mở
đầu chuyên biệt** để TTS đọc liền mạch (chào → tiêu đề → móc), rồi mới vào thân bài.

Trật tự 3 nhịp, mỗi nhịp một việc, **không trùng câu nhau và không trùng câu đầu thân bài**:

1. **Lời chào** — phần CỐ ĐỊNH duy nhất là cụm **"Mến chào các bạn,"** (luôn mở bằng đúng
   cụm này). Phần CÒN LẠI của câu chào do kịch bản **tự sinh, đa dạng theo chủ đề** — không
   fix cứng cả câu. Ví dụ: "Mến chào các bạn, bạn có đang mất tập trung vào công việc không?"
   / "Mến chào các bạn, đã bao giờ bạn cố ép mình kỷ luật mà vẫn thất bại chưa?"
2. **Đọc tiêu đề** — voice đọc tên video ra tiếng (đóng khung kỳ vọng + tốt cho người nghe
   nền). Lấy từ `title` nhưng diễn đạt tự nhiên cho giọng đọc, không nhất thiết y nguyên chuỗi.
3. **Câu móc chạm nỗi đau** — câu hỏi/nghịch lý hướng vào "bạn", dẫn vào cơ chế của tập.

- **Toàn bộ mở đầu (chào + tiêu đề + móc) phải gọn trong ~5–8 giây đầu.** CẤM mở đầu lê thê
  kiểu "chào mừng quay lại kênh, nhớ like share đăng ký, hôm nay chúng ta sẽ…".
- Vế-sinh-thêm của câu chào và câu móc nên **bổ sung** nhau, không lặp ý; và không được trùng
  câu hook/câu đầu của thân bài.
- Lời mời đăng ký/like KHÔNG đặt ở mở đầu — để dành CTA cuối (mục 5).

## 2. Cấu trúc nội dung — logic có thể nêu thành tầng + GIẢI QUYẾT VẤN ĐỀ

- **Chuyển từ "đưa thông tin" → "giải quyết vấn đề".** Đừng chỉ liệt kê ("3 thói quen");
  trả lời được câu **"Làm sao thực hiện được dù bận rộn / dù khó?"** Mỗi video phải gỡ
  một trở ngại thực tế của người xem, không chỉ kể ra điều nên làm.
- Mỗi ý nên kèm cách áp dụng cụ thể, ít rào cản ("chỉ cần 30 giây", "ngay khi vừa
  ngủ dậy") — biến lời khuyên thành hành động làm được liền.
- Sắp xếp các ý theo một trục rõ ràng (vd Tâm trí → Cơ thể → Công việc; Dễ → Khó;
  Trước → Sau). Người xem phải cảm nhận được mạch, không phải danh sách rời.
- Mỗi luận điểm kèm **một câu "tại sao" cực ngắn** (lợi ích/hệ quả), đừng chỉ nêu việc.
  - Ví dụ: "Chỉ làm một việc — tập trung tối đa thay vì dàn trải sẽ bớt áp lực hơn."
- **Trước khi viết, trả lời rõ: "Khán giả NHẬN ĐƯỢC GÌ sau khi xem?"** Nếu không nêu
  được một lợi ích cụ thể → ý tưởng chưa đủ giá trị, sửa hoặc loại.

### 2a. CẤM CHUNG CHUNG — áp cho CẢ SHORT (không chỉ video dài)

Nội dung mơ hồ là lỗi bị loại số 1. Mỗi luận điểm trong Short PHẢI có **tối thiểu 3/4**
yếu tố sau (video dài thì đủ cả 4 — xem mục 2b):

1. **Khẳng định** rõ ràng, 1 câu, có động từ hành động.
2. **Cơ chế "tại sao"** — lý do tâm lý/sinh học/logic đằng sau, KHÔNG chỉ "hãy làm X".
   - ❌ "Uống nước buổi sáng rất tốt." → ✅ "Sau 7–8 tiếng ngủ cơ thể mất ~0,5 lít nước
     qua hơi thở, uống ngay 1 cốc giúp máu bớt đặc, tỉnh táo nhanh hơn cà phê."
3. **Con số / khái niệm / ví dụ CỤ THỂ** có thật (đã VERIFY mục 0): "quy tắc 2 phút",
   "15 phút đầu", "0,5 lít", tên nghiên cứu/phương pháp — không nói "nhiều", "rất", "một số".
4. **Bước áp dụng làm-được-ngay** + rào cản thấp ("chỉ 30 giây", "ngay khi mở mắt").

- Mỗi caption/segment phải **tự nó mang một thông tin mới**; nếu một đoạn chỉ lặp ý hoặc
  toàn tính từ ("tuyệt vời", "thay đổi cuộc đời") mà không có dữ kiện → viết lại hoặc bỏ.
- Thay mọi từ định lượng mơ hồ bằng con số/khoảng cụ thể khi có thể.

## 2b. VIDEO DÀI (ngang) — ÉP độ dài & độ sâu (BẮT BUỘC khi nhận lệnh "video ngang/dài")

Khi lệnh yêu cầu **video dài / ngang**, kịch bản phải đạt:

- **Độ dài narration 12–15 phút.** Đặt `"target_minutes": <12..15>` ở cấp gốc JSON —
  `generator.load_script` **fail-fast** nếu nội dung mỏng hơn target, dưới 12 phút, hoặc
  vượt 15 phút (ước lượng ~**1.197 ký tự narration/phút** ở tốc độ TTS 2×). Quy đổi:
  - 12 phút ≈ **14.364 ký tự** narration; 15 phút ≈ **17.955 ký tự**.
  - Chia thành **24–36 section** để renderer cắt cảnh đủ nhịp.
- **CẤM nói chung chung / mơ hồ.** Mỗi luận điểm phải đào sâu theo khuôn:
  1. **Khẳng định** rõ ràng (1 câu).
  2. **Cơ chế / tại sao** — giải thích tâm lý/khoa học/logic đằng sau (không chỉ "hãy làm X").
  3. **Bằng chứng cụ thể** — số liệu, nghiên cứu, tên/khái niệm có thật, **đã VERIFY nguồn**
     (mục 0). Ví dụ "lãi suất kép", "quy tắc 2 phút", "nguyên tắc 5 giây" — nêu đúng, có dẫn.
  4. **Ví dụ / tình huống thực tế** — một câu chuyện ngắn, con số minh hoạ, kịch bản đời thực.
  5. **Bước áp dụng** chi tiết + **cạm bẫy thường gặp** khi làm.
- **Mỗi chương dày 1.5–4 phút**, không lướt. Liệt kê hời hợt = loại.
- **Cấu trúc chương + timestamps** trong `description` (00:00, 02:30, …) khớp mạch section.
- Vẫn giữ hook mạnh (mục 1) + nhịp cắt (mục 3) + CTA câu hỏi (mục 5). Dài KHÔNG nghĩa là chậm:
  giữ năng lượng, mỗi đoạn một "móc" dẫn sang đoạn sau.

> Lý do: video dài kiếm tiền (watch-time) chỉ giữ chân khi **dày thông tin chính xác, hữu
> ích** — nội dung chung chung 6 phút bị bỏ giữa chừng, hỏng cả AVP lẫn YPP.

## 3. Nhịp độ — cắt sớm, không để cảnh đẹp kéo dài

- Cảnh thư giãn/minh hoạ (rót nước, phong cảnh…) **cắt ngắn**, chuyển ý nhanh.
- **Nhịp cắt cảnh ≤ 3 giây/cảnh** (siết từ 3–6s): mỗi cảnh không quá 3 giây để giữ
  năng lượng & retention; cảnh nào dài hơn phải có lý do (thông tin dày, demo).
- Loại "khoảng chết": nếu một đoạn không thêm thông tin mới → rút gọn hoặc bỏ.

## 4. Hình ảnh đắt — B-roll phải minh hoạ đúng hành động/ẩn dụ

- Mỗi segment có `broll` (từ khoá tiếng Anh) bám sát NỘI DUNG đoạn, không chung chung.
- Với điều "nên tránh", chọn hình thể hiện **sự cấm/nguy hiểm**: tay rụt khỏi điện
  thoại, biểu tượng gạch chéo đỏ, "stop"… (tăng sức nặng cảm xúc).
- Ưu tiên hình có chuyển động/con người hơn ảnh tĩnh trừu tượng.

### 4b. Field điều khiển biên tập hình ảnh (render-ai tự dựng theo)

Mỗi section có thể khai báo thêm 3 field (đều tùy chọn) để render-ai dựng đúng nhịp:

- `"emphasis": ["Quy tắc 2 phút", "lãi suất kép"]` — từ khoá/con số cốt lõi của đoạn.
  Render pop chip lớn ở upper-third đúng lúc (visual aid củng cố luận điểm). Chỉ chọn
  1–2 từ khoá ĐẮT mỗi đoạn, không nhồi.
- `"hook": true` — đoạn có **cảnh hành động năng lượng cao** (chống đẩy, gõ phím nhanh,
  đổ mồ hôi…). Render dồn B-roll các đoạn này thành cold-open mở đầu video (giữ chân
  10s đầu) TRƯỚC khi vào kể chuyện chậm. Đánh dấu 1–3 đoạn hành động nhất.
- `"transition": true` — đặt ở đoạn mở **bước ngoặt** (đặc biệt vấn đề→giải pháp).
  Render chèn whoosh SFX + xfade ngay trước đoạn để báo hiệu chuyển mạch.

Render luôn tự cắt mỗi segment thành nhiều beat ≤6s + Ken Burns motion (không còn
cảnh tĩnh dài) — 3 field trên chỉ thêm lớp biên tập chủ đích, không bắt buộc.

## 5. CTA — kết bằng CÂU HỎI để kéo bình luận

- Đừng kết chỉ bằng "đăng ký kênh". Thêm **một câu hỏi mở** mời người xem comment.
  - Ví dụ: "Sáng mai bạn thử thói quen nào đầu tiên? Comment bên dưới nhé!"
- Câu hỏi phải dễ trả lời trong 1 dòng (chọn A/B, kể trải nghiệm, đặt mục tiêu).
- Vẫn giữ lời mời đăng ký, nhưng đặt SAU câu hỏi tương tác.
- **Trật tự kết của video dài (series):** cầu nối tập sau (mục 0d) → câu hỏi mời comment → mời
  đăng ký để "đón tập tới". Ba nhịp này nối nhau, không rời rạc.

## 6. Giọng & độ giữ chân

- Xưng "bạn", câu ngắn, chủ động; tránh câu phức nhiều mệnh đề.
- Mỗi đoạn nên có một "móc" nhỏ dẫn sang đoạn sau (gây tò mò, đếm ngược "việc thứ 3…").

## Checklist trước khi gửi duyệt (ideation tự rà)

- [ ] **VERIFY trước tiên:** đạt tiêu chuẩn cộng đồng YouTube, không vi phạm bản quyền
- [ ] **VERIFY:** nguồn nhạc/hình/B-roll hợp lệ (license rõ); số liệu/tuyên bố đã kiểm chứng
- [ ] **VERIFY:** advertiser-friendly + COPPA (made-for-kids) đúng; không reupload/lặp
- [ ] **VERIFY NGÁCH — Gate 1 (không self-help):** mỗi câu khẳng định dạy CƠ CHẾ, không khẩu hiệu rỗng; câu nào xoá đi không mất thông tin → đã cắt
- [ ] **VERIFY NGÁCH — Gate 2 (mật độ ý):** mỗi chương ≥1 ý mới; cắt câu đệm không tải ý; re-hook mỗi 60–90s qua vùng phút 4–8
- [ ] **VERIFY NGÁCH — Gate 3 (nguồn truy được):** mọi số liệu/nghiên cứu/tên riêng có nguồn truy được; không truy được → đã cắt; không "số liệu trang trí" vô danh
- [ ] **Bảng verify ngách** (mỗi tuyên bố → nguồn + PASS/FAIL 3 gate) đính kèm khi gửi Telegram
- [ ] **SERIES (mục 0d):** đúng ngách "cơ chế con người"; **một cơ chế/tập** chưa trùng ledger; giọng/cấu trúc nhất quán; kết có **cầu nối tập sau**; KHÔNG badge "Tập n" trên hình; gán playlist series
- [ ] **Hook 2s đầu** có hành động/kết quả sốc/lệnh cấm + visual mạnh ngay khung đầu (mục tiêu Stayed-to-watch ≥60%)
- [ ] Có "kẻ thù chung" + giải pháp tức thì ở câu đầu (khi hợp ngữ cảnh)
- [ ] Trả lời được **"Khán giả nhận được gì?"** + góc giải-quyết-vấn-đề (làm được dù bận rộn)
- [ ] **Short: narration trong 1–1.5 phút** (1.197–1.795 ký tự, nhắm ~1.496); KHÔNG có badge "n/total"
- [ ] **Không chung chung:** mỗi luận điểm có ≥3/4 (khẳng định + cơ chế + số/ví dụ cụ thể + bước áp dụng); đã thay từ mơ hồ bằng con số
- [ ] Các ý sắp theo một trục logic nêu được thành lời
- [ ] Mỗi luận điểm có 1 câu "tại sao" ngắn + cách áp dụng ít rào cản
- [ ] **Nhịp cắt ≤ 3s/cảnh**; không có cảnh minh hoạ kéo dài thừa
- [ ] Mỗi segment có `broll` bám sát nội dung; điều cần tránh dùng hình "cấm/nguy hiểm"
- [ ] 1–3 đoạn hành động đánh dấu `"hook": true`; bước ngoặt vấn đề→giải pháp `"transition": true`
- [ ] Đoạn có khái niệm/con số cốt lõi gắn `"emphasis"` (1–2 từ khoá đắt)
- [ ] **Mở đầu LONG-FORM (mục 1b):** segment mở đầu mở bằng đúng cụm **"Mến chào các bạn,"** (phần sau tự sinh đa dạng) → voice đọc tiêu đề → câu móc; gọn ~5–8s; KHÔNG mời đăng ký ở đầu; không trùng câu thân bài. (Short: KHÔNG chào/đọc tiêu đề)
- [ ] **Nếu là video dài/ngang:** có `"target_minutes"` 12–15; narration 14.364–17.955 ký
      tự (~1.197 ký tự/phút ở TTS 2×); mỗi luận điểm có cơ chế + bằng chứng có nguồn + ví dụ thực tế + bước áp dụng
      (KHÔNG chung chung); description có timestamps chương
- [ ] CTA kết bằng CÂU HỎI mời comment, rồi mới mời đăng ký
- [ ] Toàn bộ xưng "bạn", câu ngắn chủ động, có móc nối đoạn
