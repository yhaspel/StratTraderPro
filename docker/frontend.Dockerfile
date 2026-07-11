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

EXPOSE 80

# Use the upstream entrypoint (handles envsubst then exec's nginx -g 'daemon off;')
