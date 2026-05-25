#!/usr/bin/env bash
# 錄製前一鍵環境備妥:檢查服務、登錄頻道、產生攻擊矩陣與注入素材,
# 最後印出「可以開始錄」清單。不做破壞性動作、不自動觸發慢的攻擊場景
# (攻擊場景留給鏡頭前現場觸發,才是 demo 重點)。
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
echo -e "${B}[1/5] 服務探針${D}"
for pair in "Nemotron|http://127.0.0.1:31010/v1/models" \
            "Falcon|http://127.0.0.1:18793/health" \
            "NemoClaw-Hermes|http://127.0.0.1:8642/v1/models"; do
  name="${pair%%|*}"; url="${pair##*|}"
  if curl -fsS --max-time 4 "$url" >/dev/null 2>&1; then ok "$name OK"; else bad "$name 不可用 ($url)"; FAIL=1; fi
done

# 2) 頻道登錄(冪等)
echo -e "\n${B}[2/5] 頻道登錄${D}"
python3 nemoclaw/register_channels.py >/dev/null 2>&1 && ok "register_channels 完成" || warn "register_channels 有警告"
CH=$(python3 - <<'PY'
import os,sys; sys.path.insert(0,os.environ["NEMOCLAW_DIR"])
import db_factory; print(len(db_factory.channel_db().get_all_channels()))
PY
)
ok "頻道數:${CH}"

# 3) 注入素材 + ch19
echo -e "\n${B}[3/5] 注入攻擊素材 (ch19)${D}"
bash nemoclaw/demo_injection.sh >/tmp/nemoclaw_demo_prep_inj.log 2>&1 && \
  ok "ch19 注入影片就緒 ($(grep -o 'channel 19.*' /tmp/nemoclaw_demo_prep_inj.log | head -1))" || \
  { bad "ch19 注入素材生成失敗"; tail -3 /tmp/nemoclaw_demo_prep_inj.log; FAIL=1; }

# 4) 攻擊矩陣 JSON(dashboard 面板讀)
echo -e "\n${B}[4/5] 攻擊挑戰矩陣${D}"
if python3 nemoclaw/nemoclaw-attack-matrix --write >/tmp/nemoclaw_demo_prep_matrix.log 2>&1; then
  RES=$(grep -o '[0-9]/[0-9] 攻擊全數防禦' /tmp/nemoclaw_demo_prep_matrix.log | head -1)
  ok "攻擊矩陣 ${RES:-已產生} → attack_matrix.json"
else
  warn "攻擊矩陣回傳非 0(有缺口?)"; tail -3 /tmp/nemoclaw_demo_prep_matrix.log
fi

# 5) 既有稽核/飛行資料量(dashboard 是否已有東西可看)
echo -e "\n${B}[5/5] Dashboard 資料量${D}"
AROWS=$( [ -f nemoclaw/audit.jsonl ] && wc -l < nemoclaw/audit.jsonl || echo 0 )
FROWS=$( [ -f nemoclaw/flight_recorder.jsonl ] && grep -c trace_id nemoclaw/flight_recorder.jsonl 2>/dev/null || echo 0 )
echo "audit 決策列:${AROWS}  flight 軌跡列:${FROWS}"
if [ "${AROWS:-0}" -lt 5 ]; then
  warn "稽核資料偏少 — 想要豐富的 dashboard,先跑幾輪巡檢:"
  echo "    nohup bash nemoclaw/nemoclaw-supervisor.sh >/dev/null 2>&1 &   # 跑 1-2 分鐘後 Ctrl 看 dashboard"
else
  ok "稽核資料充足"
fi

echo ""
echo -e "${B}== 錄製清單 ==${D}"
if [ "$FAIL" = "0" ]; then echo -e "${G}${B}環境就緒,可以開始錄。${D}"; else echo -e "${R}${B}有紅燈,先處理上面 ❌ 再錄。${D}"; fi
cat <<EOF

開兩個視窗(建議大字體):
  ① 瀏覽器 → http://localhost:8099            (dashboard,含「安全挑戰矩陣 5/5」面板)
     若 dashboard 未開:  python3 nemoclaw/dashboard/app.py
  ② 終端機 → 依 DEMO_SCRIPT.md 逐鏡頭操作

決勝鏡頭(現場觸發):
  bash nemoclaw/demo_attack_scene.sh            # 不發 Telegram
  bash nemoclaw/demo_attack_scene.sh --notify   # 正式錄製要看 Telegram 通知時
  python3 nemoclaw/nemoclaw-attack-matrix       # 多模態 5/5 防禦(終端表格)
EOF
exit "$FAIL"
