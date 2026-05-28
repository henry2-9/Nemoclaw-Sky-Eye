# 🎬 NemoClaw Sky Eye — 錄製本(目標 ~2:30)

> **一句話定位**:單台 DGX Spark GB10 上 **7×24 自主世界路口監控 agent**——排程啟動後自己看(Nemotron)、自己調查、真 NemoClaw 治理、自主在 sandbox 內爬即時情報做交叉驗證、跨地標關聯升級、**事件處置不需人工核准且全程留軌跡**。

---

## ▶️ 錄製前一鍵備妥
```bash
cd ~/Security-AI-Agent
bash nemoclaw/demo_prep.sh           # 檢查 3 服務、登錄頻道、印就緒清單
sudo systemctl status nemoclaw-sentinel   # 確認常駐服務已運行
python3 nemoclaw/dashboard/app.py    # 另開一窗;瀏覽器 http://localhost:8099
```
`demo_prep.sh` 全綠才開錄。建議:終端機放大字體、瀏覽器全螢幕、關閉通知。
**讓它先自跑一段以證明自主**:dashboard 應已有事件紀錄、思考流、followup 卡片。

---

## 🎬 分鏡 / 逐句旁白 / 對應指令

| # | 時間 | 畫面 | 旁白(照唸) | 指令 / 指的重點 |
|---|---|---|---|---|
| **1** | 0:00–0:25 | 瀏覽器首頁 **N×N 監控牆** | 「這是 7×24 自主跑的世界路口監控。預設 4×4 看 16 路:台灣高公局 6 路、倫敦 TfL 6 路、東京渋谷、大阪道頓堀、柏林 Alexanderplatz、阿姆斯特丹 De Dam,還有 agent 自己上 YouTube 找到的世界路口。**全部跑在一台 GB10。**」 | 指 16 路 cell、切版面 9/25 chooser、指右側「📡 即時事件」 |
| **2** | 0:25–0:50 | 終端機跑 status | 「核心推理是本機 Nemotron;治理交給**真正的 NVIDIA NemoClaw**,跑在 OpenShell 沙箱、受 policy 護欄管。**零雲端推理。**」 | `nemohermes sentinel status` → 指 `Model: nemotron_3_nano_omni / Provider: vllm-local` · `nemohermes sentinel policy-list` 指 `sky-eye-recon` preset |
| **3** | 0:50–1:15 | 首頁展開「事件紀錄與技術證據」 | 「平時牆面只代表正常巡檢;只有異常候選才喚醒 Nemotron。事件處置為自動模式,所有決策都有紀錄。」 | 指狀態帶 `服務正常 / 處置模式 自動`;指「💭 Agent 思考即時流」第一人稱看 agent 在做什麼 |
| **4** | 1:15–1:45 | 滾到「🛰 OpenShell 沙箱二次調查紀錄」 | 「嚴重事件後 Hermes **真的在沙箱裡 curl 公共 API**:政府氣象警報、即時地震、即時航班、即時討論——3 個獨立來源平行驗證。可以爬什麼由 NemoClaw policy 白名單治理,不是 prompt 喊話。」 | 指 followup 卡片:`weather.gov / USGS / HN` 3 條指令的 stdout · 指 Hermes 結論 5 行 verdict |
| **5** | 1:45–2:05 | 滾到「🌐 跨地標關聯偵測」 | 「不只單路偵測——5 分鐘窗內 ≥2 路出現同類事件,自動升級成『全球協同/同源注入』高優先警報。3 路以上 = critical。」 | 指 correlation alert 列表(若無,指「過去 5 分鐘各地標獨立」的安全狀態) |
| **6** | 2:05–2:20 | dashboard 點證據鏈 | 「這起事件有 **flight recorder**:Falcon 候選 → Nemotron 原始回答 → NemoClaw triage → policy decision → sandbox 二次調查,每一步都留軌跡,並保存遮罩後事件影格與影片。」 | 點任一事件「查證據鏈」,指 `nemotron_raw_answer / nemoclaw_triage / policy_decision / hermes_followup` |
| **7** | 2:20–2:30 | 回 dashboard 定格 | 「**Nemotron 看,真 NemoClaw 守**——一台 GB10 上可常駐、可稽核、處置不需人工核准的自主世界路口監控。」 | 定格在 N×N 監控牆 + 即時事件 panel |

---

## 🎯 一句話收尾(給評審)
> 「**Nemotron 負責看,NVIDIA NemoClaw 負責守**——這不是概念 demo,是一台 GB10 上 7×24 自跑、能主動上網爬即時情報做跨來源驗證、跨地標關聯偵測、每個動作都受政策護欄治理、全程可稽核的自主 agent。」

## 🧱 差異化(評審會問)
- **真上網爬蟲**:Hermes 在 OpenShell sandbox 內真的 `curl weather.gov + USGS + HN + OpenSky` 4 個 sub-hourly 即時源做交叉驗證,**能爬什麼由 NemoClaw policy preset `sky-eye-recon` 白名單治理**。
- **跨地標 reasoning**:不只單路偵測,還會跨多路關聯偵測同源攻擊。
- **5 行 verdict 融合**:Hermes 對每來源寫「證實/否認/無訊號」+ 綜合判斷 + 建議,信心可量化。

## 🔧 備援指令(臨場備用)
- 真 NemoClaw 在跑:`curl -s http://127.0.0.1:8642/v1/models`
- 連續運行證明:`grep -c candidates nemoclaw/supervisor.log`(cycle 數)
- 稽核原始證據:`tail nemoclaw/audit.jsonl`(含 `governed_by=nemoclaw-openshell`)
- 最近飛行紀錄:`nemoclaw/nemoclaw-flight-recorder --latest 3`
- 二次調查紀錄:`tail nemoclaw/followups.jsonl`
- 跨地標關聯:`tail nemoclaw/correlation_alerts.jsonl`
- 自主探索:`python3 nemoclaw/discover.py --profile traffic --max 2`(讓 agent 現場找新世界路口)
- 資料後端:預設 **SQLite(免 DB server)**;`NEMOCLAW_DB_BACKEND=mongo` 可切回共用 MongoDB
