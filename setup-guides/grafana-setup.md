# Grafana Cloud Setup — Auth Health Dashboard

> **Phase:** M01 (Auth Foundation) — exit-gate item 01.11.5
> **Owner:** @yuval3000 (manual)
> **Time:** ~30–45 min
> **Outcome:** A live **Auth Health** dashboard in Grafana Cloud scraping Prometheus metrics from the Railway-staging backend, with three alerts wired up.
>
> **Status (2026-05-01):** Sections 0–3 complete. Pipeline verified: `up{service="backend"}` returns `1` in Grafana Cloud Explore (datasource `grafanacloud-yuval3000-prom`). Section 4 (dashboard import) and Section 5 (alert verification) outstanding.

## Deployed configuration (cheatsheet)

| | Actual | Notes |
|---|---|---|
| Grafana stack slug | `yuval3000` | Auto-generated from email; the guide's example "strattraderpro" was never created. Datasource is therefore `grafanacloud-yuval3000-prom`. |
| Region | `prod-eu-central-0` | Affects remote_write URL only; query latency from us-east4 backend → eu-central-0 cloud is acceptable for 30s scrapes. |
| API token name | `strattraderpro-staging` | No expiry. Stored locally in `.env.grafana.local` (gitignored). |
| API token scope | `set:alloy-data-write` | Replaces the old `MetricsPublisher` role; superset that covers Prometheus write. |
| Collector | Grafana **Agent** v0.43.4 (static, YAML) | Image: `grafana/agent:v0.43.4`. Alloy migration deferred. |
| Collector path on Railway | service `grafana-agent`, root `/infra/grafana-agent` | See `infra/grafana-agent/README.md` for env vars. |
| Backend scrape target | `backend.railway.internal:8000` | Internal DNS, port = backend's `PORT` env var. |
| Backend `ALLOWED_HOSTS` | must include `backend.railway.internal` | Without it Django returns 400 to the agent and `up=0`. **This is not in the upstream Railway docs.** |

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
| 6 | Confirmation that Railway staging is up and `/metrics` returns 200 | ✅ `curl https://backend-staging-4b6d.up.railway.app/metrics` (custom domain not yet wired) | — |

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

### Option A — Grafana Agent sidecar (recommended) ✅ deployed

1. ✅ Service `grafana-agent` deployed on Railway from this repo, root directory `/infra/grafana-agent`. Pinned image `grafana/agent:v0.43.4` (not `:latest` — locks against Grafana's pending Alloy migration). Config and Dockerfile live in-repo; see `infra/grafana-agent/README.md`.
2. ✅ Config matches what's at `infra/grafana-agent/agent.yaml`. Includes `metric_relabel_configs` to drop `python_gc_*` to stay inside the free-tier active-series quota.
3. ✅ Env vars set on the Railway service (per environment): `GRAFANA_PROM_URL`, `GRAFANA_PROM_USER`, `GRAFANA_PROM_TOKEN`, `BACKEND_TARGET=${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000`, `PORT=12345`. The agent's HTTP server is bound to `$PORT` so Railway's healthcheck can reach `/-/ready` on it.
4. ✅ Verified in Grafana Cloud Explore: `up{service="backend"} == 1` after the backend's `ALLOWED_HOSTS` was updated to include `backend.railway.internal` (without that, Django responds 400 to the agent and `up` stays at 0).

**Gotchas encountered during this rollout** (worth keeping for the production duplicate later):

- `grafana/agent:v0.40+` renamed `/bin/agent` → `/bin/grafana-agent`. The image's default ENTRYPOINT works; an explicit `ENTRYPOINT ["/bin/agent"]` in your Dockerfile fails with `executable file not found`.
- The static Grafana Agent does **not** log "successful write" at info level — silence is success. Filter logs for `error` and look for none, or query `up{}` in Grafana to confirm scrapes are succeeding.
- Backend's gunicorn must run an **ASGI** app (`config.asgi:application`) when paired with `uvicorn.workers.UvicornWorker`. Pointing it at `config.wsgi:application` returns 500 on every request: `WSGIHandler.__call__() missing 1 required positional argument: 'start_response'`.

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
