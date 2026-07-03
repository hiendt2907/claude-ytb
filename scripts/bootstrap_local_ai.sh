#!/usr/bin/env bash
# Bootstrap local AI runtimes used by the local-first pipeline.
#
# Defaults:
#   - pull Ollama model configured by OLLAMA_MODEL
#   - install/update ComfyUI in LOCAL_AI_HOME
# Optional heavy downloads:
#   INSTALL_FLUX=1  download FLUX_CHECKPOINT_NAME into ComfyUI/models/checkpoints
#   INSTALL_WAN=1   clone Wan2.2 and download WAN_MODEL_ID into LOCAL_AI_HOME
#
# Examples:
#   bash scripts/bootstrap_local_ai.sh
#   INSTALL_FLUX=1 HF_TOKEN=hf_xxx bash scripts/bootstrap_local_ai.sh
#   INSTALL_WAN=1 bash scripts/bootstrap_local_ai.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_AI_HOME="${LOCAL_AI_HOME:-$HOME/.local/share/ytb_pipeline}"
COMFYUI_DIR="${COMFYUI_DIR:-$LOCAL_AI_HOME/ComfyUI}"
WAN_DIR="${WAN_DIR:-$LOCAL_AI_HOME/Wan2.2}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"
FLUX_REPO="${FLUX_REPO:-Comfy-Org/flux1-dev}"
FLUX_CHECKPOINT_NAME="${FLUX_CHECKPOINT_NAME:-flux1-dev-fp8.safetensors}"
WAN_MODEL_ID="${WAN_MODEL_ID:-Wan-AI/Wan2.2-TI2V-5B}"
WAN_MODEL_DIR="${WAN_MODEL_DIR:-$LOCAL_AI_HOME/$(basename "$WAN_MODEL_ID")}"
LOCAL_BIN_DIR="${LOCAL_BIN_DIR:-$LOCAL_AI_HOME/bin}"

log() { printf '==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

hf_download() {
  local hf_bin="$1"
  shift
  if [[ -x "$hf_bin" ]]; then
    "$hf_bin" download "$@"
    return
  fi
  die "missing Hugging Face CLI: $hf_bin"
}

install_ollama_model() {
  require_cmd ollama
  log "Pull Ollama model: $OLLAMA_MODEL"
  ollama pull "$OLLAMA_MODEL"
}

install_comfyui() {
  require_cmd git
  mkdir -p "$LOCAL_AI_HOME"
  if [[ -d "$COMFYUI_DIR/.git" ]]; then
    log "Update ComfyUI: $COMFYUI_DIR"
    git -C "$COMFYUI_DIR" pull --ff-only
  else
    log "Clone ComfyUI: $COMFYUI_DIR"
    git clone --depth 1 https://github.com/Comfy-Org/ComfyUI.git "$COMFYUI_DIR"
  fi

  if [[ ! -x "$COMFYUI_DIR/.venv/bin/python" ]]; then
    log "Create ComfyUI venv"
    "$PYTHON_BIN" -m venv "$COMFYUI_DIR/.venv"
  fi
  log "Install ComfyUI requirements"
  "$COMFYUI_DIR/.venv/bin/python" -m pip install -U pip
  "$COMFYUI_DIR/.venv/bin/python" -m pip install -r "$COMFYUI_DIR/requirements.txt"
}

install_flux_checkpoint() {
  [[ "${INSTALL_FLUX:-0}" == "1" ]] || {
    warn "Skip Flux checkpoint download. Set INSTALL_FLUX=1 to download $FLUX_CHECKPOINT_NAME."
    return
  }
  mkdir -p "$COMFYUI_DIR/models/checkpoints"
  log "Install huggingface_hub CLI for Flux download"
  "$COMFYUI_DIR/.venv/bin/python" -m pip install -U "huggingface_hub[cli]"
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
  fi
  log "Download Flux checkpoint: $FLUX_REPO/$FLUX_CHECKPOINT_NAME"
  hf_download "$COMFYUI_DIR/.venv/bin/hf" \
    "$FLUX_REPO" "$FLUX_CHECKPOINT_NAME" \
    --local-dir "$COMFYUI_DIR/models/checkpoints"
}

install_wan() {
  [[ "${INSTALL_WAN:-0}" == "1" ]] || {
    warn "Skip Wan download. Set INSTALL_WAN=1 only if this machine has enough disk/VRAM."
    return
  }
  require_cmd git
  mkdir -p "$LOCAL_AI_HOME"
  if [[ -d "$WAN_DIR/.git" ]]; then
    log "Update Wan2.2: $WAN_DIR"
    git -C "$WAN_DIR" pull --ff-only
  else
    log "Clone Wan2.2: $WAN_DIR"
    git clone --depth 1 https://github.com/Wan-Video/Wan2.2.git "$WAN_DIR"
  fi
  if [[ ! -x "$WAN_DIR/.venv/bin/python" ]]; then
    log "Create Wan2.2 venv"
    "$PYTHON_BIN" -m venv "$WAN_DIR/.venv"
  fi
  log "Install Wan2.2 package and Hugging Face CLI"
  "$WAN_DIR/.venv/bin/python" -m pip install -U pip
  "$WAN_DIR/.venv/bin/python" -m pip install "$WAN_DIR" "huggingface_hub[cli]"
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
  fi
  log "Download Wan model: $WAN_MODEL_ID -> $WAN_MODEL_DIR"
  hf_download "$WAN_DIR/.venv/bin/hf" "$WAN_MODEL_ID" --local-dir "$WAN_MODEL_DIR"
  mkdir -p "$LOCAL_BIN_DIR"
  cat > "$LOCAL_BIN_DIR/wan2.2-ytb" <<EOF
#!/usr/bin/env bash
set -euo pipefail
MODEL=""
PROMPT=""
WIDTH="704"
HEIGHT="1280"
OUTPUT=""
IMAGE=""
SEED=""
while [[ \$# -gt 0 ]]; do
  case "\$1" in
    --model) MODEL="\$2"; shift 2 ;;
    --prompt) PROMPT="\$2"; shift 2 ;;
    --duration) shift 2 ;;
    --width) WIDTH="\$2"; shift 2 ;;
    --height) HEIGHT="\$2"; shift 2 ;;
    --output) OUTPUT="\$2"; shift 2 ;;
    --image) IMAGE="\$2"; shift 2 ;;
    --seed) SEED="\$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "\$MODEL" && -n "\$PROMPT" && -n "\$OUTPUT" ]] || {
  echo "usage: wan2.2-ytb --model DIR --prompt TEXT --output out.mp4 [--image img] [--seed N]" >&2
  exit 2
}
SIZE="704*1280"
if (( WIDTH > HEIGHT )); then
  SIZE="1280*704"
fi
CMD=("$WAN_DIR/.venv/bin/python" "$WAN_DIR/generate.py" --task ti2v-5B --size "\$SIZE" --ckpt_dir "\$MODEL" --prompt "\$PROMPT" --save_file "\$OUTPUT" --offload_model True --convert_model_dtype --t5_cpu)
if [[ -n "\$IMAGE" ]]; then
  CMD+=(--image "\$IMAGE")
fi
if [[ -n "\$SEED" ]]; then
  CMD+=(--base_seed "\$SEED")
fi
exec "\${CMD[@]}"
EOF
  chmod +x "$LOCAL_BIN_DIR/wan2.2-ytb"
  cat <<EOF

Add this to .env when you want true local video generation:
WAN_MODEL_PATH=$WAN_MODEL_DIR
WAN_CLI=$LOCAL_BIN_DIR/wan2.2-ytb
BROLL_STRATEGY=local_video
EOF
}

main() {
  cd "$ROOT"
  install_ollama_model
  install_comfyui
  install_flux_checkpoint
  install_wan

  cat <<EOF

Local AI bootstrap done.

Start ComfyUI:
  $COMFYUI_DIR/.venv/bin/python $COMFYUI_DIR/main.py --listen 127.0.0.1 --port 8188

Check readiness:
  PYTHONPATH=src .venv/bin/python -m ytb_pipeline.orchestrator.batch_cli doctor --local
EOF
}

main "$@"
