# syntax=docker/dockerfile:1.7
# =============================================================================
# falcon-perception — TII Falcon Perception VLM as a long-running HTTP service.
#
# Upstream: https://github.com/tiiuae/Falcon-Perception   (Apache-2.0)
# Pinned to a specific git ref so builds are reproducible. Bump FP_GIT_REF
# when upgrading; review upstream CHANGELOG for breaking inference-engine
# changes before bumping.
#
# Runtime
# -------
#   • Loads the Falcon-Perception model into GPU once at startup.
#   • Exposes POST /infer on port 18793 (BaseHTTPRequestHandler-based).
#   • Single-GPU; serializes requests via an internal threading.Lock.
#
# Multi-arch
# ----------
#   The NVIDIA CUDA base image publishes both linux/amd64 (BYO x86 GPU) and
#   linux/arm64 (GB10 / Grace Blackwell appliance). PyTorch 2.11 + cu130 is
#   pulled from the official PyTorch index for whichever arch is built.
# =============================================================================

ARG CUDA_TAG=13.0.0-cudnn-runtime-ubuntu24.04
FROM nvidia/cuda:${CUDA_TAG}

ARG FP_GIT_REPO=https://github.com/tiiuae/Falcon-Perception.git
ARG FP_GIT_REF=v1.0.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_ENABLE_HF_TRANSFER=1

# ---- system deps ----------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv python3-dev \
        git curl ca-certificates tini \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ---- Falcon-Perception source ---------------------------------------------
WORKDIR /opt
RUN git clone --depth 1 --branch ${FP_GIT_REF} ${FP_GIT_REPO} /opt/falcon-perception \
    || (git clone ${FP_GIT_REPO} /opt/falcon-perception && \
        git -C /opt/falcon-perception checkout ${FP_GIT_REF})

# ---- python deps ----------------------------------------------------------
# Install PyTorch 2.11 + cu130 from official index, then Falcon-Perception
# itself. Done in two steps so torch isn't pulled from the wrong index.
#
# Note: we do NOT upgrade pip — Ubuntu's apt-installed python3-pip lacks the
# RECORD file pip needs to uninstall itself, so `pip install --upgrade pip`
# fails with "Cannot uninstall pip 24.0" on this base image. System pip 24
# resolves the wheel URLs we need just fine.
RUN python3 -m pip install \
        --index-url https://download.pytorch.org/whl/cu130 \
        torch==2.11.0 torchvision==0.26.0 \
    && python3 -m pip install -e /opt/falcon-perception

# ---- runtime --------------------------------------------------------------
WORKDIR /opt/falcon-perception
EXPOSE 18793
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=10 \
    CMD curl -fsS http://localhost:18793/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "/opt/falcon-perception/falcon_perception_server.py"]
