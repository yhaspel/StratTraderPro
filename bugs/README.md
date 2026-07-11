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
| [BUG-003](BUG-003-healthz-reports-stale-git-sha.md) | `/healthz` reports a stale commit SHA | S3 | OPEN | Deploy/Provenance |
| [BUG-004](BUG-004-nginx-envsubst-filter-too-narrow.md) | nginx envsubst allowlist drops 4 of 5 runtime-config vars → **frontend Sentry has never worked** | S2 | FIXED* | Frontend/Config |
| [BUG-005](BUG-005-grafana-free-tier-metrics-limit.md) | Grafana Cloud free-tier metrics limit reached → series dropped | S3 | OPEN | Observability/Ops |
| [BUG-006](BUG-006-otel-init-log-swallowed.md) | `otel.initialized` log line swallowed (init precedes Django logging config) | S4 | OPEN | Observability |
| [BUG-007](BUG-007-frontend-tests-never-run-in-ci.md) | "Frontend — Lint & Test" CI job runs **neither** lint nor tests — no frontend spec has ever executed | S2 | OPEN | CI |

\* BUG-004 code is fixed and guarded in CI; live verification (frontend Sentry
actually receiving an event) still pending.

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

BUG-001, BUG-002 and BUG-004 share one failure mode, and it is the thing to
watch for on this project:

> **Configuration that is wired, reported healthy, and completely inert.**

M10 shipped tracing with a passing test suite, a healthy exporter, no error logs
— and not one span ever reached Tempo. The frontend ships a Sentry DSN that is
the literal string `${SENTRY_DSN}`. In every case the component *initialises
successfully* and then does nothing. Prefer end-to-end assertions ("a span
arrived", "the served config contains no `${`") over "it initialised".
