# claude-ytb

Pipeline tự động hoá sản xuất nội dung và kiếm tiền từ YouTube, chạy trên macOS.

## 4 khâu

1. **Ideation** — sinh ý tưởng + kịch bản bằng Claude
2. **Voiceover** — TTS (edge-tts miễn phí / ElevenLabs) + thu thập media
3. **Render** — dựng video bằng moviepy/ffmpeg, sinh thumbnail
4. **Publish** — upload YouTube Data API + SEO + analytics

## Khởi động nhanh

```bash
brew install ffmpeg
make setup
cp .env.example .env   # điền ANTHROPIC_API_KEY ...
make run TOPIC="5 mẹo năng suất với AI"
make test
```

Mặc định `DRY_RUN=true` — chỉ render local, không upload thật.

## Dashboard web

Một trang điều khiển + cấu hình toàn pipeline (chạy kịch bản, giao việc
`/youtube-auto`, duyệt kịch bản, sửa **mọi** cấu hình, xem ledger/log).

```bash
# đặt mật khẩu trước (bắt buộc khi mở ra ngoài)
echo 'DASHBOARD_PASSWORD=<mật-khẩu-mạnh>' >> .env
make dashboard            # http://127.0.0.1:8765
```

**Cấu hình động:** giá trị sửa trên tab *Cấu hình* ghi vào `data/config.json`
(gitignored), ưu tiên cao hơn `.env`. Mọi tiến trình (dashboard, listener,
pipeline) đọc lại file này khi khởi tạo `Settings` — không cần sửa `.env` tay.
Telegram vẫn chạy song song; cổng duyệt hiện trên cả web lẫn Telegram.

### Truy cập từ xa qua Cloudflare Tunnel

Máy đặt ở công ty, expose qua `ytb.nginxwaf.xyz` (không mở port vào mạng nội bộ):

```bash
brew install cloudflared
cloudflared tunnel login                      # chọn zone nginxwaf.xyz
cloudflared tunnel create ytb-dashboard       # tạo tunnel + credentials json
cloudflared tunnel route dns ytb-dashboard ytb.nginxwaf.xyz
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: ytb-dashboard
credentials-file: /Users/hiendang/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: ytb.nginxwaf.xyz
    service: http://127.0.0.1:8765
  - service: http_status:404
```

```bash
make dashboard   # terminal 1
make tunnel      # terminal 2  → https://ytb.nginxwaf.xyz
```

Giữ `DASHBOARD_HOST=127.0.0.1` để chỉ tunnel truy cập được, không phơi ra LAN.
Nên bật **Cloudflare Access** (Zero Trust) trước hostname để thêm 1 lớp đăng nhập.
