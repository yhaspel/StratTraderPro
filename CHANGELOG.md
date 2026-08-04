# Changelog

All notable changes to StratTraderPro will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added — Strategy Screener: turn a description's universe rules into a runnable screen (M16)

- **A `[screen]` block in a strategy description is now executable.** Authors already
  described the universe they wanted in prose ("liquid large caps above the 200-day, near
  52-week highs"); M16 makes that machine-readable. Add a small `[screen]` block to the
  description and `/strategies/:id` grows a **Screening** panel: parsed criteria as chips, a
  **Run screen** button, and a ranked candidate table.
- **Deterministic, not clever.** Criteria come from a strict `key: value` grammar parsed
  server-side — no LLM, no second parser in TypeScript, no separate criteria editor to drift
  out of sync with the description. Unknown keys are line-numbered errors rather than
  warnings, because a typo that silently widens a screen is worse than one that fails.
  15 keys: `market_cap`, `price`, `volume`, `beta`, `dividend` (with `>=`/`<=`/`A..B` and
  K/M/B/T suffixes), `sector`, `industry`, `exchange`, `country`, `etf`, `above_sma`,
  `sma_rising`, `near_52w_high`, `min_history`, `limit`.
- **Two stages, one vendor call.** Vendor-side filters go out in a single new
  `/company-screener` request (ADR-063, adopted under the ADR-061 vendor-change gate); the
  derived filters (SMA 50/200, SMA-200 slope, 52-week-high proximity) are computed locally
  from daily bars, which are also upserted into the shared `Bar` store. Enrichment is hard-
  capped at 100 candidates and ranking is fully deterministic — identical inputs produce a
  byte-identical result set, ties broken on symbol.
- **Degrades instead of lying.** A rate limit or an outage part-way through enrichment
  finishes the run `DONE` with `degraded=true` and per-cause counts
  (`skipped_rate_limited`, `skipped_unavailable`, `insufficient_history`) rather than
  truncating silently or 5xx-ing. A single bad ticker skips that symbol and keeps going; only
  a screener call that fails with a cold cache fails the run.
- **Bounded by design.** 10 runs/user/hour, one active run per (user, strategy) enforced by a
  partial unique index as well as a pre-check, `limit ≤ 100`, and a 240s task soft limit.
  Rollback is the mutable `SCREENER_ENABLED` flag: off means every screener endpoint 503s,
  the panel hides itself, and vendor spend goes to zero with no deploy.
- Screening activates only once an FMP key is configured (Settings → Data Providers or
  `FMP_API_KEY`, ADR-062); without one the panel says so and links staff straight to the
  settings page instead of failing on click.
- New authoring guide `strategy-screening` (full key reference, a worked Minervini example,
  quota maths); `docs/runbooks/fmp-rate-limit.md` gains a section on screening as a new burst
  source; screener runs are included in the GDPR personal-data export.
- Honest note on quota: the FMP response cache is a **failure fallback**, not a read-through
  cache, so re-running a screen re-spends its calls. The real bounds are the throttle and the
  enrichment cap, and the guide/runbook say so.

### Added — FMP/FRED keys are now settable in the UI (Settings → Data Providers, ADR-062)
- **New page `/settings/data-providers`** (user menu → *Data providers*): one instance-wide
  set of FMP + FRED API keys, staff-editable, stored Fernet-wrapped with the platform KEK
  (`marketdata_provider_key` table). Keys are validated live against the vendor **before**
  persisting (the brokers AC-04-6 rule: a bad key never creates a row; a 429 is accepted —
  rate-limited still means authenticated), are write-only on the API, and surface only a
  last-4 hint. Non-staff see status + "ask your administrator".
- **Resolution order everywhere: UI-stored key → `FMP_API_KEY`/`FRED_API_KEY` env var →
  unconfigured** (`apps.marketdata.keys.resolve_key`, the single choke point;
  `FMPClient`/`FREDClient` default through it). A key saved in Settings reaches web, Celery
  worker and beat through the shared DB **immediately — no per-service env vars, no
  redeploy** — which retires the "set it on all three Railway services" trap from the
  2026-07-29 handoff. Env-only deployments keep working untouched.
- New API: `GET /api/v1/marketdata/keys/` (status; MFA-enforced),
  `PUT/DELETE /api/v1/marketdata/keys/{provider}/` (staff + MFA). Set/remove are audited
  (`marketdata.provider_key_set`/`…_removed`, no key material). OpenAPI snapshot + generated
  types refreshed.
- The regime card's "data source not configured" empty state, Admin → Health's hint, and
  the `market-regime-setup` guide now point at Settings → Data Providers first, env vars
  second. `backfill_bars` names both paths in its refusal message.
- Tests: 29 backend (encryption round-trip, resolution precedence, gate lights up from
  UI-stored keys alone, validate-before-persist, never-echo, staff/MFA gates, audit rows) +
  7 karma specs for the Settings page. MFA sweep test now covers `/marketdata/keys/`.

### Changed — Observability reduced to the safety core (ADR-109)
- **Alert rules 18 → 9 in `alert-rules.yaml`** (+2 unchanged usage-budget rules = 11
  as code). Retired: `OrderSubmitLatencyHigh`, `SentimentLag`, `HMMModelStale`,
  `DBConnectionSaturation`, the three backtest rules, and both `ApiErrorBudget*Burn`
  burn-rate rules. The dead-man's pair (`MetricsPipelineDown`/`TargetDown`), the
  kill-switch/stream/webhook/audit safety alerts, and both budget guards stay.
- **Dashboards 6 → 3**: `trading-ops`, `risk-ops`, `system-health` kept, with SLO
  wording replaced by plain targets and the never-built exporter follow-up row
  removed; the retired panels' series all remain exported and queryable in Explore.
- `docs/runbooks/incident-triage.md` now triages exactly the 11 live rules —
  including new rows for the dead-man's pair and the metrics-budget pair — and the
  runbook/setup-guide set no longer references SLOs, exporters, or six dashboards.

### Removed — service-era observability surface (ADR-109)
- `postgres-exporter` + `redis-exporter` (compose services, agent scrape jobs
  7 → 5; the Railway service deletion is the operator step in the plan). Their only
  committed consumer was the retired `DBConnectionSaturation` rule.
- Dashboards `auth-health`, `data-pipelines`, `backtest-ops`; the cloud-side
  hand-made auth rules/folder are deleted in the operator step (alerts-as-code
  invariant restored).
- `docs/slo.md` — SLO/error-budget framing retired with the hosted-service
  posture (PIVOT-TO-OSS WP-3); kept thresholds live on in `alert-rules.yaml` +
  `incident-triage.md`.

### Added — Guides tab (replaces the buried /help index)
- **Guides is now a primary nav tab.** The help articles shipped in M10.5 were reachable
  only from the user dropdown, so in practice nothing in the product told a user how to use
  the product. `/help` and `/help/:slug` still resolve (redirect), because those links are
  in older builds and in people's bookmarks; every inline "?" affordance now points at
  `/guides/:slug`.
- `frontend/src/app/features/guides/` replaces `features/help/`; assets moved
  `assets/help/` -> `assets/guides/`. New `guides.catalog.ts` is the single source of truth
  for which articles exist — it drives the index, the viewer's slug allow-list (an unknown
  slug now 404s before any HTTP call, not just a malformed one) and prev/next links.
- Index is grouped into six sections with a one-line summary per article and a filter box,
  instead of thirteen bare titles in one column.
- **Five new step-by-step guides, with screenshots**: `getting-started` (account -> 2FA ->
  broker -> strategy -> first fill), `using-a-strategy`, `webhook-payload-template` (every
  field, where it goes in TradingView, and how to read each rejection code),
  `settings-profile`, `market-regime-setup`.
- Screenshots are generated, not hand-captured: `frontend/tools/guide-screenshots.mjs`
  drives the production bundle against stubbed API fixtures under Playwright. They show the
  real components with fictional data, so they carry no account identifiers into a public
  repo and can be regenerated after any restyle.
- Guard: `scripts/check_guides_catalog.py` (CI) cross-checks the catalog against
  `assets/guides/*.html` in both directions and verifies every referenced screenshot exists
  — a catalog entry with no file renders a card that opens "not found", and a file with no
  entry is an orphan article unreachable from the index.
- New a11y specs cover `/guides`, an article, and the `/help/:slug` redirect.

### Fixed — Admin health cards: `[object Object]`, and two cards that rendered nothing
- `sentiment_backlog` has always been `{depth, oldest_age_min, alert}` on the wire. The SPA
  typed it `number` and interpolated the object, so the Overview and Health KPI cards
  displayed the literal string **`[object Object]`**. Now renders `depth`, plus the oldest
  unscored age and a warn chip when the backlog alert threshold is crossed.
- Same drift, worse symptom, in two neighbours: `active_halts` is `{total, platform}` and
  `flags_overridden` is a count, both typed as `string[]`. `.length === 0` on an object is
  `undefined === 0` — false — so the "no active halts" / "no overrides" empty states never
  rendered and `@for` got a non-iterable: **both cards drew a heading and nothing else**.
- `broker_streams` is stream-state -> *count*, not -> label. The count was being bound to a
  status chip's `[status]`, so every chip read "1" and took its tone from the string "1"
  rather than from CONNECTED/DEGRADED/DOWN.
- Backend tests now pin all four shapes, so the wire contract fails in CI rather than in a
  screenshot.

### Fixed — Settings: the timezone could not be selected
- The option list was `allTimezones.slice(0, 100)` — the first hundred IANA names
  alphabetically, i.e. `Africa/*` through `America/A*`. A profile saved as `Asia/Jerusalem`
  had no matching `<option>`, so the `<select>` rendered with `selectedIndex = -1`: nothing
  looked selected, the saved value was named nowhere on screen, and scrolling the six-row
  listbox could never reach the wanted zone. The only way through was guessing that the
  unlabelled search box above it was the answer.
- The full IANA list renders now (~420 entries, no cap); the saved zone is unioned into the
  list even if the browser does not enumerate it, is scrolled into view, is named above the
  field with its UTC offset, and survives filtering. Added a "Use my browser timezone"
  shortcut, a "showing N of M" count so a stale filter is visible, a label for the search
  input, and an explicit no-match message.

### Fixed — Strategy descriptions were write-only
- `/strategies/:id` rendered the uploaded description all along, but **nothing in the UI
  linked to it** — the list showed only `description_short` ("User-uploaded strategy.
  Untested.") and the row actions were Configure webhook / Delete. A description typed at
  upload time could not be read back anywhere in the app.
- The strategy name is now a link, and each row has explicit **View** and **How to use**
  actions. The detail page leads with the description (loading state instead of a false
  "no description" while the file is in flight), adds the TradingView payload template
  pretty-printed, and links to the relevant guides.
- File loads are `Promise.allSettled`: a missing `WEBHOOK_TEMPLATE` no longer blanks out the
  description as collateral.

### Fixed — Header read "Offline" everywhere, always
- **nginx had no `/ws/` location.** `environment.prod.ts` derives
  `wss://<page-host>/ws/dashboard/` and its comment claims nginx proxies it — but the
  handshake fell through to the SPA fallback, so nginx answered the Upgrade request with
  `200 text/html` (index.html). A browser cannot upgrade an HTML response: every socket died
  with close code 1006, the client retried on its capped backoff forever, and the Live dot
  read Offline in every session since the M04 dashboard shipped. Added the proxy block with
  the `$connection_upgrade` map, `WS_URL` (+ envsubst allowlist, compose-shaped default),
  and a 3600s read timeout so the 25s client heartbeat is never cut.
- **Second, independent bug:** only `DashboardComponent` opened the socket, while the
  indicator lives in the shell header on *every* route. Strategies / Risk / Settings / Admin
  were therefore Offline by construction. The shell now owns the connection for the
  authenticated session (`DashboardWsService` is already refcounted, so the dashboard
  attaching on top is safe), and the indicator carries a tooltip saying which thing is
  offline and what it costs.
- Note: `WS_URL` must point at the daphne service (`SERVICE_ROLE=ws`), not the gunicorn one
  — prod backend runs `config.wsgi`, and WSGI cannot serve WebSockets at all.

### Fixed — Dashboard "Market Regime" said "no data yet" with no way to find out why
- Not a UI bug: `compute_features_daily` short-circuits with
  `{"skipped": "no_market_data_source_configured"}` unless **both** `FMP_API_KEY` and
  `FRED_API_KEY` are set. It is a deliberate no-op (writing neutral placeholder features
  would bias the rolling z-scores for months), so with the keys unset no `RegimeObservation`
  is ever written, the HMM never trains, and the card is empty forever — indistinguishable
  from a broken pipeline.
- `GET /regime/model/` now returns `source_configured`, and the dashboard card says "data
  source not configured" with a link to the new `market-regime-setup` guide instead of the
  misleading "no data yet". The history band is suppressed in that state rather than
  repeating the same empty message underneath.
- `GET /admin/health/` gains `regime_source_configured` (+ a card on Admin -> Health), so an
  operator gets the answer in the product rather than from Celery logs.
- The claim is only made on an explicit `false`; an older backend that omits the field
  degrades to the previous wording rather than lying.

### Fixed — Strategy list: pausing a strategy made it vanish (looked like upload deleted it) (#46)
- `Strategy.is_enabled` doubled as the soft-delete flag AND the list-row arm/disarm toggle:
  the list endpoint filtered `is_enabled=True`, so switching the toggle off removed the row
  from the list on the next load — indistinguishable from deletion, with no UI path back.
  Reported as "uploading a strategy removes the older one": upload → pause → next upload's
  list reload hid the paused row.
- Deletion is now its own field: `Strategy.deleted_at` (migration `0002`, with a data rule
  stamping pre-existing `is_enabled=False` rows as legacy soft-deletes). The list and the
  backtest picker show all non-deleted rows — paused strategies stay visible with the toggle
  off; deleted rows 404 on detail/PATCH (no resurrection). DELETE stamps `deleted_at` and
  disarms. The strategy-count gauge now excludes deleted rows.
- **Ingest actually honors the toggle now**: neither the webhook view nor `process_alert`
  ever consulted the strategy row, so a paused *or soft-deleted* strategy with a live
  webhook config kept accepting alerts and placing orders. Both now reject with an audited
  `STRATEGY_DISABLED` (same 200-reject envelope as a halt), including the task-side
  re-check for pause races and stranded-alert redispatch.
- Frontend needs no changes: the list template already renders `is_enabled=false` rows with
  the toggle off, and re-enabling goes through the existing P1-10 confirm.
- Regression tests: paused-visible/deleted-hidden list split, delete stamps + 404s,
  ingest + task-level `STRATEGY_DISABLED`, and a pause→reject→re-enable→accept round-trip.

### Fixed — Strategy upload: Pine `//@version` detection
- Upload step 3 rejected every unmodified TradingView export with *"Pine file must declare
  //@version=N within first 64 bytes."* The licence header TradingView auto-inserts is ~110
  bytes on its own, pushing the annotation to roughly byte 127 — outside the window the
  validator looked in. The annotation is now matched on any line of the file
  (`PINE_VERSION_REGEX`, start-of-line anchored so a match inside a string literal doesn't
  count), which also fixes the case where the 64-byte slice cut the token in half.
- The declared version is now parsed rather than merely detected: a bare `//@version=` no
  longer passes, and `SUPPORTED_PINE_VERSIONS = (5, 6)` rejects the TradingView-sunset v1–v4
  with an explicit message plus `details.declared_version`. A leading UTF-8 BOM is stripped
  before matching. Error code stays `STRATEGY_FILE_MISMATCH`.
- Every pine fixture in `test_strategies.py` had the annotation on line 1, which is why the
  suite never caught this; added `_tradingview_pine()` plus seven regression tests covering
  the licence header, deep placement, BOM/CRLF, the token boundary, and the reject paths.
- Help doc (`assets/help/strategy-upload.html`) updated to describe the real rule.

### Fixed — Review remediation, Phase 3 (P3 · Low / defense-in-depth)
- Backend: P3-5 admin-gate `/api/schema/` + `/api/docs/` in prod; P3-6 enforce the strict
  `default-src 'none'` CSP in prod; P3-4 bound user-editable JSON Schema complexity at save
  (depth / no `patternProperties` / capped `pattern`) to prevent a self-inflicted regex-DoS on
  the ingest hot path; P3-1 document the sizing float→Decimal boundary; P3-2 bad-sig write
  amplification is bounded by the P2-2 rate limit + keyless P2-5 rows.
- Frontend: P3-7 same-origin-only post-login redirect; P3-8 validated OAuth authorize URL
  (https + host allowlist); P3-9 unified guard predicate (via P1-4); P3-10 leak-safe help
  subscription; P3-11 removed the dead refresh-interceptor filter; P3-12 typed the retry path;
  P3-13 24×24 help tap target; P3-14 `scope="col"` on the orders/risk tables.
- Scoped follow-up: P3-3 (daily-loss equity caching — scaling note), chart.js config typing,
  and filter/paginate `aria-live` result counts.

### Fixed — Review remediation, Phase 2 (P2 · Medium)
- **Backend abuse-resistance** — P2-1 webhook IP allowlist reads the trusted (right-most)
  XFF entry per `WEBHOOK_TRUSTED_PROXY_COUNT`; P2-2 split bad-sig vs valid-alert rate
  budgets so a flood can't starve a victim's alerts; P2-3 per-IP limits on
  register/resend/reset; P2-4 IP-scoped login lockout (ADR-108); P2-5 durable
  idempotency anchor (`unique(user, idempotency_key)`, migration 0002) + stranded-alert
  requeue; P2-6 nightly export eviction + purge-on-anonymize; P2-7 kept the audit chain's
  advisory lock (the suggested row-lock forks the chain — validated + documented);
  P2-8 row-locked refresh rotation + one-step grace jti (migration 0006).
- **Frontend lifecycle** — P2-9 WS refcount no longer leaks on reconnect (openSocket split);
  P2-10 dashboard JWT rides the `Sec-WebSocket-Protocol` subprotocol, not the URL;
  P2-11 socket tears down on logout / stops reconnecting when logged out; P2-12 help HTML
  bound via Angular's sanitizer (no `bypassSecurityTrustHtml`); P2-13 OnPush on data-heavy
  screens; P2-14 `provideAppInitializer` + timeout-bounded bootstrap refresh.
- **Design / a11y / UX** — P2-DESIGN-1 dashboard halt uses the shared focus-trapping modal
  with an explicit flatten choice; DESIGN-2 register form wires `aria-describedby`;
  DESIGN-3 route-change focus + aria-live announcement; DESIGN-4 AA-contrast danger/success/
  accent tokens; DESIGN-6 auth submit buttons stay enabled (focus first invalid on submit);
  DESIGN-7 risk-event JSON behind a keyboard-accessible expander; DESIGN-8 strategies-upload
  validation moved to i18n with humanized sizes.
  DESIGN-5 (migrate 485 hardcoded Tailwind palette colors → design tokens across 34 feature
  files) is tracked as incremental follow-up per the plan's "screen-by-screen" guidance.

### Fixed — Review remediation, Phase 1 (P1 · High)
- **P1-1 · MFA login brute-force** — the login second factor was per-IP-limited only.
  Added a per-user failure cap (locks the challenge, `MFA_LOCKED`) plus per-token (jti)
  burn so a failed `mfa_token` can't be reused. (`apps/users/{views_m02,mfa}.py`.)
- **P1-2 · Option/future sizing multiplier** — sizing ran with multiplier=1, so every
  option/future risk ceiling was ~100× too loose. `apply_sizing` now sets the contract
  multiplier (100 options; per-root futures map); `max_qty_by_pos` divides by
  price×multiplier. (`apps/risk/{sizing,integration}.py`, `apps/webhooks/tasks.py`.)
- **P1-3 · GDPR export download** — the emailed `/media/exports/…` URL 404'd (nothing
  serves `/media/`). Now served through an authenticated, owner-checked, expiry-checked
  `FileResponse` view. (`apps/users/{views_gdpr,tasks,urls}.py`.)
- **P1-4 · Refresh token in localStorage** — moved to an `HttpOnly; Secure; SameSite=Strict`
  cookie stripped from the JSON body; the SPA never sees it. SameSite=Strict is the CSRF
  control (ADR-107). (`apps/users/cookies.py` + auth views; frontend auth store/facade/api/
  interceptor/guards.)
- **P1-5 · Ambiguous submit orphaned a live order** — a timeout/transient submit failure
  now marks the order `NEEDS_RECONCILE` (new non-terminal status, migration 0005), not
  `REJECTED`; reconcile resolves it by `client_order_id`. (`apps/orders/{models,services,
  reconcile}.py`, `apps/webhooks/tasks.py`, `apps/brokers/{streams,alpaca/adapter}.py`.)
- **P1-6 · Order filled_qty** — terminal state now trusts the broker's cumulative
  `filled_qty` (local sum fallback), so a dropped intermediate fill still reaches FILLED.
  (`apps/orders/services.py`.)
- **P1-7 · Halts voided by engine flag** — `is_blocked` always enforces active
  platform/user/daily-loss halts; `KILL_SWITCHES_ENABLED` gates only auto-tripping.
  (`apps/risk/killswitch.py`.)
- **P1-8 · hard_stop_pct never enforced** — at/above the hard-stop drawdown the order is
  rejected (`HARD_STOP`) and the daily L2 halt trips. (`apps/risk/{sizing,integration}.py`.)
- **P1-9 · Audit scrubber exact-match** — `scrub()` now redacts by substring (shared list
  with the GDPR redactor); `StrategyDetailView.patch` audits only allowlisted fields.
  (`apps/audit/scrub.py`, `apps/users/gdpr.py`, `apps/strategies/views.py`.)
- **P1-10 · One-tap strategy enable** — enabling now routes through the shared modal with
  consequence copy; disable stays one-click; toggle exposes `role="switch"`/`aria-checked`.
  (`features/strategies/list/`.)

### Fixed — Review remediation, Phase 0 (P0 · money & trust safety)
- **P0-1 · Risk/sizing fail-open with no RiskProfile** — a user without a `RiskProfile`
  (the default state) had the entire sizing + auto-circuit-breaker layer disabled: raw
  webhook qty reached the broker unclamped and the L2 daily-loss auto-halt never armed.
  Now a **live** account with no profile is rejected (`NO_RISK_PROFILE`); a conservative
  default profile is **auto-provisioned on broker connect** (leverage 1×, strict, STOCK/ETF);
  the daily-loss watcher covers every connected live account via a default threshold. Paper
  keeps M04 verbatim-qty behavior. (`apps/risk/{integration,killswitch,tasks,provisioning}.py`,
  `apps/brokers/views.py`.)
- **P0-2 · Dropped fills on transient ingest error** — `drain_stream` ack'd the Redis-stream
  entry unconditionally after a bare `except`, so a transient DB error silently dropped the
  fill (at-least-once → at-most-once). Now ack only on success; poison → per-user dead-letter
  stream + `fills_deadlettered_total`; transient → left pending for replay (dedup-safe) with a
  bounded retry. (`apps/orders/fills.py`, `apps/brokers/metrics.py`.)
- **P0-3 · Impersonation webhook-secret leak** — a read-only impersonation `GET` could mint a
  `WebhookConfig` (a write) and reveal the target's webhook `sig` (an order-placement bearer
  credential), burning the owner's reveal-once. Read-only impersonation now creates nothing and
  never reveals a secret. (`apps/strategies/{services,views}.py`.)
- **P0-4 · One-click Flatten-all** — the "Flatten all positions" market liquidation fired on a
  single click. Now routed through the shared focus-trapping modal with consequence copy + a
  typed `FLATTEN` confirmation, and gated on staff capability. (`features/settings/brokers/`.)

### Added — M11 (Hardening, Security, Load Test & Docs)
- **SERVICE_ROLE image entrypoint dispatch (§7.0, BUG-011)** — `docker/entrypoint.sh` (0755)
  dispatches on a **required** `SERVICE_ROLE` over seven roles (`web`, `web-dev`, `worker`,
  `worker-backtest`, `beat`, `streams`, `ws`); unset/unrecognised **exits non-zero, never
  falls back to `web`**. Compose drives all six backend-image services through it (no
  `command:` overrides; `ws` sets `PORT=8788`). New `entrypoint-dispatch` CI job (dry-run
  string-equality vs `docker/entrypoint.expected`, `SERVICE_ROLE=web` gunicorn boot, Day-6
  unset-crash drill). Railway cutover is the [LIVE] operator step (`docs/ops/service-role-cutover.md`).
- **Dependency audit gates (§7.2)** — `pip-audit` (backend, no severity threshold) + `pnpm audit
  --audit-level=high` (frontend) in CI; bumped DRF 3.15.2 / simplejwt 5.5.1 / daphne 4.2.2 /
  @angular 19.2.25; waivers + 13-PR Dependabot triage in `docs/security/dependency-waivers.md`.
- **GDPR export/delete + Terms (§7.7/§7.8)** — `GET /users/me/export/` (async ZIP to
  S3-compatible storage, creds/MFA redacted, 24h signed URL); 30-day soft delete
  (`/users/me/delete/` + `/cancel/`) with nightly anonymize-in-place; `GET /terms/current/` +
  `POST /terms/accept/` + blocking re-acceptance modal + `seed_terms`. Migration `users.0005`.
- **Security headers + log scrubber (§7.1)** — CSP report-only + Permissions-Policy
  (`SecurityHeadersMiddleware`); the M10-dangling sensitive-key log scrubber is now wired into
  `settings.LOGGING`; OWASP pentest regression tests (webhook static-`sig` model, cross-user
  BOLA/IDOR).
- **SLO burn-rate alerts (§13)** — multi-window multi-burn-rate error-budget alerts on the
  99.9% availability SLO; export/delete/terms metrics.
- **Load / chaos / backup harness (§7.4–7.6)**, **a11y axe-core gate + bundle budget (§7.10/7.11)**,
  **secret-rotation rehearsals (§7.12)**, ASVS L2 evidence + pentest report + ADRs 103–106,
  runbook `Last reviewed:` sweep, legal ToS/Privacy drafts.

### Added — M10.5 (App Shell, Navigation, Operability & Review Remediation)
- **App shell** — one `ShellComponent` (`features/shared/shell/`) wraps every authenticated route: `role="banner"` header with the wordmark, role-aware primary nav (dashboard/strategies/backtest/risk/orders/settings + staff-only admin), a user menu with **Sign out** (the first logout anywhere in the app), the impersonation-banner slot, a skip-to-content link, a mobile drawer, and the global toast host. Route restructure (`app.routes.ts`): public landing + auth pages OUTSIDE the shell; all features as children of one `authGuard`-guarded shell parent (feature `*.routes.ts` converted to child lists, `adminGuard` retained); `/` redirects authed users to `/dashboard` (`landingGuard`); a real **404 page** replaces the silent `** → ''`. Design in **ADR-043**.
- **Honest landing** — product explanation + webhook→risk→broker "how it works" strip + **Sign in / Create account** CTAs; environment badge driven by runtime config (never the hardcoded "Platform scaffold" string); paper-trading-only copy (F-13).
- **Onboarding** — `GET /api/v1/onboarding/status/` (read-only, owner-scoped, NOT MFA-gated) returns `{mfa_enrolled, broker_connected, strategy_ready, first_fill_seen, complete}`; a getting-started checklist renders as the dashboard empty state and a shell nav item that disappears when complete; each step deep-links to its screen.
- **Help** — `/help/:slug` viewer (sanitized first-party HTML, slug allow-list) + a `/help` index linking all 13 articles so none is orphaned; "?" affordances next to jargon; the Alpaca link points at `/help/alpaca-paper-connect`.
- **Shared UI kit** — `Button/Card/PageHeader/EmptyState/Spinner/Modal` (in-house focus trap, no CDK) + a signal-backed `ToastService` + `<app-toast-host>`; spacing/radius/shadow tokens wired into Tailwind.
- **RISK-5** — `apps/sentiment/management/commands/seed_tickers.py` (S&P-500 large-cap core + aliases) so market sentiment can produce non-zero output once real scorers are enabled.

### Fixed — M10.5 (security, risk truthfulness, frontend correctness)
- **C1** — auth rate-limit keyer parses the JSON body (the raw `HttpRequest` has no `.data`), so login/register/reset limit **per submitted email** instead of collapsing to one global `"anon"` bucket.
- **C2** — `config/settings/prod.py` re-reads `SECRET_KEY`/`FERNET_KEK` with **no default** (raises when unset) and rejects the insecure dev defaults + a default JWT signing key — fails the boot early.
- **C3** — `verify_mfa_code` throttles step-up brute force (N failures/window → pre-verification reject + `security.mfa_stepup_throttled` audit event).
- **SEC-4** — "revoke other sessions" / password-change no longer log you out of your **own** session (match `family_id`, not `current_jti`); the sessions "current" flag is fixed.
- **H8** — Django `/admin/` is mounted only under `DEBUG`; prod relies on `/api/v1/admin/`. **M1** — `/metrics` fails closed in prod (`METRICS_REQUIRE_AUTH`) when basic-auth creds are unset.
- **RISK-1/2/3/4** — soft-stop fires on real broker-equity intraday drawdown; `max_concurrent`/`leverage_cap`/`permitted_asset_classes` are enforced (reject codes + tests); `compute_size` clamps `qty = min(computed, requested_qty)` and `GET /risk/profile` no longer auto-creates a profile; the bear+long+negative-sentiment factor is **×0.5** (OQ-1 ruling; code + spec + pseudocode agree). Migration `audit.0004` (new audit choice).
- **C-FE-1..4** — refresh interceptor skips all unauthenticated auth endpoints (a wrong-password 401 no longer logs out / double-submits); `MissingTranslationHandler` + `auth.login.error.UNKNOWN` (no raw keys on screen); error interceptor preserves the `HttpErrorResponse` prototype; shared dashboard WebSocket is reference-counted and torn down on sign-out.
- **Swallowed errors** — 10 silent-failure sites (security actions, webhook rotation, stop-impersonation, password-reset, resend-verification, orders 30-day date default, admin KPI panel) now surface via toasts / inline `role="alert"`.
- **Accessibility** — labels, modal focus traps + Escape + restore, keyboard-operable table rows, text alternatives for the regime band + backtest canvas on touched screens.

### Added — M10 (Admin Portal, Audit Log & Observability)
- **Hash-chained audit log** — new `apps/audit`: an append-only, hash-chained `AuditLog` (`self_hash = sha256(prev_hash_ascii ‖ canonical_payload)`, genesis prev_hash = 64 zeros; canonical = JSON sorted-keys + compact separators over a fixed field set, `id` excluded) with **one** canonical hashing impl (`apps/audit/hashing.py`) and a single explicit write path `services.emit()` (never raises into the caller — audit failure increments `audit_events_dropped_total`, business action survives). `occurred_at` uses `default=timezone.now` (NOT `auto_now_add`) so the data migration can carry historical timestamps. **Postgres triggers** (migration `audit.0002`, vendor-guarded → no-op on SQLite) enforce append-only (UPDATE/DELETE always `RAISE`, every role incl. owner) + linkage (INSERT `prev_hash` must match head); `pg_advisory_xact_lock(hashtext('audit_log'))` serializes the chain head in app code **and** in the trigger. High-volume events (webhook-received, per-alert sizing decisions) are **excluded** from the chain (they stay in `AlertMessage`/`SizingDecision`) — documented deviation from master §6.11. Design in **ADR-100**.
- **Nightly integrity verifier** — `apps/audit/verifier.py` + beat task `apps.audit.tasks.verify_audit_integrity` (08:00 UTC ≈ 04:00 ET) resumes from a cursor (`AuditVerifierState`), recomputes hashes + linkage, asserts both triggers exist, and on failure writes an `audit.integrity_failure` row + emails `AUDIT_ALERT_EMAIL` + increments `audit_integrity_check_total{result="fail"}`. Retention 7y (master §17); partition threshold ≥50M rows or ≥10GB. Runbooks `audit-integrity-failure.md` + `audit-integrity-verify-monthly.md`.
- **Admin portal** — `is_staff` = admin identity; `/api/v1/admin/*` gated by `IsAdminAndMFAEnforced` (staff + MFA-enrolled, rejects impersonation tokens) + env-only `ADMIN_PORTAL_ENABLED` (off → 503 `ADMIN_PORTAL_DISABLED`). Users list/detail, disable/enable (MFA + reason; **does NOT auto-flatten** — response says so), audit search + `export.csv` (formula-injection guarded), platform status, health aggregation. Platform kill switch delegates to `apps/risk/killswitch.trigger_halt/release_halt` at **L3** — **L3 blocks new order intake and does NOT flatten** (ADR-081); engage requires typed `HALT PLATFORM` (server-validated, 400 `CONFIRM_PHRASE_MISMATCH`) + fresh `mfa_code`. Runbook `platform-halt.md`.
- **Read-only impersonation** — `ImpersonationAwareJWTAuthentication` (in `DEFAULT_AUTHENTICATION_CLASSES`) blocks non-SAFE methods (`IMPERSONATION_READONLY`), revokes on session stop (immediate via `ended_at`), 15-min TTL (`IMPERSONATION_TTL_MINUTES`), and audits every impersonated read (`admin.impersonated_read`). `ImpersonationSession` model + start/stop endpoints; `admin_impersonation_sessions_total`.
- **Feature flags** — DB-backed `FeatureFlag` (`apps/admin_portal`) + Redis (60s) + 30s process-local cache, falling back to env-parsed `settings.<NAME>`. `flags.is_enabled()` caches **only** the DB-override state and resolves the no-override case from live settings (env/override changes never masked); `set_flag()` writes DB + Redis + busts local cache + audits `flag.flipped` + `feature_flag_flips_total{flag}`. Registry `settings.FEATURE_FLAGS_REGISTRY` — 18 flags + `ADMIN_PORTAL_ENABLED`; immutable/env-only (`MFA_ENABLED`, `KILL_SWITCHES_ENABLED`, `FILLS_INLINE`, `ADMIN_PORTAL_ENABLED`), dangerous/typed-confirm (`ENABLE_LIVE_TRADING`, `SENTIMENT_FAKE_SCORERS`, `SIZING_V1_ENABLED`); fail-open to env default. Design in **ADR-101** (also: why not `apps/core`).
- **Observability topology** — `/metrics` now served **outside** Django's urlconf (`config/metrics_endpoint.py`, multiprocess-aware, basic auth via `METRICS_BASIC_AUTH_USERNAME/PASSWORD`), wired into `config/wsgi.py` (scraped gunicorn prod entry) + mirrored in `config/asgi.py`. FIX-C1: worker/beat/streams expose `/metrics` on `TASK_METRICS_PORT` (worker 9101, worker-backtest 9102, beat 9103, streams 9104; workers `--concurrency=1` for a 1:1 port map), via `worker_process_init`+`beat_init` signals (`config/celery.py`). postgres/redis exporters added to `docker-compose.yml`; `infra/grafana-agent/agent.yaml` gained basic_auth + env-var scrape targets (`WORKER_TARGET`… = Railway internal DNS). OTel init (`config/otel.py`; Django/Celery/redis/psycopg2/httpx; OTLP export only when `OTEL_EXPORTER_OTLP_ENDPOINT` set) from wsgi+asgi+worker. Request-id (ULID) correlation: `RequestIdMiddleware` + `request_context.py` contextvar/log-filter + Celery header propagation + Sentry `request_id`/`trace_id` tags. Design in **ADR-102**.
- **Alerts-as-code** — `infra/grafana/alerts/{alert-rules,contact-points,notification-policy}.yaml` (13 rules across trading-ops/risk-and-queues/platform-and-audit/backtest-ops; critical → email + Telegram, warning → email); a pytest (`config/test_alert_rules.py`) cross-checks every referenced series against the exported metric names, so a renamed/removed metric fails CI.
- **New metrics** — `audit_events_total{family}`, `audit_events_dropped_total`, `audit_integrity_check_total{result}`, `audit_verifier_duration_seconds`, `admin_impersonation_sessions_total`, `feature_flag_flips_total{flag}`, `celery_queue_depth{queue}`, `sentiment_queue_oldest_age_minutes`.
- **Docs** — ADR-100/101/102; runbooks `incident-triage.md`, `audit-integrity-failure.md`, `platform-halt.md`, `alerting-setup.md`, `audit-integrity-verify-monthly.md`, and `worker-metrics-scrape.md` promoted from options → implemented; `docs/oncall.md`, `docs/postmortem-template.md`, `docs/slo.md` (webhook availability ≥99.9%; order-submit p95 ≤1.5s; dashboard API p95 ≤300ms; kill-switch flatten p99 ≤5s).
- **Deferred (operator)** — importing the six dashboards + `infra/grafana/alerts/*.yaml` to Grafana Cloud, the Telegram/Tempo/Sentry-correlation wiring, and provisioning the Railway task-metric ports + postgres/redis exporter services (procedures in the runbooks); the AC-10-9 sample-alert firing test + AC-10-10 Sentry→Tempo click-through.

### Changed — M10
- **`/metrics` moved out of Django's urlconf** to `config/metrics_endpoint.py` (served at the WSGI entry in the same gunicorn process so the multiprocess mmap files are readable, and the scrape bypasses the middleware chain). The `django_prometheus.urls` include was removed from `config/urls.py`; its middlewares + DB-engine wrappers stay (they produce the series). Sentry `release=GIT_SHA`.

### Removed — M10
- **`AuthEvent` table dropped** — its 26-value `EventType` enum was relocated to `apps/audit/events.AuthEventType` (values byte-identical), every historical row migrated into the hash chain as `auth.*` rows (data migration `audit.0003`, self-verifying), then the table dropped (`users.0004_drop_auth_event`).
- **Sentry `_sentry_before_send` `/metrics` mitigation deleted** (`config/settings/prod.py`) — the WSGI revert + moving `/metrics` out of the urlconf remove the allauth/ASGI interaction it filtered.
- **`structlog` dependency dropped** from `requirements/` — it was pinned in M00 but never wired (the scrubber uses the `python-json-logger` LOGGING config); removed as a dead dependency.

### Added — M09 (Walk-Forward Backtester)
- **Two-stage walk-forward engine** — a **vectorbt OSS 1.0.0** parameter sweep (behind a swappable `SweepEngine` seam, unit sizing, cost-aware ranking, ≤ 100-combo chunking) feeds a **custom in-repo replay engine** (`replay_engine.py`) for path-dependent execution: next-bar-open fills, bps slippage (default 5 bp, floor 1 bp), intra-bar stops/targets with a conservative same-bar **stop-first** rule + gap-through fills, volume-participation partial fills (default 10%, re-attempted ≤ 5 bars then cancelled), per-order + per-share commissions (Alpaca-style $0 default), per-trade MFE/MAE, long-only MVP, force-close at each segment's final bar. backtrader dropped (GPLv3 + dormant); rationale in **ADR-090**.
- **Walk-forward orchestrator** (`wf.py`) — rolling/anchored windows, all intervals **half-open `[start, end)`**, MVP `step_days == test_window_days`, OOS segments concatenated by **compounding per-segment daily returns** (each segment replays from `initial_cash`; equity does not carry across windows). Window math + the golden worked example + replay/determinism semantics in **ADR-091**.
- **Production-sizing parity** — with `sizing_mode="production"` the replay sizes each entry through the same `apps.risk.sizing.compute_size` as `process_alert` (AC-09-12), replicating `apps.risk.integration._atr14` **exactly** (simple 15-bar mean, not Wilder). Documented divergences (profile-less users sized with default-profile values via `get_or_create`; `stop_distance` populated from adapter stops) in ADR-091 + the UI help.
- **Strategy adapters** — an in-repo `BacktestStrategy` Protocol + `@register` registry (`slug → adapter`; lookup miss → 400 `BACKTEST_NO_ADAPTER`), declared `warmup_bars` prefetched by the loader so window boundaries carry no NaN/look-ahead. **Repo-owned code only** — uploaded/community strategies without a registered adapter can't be backtested (no arbitrary code execution); the M03 `load_strategies` path never ingests adapter code. Security stance in **ADR-092**. Ships the seeded `sma-cross-demo` system strategy + idempotent `manage.py seed_demo_strategy`.
- **PBO / CSCV** (`pbo.py`) — Probability of Backtest Overfitting per Bailey et al. (2015), 16 contiguous blocks, vectorized over all 12 870 partitions, computed per symbol from one dedicated full-range sweep; `null` when N < 10 or T < 2S; tearsheet warning badge when PBO > 0.5.
- **Tearsheet** — canonical hashable **JSON** (sorted keys, floats 1e-9; `metrics_hash` = SHA-256, verified identical JIT vs non-JIT), single-file offline **HTML** (Plotly inline, no CDN/kaleido), and **PDF** (WeasyPrint from matplotlib SVG — selectable text) with equity/drawdown/monthly-heatmap/per-window charts, full AC-09-6 metrics, per-window Sharpe stability, and a **non-removable past-performance disclaimer** + PBO badge (server-side locale dict, `en`).
- **Bars→DataFrame loader** (`data.py`) — reads the local `marketdata.Bar` store only (no live vendor calls), half-open slicing, warm-up prefetch, and a **95%-of-weekdays** coverage gate → `BACKTEST_INSUFFICIENT_DATA` (names the largest gaps) when data is thin.
- **API** — `POST/GET /api/v1/backtest/runs/`, run detail (+ segments + progress), `POST …/cancel/` (cooperative, ≤ 30 s), and authenticated `report.json`/`report.html`/`report.pdf` streams; JWT + MFA; owner-scoped. Server-side caps at POST (≤ 2 concurrent → 409, grid ≤ 500, windows 2–60, ≤ 10 symbols, ≤ 15 y, `tf="1d"`, `step==test`, slippage floor 1 bp). Error codes `BACKTEST_NO_ADAPTER`, `BACKTEST_INSUFFICIENT_DATA`, `BACKTEST_LIMIT_CONCURRENT`, `BACKTEST_GRID_TOO_LARGE`, `BACKTEST_REPORT_TOO_LARGE`, `BACKTEST_TIME_CAP`, `BACKTEST_DISABLED`.
- **Celery orchestration** — `run_backtest` routed to a **dedicated `backtest` queue** via an explicit per-task route (first `CELERY_TASK_ROUTES` in the repo — NOT a glob) + a new `worker-backtest` compose service (`--concurrency=1 --max-memory-per-child=2000000`); `soft_time_limit=1500`/`time_limit=1800`. Progress streams over the existing `/ws/dashboard/` socket (`backtest.progress/completed/failed/cancelled`). Nightly `backtest-evict-artifacts` beat (03:30 UTC) nulls artifacts past retention (rows + `run.summary` + segments survive) and runs on the **default `celery` queue** so retention works even when the backtest worker is scaled to zero. **Railway `worker-backtest` is an operator step — until it exists, prod runs sit QUEUED** (runbook).
- **Frontend** — `/backtest` launcher (strategy picker with adapter gating, symbols, date range, train/test/step, mode/metric/cash/costs, retention, sizing toggle "Production sizing (regime/sentiment neutralized)" | "Fixed qty 1", textarea param-grid editor with live JSON validation) + runs list; `/backtest/:id` detail with live progress, chart.js tabs (equity/drawdown/monthly/per-window), metrics + segments tables, JSON/HTML/PDF downloads, and rerun.
- **Observability** — `backtest_runs_total{status}`, `backtest_run_duration_seconds` (buckets → 1800 s), `backtest_active_runs`, `backtest_failed_total{reason}`, `backtest_artifact_bytes`, `backtest_queue_wait_seconds`; **Backtest Ops** Grafana dashboard (`infra/grafana/backtest-ops-dashboard.json`) with the three alert rules documented (queue-wait p95 > 10 min; run hits the hard time cap; failed-rate > 20%/1h) — live wiring is M10.
- **Deps** — `vectorbt==1.0.0` (fair-code: Apache-2.0 + Commons Clause — not AGPL), `weasyprint>=68,<69`, `matplotlib>=3.8,<4.0`, `plotly>=5.18,<6.0` (matplotlib/plotly arrive transitively with vectorbt but pinned explicitly); resolved tree on py3.12 incl. numpy 2.1.3 / pandas 2.2.3 / numba 0.66.0 (ADR-090). `NUMBA_DISABLE_JIT=1` for tests. **Flag** `BACKTEST_ENABLED` (default True; off → UI nav hidden + endpoints 503 `BACKTEST_DISABLED`). **Migration** `backtest.0001_initial` (`BacktestRun`/`BacktestSegment`/`BacktestReport`, SQLite-compatible).
- **Docs** — ADR-090 (vectorbt + custom replay), ADR-091 (walk-forward protocol), ADR-092 (strategy adapter contract); runbook `docs/runbooks/backtest-stuck.md`; help articles "Running your first backtest", "Reading the tearsheet", "Interpreting PBO".
- **Deferred (operator)** — the staging performance SLA (3y ≤ 10 min / 10y ≤ 30 min / worker RSS ≤ 2 GB) and the Railway `worker-backtest` service (procedures in the runbook); the Backtest Ops dashboard "live on staging" + alert wiring (M10).

### Fixed — M04–M08 adversarial-review remediation (`fix/m04-m08-review-remediation`)
Every item ships with a regression test that fails before / passes after.

**Blocker**
- **FIX-B1** — the L2 daily-loss kill switch computed *lifetime unrealized P&L* over all open positions against *gross notional*, so a swing loser tripped L2 every day (and auto-released + re-tripped → permanent lockout), a day-trader who realized losses never tripped, and the pct breach was measured against position notional. Now uses **broker-truth daily P&L** — `Σ(equity − last_equity)` across the user's connected accounts against equity — and **fails safe**: a broker-read gap skips the poll (never auto-halts/releases). Gated to market hours.

**High**
- **FIX-H1** — position sizing used `buying_power` (2–4× levered) as equity → 2–4× oversizing. Added `equity`/`last_equity` to the `Account` DTO; sizing uses `equity`.
- **FIX-H2** — sizing equity fallback was a hardcoded $100k (fail-open). Now **fails closed** → `SIZING_NO_EQUITY` reject; `RISK_DEFAULT_EQUITY` deleted.
- **FIX-H3** — sizing fabricated a $100 price for MKT orders. Now resolves price hint → broker quote → last daily bar, else rejects `SIZING_NO_PRICE`.
- **FIX-H4** — a STRATEGY-scope kill switch with `flatten=true` liquidated the *entire* account (positions carry no `strategy_id`). Rejected at the serializer (`FLATTEN_SCOPE_UNSUPPORTED`); the L0 block still stops new orders. TODO(M09).
- **FIX-H5** — options `BUY_TO_OPEN`/`BUY_TO_CLOSE` fills decremented the position (`side == Order.Side.BUY` was false). Buy-side is now a set membership test.
- **FIX-H6** — a non-ASCII webhook `sig` crashed the public endpoint with a 500 (`hmac.compare_digest` on `str`). Both sides encoded → clean 401 + `SIG_BAD` audit.
- **FIX-H7** — no timeout on Alpaca HTTP calls, no Celery task time limits. Mounted a 10s timeout adapter on the Alpaca `requests` session; added `CELERY_TASK_SOFT_TIME_LIMIT`/`TIME_LIMIT` (30s/45s).
- **FIX-H8** — the stream supervisor masked dead threads (blanket-stamped CONNECTED), never hot-added accounts, and busy-looped on persistent failure (reset backoff before the blocking run). Threads own their heartbeat; the loop only diffs accounts (hot add/remove) + prunes dead threads; backoff resets only after a healthy run.
- **FIX-H9** — an alert naming an unconnected broker silently misrouted to the default. Now rejected `BROKER_NOT_CONNECTED`.
- **FIX-H10** — the daily feature/observation pipeline was an unconditional stub → regime permanently NEUTRAL. Implemented `compute_features_daily` (fetch → standardize → persist snapshot → observation), a genuine no-op only when keys are absent.

**Medium**
- **FIX-M1** — `timezone.utc` (removed in Django 5) made naive fill timestamps raise and drop the fill; use `datetime.timezone.utc`.
- **FIX-M2** — fill dedup `broker_exec_id` was globally unique; scoped to `(broker_account, broker_exec_id)` (migration `orders.0004`).
- **FIX-M3** — market sentiment was weighted by `TickerRegistry.id` (a PK, not a cap); equal-weighted now.
- **FIX-M4** — RSS fetch had no timeout and no User-Agent (hangs the beat; EDGAR blocks the default UA); fetch bytes via httpx with a bounded timeout + descriptive UA.
- **FIX-M5** — RSS `published_at` (RFC-822) never parsed → NULL dates; `email.utils.parsedate_to_datetime` fallback, tz-aware.
- **FIX-M6** — the Finnhub "RSS" source pointed feedparser at a JSON endpoint; removed from `build_fetchers()`.
- **FIX-M6-1** — FMP date-only bar timestamps were stored naive under `USE_TZ`; made aware (UTC).
- **FIX-M7** — common-word tickers (ALL/NOW/ON/…/T) tagged spuriously and cashtags bypassed the registry; expanded stopwords + registry-verify cashtags.
- **FIX-M8** — the L2 trading-day rollover used a fixed UTC-5 offset (wrong under EDT); computed via `America/New_York`.
- **FIX-M9** — the HMM swap guard compared holdout LLs from different windows; rescore the incumbent on the new holdout first.
- **FIX-M10** — FMP/FRED created (and leaked) a new `httpx.Client` per call; one reused client per instance.
- **FIX-M11** — FMP 200-with-non-JSON escaped the resilience layer; wrapped `resp.json()` → `FMPServerError` (cache-fallback).
- **FIX-M12** — FRED leaked `api_key` in transport-error URLs and had no resilience; re-raise `FREDError` from None + timeout + one retry.
- **FIX-M13** — missing macro/stress inputs failed OPEN toward RISK_ON; missing inputs neutralize (z=0) and mark the observation degraded.
- **FIX-M14** — releasing a kill switch required no MFA (only engaging did); MFA now required for USER/PLATFORM on both engage and release. (UI: the risk page prompts for MFA on release — follow-up.)
- **FIX-M15** — the 30s daily-loss watcher had no overlap guard and ran 24/7; single-flight cache lock + market-hours gate.
- **FIX-M16** — alert `qty:"NaN"/"Infinity"` and bad `option_expiry` stranded the alert / risked a 500; validated → clean `INVALID_QTY` / `ORDER_INVALID_OPTION` rejects.
- **FIX-C1** — task-side metrics were unscrapeable and four M04 metrics were never emitted. Emit `fills_ingested_total`, `broker_stream_heartbeat_age_seconds`, `order_state_transitions_total`, `broker_ws_reconnects_total` at their call sites; the streams process exposes a Prometheus port (`TASK_METRICS_PORT`); Gauges given explicit `multiprocess_mode`. Celery worker/beat scrape wiring documented as a follow-up.

**Low**
- **FIX-L1** — through-zero position flip kept the old basis; residual now takes the flip fill price.
- **FIX-L2** — kill-switch `target_id` (strategy) was not ownership-checked; validated in the serializer.
- **FIX-L3** — `SizingDecision.inputs` now records `equity` and `price`.
- **FIX-L4** — sentiment article list N+1; `prefetch_related("scores")`.
- **FIX-L5** — a non-ASCII broker API key → 500; serializer rejects non-ASCII → 400.
- **FIX-L6** — emit `SIZING_REJECT` (and `SOFT_STOP`) risk events (were enum-only).

### Added — M08 (Risk Engine, Position Sizing & Kill Switches)
- **Position sizing** — `apps/risk/sizing.py::compute_size` is a pure, deterministic function: regime scale (CRISIS=0/`REGIME_CRISIS`, BEAR=0.3, CHOP/NEUTRAL=0.6, BULL=1.0), strict-mode BEAR/CRISIS+LONG → `REGIME_SIDE_MISMATCH`, ATR-based stop (else 2%-of-price fallback), dollar-risk sizing, position-% clamp, sentiment adjustment (>0.7→×1.10, <-0.5→×0.70), soft-stop ×0.5, round-to-lot, `SIZING_ZERO`. Wired into `process_alert` **only when the user has a RiskProfile** (else raw alert qty — M04 behavior preserved), persisting a `SizingDecision` per path (AC-08-4).
- **Four-level kill switches on `brokers.TradingHalt`** (extended with `level` L0–L3 + `auto` + nullable `user` — a single kill-switch table, **no parallel model**): L0 strategy, L1 user-global, L2 daily-loss auto, L3 platform. `killswitch.is_blocked` (platform→user→strategy) is consulted at the webhook AND in `process_alert`; `trigger`/`release` use `SELECT FOR UPDATE`; L2 auto halts lock until the next trading day (UTC-05); flatten goes through the broker adapter's `flatten_all` with measured latency (AC-08-8 ≤5s local vs FakeBroker); daily-loss watcher (30s beat) trips L2 on a **two-poll-confirmed** breach off conservative cached marks.
- **RiskProfile** CRUD with validators (AC-08-2); sizing-decisions / events / kill-switches API; **L1/L3 kill-switch MFA re-prompt** (§11); platform switch admin-only.
- **Frontend** — `/risk` page (profile editor + kill-switch panel + events + sizing-decisions feeds) + a dashboard "Halt my trading" (L1) button (confirm + MFA) and a halt banner.
- **Observability** — `sizing_decisions_total`, `sizing_reject_reason_total`, `killswitch_trigger_total`, `killswitch_flatten_latency_seconds`, `daily_loss_breach_total`; **Risk Ops** Grafana dashboard.
- **Flags** `SIZING_V1_ENABLED`, `KILL_SWITCHES_ENABLED`. **Migrations** `brokers.0003` (TradingHalt levels), `risk.0001`.
- **Deferred** — the "flatten p99 ≤5s measured on staging" + "Risk Ops dashboard live on staging" (need a deployed env; latency measured locally + chaos drill documented); the Kelly damper (needs the M09 `TradeHistory`).

### Added — M07 (Sentiment Pipeline)
- **News ingestion** — `sentiment` app: FMP-news + RSS (EDGAR / Nasdaq-halts / Benzinga / Finnhub) fetchers via `feedparser` (injectable), dedup on `sha256(url+title)`, server-side HTML strip, material-flagging (8-K / halt / guidance).
- **Symbol tagger** — regex-against-`TickerRegistry` (high precision) + `$cashtags` + `AliasTable` (company→ticker); spaCy NER is a lazy flag-gated enhancement.
- **Tiered scoring** — a `SentimentScorer` abstraction: canned `FakeFinBert`/`FakeLlama` as the CI/default (deterministic, no weights), with real FinBERT (`transformers[torch]`) + Llama (`llama-cpp-python`, GGUF) imported **lazily behind `FINBERT_ENABLED`/`LLM_WORKER_ENABLED`**; versioned prompt (`prompts/v1.md`) with prompt-injection wrapping + JSON-schema validation (never eval'd). FinBERT scores all articles; Llama scores material / FinBERT-confidence<0.7 articles; **FinBERT-only graceful degradation** when the LLM worker is off (AC-07-10). No article text/model output is logged (AC-07-12).
- **Aggregation + API** — per-symbol EWMA (6h half-life) + market-wide score; `GET /api/v1/sentiment/{market,symbol/{sym},articles}/`; beat (ingest/score/aggregate). Backlog helper for the AC-07-9 alert.
- **Frontend** — market sentiment spark + "recent impactful news" feed + degraded chip on the dashboard.
- **Observability** — `news_articles_ingested_total`, `news_articles_deduped_total`, `sentiment_articles_scored_total`, `sentiment_queue_depth`, `llm_inference_latency_seconds`, `llm_invalid_responses_total`.
- **Deps** — `feedparser` only (base image); the heavy model stacks (transformers[torch] / llama-cpp-python / spaCy) live in `requirements/ml-worker.txt` (volume-mounted worker deps, NOT the base image → Trivy-lean). **Flags** `SENTIMENT_ENABLED`, `LLM_WORKER_ENABLED`, `FINBERT_ENABLED`, `SENTIMENT_FAKE_SCORERS`. **Migration** `sentiment.0001`.
- **Deferred (externals)** — FinBERT + gated Llama-3.1-8B GGUF weights (HF license), the Day-1 tokens/sec benchmark, and per-source ToS review.

### Added — M06 (Market Data + Regime Classifier)
- **Market-data plane** — `marketdata` app: `Bar`/`MacroSeries` store with idempotent upserts + gap detection; FMP client (token-bucket rate limit, tenacity retry on 429/5xx, circuit breaker, response cache with **cache-fallback so a rate-limit/outage never surfaces a 5xx** — AC-06-9); FRED client; `backfill_bars` management command. All live calls fixture-mocked (FMP/FRED keys are deferred externals).
- **Regime classifier stack** — feature pipeline (breadth/stress/credit/macro → z-scored vector + reproducibility content-hash, AC-06-10); weighted **rule classifier** (score 0–100 → RISK_ON/NEUTRAL/RISK_OFF/PANIC + top-3 reason codes); **Gaussian HMM** (`hmmlearn`, 4 states, seeded training with restarts, state→label ranking, JSON param serialization, online decode + Viterbi); **ensemble** decision table; orchestration persisting `RegimeObservation`; nightly `retrain_hmm` with a **non-regression swap guard** (activate only if holdout LL ≥ prior or within 1%); rule-only degradation when the model is >48h stale (AC-06-8).
- **Regime API** — `GET /api/v1/regime/{current,history,model}/`; `/symbol/{sym}/` → 501 (per-symbol later).
- **Frontend** — regime badge (color + label + top-features popover + "rule-based only" degraded chip) and a 90-day history strip on the dashboard.
- **Observability** — `marketdata_requests_total`, `marketdata_ratelimit_waits_total`, `marketdata_bars_ingested_total`, `regime_compute_latency_seconds`, `regime_model_age_seconds`, `hmm_retrain_total`; **Data Pipelines** Grafana dashboard.
- **Deps** — numpy/pandas/hmmlearn/tenacity. **Flag** `ENABLE_REGIME_UI`. **Beat** nightly HMM retrain. Bar Postgres month-partitioning deferred (documented in ADR-061 — plain indexed table at MVP scale).
- **Migrations** — `marketdata.0001` (Bar, MacroSeries), `regime.0001` (FeatureVectorSnapshot, HMMModel, RegimeObservation).

### Added — M05 (Order Lifecycle + TradeStation, descoped)
- **Extended order types** — MKT/LMT/STP/STP_LMT + TIF DAY/GTC/IOC across the unified `OrderRequest`; asset classes STOCK/ETF/OPTION/FUTURE with option (OCC symbol) + future descriptors on `Order`. `process_alert` parses them; futures are rejected on Alpaca (`ORDER_UNSUPPORTED_ASSET`), options route by OCC symbol.
- **Broker routing** — an alert may set `"broker"` to override the user's default; falls back to default/oldest.
- **Reconciliation** — `apps/orders/reconcile.py` + `ReconEvent` + 5-min beat: drift detected against broker `list_positions()`, healed toward broker truth on the second consecutive cycle (never places corrective orders); `GET /api/v1/reconciliation/events/`.
- **Orders page API** — server pagination + broker/strategy/status/date filters, order detail (order + fills), `GET /api/v1/orders/export.csv`.
- **Live-mode gate** — `POST /api/v1/brokers/{id}/mode/` rejects `LIVE` with `LIVE_TRADING_DISABLED` (403) until the global flag + per-user opt-in are on; server-enforced.
- **TradeStation adapter (behind `BROKER_TRADESTATION_ENABLED=false`)** — `TradeStationPaperAdapter` + thin `httpx` client (REST + transparent OAuth2 refresh on 401), symbology (options OCC→TS space format, futures ES→`ESZ26`), OAuth2 authorization_code + PKCE with single-use signed `state`; `oauth/start` + `oauth/callback` views. **Live OAuth + real sim fills are deferred** (TradeStation API access is approval-gated).
- **Frontend** — `/orders` page (paginated table, filters, detail drawer with lifecycle + fills, CSV export, reconciliation events); broker mode control (LIVE disabled) + Connect TradeStation on `/settings/brokers`.
- **Observability** — `reconcile_drifts_total`, `reconcile_heals_total`, `oauth_refresh_total`, `order_state_transitions_total`, `broker_ws_reconnects_total`.
- **Migrations** — `brokers.0002` (TradeStation + LIVE mode + OAuth token fields), `orders.0003` (extended order types + asset descriptors + `ReconEvent`).

### Added — M04 (Webhook Ingest + Broker Adapter + Alpaca Paper)
- **Public webhook ingest** — `POST /hooks/v1/{user}/{strategy}/` (mounted outside `/api/v1`, no JWT layer). Per-user rate limit before body read, 16 KB body cap, `application/json`-only, constant-time static-bearer `sig` compare (ADR-042), JSON-Schema validation, 24h `SETNX` idempotency, and a `TradingHalt` gate. `AlertMessage` is the ingest audit row (`sig` stripped before persistence). `process_alert` Celery task maps the alert → `OrderRequest` and places it.
- **Broker adapter layer** — broker-neutral `BrokerAdapter` protocol + DTOs, `FakeBrokerAdapter` (scripted fills/partials/rejects for tests), and `AlpacaAdapter` (paper-only: `TradingClient(paper=True)` hard-coded, live keys `AK`/`BK` rejected with `BROKER_LIVE_KEYS_FORBIDDEN`, 429/5xx retry-with-jitter, idempotent submit-retry guard, per-call `BrokerCallAudit` with no bodies/keys). `alpaca-py>=0.43,<0.44`.
- **Per-user broker connections** — `BrokerAccount` with Fernet-encrypted key pair (shared platform KEK), write-only serializers, connect/test-connection/status/flatten/remove (MFA re-prompt on removal via `mfa.verify_mfa_code`).
- **Orders/fills/positions** — `Order`/`Fill`/`Position` models; `ingest_fill_event` (idempotent on `broker_exec_id`) with weighted-average position math; Redis-Stream fill transport (`fills:user:{id}`) + `FillIngestor` consumer, with an inline mode for tests; `run_broker_streams` supervisor (thread-per-account, heartbeat, supervised reconnect + REST catch-up); list APIs for orders/positions/fills.
- **Realtime dashboard** — Django Channels consumer `/ws/dashboard/` (JWT-in-query + MFA), per-user group fan-out of `order.*`/`fill.created`/`position.updated`/`broker.status`; ASGI `ProtocolTypeRouter` + `daphne`/`channels-redis`; docker-compose `streams` + `ws` services.
- **Frontend** — `/settings/brokers` (connect Alpaca paper, test connection, status badges, MFA-gated removal) and a realtime `/dashboard` (open positions, today's fills, broker status) with a backoff/heartbeat websocket client.
- **Observability** — Prometheus `webhook_received_total`, `webhook_latency_seconds`, `order_submit_latency_seconds`, `broker_connect_total`, `broker_stream_disconnects_total`, `fills_ingested_total`, `broker_stream_heartbeat_age_seconds`.
- **Feature flags** — `WEBHOOK_V1_ENABLED`, `BROKER_ALPACA_ENABLED`, `ENABLE_LIVE_TRADING` (paper-only hard default), `FILLS_INLINE`.
- **Celery app wiring** — `config/__init__.py` now imports the Celery app (was missing since M00), so `@shared_task.delay()` resolves to the configured app (`task_always_eager` in tests).

### Fixed — pivot hygiene (Alpaca over IBKR, ADR-041)
- Scrubbed the legacy IBKR gateway credentials (TWS user/password + the VNC debug flag) from `backend/.env.example`; moved the `ib-gateway` compose service behind the opt-in `ibkr` profile (not booted by `make up`); added a CI `block-legacy-ibkr-creds` grep gate; removed stray `gateway-*.png` + `_tmp_14_*` files.

### Changed — Plan (M00 AC renegotiations)
- **M00 AC-00-8 renegotiated** to drop the `process_resident_memory_bytes` requirement that conflicted with M01.11.13's switch to multi-process gunicorn Prometheus aggregation. The standard `prometheus_client` `process_*` collector is incompatible with the multi-process aggregator and is auto-removed when `PROMETHEUS_MULTIPROC_DIR` is set. Updated criterion accepts `django_http_requests_total_by_view_transport_method_total` as the request counter, with the process-level metric explicitly deferred to M10 §6.5 (Railway container metrics or postgres/redis exporters). See `reference_strattraderpro_metrics_gotchas` memory note for the underlying reason. Edit landed in `project-plan/00-scoping-and-setup.md`.
- **M00 AC-00-1 renegotiated** to "rule configured, not actively enforced." Active enforcement of branch protection rules requires a GitHub Team/Enterprise organization plan; the StratTraderPro repository is a personal-private repo on the free tier where the rule saves but the platform does not block any pushes against it. The branch protection rule on `main` (require PR, require Backend+Frontend+Trivy+E2E status checks, require linear history, require branches up to date, no force-push, no deletions, 0 required approvals so solo dev can self-merge after CI green) was configured 2026-05-08 at `github.com/yhaspel/StratTraderPro/settings/branches` and will activate automatically if the repo upgrades or goes public. Both renegotiations will be documented in the `v0.0.0-scaffold` tag annotation.

### Fixed — Sentry quota burn from /metrics AttributeError
- **`backend/config/settings/prod.py`** — added `_sentry_before_send` filter wired into `sentry_sdk.init(..., before_send=...)` to drop a known-noisy `AttributeError: 'coroutine' object has no attribute 'headers'` that fires on every `/metrics` scrape. Root cause is a 3-way interaction: gunicorn UvicornWorker → ASGI app → `sentry_sdk`'s `SentryASGIMixin` wraps the app → the response object reaching `allauth.account.middleware.AccountMiddleware._should_check_dangling_login` (allauth/account/middleware.py:40) is the unawaited coroutine instead of an `HttpResponse`. The `/metrics` endpoint actually succeeds (grafana-agent successfully scrapes — `up{job="backend"}=1`), but the exception fires in post-response middleware and would burn ~240 Sentry events/hour against the 5,000/month free-tier quota (~21 hours to exhaustion). Filter is conservative — only this exact exception on `/metrics` transactions is dropped; real bugs anywhere else still surface. Long-term fix tracked as M10 §6.5 follow-up: mount `/metrics` outside Django via `prometheus_client.exposition.make_asgi_app()` to bypass the entire middleware chain. Discovered via the M00.9.4 Sentry rollout — first hour of capture surfaced 277 events of this exact issue, hence the urgency.

### Fixed — staging crash recovery (M00.7.5b deploy regression)
- **`backend/config/settings/{dev,prod}.py`** — explicit `from .base import _wrap_db_engines_for_prometheus  # noqa: F401` after the existing star-import. Python's `from .base import *` does NOT pull in names starting with underscore, so the prior commit's `_wrap_db_engines_for_prometheus(...)` call site referenced an undefined name → `NameError` at module load → Django couldn't start → staging backend, celery-worker, celery-beat all crashed for ~15 min on 2026-05-07. Test gap that allowed it to ship: `test.py` uses sqlite directly without calling the helper, so pytest never imports `prod.py`. Lesson saved to `feedback_settings_star_import_private` memory note. Future settings changes should add a `python -c "import django; django.setup()"` smoke check against `DJANGO_SETTINGS_MODULE=config.settings.prod` before claiming deploy-ready.
- **`frontend/package.json`** — pinned `"packageManager": "pnpm@10.33.4"` (was unset, so corepack auto-resolved to pnpm 11.0.8 which requires Node 22 and fails on Node 20 with `ERR_UNKNOWN_BUILTIN_MODULE: node:sqlite`). Closes the Frontend CI lint/test failure and the frontend Docker build failure during deploy.

### Added — M00.7.5b (System Health dashboard)
- **`infra/grafana/system-health-dashboard.json`** — 15-panel Grafana Cloud dashboard, sibling to the M01 Auth Health board. Six rows: Backend Health (`up`, request rate by status class, p50/p95/p99 latency, 5xx rate %), Application Activity (top 10 routes by request rate, top 10 by p95 latency, 4xx responses by view), Django DB (ORM-side query duration percentiles + new connections/sec), and three placeholder rows — Postgres/Redis/Celery exporter follow-up (text-only explainer panel; exporters are M10 §6.5 work), M04 Webhook Ingest (HMAC failure rate / idempotency dedupe rate / ingest p95 latency, "No data" until M04 wires `webhook_ingest_total` and `webhook_ingest_latency_seconds`), M04 Broker Round-trip (order placement p95 by broker / `broker_connection_up`, "No data" until M04 broker adapters land). Multi-select `env` variable defaults to All so cross-env regressions stand out at a glance. UID `stp-system-health`, schemaVersion 39, panels-only (no alert rules in v1 — pinning thresholds deferred until a week of baseline data is collected). **Container CPU/memory deliberately omitted:** multi-process gunicorn (M01.11.13) disables prometheus_client's `process_*` collector, and Railway container metrics aren't scraped yet (M10 §6.5 work). Application Activity row replaces the abandoned Process Resources row from the v0 draft.
- **`setup-guides/grafana-setup.md` §7** — import procedure, variable reference, verification checklist for closing M00.7.5b, and explicit "what's deferred" note covering alert rules and the Trading Ops / Data Pipelines / Backtest Ops dashboards still owned by M10 AC-10-8.

### Changed — backend Django DB engine wrappers for /metrics
- **`backend/config/settings/base.py`** — added `_wrap_db_engines_for_prometheus()` helper that maps stock Django engines (`django.db.backends.postgresql`, `.sqlite3`, `.mysql`) to their `django_prometheus.db.backends.*` wrapper subclasses. Wrappers are transparent drop-ins (same DSN handling, same query behavior) but **emit two extra metrics**: `django_db_query_duration_seconds_bucket{alias, vendor}` (histogram) and `django_db_new_connections_total{alias, vendor}` (counter). Without the wrapper these series are simply not emitted — the System Health Django DB row stays empty no matter how much traffic flows through the system.
- **`backend/config/settings/dev.py`** + **`prod.py`** — both call `_wrap_db_engines_for_prometheus()` after their `DATABASES = {…}` override so the wrapper applies on top of `env.db("DATABASE_URL")` resolution. `test.py` deliberately untouched (sqlite-only, query duration metrics are noise in test runs).
- Backend redeploy on staging + prod required for the System Health Django DB row to populate.

### Changed — M00.7.5 split
- Tracker entry M00.7.5 ("Grafana Cloud account + System Health dashboard") split into 00.7.5a (Grafana account — ✅ Done since M01.11.5) and 00.7.5b (System Health dashboard — was the actual unfinished work). Top-of-tracker reconciliation note updated.
- `v0.3.0-strategies` tag attribution corrected: it points to commit `a4e1e8f` (the M03-completion commit). Subsequent `a7f746c` is the tracker-update bookkeeping commit.

### Added — M03 (Strategies & Webhook Config)
- **`strategies` Django app** fleshed out from M02 ping-stub to a full domain. New models: `Strategy` (system + user-owned, soft-delete via `is_enabled`), `StrategyFile` (per-strategy bytes for `.pine` / description / webhook template, sha256 + filename + size + BYTEA content), `WebhookConfig` (per-user/per-strategy HMAC secret Fernet-encrypted at rest, JSON-Schema-validated payload template, version counter for rotation). Migration `strategies.0001_initial` is destructive on rollback (greenfield — no prod data yet).
- **Strict 3-file upload contract** for user uploads: `<stem>.pine` + `<stem>_Description.txt` + `<stem>_Webhook.json`. Validator enforces stem regex `[A-Za-z0-9_-]{3,64}`, size limits (64 KB / 16 KB / 16 KB), `//@version=` declaration in pine, required webhook keys (`strategy`, `action`, `symbol`, `qty`, `order_type`), path-traversal rejection (null bytes, `../`, separators), substring XSS scan as defense-in-depth (`<script`, `javascript:`, `onerror=`, `onload=`). All in `apps/strategies/validators.py`. ADR-030 captures the rationale.
- **Strategies API surface** (all MFA-gated via M02 `IsAuthenticatedAndMFAEnforced` + `mfa_required=True`):
  - `GET    /api/v1/strategies/`  — list (system + own).
  - `POST   /api/v1/strategies/`  — multipart upload + acknowledge checkbox.
  - `GET    /api/v1/strategies/{id}/`  — detail.
  - `PATCH  /api/v1/strategies/{id}/`  — rename / toggle enabled.
  - `DELETE /api/v1/strategies/{id}/` — soft delete (sets `is_enabled=false`). System strategies refuse with `STRATEGY_SYSTEM_IMMUTABLE`.
  - `GET    /api/v1/strategies/{id}/files/{kind}/`  — download a stored file's bytes.
  - `GET    /api/v1/strategies/{id}/webhook-config/`  — fetch URL + JSON Schema + payload template; on first call the row is created and the secret is revealed once.
  - `PUT    /api/v1/strategies/{id}/webhook-config/`  — update schema + template (server-validates schema is valid Draft 2020-12, template matches schema).
  - `POST   /api/v1/strategies/{id}/webhook-config/rotate/`  — generate new secret, increment version, reveal once. Old secret is destroyed.
  - `POST   /api/v1/strategies/{id}/webhook-config/dry-run/`  — validate a payload against the saved schema without firing an order.
- **HMAC secret rotation + reveal-once UX** documented in ADR-031. Same Fernet KEK as MFA (`settings.FERNET_KEK`) so KEK rotation covers both surfaces. Plaintext secrets never appear in logs (regression test pins this).
- **`load_strategies` management command** — `python manage.py load_strategies <path>` walks one level deep, idempotent via SHA-256, `--dry-run` flag. Adapts to the real Trading Strategies project layout: globs for any `*.pine` and `*description*.txt`, synthesizes a default webhook template when no `_Webhook.json` exists. Exit code is non-zero on partial failure so CI catches it. Runbook at `docs/runbooks/strategy-import-from-cowork.md`.
- **Frontend strategies feature area** at `/strategies`, `/strategies/upload`, `/strategies/:id`. Lazy-loaded via `STRATEGIES_ROUTES`. List view renders system + user-uploaded with a "User-uploaded" amber banner ("Community-tested: No"), inline enable/disable toggle, per-row "Configure webhook" + "Delete" actions. Upload component is a 3-step single-file wizard (select files → review → acknowledge & submit) with mandatory accept-untested-risk checkbox. Webhook configuration modal hosts URL + reveal-once secret + Rotate (with confirm) + JSON Schema editor + payload-template editor + Test (dry-run) + Copy TradingView template buttons. Monaco editor lazy-imported via dynamic import so the chunk only loads on modal open; textarea fallback keeps the editor accessible regardless.
- **Frontend abstraction layer**: `core/services/strategies.api.ts` (typed HTTP client), `abstraction/stores/strategies.store.ts` (signal-based, with reveal-once secret cache that wipes on modal close), `abstraction/facades/strategies.facade.ts` (load/upload/toggle/softDelete/webhook CRUD/rotate/dry-run).
- **i18n keys** under `strategies.*` and `webhook.*` in `assets/i18n/en.json`. Help pages: `assets/help/strategy-upload.html` ("Upload your first strategy") and `assets/help/tradingview-alert-config.html` ("Configure your TradingView alert").
- **Settings**: new `STRATEGIES_V1_ENABLED` feature flag (returns 503 from all strategies endpoints when False — no-deploy rollback per plan §15) and `STRATEGY_WEBHOOK_BASE_URL` for the public webhook hostname (defaults to `https://api.strattraderpro.com/hooks/v1`; the receiver itself goes live in M04).
- **Prometheus**: `strategy_uploads_total{result}` (3 outcomes), `strategy_webhook_rotations_total`, `strategy_count_gauge{type=system|user}`. Wired in `apps/strategies/metrics.py`.
- **New error codes** in the response envelope: `STRATEGY_NOT_FOUND`, `STRATEGY_NAME_TAKEN`, `STRATEGY_FILE_MISMATCH`, `STRATEGY_FILE_TOO_LARGE`, `STRATEGY_WEBHOOK_INVALID`, `STRATEGY_SYSTEM_IMMUTABLE`, `WEBHOOK_SCHEMA_INVALID`.
- **Admin**: `Strategy`, `StrategyFile`, `WebhookConfig` registered. System rows are read-only for non-staff (AC-03-10). `WebhookConfig` admin disables creation (configs are minted via the API only).
- **37 new backend tests** in `apps/strategies/test_strategies.py` covering AC-03-1 through AC-03-12 + validator branches (path traversal, oversize, bad JSON, missing keys, XSS), rotation+version increment, system immutability, multi-tenant isolation, fixture-based `load_strategies` integration test (incl. webhook synthesis when missing), feature-flag 503, and a regression test that the rotation log line never contains the freshly minted secret. Total backend pytest: **128 passing** (+37). One M02 sweep test in `test_mfa.py::test_all_protected_prefixes_have_mfa_gate` updated to hit the real `/strategies/` endpoint instead of the deleted `/strategies/ping/` stub.
- **Frontend test**: `strategies.store.spec.ts` covers signal-derived counts, upsert, remove, and the reveal-once secret cache wipe.
- **Dependencies**: `jsonschema>=4.21,<5.0` added to `requirements/base.txt` (Draft 2020-12 validator).
- **Docs**: ADR-030 (3-file upload contract), ADR-031 (HMAC rotation + reveal-once), runbook (strategy import).

### Added — M2.5 (Google OAuth sign-in / sign-up)
- **Google OAuth via django-allauth** with a custom JWT bridge — allauth handles only the OAuth state machine (authorize URL, code exchange, userinfo fetch, account linking), and we hijack at the post-callback step to issue our own one-time exchange code, then bridge through the M01 JWT family pipeline + M02 MFA gate. Three endpoints: `GET /api/v1/auth/oauth/google/start/` returns the authorize URL as JSON, `GET /api/v1/auth/oauth/google/callback/` is allauth's stock callback (registered in Google Cloud Console), `POST /api/v1/auth/oauth/exchange/` swaps the exchange code for `{access, refresh, user}` OR `{mfa_required, mfa_token}`. Bridge code in `apps/users/views_oauth.py` (~280 lines) and `apps/users/social_adapters.py` (~80 lines).
- **`OAuthExchangeCode` model** — single-use sha256-hashed code, 5-minute TTL (configurable via `OAUTH_EXCHANGE_TTL_MINUTES`), keeps the JWT pair off the redirect URL so it doesn't leak through referer headers / server logs / browser history. Migration `users.0003_oauth_exchange_code` adds the table.
- **MFA still required after Google sign-in** — Google proves email control, MFA proves second-factor ownership. Same `{mfa_required, mfa_token}` response as password login. Documented in ADR-021.
- **Auto-link by verified email** — when a Google sign-in arrives for an email that already has a User, `SocialAdapter.pre_social_login` calls `sociallogin.connect()` to attach the SocialAccount to the existing User. The user keeps their MFA, sessions, profile, and password. Only happens when Google asserts `email_verified=true`. Notification email (`oauth_account_linked.{txt,html}`) fires so a real user notices.
- **Auto-create User on first Google sign-in** — `SocialAdapter.populate_user` pulls `display_name` from Google's `name` claim (falls back to local-part of email) and sets `is_verified=True` (Google verified the email at the OAuth provider). Welcome email (`oauth_account_created.{txt,html}`) sent.
- **Frontend**: "Continue with Google" button on `/login` and `/register` (brand-compliant Google G logo SVG, white background per their guidelines), `/oauth/callback` route component handles the `?exchange=<code>` redirect from backend (or `?error=oauth_failed`), POSTs to exchange endpoint, routes to `/dashboard` or `/login/mfa` based on response. `auth.facade` gained `startGoogleSignIn()` + `completeGoogleSignIn(code)` methods. New i18n keys under `oauth.*`.
- **Sentry-aware Sentry environment** — derived from `RAILWAY_ENVIRONMENT_NAME` so OAuth errors group under the right env (staging vs production).
- **5 new audit-log event types**: `OAUTH_LOGIN_OK`, `OAUTH_USER_CREATED`, `OAUTH_LINKED`, `OAUTH_EXCHANGE_OK`, `OAUTH_EXCHANGE_FAIL`. New Prometheus counters: `auth_oauth_login_total{result}`, `auth_oauth_exchange_total{result}`.
- **24 new tests** in `apps/users/test_oauth.py` covering: OAuthExchangeCode model (issue, consume, single-use, expiry, replay rejection, inactive user); SocialAdapter logic (auto-link with verified email, refusal to link unverified, no-op on already-linked); OAuthExchangeView (happy path, MFA gate, invalid/expired/consumed code, audit events, feature-disabled 503); OAuthGoogleStartView (returns valid Google authorize URL with state token, refuses when disabled or unconfigured). Total backend pytest count: 90, all green.
- **`docs/adr/021-google-oauth-allauth.md`** — captures the choice rationale (allauth for state machine + custom bridge for everything else), full flow diagram, account-linking semantics, MFA interaction, why exchange-code instead of JWT in URL fragment.
- **`docs/runbooks/google-oauth-setup.md`** — reproducible GCP setup: OAuth consent screen wizard, OAuth Web client creation with the three required redirect URIs (localhost dev + staging + prod), saving credentials, adding test users while in Testing mode, publishing to In Production for unrestricted sign-up, env var configuration in Railway, smoke test, secret rotation procedure, failure modes.

### Settings (M2.5)
- New env vars: `GOOGLE_OAUTH_ENABLED` (master kill-switch — `false` returns 503 from all OAuth endpoints), `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (set in Railway env, never committed), `OAUTH_EXCHANGE_TTL_MINUTES` (defaults to 5).
- New `INSTALLED_APPS` entries: `django.contrib.sites`, `allauth`, `allauth.account`, `allauth.socialaccount`, `allauth.socialaccount.providers.google`. New middleware: `allauth.account.middleware.AccountMiddleware`. New auth backend: `allauth.account.auth_backends.AuthenticationBackend` (alongside our existing `ModelBackend`). `SITE_ID = 1`.
- Custom adapters wired via `SOCIALACCOUNT_ADAPTER` and `ACCOUNT_ADAPTER` to suppress allauth's parallel auth features (local signup form blocked via `is_open_for_signup=False` on `AccountAdapter`; email verification disabled via `ACCOUNT_EMAIL_VERIFICATION="none"` since we run our own).

### Manual setup follow-ups (Yuval)
- Google Cloud Console: existing `strattraderpro` project, OAuth consent screen configured, "StratTraderPro Web" OAuth 2.0 Web client created with 3 redirect URIs, `you@example.com` added as test user (1/100 cap). Client ID + Client Secret saved to password manager. App still in **Testing mode** — publish to Production after smoke-test (one click, no Google verification needed for our `email`+`profile` scopes).
- Railway: `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` need to be set in both staging and prod backend services.
- A duplicate empty `strattraderpro-495109` GCP project exists (created accidentally by me); Yuval to delete via GCP resource manager.

### Infrastructure — Production environment bootstrap
- **Production Railway environment** stood up alongside M02. Forked from staging via Railway's "Duplicate Environment" feature, giving us 7 fresh service instances (backend, frontend, celery-worker, celery-beat, Postgres, Redis, grafana-agent) with empty volumes and prod-unique URLs (`your-backend.example.com`, `your-frontend.example.com`). The pre-existing empty `production` env that auto-created with the project (untouched for 4 weeks) was renamed to `production-archive-2026-04` rather than deleted, kept as a safety net.
- **Prod-grade secrets generated locally** and set in Railway env: `SECRET_KEY` (64-byte url-safe-base64 from `secrets.token_urlsafe`) and `FERNET_KEK` (32-byte url-safe-base64 from `os.urandom`). Different values than staging — no key reuse between environments. KEK is a hard requirement for M02 MFA: without it, every TOTP secret would be wrapped with a SECRET_KEY-derived dev fallback. Now every MFA enrollment in prod is wrapped with the prod-only KEK.
- **URL-bound vars auto-resolved** because the staging env was set up with Railway service references (`${{RAILWAY_PUBLIC_DOMAIN}}`, `${{frontend.RAILWAY_PUBLIC_DOMAIN}}`, `${{Postgres.DATABASE_URL}}`, etc). The duplicate carried these references over verbatim and Railway re-resolved them against the prod-env service IDs — `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, `FRONTEND_BASE_URL`, and the frontend's `BACKEND_URL` were all correct on first deploy with zero edits. Yellow warning icons in the Variables panel are stale UX — the values resolve correctly to prod URLs.
- **Sentry environment derivation fixed** — `config/settings/prod.py` previously hardcoded `environment="production"` in `sentry_sdk.init`, meaning staging events would also tag as `production` (because staging also runs under `config.settings.prod`). Now reads `SENTRY_ENVIRONMENT`, defaulting to `RAILWAY_ENVIRONMENT_NAME` (Railway-injected). Staging events now tag `environment=staging`, prod events tag `environment=production` — they group separately on the Sentry dashboard.
- **Auth Health Grafana dashboard made env-aware** — `infra/grafana/auth-health-dashboard.json` gained an `Env` template variable that pulls available values via `label_values(auth_login_total, env)`. All 4 panel queries (`Login success rate`, `Login outcomes`, `Refresh family revocations`, `Rate-limit hits`) now filter by `env="$env"` so flipping the dropdown switches the dashboard between staging and prod views. The grafana-agent itself needed zero changes because `agent.yaml` already uses `${RAILWAY_ENVIRONMENT_NAME}` for both `cluster` and `env` external labels — prod metrics ship to the same Grafana Cloud workspace tagged `env=production`.
- **Smoke-tested end-to-end:** prod `/healthz` and `/readyz` both 200 (DB ok, Redis ok), frontend renders, login form reachable, `/api/v1/auth/login/` returns the structured `INVALID_CREDENTIALS` 401 envelope, all 5 MFA endpoints visible in `/api/docs/`. KEK validity proven on staging by the QR-code render path; same code on prod.
- **`docs/runbooks/prod-bootstrap.md`** committed — captures the full procedure (env duplicate → secret rotation → verification → observability check), failure modes, and rollback. Reproducible the next time we need a fresh env (DR, new region, separate tenant).

### Known follow-ups
- Frontend landing page still hardcodes "Platform scaffold — staging environment" via `app.status` i18n key. Will need an env-aware key swap (or ship from build-time `environment.*.ts`).
- Login error envelope handling: when the backend returns 401 `INVALID_CREDENTIALS`, the refresh interceptor retries the call, the second response is parsed differently, and the user sees `auth.login.error.UNKNOWN` instead of "Invalid email or password". Pre-existing from M01, exists on both envs. Tracked as a frontend ticket for next milestone.
- `DJANGO_SETTINGS_MODULE` is `config.settings.prod` in BOTH staging and prod envs — the only thing differentiating them is `RAILWAY_ENVIRONMENT_NAME`. Acceptable today (staging matches prod hardening) but worth a `staging.py` settings split if/when staging needs to diverge (e.g. wider CORS for testing, DEBUG toolbar, looser HSTS).

### Added — M02 (MFA & user profile)
- **TOTP-based MFA**, end-to-end. `pyotp.TOTP(interval=30, digits=6)` with ±1 step tolerance; secrets wrapped at rest with `cryptography.fernet` keyed by `settings.FERNET_KEK`. Endpoints: `POST /api/v1/auth/mfa/{enroll,enroll/confirm,verify,disable,backup-codes/regenerate}/`. `LoginView` now branches: enrolled users get `{ mfa_required: true, mfa_token }` (5-min purpose-scoped JWT) instead of an access+refresh pair, and complete login at `/auth/mfa/verify/`. `/verify/` is rate-limited at 5/min/mfa_token to slow brute force. ADR `docs/adr/020-totp-over-sms.md` captures the decision to ship TOTP-only.
- **10 single-use backup codes** generated at enrollment (sha256+per-row salt), regenerable via `/auth/mfa/backup-codes/regenerate/` (requires current password + TOTP — defense-in-depth). The login `/verify/` endpoint accepts either a TOTP code or a backup code via the `is_backup_code` flag.
- **`IsAuthenticatedAndMFAEnforced` permission class** in `apps/users/permissions.py`. Views opt in by setting `mfa_required = True`; the gate denies with structured `{"error":{"code":"MFA_REQUIRED",...}}` (mapped via the new `apps.users.exception_handler.custom_exception_handler` set as DRF `EXCEPTION_HANDLER`). Scaffold `/api/v1/{brokers,orders,risk,strategies}/ping/` endpoints opt in so AC-02-6 is exercised against real URLs; the auto-coverage test asserts every protected prefix denies a non-MFA user.
- **`UserProfile` model** (timezone, language, notification_email, default_broker_id placeholder, terms_version_accepted) auto-created on user creation via `post_save` signal. Endpoints: `GET /api/v1/users/me/` now returns the user + nested profile + `mfa_enabled` flag; `PATCH /api/v1/users/me/update/` validates timezone against `zoneinfo.available_timezones()` and rejects unsupported languages.
- **Authenticated password change** at `POST /api/v1/users/me/password/` — re-prompts current password, applies the same `_validate_password_or_raise` policy, revokes every other refresh-token family, leaves the current session alive.
- **Active sessions UI**: `GET /api/v1/users/me/sessions/` lists non-revoked refresh families with masked IP, summarized UA ("Chrome on macOS"), `last_used_at`, and a `current` flag computed from the access-token's `family_id` claim. `POST /api/v1/users/me/sessions/revoke/` accepts `{family_id}` for a single revoke or `{all: true}` to wipe everything except the current session. `RefreshTokenFamily` schema gained `user_agent`, `ip`, `last_used_at`; `services.issue_token_pair`/`rotate_refresh` now capture and refresh those.
- **Frontend Angular**: `/login/mfa` (custom 6-cell TOTP input with paste/auto-advance/keyboard nav, "Use a backup code instead" toggle); `/settings/security/mfa/setup` (4-step wizard: intro → QR + secret + copy → verify code → backup codes with download/copy/click-to-confirm); `/settings/security` (single page housing MFA enable/disable, regenerate backup codes, sessions list with per-row revoke + "sign out everywhere else", password change form); `/settings/profile` (display name, searchable IANA timezone dropdown via `Intl.supportedValuesOf('timeZone')`, language, email notifications). Auth store gained an `mfa_pending` status and an in-memory-only `mfa_token` signal (5-min lifetime, never persisted to localStorage).
- **MFA Prometheus counters** in `apps/users/metrics_m02.py`: `auth_mfa_enrollments_total`, `auth_mfa_verifications_total{result}`, `auth_mfa_backup_used_total`, `auth_mfa_challenge_failures_total`. Drives the planned "MFA challenge failure rate > 20% over 10 min" alert.
- **Email templates** `mfa_enabled.{txt,html}` and `mfa_disabled.{txt,html}` — sent on every enable/disable so a real user notices an attacker turning off their own MFA.
- **Audit events** added to `AuthEvent.EventType`: `MFA_ENROLLED`, `MFA_DISABLED`, `MFA_CHALLENGE_OK`, `MFA_CHALLENGE_FAIL`, `BACKUP_CODE_USED`, `BACKUP_CODES_REGENERATED`, `PASSWORD_CHANGED`, `PROFILE_UPDATED`, `SESSION_REVOKED`.
- **Runbooks** `docs/runbooks/user-lost-mfa.md` (support recovery flow with identity-check checklist + Django admin "Force-disable MFA" bulk action that emails the user and audit-logs the staff actor) and `docs/runbooks/mfa-kek-rotation.md` (envelope-encryption pattern using `MultiFernet` so the KEK can rotate without decrypting all secrets in one shot).
- **User help page** `frontend/src/assets/help/mfa.html` with setup steps, lost-phone flow, clock-skew tip, and rationale for MFA-gated broker actions.
- **Test suite**: 36 new tests in `apps/users/test_mfa.py` (Fernet roundtrip, TOTP correctness with ±1 step tolerance, backup-code single-use, full enroll/login/disable HTTP flow, regenerate, MFA enforcement against the four scaffold prefixes, profile validation rejecting unknown IANA tz and unsupported languages, password-change family revocation, sessions list/revoke). Total backend test count: 66, all green.

### Settings (M02)
- New env knobs: `MFA_ENABLED` (master kill-switch — when False, `/auth/mfa/*` returns 503 and login skips the MFA branch), `FERNET_KEK` (defaults to a deterministic dev key derived from `SECRET_KEY` so tests run unconfigured; prod must set a real `Fernet.generate_key()` in Railway env), `MFA_TOKEN_TTL_MINUTES`, `MFA_TOTP_VALID_WINDOW`, `MFA_TOTP_ISSUER`, `MFA_BACKUP_CODE_COUNT`. DRF gains a custom `EXCEPTION_HANDLER` that wraps `PermissionDenied("MFA_REQUIRED")` → `403 {"error":{"code":"MFA_REQUIRED",...}}` and `NotAuthenticated` → `401 {"error":{"code":"AUTH_REQUIRED",...}}`.

### Added — earlier
- `apps/users/metrics.py` with the four Prometheus counters required by plan §12: `auth_login_total{result}`, `auth_refresh_total{result}`, `auth_family_revocations_total`, `auth_password_reset_total{step}`. All four are now incremented from views/services on every relevant code path. The Auth Health dashboard panels and three alerts (login success rate < 95%, family revocations > 5/h, sustained 429s) now have data to chart against.
- `backend/gunicorn.conf.py` enabling `prometheus_client` multi-process mode. Each gunicorn worker mmaps its counter state into `/tmp/prom-multiproc` (set via `ENV PROMETHEUS_MULTIPROC_DIR` in `docker/backend.Dockerfile`); the `/metrics` handler aggregates across all workers and the `child_exit` hook calls `multiprocess.mark_process_dead` so dead-worker files don't inflate totals. Verified on staging: 8 consecutive `/metrics` scrapes return identical aggregated values (was bouncing 2/3/4 between workers before).

### Fixed
- `POST /api/v1/auth/register/` no longer returns 500 when Resend rejects delivery (Resend test-sender restriction, SMTP timeout, or any other backend-email failure). `_send_templated` now logs the exception and continues — the user/account is still created and the response is the expected 201/202. Anti-enumeration semantics preserved.
- Grafana alert rules `auth-login-success`, `auth-family-revocations`, `auth-rate-limit-spike` were initially created with range queries flowing into the threshold expression, which Grafana 11 errors on (`looks like time series data, only reduced data can be alerted on`). Switched all three to instant queries (`queryType: 'instant'`, `instant: true, range: false`) so the threshold expression sees a scalar; verified end-to-end by triggering 3+ family revocations and observing the rule transition Inactive → Pending(activeAt) → Firing(activeAt + 5m) → email delivered to `auth-health-email` contact point.

---

## [0.1.0-auth] — 2026-05-01

### Added (since the placeholder 2026-04-30 entry)
- **Railway staging deployment**: 7-service environment (`backend`, `frontend`, `Postgres`, `Redis`, `celery-worker`, `celery-beat`, `grafana-agent`) on a single Railway project, region us-east4. URLs: `https://your-frontend-staging.example.com`, `https://your-backend-staging.example.com`. Project: `https://railway.com/project/YOUR_PROJECT_ID`.
- **Grafana Cloud — Auth Health dashboard live** (`https://YOUR_ORG.grafana.net/d/stp-auth-health`): four panels (login success rate, login outcomes, family revocations, rate-limit hits) and three alert rules wired to email contact point `auth-health-email` → you@example.com. Dashboard JSON checked in at `infra/grafana/auth-health-dashboard.json`.
- `infra/grafana-agent/` Docker config for the `grafana-agent` Railway service (Grafana Agent v0.43.4 in static mode, scraping `backend.railway.internal:8000/metrics` and remote-writing to `prometheus-prod-58-prod-eu-central-0.grafana.net`).
- `docker/nginx.conf.template` with `${BACKEND_URL}` envsubst for the frontend nginx — replaces the docker-compose-only `nginx.conf`.

### Changed
- `docker/backend.Dockerfile`: gunicorn now points at `config.asgi:application` (uvicorn worker requires ASGI; was running `config.wsgi` and 500'ing every request); honors `${PORT}`; runs `migrate --noinput` on boot.
- `docker/frontend.Dockerfile`: switched from baked-in nginx config to the official nginx image's envsubst template flow (`NGINX_ENVSUBST_FILTER=^BACKEND_URL$`), so `BACKEND_URL` resolves at container start.
- `backend/config/settings/prod.py`: `SECURE_SSL_REDIRECT` now defaults to False and is env-controlled — Railway terminates TLS at the edge and Django redirecting again caused infinite loops.
- `backend/config/settings/base.py` (in repo): no functional change, but staging-side `ALLOWED_HOSTS` now includes `backend.railway.internal` so the in-cluster Grafana Agent can scrape `/metrics` without 400.
- `setup-guides/grafana-setup.md` and `docs/runbooks/staging-deploy.md`: updated to reflect actual deployed config (stack slug `YOUR_ORG`, Agent v0.43.4 not Alloy, scope `set:alloy-data-write`); added new troubleshooting rows for ASGI-mismatch, agent binary rename, and `up=0`-from-ALLOWED_HOSTS.

### Verified on staging
- Backend: `/healthz` 200; `/metrics` 200; `/api/schema/` 200 (also via frontend's nginx proxy at `/api/schema/`).
- Grafana Cloud Explore: `up{service="backend"} == 1` after the ALLOWED_HOSTS fix.
- AC-01-1 (register), AC-01-3 (unverified login), AC-01-9 (weak password), AC-01-10 (rate limits), AC-01-13 (auth.* i18n keys present) — all confirmed via curl against the live staging URL.
- AC-01-2/4/5/6/8/11 require manual click-through (verification email + browser auth flow) and are tagged for the next session's smoke test against staging.

---

## [0.1.0-auth] — 2026-04-30

### Added
- **M01 Auth Foundation**: registration, email verification, login, JWT access + refresh rotation, logout, password reset, account lockout, rate limiting, Argon2id hashing.
- Models: `User` (AbstractBaseUser, UUID PK, email-keyed), `EmailVerificationToken`, `PasswordResetToken`, `RefreshTokenFamily` (family rotation w/ reuse detection), `FailedLoginAttempt`, `AuthEvent` (audit precursor).
- Endpoints under `/api/v1/auth/`: `register`, `verify-email`, `resend-verification`, `login`, `refresh`, `logout`, `password/reset`, `password/reset/confirm`; plus `GET /api/v1/users/me/`.
- Email templates (i18n via `blocktrans`): `verify_email`, `password_reset`, `account_locked` (HTML + text).
- Anti-enumeration: register returns 202 on duplicate; password reset always returns 200.
- Rate limits: register 3/min/IP, login 5/min/email + 20/min/IP, password reset 3/min/email.
- Lockout: 10 failed attempts / 15 min sliding window → 15 min lock (env-configurable).
- OpenAPI: envelope serializers + request/response examples in `apps/users/schema.py`; `openapi-typescript` generation wired (`make schema`, `npm run schema:types`); compile-time contract tests.
- Angular: login, register, verify-email, resend-verification, password-reset, password-reset/confirm pages (lazy-loaded).
- Signal-based `AuthStore` + `AuthFacade`; JWT / refresh / error HTTP interceptors; `authGuard` and `guestGuard`; silent refresh on bootstrap via `APP_INITIALIZER`.
- Tests: 24 backend auth unit tests, frontend unit tests (`AuthStore`, `refreshInterceptor`, `authGuard`, form validators), Playwright E2E specs (`auth.register`, `auth.login`, `auth.reset`, `auth.refresh`) with mocked-backend fixture.
- Admin registrations for `AuthEvent`, `RefreshTokenFamily`, `FailedLoginAttempt`.
- ADR-010 (JWT family rotation), ADR-011 (Resend email provider).
- Runbooks: `user-locked-out.md`, `password-reset-abuse.md`.
- Setup guide: `setup-guides/grafana-setup.md` (Auth Health dashboard).

### Pending (gates `v0.1.0-auth` tag)
- Manual: Grafana Cloud **Auth Health** dashboard — see `setup-guides/grafana-setup.md`.
- Manual: AC-01-1 … AC-01-13 verification on Railway staging (depends on M00 staging setup).
- Manual: Sentry release tagged `v0.1.0-auth` after staging verification.
- Verify backend coverage ≥ 80% on `apps/users` via `make test-be` (run inside Docker; no local venv).

---

- Monorepo scaffold: backend (Django 5 + DRF), frontend (Angular 19 + signals), Docker, CI/CD.
- Health endpoints: `GET /healthz`, `GET /readyz`.
- OpenAPI schema at `GET /api/schema/` via drf-spectacular.
- Custom `User` model (AbstractUser, email unique).
- i18n scaffolding: `ngx-translate` (frontend) + Django locale (backend).
- docker-compose with Postgres 16, Redis 7, backend, worker, beat, frontend, ngrok.
- CI pipeline: lint, test, build, Trivy image scan.
- Deploy-to-staging workflow via Railway CLI.
- Observability: Sentry SDK, django-prometheus, OpenTelemetry skeleton.
- ADRs 000–002: tech stack, monorepo, Railway hosting.
- Tailwind CSS with custom design tokens.
- Makefile targets for common dev tasks.
- GitHub issue/PR templates, Dependabot, CODEOWNERS.
