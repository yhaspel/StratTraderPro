# ---------- Stage 1: Build Angular ----------
FROM node:25-alpine AS builder

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
# container start. Limit substitution to BACKEND_URL so nginx's own $vars
# ($uri, $host, $remote_addr, ...) pass through untouched.
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER='^BACKEND_URL$' \
    BACKEND_URL='http://backend:8777'

COPY --from=builder /app/dist/strattraderpro/browser /usr/share/nginx/html

EXPOSE 80

# Use the upstream entrypoint (handles envsubst then exec's nginx -g 'daemon off;')
