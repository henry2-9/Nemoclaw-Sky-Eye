#!/usr/bin/env bash
# =============================================================================
# openclaw container entrypoint
#
#   1. Validate required environment variables early (fail fast, fail loud).
#   2. Render the openclaw.json config from a template (no secrets in image).
#   3. Ensure mutable state directories exist and are writable.
#   4. exec into the supplied command (default: openclaw gateway).
# =============================================================================
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*" >&2; }

# ---- 1. Required env vars --------------------------------------------------
required_vars=(
  VLM_API_URL
  VLM_MODEL
  MONGO_URI
  LINE_CHANNEL_ACCESS_TOKEN
  LINE_CHANNEL_SECRET
)
missing=0
for v in "${required_vars[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    log "ERROR: required env var '$v' is not set"
    missing=1
  fi
done
[[ "$missing" -eq 0 ]] || exit 1

# ---- 2. Render openclaw.json from template ---------------------------------
template="/config/openclaw.json.template"
rendered="/state/openclaw/openclaw.json"
mkdir -p "$(dirname "$rendered")"

if [[ -f "$template" ]]; then
  # Only substitute variables that are explicitly whitelisted, to avoid
  # accidentally interpolating unrelated shell syntax present in the template.
  envsubst \
    '${VLM_API_URL} ${VLM_MODEL} ${VLM_API_KEY} ${LLM_API_URL} ${LLM_API_KEY} ${MONGO_URI} ${LINE_CHANNEL_ACCESS_TOKEN} ${LINE_CHANNEL_SECRET} ${TELEGRAM_BOT_TOKEN} ${TELEGRAM_ALLOW_FROM} ${GOOGLE_API_KEY} ${PUBLIC_WEBHOOK_URL} ${TZ}' \
    < "$template" > "$rendered"
  log "rendered openclaw.json → $rendered"
else
  log "WARNING: $template not found; skipping template render"
fi

# ---- 3. State dirs ---------------------------------------------------------
mkdir -p /state/openclaw /state/sessions /state/memory
mkdir -p /data/video /data/event_data

# ---- 4. Exec -----------------------------------------------------------
log "starting: $*"
exec "$@"
