#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ] && [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
        PYTHON_BIN="$candidate"
        break
      fi
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.11+ is required on the builder machine."
  exit 1
fi

"$PYTHON_BIN" -m venv .build-venv
.build-venv/bin/python -m pip install --upgrade pip
.build-venv/bin/python -m pip install ".[build]"
.build-venv/bin/python scripts/prepare_ffmpeg_bundle.py

rm -rf build "dist/Video Render.app" "dist/Video Render-macOS.zip"
rm -f "dist/Video Render-macOS.dmg"

.build-venv/bin/pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "Video Render" \
  --add-data "src/ytb_pipeline/webui/templates:ytb_pipeline/webui/templates" \
  --add-binary ".build-assets/ffmpeg/ffmpeg:ffmpeg" \
  --add-binary ".build-assets/ffmpeg/ffprobe:ffmpeg" \
  src/ytb_pipeline/desktop.py

find "dist/Video Render.app" -exec xattr -d com.apple.provenance {} \; 2>/dev/null || true
find "dist/Video Render.app" -exec xattr -d com.apple.FinderInfo {} \; 2>/dev/null || true
find "dist/Video Render.app" -exec xattr -d 'com.apple.fileprovider.fpfs#P' {} \; 2>/dev/null || true
xattr -cr "dist/Video Render.app" || true
for key in com.apple.FinderInfo 'com.apple.fileprovider.fpfs#P' com.apple.provenance com.apple.macl; do
  xattr -drs "$key" "dist/Video Render.app" 2>/dev/null || true
  xattr -dr "$key" "dist/Video Render.app" 2>/dev/null || true
done
for path in \
  "dist/Video Render.app" \
  "dist/Video Render.app/Contents/Resources/Python.framework" \
  "dist/Video Render.app/Contents/Frameworks/Python.framework"; do
  for key in com.apple.FinderInfo 'com.apple.fileprovider.fpfs#P' com.apple.provenance com.apple.macl; do
    xattr -ds "$key" "$path" 2>/dev/null || true
    xattr -d "$key" "$path" 2>/dev/null || true
  done
done
codesign --force --deep --sign - "dist/Video Render.app" || true

ditto -c -k --sequesterRsrc --keepParent "dist/Video Render.app" "dist/Video Render-macOS.zip"
hdiutil create \
  -volname "Video Render" \
  -srcfolder "dist/Video Render.app" \
  -ov \
  -format UDZO \
  "dist/Video Render-macOS.dmg"

echo "Created dist/Video Render-macOS.zip"
echo "Created dist/Video Render-macOS.dmg"
