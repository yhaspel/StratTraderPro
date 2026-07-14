# ONE-SHOT — M11 operator tail (PARTS C, D, E, F, H)

**Context:** A Cowork browser session completed **PART A** (SERVICE_ROLE cutover, both envs),
**PART B** (SLO burn-rate alerts imported, unpaused, fire-tested end-to-end) and **PART G**
(restricted audit role — investigated, deliberately NOT applied). Evidence:
`project-plan/M11-COWORK-OPERATOR-REPORT.md`.

This prompt covers the remainder. Each part was **deliberately not done** by the browser agent
because it requires one of: handling a secret, spending money, causing downtime, or legal
sign-off. Do them in order; they are independent.

## GROUND RULES

1. **Never** set `ENABLE_LIVE_TRADING=true`. Paper trading only.
2. **Never** paste a secret into chat, a commit, a log, or a ticket. Use `railway variables --set`
   or the Railway UI directly; read values from the operator's own clipboard/password manager.
3. Staging before production, always. Verify each change end-to-end before the next.
4. **Do not trust "Online" / `health: ok`.** Assert the end effect (BUG-009 / BUG-011).
5. Current live state you can rely on:
   - All 10 backend-image services (5 staging + 5 prod) have `SERVICE_ROLE` set and **no**
     Custom Start Command. The image entrypoint is now the single source of truth.
   - `up{job=~"worker|beat|streams|worker-backtest"} == 1` for all 8 series; 14/14 targets up.
   - Grafana: 23 rules, **0 paused**. Burn-rate rules live and evaluating.

---

## PART C — Cloudflare R2 for the GDPR export (AC-11-8 [LIVE])

**Why it was skipped:** creating the R2 token and entering the Access Key / Secret into Railway
is credential handling.

**Confirmed need (from live prod + staging boot logs):**
```
EXPORTS_BUCKET unset — GDPR exports stay PENDING until Cloudflare R2 is provisioned
(set EXPORTS_BUCKET + AWS_* + AWS_S3_ENDPOINT_URL). See docs/ops/prod-bringup.md.
```
So the graceful degradation is working; export jobs will sit `PENDING` until this is done.

**Steps**
1. Cloudflare → **R2 → Create bucket**, name `strattraderpro-prod-private`. **Private.** Note the
   **Account ID** (the endpoint is `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`).
2. R2 → **Manage API Tokens → Create**, **Object Read & Write**, scoped to that bucket only.
3. Set these on the prod `backend`, `celery-worker`, `celery-beat` services. **These are the exact
   names `config/settings/prod.py` reads — do NOT invent `AWS_STORAGE_BUCKET_NAME`:**

   | Variable | Value |
   |---|---|
   | `EXPORTS_BUCKET` | `strattraderpro-prod-private` ← trigger var; non-empty switches storage to R2 |
   | `AWS_ACCESS_KEY_ID` | R2 token Access Key ID |
   | `AWS_SECRET_ACCESS_KEY` | R2 token Secret Access Key |
   | `AWS_S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
   | `AWS_S3_REGION_NAME` | `auto` (optional, code defaults) |
   | `EXPORT_SIGNED_URL_TTL_SECONDS` | `86400` (optional, code defaults) |

4. Redeploy those three.
5. **Verify (round-trip, do not trust the var being set):** sign in →
   `GET /api/v1/users/me/export/` → poll `GET /api/v1/users/me/export/{job_id}/` until it returns a
   signed URL → download the ZIP → confirm broker API keys and MFA secrets are `[REDACTED]`
   (no plaintext **and no ciphertext**).
6. Confirm the boot log no longer prints the `EXPORTS_BUCKET unset` line.

---

## PART D — DB password rotation (AC-11-13 [LIVE]) — CAUSES DOWNTIME

**Why it was skipped:** explicit confirm-gate + credential handling.

**Ask the operator for a maintenance window first.**

**Steps (staging first)**
1. Railway → Postgres → rotate/regenerate the password.
2. Railway updates the injected `DATABASE_URL`. Redeploy **all five** backend-image services in
   that env (`backend`, `celery-worker`, `celery-beat`, `streams`, `worker-backtest`).
3. **Measure downtime:** from password change → first `GET /readyz` returning
   `{"checks":{"db":"ok"}}`. Record the seconds.
4. Confirm no sustained 5xx spike, then repeat for production.
5. Record the measured downtime in `docs/runbooks/secret-rotation.md` §2, which currently says
   "_pending operator run_".

**Watch for:** the async services fail *silently* if they can't reach the DB while `/healthz`
stays green (that's the BUG-011 shape). Assert `up{job=~"worker|beat|streams|worker-backtest"} == 1`
in Grafana after the rotation, not just the web tier.

---

## ✅ PART E — Lighthouse FCP on throttled 4G (AC-11-12) — **DONE 2026-07-13. TARGET MISSED.**

Run on the operator mac with local Chrome (the sandbox's "no Chrome / PSI quota exhausted" blocker
does not apply there). Throttling confirmed **genuine Slow-4G** — `rttMs 150`,
`throughputKbps 1638.4`, `cpuSlowdownMultiplier 4` — i.e. this is a real throttled number, not an
unthrottled one relabelled.

| Metric | Value | Target |
|---|---|---|
| **FCP** | **2.8 s** (2809 ms) | ≤ 1.2 s → **MISS (2.3×)** |
| LCP | 3.7 s | — |
| Speed Index | 2.8 s | — |
| TBT | 90 ms | — |
| Perf score | 84 | — |

Target: `https://frontend-production-c977f.up.railway.app`, form factor mobile.

**Per this prompt's own rule, a miss is NOT a release blocker → perf follow-up.** The `[CI]` bundle
gate (520 kB; actual 473.28 kB) is separately green — so **the bundle budget is not the problem, and
shrinking it further will not fix this.**

**Where the time actually goes (do not micro-optimise the wrong thing):** this is a client-rendered
Angular SPA. On Slow-4G, *nothing* paints until the initial JS is fetched, parsed and bootstrapped —
FCP is therefore gated on the bundle round-trip, and LCP (3.7 s) trails it. TBT is only 90 ms, so
this is **not** a CPU/execution problem; it is a "no HTML until JS runs" problem. The levers, in
order of effect:

1. **A static app shell / prerender** so *something* meaningful paints before Angular boots — this is
   the only change that structurally moves FCP on an SPA.
2. Preload/`modulepreload` the initial chunk; ensure Brotli on the nginx layer.
3. Only then: bundle shaving.

Log it as a perf ticket citing FCP 2.8 s vs 1.2 s (LCP 3.7 s is the bigger lever). Do not treat it
as a bundle-size regression — it isn't one.

### ⚠️ THE 2.8 s NUMBER IS ALREADY STALE — re-measure after the next frontend deploy

The 2.8 s was measured **before** the cheap wins landed. Two things have since changed in the
working tree and are **not yet deployed**:

1. **gzip was serving at level 1** — nginx's default, never overridden. Assets are now
   pre-compressed at **gzip -9** at image build and served via `gzip_static`, with `gzip_vary`
   pinned. Initial payload **168.2 kB → 144.3 kB** (~**0.12 s** on Slow-4G).
   (`docker/frontend.Dockerfile`, `docker/nginx.conf.template`)
2. **`/config.js` was a render-blocking classic script in `<head>`** — the parser stopped and could
   not paint until a full RTT completed for 326 bytes. Now `defer`red (~**0.15 s+**).
   (`frontend/src/index.html`)

**Brotli was measured and REJECTED** — brotli-11 beats gzip-9 by only ~0.08 s, and the official
nginx image has no `ngx_brotli`, so adopting it means replacing the base image and losing the
upstream `envsubst` entrypoint (BUG-004 territory). Not worth 80 ms.

**Expected after deploy: ~2.5 s — still ~2× the target.** That is the point: these were always going
to be marginal, because **this is not a compression problem.** TBT is 90 ms and the bundle is under
budget; FCP and LCP land 0.9 s apart, which is the signature of *nothing painting until the SPA
boots*. Client-side rendering has a ~1.5–2.2 s floor on Slow-4G no matter how small the bundle gets.

➡️ **The structural fix is prerendering: `project-plan/14-frontend-first-paint.md` (M14).**
Re-measure FCP once the frontend redeploys, record the new number in the perf ticket, and treat M14
as the actual owner of AC-11-12. Note M14 §11: **≤1.2 s was written before anyone measured**, and
for an authenticated dashboard with a handful of beta users, amending the AC with evidence may be
the right outcome — but only after a real measurement, never by quietly dropping it.

---

## PART F — Activate the Terms flow (`seed_terms`) — **only after legal sign-off**

**Why it was skipped:** counsel has not approved `docs/legal/terms-of-service.md` +
`privacy-policy.md`. Seeding force-prompts **every** user to accept on next login, so it is
irreversible-ish in UX terms. This is gated on a human, not on tooling.

**Once counsel signs off:**
```bash
railway run --service backend python manage.py seed_terms --tos 1.0 --privacy 1.0
```
**Verify:** sign in as a test user → blocking Terms modal appears → accept → it does **not**
reappear on next login → `GET /api/v1/terms/current/` returns `needs_acceptance: false`.

---

## PART G — restricted audit DB role — **INVESTIGATED, DO NOT BLINDLY APPLY**

Already done by the browser agent; recorded here so you don't redo it wrongly.

**Live finding (production Postgres):**
- `SELECT rolname, rolsuper FROM pg_roles WHERE rolcanlogin` → **exactly one row: `postgres`,
  `rolsuper = true`.** `stp_audit_writer` does **not** exist. Status: **NOT PROVISIONED.**
- Append-only triggers on `audit_log` are **intact**: `audit_log_block_mutation`,
  `audit_log_check_link` (2/2). The catch-net holds.

**Why the DDL in `docs/runbooks/audit-integrity-failure.md` Appendix A was NOT applied:**
1. The runbook's stated blocker — *"Railway's managed Postgres gives us one role"* — is
   **inaccurate**. The single role is a **superuser**, so it *can* `CREATE ROLE`. The plan is not
   the constraint.
2. The real blocker is that **the DDL is incomplete**. It grants `SELECT, INSERT` on `audit_log`
   and the sequence, and nothing else — the runbook literally leaves
   *"(Whatever grants the app needs on the rest of the schema go here, as usual.)"* as a TODO.
   Pointing runtime `DATABASE_URL` at that role as written would **break every other table** in
   production.
3. It needs a two-URL split (runtime role vs. migration/owner role) that nothing in the deploy
   pipeline currently implements.

**Action for a human:** decide whether to (a) design the full grant set + the migration-role split
properly, or (b) formally accept the single-role limitation and close A6 as WONTFIX, documenting
that the nightly trigger-presence check is the compensating control. Then **correct the runbook's
Appendix A** — its premise is wrong.

---

## PART H — Full production bring-up (AC-11-10) — **CONFIRM SCOPE + BUDGET FIRST**

**Why it was skipped:** requires registering `strattraderpro.com` (a purchase) and creating a
separate paid Railway project.

Ask the operator whether they have registered the domain and are ready to pay. If yes, execute
`docs/ops/prod-bringup.md` end-to-end — it is authoritative. Key points:
- A **separate** `strattraderpro-prod` Railway project, 12 services (§2). Every backend-image
  service gets `SERVICE_ROLE` **from the start** and **no** Custom Start Command — a fresh project
  needs no cutover. (The M11 entrypoint makes a blank start command crash loudly, which is the
  desired behaviour; do not "fix" it by adding start commands.)
- Generate the three prod-only secrets `SECRET_KEY` / `JWT_SIGNING_KEY` / `FERNET_KEK` (§2.4).
  **`FERNET_KEK` is required by EVERY Django service** — celery/streams/backtest workers
  crash-loop without it while `/healthz` stays green.
- DNS `api.` / `app.` (+ optional `hooks.`) via Cloudflare, **Proxied** (§3).
- Cloudflare TLS **Full (strict)**, WAF (managed + OWASP), rate-limit rules, Bot Fight, and the
  **origin lock** so the bare `*.up.railway.app` cannot bypass the WAF (§4).
- Full env-var matrix (§6), including the PART C R2 vars and `METRICS_BASIC_AUTH_*` matching the
  grafana-agent.
- The 8-point bring-up verification (§7). Then a 24-hour soak before announcing.

---

## M13 — live-trading switch: RUN THE GAUNTLET FIRST

`project-plan/13-live-trading-switch.md` + the code below landed in this session, **inert**
(`ENABLE_LIVE_TRADING=false` everywhere, unchanged). Touched:
`apps/brokers/{base,errors,services}.py`, `apps/brokers/alpaca/{adapter,errors}.py`, new
`apps/brokers/test_live_mode.py`, plus `config/settings/{base,prod}.py` and
`docker/backend.Dockerfile` for the known-issue fixes.

### ✅ GAUNTLET RUN — 2026-07-13, operator mac. ALL GREEN.

| Gate | Result |
|---|---|
| `pytest apps/brokers/test_live_mode.py -v` | **22 passed** (was 20 passed / **2 ImportError** — see below) |
| `-k STAYS_paper` (the load-bearing M13 F-3 assertion) | **PASSED** |
| `pytest` (full suite) | **exit 0, no regressions** |
| `ruff check .` | **All checks passed** |
| `bandit -q -r apps config` | **0 High.** 2 Medium + 69 Low are pre-existing baseline (`B608` in `apps/audit/tests/test_pg.py`) — **not** M13 |
| `manage.py makemigrations --check` | **No changes** — `BrokerAccount.mode` already exists, as predicted |
| `ngc --noEmit` + `ng build` | clean; initial bundle **473.28 kB** (< 520 kB gate) |

### 🐞 A REAL BUG THE GAUNTLET CAUGHT — in the test, not the product

`test_live_mode.py::SupervisorContextTests` imported **`BrokerStreamSupervisor`**. The class is
actually **`StreamSupervisor`** (`apps/brokers/streams.py:91`, and what `run_broker_streams`
instantiates). Result: **ImportError — those 2 tests never ran.**

The two that never ran were, of course, precisely the ones asserting that the supervisor propagates
`mode` into the live fill stream — the "the endpoint is only as correct as the context that reaches
it" check (AC-13-11, §5a). **The production code was correct all along**
(`StreamSupervisor._context_for()` sets `mode=account.mode`, `streams.py:135`); this was purely a
wrong symbol in the test.

**Lesson, recorded because it is the same disease this whole milestone is about:** the test was
written to verify that an assumption held, and it asserted a class name that was never checked to
exist. It failed loudly (ImportError, not a silent pass), so CI would have caught it — but it only
got caught *because someone actually ran it*. Static gates (`py_compile`, `ruff`) were all green
and told us nothing. **Green static checks are not a test run.**

**Fix applied (test-only, 3 references):** `BrokerStreamSupervisor` → `StreamSupervisor` in
`apps/brokers/test_live_mode.py`. Uncommitted, part of the M13 working-tree diff — it lands when
M13 lands.

**Still to build for M13 (not done):** the API layer (MFA step-up + `confirm:"LIVE"` + risk-profile
precondition + immutable-mode validation → AC-13-2/6/7/8) and the frontend (mode picker, permanent
LIVE banner, typed confirm → AC-13-9). The adapter/context/validation layer is done; the
**user-facing gates are not**, so do not enable the flag even in staging until they exist.

---

## KNOWN ISSUES worth fixing while you're in here

1. ✅ **FIXED — `/healthz` stale git SHA.** Prod said `e5ecd75` while running `dd93bcb`. Root cause:
   *every* source of the SHA was runtime state, and runtime state drifts from the code in the
   container. Fixed by **baking the SHA into the image at build time**
   (`docker/backend.Dockerfile`: `ARG RAILWAY_GIT_COMMIT_SHA` → `/app/.git_sha`) and having
   `config/settings/base.py::_resolve_git_sha()` read that file **first, above every env var** —
   the one source that cannot lie, because it ships with the layer it describes. Fails **soft**: if
   the build arg is absent the file is empty and the old env chain still applies, so it can never
   make `/healthz` worse. **Verify after the next deploy:** `/healthz` must report the commit you
   actually deployed.

2. ✅ **FIXED (and my first diagnosis was wrong).** `METRICS_BASIC_AUTH_*` guards **only** the
   Django `/metrics` WSGI endpoint (`config/metrics_endpoint.py`, mounted in `wsgi.py`), which
   **only the `web` role serves**. The async roles expose their series through a *different* server
   — `config.task_metrics`, a plain prometheus_client listener on `TASK_METRICS_PORT` (9101–9104)
   that never reads these settings. So setting those vars on the workers (which the earlier report
   suggested) would have changed **nothing**. The real defect was that `prod.py` emitted the
   warning from *every* role, actively misleading the operator. Fixed by scoping the warning to the
   role that actually serves the endpoint (`config/settings/prod.py`). **Note the honest residual:**
   ports 9101–9104 are genuinely unauthenticated — they are only reachable on
   `*.railway.internal` (private network), which is why the scrape works. Decide if that is
   acceptable; it is not currently a hole to the internet.

3. ✅ **FIXED — `bugs/BUG-011-...md`** now carries the correction: the claim *"the image change is
   inert (an existing start command overrides the CMD)"* was **false for `backend` and `streams`**,
   which never had start commands, and that false premise is what crash-looped staging for ~2h.

4. ✅ **FIXED — `MetricsBudgetHigh`.** *(This supersedes the CLI report of 2026-07-13, which listed
   it as "unchanged / a spend decision". It was neither — it was a cardinality bug, and it is now
   resolved. No money spent, no environment deleted.)*

   Root-caused with data, not assumption. The stack was at **9,130 / 10,000 active series (91%)**:

   | Job | Series | Share |
   |---|---|---|
   | postgres-exporter | 4,786 | **52%** |
   | redis-exporter | 2,185 | **24%** |
   | backend | 822 | 9% |
   | worker/beat/worker-backtest/streams | 1,336 | 15% |

   Two exporters were **76% of the entire budget**. What actually consumed those series across every
   committed rule and dashboard: `pg_stat_activity_count` and `pg_settings_max_connections`. That is
   all — **zero** `redis_*` series are queried anywhere (system-health's "redis ops/sec" is prose in
   a text panel). ~7,000 series were ingested to serve two. The fat was per-table churn
   (`pg_stat_user_tables_*`: 30 metrics × 124 series = 62 tables × 2 envs) and Redis command-latency
   histograms (`redis_commands_latencies_usec_bucket` alone = 724).

   Fixed by keep-lists on the two exporter jobs (`infra/grafana-agent/agent.yaml`, commit
   `e0eafe8`, deployed to both envs). **Verified live:**

   - active series **9,130 → 1,800** (91% → **18%** of the tier)
   - postgres-exporter 4,786 → **62**; redis-exporter 2,185 → **18**
   - `up` = **14/14**, all 4 exporter targets `up == 1` in both envs
   - `pg_stat_activity_count` (48) + `pg_settings_max_connections` (2) **survive**
   - `MetricsBudgetHigh`: **pending → inactive**

   **THE TRAP (why a naive keep-list is worse than doing nothing):** `up` is what `TargetDown` and
   the whole dead-man's switch (BUG-008) key off. A keep-list that omitted it would silently stop
   those targets reporting `up` — and because every liveness rule is self-filtering, alerting would
   have gone **GREEN precisely because it had gone BLIND**. `up|scrape_.*` is pinned first in both
   regexes, and a parse check asserts it.

   Deleting the staging environment (the other proposed fix) would have freed only ~4,400 series —
   **less** — while destroying the environment that caught the M11 `SERVICE_ROLE` crash-loop before
   it reached prod, and that M13 §6 gate 3 needs to provoke a real L2 kill-switch trip.

5. 🔴 **NEW — `DBConnectionSaturation` HAS NEVER BEEN ABLE TO FIRE.** Found while verifying #4.

   ```promql
   pg_stat_activity_count / pg_settings_max_connections > 0.8     # <-- always empty
   ```

   PromQL vector-to-vector division matches on the **full label set**. `pg_stat_activity_count`
   carries `datname, state, usename, backend_type, wait_event, wait_event_type`;
   `pg_settings_max_connections` carries none of them. **Nothing ever matched** → empty vector →
   and the rule is self-filtering, so empty → NoData → `noDataState=OK` → **"Normal"**. Permanently
   green, permanently blind — it would have failed to fire at **100%** connection saturation.

   **Not caused by the keep-list.** Verified: the expression returns 0 series both now *and* 2h
   before the keep-list deployed, with both inputs present the whole time. This defect is original.
   Same family as BUG-008/009/011: *the failure disabled its own detector.*

   **Fix (verified live — production 2/100 = 0.02, staging 2/100 = 0.02):**
   ```promql
   sum by (env) (pg_stat_activity_count)
     / max by (env) (pg_settings_max_connections) > 0.8
   ```
   ✅ Corrected in `infra/grafana/alerts/alert-rules.yaml` (uncommitted).
   ⚠️ **The LIVE Grafana rule is still the broken one** — it was deliberately not rewritten
   (out of scope of a "verify" instruction, and it is a pre-existing prod alert). **Apply the new
   expression to the live rule, then re-assert `isPaused: false`.**

   **Worth a wider audit:** an automated sweep of all 23 rules found this is the only one whose
   *inputs exist but whose expression can never match*. Several others (`KillSwitchTriggered`,
   `AuditIntegrityFailure`, `BacktestFailureRate`, the burn-rate pair) currently have **no series** —
   but those are **labeled counters awaiting their first event** (`increase(...) > 0` fires the
   moment one occurs). That is correct behaviour, not a defect. Do not conflate the two.
