# Development plan — Grafana reduced form (observability rightsizing after the OSS pivot)

**Date:** 2026-08-01
**Owner:** Yuval
**Status:** READY FOR IMPLEMENTATION — adversarially reviewed 2026-08-01; all 16 findings resolved in-place (§11). Nothing merged, nothing changed in prod yet.
**Branch:** `chore/observability-reduced-scope` → single PR to `main`
**Companion docs:** `docs/adr/102-observability-topology.md` (the topology this plan amends),
`project-plan/PIVOT-TO-OSS.md` (D5 — the constraint this plan respects),
`docs/runbooks/alerting-setup.md`, `docs/runbooks/worker-metrics-scrape.md`,
`bugs/BUG-005`, `bugs/BUG-008`, `bugs/BUG-009` (the history that shapes the traps below)

---

## 0. Why

Since 2026-07-15 StratTraderPro is open-source, self-hosted, and the production Railway
environment serves exactly one person. The M10 observability stack was sized for a hosted
service: 6 dashboards, 20 alert rules as code (18 in `alert-rules.yaml` + 2 in
`usage-alerts.yaml`) plus 3 hand-made auth rules living only in Grafana Cloud, SLO/error-budget
framing (`docs/slo.md`), and two Prometheus exporter services whose entire committed consumer
surface is **one** warning alert (`DBConnectionSaturation`) — see the measured budget block in
`infra/grafana-agent/agent.yaml` ("~7,000 series were being ingested to serve TWO").

What must NOT be lost is the part Sentry cannot do: **detecting silence.** This project's
signature failure (bugs/README.md, PROGRESS M10 close-out) is "wired, reports healthy,
completely inert" — paused-on-import rules (BUG-009), gunicorn-masquerading-as-celery
(BUG-011, caught by `TargetDown` within 60s of going live), a dead pipeline reading as green
(BUG-008). The reduced form keeps the dead-man's switch, the money/safety alerts, and the
budget guards; it retires the service-era layer (SLOs, research-pipeline alerts, per-user-base
dashboards, exporters).

**Goal:** one PR + ~1 hour of operator work that shrinks the stack to
**11 live alert rules, 3 dashboards, and 2 fewer Railway services**, with zero loss of
"my bot is silently broken while real money moves" coverage.

---

## 1. Non-goals — explicitly untouched

| Untouched | Why |
|---|---|
| Sentry (backend `prod.py` init, frontend `main.ts` init, DSN plumbing, GitHub wiring) | Out of scope by design — Sentry is the keep-as-is half of the observability answer |
| OTel + Tempo export (`config/otel.py`, Sentry↔Tempo click-through, ADR-102 §4/§5) | Zero marginal infra (exporter lives inside existing processes); high debug value; removing it saves nothing operational |
| `/metrics` topology (`config/metrics_endpoint.py`, WSGI wrap, basic auth) — ADR-102 §1 | Unchanged; it is what feeds the kept alerts |
| Task-process metrics ports (`config/task_metrics.py`, `TASK_METRICS_PORT`, worker 9101 / worker-backtest 9102 / beat 9103 / streams 9104) — ADR-102 §2 | The kept safety alerts (kill-switch, queue depth, stream heartbeat, audit) read these series |
| Every `apps/*/metrics.py` emitter (incl. `sentiment_*`, `hmm_*`, `backtest_*`) | **No backend runtime changes** — zero executable lines touched. One docstring truth-sync is allowed: `apps/users/metrics.py:5-7` references the retired Auth Health dashboard/rules (WP-6). Retiring a rule ≠ retiring the series; series stay queryable in Explore and cost ~nothing post-BUG-005 |
| `contact-points.yaml`, `notification-policy.yaml`, `usage-alerts.yaml` | Kept verbatim (critical → email+Telegram, warning → email; both budget rules stay) |
| `GRAFANA_URL` runtime config, `admin-health.component.ts` link, `en.json:966`, `NGINX_ENVSUBST_FILTER`, `scripts/check_envsubst_filter.py`, `ci.yml` | Zero frontend/CI changes → no ng/ngc/karma gates needed for this PR (CI still runs them; they are unaffected) |
| `infra/grafana-agent` scrape_interval 60s + `METRICS_BASIC_AUTH_*` | `ScrapeIntervalBudgetTests` enforces ≥60s (BUG-005); backend job auth stays |
| PIVOT-TO-OSS **D5** ("Keep `infra/grafana*`") | Respected in its binding sense: the CI-required files (`infra/grafana/alerts/*.yaml`, `infra/grafana-agent/agent.yaml`) stay. D5's *rationale* is CI coupling (`test_alert_rules.py`), which does not extend to the 3 dashboard JSONs this plan deletes — ADR-109 records the narrowed reading |
| `bugs/` history, shipped milestone plans, EXECUTION-REPORTs, `docs/ops/` evidence records, `docs/adr/106-load-test-target.md`, `backend/loadtest/README.md`, `CHANGELOG.md` shipped entries | Historical/evidence record; the house rule is "rewriting a closed exit gate falsifies history". These retain pre-reduction wording (exporters, six dashboards, SLOs) by design — §6 grep gates whitelist them explicitly, and ADR-109 notes the convention. (`docs/postmortem-template.md` is NOT on this list — it is a living template and gets its `docs/slo.md` citations fixed in WP-7) |

---

## 2. Decisions

| # | Decision |
|---|---|
| D-R1 | **The Grafana Cloud pipeline stays** (free tier, grafana-agent, alerts-as-code, email+Telegram paging). Sentry cannot alert on absence; the alternative (uptime pings + Sentry crons) cannot express `broker_stream_heartbeat_age_seconds > 120` or kill-switch semantics without rebuilding what already works |
| D-R2 | **Rule set 18 → 9 in `alert-rules.yaml`** (+2 kept in `usage-alerts.yaml` = 11 live). Keep = protects money in flight, instance integrity, or the alerting pipeline itself. Retire = SLO framing, research pipelines, latency tuning, or rules whose only data source is an exporter being deleted. Full table in §3 |
| D-R3 | **Delete the 3 hand-made auth rules + the `StratTraderPro Auth` folder in Grafana Cloud** (tracker 01.11.5: **folder** UID `cfkrwjgh3sxkwa`, dashboard uid `stp-auth-health` at `/d/stp-auth-health`, `auth-health-email` contact point). They exist only in the cloud, violating the ADR-102 §6 alerts-as-code invariant. App-layer protections remain (ADR-108 IP-scoped lockout, rate limiting, MFA, Sentry) |
| D-R4 | **Dashboards 6 → 3.** Keep `trading-ops` (money view), `risk-ops` (kill-switch/queue view), `system-health` (pipeline/liveness view). Delete `auth-health`, `data-pipelines`, `backtest-ops` from repo AND cloud. Kept dashboards get minimal edits (§4 WP-5): SLO retitles + removal of panels that point at deleted things |
| D-R5 | **Delete both exporter services everywhere** (Railway, compose, agent scrape jobs). Post keep-list they ship ~10 series each, but they still cost 2 Railway services, 2 compose services, secrets (a DB DSN inside a 3rd-party exporter image), and upkeep — to serve one warning alert (retired by D-R2) and four never-built system-health panels (deleted by WP-5) |
| D-R6 | **The dead-man's pair is untouchable:** `MetricsPipelineDown` (absent(), critical) + `TargetDown` (`up == 0`, critical). `DeadMansSwitchTests` in `test_alert_rules.py` enforce both exist — this plan keeps that test intact deliberately |
| D-R7 | **SLO framing is retired.** `docs/slo.md` is deleted (PIVOT WP-3 already classified SLOs as "things a *service* has"); kept alerts keep their thresholds but are documented as plain safety thresholds, not error budgets. `ApiErrorBudgetFastBurn`/`SlowBurn` retire; `WebhookErrorRatioWarn/Crit` remain the symptom-level coverage |
| D-R8 | **Ordering rule for the live cutover:** agent config with exporter jobs removed deploys **before** the exporter services are deleted. Deleting services first ⇒ `up == 0` ⇒ `TargetDown` pages critical. (§5 O-4) |
| D-R9 | **The daily scheduled audit gets a new spec** (§4 WP-8). It currently asserts "all targets up / zero paused rules" against the *old* shape; left stale it either false-alarms after the exporter removal or silently checks too little. It is a Cowork scheduled task, not a repo file — the spec ships in this plan and the audit is updated (or recreated) from it |
| D-R10 | **New ADR-109 records all of this**; ADR-102 gets a one-line "Amended by ADR-109" banner (its body is not rewritten — history stays honest) |

---

## 3. Target state

### 3.1 Alert rules (code truth after the PR: 11)

`infra/grafana/alerts/alert-rules.yaml` — **KEEP 9 of 18:**

| Group (kept count) | Rule | Sev | Why it survives a single-user instance |
|---|---|---|---|
| `trading-ops` (4/5) | `WebhookErrorRatioWarn` | warning | Early warning for the crit below (replaces slow-burn) |
| | `WebhookErrorRatioCrit` | critical | Missed webhooks = missed trades |
| | `BrokerStreamSilent` | critical | Trading blind — fills/acks not arriving |
| | `KillSwitchFlattenSlow` | critical | Risk not being cut on time (measured live: p99 0.17–0.20s vs 5s threshold) |
| `risk-and-queues` (2/4) | `CeleryQueueDepthHigh` | warning | Order-flow queue backlog = delayed placement (also covers a wedged `backtest` queue) |
| | `KillSwitchTriggered` | critical | A kill switch engaged — must be confirmed intentional |
| `platform-and-audit` (1/2) | `AuditIntegrityFailure` | critical | Tamper/corruption of the hash chain — potential security incident |
| `observability-liveness` (2/2) | `MetricsPipelineDown` | critical | Dead-man's switch: alerting is blind (BUG-008) |
| | `TargetDown` | critical | Per-target death (caught BUG-011 in 60s) |

**RETIRE 9 of 18** (delete from YAML; delete live objects in cloud):

| Rule | Group | Why it goes |
|---|---|---|
| `OrderSubmitLatencyHigh` | trading-ops | Latency *tuning* signal, not a safety control; the p95 panel stays on trading-ops |
| `SentimentLag` | risk-and-queues | M07 scorers are code-merged with **no live output** (PROGRESS) — the alert has never had signal; sentiment degrades gracefully by design |
| `HMMModelStale` | risk-and-queues | Same M06 status; regime falls back to rule-only classification (AC-06-8) |
| `DBConnectionSaturation` | platform-and-audit | Sole consumer of both exporters (agent.yaml budget block). Symptom coverage: `WebhookErrorRatioCrit` + Sentry `OperationalError` + Railway PG dashboard |
| `BacktestQueueWaitHigh`, `BacktestFailureRate`, `BacktestArtifactBloat` | backtest-ops (group deleted) | Research ops, not money in flight; `backtest-stuck.md` remains the manual path; `CeleryQueueDepthHigh` still catches a dead backtest queue |
| `ApiErrorBudgetFastBurn`, `ApiErrorBudgetSlowBurn` | slo-burn-rate (group deleted) | Error-budget semantics retired with the service posture (D-R7) |

`infra/grafana/alerts/usage-alerts.yaml` — **KEEP 2 of 2:** `MetricsBudgetHigh` (warning),
`MetricsBudgetExhausted` (critical). They guard the free tier the whole pipeline rides on
(BUG-005: over-budget ⇒ dropped series ⇒ self-filtering rules go silently green).

Grafana Cloud extras — **DELETE:** the 3 hand-made rules in the `StratTraderPro Auth` folder
(D-R3). After cleanup, the provisioning API must list **exactly the 11 code rules**.

### 3.2 Dashboards (6 → 3)

| Dashboard | Fate |
|---|---|
| `trading-ops-dashboard.json` | KEEP; retitle SLO row/panels (WP-5) |
| `risk-ops-dashboard.json` | KEEP; retitle SLO row/panel (WP-5) |
| `system-health-dashboard.json` | KEEP; delete "Sibling: Auth Health" link panel + the "Postgres / Redis / Celery — exporter follow-up" row incl. its "Why these panels are empty" text panel (WP-5) |
| `auth-health-dashboard.json` | DELETE (repo + cloud) |
| `data-pipelines-dashboard.json` | DELETE (repo + cloud) |
| `backtest-ops-dashboard.json` | DELETE (repo + cloud) |

### 3.3 Services & scrape topology

| | Before | After |
|---|---|---|
| Railway services (observability) | grafana-agent, postgres-exporter, redis-exporter | grafana-agent |
| agent.yaml scrape jobs | 7 (backend, worker, worker-backtest, beat, streams, postgres-exporter, redis-exporter) | 5 |
| compose services | …incl. postgres-exporter, redis-exporter | both removed |
| `up` targets in prod | 7 | 5 |
| Live alert rules (cloud) | 20 code + 3 hand = up to 23 | 11 |
| Dashboards (cloud) | 6 (+ the M01 Auth Health objects: folder `StratTraderPro Auth`, dashboard `/d/stp-auth-health`, contact point `auth-health-email`) | 3 |

**Environment inventory (verify, don't assume):** `production` is the ONLY Railway
environment — staging (and its ~12 services, including its agent + exporters) was deleted
2026-07-15 in the OSS-pivot tail cleanup (PROGRESS, OSS-pivot section). Repo docs dated
2026-07-13/14 still describe 14 targets (7 × 2 envs); they predate that deletion. Every
live query in §5/WP-8 is written env-scoped anyway, and O-4 step 2 asserts no stray
`env` label values survive — if anything other than `production` shows up, stop and
inventory before proceeding.

---

## 4. Work packages (repo — one PR)

### WP-1 — Prune `infra/grafana/alerts/alert-rules.yaml` (18 → 9 rules)

- Delete the 9 retired rules from §3.1 **by name** (line numbers drift; names are the spec).
  Two deletions are whole groups: `backtest-ops` and `slo-burn-rate` (including their
  `- name:/folder:/interval:` headers). The other four groups stay with their remaining rules.
- Delete the `DBConnectionSaturation` explanatory comment block that precedes its expr inside
  `platform-and-audit` (the "connection-count proxy" / label-shape commentary) — the comment
  must not outlive the rule.
- File header states no counts (verified) — no header edit needed.
- Touch up the kept BUG-008 comment block (~:161-163): "would have turned all 17 rules
  green" → "all rules green", and drop its "or an exporter dying" example (exporters are
  gone). Two-line wording fix so the kept comment doesn't contradict the file it sits in.
- ⚠️ Do NOT touch `MetricsPipelineDown` / `TargetDown` (D-R6) — `DeadMansSwitchTests`
  requires ≥1 `absent()` rule labeled critical and ≥1 `up == 0` rule. Verified: the ONLY
  `absent()` expr in the file is MetricsPipelineDown's and the only `up == 0` is
  TargetDown's — no retired rule contributes to either invariant.
- **AC-WP1:** `python -c "import yaml,sys; yaml.safe_load(open('infra/grafana/alerts/alert-rules.yaml'))"`
  parses; exactly 9 `- alert:` lines remain; groups present = `trading-ops`,
  `risk-and-queues`, `platform-and-audit`, `observability-liveness`.

### WP-2 — `infra/grafana/alerts/usage-alerts.yaml`, `contact-points.yaml`, `notification-policy.yaml`

- **No changes.** Listed as a work package only so the diff reviewer knows the absence is
  deliberate (D-R2 keeps both budget rules; routing semantics unchanged).

### WP-3 — `infra/grafana-agent/agent.yaml` (7 → 5 scrape jobs)

- Delete the `postgres-exporter` and `redis-exporter` `job_name:` blocks (targets,
  labels, and their `metric_relabel_configs` keep-lists).
- Rework the "ACTIVE-SERIES BUDGET (2026-07-13)" comment block: keep the measured history
  (it is the justification of record for BUG-005 and for this deletion) but (a) append one
  line — exporters removed entirely per ADR-109 — and (b) reword the "what actually
  CONSUMES those exporter series" lines to past tense so the retired rule name reads as
  history ("…consumed only by the now-retired `DBConnectionSaturation`"), keeping §6's
  retired-names gate clean without whitelisting agent.yaml.
- **Keep the `!! THE TRAP !!` paragraph about `up`**, with one wording fix: "pinned first
  in every keep regex below" → "must be pinned first in any future keep regex" (after this
  WP no keep-regexes remain — the backend job's only relabel is a `drop`). Also drop
  "/exporter" from the header comment's env-var list (~:11).
- Do not touch `scrape_interval: 60s` (CI-enforced), `external_labels`, `remote_write`,
  the backend job's `basic_auth`, or the worker/beat/streams jobs.
- **AC-WP3:** yaml parses; `grep -c 'job_name:' == 5`; `grep -riE 'POSTGRES_EXPORTER|REDIS_EXPORTER|DBConnectionSaturation' infra/grafana-agent/`
  returns nothing.

### WP-4 — `docker-compose.yml`

- Delete the two services under `# ---------- Prometheus exporters (M10 §6.5d) ----------`
  (`postgres-exporter` at ~:154, `redis-exporter` at ~:162) including the section comment.
  Nothing `depends_on` them (verified — only they depend on postgres/redis).
- `docker-compose.ac113.yml` / `docker-compose.loadtest.yml`: verify no exporter references
  (none expected; the load stack uses its own overrides). If any exist, delete there too.
- **AC-WP4:** `docker compose config -q` succeeds; `grep -n exporter docker-compose*.yml` → empty.

### WP-5 — Dashboard edits + deletions (`infra/grafana/`)

- `git rm auth-health-dashboard.json data-pipelines-dashboard.json backtest-ops-dashboard.json`.
- ⚠️ Editing mechanics: non-ASCII characters in these JSONs are stored escaped
  (`SLO ≤ 1.5s`, `—`), so literal `≤`/`—` search-and-replace won't match the raw
  files — match the escaped forms (the string `SLO` itself is plain ASCII and greps fine).
  No query/datasource/uid changes anywhere; dashboard UIDs must not change (re-import
  updates in place, alerting-setup.md Step 1). Panel `id`s / `gridPos` of survivors stay
  as-is (Grafana tolerates gaps; do not renumber).
- `system-health-dashboard.json`:
  - delete the "Sibling: Auth Health" entry from the top-level `links` array (~:22-34 —
    it is a dashboard link, not a panel);
  - rewrite the top-level `description` (~:18) — it still advertises "Sibling dashboard:
    Auth Health (/d/stp-auth-health)" and the "placeholder rows … (Postgres/Redis/Celery
    exporters)";
  - delete the "Postgres / Redis / Celery — exporter follow-up" row (id 400, an empty
    row header) **and** its companion text panel id 10 ("Why these panels are empty");
  - SLO scrub this file too (missed in rev 1): row `:1140` "SLO & Incidents" →
    "Targets & Incidents"; `:1153` "Request error ratio (SLO < 0.1%)" →
    "(target < 0.1%)"; `:1221` "Backend availability (SLO 99.9%)" →
    "Backend availability (target 99.9%)"; plus the SLO mentions in those panels'
    `description` fields (`:1154`, `:1222`).
- `trading-ops-dashboard.json`: row "SLO & Incidents" → "Targets & Incidents"; panel
  "Order submit p95 (SLO ≤ 1.5s)" → "(target ≤ 1.5s)"; panel "Webhook error ratio
  (SLO < 1%)" → "(target < 1%)"; **and** the residual SLO strings in `description`
  fields (~:483, :552) and `legendFormat` values (~:544, :615).
- `risk-ops-dashboard.json`: row "SLO & Incidents" → "Targets & Incidents"; panel
  "Kill-switch flatten p99 (SLO ≤ 5s)" → "(target ≤ 5s)"; **and** the `description` at
  ~:352 ("AC-08-8 SLO: p99 flatten latency ≤ 5s" → "AC-08-8 target: …") and
  `legendFormat` at ~:409.
- **AC-WP5:** each kept JSON individually passes
  `for f in infra/grafana/*-dashboard.json; do python -m json.tool "$f" >/dev/null || echo "BAD $f"; done`
  (json.tool takes ONE infile — a multi-arg/brace-expanded call either errors or silently
  overwrites the second file); `grep -l 'pg_\|redis_'` over the 3 kept dashboards → empty;
  `grep -l 'SLO'` over the 3 kept dashboards → empty; `grep -l 'stp-auth-health'` over
  them → empty; the deleted filenames appear nowhere outside `project-plan/` history docs,
  `bugs/`, and `CHANGELOG.md` shipped entries.

### WP-6 — `backend/config/test_alert_rules.py` (tidy, no behavior change)

- Prune `_EXTERNAL` of the now-unreferenced exporter series: `pg_stat_activity_count`,
  `pg_settings_max_connections`, `pg_up`, `redis_up`, `redis_connected_clients`.
  **Keep `up`** (TargetDown), keep all `django_*` and `grafanacloud_*` entries.
- Update the module docstring's "(django_prometheus + postgres/redis exporters)" phrase to
  "(django_prometheus + Grafana Cloud usage series)".
- Everything else stays: the sanity assertions (`audit_integrity_check_total`,
  `celery_queue_depth`, `sentiment_queue_oldest_age_minutes`) still pass because
  `apps/*/metrics.py` emitters are untouched (definitions verified at
  `apps/audit/metrics.py:20`, `apps/admin_portal/metrics.py:13`, `apps/sentiment/metrics.py:19`);
  `DeadMansSwitchTests` and `ScrapeIntervalBudgetTests` still pass because WP-1/WP-3
  preserve their invariants.
- **Docstring truth-sync (the one permitted backend touch, §1):**
  `backend/apps/users/metrics.py:5-7` — "The Auth Health dashboard
  (https://YOUR_ORG.grafana.net/d/stp-auth-health) and its three alert rules all read
  these series" → "These series are queryable in Grafana Explore; the M01 Auth Health
  dashboard + rules that read them were retired by ADR-109." Zero executable lines change.
- **AC-WP6:** `pytest backend/config/test_alert_rules.py` green; `git diff --stat backend/`
  shows exactly two files (`config/test_alert_rules.py`, `apps/users/metrics.py`) with
  comment/allowlist-only changes.

### WP-7 — Documentation

| File | Change |
|---|---|
| **NEW** `docs/adr/109-observability-reduced-scope.md` | Status: Accepted. Context (OSS pivot, single operator), Decision (D-R1…D-R10 condensed), Consequences incl. an honest "coverage lost" table (DB saturation early warning; backtest ops alerts; auth-anomaly alerts; order-latency alert) with mitigations, and the D5 narrowed reading (§1). "Amends: ADR-102" |
| `docs/adr/102-observability-topology.md` | One-line banner under the Status line: `**Amended by:** ADR-109 (2026-08) — exporters removed, rule set reduced to the safety core, dashboards 6 → 3.` Body untouched |
| `docs/slo.md` | **DELETE** (D-R7). Its two still-alerted thresholds (webhook 5xx ratio, flatten p99) live on in `alert-rules.yaml` + `incident-triage.md` as plain thresholds |
| `docs/runbooks/incident-triage.md` | Delete the 7 retired rows (`OrderSubmitLatencyHigh`, `SentimentLag`, `HMMModelStale`, `DBConnectionSaturation`, 3× Backtest). In the kept `WebhookErrorRatioCrit` row (:36): drop the `docs/slo.md` pointer, reword "the webhook-availability SLO (99.9%) is at risk" → "sustained server errors — missed webhooks are missed trades". In `KillSwitchFlattenSlow` (:39): drop the `docs/slo.md (flatten SLO p99 ≤ 5s)` pointer. Also scrub the two slo.md refs OUTSIDE the table: the companion-docs line (:11, "`docs/slo.md` (the four SLOs…)") and the after-a-critical step (:77, "note the error-budget impact per `docs/slo.md`" → "note the trading impact"). **Add 4 rows** (verified absent today): `MetricsPipelineDown` + `TargetDown` (critical — they page and had no triage row even before this plan) and `MetricsBudgetHigh`/`MetricsBudgetExhausted` (fires → check scrape interval FIRST per BUG-005, don't delete metrics). Keep the intro sentence "Severity and thresholds are taken verbatim from `alert-rules.yaml`" true |
| `docs/runbooks/alerting-setup.md` | "Six dashboards" list (:18-21) → the three kept files; Step 1 wording "six" → "three" (:33); Step 3 group list (:72) → `trading-ops, risk-and-queues, platform-and-audit, observability-liveness`; **and the third instance at :169** — definition-of-done "The six dashboards render with data (task-process/exporter panels populate once…)" → "The three dashboards render with data". Keep the ⛔ BUG-009 stop-box **verbatim** (it applies to any future re-import); Step 5 unchanged |
| `docs/runbooks/worker-metrics-scrape.md` | Delete `POSTGRES_EXPORTER_TARGET`/`REDIS_EXPORTER_TARGET` from the env block (:75-76); delete the whole "Provisioning the exporter services on Railway" section (:84-97); in the verification list (:113-120): drop `pg_stat_activity_count`, `SentimentLag`, `DBConnectionSaturation` (keep `CeleryQueueDepthHigh`, `AuditIntegrityFailure`, kill-switch), **drop the "postgres / redis → 1" up-target assertions (:116-117)**, and fix :119 "the task-process and exporter panels on the six dashboards populate" → "the task-process panels on the three dashboards populate". Update the header's "the postgres/redis exporters exist" clause (:7) |
| `docs/postmortem-template.md` | Living template, not history: replace its two `docs/slo.md` citations (:9, :33) — impact section points at `incident-triage.md` + the alert thresholds in `alert-rules.yaml` instead |
| `docs/runbooks/backtest-stuck.md` | :215 — replace the "Backtest Ops Grafana dashboard" pointer with: the `backtest_*` series remain exported and queryable in Grafana Explore; the dashboard was retired by ADR-109 |
| `setup-guides/grafana-setup.md` | Banner under the header: superseded in part by ADR-109 — the Auth Health dashboard + 3 auth alerts it builds are retired; §0–§3 (workspace, token, agent bring-up, `ALLOWED_HOSTS` gotcha) remain the valid bring-up reference. Also fix its system-health "Six rows" walk-through (:144-148), which lists the deleted exporter follow-up row and uses underscore spellings (`postgres_exporter`, `redis_exporter`) that §6's hyphen pattern would miss |
| `infra/grafana-agent/README.md` | Remove exporter-target rows if present (grep found none — verify during implementation, likely no-op) |
| `README.md` :105 | No change (already "optional integrations — all off by default"). Optionally append "(reduced scope: ADR-109)" — implementer's call |
| `CHANGELOG.md` `[Unreleased]` | **Changed:** observability reduced to the safety core (11 alerts, 3 dashboards) per ADR-109. **Removed:** postgres/redis exporters (compose + Railway), backtest/SLO-burn alert groups, auth-health & data-pipelines & backtest-ops dashboards, `docs/slo.md` |
| `project-plan/PROGRESS.md` | Add a dated block under the OSS-pivot section: "2026-08-XX observability rightsizing (ADR-109, `development-plans/2026-08-01-grafana-reduced-form.md`): 23→11 live alerts, 6→3 dashboards, exporters deleted, slo.md retired." Do NOT rewrite the M10/M11 rows (closed milestones) |
| **THIS PLAN FILE** → `development-plans/2026-08-01-grafana-reduced-form.md` | Commit the plan itself (the directory exists with two dated precedents; verified 2026-08-01). Without this, PROGRESS's pointer above dangles |
| `bugs/BUG-009…md`, `bugs/BUG-005…md` | Truth-sync the stale **Status** headers only: BUG-009 `OPEN — needs operator authorization` → `CLOSED — authorized and un-paused during the 2026-07-11 live bring-up (PROGRESS M10 close-out)`; BUG-005 `awaiting agent deploy` → `deployed + verified (M11 operator report)`. No other edits — the bodies are the historical record |

### WP-8 — Daily scheduled audit (new spec)

The audit is a Cowork scheduled task, not a repo file (nothing in `scripts/` or
`.github/workflows/` implements it; `scripts/audit-gate.mjs` is the unrelated frontend
dependency-audit CI gate). It currently asserts the OLD shape ("zero paused rules, all
targets up, beat→queue→worker loop fresh, budget, frontend config" — PROGRESS :84).

- Operator: open the desktop app's scheduled tasks, locate the daily StratTraderPro audit
  (it is not visible to cloud sessions' trigger list; if it was deleted, recreate it), and
  replace its assertion spec with:
  1. Provisioning API: rule titles == exactly the 11 §3.1 rules; `isPaused == false` for all;
     the `StratTraderPro Auth` folder does not exist.
  2. `up{env="production"}` == 1 for exactly 5 targets: backend, worker, worker-backtest,
     beat, streams — **no `up` series for any other job label, and no `env` label value
     other than `production`** (guards against a forgotten second environment; see §3.3
     environment inventory).
  3. beat→queue→worker loop fresh (unchanged assertion).
  4. Budget rate `sum(grafanacloud_instance_samples_per_second) * 60 / scalar(grafanacloud_org_metrics_included_series)` < 0.85 (unchanged).
  5. Frontend `STP_CONFIG` check (unchanged).
  6. Report only on failure (unchanged).
- **AC-WP8:** the audit's first post-change run is green; deliberately pausing one rule in a
  drill makes it report (proves it still detects the BUG-009 class).

---

## 5. Operator track `[LIVE]` — Grafana Cloud + Railway, in this order

> Everything here happens AFTER the PR is merged. The order exists because of D-R8; do not
> reorder. Total ~45–60 min.

### O-1 — Backup (before touching anything)

- `GET /api/v1/provisioning/alert-rules` → save the full JSON locally (captures cloud drift
  the repo doesn't have — the hand-made auth rules, any threshold tweaks).
- Export the 6 current dashboard JSONs from the cloud UI (Share → Export) into a local
  folder. (The repo has committed versions, but the cloud copies are the rollback truth.)

### O-2 — Grafana Cloud: rules

1. Import the updated `alert-rules.yaml` (+ `usage-alerts.yaml` against the
   **`grafanacloud-usage`** datasource — unchanged but re-imported if the tool replaces the
   folder wholesale).
2. ⛔ **BUG-009 gate:** converted rules import **paused**. Run the runbook snippet —
   `rules.filter(r => r.isPaused).map(r => r.title)` — and un-pause until it returns `[]`.
3. Delete the 9 retired rules' live objects by UID
   (`DELETE /api/v1/provisioning/alert-rules/{uid}` with `X-Disable-Provenance: true`), then
   the 3 rules in `StratTraderPro Auth` and that folder + its `auth-health-email` contact
   point (D-R3).
4. **Gate:** provisioning API lists exactly 11 rules, all `isPaused: false`, folders =
   `StratTraderPro` only.

### O-3 — Grafana Cloud: dashboards

- Delete the Data Pipelines and Backtest Ops dashboards, and the M01 Auth Health objects:
  dashboard `/d/stp-auth-health`, folder `StratTraderPro Auth` (folder UID
  `cfkrwjgh3sxkwa`) with its 3 rules (already deleted in O-2.3 — verify), and the
  `auth-health-email` contact point.
- Re-import the 3 edited kept dashboards (same UIDs → update in place).
- **Gate:** exactly 3 StratTraderPro dashboards; the retitled panels render; no panel shows
  a datasource error.

### O-4 — Railway (order matters — D-R8)

1. Redeploy **grafana-agent** from the merged commit (its config no longer has exporter
   jobs), and delete the now-unused `POSTGRES_EXPORTER_TARGET` / `REDIS_EXPORTER_TARGET`
   env vars from the service.
2. Wait one scrape+eval cycle (~2 min), confirm in Explore:
   `count by (job, env) (up)` → exactly backend / worker / worker-backtest / beat / streams,
   all with `env="production"` only, all 1. Any other `env` value here means a second
   agent is still shipping somewhere — stop and inventory (§3.3) before step 3.
3. **Only now** delete the `postgres-exporter` and `redis-exporter` Railway services.
   (Reverse order ⇒ `up == 0` ⇒ `TargetDown` pages critical for ~minutes. If you must
   delete first, create a 1h silence on `TargetDown` scoped to `service=~"postgres|redis"` —
   but the ordering is simpler than the silence.)

### O-5 — Live verification (AC-10-9 pattern, reduced)

1. Zero paused rules (snippet) — again, after all imports.
2. `up` set correct (O-4.2) and `MetricsPipelineDown`/`TargetDown` in state Normal.
3. **Trip one real rule** exactly as alerting-setup.md Step 5 prescribes (lower the
   threshold on the committed rule object, watch Telegram + email fire, restore) — not a
   scratch rule. Suggested: `CeleryQueueDepthHigh` (harmless, fast to trip and restore).
4. Budget rate < 0.85 (usage-alerts formula) — expect a small drop vs. pre-change.
5. Update + run the daily audit (WP-8); confirm green, then confirm it FAILS when you pause
   a rule for 5 minutes (drill), then un-pause.

---

## 6. Verification gauntlet (local, before the PR)

Run in the container/CI-parity environment (the repo venv is not usable from cloud sessions):

| Gate | Command | Expect |
|---|---|---|
| YAML sanity | `python -c "import yaml; yaml.safe_load(open('infra/grafana/alerts/alert-rules.yaml')); yaml.safe_load(open('infra/grafana-agent/agent.yaml'))"` | no error |
| Rule count | `grep -c '^      - alert:' infra/grafana/alerts/alert-rules.yaml` | 9 |
| Dead-man pair | `grep -c 'absent(' alert-rules.yaml` ≥1 and `grep -c 'up == 0'` ≥1 | both present |
| Alert cross-check + invariants | `pytest backend/config/test_alert_rules.py -q` | green |
| Full backend gauntlet | `ruff check backend` · bandit exactly as CI runs it (`ci.yml:77`): `cd backend && bandit -r apps/ config/ -x tests -q --severity-level medium` · full `pytest` | green |
| Compose | `docker compose config -q` (and the ac113/loadtest files) | green |
| Dashboards parse | `for f in infra/grafana/*-dashboard.json; do python -m json.tool "$f" >/dev/null \|\| echo "BAD $f"; done` — one file per invocation (multi-arg json.tool errors or, worse, overwrites arg 2 with arg 1's output) | no BAD lines |
| Grep gate — exporters | `grep -rniE 'postgres[-_]exporter\|redis[-_]exporter\|EXPORTER_TARGET' --exclude-dir={.git,node_modules,.venv,.pnpm-store,coverage,.angular,dist} .` (note `[-_]`: grafana-setup.md used underscore spellings) | hits ONLY in the §1 whitelist: `project-plan/` reports+archived, `bugs/`, `docs/adr/102`, `docs/adr/106`, `docs/ops/`, `backend/loadtest/README.md`, `CHANGELOG.md`, this plan. (`OTEL_EXPORTER_OTLP_ENDPOINT` does not match these patterns — untouched by design) |
| Grep gate — retired rules | same exclude-dirs, pattern = the 9 retired rule names | hits only in the same §1 whitelist + this plan. agent.yaml must NOT appear (WP-3 rewords its comment) |
| Grep gate — slo.md | `grep -rn 'slo\.md' …` | zero refs outside `project-plan/` history, `docs/ops/`, CHANGELOG. In particular: `incident-triage.md` (:11, :36, :39, :77) and `postmortem-template.md` (:9, :33) must be clean after WP-7 |
| Grep gate — deleted dashboards + auth uid | filenames of the 3 deleted JSONs **and** `stp-auth-health` | zero refs outside history docs + CHANGELOG. In particular `apps/users/metrics.py` (WP-6 docstring) and `system-health-dashboard.json` `description`/`links` (WP-5) must be clean |
| Frontend | none required (zero frontend changes) — CI's ng build/test run regardless and are unaffected | green |

---

## 7. Rollback

Everything is one PR + reversible operator actions:

1. `git revert` the PR (restores rules YAML, agent jobs, compose services, dashboards, docs).
2. Grafana Cloud: re-import the O-1 backup (`PUT` each rule back; re-import the 6 dashboard
   JSONs). ⚠️ re-imported rules arrive **paused** — run the BUG-009 gate again.
3. Railway: recreate `postgres-exporter` / `redis-exporter` per the reverted
   `worker-metrics-scrape.md` §"Provisioning the exporter services" (images + env are fully
   specified there); re-add `POSTGRES_EXPORTER_TARGET` / `REDIS_EXPORTER_TARGET` to
   grafana-agent; redeploy agent.
4. The daily audit spec reverts to the pre-change assertion list (kept in the O-1 backup
   folder alongside the rule export).

---

## 8. Risks & honest losses

| Risk / loss | Assessment | Mitigation |
|---|---|---|
| No early warning on Postgres connection saturation | Real loss, small blast radius for 1 user; failure surfaces as 5xx | `WebhookErrorRatioCrit` pages on the symptom; Sentry catches `OperationalError`; Railway PG dashboard has the graph |
| No backtest ops alerts | Backtests are research; worst case they queue | `CeleryQueueDepthHigh` catches a dead/wedged queue incl. `backtest`; `backtest-stuck.md` unchanged |
| No auth-anomaly alerts | Public login page, but: ADR-108 lockout, rate limiting, MFA, and Sentry remain; 4xx/429s visible on system-health | Accepted (D-R3); revisit only if the instance ever serves >1 human |
| Re-import re-introduces paused rules | The BUG-009 trap fires on every import | ⛔ gate in O-2/O-5 + the audit's paused-rule assertion (WP-8) |
| Deleting exporter services before the agent redeploy | `TargetDown` pages | D-R8 ordering; silence recipe as fallback |
| Stale audit spec after the change | False alarms (expects 7 targets) or silent under-checking | WP-8 is a blocking part of the plan, not a follow-up |
| A doc/runbook still points at a deleted thing | Confusion months later | §6 grep gates enumerate every name; history docs are whitelisted, living docs are not |

---

## 9. Acceptance criteria (roll-up)

- **AC-R1** `alert-rules.yaml` has exactly the 9 §3.1 rules in 4 groups; `usage-alerts.yaml` unchanged; all YAML parses.
- **AC-R2** `pytest backend/config/test_alert_rules.py` green with the pruned `_EXTERNAL` (and the full backend gauntlet green).
- **AC-R3** agent.yaml has exactly 5 scrape jobs; `scrape_interval: 60s` untouched; compose has no exporter services; `docker compose config -q` green.
- **AC-R4** Kept dashboards: valid JSON (per-file json.tool), zero `pg_*`/`redis_*` queries, zero "SLO" strings (titles, descriptions, legendFormats — incl. system-health :1140/:1153/:1221), zero `stp-auth-health` refs, UIDs unchanged; the 3 retired dashboards deleted from repo.
- **AC-R5** Grafana Cloud lists exactly 11 rules, zero paused, all under `StratTraderPro/` — in practice inside the converter's filename-derived subfolder (`StratTraderPro/stp-alert-rules.prom.yaml`), which `GET /api/folders` does not list, so resolve rule `folderUID`s via `GET /api/folders/{uid}` before asserting; Auth folder `cfkrwjgh3sxkwa` gone; exactly 3 `stp-*` dashboards.
- **AC-R6** Railway: exporter services deleted; agent redeployed first (no `TargetDown` page during cutover, or a documented deliberate silence).
- **AC-R7** `count by (job, env)(up)` == {backend, worker, worker-backtest, beat, streams} × {production} only, all 1 — no stray env label values.
- **AC-R8** O-5 drill: one real kept rule tripped → Telegram + email received → restored.
- **AC-R9** Budget rate < 0.85 post-change.
- **AC-R10** Daily audit updated to the WP-8 spec; green run + failing-drill run both demonstrated.
- **AC-R11** Docs set per WP-7 (ADR-109 exists; ADR-102 banner; slo.md gone; incident-triage has the 4 new rows and no slo.md refs; postmortem-template fixed; runbooks/setup-guide/CHANGELOG/PROGRESS updated; BUG-005/009 status lines truth-synced; `apps/users/metrics.py` docstring synced; this plan file committed under `development-plans/`).
- **AC-R12** §6 grep gates all pass with the §1 whitelist exactly as written.

---

## 10. Execution order & estimate

1. **Commit 1** — WP-1, WP-3, WP-4, WP-6 (rules, agent, compose, test) — the CI-coupled core.
2. **Commit 2** — WP-5 (dashboard deletions + edits).
3. **Commit 3** — WP-7 (ADR-109 + doc sweep + CHANGELOG + PROGRESS + bug status lines + this plan file into `development-plans/`).
4. PR with §6 gauntlet output pasted; merge.
5. Operator track O-1…O-5 (≈45–60 min) + WP-8 audit update.
6. Soak: one full trading day with the reduced set; the daily audit green on day 2 closes the plan.

Repo work: ~2–4 h. Operator work: ~1 h. No user-visible product change; no backend runtime change.

---

## 11. Adversarial review log (2026-08-01)

An independent reviewer verified every claim against the repo and returned 16 findings;
all are resolved in the text above. The record, condensed:

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | BLOCKER | WP-5 rev-1 missed system-health's own SLO strings (:1140/:1153/:1221) + descriptions/legendFormats in all three kept dashboards — its AC was unachievable | WP-5 rewritten to scrub every SLO string; AC unchanged and now reachable |
| 2 | MAJOR | slo.md refs in `postmortem-template.md` (:9,:33), `incident-triage.md` (:11,:77), `docs/ops/load-test-results.md` broke the §6 gate | postmortem-template + the two extra incident-triage lines added to WP-7; `docs/ops/` whitelisted as evidence record |
| 3 | MAJOR | WP-3 kept an agent.yaml comment naming `DBConnectionSaturation`, contradicting §6's retired-names gate | WP-3 now rewords the comment to past tense; agent.yaml must NOT appear in gate hits |
| 4 | MAJOR | Exporter refs in `backend/loadtest/README.md:96`, `docs/ops/service-role-cutover.md:53`, `docs/ops/load-test-results.md`, `docs/adr/106` uncovered | Added to the §1 historical whitelist (evidence records; not rewritten), gate updated to match |
| 5 | MAJOR | Repo docs (dated ≤2026-07-14) imply TWO scraped environments (14 targets); single-env assumption unstated | §3.3 environment-inventory note added (staging deleted 2026-07-15); every live query/AC now env-scoped with a stop-and-inventory guard |
| 6 | MAJOR | No work package committed this plan file to the repo | Added to WP-7 + Commit 3. (Reviewer's claim that `development-plans/` doesn't exist was itself wrong — re-verified on 2026-08-01: it exists with two dated precedents; the missing-commit half of the finding stands) |
| 7 | MAJOR | Invisible leakage: `apps/users/metrics.py:5-7` docstring, system-health top-level `description` + `links`, grafana-setup underscore spellings, uid `stp-auth-health` unmatched by filename greps | WP-6 docstring sync (§1 exception), WP-5 description/links edits, `[-_]` + `stp-auth-health` added to §6 patterns |
| 8 | MINOR | CHANGELOG shipped entries (:313,:497) name deleted dashboards; AC-WP5 whitelist omitted CHANGELOG | Whitelists aligned (CHANGELOG counts as shipped history; the new [Unreleased] entry is WP-7 work) |
| 9 | MINOR | Dead-man pair had no incident-triage rows; rev-1 added rows only for the budget pair | WP-7 adds all 4 rows |
| 10 | MINOR | worker-metrics-scrape :116-117 (postgres/redis up-assertions) and :119 ("six dashboards") uncovered | Added to WP-7 |
| 11 | MINOR | Third "six dashboards" instance at alerting-setup :169 uncovered | Added to WP-7 |
| 12 | MINOR | `cfkrwjgh3sxkwa` is the Auth FOLDER uid, not the dashboard uid (`stp-auth-health`) | D-R3 / §3.3 / O-3 corrected |
| 13 | MINOR | §6 json.tool command was broken (multi-arg errors; 2-arg silently overwrites) | Replaced with a per-file loop everywhere |
| 14 | MINOR | Bandit args didn't match CI (`ci.yml:77` uses `-r apps/ config/ -x tests --severity-level medium`) | §6 quotes the CI command verbatim |
| 15 | MINOR | WP-5 rev-1 misdescribed the JSON objects (links entry vs panel; row 400 + text panel 10; unicode-escaped titles) | WP-5 mechanics corrected |
| 16 | NIT | Kept comments going stale (alert-rules :161-163 "all 17 rules"/exporter example; agent.yaml TRAP "every keep regex below"; header "/exporter") | One-line touch-ups folded into WP-1/WP-3 |

Reviewer's confirmations worth keeping: the keep-9/retire-9 table matches the YAML
name-for-name; the only `absent()`/`up == 0` rules are the kept dead-man pair, so
`DeadMansSwitchTests` survives WP-1 mechanically; `_EXTERNAL` contains exactly the five
entries WP-6 prunes and no kept expr references `pg_*`/`redis_*`; nothing in CI, Makefile,
or scripts reads the dashboard JSONs (the D5 narrowed reading holds); compose has no
`depends_on` the exporters; ADR-109 is the next free number; frontend contains zero
dashboard names/uids (the zero-frontend-changes claim holds).

