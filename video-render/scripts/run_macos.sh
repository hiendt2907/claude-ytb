#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/video-render" ]; then
  echo "Local install not found. Run scripts/install_macos.sh first."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required. Run scripts/install_macos.sh or install it with: brew install ffmpeg"
  exit 1
fi

.venv/bin/video-render
