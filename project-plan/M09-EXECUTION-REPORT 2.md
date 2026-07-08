# M09 Execution Report — Walk-Forward Backtester

> Autonomous implementation run (started 2026-07-08). Updated as work proceeds so
> a partial report survives interruption. Two top-level sections:
> **A — What was implemented**, **B — Manual user steps & follow-ups**.
> Branch: `feature/m09-walk-forward-backtester` (off `main` @ `b6f54db`).

---

## Work classification (BUILDABLE NOW vs LIVE-DEFERRED)

Recorded up front per the mission. Every BUILDABLE item is my accountability;
LIVE-DEFERRED items become documented manual steps (Section B), not failures.

| AC / Exit-gate item | Class | Note |
|---|---|---|
| AC-09-1 submit + server-side caps | **BUILDABLE** | serializer + view validation |
| AC-09-2 dedicated `backtest` queue + route + time limits | **BUILDABLE** | route map + settings unit test + compose `worker-backtest`; **Railway service = LIVE-DEFERRED** |
| AC-09-3 vectorbt sweep (unit sizing, cost-aware rank) | **BUILDABLE** | behind `SweepEngine` seam |
| AC-09-4 replay engine (trades/slippage/commission/partials/same-bar) | **BUILDABLE** | golden + property tests |
| AC-09-5 OOS concatenation + `BacktestSegment` rows | **BUILDABLE** | |
| AC-09-6 report metrics + PBO + per-window stability | **BUILDABLE** | `stats.py` |
| AC-09-7 PDF tearsheet (vector charts, disclaimer, PBO badge) | **BUILDABLE** | WeasyPrint + matplotlib SVG |
| AC-09-8 progress WS events | **BUILDABLE** | `dashboard.events.push_to_user` |
| AC-09-9 cancellation ≤ 30 s | **BUILDABLE** | eager-Celery test |
| AC-09-10 3y ≤ 10 min / 10y ≤ 30 min / RSS ≤ 2 GB | **LIVE-DEFERRED (staging)** | 1y CI smoke ≤ 60 s + grid chunking = BUILDABLE |
| AC-09-11 retention + nightly eviction beat | **BUILDABLE** | default-queue beat entry |
| AC-09-12 production-sizing parity | **BUILDABLE** | non-tautological `SizingInputs` parity test |
| Exit: sample 3y PDF on demo strategy | **BUILDABLE (synthetic)** | real-symbol data needs M06 FMP backfill = LIVE-DEFERRED |
| Exit: reproducibility hash (JIT + non-JIT) | **BUILDABLE** | |
| Exit: Backtest Ops dashboard JSON committed | **BUILDABLE** | "live on staging" = LIVE-DEFERRED |
| Exit: ADRs 090–092 + runbook + help docs | **BUILDABLE** | |
| Exit: CHANGELOG + PROGRESS + tracker | **BUILDABLE** | |
| Exit: tag `v0.9.0-backtest` (created, not pushed) | **BUILDABLE (create)** | push = operator-gated |

**Expected LIVE-DEFERRED set:** Railway `worker-backtest` service; AC-09-10 staging
SLAs; Grafana "Backtest Ops" live-on-staging; real-symbol 3y PDF (synthetic fixture
accepted for the exit gate); tag push.

---

## Day-1 dependency spike

- `vectorbt==1.0.0` confirmed present on PyPI (versions available: … 1.0.0, 1.1.0).
  Engine choice is real — no autonomous engine swap needed.
- Resolver / import / 100-combo smoke / backend image build / Trivy: _in progress — recorded below._

---

# Section A — What was implemented

_(filled in as work lands)_

---

# Section B — Manual user steps & follow-ups

_(filled in as work lands)_
