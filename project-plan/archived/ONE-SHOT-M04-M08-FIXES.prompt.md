> **⚙️ SPENT ONE-SHOT — milestone shipped; not a work item.**
> This is the agent prompt that built a now-merged milestone. Moved out of the active plan on
> 2026-07-14 (OSS pivot) and kept for historical record only — **do not re-run.** The durable record
> of what shipped lives in `project-plan/PROGRESS.md` and the matching `M*-EXECUTION-REPORT.md`.

---

# ONE-SHOT PROMPT — Remediate StratTraderPro M04→M08 (post-implementation review fixes)

> Paste everything below the line into Claude CLI (max effort), running from the repo root
> `/Users/yuval3000/Documents/Claude/Projects/StratTraderPro`. Self-contained; runs end-to-end without
> human input. Operator decisions already made: **one remediation branch, admin-merge autonomously**;
> on a hard blocker for any single item, **skip that item, keep going**, and record it in the report.
> Every finding below was confirmed against the code at HEAD (`1dc33ef`) and the pinned runtime
> (Python 3.12 / Django 5.1.15). Line numbers are accurate as of that commit — re-grep before editing.

---

## MISSION

M04–M08 are implemented and merged (`v0.4.0`→`v0.8.0`, PRs #22–#26). An adversarial code review found
correctness and safety defects that CI did **not** catch (the suite passes: ruff/bandit clean, 306 pytest
green, ngc + ng build green — all re-verified locally). Your job is to fix them on **one remediation
branch**, with a regression test for every behavioural change, keep the full gauntlet green, and merge.

This is remediation, not new features. **Do not re-architect.** Smallest correct change per finding.
Each fix MUST ship with a test that fails before and passes after (the existing suite already codifies
several of these bugs as "expected" behaviour — you will need to correct those tests too; that is
expected and called out per-item).

## GROUND TRUTH — read before touching code

1. `project-plan/PROGRESS.md` — canonical status. `project-plan/M04-M08-EXECUTION-REPORT.md` — what was built + the ACs.
2. The five specs: `project-plan/0{4,5,6,7,8}-*.md` — authoritative for intended behaviour and the AC wording.
3. `CONTRIBUTING.md` + `.github/workflows/ci.yml` — branch naming, conventional commits, the exact CI gates.
4. Confirm the runtime matches CI before trusting any local run: **Python 3.12, Node 20, pnpm** (`pnpm-lock.yaml` is the lockfile; CI runs `pnpm install --frozen-lockfile` then `pnpm build`). The committed `.venv` may be an older Python — recreate on 3.12 or install `backend/requirements/dev.txt`+`test.txt` into a fresh 3.12 venv.

## PROJECT GUARDRAILS (violating these wastes hours — all still apply)

- **Local CI-parity gauntlet is the merge bar** (commands in §VERIFY). `pytest`+`tsc` alone is NOT enough — CI also runs `ruff`, `bandit`, and a real `pnpm build`.
- **Angular template errors need `ngc`, not `tsc`**: `cd frontend && npx ngc --noEmit -p tsconfig.app.json`.
- **Settings star-import drops `_`-prefixed names**: `dev.py`/`prod.py` do `from .base import *`. Any new `_helper` in `base.py` must be name-imported in `prod.py` or prod crashes at boot (tests won't catch it — the prod-import smoke does).
- **Prometheus under multi-process gunicorn**: `process_*` disabled; Gauges need `multiprocess_mode=`. Celery worker/beat processes expose no `/metrics` — see FIX-C1.
- **The webhook `sig` is a static bearer secret, not an HMAC** (ADR-042). Do not "fix" it into a computed HMAC.
- **Decimal discipline**: money/qty are `Decimal` end-to-end. `sizing.py` intentionally drops to `float` for the ratio math then returns `Decimal` — keep that boundary; do not widen float usage.

## ⚠️ DO NOT TOUCH — these were reviewed and are CORRECT (avoid false-lead churn)

- **Webhook idempotency is already race-safe**: Redis `cache.add` (SETNX) + `client_order_id`/`broker_exec_id` DB unique constraints + `get_or_create`. Do not add locks here.
- **Sizing re-clamp after the sentiment boost is already present** (`sizing.py` — `qty = min(qty, max_qty_by_pos)` after multipliers). Do not "re-add" it.
- **prod.py already name-imports `_wrap_db_engines_for_prometheus`** — the star-import gotcha is handled. Leave it.
- **No pickle in the HMM path** — models serialize to JSON; state-permutation is handled via per-model `state_labels`. Do not change the serialization.
- **`parse_datetime("2026-01-02")` does NOT return None on Django 5.1** (it delegates to `fromisoformat` → naive midnight). The review's "all FMP bars dropped" claim is FALSE on the pinned runtime. The real, smaller bug is tz-naivety → see FIX-M6-1. Do not add a `parse_date`-returns-None guard as if bars were being dropped.
- **`is_blocked` platform→user→strategy precedence and the NULL-user L3 halt gate** are correct at both the webhook view and `process_alert`. Leave the gate logic; only the items below change.

---

## THE FIXES

Severity: **BLOCKER** (safety/correctness, ship-stopping) → **HIGH** → **MEDIUM** → **LOW**.
Do them in order. Group commits by app. Every item lists: file, the defect, the required change, and the test.

════════════════════════════════════════════════════════════════════════
### BLOCKER
════════════════════════════════════════════════════════════════════════

**FIX-B1 — Daily-loss kill switch (L2) uses lifetime unrealized P&L against gross notional, not daily P&L against equity.**
`backend/apps/risk/killswitch.py` `user_daily_pnl()` (~L151-165) sums `(market_price - avg_cost) * qty`
over ALL open `Position` rows and calls it "daily P&L", with `equity = Σ|market_price*qty|` (gross open
notional). Consequences, both real and safety-critical:
  (a) a swing position held for weeks sitting at a loss trips L2 **every day**; because
      `release_expired_l2_halts()` runs in the same 30s `daily_loss_watcher` (`risk/tasks.py`), the halt
      auto-releases at rollover and **re-trips ~30-60s later → permanent lockout** for any user holding a loser;
  (b) a day-trader who realizes losses on **closed** round-trips shows flat positions → pnl 0 → L2 never fires;
  (c) `daily_loss_pct` is measured against position notional, so a user with one small position breaches on a trivial move.
`risk/test_risk.py::DailyLossTests` currently encodes the wrong semantics as expected — it must be rewritten.
**Change:** compute **broker-truth daily P&L**. Primary source: the broker account snapshot.
  - Add `equity` and `last_equity` (previous-day close) to the `Account` DTO (see FIX-H1 — do FIX-H1 first).
  - `user_daily_pnl(user)` → for each connected `BrokerAccount`, read `adapter.get_account()`; sum
    `equity` and `equity - last_equity` across the user's accounts. Return `(daily_pnl, equity)`.
  - **Fail-safe, not fail-firing**: if the broker read fails or returns no equity data, **do not trip** —
    return a sentinel that makes `check_daily_loss` skip this poll (log at WARNING). A monitoring gap must
    never auto-halt or auto-release trading. (This is the opposite of FIX-H2's sizing path, which fails *closed* by
    rejecting the order — here the safe default is to leave existing halt state untouched.)
  - Keep the two-poll confirmation and the "already tripped today → don't re-emit" short-circuit.
  - Gate the watcher to market hours (see FIX-M16) so off-hours mark drift can't trip it.
**Test:** rewrite `DailyLossTests` — a `FakeBrokerAdapter` with `equity`/`last_equity` set so daily P&L
breaches the $ threshold trips L2 after two polls; a held-overnight unrealized loss with `equity==last_equity`
(flat on the day) does **not** trip; a broker-read failure does not trip and does not release. Add a test that
a tripped L2 does not immediately re-trip after `release_expired_l2_halts()` on the same held position.

════════════════════════════════════════════════════════════════════════
### HIGH
════════════════════════════════════════════════════════════════════════

**FIX-H1 — Position sizing uses `buying_power` as equity (2–4× oversizing on every trade).**
`backend/apps/risk/integration.py` L78: `equity = adapter.get_account().buying_power`. Alpaca
`buying_power` is 2× equity (4× for PDT). The `Account` DTO (`brokers/base.py` ~L79) has no equity field.
**Change:**
  - Add `equity: Decimal` and `last_equity: Decimal` to the `Account` dataclass (`brokers/base.py`), default `Decimal("0")`.
  - `alpaca/mapping.py::map_account` (~L128): map `equity` and `last_equity` from the raw Alpaca account
    (fields confirmed present on `alpaca-py` 0.43.5 `TradeAccount`). Keep the existing `_dec(getattr(...))` guard style.
  - `FakeBrokerAdapter` (`brokers/fake.py`): add an `equity` ctor param defaulting to `Decimal("100000")`
    and set `equity`/`last_equity` in `get_account()` (default `last_equity == equity`). This keeps the existing
    sizing test's `equity==100000` assumption intact.
  - `integration.py`: `equity = adapter.get_account().equity`.
**Test:** `SizingTests` — a fake with `buying_power=200000, equity=100000` sizes off 100000, not 200000.

**FIX-H2 — Sizing equity fallback is a hardcoded $100k, fail-OPEN.**
`integration.py` L79-80: `except Exception: equity = settings.RISK_DEFAULT_EQUITY (100000)`. A transient
broker hiccup sizes a $5k account as if it had $100k. **Change:** on broker-read failure, **fail closed** —
reject the order with a new `SIZING_NO_EQUITY` reason (mirror the existing `SIZING_ERROR` reject path in
`webhooks/tasks.py`), persist a `SizingDecision(result=REJECT, reject_reason="SIZING_NO_EQUITY")`, emit the
reject metric. Never size off a constant. Delete the `RISK_DEFAULT_EQUITY` setting (or keep only for tests, but
do not use it in the prod path). **Test:** adapter whose `get_account` raises → order rejected `SIZING_NO_EQUITY`, no fill.

**FIX-H3 — Sizing invents a $100 price for market orders.**
`integration.py` L82: `price = price_hint or _latest_price(symbol) or Decimal("100")`. `price_hint` is only the
`limit_price` (None for every MKT order); `_latest_price` reads the `Bar` table, empty in prod. So every prod MKT
order is sized against $100/share. **Change:** no trusted price → **reject** `SIZING_NO_PRICE` (do not fabricate a
price). Prefer, in order: `price_hint` (limit) → a fresh broker quote if cheaply available via the adapter → last
`Bar.close`. If none, reject. **Test:** MKT alert, empty Bar table, no quote → `SIZING_NO_PRICE` reject; LMT alert
with `limit_price` sizes fine.

**FIX-H4 — L0 "flatten this strategy" liquidates the user's ENTIRE account.**
`risk/killswitch.py::flatten_user(user_id, *, scope, strategy_id)` accepts `strategy_id` and **never uses it** —
it loops all accounts calling `adapter.flatten_all()` (Alpaca `close_all_positions`). Reached from
`risk/views.py` L129-137 when a STRATEGY-scope kill switch is created with `flatten=true`. AC-08-7 requires
strategy-tagged positions only. Per-strategy position tagging does not exist yet. **Change (minimal, safe):**
reject `flatten=true` when `scope == "STRATEGY"` at the serializer/view with `FLATTEN_SCOPE_UNSUPPORTED`
(strategy toggle still halts new orders — the L0 block already works); only USER/PLATFORM scope may flatten.
Add a `# TODO(M09): per-strategy flatten once positions carry strategy_id` and a runbook note. **Test:**
STRATEGY kill switch with `flatten=true` → 400/validation, no `flatten_all` call; the L0 block still stops new orders.

**FIX-H5 — Position math inverts options BUY_TO_OPEN / BUY_TO_CLOSE fills.**
`backend/apps/orders/services.py` `_apply_fill_to_position` L92: `signed = qty if side == Order.Side.BUY else -qty`.
`order.side` for option alerts is `BUY_TO_OPEN`/`BUY_TO_CLOSE` (set in `webhooks/tasks.py`), which `!= Order.Side.BUY`,
so every buy-side option fill decrements the position. Options are a shipped M05 surface. **Change:** define a
buy-side set `{BUY, BUY_TO_OPEN, BUY_TO_CLOSE}` (or reuse `_BUY_SIDES` from `alpaca/mapping.py`) and test membership.
Apply the same fix to `fake.py::_apply_position`. **Test:** a `BUY_TO_OPEN` fill increases position qty; a
`SELL_TO_CLOSE` decreases it.

**FIX-H6 — Non-ASCII `sig` crashes the public webhook with a 500 (unauthenticated).**
`backend/apps/webhooks/views.py` L144: `hmac.compare_digest(sig, expected)` with `str` args raises `TypeError`
on any non-ASCII `sig` (confirmed). Any unauthenticated caller POSTing `{"sig":"é"}` (or a smart-quote paste)
gets a 500, skips the `SIG_BAD` audit, and pollutes the 5xx alert. **Change:**
`hmac.compare_digest(sig.encode("utf-8"), expected.encode("utf-8"))` (encode both sides). **Test:** non-ASCII
`sig` → 401 generic + `SIG_BAD` audit row, not 500.

**FIX-H7 — No timeout on any Alpaca HTTP call; no Celery task time limits.**
`alpaca/adapter.py` constructs `TradingClient(...)` with no timeout; `requests` with no timeout blocks forever,
wedging a Celery worker or the streams supervisor's catch-up on one black-holed TCP connection. There is no
`CELERY_TASK_TIME_LIMIT`/`SOFT_TIME_LIMIT` anywhere. (Contrast the TS client, which sets `httpx.Client(timeout=10.0)`.)
**Change:** (a) give the Alpaca clients a bounded timeout — mount a `requests.Session` with a timeout adapter, or
wrap calls with a timeout; a 10s default like TS is fine. (b) In `config/settings/base.py` set
`CELERY_TASK_SOFT_TIME_LIMIT` and `CELERY_TASK_TIME_LIMIT` (e.g. 30s/45s) as a backstop. **Test:** unit-assert the
Alpaca client is constructed with a timeout (or that the wrapper enforces one); assert the two settings are present and ordered soft < hard.

**FIX-H8 — Stream supervisor: masks dead streams, never hot-adds accounts, and busy-loops on persistent failure.**
`backend/apps/brokers/streams.py`, three linked defects in the supervisor:
  1. `run_forever` (~L145) calls `set_heartbeat(account.id)` for **every** active account every 15s, and the
     default state is `CONNECTED` — this overwrites a dead thread's `DEGRADED` back to `CONNECTED` and marks
     accounts that have **no thread at all** as healthy. `/brokers/{id}/status/` then lies.
  2. `start()` spawns threads once at boot; nothing subscribes to `brokers.accounts.changed`
     (`notify_accounts_changed` has no subscriber). An account connected after boot gets no stream, no fills,
     orders stuck SUBMITTED.
  3. `_run_account` (~L118-122) sets `attempt = 0` **before** the blocking `stream.run()`, so any persistent
     failure (auth/DNS) loops at ~1/sec forever, and each loop re-runs `catch_up_account` (REST fan-out) —
     self-inflicted broker+DB hammering; backoff never grows.
**Change:**
  - Let each stream thread own its heartbeat (set `CONNECTED` only on a received event / healthy run; set
    `DEGRADED` on disconnect). The main loop must **not** blanket-stamp CONNECTED — it should only (a) diff
    `load_active_accounts()` against `self._threads`, starting threads for new accounts and stopping threads for
    removed ones (this delivers the hot-add/remove requirement), and (b) prune dead threads.
  - Reset `attempt` to 0 only after the stream has run healthy for a minimum duration (e.g. first received event,
    or ≥60s connected), so `backoff_delay(attempt)` actually grows on repeated immediate failures.
**Test:** (unit, no live sockets) a fake stream that immediately raises N times → `attempt`/backoff grows
monotonically and `catch_up` is not called on every sub-second iteration; supervisor diff starts a thread for a
newly-active account and stops one for a removed account; a `DEGRADED` heartbeat is not overwritten to CONNECTED
by the main loop.

**FIX-H9 — Alert-specified broker silently misroutes to the wrong broker.**
`backend/apps/webhooks/tasks.py` L65-76: if an alert names a `broker` that the user hasn't connected, the code
falls back to the default/oldest account and **places the order on a different broker**. AC-05-2: "placed on that
broker only." Silent misrouting of real orders is worse than a reject. **Change:** when `broker_pref` is present
and no matching connected account exists, reject the alert (`AlertMessage.Status.REJECTED`,
`reject_reason="BROKER_NOT_CONNECTED"`, audit + WS event) — never fall through. Only fall back to default when the
alert did **not** specify a broker. **Test:** alert `{"broker":"TRADESTATION"}` with only Alpaca connected → REJECTED
`BROKER_NOT_CONNECTED`, no order; no-broker alert still uses the default.

**FIX-H10 — M06 daily feature/observation pipeline task is an unconditional stub; regime is permanently NEUTRAL in prod.**
`backend/apps/regime/tasks.py::compute_features_daily` returns `{"skipped": "no_market_data_source_configured"}`
unconditionally — it never checks whether keys ARE configured, and there is no `marketdata/tasks.py`. So even with
FMP/FRED keys set, no `FeatureVectorSnapshot`/`RegimeObservation` rows are ever produced → `retrain_hmm` stays
`skipped_insufficient_data`, `/regime/current/` is null forever, and M08 sizing always receives `"NEUTRAL"`.
The execution report frames this as "needs live feed" — it actually needs code. **Change:** implement the daily
task body: fetch the day's bars/macro via the existing `marketdata` services, compute + standardize features,
persist a `FeatureVectorSnapshot`, and call `compute_observation` — guarded so it is a genuine no-op **only when
keys are truly absent** (check settings/env, not an unconditional return). Wire the beat entry (it exists) and add
a `marketdata` daily-bars task if the spec's §6.8 requires it. Keep everything fixture-testable (no live keys in CI).
**Test:** with a stub/fixture market-data source injected, one `compute_features_daily` run produces a
`FeatureVectorSnapshot` and a `RegimeObservation`; with no source configured it returns skipped without error.

════════════════════════════════════════════════════════════════════════
### MEDIUM
════════════════════════════════════════════════════════════════════════

**FIX-M1 — `timezone.utc` was removed in Django 5; naive fill timestamps crash and the fill is dropped.**
`backend/apps/orders/services.py` `_parse_ts` (~L38): `timezone.make_aware(parsed, timezone.utc)`.
`django.utils.timezone.utc` does not exist on Django 5.1 (confirmed `hasattr → False`) → `AttributeError` on any
naive timestamp; in the prod transport that's caught as a "poison message", **acked, and the fill dropped**.
**Change:** `from datetime import timezone as dt_timezone` → `make_aware(parsed, dt_timezone.utc)` (or
`timezone.get_default_timezone()`). **Test:** `_parse_ts("2026-01-02 15:30:00")` (naive) returns an aware datetime.

**FIX-M2 — Fill dedup key `broker_exec_id` is globally unique, not scoped per broker/account.**
`backend/apps/orders/models.py` (~L134) `broker_exec_id = CharField(unique=True)`. Synthetic fallback exec-ids
(`f"{order_id}:{event}:{filled_qty}"` in Alpaca/TS mapping) share one namespace across brokers/users; a collision
silently swallows the second broker's fill. **Change:** make uniqueness `(broker_account, broker_exec_id)` (or
prefix exec-ids with the broker name at normalization). Migration required; keep it additive. **Test:** identical
`broker_exec_id` under two different accounts both persist.

**FIX-M3 — Sentiment "cap-weighted" market score is weighted by database primary key.**
`backend/apps/sentiment/aggregator.py` L78-83: `weights = dict(...values_list("symbol","id"))  # id as a stand-in
cap weight`. Autoincrement id is not a cap — recently-inserted tickers dominate market polarity. **Change:** use
equal weight (1.0) until real market-cap data exists; drop the id-weighting. Leave a `# TODO` for real caps.
**Test:** two symbols with opposite polarity and different ids average to ~0 (equal-weighted), not skewed to the higher id.

**FIX-M4 — RSS fetch has no timeout and no User-Agent (hangs the beat; EDGAR blocks the default UA).**
`backend/apps/sentiment/fetchers.py` (~L61): `feedparser.parse(self.feed_url)` fetches over urllib with no timeout
(one hung feed stalls the sequential `ingest_news` beat forever) and no declared UA (SEC EDGAR fair-access blocks
the default). **Change:** fetch bytes via `httpx` (explicit timeout + a descriptive `User-Agent` with contact),
then `feedparser.parse(content)`. **Test:** the fetcher passes a timeout and a custom UA (assert via a mocked httpx
call).

**FIX-M5 — RSS `published_at` never parses → all RSS articles get NULL dates and sort into limbo.**
`backend/apps/sentiment/services.py` (~L65): `parse_datetime(published)` on RFC-822 strings
(`"Mon, 07 Jul 2026 19:00:00 GMT"`) always returns None; the article list orders by `-published_at`. **Change:**
use `entry.published_parsed` (feedparser's struct_time) or `email.utils.parsedate_to_datetime` as a fallback; make
the result tz-aware. **Test:** an RFC-822 date string yields a correct aware `published_at`.

**FIX-M6 — Finnhub "RSS" fetcher points feedparser at a token-required JSON endpoint (never yields entries).**
`backend/apps/sentiment/fetchers.py` (~L88): `RSSFetcher(S.FINNHUB, "https://finnhub.io/api/v1/news?...")` — a JSON
REST endpoint, not a feed. **Change:** remove Finnhub from `build_fetchers()` defaults (or gate it behind a
clearly-off flag with a real JSON client). Do not present it as a working source in the report. **Test:**
`build_fetchers()` returns only fetchers that can actually parse their source.

**FIX-M6-1 — FMP bar timestamps stored naive under `USE_TZ=True` (tz-hygiene; NOT the "bars dropped" claim).**
`backend/apps/marketdata/services.py::upsert_bars` (~L31): `parse_datetime` on a date-only string returns a **naive**
datetime on Django 5.1 (midnight), which is then written to the `Bar.ts` `DateTimeField` — emitting a naive-datetime
`RuntimeWarning` and relying on implicit default-tz interpretation. **Change:** if the parsed ts is naive, make it
aware in UTC before upsert (`timezone.make_aware(ts, dt_timezone.utc)`). Do **not** add a "parse_datetime returned
None → bars dropped" guard — that path does not occur on the pinned runtime. **Test:** `upsert_bars` with a
date-only `ts` stores an aware midnight-UTC timestamp and the `(symbol,tf,ts)` upsert stays idempotent on re-run.

**FIX-M7 — Common-word ticker false positives; cashtags bypass the registry.**
`backend/apps/sentiment/tagger.py`: `\b[A-Z]{1,5}\b` filtered only by a ~30-word stopword set + registry membership,
but registry-listed common words (ALL, NOW, ON, CAN, SO, GO, ARE) and `T` (from "T-Mobile") tag spuriously; cashtags
(`$XYZ`) are added `unchecked` (~L40-42), bypassing the registry entirely. **Change:** require cashtags to also be
registry members (or a separate high-confidence path); expand the stopword list to cover the common-word tickers;
prefer cashtag/`$`-prefixed or multi-signal matches for ambiguous 1–2 char symbols. **Test:** an all-caps headline
containing ALL/ON/T does not tag those unless cashtagged; `$AAPL` tags AAPL; `AAPL` in a sentence tags via registry.

**FIX-M8 — L2 trading-day rollover hardcodes a fixed UTC-5 offset (wrong under EDT / DST).**
`backend/apps/risk/killswitch.py` L29: `_DAY_OFFSET = timedelta(hours=5)`; `trading_day()` subtracts a fixed 5h.
During EDT (e.g. July) the US/Eastern boundary is UTC-4, so halts release an hour late and the
`risk:dl:{user}:{trading_day()}` cache key + same-day lock inherit the skew. **Change:** compute the trading day
via `datetime.astimezone(ZoneInfo("America/New_York")).date()` (stdlib `zoneinfo`). **Test (freezegun, already in
`test.txt`):** an instant that is a different calendar day in UTC vs New York maps to the New York day; assert both
an EST and an EDT instant.

**FIX-M9 — HMM swap guard compares holdout log-likelihoods from different windows.**
`backend/apps/regime/services.py::activate_model` (~L77): compares `new.holdout_ll >= current.holdout_ll`, but each
LL was computed on its own training-time holdout — not comparable, so the guard reacts to data drift, not model
quality. **Change:** before comparing, rescore the currently-active model on the **new** holdout window
(`deserialize_model(current.params).score(hold_X)`) and compare like-for-like. Keep the non-finite-LL rejection.
**Test:** given a fixed holdout, a strictly-worse candidate is rejected and a strictly-better one activates.

**FIX-M10 — A new `httpx.Client` is created (and leaked) per request/retry in FMP and FRED.**
`backend/apps/marketdata/fmp.py` (~L88) and `fred.py` (~L23): `client = self._http or httpx.Client(timeout=...)`
inside the per-call path leaks a connection pool on every call (×retries). **Change:** create one `httpx.Client`
per `FMPClient`/`FREDClient` instance (lazily), reuse it, and close it (context-manager or explicit `close`).
**Test:** multiple `get`/`series` calls reuse a single client instance (assert via a spy/mock).

**FIX-M11 — FMP malformed-JSON (200-with-HTML) bypasses the whole resilience layer.**
`backend/apps/marketdata/fmp.py` (~L102): `_raw_get` ends with `return resp.json()`; a proxy error page raises
`json.JSONDecodeError`, which is not an `FMPError`, so `get()`'s `except FMPError` never runs — no breaker, no
metric, no cache fallback, exception escapes (violates AC-06-9 "never 5xx"). **Change:** wrap `resp.json()` and
raise `FMPError` on decode failure so it flows through the existing fallback. **Test:** a 200 with non-JSON body →
cache fallback / handled error, not an uncaught exception.

**FIX-M12 — FRED leaks `api_key` in exception URLs and has no resilience.**
`backend/apps/marketdata/fred.py` (~L30): raw `httpx.RequestError` propagates with `exc.request.url` carrying
`api_key=...` (Sentry request-context can capture it); unlike FMP there's no retry/breaker/cache. **Change:** mirror
FMP — catch transport errors and re-raise `from None` (strip the keyed URL); add at least a timeout + a single retry.
**Test:** a transport error does not surface the api_key in the raised message.

**FIX-M13 — Regime features fail OPEN toward RISK_ON when macro/stress inputs are missing.**
`backend/apps/regime/features.py` (~L72-81): missing `vix`/`hy_oas`/`move`/`ig_oas` default to `0.0`, then
`standardize()` z-scores 0 against a history of real values → strongly negative z on stress features whose weights
are negative → score pinned high → RISK_ON → M08 scale 1.0. Data loss should neutralize, not de-stress. **Change:**
on a missing input, set its standardized value to 0 (neutral) and mark the observation degraded (a flag the UI
already renders), rather than feeding raw 0 through the z-score. **Test:** an observation with VIX/HY missing does
not classify RISK_ON solely due to the gap; degraded flag set.

**FIX-M14 — Releasing a kill switch requires no MFA (only engaging does).**
`backend/apps/risk/views.py` (~L122): `if active and not verify_mfa_code(...)` — MFA is checked only when engaging.
A hijacked session can silently **release** a USER global halt (or a staff session a PLATFORM halt) and resume
trading. Release is the dangerous direction for a session thief. **Change:** require a valid MFA code for USER and
PLATFORM scope on **both** engage and release. **Test:** release without/with a valid MFA code → 403 / success.

**FIX-M15 — `daily_loss_watcher` has no overlap guard and runs 24/7.**
`backend/apps/risk/tasks.py` + beat entry (30s): no lock/`expires`; O(users) with a broker read per user — once a
run exceeds 30s, two overlapping runs `cache.incr` the same key within one stale window, defeating the two-poll
protection. **Change:** add a redis lock (or beat `expires=25`) so only one runs at a time; add a market-hours gate
(skip when US markets are closed) — this also supports FIX-B1. **Test:** a second invocation while one "holds the
lock" is a no-op; off-hours invocation skips.

**FIX-M16 — Validate alert numeric/date fields; route parse errors through reject, not an uncaught 500/stall.**
`backend/apps/webhooks/tasks.py`: `Decimal(str(body.get("qty")))` accepts `"NaN"`/`"Infinity"` (only
`InvalidOperation`/`TypeError` on construction are caught; both parse fine) → `Decimal("NaN") > 0` raises later and
strands the alert in `RECEIVED`/`PENDING_SUBMIT`; `option_expiry` is written into a `DateField` unvalidated.
**Change:** reject non-finite Decimals (`qty.is_finite()` and `> 0`) with `INVALID_QTY`; validate `option_expiry`
parses to a date; wrap the intent-parse block so any error routes through the existing `_reject(order, alert, ...)`.
**Test:** `qty:"NaN"`, `qty:"Infinity"`, and `option_expiry:"not-a-date"` each produce a clean REJECTED alert, no 500, no stuck order.

**FIX-C1 — Task-side Prometheus metrics are unscrapeable (most M06–M08 observability is dark) + dead M04 metrics.**
Nearly every new counter/gauge (`hmm_retrain_total`, `sentiment_*`, `sizing_*`, `killswitch_*`,
`daily_loss_breach_total`, `broker_stream_disconnects_total`) increments inside Celery worker/beat/streams
processes, which expose no `/metrics` endpoint and share no multiproc dir with the web service — so the committed
Grafana dashboards and the §12 alerts can never populate. Separately, four M04 metrics
(`fills_ingested_total`, `broker_stream_heartbeat_age_seconds`, `order_state_transitions_total`,
`broker_ws_reconnects_total`) are defined and exported but never `.inc()/.set()` anywhere. **Change:**
  - Emit the four dead M04 metrics at their real call sites (fills in `ingest_fill_event`; heartbeat-age from the
    cache key; state transitions on order status change; ws reconnects in the stream loop).
  - Expose task-process metrics: start a `prometheus_client` HTTP endpoint in the worker/beat/streams entrypoints
    (or write to a shared `PROMETHEUS_MULTIPROC_DIR` the scraper reads), following the existing gunicorn multiproc
    pattern. Give Gauges an explicit `multiprocess_mode=`.
  - This is infra-shaped; if the full exporter wiring can't land cleanly, at minimum emit the dead metrics and
    document the worker-scrape gap in a runbook, and record it as deferred. Do not fake it green.
**Test:** unit-assert the four metrics increment at their call sites; a smoke that the worker entrypoint exposes a metrics port (or writes multiproc files).

════════════════════════════════════════════════════════════════════════
### LOW (cheap, clearly-correct — do them; skip any that balloons in scope)
════════════════════════════════════════════════════════════════════════

**FIX-L1 — Position basis wrong on a through-zero flip.** `orders/services.py` (~L94-99) and `fake.py`: a long→short
(or short→long) flip keeps the old `avg_cost`; the residual's basis should be the flip fill price. Set
`avg_cost = price` when the sign flips. Test the flip case.

**FIX-L2 — Kill-switch `target_id` (strategy) is neither existence- nor ownership-checked.** `risk/views.py` (~L133):
a bogus/foreign strategy UUID reaches `TradingHalt.objects.create(strategy_id=...)` → 500 or a cross-user junk row.
Validate ownership in the serializer. Test a foreign/nonexistent id → 400/404.

**FIX-L3 — `SizingDecision.inputs` omits equity and price** (the two most safety-relevant inputs). `integration.py`
stores only `result.meta`. Add `equity` and `price` to the persisted inputs. Test they appear.

**FIX-L4 — Sentiment article list is N+1** (`sentiment/views.py` ~L92: `a.scores.filter(...)` per row). Add
`prefetch_related("scores")`. (Optional, no behaviour change — skip if it complicates the queryset.)

**FIX-L5 — Non-ASCII broker API key → 500 instead of 400.** `brokers/serializers.py`/`services.py`
`encrypt_key(raw.encode("ascii"))` raises `UnicodeEncodeError`. Add a serializer validator rejecting non-ASCII →
400. Test a Unicode-dash key → 400.

**FIX-L6 — Dead RiskEvent types.** `SIZING_REJECT` and `SOFT_STOP` are enum-only, never emitted; emit `SIZING_REJECT`
on a sizing reject and `SOFT_STOP` when the soft-stop halving applies, so the events feed is complete. Test one emission.

---

## SCOPE BOUNDARY — record as follow-ups, do NOT attempt in this run
(They need product decisions, new data models, or externals — a remediation branch is the wrong place.)
- Per-strategy position tagging (the real fix behind FIX-H4) — needs a schema change; M09.
- Enforcing `RiskProfile.max_concurrent` / `leverage_cap` / `permitted_asset_classes` (currently dead fields) —
  needs a design pass on limits + order-count accounting; note in the report and open a plan item.
- TradeStation OAuth state TOCTOU + refresh-lock and the cross-user account-linking interstitial — the TS adapter is
  behind `BROKER_TRADESTATION_ENABLED=false`; fix before TS go-live, out of scope here (record in the report).
- Live/staging verifications already deferred in the execution report (Alpaca paper smoke, 50-user load, p99).

## VERIFY — the CI-parity gauntlet (must be GREEN before every push)
```bash
# Backend (from backend/, in a Python 3.12 venv with dev.txt + test.txt installed)
python -m pytest -q -p no:warnings
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python manage.py makemigrations --check --dry-run --settings=config.settings.test
DJANGO_SETTINGS_MODULE=config.settings.prod python -c "import django; django.setup(); print('prod-import OK')"   # catches the star-import gotcha
# Frontend (from frontend/, Node 20)
npx ngc --noEmit -p tsconfig.app.json
pnpm install --frozen-lockfile && pnpm build
```
All must pass. The prod-import smoke is mandatory (tests don't load `prod.py`). If you added a `_`-prefixed helper
to `base.py`, name-import it in `prod.py`.

## WORKFLOW
1. **Branch** off fresh `main`: `git checkout main && git pull origin main && git checkout -b fix/m04-m08-review-remediation`.
2. **Implement** the fixes in severity order. One logical commit per fix (or per app-group), conventional-commit
   messages (`fix(risk): daily-loss watcher uses broker equity, not lifetime unrealized P&L (FIX-B1)`). Every
   behavioural fix ships with its regression test in the same commit. Correct the existing tests that encode the old
   (wrong) behaviour — call those out in the commit body.
3. **Migrations:** FIX-M2 (fill dedup scope) and possibly FIX-H1 (DTO only — no migration) — keep migrations additive;
   run `makemigrations` and commit them; verify `makemigrations --check` is clean.
4. **Docs:** update `CHANGELOG.md` under `[Unreleased]` with a "Fixed" block referencing FIX-ids; add a short
   `docs/runbooks/` note for FIX-H4 (strategy-flatten limitation) and FIX-C1 (worker metrics scrape) if you defer any
   part; amend ADR-080/081 "honest limits" if FIX-B1 changes the documented daily-loss semantics (it does).
5. **Verify** the full gauntlet green.
6. **PR:** `gh pr create --base main --title "fix(m04-m08): review remediation" --body <file>` — fill the PR template
   DoD checklist; paste a table of every FIX-id → status (fixed / deferred-with-reason) and the gauntlet results.
7. **Review:** run `/code-review` (and `/security-review` for the auth/webhook/kill-switch items) on `git diff main...HEAD`;
   address MEDIUM+ findings; re-run the gauntlet.
8. **Merge:** `gh pr merge --squash --admin --delete-branch`. If `--admin` is blocked, leave the PR open, record it, stop.
9. **Report:** append a "Remediation" section to `project-plan/M04-M08-EXECUTION-REPORT.md` and update
   `project-plan/PROGRESS.md`: every FIX-id with final status + evidence (test name), the scope-boundary follow-ups,
   and any item you had to defer with the reason. Do **not** push release tags (operator step).

## DELIVERABLE
One squash-merged PR on `main` with all BLOCKER+HIGH+MEDIUM fixes (and the LOWs that stayed cheap), each with a
regression test, full gauntlet green, CHANGELOG + report updated, scope-boundary items documented as follow-ups.
Anything you must defer: keep going, and write down exactly what and why.
