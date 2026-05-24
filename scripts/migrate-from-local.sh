#!/usr/bin/env bash
# =============================================================================
# Migrate a non-containerized local Sentinel setup into this docker-compose stack.
#
# What this script does (and does NOT):
#   ✅ Dump the local MongoDB and restore it into the `mongodb` container volume
#   ✅ Copy ~/Sentinel/BOOTSTRAP.md → config/bootstrap.md (review before commit)
#   ✅ Report every manual step you still need to do
#   ❌ Touch any secrets (LINE token, API keys). You move those to `.env`.
#   ❌ Stop the old services. Do that explicitly once you have verified the
#      new stack works end-to-end.
#
# Prerequisites
#   • Local mongod running and reachable as 127.0.0.1:27017
#   • The mongodb container has been brought up at least once:
#       docker compose up -d mongodb
#   • `.env` already filled in (MONGO_USERNAME / MONGO_PASSWORD at minimum)
# =============================================================================
set -euo pipefail

# ---- Paths -----------------------------------------------------------------
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="${REPO_ROOT}/migration-dump"
LEGACY_BOOTSTRAP="${HOME}/Sentinel/BOOTSTRAP.md"
TARGET_BOOTSTRAP="${REPO_ROOT}/config/bootstrap.md"

# ---- .env ------------------------------------------------------------------
if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  echo "ERROR: ${REPO_ROOT}/.env not found. Copy .env.example and edit it first." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source "${REPO_ROOT}/.env"; set +a

# ---- 1. mongodump the legacy DB -------------------------------------------
echo "==> [1/3] Dumping local MongoDB to ${DUMP_DIR}"
mkdir -p "${DUMP_DIR}"
if ! command -v mongodump >/dev/null 2>&1; then
  echo "ERROR: mongodump not found. Install mongodb-database-tools or run this inside the container." >&2
  exit 1
fi
mongodump --host 127.0.0.1 --port 27017 --out "${DUMP_DIR}" --quiet

# ---- 2. mongorestore into container ----------------------------------------
echo "==> [2/3] Restoring into the mongodb container"
docker compose exec -T mongodb sh -c "rm -rf /tmp/restore && mkdir -p /tmp/restore"
docker cp "${DUMP_DIR}/." "$(docker compose ps -q mongodb)":/tmp/restore/
docker compose exec -T mongodb mongorestore \
  --username "${MONGO_USERNAME}" --password "${MONGO_PASSWORD}" \
  --authenticationDatabase admin \
  --drop \
  /tmp/restore

# ---- 3. copy bootstrap.md --------------------------------------------------
echo "==> [3/3] Copying BOOTSTRAP.md"
if [[ -f "${LEGACY_BOOTSTRAP}" ]]; then
  cp "${LEGACY_BOOTSTRAP}" "${TARGET_BOOTSTRAP}"
  echo "    copied → ${TARGET_BOOTSTRAP}"
  echo "    ⚠  Review for secrets or host-specific paths before committing."
else
  echo "    no BOOTSTRAP.md found at ${LEGACY_BOOTSTRAP}; skipping."
fi

cat <<'EOF'

==============================================================================
  Migration finished. Manual follow-ups:

    1. Copy videos/event artifacts into ${Sentinel_DATA_HOST_PATH:-./data}/
         rsync -a ~/Sentinel/video/         ./data/video/
         rsync -a ~/Sentinel/event_data/    ./data/event_data/

    2. Fill in .env with LINE / Telegram / Cloudflare tokens.

    3. Verify end-to-end:
         docker compose logs -f openclaw
         (send a test message to your LINE channel)

    4. Once confirmed stable, stop the legacy services:
         systemctl --user stop openclaw-gateway ngrok-openclaw
         systemctl --user disable openclaw-gateway ngrok-openclaw

  Do NOT disable legacy services until the new stack is verified working.
==============================================================================
EOF
