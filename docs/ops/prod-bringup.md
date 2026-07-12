# Runbook — Production bring-up on Railway (`strattraderpro-prod` + Cloudflare)

**Owner:** Yuval / platform on-call
**Last reviewed:** 2026-07-12 (M11 §7.9)
**Status:** `[LIVE]` / operator — the autonomous run delivers *this runbook*, not the live environment.
**Gated by:** AC-11-10 [LIVE] (also depends on AC-11-15 [LIVE] — the `SERVICE_ROLE` cutover).
**Companion:** `docs/ops/service-role-cutover.md` (SERVICE_ROLE mapping + Custom-Start-Command deletion), `docs/runbooks/prod-bootstrap.md` (the M02 duplicate-staging bootstrap this supersedes for a *separate* project), `docs/runbooks/worker-metrics-scrape.md` (exporter + task-metrics targets), `docs/runbooks/staging-deploy.md` (the redirect-loop / `version: unknown` traps), `infra/grafana-agent/README.md`, `docs/adr/002-railway-hosting.md`, `docs/adr/103-service-role-dispatch.md`.

## What this is (read first)

This stands up the **first real internet-facing production environment** for
StratTraderPro: a **separate `strattraderpro-prod` Railway project** (not a new
*environment* inside the staging project — a new **project**, so a fat-fingered
staging action can never touch prod data), fronted by **Cloudflare** on the
registered domain `strattraderpro.com`.

Three facts frame every step below:

1. **Paper-trading only.** `ENABLE_LIVE_TRADING=false` stays off — this brings up a
   real *platform*, not real *money*. Alpaca **paper** is the only live-path broker;
   TradeStation is behind `BROKER_ALPACA_ENABLED`-style flags and stays OFF. Do **not**
   set any TradeStation live credentials here.
2. **The service set is 12, not "6."** Earlier docs (and the M02 `prod-bootstrap.md`)
   describe a 4–7 service staging shape. The real target set — derived from
   `docker-compose.yml` + `infra/grafana-agent/` + M10's exporters — is larger. Standing
   up prod is deliberately operator-heavy. See the table in §2.
3. **`SERVICE_ROLE` is load-bearing.** Every backend-image service must set
   `SERVICE_ROLE` and carry **no** Custom Start Command. This is not optional polish —
   it is the entire point of M11 §7.0 / BUG-011 (`celery-worker` and `celery-beat`
   silently ran a *second web server* for two months because the start-command box was
   blank). The image now **crashes loudly** on a missing role instead of impersonating
   the web tier. The exact per-service mapping lives in
   **`docs/ops/service-role-cutover.md`** — follow it; do not re-derive it here.

Steps tagged **[OPERATOR]** need a human with an account/credential/payment method and
cannot be done by the autonomous run. Everything else is mechanical Railway/Cloudflare
config.

## 0. Prerequisites (gather before you start)

- **[OPERATOR] Domain:** ability to purchase `strattraderpro.com` (§1).
- **[OPERATOR] Cloudflare account** (free/Pro tier is sufficient — WAF managed rules,
  rate-limiting rules, Bot Fight Mode) (§4).
- **[OPERATOR] Cloudflare R2 bucket** for GDPR exports + weekly `pg_dump` offload (§5).
- Railway account with billing enabled (a prod project on the free trial will sleep).
- Grafana Cloud workspace (already live from M10 — 6 dashboards, 21 rules, all targets
  `up`; you are *adding a production env*, not building the stack).
- Sentry project (prod events tag `environment=production` automatically via
  `RAILWAY_ENVIRONMENT_NAME`).
- Alpaca **paper** API key id + secret for the prod env.
- Resend (Anymail) API key for transactional email.
- A password manager open — you will generate three prod-only secrets you must not lose.

## 1. Register the domain — **[OPERATOR]**

1. Purchase `strattraderpro.com` at a registrar (Cloudflare Registrar is simplest since
   Cloudflare will be the DNS provider anyway; any registrar works).
2. If you did **not** buy through Cloudflare, add the domain to Cloudflare as a site
   (§4.1) and change the registrar's nameservers to the two Cloudflare assigns. Wait for
   Cloudflare to report the zone **Active** (minutes–hours) before doing DNS in §3.

## 2. Create the `strattraderpro-prod` Railway project + all 12 services

> Use a **new project**, not a `production` environment in the staging project. Isolation
> is non-negotiable for prod. (The M02 `prod-bootstrap.md` "Duplicate Environment" flow
> was for a same-project mirror; here we build a clean project.)

### 2.1 Create the project and the two managed data stores

1. Railway → **New Project** → name it `strattraderpro-prod`.
2. **+ New** → **Database** → **Add PostgreSQL** → gives `DATABASE_URL` via
   `${{Postgres.DATABASE_URL}}`. This is a **fresh, empty** prod DB — separate from
   staging.
3. **+ New** → **Database** → **Add Redis** → gives `REDIS_URL` via
   `${{Redis.REDIS_URL}}`.

### 2.2 Create the ten application services

Add each service below. The six **backend-image** services deploy from this repo
(`docker/backend.Dockerfile`); they are **identical images** distinguished only by
`SERVICE_ROLE`. `grafana-agent` builds from `/infra/grafana-agent` (it is **not** a
compose service). `frontend`, `postgres-exporter`, `redis-exporter` use public images.

| # | Railway service | Image / source | `SERVICE_ROLE` | Custom Start Command | Notes |
|---|---|---|---|---|---|
| 1 | `backend` | this repo, `docker/backend.Dockerfile` | **`web`** | **delete it** | gunicorn WSGI. **Never `web-dev`** — that role refuses to boot in a deployed env. |
| 2 | `celery-worker` | same image | `worker` | **delete it** | default `celery` queue; GDPR export job runs here. |
| 3 | `worker-backtest` | same image | `worker-backtest` | **delete it** | `backtest` queue; must exist or prod backtests sit `QUEUED` forever. |
| 4 | `celery-beat` | same image | `beat` | **delete it** | redbeat scheduler; nightly anonymize + weekly `pg_dump` fire here. |
| 5 | `streams` | same image | `streams` | **delete it** | `run_broker_streams` (Alpaca `trade_updates`). |
| 6 | `ws` | same image | `ws` | **delete it** | daphne ASGI, `/ws/dashboard/`. Binds Railway's injected `$PORT` — no `PORT` override needed on Railway. |
| 7 | `frontend` | nginx image (Angular SPA build) | — | (its own) | proxies `/api/*` → backend via `BACKEND_URL`. Not a `SERVICE_ROLE` service. |
| 8 | `grafana-agent` | build from `/infra/grafana-agent` | — | (Dockerfile) | Root dir `/infra/grafana-agent`, healthcheck `/-/ready` :12345. |
| 9 | `postgres-exporter` | `prometheuscommunity/postgres-exporter` | — | — | exposes `:9187`. |
| 10 | `redis-exporter` | `oliver006/redis_exporter` | — | — | exposes `:9121`. |

Combined with **Postgres** and **Redis** from §2.1 that is the **12-service** target set:
`backend, celery-worker, worker-backtest, celery-beat, streams, ws, frontend,
postgres, redis, grafana-agent, postgres-exporter, redis-exporter`.

### 2.3 Set `SERVICE_ROLE` and delete every Custom Start Command — **follow `service-role-cutover.md`**

For each of the six backend-image services (rows 1–6):

1. **Variables** → add `SERVICE_ROLE=<role>` exactly per the table above (and the mapping
   table in **`docs/ops/service-role-cutover.md`** — it is the authoritative source).
2. **Settings → Deploy → Custom Start Command** → **clear it and save.** The image `CMD`
   (the `docker/entrypoint.sh` dispatcher) now runs.
3. Redeploy.

If a service crash-loops with `entrypoint: FATAL: SERVICE_ROLE is unset`, the env var did
not save — re-add it. **That crash is the design working: loud, not silent.** Do the full
staging-first cutover in `service-role-cutover.md`; on a brand-new prod project there is no
staging step to repeat, but the same end-to-end verification (§7 here) applies.

### 2.4 Generate the three prod-only secrets — **[OPERATOR]**

In a terminal you trust (do **not** paste output into chat/tickets):

```bash
# SECRET_KEY (Django) and, ideally, a DISTINCT JWT signing key.
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # run TWICE — one SECRET_KEY, one JWT_SIGNING_KEY
# FERNET_KEK — 32 random bytes, url-safe base64 (wraps every MFA secret + broker key + webhook sig).
python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Store all three in your password manager. **Lose `FERNET_KEK` and every prod MFA secret /
broker key / webhook `sig` becomes undecryptable** (`docs/runbooks/mfa-kek-rotation.md`).
`prod.py` fails the boot if `SECRET_KEY` / `FERNET_KEK` are unset or left at the insecure
dev default — that is intentional (fail closed).

## 3. DNS — custom domains for `api.` / `app.` / (optional) `hooks.`

Railway gives each public service a `*.up.railway.app` domain; we attach human domains and
put Cloudflare in front. **Never advertise the raw `*.up.railway.app` domain** — it
bypasses Cloudflare (§4.5).

1. Railway `backend` service → **Settings → Networking → Custom Domain** → add
   `api.strattraderpro.com`. Railway shows a **CNAME target** (e.g.
   `xxxx.up.railway.app`).
2. Railway `frontend` service → add `app.strattraderpro.com` → note its CNAME target.
3. **(Optional) `hooks.strattraderpro.com`** → add as a **second** custom domain on the
   **`backend`** service. This gives TradingView webhooks their own hostname so you can
   rate-limit / WAF the intake path separately in Cloudflare (§4.3) without touching the
   app. If you skip it, webhooks stay on `api.` — that is fine for beta.
4. In **Cloudflare → DNS**, add a **CNAME** for each, **Proxied (orange cloud ON)**:

   | Type | Name | Target (from Railway) | Proxy |
   |---|---|---|---|
   | CNAME | `api` | `<backend>.up.railway.app` | Proxied 🟠 |
   | CNAME | `app` | `<frontend>.up.railway.app` | Proxied 🟠 |
   | CNAME | `hooks` *(optional)* | `<backend>.up.railway.app` | Proxied 🟠 |

5. Add `api.strattraderpro.com` (and `hooks.` if used) plus `backend.railway.internal` to
   the backend's `ALLOWED_HOSTS`; add `https://app.strattraderpro.com` to
   `CSRF_TRUSTED_ORIGINS`. See §6.

## 4. Cloudflare — TLS, WAF, rate-limit, Bot Fight, origin lock — **[OPERATOR] account**

### 4.1 TLS

- **SSL/TLS → Overview → Full (strict).** (Railway presents a valid edge cert, so strict
  works and prevents downgrade.) Do **not** use Flexible.
- **Edge Certificates → Always Use HTTPS = On**, **HSTS = On** (Django already sends
  `Strict-Transport-Security` with `preload` from `prod.py`; enabling at the edge is belt
  and braces), **Minimum TLS 1.2**.
- Keep Django's **`SECURE_SSL_REDIRECT=False`** (default). Both Cloudflare and Railway
  terminate TLS, so Django sees HTTP on the proxied request — enabling its redirect causes
  an **infinite redirect loop** (see `staging-deploy.md`).

### 4.2 WAF

- **Security → WAF → Managed rules:** enable the **Cloudflare Managed Ruleset** and the
  **OWASP Core Ruleset** (start OWASP at *paranoia low / anomaly high* to avoid false
  positives on the SPA, then tighten).

### 4.3 Rate-limiting

- **Security → WAF → Rate limiting rules.** Two rules:
  - **Auth:** path `starts_with /api/v1/auth/` → e.g. 20 req / 10 s per IP → managed
    challenge / block. (Backstops the app-layer `django-ratelimit` + `FailedLoginAttempt`
    lockout.)
  - **Webhooks:** hostname `hooks.strattraderpro.com` (or path `starts_with /hooks/v1/`)
    → a ceiling above the legitimate 20 req/s load-test rate (e.g. 60 req / 10 s per IP).
    The app already enforces `WEBHOOK_RATE_LIMIT_PER_MIN` per config — this is a coarse DoS
    lid, not the per-strategy limit.

### 4.4 Bot mitigation

- **Security → Bots → Bot Fight Mode = On** (free) or **Super Bot Fight Mode** (Pro).
  Exempt `hooks.` from JS-challenge bot rules — TradingView is a legitimate server-to-server
  caller and cannot solve a challenge.

### 4.5 Lock the origin to Cloudflare

The goal: the Railway origin must accept traffic **only** from Cloudflare, so an attacker
who discovers the `*.up.railway.app` URL cannot bypass the WAF.

- **Preferred: Authenticated Origin Pulls (mTLS).** SSL/TLS → **Origin Server →
  Authenticated Origin Pulls = On**. (Railway's managed edge does not expose an
  origin-cert upload, so if full mTLS termination is not available on the plan, use the
  secret-header method below — do **not** leave the origin open.)
- **Portable fallback (works on any Railway plan): a shared secret header.** Cloudflare
  **Transform Rules → Modify Request Header** injects `X-Edge-Auth: <random-secret>` on
  every proxied request; Django middleware (or the frontend nginx) **rejects any request
  missing it** in prod. This makes the bare Railway URL useless without the secret.
- **Do not publish or link the `*.up.railway.app` domains anywhere.** Set
  `ALLOWED_HOSTS` to the `api.`/`app.`/`hooks.` names (plus `*.railway.internal` for
  agent scrapes) so a Host-header hit on the raw domain returns 400.

> **Railway note:** Railway's public networking does not offer per-service inbound IP
> allowlisting on standard plans, so a literal "allow only Cloudflare's IP ranges at the
> origin firewall" is not directly available. The two mechanisms above achieve the same
> guarantee (only Cloudflare-proxied traffic is honored). If you later move the origin
> behind a proxy/VM you control, add Cloudflare's published IP ranges
> (`https://www.cloudflare.com/ips/`) to that firewall as defense in depth.

## 5. Provision the Cloudflare R2 bucket — **[OPERATOR]**

R2 backs two prod-only data paths that are **net-new in M11** (§7.6, §7.7; §4 decision 2):
GDPR personal-data **export** ZIPs (delivered via a 24h **signed URL**, broker creds + MFA
secrets redacted) and the weekly `pg_dump` **backup offload**.

1. Cloudflare dashboard → **R2 → Create bucket** → e.g. `strattraderpro-prod-private`
   (private — never public). Note the **account ID** (the R2 S3 endpoint is
   `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`).
2. **R2 → Manage API Tokens → Create** an **Object Read & Write** token scoped to that
   bucket. Capture the **Access Key ID** + **Secret Access Key** → these become the
   `AWS_*` vars in §6.
3. (Recommended) a **lifecycle rule** on the export prefix to auto-delete objects after a
   few days (exports are transient) and retain `pg_dump` offloads 90 days (§7.6).

The GDPR/backup code is built against an S3-compatible **`django-storages`[s3] / boto3**
abstraction (tested locally against MinIO/moto). Until these vars are set, the export job
degrades gracefully (stays `PENDING` with a clear operator note) rather than crashing.

## 6. Environment-variable matrix

`config.settings.prod` **fails closed**: unset `SECRET_KEY` / `FERNET_KEK` / an insecure
signing key aborts the boot. Use Railway **service references** (`${{Postgres.DATABASE_URL}}`,
`${{backend.RAILWAY_PUBLIC_DOMAIN}}`) wherever possible so values resolve automatically.

### 6.1 Core — set on **all six** backend-image services (`backend`, `celery-worker`, `worker-backtest`, `celery-beat`, `streams`, `ws`)

| Var | Value / source | Notes |
|---|---|---|
| `SERVICE_ROLE` | per §2.2 table | The one var that differs per service. |
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` | Not `.dev` — `web-dev` role is refused in a deployed env. |
| `SECRET_KEY` | generated (§2.4) | No default in prod → boot aborts if unset. |
| `JWT_SIGNING_KEY` | generated (§2.4), distinct from `SECRET_KEY` | HS256, single key (no `kid` rotation). Defaults to `SECRET_KEY` if unset — set a distinct value in prod. Rotation = drain (`docs/runbooks/secret-rotation.md`). |
| `FERNET_KEK` | generated (§2.4) | Fernet-at-rest for MFA secrets + broker API keys + webhook `sig`. Irreplaceable — back it up. |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | The prod Postgres from §2.1. |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Celery broker/result + idempotency SETNX + channels. |
| `ALLOWED_HOSTS` | `api.strattraderpro.com,hooks.strattraderpro.com,backend.railway.internal` | Comma list. Include `hooks.` only if used; include the internal name so the agent scrape (Host `backend.railway.internal`) is not 400'd. |
| `CORS_ALLOWED_ORIGINS` | `https://app.strattraderpro.com` | Empty is acceptable if the frontend proxies same-origin; set it if the SPA calls `api.` cross-origin. |
| `CSRF_TRUSTED_ORIGINS` | `https://app.strattraderpro.com,https://api.strattraderpro.com` | Scheme required. |
| `SECURE_SSL_REDIRECT` | `false` (default) | Leave false — see §4.1 (edge terminates TLS; true = redirect loop). |
| `SENTRY_DSN` | prod Sentry DSN | Empty disables Sentry. Env auto-tags `production` via `RAILWAY_ENVIRONMENT_NAME`. |
| `METRICS_BASIC_AUTH_USERNAME` | chosen | `/metrics` **fails closed** (401) in prod until both are set. Must match the grafana-agent's `basic_auth` (§6.5). |
| `METRICS_BASIC_AUTH_PASSWORD` | chosen | " |
| `ENABLE_LIVE_TRADING` | `false` | **Stays off.** Paper only. |
| `ALPACA_PAPER_KEY_ID` | Alpaca paper key id | Paper broker. |
| `ALPACA_PAPER_SECRET_KEY` | Alpaca paper secret | " |
| `FRONTEND_BASE_URL` | `https://app.strattraderpro.com` | OAuth + email links are built from this (no user-controlled redirect). |
| `EMAIL_BACKEND` / Resend key | Anymail Resend (base default) + `RESEND_API_KEY` | Transactional email (export link, delete confirmation, terms). |
| `DEFAULT_FROM_EMAIL` | e.g. `no-reply@strattraderpro.com` | Verify the domain in Resend. |

### 6.2 Per-service extras — `TASK_METRICS_PORT` (task services) + `ws` port

`TASK_METRICS_PORT` gives each task process its own `/metrics` server for the grafana-agent
to scrape (M10 FIX-C1; `docs/runbooks/worker-metrics-scrape.md`). One port per service:

| Service | Extra var(s) | Value |
|---|---|---|
| `celery-worker` | `TASK_METRICS_PORT` | `9101` |
| `worker-backtest` | `TASK_METRICS_PORT` | `9102` |
| `celery-beat` | `TASK_METRICS_PORT` | `9103` |
| `streams` | `TASK_METRICS_PORT` | `9104` |
| `ws` | *(none)* | daphne binds Railway's injected `$PORT`; the `${PORT:-8788}` fallback is only for local compose — **do not** set `PORT` on Railway. |

`backend` (`web`) exposes `/metrics` from gunicorn on its normal `$PORT`; no
`TASK_METRICS_PORT`.

### 6.3 GDPR / backup storage (Cloudflare R2) — set on `backend`, `celery-worker`, `celery-beat`

These are **net-new M11** vars (§5). The `django-storages`[s3] S3 backend talks to R2 via
its S3-compatible endpoint. Set them where storage is touched: `backend` (mints the signed
URL), `celery-worker` (writes the export ZIP), `celery-beat` (weekly `pg_dump` offload). Set
on all six backend-image services if you prefer uniformity — harmless on the ones that don't
use storage.

| Var | Value | Notes |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | R2 token Access Key ID (§5) | |
| `AWS_SECRET_ACCESS_KEY` | R2 token Secret Access Key (§5) | Secret. |
| `AWS_STORAGE_BUCKET_NAME` | `strattraderpro-prod-private` | The private bucket. |
| `AWS_S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` | R2's S3 endpoint (from §5). |
| `AWS_S3_REGION_NAME` | `auto` | R2 uses `auto`. |
| `AWS_S3_SIGNATURE_VERSION` | `s3v4` | Required for R2 presigned URLs. |
| `AWS_S3_ADDRESSING_STYLE` | `virtual` | R2 supports virtual-hosted style. |
| `GDPR_EXPORT_URL_TTL_SECONDS` | `86400` | Signed-URL lifetime = 24h (§4 decision 2). |

> Django 5's `STORAGES` setting selects this S3 backend for the export/backup buckets while
> `staticfiles` stays local — the code wires the backend from the `AWS_*` vars above; there
> is no separate `STORAGES` env var to set by hand.

### 6.4 Exporters (`postgres-exporter`, `redis-exporter`)

| Service | Var | Value |
|---|---|---|
| `postgres-exporter` | `DATA_SOURCE_NAME` | `postgresql://<user>:<pw>@<pg-host>:5432/<db>?sslmode=disable` — from the Railway Postgres connection components. Exposes `:9187`. |
| `redis-exporter` | `REDIS_ADDR` | `redis://<redis-host>:6379` — from the Railway Redis. Exposes `:9121`. |

### 6.5 grafana-agent (scrape targets + remote-write)

The agent's `agent.yaml` reads every target as an env var, so the same config drives compose
and Railway; on Railway they take the **internal-DNS** form `<service>.railway.internal:<port>`
(`docs/runbooks/worker-metrics-scrape.md`).

| Var | Value |
|---|---|
| `GRAFANA_PROM_URL` | Grafana Cloud remote-write URL (`https://prometheus-…grafana.net/api/prom/push`) |
| `GRAFANA_PROM_USER` | Grafana Cloud Prometheus user id |
| `GRAFANA_PROM_TOKEN` | Grafana Cloud API token (`glc_…`) |
| `BACKEND_TARGET` | `backend.railway.internal:8777` (with `basic_auth` = `METRICS_BASIC_AUTH_*`) |
| `WORKER_TARGET` | `celery-worker.railway.internal:9101` |
| `WORKER_BACKTEST_TARGET` | `worker-backtest.railway.internal:9102` |
| `BEAT_TARGET` | `celery-beat.railway.internal:9103` |
| `STREAMS_TARGET` | `streams.railway.internal:9104` |
| `POSTGRES_EXPORTER_TARGET` | `postgres-exporter.railway.internal:9187` |
| `REDIS_EXPORTER_TARGET` | `redis-exporter.railway.internal:9121` |
| `RAILWAY_ENVIRONMENT_NAME` | auto-injected (`production`) — tags all metrics `env=production` |

### 6.6 frontend (nginx)

| Var | Value | Notes |
|---|---|---|
| `BACKEND_URL` | `https://api.strattraderpro.com` (or `https://${{backend.RAILWAY_PUBLIC_DOMAIN}}`) | nginx proxies `/api/*` here. Must be a **public** HTTPS URL, not `*.railway.internal` (private DNS doesn't resolve from nginx — see `staging-deploy.md`). |

## 7. Bring-up verification (do not trust "Online")

BUG-011's whole lesson: a service reporting **Online** proves nothing. Assert end-to-end.

1. **Backend health (via Cloudflare):**
   ```bash
   curl https://api.strattraderpro.com/healthz   # {"status":"ok","version":"<git-sha>"}
   curl https://api.strattraderpro.com/readyz     # {"status":"ok","checks":{"db":"ok","redis":"ok"}}
   ```
   `version: "unknown"` ⇒ deployed via `railway up` CLI, not GitHub — redeploy from git so
   `RAILWAY_GIT_COMMIT_SHA` is injected (`staging-deploy.md`).
2. **The async tier is really async (the BUG-011 assertion), in Grafana Cloud → Explore:**
   ```promql
   up{job=~"worker|beat|streams|worker-backtest"} == 1   # all four scraping
   celery_queue_depth                                     # 4 live series, fresh → beat→queue→worker loop works
   up{service=~"postgres|redis"} == 1                     # exporters scraping
   ```
   Then confirm each service's **deploy logs name the right process**: worker/beat show
   `celery`, `streams` shows `run_broker_streams`, `backend` shows `gunicorn` (**not**
   `runserver`). A `web-dev`/gunicorn mixup here is exactly what §7.0 exists to catch.
3. **Frontend → backend:** open `https://app.strattraderpro.com/login`, submit junk creds,
   confirm the request reaches Django (a clean auth error, not a proxy 502).
4. **MFA KEK loads:** sign in, Settings → Security → Set up 2FA; a QR code proves
   `FERNET_KEK` wraps a fresh TOTP secret.
5. **Cloudflare is actually in front:** `curl -sI https://api.strattraderpro.com/healthz`
   shows a `cf-ray` / `server: cloudflare` header. Confirm the bare `*.up.railway.app`
   domain is **not** reachable without the origin-lock secret (§4.5).
6. **GDPR export round-trip (once R2 is set):** `GET /api/v1/users/me/export/` → job →
   `GET …/export/{job_id}/` returns a signed R2 URL; download the ZIP and confirm broker
   creds + MFA secrets are **redacted**.
7. **Sentry:** trigger a test 500 (e.g. a non-existent admin URL) → event appears under
   `environment=production` within ~30s.
8. **Burn-rate alerts (M11 §13):** after importing the new rules, assert **`isPaused ==
   false`** via the Grafana API (BUG-009: import ≠ enable) and fire-test one.

## 8. Rollback / teardown

- **Per-service:** roll back a bad deploy via Railway → service → Deployments → previous
  healthy deploy → Rollback.
- **`SERVICE_ROLE` mistake:** re-type the old Custom Start Command in Railway (seconds) —
  the image change is inert while a start command overrides it (`service-role-cutover.md`).
- **Whole environment:** because prod is a **separate project**, tearing it down is
  deleting the `strattraderpro-prod` project — staging is untouched. Nothing in Cloudflare
  is created by the app, so remove the DNS records / zone manually if abandoning the domain.

## 9. Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Service crash-loops: `entrypoint: FATAL: SERVICE_ROLE is unset` | Start command deleted but `SERVICE_ROLE` not set (or not saved) | Set `SERVICE_ROLE` per §2.2 / `service-role-cutover.md`. **This crash is correct behavior.** |
| Backend boots then 500s on every request | Malformed `FERNET_KEK` (must be 32-byte url-safe base64) | Regenerate (§2.4), re-set, redeploy. |
| Boot aborts `ImproperlyConfigured: SECRET_KEY is the insecure dev default` | `SECRET_KEY`/`FERNET_KEK` unset or left at dev default | Set the real generated values — this is prod failing closed. |
| Infinite redirect loop on `app.`/`api.` | `SECURE_SSL_REDIRECT=True` behind edge TLS | Keep it `False` (§4.1). |
| `/healthz` → `{"version":"unknown"}` | Deployed via `railway up` CLI (no `RAILWAY_GIT_COMMIT_SHA`) | Redeploy via GitHub push (`staging-deploy.md`). |
| `up{service="backend"} == 0` in Grafana | `backend.railway.internal` not in `ALLOWED_HOSTS`, or `METRICS_BASIC_AUTH_*` mismatch between backend and agent | Add the internal host; make the creds match (§6.1/§6.5). |
| `/metrics` returns 401 to the agent | prod `/metrics` fails closed; agent `basic_auth` not set/mismatched | Set `METRICS_BASIC_AUTH_*` identically on backend + grafana-agent. |
| Prod backtests sit `QUEUED` forever | `worker-backtest` service missing | Create it (§2.2 row 3) with `SERVICE_ROLE=worker-backtest` (`backtest-stuck.md`). |
| `/ws/dashboard/` dead in prod | `PORT` overridden on the `ws` Railway service | Remove it — Railway injects `$PORT`; only local compose needs `PORT: 8788`. |
| GDPR export job stuck `PENDING` | R2 vars unset/wrong | Set the §6.3 `AWS_*` vars; verify the endpoint URL + token scope (§5). |
| Bare `*.up.railway.app` serves the app | origin not locked; raw domain advertised | Apply §4.5 (Authenticated Origin Pulls or the `X-Edge-Auth` secret header); keep `ALLOWED_HOSTS` to the human names. |

---

**Last reviewed:** 2026-07-12 (M11 §7.9 — AC-11-10 [LIVE]; the autonomous run delivers this runbook, not the live environment).
