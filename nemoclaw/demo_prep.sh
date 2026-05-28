#!/usr/bin/env bash
# 錄製前一鍵環境備妥:檢查服務、登錄頻道、印出「可以開始錄」清單。
# 不做破壞性動作。
set -uo pipefail
cd "$(dirname "$0")/.."
source nemoclaw/nemoclaw.env

G='\033[92m'; R='\033[91m'; B='\033[1m'; D='\033[0m'; Y='\033[93m'
ok(){ echo -e "${G}✅${D} $1"; }
bad(){ echo -e "${R}❌${D} $1"; }
warn(){ echo -e "${Y}⚠️${D} $1"; }

echo -e "${B}== NemoClaw Sentinel — Demo 環境備妥 ==${D}"
echo "backend=${NEMOCLAW_DB_BACKEND}  ws=${SENTINEL_WORKSPACE}"
echo ""

# 1) 三服務
FAIL=0
echo -e "${B}[1/3] 服務探針${D}"
for pair in "Nemotron|http://127.0.0.1:31010/v1/models" \
            "Falcon|http://127.0.0.1:18793/health" \
            "NemoClaw-Hermes|http://127.0.0.1:8642/v1/models"; do
  name="${pair%%|*}"; url="${pair##*|}"
  if curl -fsS --max-time 4 "$url" >/dev/null 2>&1; then ok "$name OK"; else bad "$name 不可用 ($url)"; FAIL=1; fi
done

# 2) 頻道登錄(冪等)
echo -e "\n${B}[2/3] 頻道登錄${D}"
python3 nemoclaw/register_channels.py >/dev/null 2>&1 && ok "register_channels 完成" || warn "register_channels 有警告"
CH=$(python3 - <<'PY'
import os,sys; sys.path.insert(0,os.environ["NEMOCLAW_DIR"])
import db_factory; print(len(db_factory.channel_db().get_all_channels()))
PY
)
ok "頻道數:${CH}"

# 3) 既有稽核/飛行資料量(dashboard 是否已有東西可看)
echo -e "\n${B}[3/3] Dashboard 資料量${D}"
AROWS=$( [ -f nemoclaw/audit.jsonl ] && wc -l < nemoclaw/audit.jsonl || echo 0 )
FROWS=$( [ -f nemoclaw/flight_recorder.jsonl ] && grep -c trace_id nemoclaw/flight_recorder.jsonl 2>/dev/null || echo 0 )
echo "audit 決策列:${AROWS}  flight 軌跡列:${FROWS}"
if [ "${AROWS:-0}" -lt 5 ]; then
  warn "稽核資料偏少 — 想要豐富的 dashboard,先跑幾輪巡檢(systemd 服務已自動執行)"
else
  ok "稽核資料充足"
fi

echo ""
echo -e "${B}== 錄製清單 ==${D}"
if [ "$FAIL" = "0" ]; then echo -e "${G}${B}環境就緒,可以開始錄。${D}"; else echo -e "${R}${B}有紅燈,先處理上面 ❌ 再錄。${D}"; fi
cat <<EOF

開瀏覽器(建議大字體):
  http://localhost:8099         主頁 N×N 監控牆 + 即時事件 + 思考流 + 跨地標關聯
                                + 🛰 OpenShell 沙箱二次調查
  http://localhost:8099/wall    全螢幕監控牆模式

若 dashboard 未開:
  python3 nemoclaw/dashboard/app.py
EOF
exit "$FAIL"
