#!/usr/bin/env bash
# Cài đặt hoặc cập nhật claude-ytb với 1 lệnh duy nhất.
#
# DÙNG:
#   GH_TOKEN=ghp_xxx bash <(curl -fsSL "https://$GH_TOKEN@raw.githubusercontent.com/hiendt2907/claude-ytb/main/scripts/bootstrap.sh")
#
# Tự phát hiện:
#   - Chưa có repo → clone về $INSTALL_DIR rồi setup
#   - Đã có repo   → pull bản mới nhất + re-run setup (idempotent, không đè key)
#
# Tuỳ chọn:
#   INSTALL_DIR=/path/to/dir  — thư mục cài (mặc định ~/claude-ytb)
set -euo pipefail

TOKEN="${GH_TOKEN:-${1:-}}"
REPO_HOST="github.com/hiendt2907/claude-ytb.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/claude-ytb}"

# ── màu cho dễ đọc ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}" >&2; }
die()  { echo -e "${RED}❌ $*${NC}" >&2; exit 1; }

# ── bắt Ctrl+C ─────────────────────────────────────────────────────────────
trap 'echo ""; warn "Đã huỷ."; exit 1' INT

# ── xác định repo đang ở đâu ───────────────────────────────────────────────
detect_repo() {
  # Đang đứng trong 1 worktree của repo này?
  if git rev-parse --git-dir >/dev/null 2>&1; then
    local top
    top="$(git rev-parse --show-toplevel)"
    # Xác nhận đúng repo (không phải repo khác tình cờ)
    if grep -q "claude-ytb\|hiendt2907" "$top/.git/config" 2>/dev/null; then
      echo "$top"
      return
    fi
  fi
  # Repo đã tồn tại tại INSTALL_DIR?
  if [[ -d "$INSTALL_DIR/.git" ]] && grep -q "claude-ytb\|hiendt2907" "$INSTALL_DIR/.git/config" 2>/dev/null; then
    echo "$INSTALL_DIR"
    return
  fi
  echo ""
}

REPO_DIR="$(detect_repo)"

retry_git() {
  local max=3 delay=5 n=1
  until "$@"; do
    (( n >= max )) && return 1
    warn "Thử lại lần $((n+1))/$max sau ${delay}s (lỗi mạng?)..."
    sleep "$delay"; delay=$(( delay * 3 )); n=$(( n + 1 ))
  done
}

set_https_remote() {
  local dir="$1"
  [[ -z "$TOKEN" ]] && return  # giữ nguyên remote nếu không có token mới
  git -C "$dir" remote set-url origin "https://$TOKEN@$REPO_HOST"
}

# ── install hoặc update ────────────────────────────────────────────────────
if [[ -n "$REPO_DIR" ]]; then
  echo "==> Repo đã có tại $REPO_DIR — cập nhật"
  cd "$REPO_DIR"
  # Cập nhật token trong remote URL nếu có token mới
  set_https_remote "$REPO_DIR"
  retry_git git fetch origin main || die "git fetch thất bại sau 3 lần."
  OLD_SHA="$(git rev-parse HEAD)"
  NEW_SHA="$(git rev-parse origin/main)"
  if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
    ok "Đã ở bản mới nhất ($OLD_SHA) — không có gì để kéo."
  else
    git merge --ff-only origin/main || die "merge fail — có thay đổi cục bộ trên máy này, không tự giải quyết được."
    ok "Đã cập nhật: ${OLD_SHA:0:7} → ${NEW_SHA:0:7}"
  fi
else
  echo "==> Cài mới vào $INSTALL_DIR"
  [[ -z "$TOKEN" ]] && die "Cần GITHUB_TOKEN để clone repo private.\nDùng: GH_TOKEN=ghp_xxx bash <(curl ...)"
  [[ -e "$INSTALL_DIR" ]] && die "$INSTALL_DIR đã tồn tại nhưng không phải repo claude-ytb. Đổi INSTALL_DIR= hoặc xoá thủ công."
  retry_git git clone "https://$TOKEN@$REPO_HOST" "$INSTALL_DIR" || die "git clone thất bại."
  cd "$INSTALL_DIR"
  ok "Clone xong tại $INSTALL_DIR"
fi

# ── setup ──────────────────────────────────────────────────────────────────
echo ""
echo "==> Chạy setup.sh"
bash scripts/setup.sh

# ── tuỳ chọn cài daemon (chỉ khi interactive) ──────────────────────────────
if [[ -t 0 ]]; then
  echo ""
  echo "Tuỳ chọn (có thể cài sau bằng make):"

  read -r -p "   Cài Telegram listener daemon? (y/N) " ans_listen
  if [[ "$ans_listen" =~ ^[Yy]$ ]]; then
    make listen-install && ok "Listener đã cài." || warn "listen-install lỗi — thử lại sau."
  fi

  read -r -p "   Cài auto-update daemon (tự kéo code mới mỗi 30 phút)? (y/N) " ans_update
  if [[ "$ans_update" =~ ^[Yy]$ ]]; then
    make update-install && ok "Auto-update đã cài." || warn "update-install lỗi — thử lại sau."
  fi
fi

echo ""
ok "Xong! Bắt đầu: ytb batch start -n 5 --type-of-vid long"
