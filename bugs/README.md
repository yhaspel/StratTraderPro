# Bug Log

Tracked defects found outside the normal test/CI loop — mostly things that were
**CI-green but broken in production**. Each bug gets its own file so it can be
picked up later without re-deriving the investigation.

## Conventions

- **File name:** `BUG-<NNN>-<kebab-slug>.md`
- **Status:** `OPEN` · `FIXED` · `WONTFIX` · `DEFERRED`
- **Severity:**
  - `S1` — data loss, money loss, or a safety control that silently doesn't work
  - `S2` — a shipped feature is silently non-functional in production
  - `S3` — degraded/misleading behaviour, workaround exists
  - `S4` — cosmetic / papercut
- Every bug records **how it was detected**, because most of these were invisible
  to CI. If a bug could have been caught by a test, the fix must add that test.

## Index

| ID | Title | Sev | Status | Area |
|----|-------|-----|--------|------|
| [BUG-001](BUG-001-otel-web-tier-never-traced.md) | OTel never traced the web tier (entrypoint ordering) | S2 | FIXED | Observability |
| [BUG-002](BUG-002-otlp-endpoint-missing-signal-path.md) | OTLP exporter given base URL; `/v1/traces` never appended | S2 | FIXED | Observability |
| [BUG-003](BUG-003-healthz-reports-stale-git-sha.md) | Frontend shipped `release: ''` — Sentry sourcemaps could never resolve (original "stale SHA" premise was a measurement error) | S3 | **FIXED & VERIFIED** | Deploy/Provenance |
| [BUG-004](BUG-004-nginx-envsubst-filter-too-narrow.md) | Frontend Sentry never worked (nginx envsubst allowlist + empty `SENTRY_DSN`) | S2 | **FIXED & VERIFIED** | Frontend/Config |
| [BUG-005](BUG-005-grafana-free-tier-metrics-limit.md) | "Free tier limit for Metrics" — caused by the **scrape interval**, not the series count | S3 | **FIXED & VERIFIED** (DPM 1.98→0.96) | Observability/Ops |
| [BUG-006](BUG-006-otel-init-log-swallowed.md) | `otel.initialized` log line swallowed (init precedes Django logging config) | S4 | FIXED | Observability |
| [BUG-007](BUG-007-frontend-tests-never-run-in-ci.md) | "Frontend — Lint & Test" CI job ran **neither** lint nor tests — no frontend spec had ever executed | S2 | **FIXED & VERIFIED** (67 specs now run) | CI |
| [BUG-008](BUG-008-no-dead-mans-switch-alerting-fails-silent.md) | No dead-man's switch: a dead metrics pipeline was indistinguishable from "all healthy" | **S1** | **FIXED & VERIFIED** (caught BUG-011 within 60s) | Alerting |
| [BUG-009](BUG-009-all-alert-rules-imported-paused.md) | **Every imported alert rule was PAUSED — the M10 alerting stack had never been able to fire** | **S1** | FIXED (21 live at the time of the fix; 11 after the ADR-109 rightsizing, 0 paused) | Alerting |
| [BUG-010](BUG-010-worker-beat-metrics-endpoints-unscrapeable.md) | celery-worker + celery-beat metrics endpoints unscrapeable in both envs | S2 | CLOSED — symptom of 011 | Observability/Railway |
| [BUG-011](BUG-011-celery-worker-and-beat-are-not-running-celery.md) | **`celery-worker` + `celery-beat` were running gunicorn, not Celery — the default queue had no consumer and beat had never run, in both envs** | **S1/P0** | **FIXED & VERIFIED** | Railway/Celery |

BUG-004 is fixed, guarded in CI, and verified live: the SPA now serves a real DSN
and Sentry recorded `STRATTRADERPRO-2` — the first frontend event this project has
ever had. **Both follow-ups are now closed too** (2026-07-11):

- The Railway service-level `NGINX_ENVSUBST_FILTER` override has been **deleted on
  both frontend services**. While it existed it shadowed the image's `ENV`, so the
  CI guard was protecting an artifact nobody ran. The Dockerfile value —
  `^(BACKEND_URL|GRAFANA_URL|SENTRY_DSN|SENTRY_ENVIRONMENT|RELEASE|WS_URL)$`, cross-checked
  against the template by `scripts/check_envsubst_filter.py` — is now the single
  source of truth, and the guard finally protects production. Verified after
  redeploy: `/config.js` is fully substituted on both envs, no `${...}` literals.
- `release: ''` is fixed (BUG-003) and verified — it now carries the full commit SHA,
  matching the release CI uploads sourcemaps under.

## Gotchas (not bugs — traps that will cost you time again)

**The "Trace ID" Sentry shows you is not the OTel trace id.** A Sentry issue's
header/highlights show Sentry's *own* trace-context ID. Looking that value up in
Tempo returns `failed to get trace with id: … Status: Not Found`, which looks
exactly like "tracing is broken".

The join key for the Sentry → Tempo click-through is the **`trace_id` tag** on the
event (set by `config.otel.tag_sentry_correlation()`), alongside `request_id`.
Verified 2026-07-11 on staging:

| Source | Value |
|---|---|
| Sentry UI "Trace: Trace ID" (Sentry's own) | `c3aa56fe14c54a0eb878014f0666a44b` → **not in Tempo** |
| Sentry event **tag** `trace_id` (OTel) | `a18459fd968c301c3191335b759ee5da` → **found in Tempo** ✅ |

Sentry's issue page also only renders the *top* tag distribution (transaction, url,
release, environment). `trace_id`/`request_id` are present but need the full tag
list or the event JSON. Don't conclude the tags are missing from the summary panel.

## Theme

BUG-001, BUG-002, BUG-004, BUG-007, BUG-008 and BUG-009 share one failure mode,
and it is *the* thing to watch for on this project:

> **Configuration that is wired, reported healthy, and completely inert.**

M10 shipped tracing with a passing test suite, a healthy exporter, no error logs
— and not one span ever reached Tempo. The frontend shipped a Sentry DSN that was
the literal string `${SENTRY_DSN}`. A CI job called "Frontend — Lint & Test" ran
neither lint nor tests. And 17 alert rules sat in Grafana, correctly written,
correctly routed, reporting `health: ok` — **paused**, unable to fire, for the
platform's kill switch and audit-integrity checks.

In every case the component *initialises successfully* and then does nothing.

### The corollary, which is worse

**A clean bill of health can be produced by the defect itself.**

- A paused alert rule reports `health: ok` *because* it never evaluates.
- A self-filtering rule with no data reports `Normal` *because* it sees nothing.
- A CI job with no test step is green *because* it tests nothing.

So "it's green" is not evidence. Ask what would have to be true for the green to
be a lie, and go check *that*. Prefer end-to-end assertions — "a span arrived",
"the served config contains no `${`", "the rule is not paused", "the test step
exists in the workflow file" — over any component's self-report.

### And: verify the fix against the real artifact

AC-10-9 "passed" by creating a **new** temp alert rule and watching it page. It
proved the notification path and nothing else — every rule the platform actually
depends on was paused, and the acceptance check was structurally incapable of
noticing. A test that exercises a fresh copy of the thing is not a test of the
thing.
