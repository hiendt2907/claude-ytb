# claude-ytb

Pipeline tự động hoá sản xuất nội dung và kiếm tiền từ YouTube, chạy trên macOS.

## 4 khâu

1. **Ideation** — sinh ý tưởng + kịch bản bằng local LLM
2. **Voiceover** — TTS (edge-tts miễn phí / ElevenLabs) + thu thập media
3. **Render** — dựng video bằng moviepy/ffmpeg, sinh thumbnail
4. **Publish** — upload YouTube Data API + SEO + analytics

## Cài đặt / cập nhật — 1 lệnh duy nhất

Dùng cho cả **máy mới chưa có repo** lẫn **máy đã cài muốn update ngay**:

```bash
GH_TOKEN=ghp_xxx bash <(curl -fsSL "https://$GH_TOKEN@raw.githubusercontent.com/hiendt2907/claude-ytb/main/scripts/bootstrap.sh")
```

`GH_TOKEN` là GitHub Personal Access Token (PAT) có quyền đọc repo — tạo tại
GitHub → Settings → Developer settings → Personal access tokens → Fine-grained →
chỉ cần permission `Contents: Read-only` cho repo này.

Script tự phát hiện trạng thái máy:
- **Chưa có repo** → clone về `~/claude-ytb` rồi chạy `setup.sh`
- **Đã có repo** → `git pull` bản mới nhất rồi re-run `setup.sh` (idempotent, không đè key)

Cuối cùng hỏi có muốn cài Telegram listener + auto-update daemon không.

Token được lưu vào `remote URL` của git để auto-update daemon dùng cho các lần
pull sau — không cần nhập lại. Nếu token hết hạn, chạy lại lệnh trên với token mới.

**Trigger update thủ công** (không chờ daemon 30 phút):

```bash
ytb update
```

---

## Cài đặt trên máy mới (cách thủ công)

```bash
git clone git@github.com:hiendt2907/claude-ytb.git
cd claude-ytb
make setup              # cài ffmpeg, venv, requirements, tạo .env + thư mục runtime
```

`make setup` chạy `scripts/setup.sh`: kiểm tra local runtime + Homebrew, cài `ffmpeg`
nếu thiếu, tạo `.venv` + cài `requirements.txt`, tạo `secrets/` `data/` `assets/`
(gitignored nên không có sẵn sau khi clone), copy `.env.example` → `.env` (không
đè nếu đã có), rồi **hỏi tay từng API key/secret** (kèm hướng dẫn lấy ở đâu) và
tự điền vào `.env` — Enter để bỏ qua, điền lại sau cũng được. Idempotent — chạy
lại an toàn, không đè key đã điền.

Các key được hỏi (không bắt buộc phải có hết cho lần chạy thử đầu tiên):

| Key | Khi nào cần |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Muốn điều khiển pipeline qua Telegram |
| `PEXELS_API_KEY` | Chỉ khi `RENDER_PROVIDER=ai` (B-roll stock) |
| `ELEVENLABS_API_KEY` | Chỉ khi `TTS_PROVIDER=elevenlabs` |
| `YOUTUBE_API_KEY` | Chỉ để research trending, không bắt buộc cho upload |
| `secrets/client_secret.json` | File JSON OAuth — chỉ cần khi `DRY_RUN=false` (publish thật) |

```bash
make test               # xác nhận môi trường chạy đúng
```

Mặc định `DRY_RUN=true` — chỉ render local, không upload thật. `TTS_PROVIDER=edge`
(miễn phí, không cần model nào) là provider mặc định.

### Giọng nhân bản local (F5-TTS) — tuỳ chọn

Provider `f5` dùng model fine-tune tiếng Việt (~5.4GB, tải từ HuggingFace) để
nhân bản giọng từ `assets/ref/narrator.wav` (đã có sẵn trong repo):

```bash
make setup-f5            # cài .venv-tts (Python 3.12) + tải model_last.pt
```

Cần `python3.12` (`brew install python@3.12` nếu chưa có). Sau khi xong, đặt
`TTS_PROVIDER=f5` trong `.env`.

## Bộ lệnh CLI (`ytb`)

Toàn bộ pipeline điều khiển qua lệnh `ytb`. Cài symlink để gõ từ bất kỳ đâu:

```bash
ln -sf "$PWD/bin/ytb" ~/.local/bin/ytb   # hoặc /usr/local/bin/ytb
```

### Lệnh top-level

```bash
ytb doctor               # kiểm tra môi trường: token, config, queue, ledger
ytb auth                 # đăng nhập lại OAuth (mở browser) cho YouTube + Drive
ytb batch <lệnh>         # toàn bộ batch workflow (xem bên dưới)
```

### Quy trình sản xuất

```bash
# 1. Viết kịch bản (mặc định dùng local LLM)
ytb batch start -n 5 --type-of-vid long --local   # LLM tự chọn chủ đề
ytb batch start -n 3 --type-of-vid short --local  # video dọc 1-2 phút
ytb batch start -n 10 --type-of-vid short --local --idea "cơ chế trì hoãn"  # chủ đề chỉ định
ytb batch start -n 10 --type-of-vid short --local --idea "cơ chế xấu hổ" --clear-ledger  # backup + reset ledger cũ
ytb batch start --ask --local  # hỏi tương tác số lượng, loại video, ý tưởng, clear ledger

# 2. Kiểm tra trước khi chạy
ytb doctor                # token OAuth, Telegram, script JSON còn đủ không
ytb batch status          # xem done/pending từng video trong queue

# 3. Render + publish
ytb batch run             # chạy 1 video kế tiếp rồi dừng
ytb batch run --loop      # chạy hết queue, không cần lặp tay
```

### Theo dõi tiến độ (mở terminal khác)

```bash
ytb batch ps                        # slug + PID + thời gian đang chạy
ytb batch logs --current            # tail -f log video đang chạy (không cần biết slug)
ytb batch logs <slug>               # log của 1 video cụ thể
ytb batch logs <slug> -f            # tail -f trực tiếp
ytb batch logs <slug> --tail 200    # xem nhiều dòng hơn (mặc định 50)
ytb batch logs --warnings           # log cảnh báo retry/lỗi — đưa cho Claude fix
```

### Quản lý queue

```bash
ytb batch status          # done/pending từng video theo thứ tự day
ytb batch queue           # in JSON đầy đủ (để pipe qua jq)
ytb batch stop            # dừng graceful run/retry đang chạy — resume đúng video đó sau
ytb batch retry <slug>    # chạy lại ngay 1 slug cụ thể (slug phải trong queue)
ytb batch reset <slug>    # đưa video đã done về pending (render lại từ đầu)
ytb batch cancel <slug>   # huỷ khỏi queue vĩnh viễn (topic lỗi thời, không sản xuất nữa)
```

> **`reset` vs `cancel`:** `reset` giữ slug trong queue và cho phép `run` nhặt lại;
> `cancel` xoá hẳn khỏi queue. Cả hai đều không thể chạy khi slug đang được xử lý —
> dùng `stop` trước.

### Xác minh & ledger

```bash
ytb batch verify <youtube_id>   # xác minh video thật qua YouTube API (không tin stdout)
ytb batch ledger                # 20 dòng cuối ledger.md
ytb batch ledger --tail 50      # xem nhiều hơn
```

### Daemon (Telegram listener + auto-update)

```bash
make listen-install      # Telegram listener — điều khiển pipeline từ Telegram
make listen-uninstall
make listen-logs         # tail log listener

make update-install      # auto-update — poll git remote mỗi 30 phút, tự pull + rollback
make update-uninstall
make update-run          # chạy thử 1 lượt ngay
make update-logs
```

## Tự động cập nhật code mới

Sau khi đã `make setup` 1 lần, máy có thể tự đồng bộ mỗi khi có commit mới
trên `main` — không cần SSH vào lại để `git pull` tay mỗi lần.

Mỗi lượt poll: `git fetch` (retry nếu mạng chập chờn) → nếu có commit mới thì
`git pull --ff-only` → chạy lại `setup.sh` (cài lib/dep mới nếu `requirements.txt`
đổi) → smoke test. Nếu bất kỳ bước nào fail → **tự rollback** về commit cũ, không
để máy kẹt ở trạng thái nửa vá. Luôn báo qua Telegram. Tự bỏ qua nếu đang có
batch render/upload chạy dở. Log chi tiết từng lượt: `assets/update_logs/`.

Vì repo là private, máy cần quyền đọc qua SSH. Khuyên dùng **Deploy Key**
(SSH key riêng chỉ-đọc, tạo trên máy đó bằng `ssh-keygen`, thêm public key
vào GitHub repo → Settings → Deploy keys).
