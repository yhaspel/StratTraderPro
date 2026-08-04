# M11 Operator Follow-ups — one-shot prompt for Claude Cowork

> **Status: ❌ SCRAPPED 2026-07-14 — OSS pivot; do not run.**
> Superseded by `project-plan/PIVOT-TO-OSS.md`. Browser-driven operator PARTS A–H against a hosted
> Railway/Grafana/Sentry stack; parts C/D/E/F/H are void or moot under self-hosting. The one live
> finding (PART G — the audit-integrity runbook DDL bug) was transplanted and fixed in WP-3c before
> archiving. Kept as a record.

> Paste everything below the line into Claude Cowork. It drives the browser on a Chrome
> instance already logged into Railway, Cloudflare, Grafana Cloud, GitHub, Sentry, Resend,
> Alpaca, and the domain registrar. It executes the M11 Section-B operator to-do list.
>
> Source of truth in the repo (Cowork can read these if it has the checkout):
> `project-plan/M11-EXECUTION-REPORT.md` (Section B), `docs/ops/service-role-cutover.md`,
> `docs/ops/prod-bringup.md`, `docs/runbooks/{alerting-setup,secret-rotation}.md`,
> `docs/adr/103-service-role-dispatch.md`.

---

## MISSION

M11 (Hardening, Security, Load Test & Docs) merged to `main` (PR #32, squash `72ed231`).
The **code** for every hardening capability is live. Your job is the **operator half** — the
steps that need a logged-in human driving Railway/Cloudflare/Grafana/etc. Work through the
PARTS below **in order**. PART A is the most important and the lowest risk; do it first.

## RULES OF ENGAGEMENT (read before touching anything)

1. **This is production infrastructure.** Move deliberately. After every change, run the
   stated **verification** before moving on. Do not batch changes across services without
   verifying each.
2. **Staging before production, always.** Where an action exists in both a `staging` and a
   `production` Railway environment, do **staging first**, verify it fully, and only then do
   production.
3. **The BUG-009 lesson governs everything: never trust a "self-report."** A Railway service
   showing **"Online / Active"** proves nothing (BUG-011: a service was "Online" while running
   the wrong process for two months). A Grafana rule reporting `health: ok` proves nothing (it
   may be paused). Always assert the **end-to-end** effect, not the status badge.
4. **STOP and report to the user (do not improvise) if:** a service crash-loops in a way not
   described here; a verification query fails; you are unsure which of two UI elements to
   click; or an action would cost money or cause downtime you were not explicitly told to do.
5. **Ask the user to confirm before:** buying a domain, creating paid resources, deleting a
   **production** Custom Start Command (PART A step 4), or rotating the DB password (PART D —
   causes downtime). Screenshots of the *before* state help rollback.
6. **Never** set `ENABLE_LIVE_TRADING=true`. The platform is paper-trading only.
7. **Never** paste secrets (API keys, `FERNET_KEK`, DB passwords) into chat, tickets, or logs.
8. Keep a running log of what you changed, per service/env, so a rollback is trivial.

---

## PART A — `SERVICE_ROLE` cutover on the EXISTING Railway services (AC-11-15) — **DO THIS FIRST**

> **✅ COMPLETED live 2026-07-13** (both envs) — see `project-plan/M11-COWORK-OPERATOR-REPORT.md`.
> **⚠️ The premise below was partly wrong and caused a real (remediated) staging outage:** it is
> NOT true that the change is "inert until you set `SERVICE_ROLE`" for **`backend`**. `backend`
> never had a Custom Start Command — it ran the image *default* `CMD`, which §7.0 replaced with
> the dispatcher, so the merge's auto-deploy **crash-looped staging `backend`** (`SERVICE_ROLE
> unset`) while Railway showed "Online". **Set `SERVICE_ROLE=web` on `backend` BEFORE/AT the
> merge.** Command-bearing services (worker/beat/worker-backtest/streams) *are* inert until their
> cutover. Still outstanding to formally close AC-11-15: the Grafana `up{}`/`celery_queue_depth`
> PromQL checks in the verification below (they were not run during the cutover).

**Why:** M11 §7.0 baked service-role dispatch into the backend image so a blank start command
**crashes loudly** instead of silently running a web server (BUG-011). For the services that
already have a Custom Start Command, the image change is inert until you set `SERVICE_ROLE` and
**delete** the command; for **`backend`** (no start command → runs the image default `CMD`) it is
**not** inert — set `SERVICE_ROLE=web` first or it crash-loops. This part flips it on.

**Scope:** the CURRENT Railway project's **backend-image** services, in **both** the `staging`
and `production` environments. First open Railway and **list the services** in each environment.
The backend-image services (the ones built from `docker/backend.Dockerfile`) are typically:
`backend`, `celery-worker`, `worker-backtest` (or `worker-backtest-prod`), `celery-beat`,
`streams`, `ws`. **Do NOT touch** `frontend`, `postgres`, `redis`, `grafana-agent`,
`postgres-exporter`, `redis-exporter` — they are not `SERVICE_ROLE` services.

**Authoritative service → role mapping** (from `docs/ops/service-role-cutover.md`):

| Railway service | Set `SERVICE_ROLE` = |
|---|---|
| `backend` | **`web`**  ← production gunicorn. **NEVER `web-dev`** (that role refuses to boot in a deployed env). |
| `celery-worker` | `worker` |
| `worker-backtest` (/ `-prod`) | `worker-backtest` |
| `celery-beat` | `beat` |
| `streams` | `streams` |
| `ws` | `ws` |

**Procedure — do STAGING first, one service at a time:**

For each backend-image service in the **staging** environment:
1. Open the service → **Variables** tab. Note (screenshot) the current **Custom Start Command**
   (Settings → Deploy) so you can roll back.
2. **Add the variable** `SERVICE_ROLE` = its role from the table. Save. (Railway redeploys; no
   behavior change yet, because the start command still overrides the image.)
3. Wait for that redeploy to go healthy.
4. **Settings → Deploy → Custom Start Command → clear it and Save.** Railway redeploys; now the
   image entrypoint (`docker/entrypoint.sh`) dispatches on `SERVICE_ROLE`.
5. **Verify this service (do not trust "Active"):** open its **Deploy Logs** and confirm the
   process name:
   - `backend` logs must show **`gunicorn`** (and **NOT** `runserver`).
   - `celery-worker` / `worker-backtest` / `celery-beat` logs must show **`celery`**.
   - `streams` logs must show **`run_broker_streams`**.
   - If instead you see `entrypoint: FATAL: SERVICE_ROLE is unset`, the variable did not save —
     re-add it (step 2). **That crash is the design working — loud, not silent.**

After **all** staging services are cut over, verify the async tier end-to-end in
**Grafana Cloud → Explore** (Prometheus data source), each query returns the expected result:
```
up{job=~"worker|beat|streams|worker-backtest"} == 1     # all four scraping (was 0 during BUG-011)
celery_queue_depth                                       # 4 live series, recently updated
```
Also confirm `TargetDown` / `MetricsPipelineDown` are **not** firing.

**Only when staging is fully green**, ask the user to confirm, then repeat the exact same
procedure for the **production** environment's services.

**Rollback (per service, seconds):** re-type the old Custom Start Command you screenshotted in
step 1 and Save. The image change is inert while a start command exists.

**Report at the end of PART A:** for each env, a table of service → role set → start command
deleted (y/n) → verified process → `up == 1` (y/n).

---

## PART B — Import the two NEW Grafana burn-rate alert rules (M11 §13) + unpause + fire-test

**Why:** M11 added SLO error-budget burn-rate alerts. The Grafana stack is already live (M10:
6 dashboards, 21 rules, contact points, notification policy). You are **adding two rules**, not
rebuilding anything.

The two new rules live in the repo at `infra/grafana/alerts/alert-rules.yaml`, group
`slo-burn-rate`:
- **`ApiErrorBudgetFastBurn`** (severity critical) — 14.4× burn over 1h AND 5m.
- **`ApiErrorBudgetSlowBurn`** (severity warning) — 6× burn over 6h AND 30m.

Both key off `django_http_responses_total_by_status_total` (a live series).

**Procedure:**
1. Import the two rules into Grafana Cloud the **same way M10's rules were imported** — follow
   `docs/runbooks/alerting-setup.md` (Grafana Alerting → the project's rule folder). If M10 used
   a provisioning file / API, add these two rules to it; if it used the UI, recreate them as
   Grafana-managed alerts in the `StratTraderPro` folder with the PromQL from the YAML.
2. **CRITICAL (BUG-009): after import, assert each new rule has `isPaused == false`.** Grafana's
   Prometheus-rule converter imports rules **paused by default**, and a paused rule reports
   `health: ok` forever while being unable to fire. Check via the Grafana API
   (`GET /api/v1/provisioning/alert-rules` → find the two rules → confirm `isPaused: false`) or,
   in the UI, that they are **not** shown as Paused. If paused, **unpause them**.
3. **Fire-test one** (e.g. `ApiErrorBudgetFastBurn`): temporarily lower its threshold or use a
   test rule so it enters Pending→Firing, and confirm the alert is **received** on both the
   email and Telegram contact points. Then restore the real threshold.

**Report:** the two rules' names, `isPaused` value after import (must be `false`), and whether
the fire-test reached email + Telegram.

---

## PART C — Cloudflare R2 for GDPR export + set the export env vars (AC-11-8 [LIVE] half)

**Why:** the GDPR personal-data export needs an S3-compatible bucket. Until these vars are set,
export jobs stay `PENDING` with an operator note (the code degrades gracefully — it does not
crash). Do this for **production** (and staging if you want exports there).

**Procedure:**
1. Cloudflare dashboard → **R2 → Create bucket**, name e.g. `strattraderpro-prod-private`
   (**private** — never public). Note the **Account ID** — the S3 endpoint is
   `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
2. **R2 → Manage API Tokens → Create** an **Object Read & Write** token scoped to that bucket.
   Capture the **Access Key ID** + **Secret Access Key**.
3. In Railway, on the production **`backend`, `celery-worker`, and `celery-beat`** services (set
   on all six backend-image services if you prefer uniformity — harmless on the rest), set these
   **exact** variables (these are the names `config/settings/prod.py` actually reads — do NOT
   invent `AWS_STORAGE_BUCKET_NAME`):

   | Variable | Value |
   |---|---|
   | `EXPORTS_BUCKET` | `strattraderpro-prod-private`  ← the trigger var; non-empty switches storage to R2 |
   | `AWS_ACCESS_KEY_ID` | the R2 token Access Key ID |
   | `AWS_SECRET_ACCESS_KEY` | the R2 token Secret Access Key |
   | `AWS_S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
   | `AWS_S3_REGION_NAME` | `auto` (optional — code defaults to `auto`) |
   | `EXPORT_SIGNED_URL_TTL_SECONDS` | `86400` (optional — code defaults to 24h) |

4. Redeploy those services.
5. **Verify (round-trip):** sign into the app (`app.` domain, or the staging URL), call
   `GET /api/v1/users/me/export/`, then poll `GET /api/v1/users/me/export/{job_id}/` until it
   returns a **signed download URL**. Download the ZIP and confirm broker API keys + MFA
   secrets are **redacted** (`[REDACTED]`, no plaintext/ciphertext).

**Report:** bucket name, endpoint host (not the secret), and that the export round-trip produced
a downloadable ZIP with redacted credentials.

---

## PART D — DB password rotation (AC-11-13 [LIVE] half) — **CONFIRM FIRST (causes downtime)**

**Ask the user to confirm a maintenance window before doing this.** Rotating the DB password
invalidates the live `DATABASE_URL` until the app services redeploy and re-read it.

**Procedure (staging first):**
1. Railway → Postgres service → rotate/regenerate the password (Variables / Connect).
2. Railway updates the injected `DATABASE_URL`. Redeploy every service that uses it (all six
   backend-image services).
3. **Measure downtime:** from the moment the password changes to the first successful
   `GET /readyz` returning `{"checks":{"db":"ok"}}`. Log the measured seconds.
4. Verify no sustained error spike, then do production.

**Report:** measured downtime per environment. (Then note it in
`docs/runbooks/secret-rotation.md` §2, which currently says "_pending operator run_".)

---

## PART E — Lighthouse FCP on throttled 4G (AC-11-12 [LIVE] half)

**Why:** the [CI] bundle gate is enforced; the FCP-on-4G target (≤ 1.2s) needs a deployed URL.

**Procedure:** open the deployed SPA (`https://app.strattraderpro.com`, or the staging frontend
URL) in Chrome → DevTools → **Lighthouse** → Mobile, **Slow 4G** throttling → run the
Performance audit. Record **First Contentful Paint**. (Or use PageSpeed Insights on the URL.)

**Report:** the FCP number and whether it meets ≤ 1.2s. If it misses, note it as a perf
follow-up (not a blocker).

---

## PART F — Activate the Terms acceptance flow (`seed_terms`) — **only after legal sign-off**

**Why:** the Terms/Privacy re-acceptance modal is INERT until a `TermsDocument` of each kind
exists. Seeding it force-prompts every user to accept on next login, so do it **only once
counsel has approved** `docs/legal/terms-of-service.md` + `privacy-policy.md`.

**Procedure:** run the management command on the backend service (Railway service → the
console/shell, or `railway run`):
```
python manage.py seed_terms --tos 1.0 --privacy 1.0
```
**Verify:** sign in as a test user → the blocking Terms modal appears → accept → it does not
reappear on the next login. `GET /api/v1/terms/current/` returns `needs_acceptance: false` after.

**If you cannot open a shell on the Railway service**, report that back — this step needs
command execution, not just the browser.

---

## PART G — Verify the restricted audit DB role (M10 carryover `M10-cowork-followups.md` A6)

**Why:** the one known open M10 operator item. State its **actual** status; do not assume.

**Procedure:** connect to the production Postgres (Railway → Postgres → Data/Connect, or `psql`)
and check whether a **restricted, read-mostly role for the audit tables** exists and is used by
the app for audit reads (per `M10-cowork-followups.md` A6). Report exactly what you find:
provisioned & in use / provisioned but unused / not provisioned. If not provisioned and the
runbook has the DDL, apply it; otherwise report so the team can decide.

---

## PART H — Full production bring-up (AC-11-10) — **large; confirm scope + budget first**

**This is a big initiative, not a quick toggle. Ask the user whether to proceed now**, and
whether they have registered `strattraderpro.com` and are ready to pay for a domain + a prod
Railway project. If yes, execute **`docs/ops/prod-bringup.md`** end-to-end — it is the
authoritative, step-by-step runbook and includes:
- Registering `strattraderpro.com` (§1, needs a purchase — **confirm with the user**).
- A **separate** `strattraderpro-prod` Railway project with all **12 services** (§2) — every
  backend-image service gets `SERVICE_ROLE` from the start (no cutover needed on a fresh project)
  and **no** Custom Start Command.
- Generating the three prod-only secrets `SECRET_KEY` / `JWT_SIGNING_KEY` / `FERNET_KEK` (§2.4).
- DNS `api.` / `app.` (+ optional `hooks.`) via Cloudflare, **Proxied** (§3).
- Cloudflare TLS **Full (strict)**, WAF (managed + OWASP), rate-limit rules, Bot Fight, and the
  **origin lock** so the bare `*.example.com` cannot bypass the WAF (§4).
- The full env-var matrix (§6) — including the R2 vars from PART C above and
  `METRICS_BASIC_AUTH_*` matching the grafana-agent.
- The 8-point bring-up verification (§7) — **do not trust "Online."**
- Then a 24-hour prod soak before announcing.

Follow that runbook's steps and verifications exactly; report progress per section.

---

## NOT for Cowork (flag these to the user, do not attempt)

- **Legal counsel review** of `docs/legal/terms-of-service.md` + `privacy-policy.md` — a human
  task; PART F depends on it.
- **The local git tag `v0.11.0-rc.1`** was created on the merge commit and is **intentionally
  not pushed** (operator convention — prior tags are also unpushed). Do not push it unless the
  user explicitly asks.
- **Reconcile a concurrent session's uncommitted work**: four files
  (`backend/apps/users/{metrics,services,views,test_auth}.py`) in the local working tree carry a
  different session's email-instrumentation feature that M11 deliberately did **not** commit.
  This is a local dev-tree matter for the user to resolve — not a browser task.
- **The full load test + destructive chaos drills** (`backend/loadtest/`, `scripts/chaos/`) run
  on a **dedicated throwaway** compose stack, not on shared/prod infra — a developer task, not a
  browser task.

---

## FINAL REPORT

Produce one consolidated report: for each PART A–H, state **Done / Partially done / Blocked /
Skipped (why)**, the verification result, and anything you had to STOP on. Lead with PART A
(the cutover) and call out explicitly whether `up{job=~"worker|beat|streams|worker-backtest"} == 1`
in **both** environments after the cutover.
