# video-render

Công cụ dựng video từ video source có sẵn — thay thế CapCut cho use case
KOL/KOC/affiliate cần ra nhiều video biến thể từ cùng một buổi quay.

Xem `CLAUDE.md` và `PROJECT_VISION.md` (Amendment Log 2026-07-07) để biết
đầy đủ spec/mission.

## Setup nhanh từ GitHub

Yêu cầu chung:

- Python 3.11 trở lên.
- FFmpeg/FFprobe có trong `PATH`.
- Git để clone source.

Clone repo:

```bash
git clone https://github.com/hiendt2907/render-video.git
cd render-video
```

### macOS

Nếu chưa có FFmpeg:

```bash
brew install ffmpeg
```

Cài app:

```bash
chmod +x scripts/*.sh
scripts/install_macos.sh
```

Chạy Web UI:

```bash
scripts/run_macos.sh
```

Mở trình duyệt tại `http://127.0.0.1:8000`.

### Windows

Yêu cầu: Python 3.11+ đã tick **Add python.exe to PATH** khi cài đặt.

Mở PowerShell trong thư mục repo, rồi chạy:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install_windows.ps1
.\scripts\run_windows.ps1
```

Script sẽ thử cài FFmpeg bằng `winget` nếu máy chưa có. Nếu không có `winget`,
cài FFmpeg thủ công từ `https://www.gyan.dev/ffmpeg/builds/` rồi thêm thư mục
`bin` của FFmpeg vào `PATH`.

Sau khi app chạy, mở `http://127.0.0.1:8000`.

## Input

- Nhiều **thư mục cảnh** theo đúng thứ tự cảnh (VD `scene_00/`, `scene_01/`...),
  mỗi thư mục chứa nhiều clip source ứng viên cho cảnh đó. Trong 1 thư mục,
  file đặt tên theo số thứ tự phụ (VD `1.1.mp4`, `1.2.mp4`) để quyết định thứ
  tự nối clip khi nhiều clip được chọn cho cùng 1 cảnh.
- **Một voice track** cho toàn bộ video.
- Số lượng output **N** do user chọn.

Ví dụ cấu trúc input:

```text
my-project/
  scenes/
    scene_00/
      1.1.mp4
      1.2.mp4
      1.3.mp4
    scene_01/
      2.1.mp4
      2.2.mp4
    scene_02/
      3.1.mp4
      3.2.mp4
  voice.m4a
  output/
```

Trong Web UI:

1. Chọn thư mục `scenes`.
2. Chọn file voice, ví dụ `voice.m4a`.
3. Chọn thư mục output.
4. Chọn profile dựng tự động.
5. Bấm **Xem thử** trước, sau đó bấm **Render full** nếu preview ổn.

## Bản cho người dùng không rành kỹ thuật

Không gửi source code cho người dùng cuối. Hãy build app tự chứa trước:

### macOS

Chạy trên máy macOS:

```bash
scripts/build_macos_app.sh
```

Gửi cho người dùng file:

- `dist/Video Render-macOS.dmg`

Người dùng chỉ cần mở file `.dmg`, mở **Video Render.app**, app sẽ tự mở trình
duyệt tại `http://127.0.0.1:8000`. Bản này đã bundle Python, dependency Python,
`ffmpeg` và `ffprobe`; máy người dùng không cần cài gì thêm.

Lưu ý: để người dùng mở app không bị cảnh báo bảo mật của macOS, bản phát hành
thật nên được ký bằng Apple Developer ID và notarize. Bản build local hiện dùng
ad-hoc signing, phù hợp để test nội bộ.

### Windows

Chạy trên máy Windows:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\build_windows_exe.ps1
```

Gửi cho người dùng file:

- `dist\Video Render.exe`

Người dùng chỉ cần double-click file `.exe`. Bản này đã bundle Python,
dependency Python, `ffmpeg` và `ffprobe`; máy người dùng không cần cài gì thêm.

Lưu ý: để tránh Windows SmartScreen cảnh báo, bản phát hành thật nên được ký
code-signing certificate.

## Cài đặt thủ công

### Máy đang phát triển

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
brew install ffmpeg   # bắt buộc, gọi qua subprocess khi render
```

## Chạy — Web UI (khuyến nghị, thao tác bằng chuột)

```bash
.venv/bin/video-render
```

Mở http://127.0.0.1:8000 — nhập đường dẫn thư mục scenes, voice track, tên
sản phẩm, N, chế độ thời lượng, bấm "Render". Tiến độ + link tải video hiện
ngay trên trang, tự cập nhật.

Nếu port `8000` đang bận, tắt app cũ trước rồi chạy lại:

```bash
pkill -f "ytb_pipeline.webui.app"
.venv/bin/video-render
```

## Đóng gói source để dev/debug trên máy khác

Chỉ dùng cách này cho dev/debug, không dùng cho người dùng non-tech. Cách này
vẫn cần máy đích có Python/internet để cài dependency.

### Chuẩn bị gói gửi đi

Từ thư mục project:

```bash
scripts/make_portable_zip.sh
```

Gửi file `dist/video-render-portable.zip` cho máy khác, giải nén ra một thư
mục dễ nhớ, ví dụ `Documents/video-render`.

### Cài trên macOS

Yêu cầu: Python 3.11+ và Homebrew nếu máy chưa có `ffmpeg`.

```bash
cd ~/Documents/video-render
chmod +x scripts/*.sh
scripts/install_macos.sh
scripts/run_macos.sh
```

Sau đó mở `http://127.0.0.1:8000`.

### Cài trên Windows

Yêu cầu: Python 3.11+ đã tick **Add python.exe to PATH**. Script sẽ thử cài
`ffmpeg` bằng `winget`; nếu máy không có `winget`, cài FFmpeg thủ công rồi
thêm thư mục `bin` của FFmpeg vào `PATH`.

Mở PowerShell tại thư mục đã giải nén:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install_windows.ps1
.\scripts\run_windows.ps1
```

Sau đó mở `http://127.0.0.1:8000`.

### Lệnh sau khi đã install

Nếu muốn chạy trực tiếp trong virtualenv:

```bash
.venv/bin/video-render          # macOS
.\.venv\Scripts\video-render.exe # Windows PowerShell
```

CLI render vẫn có sẵn qua lệnh `video-render-cli`.

## Chạy — CLI

```bash
.venv/bin/video-render-cli \
  --scenes-dir path/to/scenes \
  --voice-track path/to/voice.wav \
  --product-name my_product \
  --n-outputs 10 \
  --duration-mode clip_length   # hoặc voice_silence
```

Output: `output/<product_name>/variant_01.mp4` ... `variant_N.mp4`.

## Test

```bash
.venv/bin/pytest
```

## Lỗi thường gặp

### `ffmpeg` hoặc `ffprobe` không tìm thấy

Cài FFmpeg rồi mở terminal/PowerShell mới:

```bash
brew install ffmpeg
```

Trên Windows, cài bằng `winget install --id Gyan.FFmpeg -e` hoặc cài thủ công
và thêm thư mục `bin` vào `PATH`.

### Web UI vẫn chạy code cũ sau khi sửa source

Server không auto reload. Tắt process cũ rồi chạy lại app.

### Video output bị ngắn hoặc chất lượng chưa ổn

Hãy thử profile dựng khác trong Web UI, bấm **Xem thử**, rồi render full.
App sẽ tự kiểm tra freeze/black frame/fps sau khi render và hiện lời khuyên
trên màn hình.
