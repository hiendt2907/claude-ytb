# claude-ytb

Pipeline tự động hoá sản xuất nội dung và kiếm tiền từ YouTube, chạy trên macOS.

## 4 khâu

1. **Ideation** — sinh ý tưởng + kịch bản bằng Claude
2. **Voiceover** — TTS (edge-tts miễn phí / ElevenLabs) + thu thập media
3. **Render** — dựng video bằng moviepy/ffmpeg, sinh thumbnail
4. **Publish** — upload YouTube Data API + SEO + analytics

## Cài đặt trên máy mới

```bash
git clone git@github.com:hiendt2907/claude-ytb.git
cd claude-ytb
make setup              # cài ffmpeg, venv, requirements, tạo .env + thư mục runtime
```

`make setup` chạy `scripts/setup.sh`: kiểm tra Homebrew, cài `ffmpeg` nếu thiếu,
tạo `.venv` + cài `requirements.txt`, tạo `secrets/` `data/` `assets/output/`
`assets/audio/` (gitignored nên không có sẵn sau khi clone), và copy
`.env.example` → `.env` (không đè nếu đã có). Idempotent — chạy lại an toàn.

Sau khi setup, mở `.env` điền key cần dùng (tuỳ tính năng, không phải tất cả
đều bắt buộc cho lần chạy thử đầu tiên):

| Key | Khi nào cần |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Muốn duyệt kịch bản qua Telegram (mặc định `TELEGRAM_APPROVAL=true`) |
| `PEXELS_API_KEY` | Chỉ khi `RENDER_PROVIDER=ai` (B-roll stock) |
| `ELEVENLABS_API_KEY` | Chỉ khi `TTS_PROVIDER=elevenlabs` |
| `YOUTUBE_*` + `secrets/client_secret.json` | Chỉ khi `DRY_RUN=false` (publish thật lên YouTube) |

```bash
make test                                # xác nhận môi trường chạy đúng
make run TOPIC="5 mẹo năng suất với AI"  # chạy thử pipeline
```

Mặc định `DRY_RUN=true` — chỉ render local, không upload thật. `TTS_PROVIDER=edge`
(miễn phí, không cần model nào) là provider mặc định nên có thể chạy thử ngay
sau `make setup` mà không cần điền key gì.

### Giọng nhân bản local (F5-TTS) — tuỳ chọn

Provider `f5` dùng model fine-tune tiếng Việt (~5.4GB, tải từ HuggingFace) để
nhân bản giọng từ `assets/ref/narrator.wav` (đã có sẵn trong repo). Không bắt
buộc — chỉ cần khi muốn giọng đọc khác `edge-tts`:

```bash
make setup-f5            # cài .venv-tts (Python 3.12) + tải model_last.pt
```

Cần `python3.12` (`brew install python@3.12` nếu chưa có). Sau khi xong, đặt
`TTS_PROVIDER=f5` trong `.env`.

Điều khiển pipeline qua Telegram (`make listen-install`) hoặc CLI (`make run`).
Không có dashboard web — chưa tới lúc làm UI.
