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

| Component | Minimum | Recommended |
|---|---|---|
| CPU | x86_64 with AVX2 or ARM64 v8.2 | 8+ cores |
| GPU | NVIDIA, 24 GB VRAM | 48 GB VRAM (full-context sessions) |
| RAM | 32 GB | 64 GB |
| Storage | 200 GB (OS + model + 30 days of event data) | 1 TB NVMe |
| OS | Ubuntu 22.04 LTS or 24.04 LTS | 24.04 LTS |

### Software prerequisites

```bash
# Docker + Compose v2
curl -fsSL https://get.docker.com | sh

# NVIDIA container toolkit
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
```

### Steps

```bash
git clone http://192.168.0.12:3000/Henry/Security-AI-Agent.git
cd Security-AI-Agent

cp .env.example .env
# Fill in MONGO_*, LINE_*, CLOUDFLARE_TUNNEL_TOKEN, VLM_MODEL_FILENAME

mkdir -p models
# Put your Qwen3.6-35B-A3B GGUF (or equivalent) file here.

docker compose pull
docker compose up -d

docker compose ps
docker compose logs -f openclaw
```

### Verifying

- `docker compose ps` → all services `healthy`/`running`
- `curl -fsS http://localhost:8080/health` (from inside llama-server container)
- Cloudflare Tunnel dashboard → status `HEALTHY`
- Send a LINE message → see matching entry in `docker compose logs openclaw`

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
