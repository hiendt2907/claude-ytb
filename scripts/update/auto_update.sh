#!/usr/bin/env bash
# Tự đồng bộ code mới nhất từ git remote (chạy lặp lại qua launchd, xem install.sh).
# Có retry cho lỗi mạng, rollback tự động nếu setup/smoke-test fail sau khi pull
# (ví dụ máy này khác OS/kiến trúc/version lib so với lúc code được viết), và
# "chặn" 1 commit lỗi để không lặp lại rollback ở mỗi lượt poll.
set -uo pipefail  # KHÔNG -e: cần tự bắt lỗi từng bước để rollback, không thoát giữa đường

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/assets/update_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

PID_LOCK="$PROJECT_DIR/assets/auto_update.pid"
BATCH_PID="$PROJECT_DIR/assets/batch_cli.pid"
FAILED_SHA_FILE="$PROJECT_DIR/assets/auto_update.failed_sha"
LISTENER_LABEL="com.claude-ytb.listener"

notify() {
  # Gửi Telegram qua module có sẵn (notify/telegram.py) — không raise nếu lỗi,
  # update daemon không được vì gửi Telegram fail mà tự coi là update fail.
  PYTHONPATH=src "$PROJECT_DIR/.venv/bin/python" - "$1" <<'PYEOF' 2>>"$LOG_FILE" || true
import sys
from ytb_pipeline.notify.telegram import send_message
send_message(sys.argv[1])
PYEOF
}

retry() {
  # retry <max_lần> <lệnh...> — backoff 5s/15s/45s.
  local max="$1"; shift
  local delay=5 n=1
  until "$@"; do
    if (( n >= max )); then
      return 1
    fi
    echo "   thử lại lần $((n + 1))/$max sau ${delay}s..."
    sleep "$delay"
    delay=$(( delay * 3 ))
    n=$(( n + 1 ))
  done
  return 0
}

smoke_test() {
  # Chỉ kiểm tra CODE còn import/khởi động được sau update (đúng phạm vi rollback:
  # lỗi do OS/lib/version khác nhau). KHÔNG dùng `ytb batch doctor` ở đây — doctor
  # còn check cả trạng thái môi trường (OAuth token hết hạn, thiếu script JSON...)
  # vốn không liên quan tới việc update có làm hỏng code hay không, dùng nó sẽ
  # gây rollback oan khi token hết hạn đúng lúc launchd poll.
  PYTHONPATH=src "$PROJECT_DIR/.venv/bin/python" -c "
import ytb_pipeline.pipeline
import ytb_pipeline.orchestrator.batch_cli
import ytb_pipeline.voiceover.tts
import ytb_pipeline.render.compose_ai
import ytb_pipeline.publish.uploader
" \
    && "$PROJECT_DIR/bin/ytb" batch --help >/dev/null 2>&1
}

restart_listener() {
  local uid_num
  uid_num="$(id -u)"
  launchctl kickstart -k "gui/$uid_num/$LISTENER_LABEL" 2>/dev/null || true
}

rollback() {
  local new_sha="$1" reason="$2"
  echo "❌ Update $new_sha lỗi: $reason — rollback về $OLD_SHA"
  echo "$new_sha" > "$FAILED_SHA_FILE"
  if git reset --hard "$OLD_SHA" >/dev/null \
      && retry 2 bash scripts/setup.sh < /dev/null \
      && smoke_test; then
    restart_listener
    notify "⚠️ claude-ytb: update $new_sha lỗi ($reason). Đã rollback về $OLD_SHA — hệ thống chạy bình thường trở lại. Sẽ bỏ qua $new_sha cho đến khi có commit mới hơn."
  else
    notify "🚨 claude-ytb: update $new_sha lỗi ($reason) VÀ rollback về $OLD_SHA cũng lỗi. CẦN can thiệp tay ngay trên máy. Log: $LOG_FILE"
  fi
  exit 1
}

# --- chặn chạy chồng lấp (1 lượt update đang chạy thì lượt poll sau bỏ qua) ---
if [[ -f "$PID_LOCK" ]]; then
  old_pid="$(cat "$PID_LOCK" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Đã có auto_update đang chạy (PID $old_pid) — bỏ qua lượt này"
    exit 0
  fi
fi
echo $$ > "$PID_LOCK"
trap 'rm -f "$PID_LOCK"' EXIT

# --- bỏ qua nếu batch render/upload đang chạy (đừng đổi code dưới chân nó) ---
if [[ -f "$BATCH_PID" ]]; then
  batch_pid="$(cat "$BATCH_PID" 2>/dev/null || true)"
  if [[ -n "$batch_pid" ]] && kill -0 "$batch_pid" 2>/dev/null; then
    echo "Batch render/upload đang chạy (PID $batch_pid) — bỏ qua lượt update này"
    exit 0
  fi
fi

echo "==> git fetch origin main"
if ! retry 3 git fetch origin main; then
  echo "fetch fail sau 3 lần (mạng?) — bỏ qua lượt poll này, thử lại lần sau"
  exit 0
fi

OLD_SHA="$(git rev-parse HEAD)"
NEW_SHA="$(git rev-parse origin/main)"

if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
  echo "Không có bản mới (đang ở $OLD_SHA)"
  exit 0
fi

if [[ -f "$FAILED_SHA_FILE" ]] && [[ "$(cat "$FAILED_SHA_FILE")" == "$NEW_SHA" ]]; then
  echo "Commit $NEW_SHA đã từng update-fail trước đó — bỏ qua, chờ commit mới hơn"
  exit 0
fi

echo "==> Có bản mới: $OLD_SHA -> $NEW_SHA"

if ! git merge --ff-only origin/main; then
  echo "❌ Không fast-forward được (working tree có thay đổi cục bộ trên máy này?)"
  notify "⚠️ claude-ytb: có bản mới ($NEW_SHA) nhưng auto-update không merge được (không fast-forward). Có thay đổi cục bộ trên máy — cần kiểm tra tay, KHÔNG tự xử để tránh mất việc đang dở."
  exit 1
fi

echo "==> Chạy setup.sh (non-interactive)"
if ! retry 2 bash scripts/setup.sh < /dev/null; then
  rollback "$NEW_SHA" "setup.sh fail (thiếu lib hệ thống / version OS-kiến trúc không tương thích)"
fi

echo "==> Smoke test"
if ! smoke_test; then
  rollback "$NEW_SHA" "smoke test fail sau khi update (import lỗi hoặc 'ytb batch doctor' fail)"
fi

rm -f "$FAILED_SHA_FILE"
restart_listener

commit_msg="$(git log -1 --pretty=%s "$NEW_SHA")"
notify "✅ claude-ytb: đã cập nhật lên ${NEW_SHA:0:7} — $commit_msg"
echo "✅ Update thành công: $NEW_SHA"
