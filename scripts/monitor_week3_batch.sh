#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BATCH_KEY="${BATCH_KEY:-shorts_funnel_batch_2026-07-20}"
START_PID="${START_PID:?START_PID is required; pass the live batch start PID}"
INTERVAL="${MONITOR_INTERVAL:-30}"
EXPECTED_LONGS="${EXPECTED_LONGS:-2}"
EXPECTED_SHORTS="${EXPECTED_SHORTS:-28}"
LOG="$ROOT/assets/batch_logs/week3_monitor_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$ROOT/assets/batch_logs"
exec > >(tee -a "$LOG") 2>&1
echo "monitor started batch=$BATCH_KEY pid=$START_PID"

while kill -0 "$START_PID" 2>/dev/null; do
  echo "$(date '+%F %T') start still running"
  sleep "$INTERVAL"
done

echo "$(date '+%F %T') start process exited"
python3 - "$ROOT/assets/auto_state.json" "$BATCH_KEY" "$EXPECTED_LONGS" "$EXPECTED_SHORTS" <<'PY'
import json, sys
path, key, expected_longs, expected_shorts = sys.argv[1:]
try:
    state = json.load(open(path, encoding="utf-8"))
except Exception as exc:
    print(f"state unreadable: {exc}")
    raise SystemExit(2)
batch = state.get(key)
if not isinstance(batch, dict):
    print(f"batch key missing: {key}")
    raise SystemExit(3)
longs = batch.get("long_videos", [])
shorts = batch.get("short_videos", [])
print(f"batch state found: longs={len(longs)} shorts={len(shorts)}")
if len(longs) < int(sys.argv[3]) or len(shorts) < int(sys.argv[4]):
    print("batch incomplete; refusing to run")
    raise SystemExit(4)
PY

if [[ $? -ne 0 ]]; then
  echo "refusing batch run"
  exit 1
fi

echo "starting scheduled batch run"
cd "$ROOT"
exec ./bin/ytb batch run --schedule --loop --workers 1
