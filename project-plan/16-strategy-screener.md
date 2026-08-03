# Milestone 16 — Strategy Screener (FMP, description-driven)

> **Duration:** 4 working days
> **Depends on:** ADR-062 instance data-provider keys (shipped 2026-08-01 — the FMP key gate + Settings page), M06 marketdata plane (`FMPClient`, `Bar` store, resilience stack), M03 strategies (`StrategyFile` DESC contract)
> **Unlocks:** watchlist/auto-candidate features, M06A per-symbol regime (shares the candidate-universe idea)
> **Status:** Spec — not started

> **Decision provenance (2026-08-01, Yuval):** screening criteria come from a
> **machine-readable `[screen]` block authored inside the strategy description**
> (deterministic parse; no LLM, no separate criteria editor), and the screen
> runs on the **instance** FMP key (`apps.marketdata.keys.resolve_key`) — there
> are no per-user vendor keys (ADR-062).

## 1. Purpose

Strategy descriptions (TradingView-style BBCode, stored as the `DESC`
`StrategyFile`) already tell a human what universe the strategy wants —
"liquid large caps above the 200-day, near 52-week highs". M16 makes that
executable: an author adds a small `[screen]` block to the description; the
strategy page grows a **Screening** panel that shows the parsed criteria and a
**Run screen** button; the backend runs one FMP company-screener call plus a
local technical-enrichment pass over daily bars, and returns a ranked candidate
list. The feature is available whenever the instance has an FMP key configured
(Settings → Data Providers or `FMP_API_KEY` — ADR-062); it is cleanly and
honestly unavailable otherwise.

## 2. In Scope

- `[screen]` block grammar + deterministic parser with line-numbered errors
  (`apps/screener/criteria.py`), single-sourced server-side.
- `FMPClient.company_screener()` — the one new vendor endpoint (ADR-063).
- New `screener` app: `ScreenRun` model, Celery task, API under
  `/api/v1/strategies/{id}/screen/…` (keeps the MFA-swept `strategies` prefix).
- Two-stage pipeline: vendor-side filters in ONE screener call → local derived
  filters (SMA 50/200, SMA-200 slope, 52-week-high proximity) computed from
  `daily_bars` (upserted into the `Bar` store for reuse by M06A). **A5:** the
  FMP response cache is a *failure fallback*, not a read-through cache — a
  re-run re-spends the vendor calls on a healthy day.
- Frontend Screening panel on `/strategies/:id`: criteria chips, run + poll,
  results table, honest gated/empty states; `[screen]` hidden from the rendered
  description prose.
- Feature flag `SCREENER_ENABLED`, metrics, per-user throttle, run history
  (last 20 per user+strategy), authoring guide.

## 3. Out of Scope

- LLM extraction of criteria from free prose (rejected 2026-08-01 — adds an
  Anthropic key dependency + non-determinism to a self-hosted OSS app).
- A separate structured criteria editor (two sources of truth).
- Per-user FMP keys (ADR-062 decided instance-wide).
- Scheduled/recurring screens, watchlists, auto-trading or auto-backtesting the
  results (candidates are informational output in M16).
- Technical indicators beyond SMA/52w-high derived from daily bars (no RSI/ADX
  — needs an indicator library decision; a later milestone).
- FRED-based criteria (macro gating belongs to the regime plane, not per-stock
  screening). FRED key absence does NOT block screening.
- Multi-value vendor enums (`sector: A|B`) — v1 takes one value per vendor key.
- Fundamentals beyond the screener's own fields (P/E, revenue growth …) — each
  would add per-candidate vendor calls; revisit with a quota budget.

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-16-1 | A strategy whose DESC contains a valid `[screen]` block exposes parsed criteria at `GET /api/v1/strategies/{id}/screen/criteria/`, including the exact FMP param mapping; a malformed block returns `SCREEN_CRITERIA_INVALID` with line-numbered errors — never a 500, and never a failed *upload* (description uploads stay prose-first). |
| AC-16-2 | `POST /api/v1/strategies/{id}/screen/` with a resolved instance FMP key creates a `ScreenRun` (QUEUED) and returns **202** `{run_id}`; the run completes via Celery and `GET …/screen/runs/{run_id}/` serves status → results. |
| AC-16-3 | Without a resolved FMP key (no UI-stored key AND no `FMP_API_KEY` env), POST returns **409 `FMP_NOT_CONFIGURED`**; the UI disables Run and links staff to `/settings/data-providers`, non-staff get ask-your-administrator copy. FRED's absence has no effect. |
| AC-16-4 | Without a `[screen]` block, POST returns **409 `NO_SCREEN_CRITERIA`** and the panel shows an honest empty state linking the authoring guide — not a disabled button with no explanation. |
| AC-16-5 | Vendor-side criteria are applied in **one** `/company-screener` call; derived criteria (`above_sma`, `sma_rising`, `near_52w_high`) are computed locally from `daily_bars` — no vendor calls per candidate beyond the (`Bar`-upserted) daily bars. Hard cap ≤ 100 candidates enriched. **A5:** `FMPClient.get()` is fetch-always and consults its cache only in the failure path, so this is a *failure-fallback* cache, not a 24h dedupe; the real quota bounds are the 10/h/user throttle and the ≤100 cap. |
| AC-16-6 | Runs are reproducible + attributable: each `ScreenRun` stores the parsed criteria snapshot and the DESC file's `sha256`; editing the description does not mutate past runs. |
| AC-16-7 | An FMP rate-limit/outage mid-enrichment degrades, never 5xxes and never silently truncates: the run finishes `DONE` with `degraded=true` and per-cause counts (`insufficient_history`, `skipped_rate_limited`, **`skipped_unavailable`** — A4); a screener-call failure with no cache fails the run with `error_code`. |
| AC-16-8 | Concurrency + quota safety: a second POST while a run is active for the same (user, strategy) → **409 `SCREEN_RUN_ACTIVE`**; more than 10 run-creates/user/hour → **429 `RATE_LIMITED`**. |
| AC-16-9 | Permissions: every screen endpoint requires `can_user_view(strategy)` + MFA; users only ever see their own runs. **A1:** the `strategies` prefix sweep in `apps/users/test_mfa.py` does **not** cover the new paths for free — it walks a hardcoded `scaffold_paths` list of one representative URL per prefix, so a `("strategies", "00000000-0000-0000-0000-000000000000/screen/criteria/")` row must be added (DRF runs permissions before object lookup, so the nil UUID cleanly yields 403 `MFA_REQUIRED`). |
| AC-16-10 | The `[screen]` block never renders as raw text in the description prose (BBCode renderer swallows it); the Screening panel renders criteria as structured chips fed by the criteria endpoint (server parse only — no second parser in TS). |
| AC-16-11 | `SCREENER_ENABLED=false` → **every** screener endpoint (the criteria GET and the run GETs included, not just POST) returns **503 `FEATURE_DISABLED`** — the house code, per **A3**; panel hidden; flag registered in `FEATURE_FLAGS_REGISTRY` (mutable). |
| AC-16-12 | The FMP screener wire shape is pinned by fixtures in CI and re-validated live when a real key is present, recorded in ADR-063 (the ADR-061 §4 vendor-change gate). |

## 5. Definition of Done

Baseline DoD (project-plan/README.md §Cross-cutting conventions) applies, plus:

- ADR-063 (`docs/adr/063-fmp-company-screener.md`) — new-endpoint decision per
  ADR-061 §4: documented params/fields, fixture tripwire, live re-validation
  note, tier caveats.
- Authoring guide `strategy-screening` shipped (catalog + HTML — the
  `check_guides_catalog.py` CI guard enforces both).
- Parser fixtures mirror REAL TradingView exports (licence header before
  `//@version`-style leading noise, CRLF, BOM, block mid-prose) — the
  2026-07-30 fixture lesson (#45): synthetic-only fixtures hide real-input
  rejections.
- CHANGELOG `[Unreleased]` entry; PROGRESS.md row flipped when closed.

## 6. Implementation Tasks

### 6.1 `[screen]` block grammar + parser (`apps/screener/criteria.py`)

One optional block anywhere in the DESC text (case-insensitive tags, ≤ 4096
bytes between tags, ≤ 40 lines; at most one block — a second is a
`duplicate_block` error). Inside: `key: value` lines; blank lines and
`# comment` lines ignored. Numbers accept `K/M/B/T` suffixes; `%` where noted.

```
[screen]
# Minervini-style trend template, large caps
market_cap: >= 2B
price: 10..1000
volume: >= 1M
sector: Technology
exchange: NASDAQ
above_sma: 200
sma_rising: 200
near_52w_high: 25%
limit: 50
[/screen]
```

Keys (the full v1 allowlist — unknown keys are line-numbered errors, not
warnings; typos must not silently widen a screen):

| Key | Value forms | Applied | FMP mapping |
|---|---|---|---|
| `market_cap` | `>= N`, `<= N`, `A..B` | vendor | `marketCapMoreThan` / `marketCapLowerThan` |
| `price` | same | vendor | `priceMoreThan` / `priceLowerThan` |
| `volume` | same | vendor | `volumeMoreThan` / `volumeLowerThan` |
| `beta` | same | vendor | `betaMoreThan` / `betaLowerThan` |
| `dividend` | same | vendor | `dividendMoreThan` / `dividendLowerThan` |
| `sector` | single string | vendor | `sector` |
| `industry` | single string | vendor | `industry` |
| `exchange` | single string | vendor | `exchange` |
| `country` | single ISO-2 string | vendor | `country` |
| `etf` | `true`/`false` (default `false`) | vendor | `isEtf` |
| `above_sma` | `50` or `200` (repeatable once each) | derived | close > SMA(n) |
| `sma_rising` | `50` or `200` (repeatable once each) | derived | SMA(n) today > SMA(n) 20 sessions ago |
| `near_52w_high` | `N%` (1–100) | derived | close ≥ (1 − N/100) × 252-day high |
| `min_history` | integer days (default 260 iff any derived key present) | derived | require ≥ N daily bars |
| `limit` | 1–100 (default 50) | both | `limit` (vendor) + enrichment cap |

`isActivelyTrading=true` is always sent. **A9: `isEtf` is always sent too** —
`isEtf=false` unless `etf: true`. Mirroring `isActivelyTrading` is the
deterministic-narrowing reading of the table's "default `false`" and removes the
ambiguity where §9's example omitted the param. Parser returns
`ScreenCriteria` (dataclass: `vendor_params: dict`, `derived: dict`,
`limit: int`) or a list of `{line, error}` dicts. Pure module — no Django
imports; linear scan, no backtracking-prone regexes (the block is
user-authored input — §11).

### 6.2 FMP client: the one new endpoint (`apps/marketdata/fmp.py`)

```python
def company_screener(self, params: dict) -> list[dict]:
    return self.get("/company-screener", params, cache_ttl=300) or []
```

Rides the existing token-bucket → retry → breaker → cache-fallback stack
(AC-06-9 semantics for free). Documented response fields to pin in fixtures:
`symbol, companyName, marketCap, sector, industry, beta, price,
lastAnnualDividend, volume, exchange, exchangeShortName, country, isEtf,
isActivelyTrading`. The public docs page confirms the path
(`…/stable/company-screener`) and the filter families (market cap, price,
volume, beta, sector, country, …) but renders the param table client-side —
so ADR-063 records the shape above as *documented-contract-to-verify*, the
fixtures are the tripwire, and AC-16-12 mandates the live re-validation at
key-land. Exactly how M06 treated its endpoints (deferred external).

### 6.3 `screener` app: model + migration (`apps/screener/models.py`)

```python
class ScreenRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"; RUNNING = "RUNNING"; DONE = "DONE"; FAILED = "FAILED"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="screen_runs")
    strategy = models.ForeignKey("strategies.Strategy", on_delete=models.CASCADE,
                                 related_name="screen_runs")
    status = models.CharField(max_length=8, choices=Status.choices,
                              default=Status.QUEUED, db_index=True)
    criteria = models.JSONField()            # parsed snapshot (reproducibility)
    desc_sha256 = models.CharField(max_length=64)   # DESC StrategyFile.sha256 at run time
                                                   # (A7: renamed from criteria_sha256 —
                                                   #  nothing hashes the criteria)
    results = models.JSONField(default=list) # [{symbol, name, exchange, sector, market_cap,
                                             #   price, volume, beta, pct_from_52w_high,
                                             #   above_sma_50, above_sma_200, sma200_rising}]
    counts = models.JSONField(default=dict)  # {vendor_matches, enriched, returned,
                                             #   insufficient_history, skipped_rate_limited,
                                             #   skipped_unavailable}   <- A4
    degraded = models.BooleanField(default=False)
    error_code = models.CharField(max_length=48, blank=True, default="")
    celery_task_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table = "screener_run"
        indexes = [models.Index(fields=["user", "strategy", "-created_at"])]
        constraints = [                      # race hardening beyond the 409 pre-check
            models.UniqueConstraint(
                fields=["user", "strategy"],
                condition=Q(status__in=["QUEUED", "RUNNING"]),
                name="uniq_active_screen_run_per_user_strategy",
            ),
        ]
```

The partial unique index is **required**, not optional: the view's "is a run
active?" pre-check loses the race between two interleaved POSTs, and both would
insert. Run creation is wrapped so the resulting `IntegrityError` returns the
same 409 `SCREEN_RUN_ACTIVE`. Partial unique indexes work on SQLite and
Postgres, so the SQLite lane proves it.

Results live as JSON on the run (≤ 100 rows) — no per-row table; the backtest
precedent for small terminal payloads. Retention: after a run finishes, prune
beyond the newest 20 per (user, strategy) inline in the task (no beat job).
Register the app in `INSTALLED_APPS` (`config/settings/base.py`).

### 6.4 Pipeline task (`apps/screener/tasks.py`)

`@shared_task(bind=True, ignore_result=True, soft_time_limit=240, time_limit=300)`
(global default is 30s — the backtest per-task override pattern), default queue
(runs are seconds-to-a-minute; no dedicated-queue routing — the M09 note about
route-glob dangers applies).

`run_screen(run_id)`:
1. Load run; set RUNNING + `started_at`; re-check `resolve_key("FMP")` (key
   could have been removed since enqueue → FAILED `FMP_NOT_CONFIGURED`).
2. Vendor stage: `FMPClient().company_screener(criteria.vendor_params)` →
   `vendor_matches`. Uncached failure → FAILED with the mapped error code
   (`FMP_RATE_LIMITED` / `FMP_UNAVAILABLE`).
3. Derived stage (only if derived keys present): for each candidate up to
   `limit`: `daily_bars(symbol)` (also `upsert_bars(sym, "1d", …)`
   into the `Bar` store — free reuse for M06A; **A5:** no read-through cache,
   so a re-run re-spends the call on a healthy day); compute SMA50/200, SMA200
   20-session slope, 252-day high distance; drop + count
   `insufficient_history` when bars < `min_history`.

   **A4 — the degrade ladder has three rungs, not one** (the spec previously
   named only rate limits, while AC-16-7 promised outages too):
   * `FMPRateLimited` / `FMPCircuitOpen` → stop fetching; the raising symbol
     **plus the unfetched remainder** count as `skipped_rate_limited`;
     `degraded=True`.
   * `FMPServerError` (outage with a cold cache) → stop fetching; raiser +
     remainder count as `skipped_unavailable`; `degraded=True`.
   * bare `FMPError` (a 4xx for ONE symbol — bad/delisted ticker) → skip that
     symbol only, count it in `skipped_unavailable`, **continue**;
     `degraded=True`.

   The vendor *screener call* failing with no cache still FAILs the run
   (step 2, unchanged).
4. Rank: `pct_from_52w_high` ascending when `near_52w_high` present, else
   vendor `marketCap` descending. Persist results/counts/status/finished_at;
   prune history (§6.3); metrics (§12).

### 6.5 API (`apps/screener/views.py` + `urls.py`)

Mounted in `config/urls.py` INSIDE the swept prefix:
`path("api/v1/strategies/<uuid:strategy_id>/screen/", include("apps.screener.urls"))`
(place it above the `apps.strategies.urls` include so the literal `screen/`
segment can't be shadowed later). All views: `IsAuthenticatedAndMFAEnforced` +
`mfa_required = True` + `can_user_view(strategy)` (404 on no-view, the
strategies convention); runs are filtered `user=request.user`.

| Method + path | Behavior |
|---|---|
| `GET …/screen/criteria/` | Parse DESC now (no cache): `{"data": {criteria, fmp_params, derived, block_present: true}}`, or `block_present: false`, or 400 `SCREEN_CRITERIA_INVALID` + `details: [{line, error}]`. |
| `POST …/screen/` | Gate order: flag off → 503 `FEATURE_DISABLED` (A3); `@ratelimit(key="user", rate="10/h")` → 429 `RATE_LIMITED`; no resolved FMP key → 409 `FMP_NOT_CONFIGURED`; no block → 409 `NO_SCREEN_CRITERIA`; invalid block → 400 `SCREEN_CRITERIA_INVALID`; active run exists → 409 `SCREEN_RUN_ACTIVE`. Else create run, enqueue, **202** `{"data": {"run_id": …}}`, audit `screener.run_requested` (add to `AuditEventType`; entity = strategy id — no criteria payload needed, the run row has it). |
| `GET …/screen/runs/` | Newest-first, `?limit=` ≤ 20 default 5. Envelope list of run summaries (no `results` — keep list light). |
| `GET …/screen/runs/{run_id}/` | Full run incl. `results`, `counts`, `degraded`, `error_code`. 404 unless owner. |

**A3 — the flag gates EVERY row above, not just the POST.** The criteria GET
and both run GETs return 503 `FEATURE_DISABLED` when `SCREENER_ENABLED` is off;
§6.6 state 1 ("panel hidden") is only observable if the GETs 503 too. The gate
reads `apps.admin_portal.flags.is_enabled("SCREENER_ENABLED")` so a mutable
registry override is honored (matching `apps/strategies/views.py::_enabled`).

`@extend_schema(operation_id=…, tags=["screener"])` on every method; regen
OpenAPI snapshot + `pnpm schema:types` (the ADR-062 flow).

### 6.6 Frontend: Screening panel (`features/strategies/detail/`)

New standalone `screening-panel.component.ts` embedded in
`strategies-detail.component.ts` below the description, plus
`core/services/screener.api.ts`, `core/models/screener.models.ts`,
`abstraction/facades/screener.facade.ts` (facade-only, the ADR-062
`DataProvidersFacade` shape). States, in order of precedence:

1. Flag off / API 503 → panel hidden entirely.
2. `block_present: false` → empty state: "This strategy's description has no
   screening recommendations block" + guide link (`app-help-link
   slug="strategy-screening"`).
3. Criteria invalid → the line-numbered errors verbatim (author-facing).
4. FMP not configured (`FMP_NOT_CONFIGURED` on POST, or pre-checked via
   `DataProvidersFacade.load()`) → warn chip + staff link to
   `/settings/data-providers` / non-staff ask-admin copy (reuse
   `data_providers.staff_only`).
5. Ready → criteria chips (from the criteria endpoint — server parse only),
   **Run screen** button, poll the active run every 2s until terminal **and on
   component destroy** (A8: a deliberate 2s — runs are seconds-to-a-minute and
   the run GET is cheap. This is NOT the backtest detail page's cadence, which
   is 5000ms and exists as a WS-down fallback), then results table: symbol (mono), name, exchange,
   sector, market cap (compact `Intl.NumberFormat`), price, volume, % from 52w
   high, SMA badges. `degraded=true` → warn chip + per-cause counts line
   (`skipped_rate_limited`, `skipped_unavailable` (A4), `insufficient_history`).
   History: last 5 runs collapsible list.

BBCode renderer (`core/util/tradingview-description.ts`): add `[screen]…[/screen]`
to a swallow-entirely rule (drop tag AND inner text — unlike the strip-keep-text
default), so recommendations don't double-render as prose; specs extended
(incl. unclosed-`[screen]` falls back to strip-keep-text, never eats the rest
of the description).

### 6.7 Flag, throttle, audit (`config/settings/base.py`, `apps/audit/events.py`)

- `SCREENER_ENABLED = env.bool("SCREENER_ENABLED", default=True)` + registry
  row `_flag(SCREENER_ENABLED, "Strategy screener (FMP).")` (mutable).
- `django_ratelimit` on the POST (function-view wrap or `method_decorator` —
  match `apps/users/views.py:405` style), `RATELIMIT_ENABLE=False` keeps tests
  hermetic.
- `AuditEventType.SCREEN_RUN_REQUESTED = "screener.run_requested"` (+ audit
  migration for the choices change — the ADR-062 `0007` precedent).

### 6.8 Metrics (`apps/screener/metrics.py`)

`SCREEN_RUNS_TOTAL = Counter("screen_runs_total", …, ["result"])` with
`result ∈ {done, degraded, failed}`; `SCREEN_RUN_DURATION_SECONDS = Histogram`
(buckets 1–300s). Vendor traffic is already visible as
`marketdata_requests_total{endpoint="company-screener"}` for free.

**A6 — metrics only; no Grafana wiring.** ADR-109 (PR #50) deleted the Data
Pipelines dashboard and reduced Grafana to the 3-dashboard safety core, so the
"System Health dashboard's Data Pipelines row" this sentence used to name no
longer exists (and was never a System-Health row). Ship the counter and the
histogram and stop there; the series stay queryable in Explore, and whether they
earn a panel is a future ADR-109-scope decision, recorded in ADR-063.

### 6.9 Guide + docs

`assets/guides/strategy-screening.html` + `guides.catalog.ts` entry (CI guard
enforces the pair): what the panel does, the full key reference table from
§6.1, a worked Minervini example, the FMP-key prerequisite with a link to
`market-regime-setup`'s key section, quota notes (free-tier 250 req/day ⇒ a
50-candidate derived screen ≈ 51 calls; **A5:** a re-run re-spends them — the
response cache is a failure fallback, not a 24h dedupe — so the real bounds are
the 10/h/user throttle and the ≤100 enrichment cap;
`docs/runbooks/fmp-rate-limit.md` for sustained limits).

## 7. Tech Stack Notes

- **No new dependencies.** Parser is stdlib; SMA/52w-high math is plain Python
  over the bar dicts (numpy already present if wanted — don't reach for
  pandas).
- FMP `/company-screener` screens on **current** volume, not average volume —
  the guide says so and `volume:` maps accordingly (an `avg_volume` key is
  deliberately absent from the grammar to avoid promising what the vendor
  doesn't sell).
- The vendor's param table is JS-rendered in their docs; ADR-063 carries the
  §6.2 contract and AC-16-12 the live re-validation. Screener availability
  differs by FMP tier — the premium tier assumed by ADR-061 includes it; the
  error surface for a tier-blocked key is the same 4xx→`FMPError` path and
  lands as run `FAILED FMP_UNAVAILABLE`.
- Ranking is deterministic (AC-06-10 spirit): same inputs → same order (ties
  broken by symbol).

## 8. Data Model Changes

- New table `screener_run` (§6.3), additive migration; SQLite-compatible
  (JSONField, no partitioning).
- Audit `AuditLog.event_type` choices gain `screener.run_requested`
  (AlterField migration, no data change).
- No changes to `Strategy` / `StrategyFile` — the DESC file IS the criteria
  store; `StrategyFile.sha256` (already maintained) provides run provenance.

## 9. API Contract Changes

New tag `screener` (§6.5 table). Representative payloads:

`GET …/screen/criteria/` →
```json
{"data": {"block_present": true,
  "criteria": {"market_cap": {"gte": 2000000000}, "price": {"gte": 10, "lte": 1000},
               "volume": {"gte": 1000000}, "sector": "Technology",
               "above_sma": [200], "sma_rising": [200],
               "near_52w_high": 25, "limit": 50},
  "fmp_params": {"marketCapMoreThan": 2000000000, "priceMoreThan": 10,
                 "priceLowerThan": 1000, "volumeMoreThan": 1000000,
                 "sector": "Technology", "isActivelyTrading": true, "limit": 50},
  "derived": {"above_sma": [200], "sma_rising": [200], "near_52w_high": 25,
              "min_history": 260}}}
```

`GET …/screen/runs/{id}/` (terminal) →
```json
{"data": {"id": "…", "status": "DONE", "degraded": false,
  "criteria_sha256": "…", "created_at": "…", "finished_at": "…",
  "counts": {"vendor_matches": 312, "enriched": 50, "returned": 17,
             "insufficient_history": 3, "skipped_rate_limited": 0},
  "results": [{"symbol": "NVDA", "name": "NVIDIA Corp", "exchange": "NASDAQ",
               "sector": "Technology", "market_cap": 3200000000000,
               "price": 182.11, "volume": 41000000, "beta": 1.7,
               "pct_from_52w_high": 3.2, "above_sma_50": true,
               "above_sma_200": true, "sma200_rising": true}]}}
```

Error codes introduced: `FMP_NOT_CONFIGURED`, `NO_SCREEN_CRITERIA`,
`SCREEN_CRITERIA_INVALID`, `SCREEN_RUN_ACTIVE`, `SCREENER_DISABLED`,
`FMP_RATE_LIMITED`, `FMP_UNAVAILABLE` (all through the `{"error": {code,
message, details?}}` envelope).

## 10. Test Plan

### 10.1 Unit

- Parser table tests: every key/operator/suffix; range inversion (`5..2`),
  unknown key, duplicate key, duplicate block, oversized block, `%` bounds,
  `limit` clamp, comment/blank handling, unclosed tag; **fixtures from real
  TradingView exports** — licence-header lead-in, CRLF, BOM, block mid-prose
  (the #45 lesson: synthetic-only fixtures pass while real input fails).
- Criteria→FMP param mapping golden test (the §6.1 table, exactly).
- Derived math: SMA windows, slope, 52w-high distance, `min_history` drop —
  against a golden bar fixture.
- `company_screener()` contract test with injectable http (recorded fixture of
  the §6.2 field set; tolerate extra fields, fail on missing screened fields).

### 10.2 Integration (Django `TestCase`, eager Celery)

- Full lifecycle: seed strategy + DESC with block → POST → run executes with
  `FMPClient(http=FakeHttp)` fixtures → poll → results + counts + provenance
  sha; rerun-after-description-edit provenance change.
- Every gate of §6.5's POST ladder, each asserting code + status; active-run
  409; ratelimit 429 (`override_settings(RATELIMIT_ENABLE=True)`).
- Degradation: FakeHttp raising 429 mid-enrichment → DONE + degraded +
  `skipped_rate_limited` count; screener-call 500 with empty cache → FAILED.
- Permissions: non-owner private strategy → 404; system strategy visible;
  non-MFA user → 403 `MFA_REQUIRED` (sweep already covers the prefix).
- Key-gate integration with ADR-062: UI-stored key only (no env) → POST
  accepted (uses `resolve_key`).

### 10.3 E2E / a11y

- Karma: panel state ladder (hidden/empty/invalid/not-configured/ready),
  run+poll flow with a stubbed facade, degraded chip, results table rendering,
  `[screen]` swallowed from prose (renderer spec).
- Playwright `e2e/a11y`: axe pass on a strategy detail page with the panel in
  the ready state (extend the existing a11y spec set).

### 10.4 Performance

- 50-candidate derived screen completes < 60s with warm HTTP fixtures; task
  soft limit 240s leaves 4× headroom. One vendor screener call per run —
  assert via FakeHttp call-count.

### 10.5 Reproducibility

- Same criteria + same bar fixtures → byte-identical `results` JSON (ranking
  determinism, AC-06-10 spirit).

## 11. Security Considerations

- The `[screen]` block is **user-authored input parsed server-side**: size cap
  4096 bytes / 40 lines pre-parse, allowlisted keys, linear scan (no
  backtracking regex), numeric bounds clamped (`limit` ≤ 100), values never
  eval'd or interpolated into vendor URLs beyond httpx `params=` encoding.
- The FMP key never appears in run rows, logs, task args (task gets `run_id`
  only) or error strings — the existing `FMPError`/transport-redaction rules
  (FIX-M12) already cover the client.
- Strategy ownership enforced with the strategies-app permission helpers; runs
  are strictly owner-scoped; system strategies screenable by any MFA user but
  each user sees only their own runs (instance key spend bounded by the
  throttle).
- Audit on run creation; no criteria in the audit row (the run row is the
  record; audit stays PII/payload-light per AC-04-12 spirit).
- XSS: results render through Angular interpolation only (no `[innerHTML]`);
  vendor strings (company names) are data-bound, never trusted HTML.

## 12. Observability

§6.8 metrics; log lines `screener.run_started/finished/failed` with run id,
counts and duration (no symbols spam, no keys). Failures surface in Sentry via
the normal task error path. Dashboard row: Data Pipelines (placeholder-first
pattern).

## 13. Translation & Localization

New `screener.*` root in `en.json` (panel title, states, table headers, error
codes incl. `screener.error.FMP_NOT_CONFIGURED` pointing at Data Providers,
degraded counts line with `{{n}}` params). English-only, per the profile
page's stated support.

## 14. Documentation Deliverables

- ADR-063 — FMP company-screener adoption (the ADR-061 §4 gate): documented
  contract, fixture tripwire, live re-validation record, tier notes.
- Guide `strategy-screening` (§6.9) + catalog entry.
- `docs/runbooks/fmp-rate-limit.md` — add a paragraph: screener runs as a new
  burst source; what `skipped_rate_limited` in a run means for the operator.
- README milestone table + PROGRESS.md row updates.

## 15. Rollback Plan

Flip `SCREENER_ENABLED=false` (env or admin flag override): API 503s, panel
hides, zero vendor spend — no deploy needed. Full removal = revert the
migration (additive table + one choices AlterField; no other model touched).
Past runs are self-contained JSON — safe to drop.

## 16. Risks & Mitigations

| Risk | L×I | Mitigation |
|---|---|---|
| FMP screener params/fields differ from the documented contract (docs are JS-rendered; table unverifiable statically) | Med × Med | ADR-063 + fixtures as tripwire; AC-16-12 live re-validation at key-land; params built from the mapping table only — an unknown-param 4xx fails loud as `FMP_UNAVAILABLE`. |
| Screener endpoint tier-gated on some FMP plans | Med × Low | Same 4xx path → run FAILED with honest error; guide names the tier assumption (ADR-061: premium). |
| Free-tier quota burn (250/day) from derived screens | Med × Med | `limit` ≤ 100 hard cap; 10/h/user throttle; 24h bar cache + `Bar` store reuse; degraded-not-dead behavior on 429; runbook guidance. |
| Authors write prose-y blocks that fail parsing and conclude "screener is broken" | Med × Med | Line-numbered errors surfaced verbatim in the panel + criteria endpoint as a lint loop + authoring guide with copy-paste templates. |
| `[screen]` in descriptions of strategies imported before M16 (none exist — descriptions are operator-authored) breaking render | Low × Low | Renderer swallow-rule is additive; unclosed-tag fallback keeps prose intact (spec'd + tested). |
| Task pile-up from spammed runs | Low × Low | Active-run 409 + throttle; 240s soft limit; default queue keeps beat isolation intact (no route glob — M09 lesson). |

## 17. Exit Gate Checklist

- [ ] AC-16-1 … AC-16-12 pass (each with a named test or live-verification note)
- [ ] Full local gauntlet green: `ruff`, `bandit`, `pytest` (SQLite + `-m pg`), `ngc --noEmit`, karma, `pnpm build`, guards (`check_guides_catalog.py`, `check_envsubst_filter.py`), `makemigrations --check`, prod-import smoke
- [ ] OpenAPI snapshot + generated types regenerated and committed
- [ ] ADR-063 merged; guide live; CHANGELOG + PROGRESS updated
- [ ] Live re-validation with a real FMP key recorded (or explicitly deferred with the deferred-external banner, M06-style)
