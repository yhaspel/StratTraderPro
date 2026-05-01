# Grafana Agent — Railway sidecar

Scrapes `/metrics` from the `backend` service over Railway's private network and
remote-writes to Grafana Cloud Hosted Prometheus.

## Files
- `agent.yaml` — scrape + remote_write config (env-var placeholders expanded at start).
- `Dockerfile` — pins `grafana/agent:v0.43.4` and bakes the config in.

## Required Railway env vars (per environment)
| Var | Source | Example |
|-----|--------|---------|
| `GRAFANA_PROM_URL` | grafana-setup.md §0 item 2 | `https://prometheus-prod-58-prod-eu-central-0.grafana.net/api/prom/push` |
| `GRAFANA_PROM_USER` | grafana-setup.md §0 item 3 | `3164090` |
| `GRAFANA_PROM_TOKEN` | grafana-setup.md §0 item 4 | `glc_…` |
| `BACKEND_TARGET` | Railway internal DNS of the API service in the same env | `backend.railway.internal:8777` |
| `RAILWAY_ENVIRONMENT_NAME` | Auto-injected by Railway | `staging` / `production` |

## Railway service settings
- **Builder:** Dockerfile
- **Root directory:** `/infra/grafana-agent`
- **Dockerfile path:** `Dockerfile`
- **Healthcheck path:** `/-/ready` on port `12345`

## Verify it's working
1. Railway logs for the `grafana-agent` service should show
   `level=info component=remote_write msg="Done replaying WAL"` then periodic
   `successful write` messages.
2. In Grafana Cloud → Explore → Prometheus, query `up{service="backend"}` —
   should return `1`.
3. Then `auth_login_total` (and the other auth_* counters) should appear once
   the backend has served any auth traffic.
