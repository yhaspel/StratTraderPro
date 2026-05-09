# IB Gateway sidecar — M04 Day-1 SPIKE
#
# Status: throwaway-or-promote. Validates that headless IB Gateway + IBC can
# run on Railway and accept ib_insync connections from a sibling service.
# See docs/adr/040-ibkr-gateway-sidecar.md for the four assumptions this is
# trying to prove. NOT production-shaped:
#   - Single static credential set via env (per-user pool is M04 §6.2 work)
#   - VNC port exposed for debugging (gated by DEBUG_VNC=1; remove in prod)
#   - Pinned IB Gateway + IBC versions (refresh manually until promoted)
#
# Build args can be overridden in docker-compose or `docker build --build-arg`.

FROM eclipse-temurin:17-jre-jammy

# Pinned versions. IBKR resets the "stable" channel periodically; if a build
# breaks because the installer URL 404s, bump IB_GATEWAY_CHANNEL to "latest"
# or hardcode a known-good version (look at the gnzsnz/ib-gateway tags for
# what's currently working in the wild).
ARG IB_GATEWAY_CHANNEL=stable
ARG IBC_VERSION=3.20.0

# 4002 = paper API, 4001 = live API. M04 is paper-only; the spike runs paper.
ENV TWS_PORT=4002 \
    DISPLAY=:1 \
    IBC_PATH=/opt/ibc \
    TWS_PATH=/root/Jts \
    LOG_PATH=/var/log/ibc \
    TRADING_MODE=paper \
    DEBUG_VNC=0

# System deps:
#   xvfb           — IB Gateway is a Swing GUI even in "Gateway" mode; it
#                    needs an X server to render to (off-screen)
#   x11vnc         — optional debug surface, gated by DEBUG_VNC=1
#   xdpyinfo       — entrypoint waits on X readiness with this
#   netcat-openbsd — Docker HEALTHCHECK uses `nc -z` to probe TWS_PORT
#   libx*          — Swing's runtime dependencies that the JRE base lacks
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
        xvfb \
        x11vnc \
        x11-utils \
        netcat-openbsd \
        libxext6 \
        libxrender1 \
        libxtst6 \
        libxi6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/install

# IB Gateway installer — IBKR forbids redistribution of the installer in
# images, so we fetch at build time from their CDN. The installer is a
# self-extracting shell script that runs an InstallAnywhere wizard; we feed
# it stdin "n" answers to skip the optional Java bundle (we have one) and
# the post-install launch (we don't want it running during build).
RUN curl -fsSL -o ibgateway.sh \
        "https://download2.interactivebrokers.com/installers/ibgateway/${IB_GATEWAY_CHANNEL}-standalone/ibgateway-${IB_GATEWAY_CHANNEL}-standalone-linux-x64.sh" \
    && chmod +x ibgateway.sh \
    && yes n | ./ibgateway.sh -q -dir "${TWS_PATH}" \
    && rm ibgateway.sh

# IBC — handles the headless login + session keepalive that vanilla IB
# Gateway can't do on its own.
RUN mkdir -p "${IBC_PATH}" "${LOG_PATH}" \
    && curl -fsSL -o ibc.zip \
        "https://github.com/IbcAlpha/IBC/releases/download/${IBC_VERSION}/IBCLinux-${IBC_VERSION}.zip" \
    && unzip -q ibc.zip -d "${IBC_PATH}" \
    && chmod +x "${IBC_PATH}"/*.sh "${IBC_PATH}"/scripts/*.sh \
    && rm ibc.zip

WORKDIR /

COPY docker/ib-gateway/ibc-config.ini ${IBC_PATH}/config.ini.template
COPY docker/ib-gateway/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 4002 = paper API (the only port the broker adapter will talk to)
# 5900 = VNC, only useful when DEBUG_VNC=1
EXPOSE 4002 5900

# Cold start observed in dev: 60–120s (JVM warmup + login + API init). Give
# the orchestrator a generous start_period so it doesn't kill us during boot.
# The probe itself is cheap: a TCP connect on TWS_PORT.
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=3 \
    CMD nc -z localhost ${TWS_PORT} || exit 1

ENTRYPOINT ["/entrypoint.sh"]
