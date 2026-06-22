#!/usr/bin/env bash
# Gỡ LaunchAgent listener.
set -euo pipefail

LABEL="com.claude-ytb.listener"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"

launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
rm -f "$DEST"
echo "✅ Đã gỡ $LABEL"
