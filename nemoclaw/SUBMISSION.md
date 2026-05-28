# 🌐 NemoClaw 天眼 · Sky Eye — NVIDIA Agent Hackathon 提交摘要

> **Nemotron 負責看,NVIDIA NemoClaw 負責守。** 單台 DGX Spark **GB10** 上、7×24 自主巡檢世界路口/公共地標的天眼 agent —— 自學 cheap-gate 基線、自主調查與處置、自主上網爬取即時情報做跨來源驗證、事件處置**不需人工核准**,每個動作都受 NemoClaw 政策護欄治理、全程可稽核。

## 🎬 Demo 影片
**https://www.youtube.com/watch?v=kmVBfhoFfS0** (2:30)

## 它做什麼
主視覺是 **N×N 監控牆**(預設 4×4 · 可切 1/4/6/9/16/25):台灣高公局 6 路國道 CCTV + 倫敦 TfL JamCam 6 路 + 日本/歐洲 24/7 公開直播 + agent 自主 yt-dlp 探索的世界路口,總計 ~22 路。右側即時事件 panel 拉 audit ≥medium 最近事件依嚴重度上色。

```
LocateAnything sweep(便宜,按巡檢週期)
   → 〔有候選〕→ Nemotron-Omni 多模態確認分級(本機 vLLM :31010)
   → 真 NVIDIA NemoClaw / OpenShell 沙箱 文字 triage(policy 治理)
   → 〔severity ≥ high〕→ OpenShell sandbox 3 源獨立交叉驗證
         curl weather.gov + earthquake.usgs.gov + opensky-network.org + hn.algolia.com
         → Hermes 寫 5 行 verdict(每源證實/否認/無訊號 + 綜合判斷 + 建議)
   → 政策閘(唯一對外出口) → Telegram 通知(人臉馬賽克)
   → 跨地標關聯偵測(5min 窗 ≥2 路同類事件升級)
   → 稽核軌跡 + Incident Flight Recorder
```

## 對應評審標準
| 要求 | 實現 |
|---|---|
| **核心模型 = Nemotron** ✅ | 每個事件的多模態確認/描述/分級皆由 `Nemotron-3-Nano-Omni-30B`(本機 vLLM :31010)推理 |
| **autonomous / no human in loop** ✅✅ | production supervisor 自動觸發偵測→**自主調查**(信心邊界時自己再查)→治理→**自主分級處置/自動 Markdown 報告**→**自主上網爬即時情報做交叉驗證**→**自主跨地標關聯升級**;處置無人工核准 |
| **long-running 架構** ✅ | cheap-sweep 連續、Nemotron 按需喚起、per-cycle watchdog;systemd 開機自啟、docker `restart=always` 自癒 |
| **real task / deployable** ✅ | 真實監控事件全鏈處理;systemd 常駐、SQLite confirmed incidents + JSONL 稽核持久化、服務健康探針 |
| **persistent deployment** ✅ | systemd `Restart=always` + 稽核 `audit.jsonl` + `flight_recorder.jsonl` + `followups.jsonl` + `correlation_alerts.jsonl`(重啟可查) |
| **bonus:NemoClaw policy guardrails** ✅✅ | **裝了真正的 NVIDIA NemoClaw**(OpenShell 沙箱 + policy + intent verification),治理決策 `governed_by=nemoclaw-openshell`;**custom policy preset `sky-eye-recon` 開通 4 個白名單即時情報源**,「能爬什麼」由 policy 治理 |

## 五個差異化亮點
1. **可看見的自主閉環**:production loop 啟動即離手—— N×N 監控牆持續更新各路遮罩巡檢快照與健康狀態;agent 自己看(Nemotron)、真 NemoClaw 治理、**自主分級處置**、critical **自動產 Markdown 事件報告**。
2. **用了真 NemoClaw,不是仿製**:官方 `curl|bash` 安裝,Hermes agent 跑在 OpenShell 沙箱、inference 路由到本機 Nemotron(零雲端);治理決策有 OpenShell policy 背書。
3. **真實上網爬即時情報 + 3 源融合**:嚴重事件後 Hermes 在 OpenShell sandbox 內 `curl` 政府氣象警報 + USGS 即時地震 + OpenSky 即時航班 + HN 即時討論 4 個 sub-hourly 來源;然後寫 5 行 verdict(每源證實/否認/無訊號 + 綜合判斷 + 建議)。**能爬什麼由 policy 白名單治理,不是 prompt 喊話**。
4. **跨地標關聯偵測**:5min 窗內 ≥2 路同類事件 → 自動升級「全球協同/同源注入」高優先警報,3+ 路 → critical。多攝影機 reasoning,不只單路偵測。
5. **全程可稽核(Incident Flight Recorder)**:牆面平時只展示 redacted 最近巡檢快照;事件軌跡包含 LocateAnything 候選 → Nemotron 原始回答 → grading → NemoClaw triage → policy decision → sandbox 二次調查 stdout → Hermes verdict。

## 實機驗證
全部跑在**一台 GB10**(Nemotron + LocateAnything + NemoClaw + dashboard 共存,零雲端推理)。
- 22 路世界路口巡檢(6 台灣國道 + 6 倫敦 TfL + 渋谷 + 道頓堀 + Alexanderplatz + De Dam + 6 自主發現)
- 136/136 單元測試通過

## 技術棧 / 復用
Nemotron-3-Nano-Omni-NVFP4(vLLM)· NVIDIA NemoClaw / OpenShell · LocateAnything-3B · Telegram · **SQLite(預設,免 DB server)/ MongoDB(選用)** · GB10(aarch64, sm_121)。複用既有 Sentinel appliance 約 80%(5 個 `sentinel-*` 工具、event-types、通知、持久化);資料層與 FPG 共用 MongoDB 脫鉤,全 `sentinel-*` 工具經端到端煙霧驗證可在 SQLite 後端運作。

## 快速啟動
```bash
source nemoclaw/nemoclaw.env && python3 nemoclaw/register_channels.py
sudo systemctl start nemoclaw-sentinel     # 正式部署(已 enable)
python3 nemoclaw/dashboard/app.py          # 監控牆 + 治理稽核 :8099
```
看 `nemoclaw/nemoclaw-briefing` 自主情勢簡報 · `nemoclaw/nemoclaw-flight-recorder --latest 3` 看完整軌跡。

— Henry Lu · NemoClaw · **136 單元測試通過** · 自主閉環(偵測→自主調查→治理→處置→3 源跨來源驗證→跨地標關聯→稽核)· branch `nemoclaw-sentinel`
