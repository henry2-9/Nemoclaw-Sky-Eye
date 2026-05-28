#!/usr/bin/env bash
# NemoClaw Sentinel 自主監督迴圈:持續跑 nemoclaw-cycle,週期間 sleep,
# per-cycle timeout 防卡死。以 systemd / nohup 維持長時間運行(no human in the loop)。
set -uo pipefail
cd "$(dirname "$0")/.."
source nemoclaw/nemoclaw.env
INTERVAL="${NEMOCLAW_INTERVAL:-30}"
CYCLE_TIMEOUT="${NEMOCLAW_CYCLE_TIMEOUT:-600}"
LOG="${NEMOCLAW_DIR}/supervisor.log"
LOCK="${NEMOCLAW_DIR}/.supervisor.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -Is) supervisor already active; refusing duplicate" | tee -a "$LOG"
  exit 0
fi
printf '%s\n' "${NEMOCLAW_CHANNELS_FILE:-}" >"$NEMOCLAW_DIR/active_channels_file"
echo "$(date -Is) supervisor start interval=${INTERVAL}s max_per_cycle=${NEMOCLAW_MAX_PER_CYCLE:-4}" | tee -a "$LOG"
trap 'echo "$(date -Is) supervisor stop" | tee -a "$LOG"; exit 0' INT TERM
cycle_no=0
while true; do
  ts=$(date -Is)
  python3 nemoclaw/watchdog.py --once >>"$LOG" 2>&1 || true
  cycle_no=$((cycle_no + 1))
  if [ "${NEMOCLAW_DISCOVERY_ENABLED:-0}" = "1" ] \
      && [ $((cycle_no % ${NEMOCLAW_DISCOVERY_EVERY_CYCLES:-20})) -eq 0 ]; then
    discovery_profile="${NEMOCLAW_DISCOVERY_PROFILE:-}"
    if [ -z "$discovery_profile" ]; then
      case "${NEMOCLAW_CHANNELS_FILE:-}" in
        */world_channels.yaml) discovery_profile="traffic" ;;
        */landmarks.yaml) discovery_profile="landmark" ;;
      esac
    fi
    if [ -n "$discovery_profile" ]; then
      python3 nemoclaw/nemoclaw-discover --profile "$discovery_profile" \
        --max "${NEMOCLAW_DISCOVERY_MAX_NEW:-1}" >>"$LOG" 2>&1 || true
    fi
  fi
  out=$(timeout "$CYCLE_TIMEOUT" ./nemoclaw/nemoclaw-cycle 2>>"$LOG")
  rc=$?
  if [ "$rc" -ne 0 ]; then
    out="{\"error\":\"cycle failed\",\"exit_code\":$rc}"
  fi
  echo "$ts $out" | tee -a "$LOG"
  sleep "$INTERVAL"
done
