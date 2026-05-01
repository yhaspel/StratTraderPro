# Grafana Cloud Setup — Auth Health Dashboard

> **Phase:** M01 (Auth Foundation) — exit-gate item 01.11.5
> **Owner:** @yuval3000 (manual)
> **Time:** ~30–45 min
> **Outcome:** A live **Auth Health** dashboard in Grafana Cloud scraping Prometheus metrics from the Railway-staging backend, with three alerts wired up.

---

## 0. What I need from you to finish this phase

Please collect / decide the following and paste them back into the chat (or save them in a local secrets file). I cannot complete M01 without these:

| # | Item | Where to get it | Stored as |
|---|------|------------------|-----------|
| 1 | Grafana Cloud account email + org slug | grafana.com signup → org URL e.g. `https://yuval3000.grafana.net` | — |
| 2 | Grafana Cloud **Prometheus remote_write** endpoint URL | Grafana Cloud → *Connections → Prometheus → Send Metrics* | env: `GRAFANA_PROM_URL` |
| 3 | Grafana Cloud **Prometheus username** (numeric instance ID) | Same page as #2 | env: `GRAFANA_PROM_USER` |
| 4 | Grafana Cloud **API token** (scope: `MetricsPublisher`) | Grafana Cloud → *Security → Access Policies → Add token* | env: `GRAFANA_PROM_TOKEN` (GitHub Actions secret + Railway service var) |
| 5 | Notification target for alerts (email / Slack webhook / PagerDuty key) | Your choice | Configured inside Grafana UI |
| 6 | Confirmation that Railway staging is up and `/metrics` returns 200 | `curl https://api-staging.strattraderpro.com/metrics` | — |

Once you give me items **1–5**, I can hand you a ready-to-import dashboard JSON and the exact `prometheus.yml` / Railway env-var diff. Item 6 is a precondition — if staging isn't deployed yet, finish M00.9.3 / M00.9.7 first.

---

## 1. Prerequisites checklist

- [ ] Railway staging running (`backend` service healthy, `/healthz` 200).
- [ ] Backend exposes `/metrics` (django-prometheus — already wired in M00.7.2).
- [ ] The four custom auth metrics are emitted. **Verify** by curl-ing staging `/metrics` and grepping for:
  - `auth_login_total`
  - `auth_refresh_total`
  - `auth_family_revocations_total`
  - `auth_password_reset_total`

  If any are missing, that's a code gap — tell me and I'll add the `Counter()` definitions in `apps/users/metrics.py` and increment them in the corresponding views.

---

## 2. Create the Grafana Cloud account

1. Go to https://grafana.com/auth/sign-up/create-user.
2. Sign up with `yuval3000@gmail.com`. Pick the **Free** tier (10k active series, 50 GB logs — plenty for staging).
3. Choose a stack name, e.g. `strattraderpro`. Your stack URL becomes `https://strattraderpro.grafana.net`.
4. From *Home → Connections → Add new connection → Hosted Prometheus metrics*, copy:
   - **Remote write endpoint** (`https://prometheus-prod-XX-prod-XX-XXXXX.grafana.net/api/prom/push`)
   - **Username** (a numeric instance ID)
   - Click **Generate now** to mint an API token with the `MetricsPublisher` role; copy it (shown once).

Save these three values — they are items 2/3/4 above.

---

## 3. Wire Railway → Grafana Cloud

We push metrics from the Railway-hosted backend to Grafana via Prometheus remote_write. Two options; pick **A** unless you have reasons to prefer **B**.

### Option A — Grafana Agent sidecar (recommended)

1. Add a new Railway service `grafana-agent` from the Docker image `grafana/agent:latest`.
2. Mount the following config (paste into Railway as a file or as `AGENT_CONFIG_CONTENT`):

   ```yaml
   server:
     log_level: info
   metrics:
     global:
       scrape_interval: 30s
       remote_write:
         - url: ${GRAFANA_PROM_URL}
           basic_auth:
             username: ${GRAFANA_PROM_USER}
             password: ${GRAFANA_PROM_TOKEN}
     configs:
       - name: strattraderpro-staging
         scrape_configs:
           - job_name: backend
             static_configs:
               - targets: ['backend.railway.internal:8000']
             metrics_path: /metrics
   ```

3. Set `GRAFANA_PROM_URL`, `GRAFANA_PROM_USER`, `GRAFANA_PROM_TOKEN` as Railway service variables.
4. Redeploy. Watch `grafana-agent` logs — you should see `level=info component=remote_write msg="successful write"` within 60s.

### Option B — Push directly from Django

Add `prometheus_client.exposition.push_to_gateway(...)` on a Celery beat schedule. Simpler infra but couples the app to the metrics backend; not recommended.

---

## 4. Import the Auth Health dashboard

> I'll generate the dashboard JSON once you confirm Section 3 is live and `auth_login_total` shows up under *Explore → Prometheus*. The dashboard will contain four panels and three alerts:

| Panel | Query | Alert |
|-------|-------|-------|
| Login success rate (5 min) | `sum(rate(auth_login_total{result="ok"}[5m])) / sum(rate(auth_login_total[5m]))` | < 0.95 for 5 min → **warning** |
| Login outcomes (stacked) | `sum by (result) (rate(auth_login_total[1m]))` | — |
| Refresh family revocations | `increase(auth_family_revocations_total[1h])` | > 5/h → **critical** (possible token theft) |
| Rate-limit hits | `sum by (endpoint) (rate(django_http_responses_total_by_status_view_method_total{status="429"}[5m]))` | spike > 10× baseline → **warning** |

Steps once metrics are flowing:
1. Grafana → *Dashboards → New → Import* → paste JSON I provide.
2. Pick the Prometheus datasource Grafana auto-created (`grafanacloud-strattraderpro-prom`).
3. *Alerting → Contact points → New* — add the channel from item 5 above.
4. *Alerting → Notification policies* — route `severity=critical` to your channel; warnings to email.

---

## 5. Verification (closes 01.11.5)

- [ ] Dashboard loads with non-zero data on all four panels (generate traffic by running the E2E suite against staging).
- [ ] Trigger the family-revocation alert by re-using a rotated refresh token via `curl`; confirm alert fires within 5 min.
- [ ] Screenshot dashboard + alert into the M01 exit-gate evidence folder.
- [ ] Mark `01.11.5` ✅ in `project-plan/plan-progress-tracker.md`.
- [ ] Tag `v0.1.0-auth` (closes `01.11.8`).

---

## 6. Troubleshooting

- **No data in Grafana**: check `grafana-agent` logs for 401 (token wrong) or 404 (URL wrong). Confirm `/metrics` is reachable from the agent service via Railway internal DNS.
- **Metrics present but `auth_*` missing**: code gap — the `Counter` isn't being incremented in the view. Ping me with the metric name and I'll patch it.
- **Free-tier quota warnings**: drop scrape_interval to 60s and remove default `python_*` metrics via `metric_relabel_configs` drop rules.
