#!/usr/bin/env bash
# Backward-compatible entrypoint for the polished attack-scene demo.
set -euo pipefail
exec "$(dirname "$0")/demo_attack_scene.sh" "$@"
