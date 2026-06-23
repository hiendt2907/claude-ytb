#!/usr/bin/env bash
# Cài auto-update thành LaunchAgent (poll git remote mỗi 30 phút, tự pull +
# setup + smoke-test + rollback nếu fail, báo Telegram).
set -euo pipefail

LABEL="com.claude-ytb.autoupdate"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$PROJECT_DIR/scripts/update/${LABEL}.plist.template"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST="$DEST_DIR/${LABEL}.plist"

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "❌ Chưa có .venv — chạy 'make setup' trước." >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" -e "s|__HOME__|$HOME|g" "$TEMPLATE" > "$DEST"

UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST"
launchctl enable "gui/$UID_NUM/$LABEL"
launchctl kickstart -k "gui/$UID_NUM/$LABEL"

echo "✅ Đã cài & bật $LABEL (poll mỗi 30 phút, vừa chạy thử 1 lượt ngay)"
echo "   plist: $DEST"
echo "   log:   $PROJECT_DIR/assets/auto_update.{out,err}.log"
echo "   log chi tiết mỗi lượt: $PROJECT_DIR/assets/update_logs/"
echo "   Chạy thử ngay (không chờ 30 phút): make update-run"
