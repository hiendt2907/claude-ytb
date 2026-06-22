---
name: iphone-video-maker
description: Cắt ghép, chỉnh sửa và render hoàn chỉnh các clip quay trên iPhone (KOL/quảng cáo sản phẩm, video cá nhân) thành 1 video — trim từng đoạn, slow-mo/tua nhanh, zoom Ken Burns theo cảnh, crossfade, nhạc nền. KHÔNG có voice-over, text, badge, hay emoji — thuần cắt/ghép/render. Việc cá nhân/dự án riêng, KHÔNG liên quan đến pipeline YouTube của project — không đọc/viết gì trong src/, assets/, data/, scripts/ của repo. Dùng khi người dùng nói cắm điện thoại, đưa clip raw cần edit, làm video brand/KOL, hoặc gọi /iphone-video-maker.
version: 3.0.0
source: personal
---

# iPhone Video Maker

Skill cá nhân/dự án riêng, tách biệt hoàn toàn khỏi pipeline YouTube (`src/ytb_pipeline`).
Mục đích: lấy clip raw quay trên iPhone (quảng cáo sản phẩm cho brand/KOL, video cá nhân...),
**cắt ghép từng đoạn theo ý muốn, chỉnh tốc độ, zoom Ken Burns nhẹ theo cảnh, nối crossfade,
mix nhạc nền**, render ra 1 video hoàn chỉnh. KHÔNG có voice-over, KHÔNG burn text/badge/emoji
lên video.

> Lưu ý lịch sử: bản đầu dùng `ifuse` mount trực tiếp DCIM qua cáp, nhưng cần macFUSE (kernel
> extension, phải build from source + cấp quyền System Settings + có thể restart máy) — đã bỏ
> để tránh đụng cấu hình hệ thống. Hiện tại đọc clip từ một **thư mục import cố định** (AirDrop
> hoặc Photos.app export).

## Yêu cầu hệ thống

```bash
brew install ffmpeg        # đủ dùng cho toàn bộ pipeline: trim/scale/crop/xfade/atempo
```

`edit_render.py` tự ưu tiên `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` nếu có trên máy
(không bắt buộc), fallback về `ffmpeg` thường nếu không.

## Bước 1 — Đưa clip raw vào thư mục import

```bash
mkdir -p ~/Movies/iphone-video-maker/import
```

- **AirDrop**: từ iPhone AirDrop clip sang Mac → lưu vào thư mục trên (hoặc Downloads rồi `mv`).
- **Photos.app**: chọn clip → File > Export > **Export Unmodified Original(s)** (không chọn
  "Export Photos..." vì sẽ render lại/đổi định dạng) → chọn thư mục trên (dùng ⌘+Shift+G để
  gõ path nếu hộp thoại không cho gõ thẳng).

## Bước 2 — Tự động dựng draft EDL (auto_pipeline.py)

Đây là chỗ tối giản thao tác tay nhất có thể: **code tự làm mọi phần code làm được**,
chỉ phần "cần nhìn để biết" mới bàn giao cho Claude — và Claude chỉ chạm vào việc đó
**MỘT LẦN DUY NHẤT**, không quay lại sửa file nhiều lượt.

```bash
python3 .claude/skills/iphone-video-maker/scripts/auto_pipeline.py
```

Script này tự động (không cần Claude, không hỏi gì) — **Python đóng vai "máy quay
phim", tự dò chỗ nào trong từng clip có khả năng là 1 điểm cắt** (giống cách app
dựng video kiểu TikTok tự gợi ý cut point), thay vì chia đều theo thời gian:
1. Quét toàn bộ clip `.MOV/.mp4` trong `import/`.
2. Với mỗi clip, dò **điểm cắt ứng viên** bằng 2 detector: scene-change (ffmpeg
   `select=gt(scene,X)` — đổi góc máy/cắt cảnh đột ngột) + motion-magnitude (ffmpeg
   `scdet` — chuyển từ tĩnh sang động trong cùng 1 cú quay liên tục) — không chia
   đều theo giây như trước. Tối đa `MAX_BEATS_PER_CLIP` đoạn/clip (xem hằng số đầu
   `extract_frames.py`).
3. Trích **1 frame đại diện cho mỗi đoạn ứng viên** vào `stage/frames/<tên clip>/beat_NN.jpg`
   — đây là cái Claude Read để quyết. Đồng thời cắt sẵn **1 clip .mp4 ngắn thật**
   (cùng số thứ tự) vào `stage/cuts/<tên clip>/beat_NN.mp4` — chỉ để BẠN bấm xem
   nhanh bằng Finder/QuickTime (phím Space = Quick Look) khi muốn kiểm lại quyết
   định của Claude, không phải input cho bước render.
4. Viết `edl.json` (draft, **không phải bản chính thức**) với **1 entry/đoạn ứng
   viên** (không phải 1 entry/clip nữa): `file`/`start`/`end` theo đúng ranh giới đã
   dò/`speed=1.0`, `scene` để `null`, kèm field tạm `_frame` (đường dẫn frame đại
   diện của riêng đoạn đó).

## Bước 3 — Claude là "não": nhận biết hành vi từng đoạn, quyết giữ/cắt (1 lần, không Edit lặp lại)

Python đã tự lo phần cơ học (tìm điểm cắt, cắt thô). Việc duy nhất Claude phải
làm — vì code không "nhìn" được **hành vi đang diễn ra** trong từng đoạn — là xem
1 frame/đoạn rồi quyết GIỮ hay CẮT BỎ, KHÔNG phải phần ghi file:

1. Read frame `_frame` của **từng đoạn ứng viên** (một lượt, không lặp lại) — chú ý:
   nhiều đoạn có thể cùng `file` (cùng 1 clip gốc bị Python tách thành nhiều đoạn).
2. Trong đầu (không Edit `edl.json`), với **mỗi đoạn**, quyết định:
   - **CẮT BỎ hẳn entry đó** nếu là đoạn chết/dư: tay cầm đứng yên không hành động,
     đoạn mờ/rung/chuyển cảnh dở, hoặc lặp nội dung đoạn khác đã giữ.
   - Nếu **GIỮ**: gán `scene` — một trong `hook`/`unbox`/`demo`/`testimonial`/`cta`
     theo đúng **hành vi** đang diễn ra trong đoạn đó (mở hộp/bóc seal → `unbox`,
     cầm dùng/đổ ra tay → `demo`, đoạn đầu gây chú ý có chuyển động mạnh → `hook`,
     nói cảm nhận → `testimonial`, đoạn chốt cuối cùng → `cta`). Mỗi nhãn tự kéo
     theo 1 kiểu zoom/color grade riêng trong `edit_render.py` (`SCENE_STYLES`).
   - Tinh chỉnh thêm `start`/`end` trong phạm vi đoạn nếu biên Python dò chưa khớp
     hành động thật (vd lùi `start` vài frame để bắt đúng lúc tay vừa chạm vào vật).
   - `speed`: dùng slow-mo (`<1.0`) cho khoảnh khắc "đã" (mở nắp, đổ viên ra tay),
     tua nhanh (`>1.0`) cho đoạn di chuyển/chờ không quan trọng.
   - Cảnh `hook` mở đầu nên NGẮN (1–3s, có chuyển động) — không lấy nguyên đoạn dài
     đọc thông tin tĩnh làm hook.
3. **Write** (không phải Edit) toàn bộ EDL hoàn chỉnh — đã điền hết các đoạn GIỮ,
   đã xoá hẳn các đoạn CẮT BỎ, đã xoá sạch mọi field `_frame` — ra **một file draft
   mới**, ví dụ `~/Movies/iphone-video-maker/stage/edl_draft.json`.
4. Gọi đúng 1 lệnh, xong, không làm gì thêm:

```bash
python3 .claude/skills/iphone-video-maker/scripts/finalize_edl.py \
  ~/Movies/iphone-video-maker/stage/edl_draft.json
```

`finalize_edl.py` (thuần Python, không cần Claude nữa) tự:
- Validate: mọi `file` khớp clip có thật trong `import/`, mọi `scene` hợp lệ, không
  còn field `_frame`/`_frames` — báo lỗi rõ ràng và dừng nếu sai (Claude sửa lại
  draft và gọi lại lệnh trên, vẫn không cần Edit `edl.json` chính thức).
- Ghi draft đã validate thành `edl.json` chính thức.
- **Tự gọi render** (`edit_render.py`) luôn — không cần lệnh tiếp theo nào.

Tổng cộng cho 1 lượt: Claude tốn token đúng 1 lần (đọc frame từng đoạn + quyết
giữ/cắt/scene), sau đó toàn bộ — validate, ghi file, render — là code Python,
không quay lại hỏi/sửa gì thêm. `edit_render.py` không cần đổi gì: 1 file gốc xuất
hiện nhiều lần trong `clips` với `start`/`end` khác nhau đã là cú pháp hợp lệ sẵn có.

> Muốn xử lý thêm clip mới: thả clip vào `import/` rồi chạy lại `auto_pipeline.py` —
> script ghi đè draft mới từ toàn bộ `import/` hiện tại (không cộng dồn với bản cũ).

## Render (tự động, đã gọi sẵn trong Bước 3)

`finalize_edl.py` tự gọi script này — chỉ cần chạy tay khi muốn render lại một
`edl.json` đã có sẵn (không qua Claude lại):

```bash
python3 .claude/skills/iphone-video-maker/scripts/edit_render.py ~/Movies/iphone-video-maker/edl.json
```

(Không truyền path → tự dùng `~/Movies/iphone-video-maker/edl.json`.)

Engine tự: với mỗi clip trong `clips` → trim đúng đoạn → zoom Ken Burns/punch nhẹ theo
`scene` (`SCENE_STYLES`) → scale/pad về khung **2K dọc cố định 1440x2560** (chuẩn TikTok/Reels
9:16, hằng số `TARGET_W`/`TARGET_H` trong `edit_render.py`) → áp tốc độ (`setpts`+`atempo`) →
nối toàn bộ bằng `xfade`/`acrossfade` → mix nhạc nền nếu có `music` → xuất
`output/<output_name>.mp4`, Finder tự mở thư mục output. KHÔNG có bước burn text/badge/emoji
hay chèn voice-over nào.

> Clip nguồn ngang hay dọc đều tự `scale + pad` (letterbox/pillarbox) về đúng khung 1440x2560,
> không bị méo hình. Muốn đổi sang khung khác (vd ngang 16:9 2560x1440, hoặc Full HD dọc
> 1080x1920) → sửa 2 hằng số `TARGET_W`/`TARGET_H` đầu file `edit_render.py`.

Muốn sửa/lặp lại: sửa `edl.json` (tay hoặc chạy lại `auto_pipeline.py`), chạy lại lệnh trên —
không cần xoá gì tay, `stage/` tự dọn mỗi lần chạy (trừ `stage/frames/`, do `auto_pipeline.py`
tự quản lý riêng).

### Nếu muốn viết EDL tay (không qua auto-discovery)

Vẫn dùng được — xem schema đầy đủ ở `scripts/edl.example.json`. Field `scene` là optional,
bỏ trống/`null` thì dùng style mặc định (`demo`).

## Vùng dữ liệu — cách ly khỏi project

Tất cả nằm ngoài repo, trong `~/Movies/iphone-video-maker/`:

- `import/` — clip raw bạn tự đưa vào, không tự xoá.
- `edl.json` — EDL hiện tại, do `auto_pipeline.py` tự sinh, Claude patch thêm `scene`.
- `stage/frames/<tên clip>/` — frame mẫu do `auto_pipeline.py`/`extract_frames.py` trích để
  Claude xem; tự dọn riêng theo từng clip, không bị `edit_render.py` xoá khi render.
- `stage/` (còn lại) — đoạn đã trim/chuẩn hoá, xoá sạch mỗi lần render lại.
- `output/` — video cuối theo `output_name`, không tự xoá (giữ lại để xem/gửi brand).

Engine không đụng tới `assets/`, `data/`, `scripts/` (kịch bản YouTube) hay `src/ytb_pipeline`
của project.

## Script cũ (nối thô không EDL)

`scripts/make_video.sh` vẫn còn — chỉ nối nguyên clip theo thời gian quay + crossfade, không
trim/speed. Dùng khi chỉ cần ghép nhanh, không cần chỉnh sửa chi tiết:

```bash
bash .claude/skills/iphone-video-maker/scripts/make_video.sh all
```

## Khi cần chỉnh / debug

- **ffprobe trả dimensions có dấu phẩy thừa** (`3840,2160,`): đã xử lý trong `edit_render.py`
  bằng `rstrip(",")` — nếu gặp lỗi parse width/height tương tự ở chỗ khác, áp dụng cùng cách.
- **Đổi kiểu/độ dài chuyển cảnh**: sửa `transition`/`transition_duration` trong `edl.json`,
  không cần sửa code.
- **Muốn audio gốc bị tắt hoàn toàn khi có nhạc nền** (không mix): sửa `mix_music()` trong
  `edit_render.py`, đổi `amix` thành chỉ map track nhạc (`-map 1:a` thay vì filter `amix`).
- **Đổi/thêm nhãn cảnh hoặc style zoom/hiệu ứng theo cảnh**: sửa dict `SCENE_STYLES` đầu
  `edit_render.py` — mỗi nhãn có `extra_vf` (filter ffmpeg áp thêm, vd `eq=...`, `vignette`),
  `zoom_end` (hệ số zoom Ken Burns) và `punch` (cú giật zoom nhẹ đầu đoạn). Test logic mapping
  này (không cần ffmpeg) bằng
  `python3 -m pytest .claude/skills/iphone-video-maker/scripts/test_scene_styles.py`.
- **Chỉnh số frame mẫu/khoảng cách trích frame**: sửa `INTERVAL_SEC`/`MAX_FRAMES_PER_CLIP`
  đầu `extract_frames.py` (mặc định 3s/clip, tối đa 8 frame).
- **`auto_pipeline.py` ghi đè `edl.json` cũ mất nội dung đã sửa tay**: đúng hành vi — script
  này coi `import/` là nguồn sự thật, build lại từ đầu mỗi lần chạy. Nếu đã sửa tay và muốn
  giữ, copy `edl.json` ra tên khác trước khi chạy lại `auto_pipeline.py`.
