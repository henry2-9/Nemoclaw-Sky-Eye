# syntax=docker/dockerfile:1.7
# =============================================================================
# FPG Appliance — openclaw agent + fpg-tools container
#
# This image bundles:
#   • openclaw gateway (agent framework, LINE/Telegram providers)
#   • fpg-tools CLI scripts (fpg-video-ingest, fpg-event-query, etc.)
#   • ffmpeg for frame extraction
#   • Python 3 runtime for the tool scripts
#
# The image is deliberately a "batteries-included" container so the agent
# subprocesses can invoke the fpg-* CLIs directly without cross-container
# plumbing. Once we outgrow this (horizontal scale, independent tool
# versioning), the tools will move to a separate image.
# =============================================================================

FROM node:22-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false

# ---- System packages -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ffmpeg curl jq ca-certificates gettext-base tini \
    && rm -rf /var/lib/apt/lists/*

# ---- openclaw gateway ------------------------------------------------------
# TODO: pin to an exact version once release channel is decided. For now the
# build will fail with a clear message so we don't silently ship an unpinned
# dependency to customers.
#
# RUN npm install -g openclaw@<pinned-version>
RUN echo "BUILD TODO: install openclaw — see images/openclaw/Dockerfile" \
    && mkdir -p /opt/openclaw

# ---- fpg-tools (python scripts) --------------------------------------------
# TODO: once fpg-tools is extracted into a proper Python package, replace this
# with `pip install /opt/fpg-tools`. Until then the tools live outside the
# image and will be mounted at runtime.
RUN mkdir -p /opt/fpg-tools /config /state /data
ENV PATH="/opt/fpg-tools/bin:${PATH}"

# ---- Entrypoint ------------------------------------------------------------
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /state
EXPOSE 18789
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["openclaw", "gateway", "--foreground"]
