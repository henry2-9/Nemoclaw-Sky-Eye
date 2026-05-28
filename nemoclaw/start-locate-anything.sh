#!/usr/bin/env bash
# 啟動 LocateAnything-3B HTTP server(替代 Falcon Perception 作為 cheap-gate 偵測後端)。
# Port: 18794;contract 同 Falcon /infer。
# 在 openclaw-vllm venv 內跑(它有 torch+cuda)。
set -uo pipefail

VENV="${LOCATE_VENV:-/home/aiunion/.venvs/openclaw-vllm}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="${LOCATE_LOG:-$SCRIPT_DIR/locate_server.log}"
PORT="${LOCATE_PORT:-18794}"
MODEL_PATH="${LOCATE_MODEL_PATH:-/home/aiunion/hf-models/LocateAnything-3B}"

if [ ! -f "$MODEL_PATH/config.json" ]; then
  echo "ERROR: model not found at $MODEL_PATH" >&2
  echo "Download with: hf download nvidia/LocateAnything-3B --local-dir $MODEL_PATH" >&2
  exit 1
fi

# Kill existing instance on the same port (exact PID via ss)
EXISTING_PID="$(ss -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {match($0,/pid=[0-9]+/); if(RSTART) print substr($0,RSTART+4,RLENGTH-4); exit}')"
if [ -n "${EXISTING_PID:-}" ]; then
  echo "Killing existing locate-server PID $EXISTING_PID"
  kill "$EXISTING_PID" 2>/dev/null || true
  sleep 2
fi

export LOCATE_PORT="$PORT"
export LOCATE_MODEL_PATH="$MODEL_PATH"
echo "starting locate-anything-server on :$PORT (model $MODEL_PATH)"
nohup "$VENV/bin/python3" "$SCRIPT_DIR/locate_server.py" >"$LOG" 2>&1 &
echo "PID $!, log $LOG"
echo "wait until ready: until curl -fsS http://127.0.0.1:$PORT/health; do sleep 2; done"
