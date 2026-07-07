# ADR-061 — FinancialModelingPrep + FRED as the market-data vendors, and the deferred `Bar` partitioning

**Date:** 2026-07-07
**Status:** Accepted
**Milestone:** M06 — Market Data + Regime Classifier
**Reference:** `project-plan/06-market-data-and-regime.md` §6.1–§6.2, §7, §11,
§12, §16; the 2026-07-05 post-Alpaca-pivot review note; ADR-041 (Alpaca ships a
market-data API for free); AC-06-1, AC-06-9

## Context

The regime feature pipeline (§6.3, ADR-060) needs four *different* classes of
data on our own schedule: **equities bars** (SPY/QQQ/IWM + S&P 500 constituents
for breadth), **sector performance** (breadth approximation), the **treasury
yield curve** (10y–2y), and **credit spreads** (HY/IG OAS). No single free source
covers all of that, and the pivot to Alpaca (ADR-041) put a *second* bar source
in our hands for free. So M06 had to decide who provides what, and how to survive
a vendor's rate limit or outage without the dashboard 5xx-ing.

## Decision

### 1. FMP is the primary vendor; FRED covers credit spreads; Alpaca is an available second bar source

- **FinancialModelingPrep (FMP), premium tier — primary.** FMP is the only
  single vendor that covers the pipeline's non-price inputs — **sector
  performance**, the **treasury yield curve**, and **economics** endpoints —
  alongside equities bars and quotes. That breadth is why it stays primary even
  though Alpaca now gives us bars for free (per the §review note). Endpoints used
  (`backend/apps/marketdata/fmp.py`, base `…/stable`):

  | Method | Endpoint | Use |
  |---|---|---|
  | `daily_bars` | `/historical-price-eod/full?symbol=` | daily OHLCV |
  | `intraday_bars` | `/historical-chart/{tf}?symbol=&from&to` | 5-min intraday |
  | `quote` | `/quote?symbol=` | realtime quote |
  | `treasury_yield_curve` | `/economics/treasury-yield-curve?from&to` | 10y/2y |
  | `sector_performance` | `/historical-sector-performance` | sector breadth |

- **FRED — credit spreads (free).** `backend/apps/marketdata/fred.py` pulls HY
  OAS (`BAMLH0A0HYM2`) and IG OAS (`BAMLC0A0CM`) from the free St. Louis Fed API.
  Credit stress is a top-weight risk-off signal in the rule (ADR-060 §1), and
  FRED is the authoritative, no-cost source — no reason to pay FMP for it.

- **Alpaca — available second source for plain equities bars.** ADR-041 brought
  Alpaca's market-data API in for free (real-time IEX + 15-min-delayed SIP,
  historical bars via the already-pinned `alpaca-py`). It is the natural
  second source for *plain equities bars* — the one data class where FMP is not
  unique — to cut FMP tier cost and add a real-time-capable feed. **As built,
  M06 reads bars through `FMPClient` directly** and does not yet route them
  through a provider abstraction; extracting a `MarketDataProvider` seam (the
  plan's §6.13 intent) with an `AlpacaDataProvider` alongside an FMP provider is
  a documented near-term follow-up, not an M06 deliverable. The sector /
  treasury / credit inputs stay on FMP+FRED regardless — Alpaca does not cover
  them.

The `Bar.source` column already records provenance (`"FMP"` today), so mixing an
Alpaca bar source later is an additive change, not a migration.

### 2. Caching strategy — short for intraday, long for daily

FMP responses are cached (Django cache) with a TTL that matches how fast the
underlying data actually changes, per §6.1:

| Data | `cache_ttl` | Rationale |
|---|---|---|
| Intraday bars | **30s** | 5-min bars change slowly relative to a 30s dashboard refresh; 30s collapses a burst of dashboard reads into one upstream call. |
| Realtime quote | 15s | freshest surface, still deduped. |
| Daily bars | **24h** (86 400s) | EOD bars are immutable once the day closes. |
| Treasury curve / sector | 1h | updated at most daily; hourly is generous. |

The cache is also the **fallback store** (below), so its floor is `max(ttl, 30)`
seconds — a cached copy always outlives a short rate-limit stall.

### 3. Resilience: token-bucket → circuit breaker → cache-fallback (AC-06-9)

`FMPClient.get` layers three defenses so that **a rate-limit breach or vendor
outage never surfaces as a 5xx on the dashboard** — it degrades to cached data
instead:

1. **Token-bucket rate limit** — a fixed per-minute window (`fmp:rl:{minute}`)
   sized to `FMP_RATE_LIMIT_PER_MIN` (default **750**, the assumed premium tier).
   Exceeding it raises `FMPRateLimited` client-side *before* a call goes out and
   increments `marketdata_ratelimit_waits_total` — we throttle ourselves rather
   than earn a real 429.
2. **Retry with backoff** — `tenacity`, 3 attempts, exponential jitter
   (`initial=0.1`, `max=2.0`) on `FMPRateLimited` / `FMPError` (429 / 5xx).
3. **Circuit breaker** — after 5 failures within a 60s cooldown the breaker
   opens for 60s (`FMPCircuitOpen`), so we stop hammering a vendor that is down.
4. **Cache-fallback** — on rate-limit, open circuit, or exhausted retries,
   `get` returns the **last cached response** for that path+params if one
   exists (logging `fmp.cache_fallback`), and only raises if there is nothing
   cached at all. Every path is metered `marketdata_requests_total{endpoint,
   result="ok"|"fail"}`.

The operator playbook for a sustained rate-limit / outage is
`docs/runbooks/fmp-rate-limit.md`.

### 4. Vendor-change safety: contract tests against fixtures, ADR before a swap

Both clients take an **injectable HTTP client** (`http=`) and no live vendor call
runs in CI — an FMP premium key and a FRED key are **deferred externals** (empty
by default in settings; `backfill_bars` refuses to run without `FMP_API_KEY`).
Parsing is therefore pinned by **contract tests against recorded fixtures** of
each endpoint's response shape (`_normalize_bars` tolerates FMP's `historical`
-wrapped and bare-list forms; FRED's `.`/empty sentinels are dropped). §16 rates
"FMP endpoint changes break parser" **Low/Med** and requires a **vendor-change
ADR before adopting a new endpoint or format** — the fixtures are the tripwire,
this ADR is the gate. This mirrors the M05 broker-adapter approach (ADR-050): the
vendor's *documented* shape is proven; its *live* shape is re-validated when the
key lands.

### 5. Deferred: `Bar` Postgres month-partitioning (an index-size optimization)

The plan (§6.2) calls for partitioning `Bar` by month via
`django-postgres-partition` "to keep indexes small," with a >5y retention drop.
**This is deferred.** As built, `Bar` (`backend/apps/marketdata/models.py`) is a
**plain indexed table**: `BigAutoField` PK, `unique_together (symbol, tf, ts)`,
and a composite `(symbol, tf, ts)` index — with idempotent upserts on that key
(`services.upsert_bars`) satisfying AC-06-1.

Why deferring is correct rather than a gap:

- **It is an index-size / retention optimization, not a functional one.** Query
  correctness, idempotency, gap detection (`missing_bars`), and the feature
  pipeline are all identical on a plain table. Nothing above the model can tell
  whether the table is partitioned.
- **The composite index is right-sized at MVP scale.** The M06 working set is
  ~500 S&P names + a handful of index symbols in daily bars; the index is small
  and the `(symbol, tf, ts)` lookups the pipeline makes are exact-prefix. There
  is no bloat to fight yet.
- **It keeps the model SQLite-testable.** `django-postgres-partition` is a
  Postgres-only declarative-partition layer; adopting it now would fork the test
  DB off SQLite for no functional benefit. Plain-table `Bar` runs the same in
  CI and prod.
- **The migration is additive and provenance is already tracked.** Converting to
  monthly partitions later is a schema change behind the same
  `(symbol, tf, ts)` contract; `Bar.source` already records provenance, so a
  retention policy can be added without touching callers.

**Revisit when the table grows** — once intraday bars for a wide symbol universe
push the single index past comfortable size (the §16 "DB bloat from bar
partitions" Med/Low risk becoming real), adopt monthly partitions + the >5y
retention drop as planned. Tracked as a follow-up, not shipped in M06.

## Consequences

**Positive:**

- One primary vendor (FMP) covers the pipeline's unique inputs; FRED covers
  credit for free; Alpaca is a ready second bar source when the cost math favors
  it — all behind a `source`-tagged store.
- The dashboard cannot 5xx on a data-vendor problem (AC-06-9): it shows the last
  good cached value and the metrics/runbook expose the degradation.
- CI is hermetic — no live keys, fixture-pinned parsing, an explicit
  vendor-change gate.

**Negative / honest limits:**

- **The premium FMP key, the FRED key, and the 10-year backfill are deferred
  externals.** `backfill_bars` and the live pipeline are built and unit-tested
  against fixtures, but no live 10y series has been ingested; the live wire shape
  is proven only against recorded fixtures until the key lands.
- **The `MarketDataProvider` abstraction is not yet extracted.** M06 uses
  `FMPClient` directly; the Alpaca second-source path is a documented follow-up,
  not a shipped seam.
- **`Bar` is unpartitioned.** Correct and fast now; a known, bounded follow-up
  when the table grows (§5).

## Alternatives considered

1. **Alpaca as primary, drop FMP.** Rejected: Alpaca has no sector-performance,
   treasury-curve, or economics endpoints — the pipeline's non-price inputs would
   be uncovered. Alpaca is a *bar* source, not a replacement for FMP's breadth.
2. **Pay FMP for credit spreads instead of FRED.** Rejected: FRED is the free,
   authoritative source for OAS series; paying for it adds cost and a second
   failure surface for no gain.
3. **Adopt TimescaleDB / partition `Bar` now.** Rejected for M06 (§7 explicitly
   drops TimescaleDB; §5 above defers partitioning): plain Postgres is sufficient
   at our scale and stays SQLite-testable. Revisit on real growth.
4. **No cache-fallback — just retry and let it fail.** Rejected: it would let an
   FMP rate limit or outage cascade into a dashboard 5xx, violating AC-06-9. The
   cache-fallback is what makes degradation invisible to the user.

## See also

- ADR-041 — Alpaca replaces IBKR (brought the free market-data API in)
- ADR-060 — the regime ensemble that consumes these features
- `docs/runbooks/fmp-rate-limit.md` — operating an FMP rate-limit / outage
- `backend/apps/marketdata/fmp.py`, `backend/apps/marketdata/fred.py` — the clients
- `backend/apps/marketdata/models.py` — `Bar` / `MacroSeries` (the plain-table decision)
- `backend/apps/marketdata/services.py` — idempotent upserts + gap detection
- `backend/apps/marketdata/management/commands/backfill_bars.py` — the backfill command
- `project-plan/06-market-data-and-regime.md` §6.1–§6.2, §7, §16
