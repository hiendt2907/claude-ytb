#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p dist
rm -f dist/video-render-portable.zip

zip -r dist/video-render-portable.zip . \
  -x ".git/*" \
  -x ".venv/*" \
  -x ".build-venv/*" \
  -x ".build-assets/*" \
  -x "__pycache__/*" \
  -x "*/__pycache__/*" \
  -x "*.pyc" \
  -x ".pytest_cache/*" \
  -x ".coverage*" \
  -x ".DS_Store" \
  -x "*/.DS_Store" \
  -x "build/*" \
  -x "*.spec" \
  -x "src/*.egg-info/*" \
  -x "tests/*" \
  -x "demo_data/*" \
  -x "output/*" \
  -x ".assembler_tmp/*" \
  -x "dist/*"

echo "Created dist/video-render-portable.zip"
