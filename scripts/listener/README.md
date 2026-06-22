# Listener Telegram ⇄ Claude

Điều khiển Claude trên Mac từ Telegram, từ bất kỳ đâu — miễn máy Mac còn mở.

## Cài

```bash
make setup            # nếu chưa có .venv
# .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (bắt buộc)
make listen           # chạy thử foreground, nhắn /help cho bot
make listen-install   # cài daemon launchd (chạy nền, tự khởi động + tự restart)
make listen-logs      # xem log
make listen-uninstall # gỡ
```

## Lệnh trên Telegram

| Lệnh | Tác dụng |
|------|----------|
| *(gõ tự do)* | giao việc cho Claude trong dự án (phiên mới, context sạch) |
| `/ask <prompt>` | như trên, tường minh |
| `/cont <prompt>` | tiếp nối phiên Claude gần nhất (`--continue`, giữ context) |
| `/auto <lệnh>` | chạy pipeline `/youtube-auto` (có cổng duyệt) |
| `/sh <cmd>` | chạy lệnh shell trong thư mục dự án |
| `/stop` | hủy job đang chạy nền |
| `/status` | tiến độ hàng đợi + ledger + job hiện tại |
| `/logs [n]` | n dòng log cuối |
| `/ping` `/help` | — |

## Lưu ý

- **Bypass quyền:** mặc định `LISTENER_CLAUDE_ARGS=--dangerously-skip-permissions`
  để daemon chạy tự trị không bị chặn. Daemon này thực thi lệnh từ Telegram với
  toàn quyền — **chỉ chạy trên máy cá nhân, giữ bot token/chat_id bí mật.**
- **Single-flight:** mỗi lúc 1 job; lệnh mới khi đang bận bị từ chối (dùng `/stop`).
- `/auto` chạy đồng bộ (nhường luồng Telegram cho cổng duyệt của skill); job thường
  chạy nền nên `/stop`, `/status` vẫn dùng được giữa chừng.
- Chỉ nhận lệnh từ đúng `TELEGRAM_CHAT_ID` trong `.env`.
