#!/usr/bin/env bash
# Cài listener Telegram thành LaunchAgent (tự chạy khi đăng nhập, tự restart).
set -euo pipefail

LABEL="com.claude-ytb.listener"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$PROJECT_DIR/scripts/listener/${LABEL}.plist.template"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST="$DEST_DIR/${LABEL}.plist"

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "❌ Chưa có .venv — chạy 'make setup' trước." >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__HOME__|$HOME|g" "$TEMPLATE" > "$DEST"

# Nạp lại (gỡ nếu đã có) — bootout có thể báo lỗi nếu chưa load, nuốt đi.
UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST"
launchctl enable "gui/$UID_NUM/$LABEL"
launchctl kickstart -k "gui/$UID_NUM/$LABEL"

echo "✅ Đã cài & khởi động $LABEL"
echo "   plist: $DEST"
echo "   log:   $PROJECT_DIR/assets/listener.{out,err}.log"
echo "   Kiểm tra: launchctl print gui/$UID_NUM/$LABEL | grep state"
