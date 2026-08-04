# ---------- Stage 1: Build Angular ----------
FROM node:24-alpine AS builder

WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml* frontend/package-lock.json* ./
RUN corepack enable && \
    ([ -f pnpm-lock.yaml ] && pnpm install --frozen-lockfile || npm ci)

COPY frontend/ .
RUN npm run build -- --configuration production

# ---------- Stage 2: Serve with nginx ----------
FROM nginx:1.30-alpine

# Drop the stock default site so our template wins
RUN rm /etc/nginx/conf.d/default.conf

# Place the config as a TEMPLATE; the official nginx image's docker-entrypoint
# script will envsubst /etc/nginx/templates/*.template → /etc/nginx/conf.d/ at
# container start.
#
# NGINX_ENVSUBST_FILTER is an ANCHORED ALLOWLIST. It must be narrow enough that
# nginx's own $vars ($uri, $host, $remote_addr, ...) pass through untouched, but
# it must list EVERY ${VAR} the template emits — anything missing is shipped to
# the browser as the literal string "${FOO}".
#
# BUG-004: this was '^BACKEND_URL$' while the template emitted five vars, so the
# SPA was served sentryDsn: '${SENTRY_DSN}' and frontend Sentry never reported a
# single event. scripts/check_envsubst_filter.py now cross-checks this list
# against the template in CI, so the two cannot drift apart again.
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
#
# WS_URL is the daphne (SERVICE_ROLE=ws) origin for the /ws/ proxy. It carries a
# compose-shaped default for the same reason BACKEND_URL does: `proxy_pass ;`
# with an empty value is a config-parse error, so nginx would refuse to start
# rather than merely losing the websocket. On Railway, override it with the ws
# service's PUBLIC url.
ENV NGINX_ENVSUBST_FILTER='^(BACKEND_URL|GRAFANA_URL|SENTRY_DSN|SENTRY_ENVIRONMENT|RELEASE|WS_URL)$' \
    BACKEND_URL='http://backend:8777' \
    WS_URL='http://ws:8788'

# BUG-003 — default RELEASE from the platform's commit SHA, so Sentry events carry
# a release and the sourcemaps CI uploads under $GITHUB_SHA can actually match.
#
# Three things are load-bearing here:
#   - `.envsh` extension: the entrypoint SOURCES those, so the export survives.
#     A plain `.sh` is executed in a subshell and its exports would be lost.
#   - sorts before `20-envsubst-on-templates.sh`, which renders the template.
#   - MUST be EXECUTABLE: the entrypoint skips non-executable files outright
#     ("Ignoring $f, not executable") — it would fail silently, which is exactly
#     the class of bug this repo keeps getting bitten by. chmod is explicit rather
#     than trusting the git file mode to survive the checkout.
COPY docker/15-release-default.envsh /docker-entrypoint.d/15-release-default.envsh
RUN chmod +x /docker-entrypoint.d/15-release-default.envsh

COPY --from=builder /app/dist/strattraderpro/browser /usr/share/nginx/html

# M11 perf follow-up (AC-11-12) — PRE-COMPRESS the static bundle at build time.
#
# nginx's `gzip on` compresses on the fly at `gzip_comp_level` which DEFAULTS TO 1
# — the weakest setting. That is what production was serving: main.js came down at
# 47,990 B when the same bytes at gzip -9 are 41,228 B. Across the initial payload
# that is 168.2 kB vs 144.3 kB — ~0.12 s of pure transfer on a Slow-4G link, paid
# on every cold load, for nothing.
#
# Compressing here (once, at build) instead of per-request means we can afford -9
# and nginx spends ZERO CPU on it: `gzip_static on` just serves the .gz next to the
# original. Clients that don't send Accept-Encoding: gzip still get the plain file.
#
# Brotli was measured and REJECTED: brotli-11 gives 128.2 kB vs gzip-9's 144.3 kB —
# only ~0.08 s more — and the official nginx image ships no ngx_brotli, so it would
# mean swapping the base image and losing the upstream entrypoint's envsubst step.
# That step is load-bearing (BUG-004: a broken NGINX_ENVSUBST_FILTER served the SPA
# a literal "${SENTRY_DSN}" and Sentry silently no-op'd) and is CI-guarded. Trading
# that for 80 ms is a bad deal. Revisit in M14, where the serving layer is already
# being touched for prerendering.
#
# -k keeps the original (nginx needs BOTH files present).
RUN find /usr/share/nginx/html \
      -type f \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.svg' -o -name '*.json' \) \
      -size +256c \
      -exec gzip -9 -k -f {} \; \
 && echo "pre-compressed $(find /usr/share/nginx/html -name '*.gz' | wc -l) assets"

EXPOSE 80

# Use the upstream entrypoint (handles envsubst then exec's nginx -g 'daemon off;')
