#!/usr/bin/env bash
# Cài đặt toàn bộ pipeline trên máy mới: ffmpeg, venv chính (.venv), requirements,
# .env, thư mục runtime gitignored. Chạy 1 lần sau khi git clone.
#
# F5-TTS (giọng nhân bản local, model ~5.4GB) là TUỲ CHỌN — mặc định pipeline
# dùng TTS_PROVIDER=edge (miễn phí, không cần model). Bật F5 bằng --with-f5-voice.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

WITH_F5=false
for arg in "$@"; do
  case "$arg" in
    --with-f5-voice) WITH_F5=true ;;
    *)
      echo "❌ Tham số không hợp lệ: $arg (chỉ nhận --with-f5-voice)" >&2
      exit 1
      ;;
  esac
done

echo "==> Kiểm tra hệ điều hành"
if [[ "$(uname)" != "Darwin" ]]; then
  echo "⚠️  Pipeline này build cho macOS (ffmpeg/launchd). Máy khác có thể lỗi ở bước sau." >&2
fi

echo "==> Kiểm tra Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  echo "❌ Chưa có Homebrew. Cài tại https://brew.sh rồi chạy lại script này." >&2
  exit 1
fi

echo "==> ffmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "   đã có: $(ffmpeg -version | head -1)"
else
  brew install ffmpeg
fi

echo "==> venv chính (.venv) + requirements.txt"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "==> Thư mục runtime (gitignored, cần tồn tại trước khi chạy)"
mkdir -p secrets assets/output assets/audio data

echo "==> .env"
if [[ -f .env ]]; then
  echo "   .env đã tồn tại — giữ nguyên, không đè."
else
  cp .env.example .env
  echo "   đã tạo .env từ .env.example — điền API key cần dùng (xem README)."
fi

if $WITH_F5; then
  echo "==> [TUỲ CHỌN] F5-TTS — giọng nhân bản local (~5.4GB model)"
  if ! command -v python3.12 >/dev/null 2>&1; then
    echo "❌ Cần python3.12 cho .venv-tts (F5-TTS chưa hỗ trợ Python mới hơn)." >&2
    echo "   Cài: brew install python@3.12" >&2
    exit 1
  fi
  if [[ ! -x .venv-tts/bin/python ]]; then
    python3.12 -m venv .venv-tts
  fi
  .venv-tts/bin/pip install --upgrade pip -q
  .venv-tts/bin/pip install f5-tts -q

  mkdir -p models/vivoice
  BASE_URL="https://huggingface.co/hynt/F5-TTS-Vietnamese-ViVoice/resolve/main"
  if [[ -f models/vivoice/model_last.pt ]]; then
    echo "   model_last.pt đã có — bỏ qua tải lại."
  else
    echo "   tải model_last.pt (~5.4GB, tuỳ mạng có thể mất nhiều phút)..."
    curl -L --fail -o models/vivoice/model_last.pt "$BASE_URL/model_last.pt"
  fi
  if [[ ! -f models/vivoice/config.json ]]; then
    curl -L --fail -o models/vivoice/config.json "$BASE_URL/config.json"
  fi
  echo "   xong — đặt TTS_PROVIDER=f5 trong .env để dùng giọng nhân bản từ"
  echo "   assets/ref/narrator.wav (đã có sẵn trong repo)."
else
  echo "==> Bỏ qua F5-TTS (mặc định TTS_PROVIDER=edge, miễn phí, không cần model)."
  echo "    Muốn giọng nhân bản local: chạy lại 'bash scripts/setup.sh --with-f5-voice'"
fi

echo ""
echo "✅ Setup xong."
echo ""
echo "Bước tiếp theo:"
echo "  1. Mở .env, điền các key cần dùng:"
echo "     - TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID  (cổng duyệt kịch bản qua Telegram)"
echo "     - PEXELS_API_KEY                          (chỉ cần khi RENDER_PROVIDER=ai)"
echo "     - ELEVENLABS_API_KEY                      (chỉ cần khi TTS_PROVIDER=elevenlabs)"
echo "     - YOUTUBE_* + secrets/client_secret.json   (chỉ cần khi DRY_RUN=false, publish thật)"
echo "  2. .venv/bin/pytest          # xác nhận môi trường chạy đúng (hoặc: make test)"
echo "  3. make run TOPIC=\"...\"      # chạy thử pipeline (DRY_RUN=true mặc định, không upload)"
