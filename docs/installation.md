# Installation Guide

Two deployment modes share the same software stack.

## Mode A — Hardware Appliance

Shipped from factory with the stack preloaded. On first power-on:

1. Connect the appliance to a LAN with outbound internet access.
2. Visit `http://<appliance-ip>:18789/setup` *(web UI, lands in Phase 3)*.
3. Paste the LINE channel token and the activation key from your invoice.
4. The appliance registers its Cloudflare Tunnel and starts serving.

There is nothing to `apt install`, `docker compose up`, or similar — all
systemd units are enabled on the appliance image.

## Mode B — Software License (BYO GPU)

### Hardware requirements

The stack runs two GPU-bound services (`llama-server` for VLM inference and
`falcon-perception` for object detection) that share the same NVIDIA GPU(s).

| Component | Minimum | Recommended |
|---|---|---|
| CPU | x86_64 (AVX2) or ARM64 v8.2+ | 8+ cores |
| GPU | NVIDIA, **40 GB VRAM** (Qwen 23 GB + Falcon-Perception 10 GB + slack) | 48–80 GB VRAM |
| RAM | 32 GB | 64 GB (GB10 unified memory: 128 GB) |
| Storage | 200 GB (OS + 2 models + 30 days of event data) | 1 TB NVMe |
| OS | Ubuntu 22.04 LTS or 24.04 LTS | 24.04 LTS |
| CUDA | 12.6+ for PyTorch 2.11 path | 13.0 (matches GB10 stock image) |

### Software prerequisites

```bash
# Docker + Compose v2
curl -fsSL https://get.docker.com | sh

# NVIDIA container toolkit
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
```

### Steps

```bash
git clone git@192.168.0.12:Henry/Security-AI-Agent.git
cd Security-AI-Agent

cp .env.example .env
# Fill in MONGO_*, LINE_*, CLOUDFLARE_TUNNEL_TOKEN, PICTSHARE_*,
# and confirm VLM_MODELS_HOST_PATH / VLM_MODEL_FILENAME / VLM_MMPROJ_FILENAME.

# 1. Provide the VLM model files
ls "$VLM_MODELS_HOST_PATH"
#  → Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
#  → mmproj-F16.gguf            (REQUIRED — vision projector)

# 2. Build product images locally (openclaw + falcon-perception)
docker compose build

# 3. Pull third-party images (mongo, llama-server, cloudflared)
docker compose pull mongodb llama-server cloudflared

# 4. Start
docker compose up -d
docker compose ps                  # wait until services are healthy
docker compose logs -f openclaw    # tail agent logs
```

> **First boot is slow.** `falcon-perception` downloads its model from
> Hugging Face into the `hf_cache` volume — expect 5–10 minutes the first
> time. Until that finishes, perception calls return an error but every
> other tool (LINE chat, event query, video ingest) works.

### Verifying

| Check | How |
|---|---|
| All services healthy | `docker compose ps` |
| LLM reachable | `docker compose exec llama-server curl -fsS localhost:8080/health` |
| Perception reachable | `docker compose exec falcon-perception curl -fsS localhost:18793/health` |
| Tunnel up | Cloudflare Zero Trust dashboard → status `HEALTHY` |
| End-to-end | Send a LINE message → see entry in `docker compose logs openclaw` |

### Upgrading

```bash
git pull
docker compose pull
docker compose up -d
```

Event type files (`config/event-types/*.yaml`) that existed before the upgrade
are preserved; new built-in types are added alongside them. Customer-created
event types are not touched.

### Backup & restore

```bash
scripts/backup.sh    # dumps MongoDB + configs to ./backups/YYYY-MM-DD/
scripts/restore.sh ./backups/2026-04-24/
```

*(`backup.sh` / `restore.sh` land in the next sprint.)*
