# ADR-106 — Load-test target: local docker-compose + `FakeBrokerAdapter` (not real Alpaca paper)

**Date:** 2026-07-12
**Status:** Accepted
**Milestone:** M11 — Hardening, Security, Load Test & Docs
**Reference:** `project-plan/11-hardening-and-load-test.md` §4.1, §7.4; AC-11-3 [CI], AC-11-4 [CI];
`backend/apps/brokers/fake.py` (`FakeBrokerAdapter`), `backend/apps/brokers/test_brokers.py` (`FakeAdapterTests`);
`backend/apps/webhooks/views.py` (`WebhookIngestView.post`), `backend/apps/risk/killswitch.py` (L1 halt+flatten);
`docker-compose.yml` (`postgres-exporter`, `redis-exporter`), `backend/apps/admin_portal/tasks.py` (`celery_queue_depth` gauge);
`docs/ops/load-test-results.md`, `.github/workflows/ci.yml` (weekly load-test canary)

## Context

M11 must prove the platform holds up at ~100-user scale: 100 concurrent WS
dashboards + 20 webhooks/sec sustained for 10 minutes (AC-11-3), plus a 50-user
simultaneous **L1** halt+flatten (AC-11-4, which completes the deferred M08
AC-08-11 load item). The question this ADR settles is *what sits at the broker
boundary while that load runs* — the real Alpaca paper API, or the in-process
`FakeBrokerAdapter`.

Two facts force the choice:

1. **Alpaca paper is rate-limited to ~200 req/min.** The webhook load alone is
   20/sec = **1200/min**, six times the cap, before any order, quote, or account
   call the order path makes downstream. Alpaca paper would 429 within the first
   few seconds and the run would measure *its* throttle, not ours.
2. **The metric under test is a platform-path latency.** AC-11-3's gate is
   **p95 alert-ingest → order-submit ≤ 1.5s**. That path is: `WebhookIngestView.post`
   (`apps/webhooks/views.py:93`) → static-`sig` constant-time compare
   (`hmac.compare_digest`, `views.py:147`) → idempotency SETNX
   (`cache.add`, `views.py:180`) → `process_alert.delay` (`views.py:213`) →
   sizing → `adapter.place_order`. Real-broker network latency and fill timing are
   deliberately *outside* what this number is meant to bound.

`FakeBrokerAdapter` (`apps/brokers/fake.py:59`) already implements the full
`BrokerAdapter` protocol in memory and is deterministic: `place_order`
(`fake.py:132`) emits `new`/`partial_fill`/`fill` events to the *same* transport
as Alpaca (`apps.orders.fills.publish_fill`), so the ingest path is exercised
identically whether the broker is fake or real (`fake.py:1-11`). It is already the
backbone of the AC-04-10 end-to-end test and every scripted-outcome unit test
(`FakeAdapterTests`, `apps/brokers/test_brokers.py:221`). Its `flatten_all`
(`fake.py:226`) gives the L1 flatten drill a deterministic, network-free execution
to measure — the halt engine's `flatten_user` path (`apps/risk/killswitch.py:136`)
and `KILLSWITCH_FLATTEN_LATENCY` gauge are what AC-11-4 actually times.

## Decision

**The M11 load test runs against local docker-compose with `FakeBrokerAdapter` at
the broker boundary — not real Alpaca paper.** (Frozen: §4.1 decision 1.)

- The full-scale run (100 WS / 20 rps / 10 min, and the 50-user L1
  halt+flatten) executes on the local compose stack, with Locust scripts under
  `backend/loadtest/`. Results land in `docs/ops/load-test-results.md`.
- **Determinism is a feature, not a compromise.** `FakeBrokerAdapter` fills on a
  scripted, in-memory basis with no network, so p50/p95/p99 for ingest→submit and
  for flatten are attributable to *our* code (gunicorn worker count, DB pool size,
  Celery queue depth, WS fan-out) rather than to broker-side variance we do not
  control and do not ship.
- **AC-11-3's 1.5s p95 measures the platform path and excludes real-broker
  latency by design.** The gate bounds webhook-receipt → order-submit inside the
  platform; broker round-trip is explicitly not in scope for this number. AC-11-4's
  L1 flatten (p99 ≤ 8s) is measured the same way, against `flatten_all`.
- **Infra metrics are captured locally, not deferred.** DB/Redis throughput,
  connections, and memory come from the `postgres-exporter` and `redis-exporter`
  compose services (`docker-compose.yml:154`, `:162`), which are also deployed on
  Railway (§0.16) — scrape them during the local run. Reuse M10's
  `celery_queue_depth{queue}` gauge (`apps/admin_portal/tasks.py`) for backlog over
  time. Under multiproc gunicorn, do **not** assert on `process_*`/`django_db_*`
  (disabled) — read the app-level gauges. Only host-level CPU/IOPS on the Railway
  side remains [LIVE].
- **A reduced canary runs weekly in CI, not per-commit.** A scaled-down profile
  (e.g. 10 WS / 2 rps / 60s) runs as a `workflow_dispatch` + weekly-`cron` GitHub
  Actions job (`.github/workflows/ci.yml`), headless Locust, gated so it never runs
  on every push. It guards against gross regressions between full runs without
  paying the full-scale cost per commit.
- **A staging spot-check is a documented operator follow-up.** Staging today lacks
  the `ws`/`streams` services, so the full run cannot execute there yet; the
  procedure is recorded in Section B, not run autonomously.

## Why real-broker load was rejected (2026-07-12)

Pointing the load test at real Alpaca paper is the tempting "more realistic"
option and it fails on all three counts that matter for a repeatable gate:

- **Rate-limited.** ~200 req/min cannot absorb 20 webhooks/sec (1200/min). The run
  would measure Alpaca's 429s, not our throughput.
- **Non-deterministic.** Fill timing, partial-fill behaviour, and paper-account
  latency vary run to run, so p95/p99 would drift for reasons unrelated to any code
  change — an unstable gate is indistinguishable from no gate.
- **External dependency.** A CI-adjacent gate that fails when a third-party paper
  environment is slow, down, or throttling is not a signal about our platform. It
  also cannot run in the weekly CI canary at all.

Real-broker *correctness* is already covered elsewhere: the M04 live-broker spike
and the Alpaca adapter's own tests exercise the real REST/stream path. This ADR is
about *load characterisation of the platform*, for which the fake is the correct
and only stable instrument.

## Consequences

- **Positive:** a deterministic, repeatable load gate that attributes latency to
  our own tunables; runs entirely on local compose with no external credential; a
  cheap weekly canary in CI; infra metrics captured from the same exporters that
  run in production, so the local numbers map to real dashboards.
- **Cost / limitation:** the run does **not** exercise real Alpaca REST/stream
  latency or its rate limiter under load. That is by design (AC-11-3 excludes it),
  but it means a broker-side bottleneck would not surface here — the staging
  spot-check and the M04 real-broker tests are the mitigations, and the broker-5xx
  chaos drill (§7.5 Day 4) injects failure via the fake/mock rather than hammering
  real Alpaca.
- **Scope note:** the 50-user scenario is specifically an **L1** halt+flatten
  (per-user global halt + flatten that user's positions, `killswitch.py:136`), not
  an L3 platform halt (which blocks intake and does *not* flatten). Kill-switch
  levels are **L0–L3** (ADR-081); do not describe this drill as "L4".
- **Deliverable, not live env:** the run produces the Locust harness, the CI
  canary job, and `docs/ops/load-test-results.md`. The full-scale numbers come from
  the local stack; the staging replay is a Section-B operator step.
