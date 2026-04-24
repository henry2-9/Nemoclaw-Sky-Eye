# Security AI Agent (FPG Appliance)

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
            ┌──────────────────┼─────────────────────┐
            │                  ▼                     │
            │         ┌────────────────┐             │
            │         │   openclaw     │  ← agent    │
            │         │   + fpg-tools  │  ← CLI tools│
            │         └─┬────────────┬─┘             │
            │           │            │               │
            │ ┌─────────▼─────┐ ┌────▼────────────┐  │
            │ │ llama-server  │ │    MongoDB      │  │
            │ │ (VLM inference)│ │ (events/state)  │  │
            │ └───────────────┘ └─────────────────┘  │
            │                                        │
            │        fpg_internal docker network     │
            └────────────────────────────────────────┘
                       ▲                     ▲
             /config/event-types/*.yaml   /data/{video,event_data}
               (built-in + customer)        (bind mount)
```

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

Put your GGUF model under `./models/`, then set `VLM_MODEL_FILENAME` in `.env`.

```bash
ls models/
# qwen3.6-35b-a3b-Q4_K_M.gguf
```

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

See [`docs/event-types-guide.md`](docs/event-types-guide.md). In short:

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
