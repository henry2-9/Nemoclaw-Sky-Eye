# syntax=docker/dockerfile:1.7
# =============================================================================
# Sentinel Appliance — openclaw agent + sentinel-tools container
#
# Bundles:
#   • openclaw gateway (LINE / Telegram providers, agent runtime)
#   • sentinel-tools CLI scripts (event-query, video-ingest, perception-client, ...)
#   • Python 3 + ffmpeg + the libs the tools depend on
#
# Multi-arch: ships for linux/amd64 (BYO x86 GPU host) and linux/arm64 (GB10
# appliance). All runtime dependencies are pure-python or have official ARM
# wheels.
# =============================================================================

FROM node:22-bookworm

ARG OPENCLAW_VERSION=2026.3.24

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_NO_CACHE_DIR=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

# ---- 1. system deps -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ffmpeg curl jq ca-certificates gettext-base tini \
    && rm -rf /var/lib/apt/lists/*

# ---- 2. openclaw gateway --------------------------------------------------
# Pinned to OPENCLAW_VERSION for reproducibility. Bumping must happen via the
# CI release pipeline (smoke test against this stack), not silently.
RUN npm install -g openclaw@${OPENCLAW_VERSION} \
    && openclaw --version

# ---- 3. python deps for sentinel-tools ----------------------------------------
# Pinned to broad ranges; the inner stack is small and stable. opencv-python-
# headless avoids pulling X11 just for cv2.imread / cv2.imwrite.
RUN python3 -m pip install \
        "pymongo>=4.7,<5" \
        "pillow>=10,<12" \
        "reportlab>=4.0,<5" \
        "requests>=2.31,<3" \
        "opencv-python-headless>=4.10,<5" \
        "PyYAML>=6.0,<7" \
        "jsonschema>=4.20,<5"

# ---- 4. sentinel-tools ---------------------------------------------------------
COPY tools/ /opt/sentinel-tools/
RUN chmod +x /opt/sentinel-tools/sentinel-* 2>/dev/null || true

ENV PATH="/opt/sentinel-tools:${PATH}"

# ---- 5. layout ------------------------------------------------------------
RUN mkdir -p /config /state /data /state/openclaw /state/sessions /state/memory

# ---- 6. entrypoint --------------------------------------------------------
# Build context is the repo root, so the entrypoint lives under images/openclaw/.
COPY images/openclaw/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /state
EXPOSE 18789
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:18789/__openclaw__/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["openclaw", "gateway", "--foreground"]
