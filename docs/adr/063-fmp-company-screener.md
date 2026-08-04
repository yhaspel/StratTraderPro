# ADR-063 — Adopting FMP's `/stable/company-screener` for the strategy screener

**Date:** 2026-08-03
**Status:** Accepted
**Milestone:** M16 — Strategy Screener
**Reference:** ADR-061 **§4** (the vendor-change gate this ADR *is*); ADR-062 (the
instance FMP key this endpoint spends); ADR-109 (why no dashboard panel);
`project-plan/16-strategy-screener.md` §6.1–§6.2, §6.4, §7, §16; AC-16-5,
AC-16-7, AC-16-12; the 2026-08-03 spec-review amendments **A5** (no read-through
caching), **A6** (metrics only) and **A9** (`isEtf` always sent)

## Context

M16 turns a `[screen]` block inside a strategy description into a ranked
candidate list. The pipeline is deliberately two-stage: **one** vendor-side call
applies the fundamental/universe filters, then a local pass over daily bars
applies the derived ones (SMA 50/200, SMA-200 slope, distance from the 252-session
high). That first stage needs an endpoint FMP already sells and we have never
called: `…/stable/company-screener`.

ADR-061 §4 is explicit about what that costs procedurally: parsing is pinned by
contract tests against recorded fixtures, no live vendor call runs in CI, and a
**vendor-change ADR is required before adopting a new endpoint or format** — the
fixtures are the tripwire, an ADR is the gate. This is that ADR.

Two facts shape everything below:

- **FMP's docs render their param table client-side.** The endpoint path and the
  filter *families* are readable statically; individual param spellings are not
  uniformly verifiable without executing their page. §16 rates "FMP screener
  params/fields differ from the documented contract" Med×Med for exactly this
  reason.
- **There is no FMP key on this machine.** `resolve_key("FMP")` is empty (no
  `DataProviderKey` row, no `FMP_API_KEY` in `.env`), so the live half of
  AC-16-12 cannot be executed in this run — it is recorded as an open item (§4)
  under the M06 deferred-external convention, not quietly skipped.

## Decision

### 1. Adopt `/company-screener` on the existing base URL, through the existing resilience stack

`backend/apps/marketdata/fmp.py`:

```python
def company_screener(self, params: dict) -> list[dict]:
    return self.get("/company-screener", params, cache_ttl=300) or []
```

- **Base URL unchanged** — `FMP_BASE_URL`, default
  `https://financialmodelingprep.com/stable` (ADR-061's table). No second base,
  no v3 route.
- **The shared `get()` path, unmodified**: client-side token bucket → tenacity
  retry (3 attempts, jittered, on 429/5xx) → circuit breaker → **cache-FALLBACK**.
  AC-06-9 semantics come for free, and the call is metered as
  `marketdata_requests_total{endpoint="company-screener"}` with no new metric.
- **Exactly one call per run** (AC-16-5). Derived criteria never cost a screener
  call; they are computed locally from `daily_bars`, and the bars are upserted
  into the shared `Bar` store for M06A reuse.
- **Params are built only from the §6.1 mapping table.** `apps/screener/criteria.py`
  allowlists every key, so a typo in a description is a line-numbered authoring
  error — never an unrecognized vendor param and never a silently widened screen.
  Values reach the wire through `httpx`'s `params=` encoder only; nothing is
  interpolated into a URL by hand and nothing is `eval`'d.
- **Failure mapping** (`apps/screener/tasks.py`): `FMPRateLimited` /
  `FMPCircuitOpen` on the screener call → run FAILED `FMP_RATE_LIMITED`; any
  other `FMPError` (4xx, or an outage with a cold cache) → run FAILED
  `FMP_UNAVAILABLE`. The screener call is the one stage that fails the run rather
  than degrading — a run with no universe has nothing honest to show.

### 2. Param provenance, per family

On **2026-08-03** the FMP stable docs page rendered and the params in the
"web-confirmed" rows below were read off it directly. The `*LowerThan` halves
were **not visible on the page** and are carried as *documented-contract-to-verify*
— the same status ADR-061 §4 gives a shape proven only against recorded fixtures.

| FMP param | From `[screen]` key | Provenance |
|---|---|---|
| `marketCapMoreThan` | `market_cap: >= N` / lower half of `A..B` | web-confirmed 2026-08-03 |
| `marketCapLowerThan` | `market_cap: <= N` / upper half of `A..B` | documented-contract-to-verify |
| `priceMoreThan` | `price: >= N` | web-confirmed 2026-08-03 |
| `priceLowerThan` | `price: <= N` | documented-contract-to-verify |
| `volumeMoreThan` | `volume: >= N` | web-confirmed 2026-08-03 |
| `volumeLowerThan` | `volume: <= N` | documented-contract-to-verify |
| `betaMoreThan` | `beta: >= N` | web-confirmed 2026-08-03 |
| `betaLowerThan` | `beta: <= N` | documented-contract-to-verify |
| `dividendMoreThan` | `dividend: >= N` | web-confirmed 2026-08-03 |
| `dividendLowerThan` | `dividend: <= N` | documented-contract-to-verify |
| `sector` | `sector` | web-confirmed 2026-08-03 |
| `industry` | `industry` | web-confirmed 2026-08-03 |
| `exchange` | `exchange` | web-confirmed 2026-08-03 |
| `country` | `country` (ISO-2, upper-cased) | web-confirmed 2026-08-03 |
| `isEtf` | `etf` (always sent; `false` unless `etf: true` — A9) | web-confirmed 2026-08-03 |
| `isActivelyTrading` | always sent as `true` | web-confirmed 2026-08-03 |
| `limit` | `limit` (1–100, default 50, out-of-range clamps) | web-confirmed 2026-08-03 |

No other param is sent, and none is invented: the grammar's key list *is* the
param list. Nothing outside this table can reach the vendor.

**What it means if a `documented-contract-to-verify` name is wrong.** The two
failure modes are not symmetric, and the honest one is the worse one:

- If FMP **rejects** the unknown param (4xx), the run fails loud as
  `FMP_UNAVAILABLE` — annoying, obvious, fixable.
- If FMP **ignores** it, the upper bound silently does not bind and the screen is
  *wider* than the author asked for. The lower bound still applies, so results
  still look plausible. **No fixture can catch this** — a fixture pins the
  response shape, not the server's filtering semantics. Only the live
  re-validation in §4 closes it, which is why that check explicitly asserts a
  bound actually binds rather than merely that the call returns 200.

### 3. Response fields pinned by fixture — the tripwire

`backend/apps/screener/fixtures/company_screener.json` records three rows
(NVDA/MSFT/AAPL) carrying the §6.2 documented field set:

```
symbol, companyName, marketCap, sector, industry, beta, price,
lastAnnualDividend, volume, exchange, exchangeShortName, country,
isEtf, isActivelyTrading
```

`backend/apps/marketdata/test_company_screener.py` is the gate ADR-061 §4 asks
for, and its asymmetry is deliberate:

- **Missing field ⇒ CI fails.** `DOCUMENTED_FIELDS` is asserted present on every
  fixture row, and the results-row builder reads `symbol`, `companyName`,
  `exchangeShortName`/`exchange`, `sector`, `marketCap`, `price`, `volume`,
  `beta` — a rename upstream would otherwise ship half-populated rows to a user
  with no error anywhere.
- **Extra fields ⇒ tolerated.** Vendors add columns; that is not a breakage
  (`test_extra_vendor_fields_are_tolerated`).

The same file pins the behaviors this ADR claims above, so the claims are tested
rather than asserted: the documented path is hit
(`test_returns_rows_and_hits_the_documented_path`), params pass through untouched
plus the key (`test_params_are_passed_through_untouched_plus_the_key`), a null
body degrades to `[]`, 429 retries then succeeds, a cold-cache 429 raises, a 4xx
is **not** retried, cache-fallback serves the last good payload, and the metrics
label is `endpoint="company-screener"`.

### 4. Live re-validation is DEFERRED — the open item, with its closing steps

**AC-16-12's live half is not met and is not claimed to be.** No FMP key exists
on this instance, so everything above is proven against the documented contract
only. Recorded here per ADR-061 §4's "the vendor's *documented* shape is proven;
its *live* shape is re-validated when the key lands" and M06's deferred-external
precedent.

To close it, once a real key is present (Settings → Data Providers, or
`FMP_API_KEY`):

1. **Confirm the key resolves:**
   `python manage.py shell -c "from apps.marketdata.keys import resolve_key; print(bool(resolve_key('FMP')))"`.
2. **Call the endpoint with a full-shape param set** (both halves of one range,
   so the unverified names are actually exercised):

   ```
   python manage.py shell -c "
   import json
   from apps.marketdata.fmp import FMPClient
   rows = FMPClient().company_screener({
       'marketCapMoreThan': 2000000000, 'priceMoreThan': 10, 'priceLowerThan': 1000,
       'volumeMoreThan': 1000000, 'sector': 'Technology',
       'isActivelyTrading': True, 'isEtf': False, 'limit': 25})
   print(len(rows)); print(json.dumps(rows[0], indent=2))
   print('max price:', max(r['price'] for r in rows))"
   ```

3. **Assert the fields**: the returned row's keys must be a superset of
   `DOCUMENTED_FIELDS` (§3). Missing ⇒ re-record the fixture from the real
   payload and adjust `enrich.result_row` before shipping anything further.
4. **Assert the unverified halves actually bind** (the §2 silent-widening risk):
   `max price` above must be ≤ 1000, and re-running without `priceLowerThan`
   must return a *different, wider* set. If the bound does not bind, the param
   name is wrong — find the real spelling, fix `_RANGE_KEYS` in
   `apps/screener/criteria.py`, and update §2.
5. **Record the tier** the key is on (the §5 caveat) and whether the endpoint
   answered at all.
6. **Amend this ADR in place**: flip the affected provenance rows to
   `live-verified <date>`, note the tier, and tick AC-16-12 in
   `project-plan/16-strategy-screener.md` §17 with the date. Re-run
   `pytest backend/apps/marketdata/test_company_screener.py` after any fixture
   re-record.

### 5. Tier caveat — the screener may not be on every plan

FMP gates endpoints by plan, and the screener is not universally included.
**ADR-061 assumes the premium tier**, which is the tier this decision inherits.
A key whose plan does not include the endpoint is not a special case in the code:
it returns 4xx → `FMPError` (explicitly **not** retried — a 4xx is a client error,
pinned by `test_tier_blocked_key_surfaces_as_a_plain_fmp_error`) → the run lands
`FAILED` with `error_code = FMP_UNAVAILABLE`. The user sees an honest failed run,
the operator sees `marketdata_requests_total{endpoint="company-screener",result="fail"}`
and the runbook, and the guide names the tier assumption so the failure is
diagnosable without reading code.

### 6. Quota honesty: there is no read-through cache (amendment A5)

This must not be misdescribed, because the mitigation in §16 and the guide's
quota advice both depend on it.

**`FMPClient.get()` is fetch-always.** It calls the vendor, and the response
cache is written on success — but the cache is **read only in the failure path**
(rate limit, open breaker, exhausted retries, transport outage). There is no
"cached ⇒ skip the call" branch anywhere in the client. Consequently:

- A run costs **1 screener call + up to `limit` `daily_bars` calls** when the
  block has any derived key (≤ 101 calls at the `limit` ≤ 100 hard cap), or
  exactly **1 call** for a vendor-only block.
- **Re-running the same screen 5 minutes later re-spends all of them.** The
  `cache_ttl=300` on the screener call and the 24h TTL on daily bars size the
  *fallback window* — how long a stale copy remains available to rescue a
  degraded run — not a dedupe window.
- The real bounds on vendor spend are therefore the **10 run-creates/user/hour
  throttle** and the **≤ 100 enrichment cap**: worst case ≈ 10 × 101 ≈ 1010
  vendor calls per user per hour.
- `upsert_bars` still runs on every enriched symbol. That is for **M06A reuse of
  the `Bar` store**, not a quota optimization — v1 never reads it back (§8).

### 7. Observability: metrics only (amendment A6)

M16 ships `screen_runs_total{result="done"|"degraded"|"failed"}` and
`screen_run_duration_seconds`; vendor traffic needs nothing new because the call
already appears as `marketdata_requests_total{endpoint="company-screener"}`.

**No dashboard panel.** The spec's "Data Pipelines row" target no longer exists:
ADR-109 deleted that dashboard and reduced Grafana to a 3-dashboard safety core.
The series ship and stay queryable in Explore; whether they earn a panel is a
future decision **inside ADR-109's scope**, explicitly out of scope here. Adding
one in this milestone would re-grow the surface ADR-109 just cut.

### 8. Explicitly not in v1

- **A store-first read.** Consulting the local `Bar` store before calling the
  vendor for daily bars is *not* in v1. It is the obvious quota win, and it is a
  real decision rather than an optimization: it needs a freshness policy (how
  stale may a stored bar be before a run must refetch?), gap semantics (a
  partially-backfilled symbol must not pass `min_history` on stale rows), and a
  story for the store being nearly empty on a fresh instance — which it is today,
  since these upserts are what start populating it. Revisit as its own change,
  with the §6 numbers as the motivation.
- **Multi-value vendor enums** (`sector: A|B`) — the parser rejects them with a
  line-numbered error rather than guessing a delimiter.
- **Extra vendor filter families** (P/E, revenue growth, `avg_volume`). The
  endpoint screens on *current* session volume; the grammar deliberately has no
  `avg_volume` key so it cannot promise what the vendor does not sell.
- **Per-candidate vendor enrichment** beyond daily bars — AC-16-5 forbids it.

## Consequences

**Positive:**

- One new endpoint, zero new machinery: the same rate limit, retry, breaker,
  cache-fallback and metrics as every other FMP path, so there is nothing new to
  operate and `docs/runbooks/fmp-rate-limit.md` already covers it.
- The fixture tripwire fails in CI if FMP drops or renames a screened field —
  the ADR-061 §4 contract, honored.
- Params are allowlisted at parse time, so no user-authored text can reach the
  vendor as an unexpected filter; the blast radius of a bad block is a
  line-numbered error in the panel.
- Vendor-side spend per run is bounded and stated (§6), not hand-waved.

**Negative / honest limits:**

- **Five param names are unverified** (§2), and the failure mode if one is wrong
  is a *silently wider* screen, which no fixture can detect. Live re-validation
  (§4) is the only closer.
- **AC-16-12's live half is deferred** — there is no FMP key on this machine. The
  wire shape is proven against a recorded fixture only.
- **No read-through caching** (§6): repeat runs re-spend quota. On a free-tier
  key, a handful of 50-candidate derived screens is a day's budget.
- **A tier-blocked key fails the whole run** rather than degrading — correct
  (there is no universe to degrade to), but it means "screener is broken" and
  "your plan doesn't include the screener" look identical until someone reads the
  error code.
- **No dashboard panel** for the new series (§7), by ADR-109's design.

## Alternatives considered

1. **Build the screen locally from the `Bar` store — adopt no new endpoint.**
   Rejected: the store holds only symbols we have previously fetched, so there is
   no universe to screen; and it has no market cap, sector, industry, beta or
   dividend at all. It would require a full-universe fundamentals backfill —
   strictly more vendor spend than one screener call.
2. **Skip the screener; enrich a fixed symbol list with per-candidate calls.**
   Rejected: quota explodes (one call per symbol before any filtering), the
   candidate universe becomes a hard-coded artifact, and AC-16-5 forbids it.
3. **Block M16 until a real FMP key lands and the live shape is proven.**
   Rejected: the key is an external we do not control, and ADR-061 §4 already
   defines the alternative — prove the documented shape against fixtures now,
   re-validate live when the key lands. Same treatment M06 gave every endpoint it
   shipped.
4. **Use the legacy `/api/v3/stock-screener` route.** Rejected: ADR-061 pins the
   `…/stable` base for every endpoint; mixing bases would fork `FMPClient`'s
   `base_url` handling for one method, and the v3 surface is the one being
   superseded.
5. **Send only the web-confirmed params — drop the `<=` halves from the grammar
   until they are verified.** Rejected: it trades an *unverified* upper bound for
   a *guaranteed missing* one — `price: 10..1000` would silently apply half of
   what the author wrote either way, and the grammar would then have to change
   again when §4 closes. Keeping one grammar localizes the uncertainty in this
   ADR and in one live check.

## See also

- ADR-061 §4 — the vendor-change gate this ADR satisfies (and §3, the resilience
  stack this endpoint rides)
- ADR-062 — the instance FMP key resolution (`resolve_key`) this endpoint spends
- ADR-109 — the reduced observability scope behind §7's "metrics only"
- `backend/apps/marketdata/fmp.py` — `FMPClient.company_screener`
- `backend/apps/marketdata/test_company_screener.py` — the contract test / tripwire
- `backend/apps/screener/fixtures/company_screener.json` — the pinned payload
- `backend/apps/screener/criteria.py` — the §6.1 grammar the params are built from
- `backend/apps/screener/tasks.py` — the one-call-per-run pipeline and its failure mapping
- `docs/runbooks/fmp-rate-limit.md` — operating a rate limit / outage, screener runs included
- `frontend/src/assets/guides/strategy-screening.html` — the authoring guide (quota + error surface)
- `project-plan/16-strategy-screener.md` §6.1–§6.2, §6.4, §7, §16
