#!/bin/sh
# Dev server: nạp .env (gitignored, KHÔNG commit) rồi chạy uvicorn.
cd "$(dirname "$0")/.."
set -a
[ -f .env ] && . ./.env
set +a
exec "$(dirname "$0")/../.venv-check/bin/uvicorn" ytb_pipeline.webui.app:app --app-dir src --host 127.0.0.1 --port 8010
