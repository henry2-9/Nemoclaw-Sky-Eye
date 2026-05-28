# 🌐 NemoClaw Sky Eye

> **Nemotron sees, NVIDIA NemoClaw guards.** A 24/7 autonomous agent on a single DGX Spark **GB10** patrolling world traffic intersections and public landmarks — self-learning cheap-gate baselines, autonomous investigation, autonomous web crawling for real-time intel cross-verification, cross-camera correlation escalation, and **incident handling without human approval** — every action governed by NemoClaw policy guardrails with full audit trail.

**繁體中文版本:** [README.md](README.md)

---

## ✨ Key Features

| Capability | Description |
|---|---|
| 🎥 **N×N Surveillance Wall** | 4×4 default; switchable to 1/4/6/9/16/25; Taiwan freeway CCTV + London TfL + Japan + Europe + agent-discovered = ~22 channels |
| 🧠 **R2 Cascade Architecture** | Falcon cheap-sweep (cheap) → Nemotron-Omni multimodal confirmation (on-demand) → real NVIDIA NemoClaw governance |
| 🛰 **3-Source Cross-Verification via OpenShell Sandbox** | On severe events, Hermes actively `curl`s `weather.gov + USGS + HN + OpenSky` (4 sub-hourly realtime sources) from inside the sandbox |
| 🌐 **Cross-Camera Correlation** | ≥2 channels with same event_type within 5-min window → auto-escalate to coordinated alert (3+ = critical) |
| 🔬 **Visible Autonomy** | First-person thought-stream ticker: agent's actions visible in real-time (sweep/baseline/investigate/discover/...) |
| 🛡 **Real NemoClaw Governance** | OpenShell sandbox + policy preset `sky-eye-recon` whitelisting 4 hosts; `governed_by=nemoclaw-openshell` |
| 🔒 **Privacy by Design** | Mandatory face redaction; raw frames return 403, only redacted artifacts served; dashboard URL strict allowlist |
| 📋 **Flight Recorder** | Full per-event trace: sweep → Nemotron raw → grading → NemoClaw triage → policy decision → sandbox followup |
| 💾 **Local Storage** | SQLite default (no DB server needed); MongoDB switchable |
| ⚡ **Zero Cloud Inference** | Nemotron + Falcon + NemoClaw + dashboard all run on one GB10 |

---

## 📸 UI Preview

### Home: N×N Surveillance Wall + Live Events + Autonomous Investigation
![Sky Eye Dashboard](docs/screenshots/home.png)

> 👉 **Screenshot pending**: `docs/screenshots/home.png` (home page N×N wall + right-side 📡 Live Events)
> Temporary reference: `home-legacy.png` (older focus-grid layout, same dark theme)

### Full-screen Surveillance Wall: `/wall?layout=16`
![Surveillance Wall](docs/screenshots/wall.png)

> 👉 **Screenshot pending**: `docs/screenshots/wall.png` (full-screen wall mode, 4×4 dark theme)

### OpenShell Sandbox 3-Source Cross-Verification
![3-Source Cross-Verification](docs/screenshots/followup.png)

> 👉 **Screenshot pending**: `docs/screenshots/followup.png` (expand "Event Records & Tech Evidence" → 🛰 OpenShell Sandbox Investigation Records panel)

---

## 🏗 Architecture

```
                ┌─────────────────────────────────────────────────────┐
                │  22 World Intersections (TW Freeway·TfL·Japan·EU·   │
                │                          agent-discovered)          │
                └─────────────────────────────────────────────────────┘
                                          │
                                          ▼
            ┌──────────────────────────────────────────────────┐
            │  Falcon Perception sweep (cheap, per-cycle)      │
            │  → 1 frame / channel / cycle, OWL-ViT detection  │
            └──────────────────────────────────────────────────┘
                                          │ candidates
                                          ▼
            ┌──────────────────────────────────────────────────┐
            │  Nemotron-3-Nano-Omni-30B (vLLM :31010)          │
            │  → multimodal confirm + grade + borderline       │
            │    re-investigation                              │
            └──────────────────────────────────────────────────┘
                                          │ confirmed
                                          ▼
            ┌──────────────────────────────────────────────────┐
            │  Real NVIDIA NemoClaw / Hermes (:8642)           │
            │  OpenShell sandbox + policy guardrails           │
            │  → triage (severity guardrail vs OCR injection)  │
            └──────────────────────────────────────────────────┘
                                          │ severity ≥ high
            ┌──────────────────────────────────────────────────┐
            │  🛰 sandbox 3-source crawl (policy-whitelisted)  │
            │  curl weather.gov + USGS + HN + OpenSky          │
            │  → Hermes 5-line verdict fusion                  │
            │     (confirm/refute/no-signal per source)        │
            └──────────────────────────────────────────────────┘
                                          │
                                          ▼
            ┌──────────────────────────────────────────────────┐
            │  Policy gate (sole external exit)                │
            │  → Telegram notify + audit + flight recorder     │
            │  → Cross-camera correlation (5min ≥2 channels)   │
            └──────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

```bash
# 1. Source environment
source nemoclaw/nemoclaw.env

# 2. Ensure 3 services running
docker start vllm-nemotron-omni-nvfp4    # Nemotron :31010
nemohermes sentinel recover               # Hermes :8642
# Falcon Perception should be auto-started # :18793

# 3. Apply sandbox real-time intel whitelist policy
nemohermes sentinel policy-add --from-file nemoclaw/policies/sky-eye-recon.yaml --yes

# 4. Register channels + start persistent supervisor
python3 nemoclaw/register_channels.py
sudo systemctl start nemoclaw-sentinel

# 5. Open dashboard
python3 nemoclaw/dashboard/app.py         # http://localhost:8099
```

Environment check: `bash nemoclaw/demo_prep.sh` (3-step preflight)

---

## 📁 Key Files

```
nemoclaw/
  dashboard/app.py              N×N wall + live events + audit dashboard (:8099 + /wall)
  orchestrator.py               R2 cascade orchestrator (sweep→Nemotron→Hermes→policy→followup)
  sweep.py                      Falcon cheap-gate sweep
  nemoclaw_triage.py            Real NemoClaw Hermes triage (:8642)
  hermes_followup.py            OpenShell sandbox 3-source realtime intel crawler
  correlation.py                Cross-camera correlation (5min ≥2 channels same event_type)
  discover.py                   Agent autonomous yt-dlp discovery (traffic + landmark profiles)
  policy.py / act.py            Policy gate (sole external exit, audited)
  audit.py / flight_recorder.py Full audit + per-event flight recorder
  redact.py                     Face redaction (privacy by design)
  thoughts.py                   First-person thought-stream ticker
  briefing.py                   Autonomous situation briefing (agent-scheduled)
  baseline.py                   Per-camera self-learning baseline (cold-start floor=2)
  watchdog.py                   Service health monitor (transition log)
  curiosity.py                  Autonomous curiosity tasks (idle channel proactive patrol)
  feed_health.py                Channel state watchdog
  world_channels.yaml           Seed 22 world intersections (gov public CCTV + YouTube 24/7)
  landmarks.yaml                Seed global landmarks (alternate profile)
  policies/sky-eye-recon.yaml   NemoClaw custom policy (4 realtime intel whitelist hosts)
  nemoclaw-sentinel.service     systemd persistent (auto-start / crash-restart)
  nemoclaw-supervisor.sh        long-running supervisor loop (watchdog + cycle + discover)
  tests/                        136 unit tests
```

---

## 🎬 Demo Script

Full recording script: [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md). Summary:

1. **Home N×N Wall** (0:00-0:25) — 22 world intersections, switch layouts 9/25
2. **Status: Local Inference** (0:25-0:50) — `nemohermes sentinel status` proves Nemotron + NemoClaw both local
3. **Policy Whitelist** (0:50-1:15) — `nemohermes sentinel policy-list` see `sky-eye-recon` preset
4. **🛰 OpenShell 3-Source Verification** (1:15-1:45) — expand "Event Records" → followup cards, see Hermes actually `curl`ing realtime sources in sandbox
5. **🌐 Cross-Camera Correlation** (1:45-2:05) — correlation panel
6. **Flight Recorder** (2:05-2:20) — click any event "View Evidence Chain"
7. **Hold** (2:20-2:30) — surveillance wall + live events panel

---

## 📊 Hackathon Judging Criteria Alignment

| Requirement | Implementation |
|---|---|
| **Core model = Nemotron** ✅ | All multimodal confirmation/description/grading by `Nemotron-3-Nano-Omni-30B` (local vLLM :31010) |
| **autonomous / no human in loop** ✅✅ | Production supervisor auto-triggers detection → autonomous investigation → governance → autonomous grading & handling → autonomous web crawling for cross-source verification → cross-camera correlation escalation; no human approval |
| **long-running architecture** ✅ | Continuous cheap-sweep, on-demand Nemotron, per-cycle watchdog; systemd auto-start, docker `restart=always` self-healing |
| **real task / deployable** ✅ | Real 22-channel world intersection patrol; systemd persistent, SQLite + JSONL persistence, service health probes |
| **persistent deployment** ✅ | systemd `Restart=always` + `audit.jsonl` + `flight_recorder.jsonl` + `followups.jsonl` + `correlation_alerts.jsonl` |
| **bonus: NemoClaw policy guardrails** ✅✅ | Real NVIDIA NemoClaw (OpenShell + policy + intent verification); custom `sky-eye-recon` preset whitelists what sandbox can crawl |

---

## 🛠 Tech Stack

- **Multimodal VLM**: Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4 (vLLM 0.20.0)
- **Governance agent**: NVIDIA NemoClaw v0.0.50 + OpenShell sandbox + Hermes
- **Perception**: Falcon-Perception (OWL-ViT)
- **Hardware**: DGX Spark GB10 (aarch64, sm_121)
- **Persistence**: SQLite (default, no DB server) / MongoDB (optional)
- **Notification**: Telegram Bot
- **Web**: Pure Python `http.server` (no external web framework)

---

## 📜 License

— Henry Lu · NemoClaw · NVIDIA Agent Hackathon · branch `nemoclaw-sentinel`
