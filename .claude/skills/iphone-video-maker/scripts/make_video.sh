#!/usr/bin/env bash
# Nối các clip video (AirDrop/export từ iPhone) thành 1 video crossfade.
# Hoàn toàn độc lập với pipeline YouTube của project — không đọc/viết gì trong
# src/, assets/, data/. Mọi file trung gian + output nằm trong ~/Movies/iphone-video-maker.
set -euo pipefail

WORKDIR="$HOME/Movies/iphone-video-maker"
IMPORT_DIR="$WORKDIR/import"
STAGE_DIR="$WORKDIR/stage"
OUTPUT_DIR="$WORKDIR/output"
SINCE="${1:-24 hours ago}"   # vd: ./make_video.sh "2 hours ago"

mkdir -p "$IMPORT_DIR" "$STAGE_DIR" "$OUTPUT_DIR"
rm -rf "${STAGE_DIR:?}"/*

log() { echo "[iphone-video-maker] $*"; }

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Thiếu '$1'. Cài bằng: brew install $2" >&2
    exit 1
  }
}

require_tool ffmpeg ffmpeg
require_tool ffprobe ffmpeg

log "Đọc clip từ: $IMPORT_DIR"
log "(AirDrop hoặc Photos.app > File > Export Unmodified Original vào thư mục này trước khi chạy)"

RAW_CLIPS=()
while IFS= read -r -d '' f; do
  RAW_CLIPS+=("$f")
done < <(find "$IMPORT_DIR" -type f \( -iname "*.mov" -o -iname "*.mp4" \) -print0)

if [[ "${#RAW_CLIPS[@]}" -eq 0 ]]; then
  echo "Không tìm thấy file .MOV/.mp4 nào trong $IMPORT_DIR. AirDrop/export clip vào đó trước." >&2
  exit 1
fi

# Lọc theo thời gian sửa đổi (SINCE) rồi sort theo thời gian quay tăng dần.
CUTOFF_EPOCH="$(date -j -v-24H "+%s" 2>/dev/null || echo 0)"
case "$SINCE" in
  *hour*) N="$(echo "$SINCE" | grep -oE '[0-9]+' | head -1)"; CUTOFF_EPOCH="$(date -j -v-"${N}"H "+%s")" ;;
  *day*)  N="$(echo "$SINCE" | grep -oE '[0-9]+' | head -1)"; CUTOFF_EPOCH="$(date -j -v-"${N}"d "+%s")" ;;
  all) CUTOFF_EPOCH=0 ;;
esac

SELECTED=()
for f in "${RAW_CLIPS[@]}"; do
  MTIME="$(stat -f %m "$f")"
  if [[ "$MTIME" -ge "$CUTOFF_EPOCH" ]]; then
    SELECTED+=("$f|$MTIME")
  fi
done

if [[ "${#SELECTED[@]}" -eq 0 ]]; then
  echo "Không có clip nào trong khoảng thời gian '$SINCE'. Thử: ./make_video.sh all" >&2
  exit 1
fi

IFS=$'\n' SORTED=($(printf '%s\n' "${SELECTED[@]}" | sort -t'|' -k2 -n))
unset IFS

log "Chọn được ${#SORTED[@]} clip, copy + chuẩn hoá vào stage..."

INDEX=0
NORMALIZED=()
TARGET_DIMS=""
for entry in "${SORTED[@]}"; do
  SRC="${entry%%|*}"
  INDEX=$((INDEX + 1))
  NUM=$(printf "%02d" "$INDEX")
  DEST="$STAGE_DIR/${NUM}.mov"
  cp "$SRC" "$DEST"

  if [[ -z "$TARGET_DIMS" ]]; then
    TARGET_DIMS="$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$DEST" | sed -E 's/,+$//')"
  fi
  W="${TARGET_DIMS%%,*}"
  H="${TARGET_DIMS##*,}"

  NORM="$STAGE_DIR/${NUM}_norm.mp4"
  ffmpeg -y -loglevel error -i "$DEST" \
    -vf "scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30" \
    -c:v libx264 -preset fast -crf 18 -c:a aac -ar 48000 -ac 2 \
    "$NORM"
  NORMALIZED+=("$NORM")
done

log "Nối ${#NORMALIZED[@]} clip với crossfade..."

TIMESTAMP="$(date "+%Y%m%d_%H%M%S")"
FINAL_OUT="$OUTPUT_DIR/love_video_${TIMESTAMP}.mp4"
XFADE_DUR=0.6

if [[ "${#NORMALIZED[@]}" -eq 1 ]]; then
  cp "${NORMALIZED[0]}" "$FINAL_OUT"
else
  CURRENT="${NORMALIZED[0]}"
  CURRENT_DUR="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$CURRENT")"
  for i in "${!NORMALIZED[@]}"; do
    [[ "$i" -eq 0 ]] && continue
    NEXT="${NORMALIZED[$i]}"
    OFFSET="$(echo "$CURRENT_DUR - $XFADE_DUR" | bc)"
    STEP_OUT="$STAGE_DIR/step_${i}.mp4"
    ffmpeg -y -loglevel error -i "$CURRENT" -i "$NEXT" -filter_complex \
      "[0:v][1:v]xfade=transition=fade:duration=${XFADE_DUR}:offset=${OFFSET}[v];[0:a][1:a]acrossfade=d=${XFADE_DUR}[a]" \
      -map "[v]" -map "[a]" -c:v libx264 -preset fast -crf 18 -c:a aac "$STEP_OUT"
    CURRENT="$STEP_OUT"
    CURRENT_DUR="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$CURRENT")"
  done
  cp "$CURRENT" "$FINAL_OUT"
fi

log "Xong! Video: $FINAL_OUT"
open "$OUTPUT_DIR"
