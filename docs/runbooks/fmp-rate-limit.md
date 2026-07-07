# Runbook — FMP rate limit / outage

**Owner:** Yuval
**Status:** Executable checklist — the token-bucket rate limit, retry/backoff,
circuit breaker, and cache-fallback are built and unit-tested (M06, AC-06-9).
Live FMP calls are **not** exercised in CI — an **FMP premium key is a deferred
external** (`docs/adr/061-data-vendor-fmp.md`); this runbook applies once a key
is set in Railway env.
**Companion docs:** `docs/adr/061-data-vendor-fmp.md` (the vendor + resilience
decision this operationalizes — read §3 first),
`docs/runbooks/hmm-retrain-failure.md` (a starved feature pipeline can strand the
nightly retrain), `project-plan/06-market-data-and-regime.md` §6.1, §12, §16.

## The one thing to know first

**An FMP rate limit or outage must never 5xx the dashboard (AC-06-9).** By
design, `FMPClient.get` (`backend/apps/marketdata/fmp.py`) degrades to the **last
cached response** instead of raising. So if a user says "the dashboard looks a
bit stale," that is the resilience *working*, not an outage. This runbook is
about confirming the degradation, understanding how deep it is, and — only if
needed — adjusting the client-side cap.

## How the client behaves under pressure (§6.1, ADR-061 §3)

Four layers, in the order `get` applies them:

1. **Token-bucket rate limit (client-side).** A fixed per-minute window
   (`fmp:rl:{minute}` in the Django cache) counts requests and, once it exceeds
   `FMP_RATE_LIMIT_PER_MIN` (default **750**), raises `FMPRateLimited`
   **before** a request leaves us and increments
   `marketdata_ratelimit_waits_total`. We throttle *ourselves* rather than earn a
   real 429 from FMP.
2. **Retry with backoff.** `tenacity`, **3 attempts**, exponential jitter
   (`initial=0.1s`, `max=2.0s`) on `FMPRateLimited` / `FMPError` (429 / 5xx).
3. **Circuit breaker.** After **5 failures within a 60s cooldown** the breaker
   opens for 60s (`FMPCircuitOpen`); further calls short-circuit instead of
   hammering a vendor that's down. It self-closes after the cooldown on the next
   success.
4. **Cache-fallback.** On rate-limit, open circuit, or exhausted retries, `get`
   returns the **last cached response** for that path+params if present (logging
   `fmp.cache_fallback`) and **only raises if nothing is cached**. Cache TTLs are
   30s intraday / 24h daily (with a 30s floor), so a cached copy almost always
   outlives a short stall.

Net effect on the dashboard: **cached data, never a 5xx** — until a cache miss on
a path we've never fetched, which is the only case that surfaces an error.

## Symptoms / when to open this

- **Alert: FMP error rate > 5% over 10 min** (§12).
- `marketdata_requests_total{result="fail"}` climbing, or
  `marketdata_ratelimit_waits_total` climbing.
- Logs showing repeated `fmp.cache_fallback` warnings.
- A user reports the regime badge / prices look slightly stale (a few minutes
  behind) but **nothing is 500-ing** — the expected degraded state.
- The nightly HMM retrain is `skipped_insufficient_data` because the feature
  pipeline couldn't fetch fresh bars/macro (cross-link:
  `docs/runbooks/hmm-retrain-failure.md`).

## Step 1 — Check the metrics to size the problem

| Metric | What it tells you |
|---|---|
| `marketdata_requests_total{endpoint,result}` | The `result="fail"` / `result="ok"` split **per endpoint**. A spike localized to one endpoint (e.g. `historical-sector-performance`) is an FMP-side problem with that route; a broad spike across all endpoints is a rate-limit or a full FMP outage. |
| `marketdata_ratelimit_waits_total` | How often we hit our **own** per-minute cap. Rising here means *we* are throttling — the fix may be raising `FMP_RATE_LIMIT_PER_MIN` (Step 3), not FMP being down. |
| `marketdata_bars_ingested_total{tf}` | If this stalls while the market is open, ingestion is actually blocked (cache-fallback returns stale reads but writes no new bars). |

Read the two together:

- **`ratelimit_waits` rising, `requests{result=fail}` mostly from us** → we are
  self-throttling against our configured cap. Either our cap is set too low for
  the tier, or our call volume genuinely spiked. Step 3.
- **`requests{result="fail"}` rising with 429/5xx from FMP, `ratelimit_waits`
  flat** → FMP is rate-limiting or down on their side. The breaker will open and
  cache-fallback carries the dashboard. Mostly wait it out (Step 2); don't raise
  our cap (that makes it worse).

## Step 2 — Confirm the dashboard is degrading gracefully, not failing

This is the AC-06-9 check. Confirm the user impact is *staleness*, not *errors*:

- `GET /api/v1/regime/current/` still returns **200** with a slightly older `ts`
  — the ensemble runs on the last good features. It does **not** 5xx.
- Look for `fmp.cache_fallback` in the logs: each line is one request that
  degraded to cache instead of erroring — exactly the intended path.
- The only genuine error is a **cache miss on a never-fetched path**. If you see
  `FMPError` / `FMPRateLimited` / `FMPCircuitOpen` propagating (not caught by
  cache-fallback), it's because that path had no cached copy yet — the fix is to
  let the breaker cooldown pass and re-warm the cache, not a code change.

If the dashboard is genuinely 5xx-ing on market data, that is a **defect against
AC-06-9** — capture the endpoint + stack and treat it as a bug, because the
contract is that it can't.

## Step 3 — Adjust `FMP_RATE_LIMIT_PER_MIN` (only when we're self-throttling)

`FMP_RATE_LIMIT_PER_MIN` (default **750**, the assumed premium per-minute limit)
is the client-side token-bucket size. Change it **only** when Step 1 shows *we*
are the throttle (`marketdata_ratelimit_waits_total` climbing) — not when FMP is
429-ing us.

- **Confirm the real tier limit** with FMP first (the 750 default is an
  assumption from §6.1 — "confirm with Yuval"). Set the cap **at or just below**
  the true per-minute limit, never above it — the bucket exists to keep us under
  FMP's ceiling.
- Set it in Railway env: `FMP_RATE_LIMIT_PER_MIN=<n>`. It's read via
  `settings.FMP_RATE_LIMIT_PER_MIN` at client construction, so a redeploy /
  restart picks it up.
- **Lower** it if we're genuinely earning real 429s from FMP (we're over the
  tier); **raise** it toward the true tier limit if we're stalling ourselves well
  under FMP's actual ceiling.
- If call volume is the problem rather than the cap, remember caching is the
  first lever (ADR-061 §2): the 30s/24h TTLs already collapse bursts — a wider
  symbol set or too-frequent polling is what pushes volume up.

## Step 4 — Verify recovery

- `marketdata_requests_total{result="ok"}` resumes climbing; `result="fail"` flat.
- `marketdata_ratelimit_waits_total` stops climbing (if the cap was the issue).
- `marketdata_bars_ingested_total{tf}` resumes during market hours.
- No more `fmp.cache_fallback` warnings in the logs.
- The FMP-error-rate alert clears.

## Note on the deferred key

The whole resilience stack is proven in unit tests with an **injectable HTTP
client** (rate-limit enforcement, retry-on-429, breaker-open-after-N,
cache-fallback) — no live FMP call runs in CI, and `backfill_bars` refuses to run
without `FMP_API_KEY`. The **live premium key is a deferred external**
(ADR-061); this runbook becomes operable the moment it's set in Railway env, at
which point re-confirm the true per-minute tier limit and set
`FMP_RATE_LIMIT_PER_MIN` to match.
