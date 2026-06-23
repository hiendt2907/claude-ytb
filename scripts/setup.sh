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

echo "==> Chẩn đoán hệ điều hành"
OS_NAME="$(uname -s)"   # Darwin | Linux
ARCH="$(uname -m)"      # arm64 | x86_64 | aarch64
case "$OS_NAME" in
  Darwin)
    case "$ARCH" in
      arm64)  PLATFORM="macos-arm64" ;;
      x86_64) PLATFORM="macos-intel" ;;
      *)      PLATFORM="macos-unknown" ;;
    esac
    ;;
  Linux)
    case "$ARCH" in
      x86_64)          PLATFORM="linux-x86_64" ;;
      aarch64|arm64)   PLATFORM="linux-arm64" ;;
      *)               PLATFORM="linux-unknown" ;;
    esac
    ;;
  *)
    PLATFORM="unknown"
    ;;
esac
echo "   OS=$OS_NAME  ARCH=$ARCH  → PLATFORM=$PLATFORM"
case "$PLATFORM" in
  macos-arm64)
    echo "   Apple Silicon — F5-TTS chạy được GPU (MPS), tốc độ tốt."
    ;;
  macos-intel)
    echo "   ⚠️  Mac Intel — F5-TTS (nếu dùng --with-f5-voice) sẽ chạy CPU, chậm hơn nhiều" >&2
    echo "      so với Apple Silicon. Khuyên giữ TTS_PROVIDER=edge (mặc định, miễn phí)." >&2
    ;;
  linux-*)
    echo "   ⚠️  Linux chưa hỗ trợ launchd (chỉ macOS) — bước cài listener auto-start" >&2
    echo "      (make listen-install) sẽ KHÔNG chạy được, cần thay bằng systemd tay." >&2
    ;;
  *)
    echo "   ⚠️  Không nhận diện được OS/kiến trúc — các bước sau có thể cần chỉnh tay." >&2
    ;;
esac

echo "==> ffmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "   đã có: $(ffmpeg -version | head -1)"
else
  case "$PLATFORM" in
    macos-*)
      if ! command -v brew >/dev/null 2>&1; then
        echo "❌ Chưa có Homebrew. Cài tại https://brew.sh rồi chạy lại script này." >&2
        exit 1
      fi
      brew install ffmpeg
      ;;
    linux-*)
      if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y ffmpeg
      elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y ffmpeg
      elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Sy --noconfirm ffmpeg
      else
        echo "❌ Không nhận diện được package manager Linux (apt/dnf/pacman)." >&2
        echo "   Cài ffmpeg tay rồi chạy lại script này." >&2
        exit 1
      fi
      ;;
    *)
      echo "❌ Không tự cài được ffmpeg trên PLATFORM=$PLATFORM. Cài tay rồi chạy lại." >&2
      exit 1
      ;;
  esac
fi

echo "==> venv chính (.venv) + requirements.txt"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
# requirements.txt thuần Python (pydantic, edge-tts, moviepy, Pillow, google-api-*) —
# pip tự chọn wheel đúng theo PLATFORM, không cần file requirements riêng theo OS.
.venv/bin/pip install -r requirements.txt -q

echo "==> Thư mục runtime (gitignored, cần tồn tại trước khi chạy)"
mkdir -p secrets assets/output assets/audio data

echo "==> .env"
if [[ -f .env ]]; then
  echo "   .env đã tồn tại — giữ nguyên, không đè."
else
  cp .env.example .env
  echo "   đã tạo .env từ .env.example."
fi

# Ghi 1 biến vào .env (giữ comment cuối dòng nếu có), thêm dòng mới nếu key
# chưa tồn tại. Bỏ qua nếu value rỗng (giữ giá trị cũ trong .env).
set_env_var() {
  local key="$1" value="$2"
  [[ -z "$value" ]] && return
  KEY="$key" VALUE="$value" python3 - <<'PYEOF'
import os
path = ".env"
key = os.environ["KEY"]
value = os.environ["VALUE"]
with open(path) as f:
    lines = f.readlines()
prefix = key + "="
found = False
for i, line in enumerate(lines):
    if line.startswith(prefix):
        rest = line[len(prefix):]
        if "#" in rest:
            _, comment = rest.split("#", 1)
            lines[i] = f"{key}={value}  #{comment}"
        else:
            lines[i] = f"{key}={value}\n"
        found = True
        break
if not found:
    lines.append(f"{key}={value}\n")
with open(path, "w") as f:
    f.writelines(lines)
PYEOF
}

# Hỏi 1 secret, hiện hướng dẫn lấy key trước, Enter để bỏ qua (điền sau trong .env).
# Input bị ẩn (giống nhập mật khẩu) vì đây là token/API key.
prompt_secret() {
  local label="$1" guide="$2" __resultvar="$3"
  echo ""
  echo "   $label"
  echo "   → $guide"
  read -r -s -p "   Dán giá trị (Enter để bỏ qua): " value
  echo ""
  printf -v "$__resultvar" '%s' "$value"
}

if [[ ! -t 0 ]]; then
  echo "   (không phải terminal tương tác — bỏ qua hỏi secret, điền .env thủ công sau)"
else
  echo ""
  echo "==> Nhập secrets/API key (Enter để bỏ qua, điền lại sau trong .env)"

  prompt_secret "Telegram Bot Token — cổng duyệt kịch bản qua Telegram" \
    "Mở Telegram, chat với @BotFather, gõ /newbot, đặt tên bot. BotFather trả về token dạng 123456:ABC-xyz..." \
    TELEGRAM_BOT_TOKEN_VAL
  set_env_var TELEGRAM_BOT_TOKEN "$TELEGRAM_BOT_TOKEN_VAL"

  prompt_secret "Telegram Chat ID — id của mày để bot biết gửi cho ai" \
    "Nhắn 1 tin bất kỳ cho bot vừa tạo, rồi chat với @userinfobot để lấy ID; hoặc mở https://api.telegram.org/bot<TOKEN>/getUpdates và tìm \"chat\":{\"id\":...}" \
    TELEGRAM_CHAT_ID_VAL
  set_env_var TELEGRAM_CHAT_ID "$TELEGRAM_CHAT_ID_VAL"

  prompt_secret "Pexels API Key — chỉ cần khi RENDER_PROVIDER=ai (B-roll stock)" \
    "Đăng nhập https://www.pexels.com rồi vào https://www.pexels.com/api/ — key hiện ngay, free." \
    PEXELS_API_KEY_VAL
  set_env_var PEXELS_API_KEY "$PEXELS_API_KEY_VAL"

  prompt_secret "ElevenLabs API Key — chỉ cần khi TTS_PROVIDER=elevenlabs" \
    "Đăng nhập https://elevenlabs.io → avatar góc trên phải → Profile + API Key." \
    ELEVENLABS_API_KEY_VAL
  set_env_var ELEVENLABS_API_KEY "$ELEVENLABS_API_KEY_VAL"

  prompt_secret "YouTube Data API Key — chỉ cần để research trending (videos.list), KHÔNG bắt buộc cho upload" \
    "Google Cloud Console → APIs & Services → Library → bật 'YouTube Data API v3' → Credentials → Create credentials → API key." \
    YOUTUBE_API_KEY_VAL
  set_env_var YOUTUBE_API_KEY "$YOUTUBE_API_KEY_VAL"

  echo ""
  echo "   secrets/client_secret.json — OAuth client để UPLOAD THẬT (DRY_RUN=false)."
  echo "   → File JSON, không nhập qua đây được. Lấy tại: Google Cloud Console →"
  echo "     APIs & Services → Credentials → Create Credentials → OAuth client ID →"
  echo "     Application type 'Desktop app' → Download JSON → lưu đúng đường dẫn"
  echo "     secrets/client_secret.json (tạo OAuth consent screen trước nếu chưa có)."
  if [[ -f secrets/client_secret.json ]]; then
    echo "   ✅ đã thấy file tại secrets/client_secret.json."
  else
    echo "   ⚠️  chưa có file — DRY_RUN vẫn chạy được (render local), chỉ cần file này khi"
    echo "      muốn upload thật. Có thể copy vào sau, không chặn setup."
  fi
fi

setup_f5() {
  echo "==> [TUỲ CHỌN] F5-TTS — giọng nhân bản local (~5.4GB model)"
  case "$PLATFORM" in
    macos-arm64) ;;  # MPS — tốc độ tốt, không cần cảnh báo
    macos-intel|linux-*)
      echo "⚠️  PLATFORM=$PLATFORM — F5-TTS sẽ chạy CPU (không GPU/MPS), chậm hơn nhiều" >&2
      echo "   so với Apple Silicon (có thể vài phút/đoạn thay vài giây)." >&2
      read -r -p "   Vẫn tiếp tục cài? (y/N) " confirm_f5
      if [[ ! "$confirm_f5" =~ ^[Yy]$ ]]; then
        echo "   Bỏ qua F5-TTS — giữ TTS_PROVIDER=edge."
        return 0
      fi
      ;;
  esac
  if ! command -v python3.12 >/dev/null 2>&1; then
    echo "❌ Cần python3.12 cho .venv-tts (F5-TTS chưa hỗ trợ Python mới hơn)." >&2
    case "$PLATFORM" in
      macos-*) echo "   Cài: brew install python@3.12" >&2 ;;
      linux-*) echo "   Cài: sudo apt-get install -y python3.12 python3.12-venv  (hoặc dnf/pacman tương đương)" >&2 ;;
    esac
    return 1
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
}

if $WITH_F5; then
  setup_f5
else
  echo "==> Bỏ qua F5-TTS (mặc định TTS_PROVIDER=edge, miễn phí, không cần model)."
  echo "    Muốn giọng nhân bản local: chạy lại 'bash scripts/setup.sh --with-f5-voice'"
fi

echo ""
echo "✅ Setup xong."
echo ""
echo "Bước tiếp theo:"
echo "  1. Key nào vừa bỏ qua ở trên (Enter trống) thì mở .env điền tay sau, hoặc"
echo "     chạy lại 'bash scripts/setup.sh' để được hỏi lại (không đè key đã điền)."
echo "  2. .venv/bin/pytest          # xác nhận môi trường chạy đúng (hoặc: make test)"
echo "  3. make run TOPIC=\"...\"      # chạy thử pipeline (DRY_RUN=true mặc định, không upload)"
