# Security AI Agent (FPG Appliance)

> 這是 NemoClaw Sentinel 的底層平台說明。Hackathon 入口請見 [專案根目錄 README](../README.md)。

Edge AI surveillance agent that detects security events (fire/smoke, abnormal
crowd, abnormal weather, intrusion) from video feeds and pushes notifications
to LINE / Telegram / webhooks.

Ships in two SKUs with a single software stack:

- **(a) Hardware Appliance** — preloaded on NVIDIA Grace Blackwell (GB10) ARM64
  with all services enabled on first boot.
- **(b) Software License** — customer-supplied NVIDIA GPU (x86_64 or ARM64),
  deployed via `docker compose up -d` with a license key.

## Architecture

```
                    ┌────────────────────┐
                    │  LINE / Telegram   │
                    └──────────┬─────────┘
                               │ webhook
                    ┌──────────▼─────────┐
                    │   cloudflared      │  (tunnel, fixed public URL)
                    └──────────┬─────────┘
                               │
            ┌──────────────────┼──────────────────────────────┐
            │                  ▼                              │
            │         ┌────────────────┐                      │
            │         │   openclaw     │  ← agent runtime     │
            │         │   + fpg-tools  │  ← 5 CLI scripts     │
            │         └─┬───────┬─────┬┘                      │
            │           │       │     │                       │
            │ ┌─────────▼─┐ ┌───▼───┐ │ ┌───────────────────┐ │
            │ │ llama-    │ │ Mongo │ │ │ falcon-perception │ │
            │ │  server   │ │  DB   │ │ │   (TII Apache-2)  │ │
            │ │ (Qwen VLM)│ │       │ │ │ object detection  │ │
            │ └───────────┘ └───────┘ │ └───────────────────┘ │
            │                                                 │
            │            fpg_internal docker network          │
            └─────────────────────────────────────────────────┘
                  ▲              ▲              ▲
        /config/event-types/  /data/video/   HF cache
        (yaml, customer-      (bind mount)   (volume,
         extensible)                          first boot DL)
```

**Service responsibilities**

| Service             | Role                                                       |
|---------------------|------------------------------------------------------------|
| `mongodb`           | Event records, agent session state                         |
| `llama-server`      | Vision-Language inference (Qwen3.6-35B-A3B + mmproj)       |
| `falcon-perception` | Specialised object detection / OCR (TII Falcon Perception) |
| `openclaw`          | Agent runtime, LINE/Telegram providers, dispatches `fpg-*` |
| `cloudflared`       | Stable public webhook URL (replaces ngrok)                 |

## Quick Start

### Prerequisites

- Docker 24+ with Docker Compose v2
- NVIDIA GPU + `nvidia-container-toolkit`
- Outbound internet access (Cloudflare Tunnel)

### 1. Clone & configure

```bash
git clone http://192.168.0.12:3000/Henry/Security-AI-Agent.git
cd Security-AI-Agent
cp .env.example .env
# edit .env with your LINE/Telegram/Cloudflare tokens
```

### 2. Place the VLM model

llama-server needs both the main GGUF and the multimodal projector.

```bash
ls "$VLM_MODELS_HOST_PATH"
# Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf   (main model, ~23 GB)
# mmproj-F16.gguf                   (vision projector — REQUIRED)
```

Without `mmproj`, llama-server will run text-only and the event-detection
pipeline (which sends frames as image inputs) will be blind.

The `falcon-perception` service auto-downloads its model from Hugging Face
into the `hf_cache` volume on first boot. Initial download takes 5–10 minutes;
subsequent restarts are warm.

### 3. Start

```bash
docker compose up -d
docker compose logs -f openclaw
```

### 4. Verify

- `curl http://localhost:18789/health` → `{"ok":true}` (via openclaw container)
- Cloudflare dashboard → tunnel is `HEALTHY`
- Send a LINE message to the configured channel → agent responds

## Repository Layout

```
.
├── docker-compose.yml
├── .env.example
├── config/
│   ├── event-types/                 # YAML-defined detection types
│   │   ├── fire_smoke.yaml
│   │   ├── abnormal_crowd.yaml
│   │   ├── abnormal_weather.yaml
│   │   └── intrusion.yaml
│   └── openclaw.json.template       # rendered at container start
├── schemas/
│   └── event-type.schema.json       # validation schema
├── images/
│   └── openclaw/                    # Dockerfile + entrypoint
├── scripts/
│   ├── migrate-from-local.sh        # port legacy non-containerized setup
│   ├── backup.sh                    # dump MongoDB + configs
│   └── restore.sh
├── docs/
│   ├── installation.md
│   └── event-types-guide.md
└── .gitea/workflows/                # CI (multi-arch build)
```

## Adding Custom Event Types

See [`event-types-guide.md`](event-types-guide.md). In short:

1. Drop a YAML file into `config/event-types/`, following the schema.
2. Use ID range **100–999** for customer-defined types.
3. `docker compose restart openclaw` to pick it up.

## Versioning

`APP_VERSION` in `.env` pins the image tag. Container images are built and
pushed per release (see `.gitea/workflows/build.yml`).

## Support & License

Commercial license (software SKU) or support contract (appliance SKU).
Contact AiUnion.

---

*This is Phase 1 of productization — see internal roadmap document for upcoming
phases (observability, web admin UI, plugin system, multi-site).*
