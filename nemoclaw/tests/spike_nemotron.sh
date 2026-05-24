#!/usr/bin/env bash
# Nemotron-Omni 多模態 smoke test:抽一張真實幀 + 提問,確認回應合理
set -euo pipefail
VID="${1:-${SENTINEL_WORKSPACE:-$HOME/sentinel-workspace}/video/火煙偵測1.mp4}"
SEC="${2:-2}"
FRAME=/tmp/nemo_spike.jpg
ffmpeg -y -ss "$SEC" -i "$VID" -frames:v 1 -vf scale=512:-1 -q:v 3 "$FRAME" >/dev/null 2>&1
B64=$(base64 -w0 "$FRAME")
curl -s http://localhost:31010/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"nemotron_3_nano_omni\",\"max_tokens\":200,\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"這張監控畫面中是否有火災或濃煙?用繁體中文一句話回答並說明依據。\"},{\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/jpeg;base64,$B64\"}}]}]}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['choices'][0]['message']['content'] if 'choices' in d else json.dumps(d,ensure_ascii=False,indent=2))"
