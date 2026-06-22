.PHONY: setup setup-f5 test run lint clean listen listen-install listen-uninstall listen-logs dashboard tunnel

# Cài đặt đầy đủ trên máy mới: ffmpeg, .venv, requirements, .env, thư mục runtime.
setup:
	bash scripts/setup.sh

# Như setup, cộng thêm F5-TTS giọng nhân bản local (tải model ~5.4GB).
setup-f5:
	bash scripts/setup.sh --with-f5-voice

test:
	.venv/bin/pytest

# Chạy pipeline với 1 chủ đề (mặc định DRY_RUN=true trong .env)
run:
	.venv/bin/python -m ytb_pipeline "$(TOPIC)"

clean:
	rm -rf assets/output/* assets/audio/*.mp3 .pytest_cache .coverage htmlcov

# Listener Telegram — chạy foreground (debug). launchd dùng listen-install.
listen:
	.venv/bin/python -m ytb_pipeline.listener

# Cài daemon launchd (tự khởi động khi đăng nhập, tự restart nếu crash)
listen-install:
	bash scripts/listener/install.sh

listen-uninstall:
	bash scripts/listener/uninstall.sh

listen-logs:
	tail -f assets/listener.out.log assets/listener.err.log

# Dashboard web — điều khiển + cấu hình toàn pipeline trên 1 trang.
# Host/port lấy từ settings (DASHBOARD_HOST/PORT). Cần DASHBOARD_PASSWORD đã đặt.
dashboard:
	.venv/bin/uvicorn ytb_pipeline.web.app:app \
		--host $${DASHBOARD_HOST:-127.0.0.1} --port $${DASHBOARD_PORT:-8765} \
		--app-dir src

# Mở Cloudflare Tunnel tới dashboard (config riêng, không đụng tunnel khác).
tunnel:
	cloudflared tunnel --config $(HOME)/.cloudflared/ytb-dashboard.yml run ytb-dashboard
