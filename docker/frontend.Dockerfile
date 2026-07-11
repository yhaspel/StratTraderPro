# ---------- Stage 1: Build Angular ----------
FROM node:20-alpine AS builder

WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml* frontend/package-lock.json* ./
RUN corepack enable && \
    ([ -f pnpm-lock.yaml ] && pnpm install --frozen-lockfile || npm ci)

COPY frontend/ .
RUN npm run build -- --configuration production

# ---------- Stage 2: Serve with nginx ----------
FROM nginx:1.27-alpine

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
ENV NGINX_ENVSUBST_FILTER='^(BACKEND_URL|GRAFANA_URL|SENTRY_DSN|SENTRY_ENVIRONMENT|RELEASE)$' \
    BACKEND_URL='http://backend:8777'

COPY --from=builder /app/dist/strattraderpro/browser /usr/share/nginx/html

EXPOSE 80

# Use the upstream entrypoint (handles envsubst then exec's nginx -g 'daemon off;')
