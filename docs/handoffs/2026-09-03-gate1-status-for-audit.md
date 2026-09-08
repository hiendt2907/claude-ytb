# Gate 1 — trạng thái để audit độc lập (2026-09-03)

Mục đích: đưa cho một reviewer độc lập (Codex) kiểm tra. Mọi con số dưới đây
đều lấy từ log/đo thật và có thể chạy lại. Phần không chứng minh được ghi rõ ở
§5, không giấu trong văn xuôi.

## 0. Kết luận ngắn

**Chưa có video. Chưa có verdict.** Chưa một lần nào chuỗi đi hết
ideation → produce → render. Điểm chặn hiện tại vẫn nằm ở **ideation**, không
phải render hay publish.

Suite: `1411 passed, 3 skipped, 1 deselected`.
Nhánh: `codex/production-readiness-e2e-gate1`. 11 commit mới trong phiên
2026-09-02 (`72699c5` … `433dc85`).

## 1. Vì sao Gate 1 kéo dài — nguyên nhân đo được

Gộp toàn bộ log production thật (đã lọc log của test) cho một hình dạng lặp
lại: **một luật được thi hành ở một nơi mà không được nói ở nơi kia.**

- cổng chặn thứ prompt không cấm;
- bản sửa bị chấm theo ràng buộc không ai nói cho nó;
- lỗi provider bị đọc ở tầng trên thành lỗi model.

Từng cái nhìn riêng trông như xui. Gộp lại, chúng là lý do mỗi lượt sinh
8–16 phút bị ném đi. Đó là chi phí, không phải độ khó kỹ thuật.

## 2. Đã sửa — mỗi mục kèm số đo

| # | commit | lỗi | bằng chứng |
|---|---|---|---|
| 1 | `72699c5` | `unrenderable_visual_intent` không có đường sửa hẹp | 3/5 lượt bị từ chối thuộc riêng luật này |
| 2 | `d639bd6` | Vision provider không retry lỗi transport | ~250 lời gọi Judge/video; 1 timeout giết cả node sau khi đã sinh ảnh |
| 3 | `76213e5` | repair của Long không biết ngân sách độ dài | 278.1s / sàn 297.0s sau 2 lượt rewrite |
| 4 | `8539904` | **sửa ngược lỗi do #3 gây ra** | ngân sách ép lời chốt "879–2346 ký tự" trong khi luật đòi 2–3 câu |
| 5 | `8e99d64` | guard lọt 2 dạng cử chỉ Judge đã hard-fail | 4 shot: semantic 0.0–0.2, character/continuity ~1.0 |
| 6 | `2c6acd1` | profile 2.3.0 — An chỉ có lệnh cấm trừu tượng | 2 lượt liên tiếp bị loại vì An thành coach |
| 7 | `cf24cf6` | tên cast khớp theo âm tiết | `xác minh` → `['xác','minh']` → báo rò rỉ tên nhân vật |
| 8 | `e8363f9` | retry U+FFFD vô hình | 3 lần retry để lại đúng 1 dòng log |
| 9 | `433dc85` | candidate bị loại không được nhớ giữa các lần chạy | gateway cache: cùng prompt → cùng sha256 |

### 2.1 Hai mục đáng soi kỹ

**#7 (`cf24cf6`)** — nghiêm trọng nhất và ẩn nhất. Cổng chống rò rỉ tên nhân
vật tách text thành âm tiết rồi so với `voice_cast`. Trong tiếng Việt đó không
phải phép thử tên: `xác minh`, `chứng minh`, `thông minh`, `minh bạch` đều khớp
`minh`. Tập đang viết nói về **một cuộc gọi xác minh**, nên cổng gần như không
thể qua. Cùng gốc lỗi có ở `_check_story_hook` nhưng **ngược chiều** — ở đó tên
cast là bằng chứng "cảnh mở có neo", nên một hook chỉ nói "xác minh" được cho
qua. Cổng chặn nhầm thì tự lộ; cổng **cho qua nhầm** thì không.

**#9 (`433dc85`)** — đo trực tiếp, ba lần cùng một prompt:

```
lần 1: 14.20s  sha=bf49062e7cc86756  len=915
lần 2:  0.43s  sha=bf49062e7cc86756  len=915
lần 3:  0.27s  sha=bf49062e7cc86756  len=915
```

Gateway xKiro cache request giống hệt. Hệ quả: **thử lại với brief không đổi
không thể ra kịch bản khác** — nó phát lại đúng bản cũ trong 2 giây. Ba "lượt
thử lại" hôm 2026-09-02 hỏng y hệt nhau: cùng section được sửa
`[2,5,6,12,13,19]`, cùng dòng normalize, cùng câu vi phạm.

Trong **một** lần chạy engine đã chống lặp đúng (`REJECTED — do not reuse`).
Nhưng lần chạy **mới** dựng lại lịch sử từ `ledger.md`, còn bản bị loại — dù đã
lưu xuống `assets/script_revisions/failed_ideation/` — **chưa bao giờ được đọc
lại**; thư mục đó (171 file) chỉ được ghi vào.

## 3. Dụng cụ đo từng nói dối — 6 lần

Ghi riêng vì đây là loại nguy hiểm hơn lỗi engine: lỗi engine tốn một lượt
chạy, **dụng cụ hỏng làm mọi kết luận sau nó không an toàn**, kể cả những kết
luận đã báo đi.

| dụng cụ | báo | thật ra |
|---|---|---|
| `classify.py` | lỗi đã sửa xong | nguyên nhân là `editorial_review` |
| `classify.py` | 1 lớp | có 2 lớp; thứ tự bảng luật quyết định |
| `classify.py` | regex văn xuôi khớp nhầm | dữ liệu vốn có cấu trúc `'rule': '<tên>'` |
| `inspect_visuals.py` | `DONE` | project không tồn tại |
| `check_video.sh` | im lặng sau 5 tầng | không có kết luận từng tầng |
| `gate1.sh` | `PASS` | ideation đã crash (chỉ dò dấu `✗`, traceback lọt) |

Tất cả đã sửa. `gate1.sh` giờ lấy **exit code** làm nguồn sự thật và chỉ báo
PASS khi **có file script mới trên đĩa**. `check_video.sh` kết bằng bảng
ĐẠT/HỎNG từng tầng và câu: *5 tầng sạch vẫn chưa đủ để kết luận PASS — còn
phải ngồi xem hết video.*

Thêm 2 lần **probe của tôi** sai (không phải engine): tự ghép đường dẫn ảnh
thiếu tiền tố `assets/`; gọi `QAAgent.run(script)` thay vì context dict. Cả hai
đều suýt thành kết luận sai về engine.

## 4. Trạng thái hiện tại

Kịch bản mới nhất trên đĩa: `scripts/noi-ra-roi-ma-chua-nhe.json`
(Long, 23 section, profile 2.3.0, 5270 ký tự lời đọc), viết lúc 21:22 trong
lượt chạy bị dừng lúc 21:27.

Chạy lại các cổng offline lên chính file đó:

```
contract publishable : True
QA agent (strict)    : passed = True
editorial rubric     : 6/10  (ngưỡng 9/10)
  human_truth 8 · spoken_naturalness 7 · causal_coherence 7
  role_fidelity 6 · useful_restraint 5
  - An ép Minh ra quyết định và nói hộ hệ quả (section 14, 21)
  - Kết narrator nâng thành quy luật chung 'Nếu bạn...' (section 23)
  - Lời An liệt kê quan sát quá chi tiết, nghe như tường thuật (section 4)
```

**Nên file này KHÔNG dùng được.** Hai cổng tất định đạt, rubric loại. Ngưỡng
9/10 không được hạ và không được đi vòng.

Đáng chú ý cho reviewer: bản sửa `2c6acd1` nhắm vào **câu hỏi chẩn đoán** của
An và giữ được ở lượt sau; rubric giờ bắt An ở **một dạng khác** — ép ra quyết
định và nói hộ hệ quả. Cùng nhân vật, cùng xu hướng "giúp hộ", biểu hiện khác.

## 5. Chưa chứng minh được — đọc kỹ phần này

- **Chưa có video nào đi qua kiến trúc ScenePlan + VisualJudge.** Mọi project
  cũ trong `assets/projects/` đều là DAG 4-node của kiến trúc cũ. Node
  `scene_plan` và `visual_assets` **chưa từng chạy thật lần nào**.
- **Điểm 4 và 5 của bất biến TTS↔STT** (audio rút từ chính MP4) **chưa từng
  được chạy** — chưa có MP4 để chạy.
- **U+FFFD ở kích thước sinh đầy đủ.** Đo: 5/5 sạch ở 64 token, 3/3 sạch ở
  1200 token, 3/3 hỏng ở 14000 token. Tương quan kích thước là **giả thuyết**,
  chưa phải kết luận. Nếu đúng, cách sửa là chia nhỏ generation — thuộc kiến
  trúc **đang đóng băng**, tôi không tự mở. Retry 3 lượt là thứ duy nhất dùng
  được trong v1.
- **Hai lượt chạy nền bị giết từ bên ngoài** (2026-09-02, ~11 phút và ~15
  phút), cả hai đúng lúc `rewrite: editorial score below profile bar`. Đã loại
  trừ OOM (RAM 47% free, không có bản ghi jetsam). **Không xác định được
  nguyên nhân.** Xử lý bằng thiết kế: chạy `nohup … & disown` để tiến trình
  không còn là con của task wrapper. Đã sống qua trọn lượt sau đó.
- **Profile không khai bối cảnh dựng được.** Không gì ngăn ideation viết cảnh
  mà profile không dựng nổi; hiện chỉ brief chặn.
- **`gain_db` chấp nhận tới +12 dB.**

## 6. Điều tôi làm sai trong phiên này

Ghi để reviewer cân đúng độ tin của phần còn lại:

1. `76213e5` giới thiệu một lỗi giết lượt chạy kế tiếp; `8539904` sửa ngược.
   Ba test Short cũ là thứ bắt được bản sửa đầu của tôi đang nuốt mất một cái
   sàn có thật — **tôi không sửa các test đó**.
2. Tôi báo "ideation ĐẠT" một lần khi thực tế nó crash — do runner chỉ dò dấu
   `✗`. Đã ghi bản đính chính vào ledger.
3. Tôi phân loại sai nguyên nhân một lượt hỏng, báo đúng cái engine vừa chạy
   **đúng**. Đã ghi bản đính chính.
4. Tôi vá ràng buộc vào brief thay vì vá vào engine trong nhiều vòng trước —
   cứu đúng một chủ đề, không giúp chủ đề sau.

## 7. Cách kiểm chứng lại

```bash
.venv/bin/pytest -q                       # 1411 passed
cat assets/production_readiness/gate1/attempts.tsv   # mọi lượt + 2 bản đính chính
docs/production-readiness/RUNBOOK-gate1.md           # quy trình + bảng 3 tầng sở hữu
docs/handoffs/2026-09-02-engine-fixes-from-gate1-attempts.md
```

Ledger dùng cột `owner` làm cột chính: nó nói **tầng nào phải sửa**, không phải
lỗi trông như thế nào.
