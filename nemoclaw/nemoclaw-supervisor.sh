#!/usr/bin/env bash
# NemoClaw Sentinel 自主監督迴圈:持續跑 nemoclaw-cycle,週期間 sleep,
# per-cycle timeout 防卡死。以 systemd / nohup 維持長時間運行(no human in the loop)。
set -uo pipefail
cd "$(dirname "$0")/.."
source nemoclaw/nemoclaw.env
INTERVAL="${NEMOCLAW_INTERVAL:-30}"
CYCLE_TIMEOUT="${NEMOCLAW_CYCLE_TIMEOUT:-600}"
LOG="${NEMOCLAW_DIR}/supervisor.log"
echo "$(date -Is) supervisor start interval=${INTERVAL}s max_per_cycle=${NEMOCLAW_MAX_PER_CYCLE:-4}" | tee -a "$LOG"
trap 'echo "$(date -Is) supervisor stop" | tee -a "$LOG"; exit 0' INT TERM
while true; do
  ts=$(date -Is)
  out=$(timeout "$CYCLE_TIMEOUT" ./nemoclaw/nemoclaw-cycle 2>>"$LOG") || out='{"error":"cycle timeout/fail"}'
  echo "$ts $out" | tee -a "$LOG"
  sleep "$INTERVAL"
done
