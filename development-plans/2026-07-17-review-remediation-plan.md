# StratTraderPro — Code Review & Design Remediation Plan

**Date:** 2026-07-17
**Author:** Architecture review (full `/engineering:code-review` + `/design:design-critique`)
**Repo state at review:** `main` @ `a77667d`, tag `v0.11.0-rc.1` (M11 implemented; OSS pivot complete)
**Method:** Four adversarial deep-dive passes (backend execution path, backend auth/infra/data, Angular engineering, Angular design/UX), each grounded in source. Every CRITICAL and HIGH finding below was independently re-verified against the actual code by the reviewer before inclusion.

> **How to read this document.** This is a work plan meant to be executed autonomously by Claude CLI (Opus 4.8, Ultra). It is ordered by risk. Each item is self-contained: location, the defect, the required change, acceptance criteria (tests to add), and the verification gate. Line numbers are **as-of-review pointers** — the codebase moves, so confirm the exact line on open and match on the quoted symbol/snippet, not the number.

---

## 1. Implementation status (verified, not tracker-derived)

StratTraderPro is a mature, self-hosted algorithmic-trading platform (Django/DRF + Celery backend ≈30k LOC; Angular 19 signals frontend ≈16k LOC). Per the project's own canonical `project-plan/PROGRESS.md` and confirmed against code:

| Phase | Scope | Status |
|---|---|---|
| M00–M03, M2.5 | Scaffold/CI/observability, auth (JWT family rotation + reuse detection, lockout, reset), MFA (TOTP + backup codes), Google OAuth, strategy upload + webhook config | ✅ Shipped |
| M04 | Webhook ingest + broker adapter + **Alpaca paper** execution | ✅ Implemented (live-paper smoke deferred) |
| M05 | Order lifecycle + TradeStation (behind flag, OFF) | ✅ Implemented |
| M06 / M07 | Market-data + regime classifier / sentiment pipeline | ⚠️ **Code-merged but INERT** — no API keys, no intraday task, fake scorers ⇒ produce no output in any deployed config |
| M08 | Risk engine, sizing & 4-level kill switches | ✅ Implemented |
| M09 | Walk-forward backtester (vectorbt + replay, PBO/CSCV, tearsheets) | ✅ Implemented |
| M10 / M10.5 | Admin portal, chained audit log, observability; app shell, nav, operability | ✅ Done, live-verified |
| M11 | Hardening, security, load test & docs; load/chaos executed on a prod-shaped stack | ✅ Implemented (`v0.11.0-rc.1`, tag local) |
| M13 | Live-trading switch (`ENABLE_LIVE_TRADING`) | ✅ Merged, **disabled by default** |
| M14 / M15 | Frontend first paint / dashboard responsiveness | 📋 Spec only |
| M12 | Beta & sign-off | ❌ Scrapped (OSS pivot) |

**Bottom line:** the platform is feature-complete through M11 and structurally sound — object-ownership/IDOR discipline is consistent, the audit hash-chain is well-built, secret hygiene is tight, settings fail closed, and the previously-reported daily-loss "lifetime P&L" lockout blocker is genuinely fixed. **However**, this review found a cluster of **money-safety and security defects that a green CI does not catch**, concentrated in the exact place the project's own history warns about: the semantics of the execution and risk path, not its syntax. The headline issues:

- The **entire sizing + auto-circuit-breaker layer fails open** when a user has no `RiskProfile` (the default state) — raw webhook quantities reach the broker unclamped, and the daily-loss auto-halt never arms.
- A **transient DB error during fill ingestion permanently drops the fill** (at-least-once silently becomes at-most-once), corrupting the order/position ledger.
- A **read-only admin impersonation can reveal a user's webhook secret** (a bearer credential for order placement) via a GET — privilege escalation, now on a public Apache-2.0 repo.
- The **login MFA second factor has no per-user brute-force cap** (per-IP only) and does not burn the challenge token on failure.
- Two **irreversible, one-click destructive trading actions in the UI** ("Flatten all positions" and "Enable strategy") have **no confirmation** — sitting right next to an excellently-guarded admin halt.

These are addressed first below.

---

## 2. Findings summary

| Severity | Count | Theme |
|---|---|---|
| 🔴 P0 Critical | 4 | Fail-open risk layer, dropped fills, impersonation secret leak, one-click flatten |
| 🟠 P1 High | 10 | MFA brute-force, options 100× sizing, GDPR dead link, refresh-token storage, orphaned orders, ledger drift, kill-switch flag, hard-stop no-op, audit scrub gaps, one-click strategy-enable |
| 🟡 P2 Medium | 22 | Rate-limit/DoS primitives, idempotency window, WS lifecycle leaks, a11y (labels/focus/contrast), design-system drift, halt-UI unification |
| 🟢 P3 Low | ~14 | Redirect validation, Swagger/CSP hardening, float sizing, type-safety, copy/i18n leaks |

Full detail in Sections 4–7. Nothing here blocks the code from *running*; the P0/P1 items block it from being *safe to run live with real money*.

---

## 3. Execution guide (for Claude CLI)

### 3.1 Branching & sequencing
Work the phases **in order** (P0 → P1 → P2 → P3). Each phase is a branch and a PR:

- `fix/review-p0-money-safety`
- `fix/review-p1-security-and-execution`
- `fix/review-p2-hardening-and-a11y`
- `fix/review-p3-polish`

Within a phase, land items as focused commits. Do not batch unrelated items into one commit. If an item needs a DB migration, name it explicitly and run `makemigrations --check` before claiming done.

### 3.2 The verification gauntlet (run locally before declaring ANY item ready)
Green `pytest` + `tsc` is **not** sufficient on this repo (documented house rule). The full local CI-parity gauntlet is:

**Backend** (`cd backend`):
```bash
ruff check .
bandit -r apps/ config/ -x tests -q --severity-level medium
python -m pytest --tb=short -q                       # SQLite, config.settings.test
python -m pytest -m pg --tb=short -q                  # Postgres lane (needs a PG DSN)
python manage.py makemigrations --check --dry-run
pip-audit -r requirements/base.txt -r requirements/prod.txt   # fails on ANY vuln
python -c "import django,os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings.prod'; django.setup()"  # prod-import smoke (set required prod env first)
```

**Frontend** (`cd frontend`):
```bash
pnpm install --frozen-lockfile
npx ngc --noEmit -p tsconfig.app.json                 # REQUIRED: tsc --noEmit does NOT catch NG5002/NG9 template errors
pnpm lint
pnpm test:ci                                          # karma
pnpm build
pnpm exec playwright test e2e/a11y                    # axe-core gate (dashboard/strategies/backtest/risk/admin)
```

**Docker/Trivy:** the CI also builds the backend image and runs Trivy (HIGH/CRITICAL). Keep dependency changes clean.

### 3.3 House-specific gotchas (do not relearn these the hard way)
- **Settings star-import drops `_private` names.** `prod.py`/`dev.py` do `from .base import *`, which skips names starting with `_`. Any new helper used by prod settings must be **named-imported**, or prod crashes with `NameError` — and `test.py` won't catch it (it doesn't load `prod.py`). Always run the prod-import smoke above.
- **Cross-cutting request/worker hooks are WSGI in prod.** Prod serves `config.wsgi` (gunicorn gthread); `asgi.py` only serves the Channels websocket + dev. A hook added only to `asgi.py` is prod-dark. Mirror into `wsgi.py` **and** `asgi.py` **and** `worker_process_init` as applicable.
- **`FERNET_KEK` is required by every Django service** (no default since M10.5). Any new management command / worker path must have it set or it crash-loops while `/healthz` stays green.
- **Angular template check** needs `ngc --noEmit -p tsconfig.app.json`; `tsc` alone is blind to template type errors. Already in the gauntlet above — do not skip it.
- **nginx `NGINX_ENVSUBST_FILTER` is an anchored allowlist.** If you introduce a new `${VAR}` into a frontend-served template, add it to the allowlist or it ships literally to browsers.

### 3.4 Definition of done (per item)
1. Code change made at the cited location(s), matching the quoted symbol.
2. A **regression test that fails before the fix and passes after** (backend: pytest incl. `-m pg` where the path needs Postgres locks; frontend: karma spec; a11y: axe assertion where relevant).
3. Full gauntlet green.
4. No new `ruff`/`bandit`/`pip-audit`/`ngc`/axe findings.
5. `PROGRESS.md` / `CHANGELOG.md` updated with the fix and its evidence, per house convention.

### 3.5 Global guardrail
Several fixes flip behavior from **fail-open to fail-closed on a live-money path**. Where a change could reject orders that previously went through (e.g. P0-1), gate the new strictness so it is **always on for live mode** and, for paper, log-and-reject with a clear reason code rather than silently sizing. Add the reason code to the frontend error allowlist so the user sees a real message.

---

## 4. Phase 0 — 🔴 P0 Critical (money & trust safety)

> These four are the reason this plan exists. Do them first, in this order. Every one is a real, exploitable-in-normal-use defect verified against source.

### P0-1 · Risk/sizing layer fails open when the user has no RiskProfile
**Severity:** 🔴 Critical (money) · **Confidence:** High (verified)
**Locations:**
- `backend/apps/risk/integration.py:93-95` — `apply_sizing` returns `None` when `RiskProfile` is absent.
- `backend/apps/webhooks/tasks.py:287` — `if sizing is not None:` — when `None`, the **raw alert qty** is placed verbatim.
- `backend/apps/risk/killswitch.py:249-250` — `check_daily_loss` returns `False` (no trip) when `profile is None`; the `daily_loss_watcher` only iterates `RiskProfile` holders.

**Defect:** `RiskProfile` is opt-in and does not exist by default. With no profile, an order gets **no position sizing, no `max_position_pct`/`leverage_cap` clamp, no `permitted_asset_classes` filter, no `max_concurrent` limit, and no L2 daily-loss auto-halt** — the webhook `qty` flows straight to the broker, bounded only by broker buying power. (Explicit `TradingHalt` rows still block via `is_blocked`, but the automatic circuit breaker never arms.) On a live instance this silently disables the entire risk subsystem while everything appears to work.

**Required change:** Fail closed. When `SIZING_V1_ENABLED` and no `RiskProfile` exists for the user:
- In **live mode**, reject the order with a new reason code `NO_RISK_PROFILE` (persist a `SizingDecision`/`RiskEvent` like the other reject paths in `integration.py:99-118`).
- Additionally, **auto-provision a conservative default `RiskProfile`** on broker-account connect (in `apps/brokers` account-create path) so the common case is safe-by-default rather than reject-by-default. Choose defaults that are strictly conservative (small `risk_per_trade_pct`, `max_position_pct`, `leverage_cap = 1`, `strict_mode=True`).
- Make `daily_loss_watcher` / `check_daily_loss` operate on **every connected live account**, treating "no profile" as "use the safe default threshold," not "skip."

**Acceptance criteria (tests):**
- `test_no_risk_profile_rejects_in_live_mode` — live account + no profile ⇒ order `REJECTED` with `NO_RISK_PROFILE`, nothing sent to the adapter.
- `test_broker_connect_provisions_default_risk_profile` — connecting an account creates a conservative profile.
- `test_daily_loss_watcher_covers_accounts_without_explicit_profile`.
- Existing "sizing off" behavior for paper/backtester (`requested_qty=0`) must remain intact — assert no regression.

**Verify:** backend gauntlet incl. `-m pg`.

---

### P0-2 · Transient error during fill ingestion permanently drops the fill
**Severity:** 🔴 Critical (ledger integrity) · **Confidence:** High (verified)
**Location:** `backend/apps/orders/fills.py:112-116` — `ingest_fill_event(...)` is wrapped in `try/except Exception`, but `client.xack(...)` runs **unconditionally after** the except block.

**Defect:** The comment intends to skip only *poison* messages, but the bare `except Exception` also catches transient failures (Postgres deadlock/serialization error, connection blip). Any such error logs and then **acks** the Redis-stream entry, removing it from the pending list with no retry and no dead-letter. That execution is lost forever: `order.filled_qty`/status and the `Fill` audit row are permanently wrong, and `reconcile_positions` heals only *position qty* every 5 min — not order state or the fill record. This converts at-least-once delivery into at-most-once on any hiccup.

**Required change:**
- `xack` **only on success**. On exception, leave the entry pending (it will be re-read via the existing `"0"` replay branch and de-duped by `broker_exec_id` — dedup is already correct).
- Distinguish **poison** (bad schema / `json.loads` / `wire_to_fill` `ValueError`) from **transient** (DB/IntegrityError-that-isn't-dup): only true poison is ack'd-and-skipped, and it should go to a **dead-letter stream** (`fills:user:{id}:dead`) plus an alert, never silently vanish.
- Add a bounded retry/backoff so a persistently-poison message can't wedge the consumer forever (track delivery count via `XCLAIM`/`XPENDING` or a per-msg attempt counter; after N, dead-letter).

**Acceptance criteria (tests):**
- `test_transient_ingest_error_leaves_message_pending` — patch `ingest_fill_event` to raise `OperationalError` once; assert the message is **not** ack'd and is reprocessed on the next `drain_stream`, ending in exactly one `Fill` (dedup holds).
- `test_poison_message_is_deadlettered_not_lost` — malformed payload ⇒ routed to dead-letter, alert metric incremented, main stream ack'd.
- `test_dedup_survives_replay` — same `broker_exec_id` delivered twice ⇒ one `Fill`, order state correct.

**Verify:** backend gauntlet incl. `-m pg` (this path needs the real `select_for_update`).

---

### P0-3 · Read-only impersonation leaks the target's webhook secret via GET (privilege escalation)
**Severity:** 🔴 Critical (security) · **Confidence:** High (verified)
**Locations:**
- `backend/apps/users/authentication.py:46-47` — impersonation write-block rejects only non-`SAFE_METHODS`.
- `backend/apps/strategies/views.py:334-353` — `WebhookConfigView.get` calls `get_or_create_webhook_config` and surfaces the reveal-once `secret` on first access.
- `backend/apps/strategies/services.py:108-126` — that helper **creates** a `WebhookConfig` row (a DB write) and returns the plaintext `sig` on first access.

**Defect:** A staff admin on a *read-only* impersonation token can `GET /api/v1/strategies/{id}/webhook-config/` and (a) cause a DB write despite "read-only," and (b) obtain the target's live webhook `sig`. That `sig` is a **bearer credential** for the public ingest endpoint `/hooks/v1/<user>/<strategy>/`, which routes to `process_alert` → real order placement. So the admin can place trades as the user *outside* the audited impersonation session, and burns the real owner's reveal-once (owner never sees their secret). This is now in a public Apache-2.0 repo.

**Required change:** Make "read-only" mean **side-effect read-only**, not just HTTP-method read-only.
- When `request.impersonation` is set, `WebhookConfigView.get` must **never create** a config and **never reveal** a secret: if the config does not yet exist, return `404`/`409`; if it exists, return it with `secret=None, reveal_once=False` unconditionally.
- Best implemented centrally: pass an `allow_create=False` / `impersonating` flag from the view into `get_or_create_webhook_config`, or add a read-only variant `get_webhook_config`. Any other reveal-once/secret-minting endpoint must apply the same guard (audit `strategies` + `brokers` for reveal-once patterns under impersonation).

**Acceptance criteria (tests):**
- `test_impersonation_get_webhook_config_never_creates_or_reveals` — impersonating GET on a strategy with no config ⇒ no row created, no secret returned.
- `test_impersonation_get_existing_config_hides_secret`.
- `test_owner_reveal_once_still_works_without_impersonation` — non-regression.

**Verify:** backend gauntlet.

---

### P0-4 · "Flatten all positions" is a one-click, unconfirmed, irreversible market liquidation
**Severity:** 🔴 Critical (trust/safety) · **Confidence:** High (verified)
**Locations:**
- `frontend/src/app/features/settings/brokers/brokers.component.ts:105-108` — the "Flatten" button, rendered as a subtle amber text link immediately after the (MFA-gated) "Remove" link.
- `.../brokers.component.ts:338-344` — `onFlatten(id)` calls `facade.flatten(id)` directly, **no confirmation, no consequence copy, no MFA**.

**Defect:** "Flatten" liquidates **all** open positions at market on a single click. It is more destructive than "Remove" (which *is* MFA-gated) and than the admin platform-halt (typed-phrase + MFA), yet it is the least-guarded control on the screen. An accidental click closes the user's entire book at market.

**Required change:**
- Route the action through the existing shared `ModalComponent` (`frontend/src/app/features/shared/ui/modal.component.ts`, used as `app-modal`) with an explicit confirm that states the consequence in plain language: *"This closes ALL open positions on this account at market. This cannot be undone."*
- Require a deliberate confirmation step (typed confirm or MFA step-up, consistent with the broker-remove flow).
- Do not render Flatten to users who can't use it (backend currently only 403s); gate on capability.
- Reuse the unified `HaltConfirmModal` from item P2-DESIGN-1 if that lands first (shared component).

**Acceptance criteria (tests):**
- Karma: clicking Flatten opens the modal and does **not** call `facade.flatten` until confirmed; cancel path calls nothing; confirm path calls once.
- axe: the modal passes the a11y gate (role=dialog, focus trap — inherited from `ModalComponent`).

**Verify:** `ngc --noEmit -p tsconfig.app.json`, `pnpm test:ci`, axe gate.

---

## 5. Phase 1 — 🟠 P1 High

### P1-1 · Login MFA challenge has no per-user brute-force cap and does not burn the token on failure
**Severity:** 🟠 High (security) · **Confidence:** High (verified)
**Locations:** `backend/apps/users/views_m02.py:229-249` (`MFAVerifyView` verifies TOTP directly, returns 401 on fail but does **not** invalidate `mfa_token`) and `:260-262` (throttled only by `ratelimit(key="ip", rate="5/m")`). Contrast the correct pattern in `backend/apps/users/mfa.py:227-249` (`verify_mfa_code`, the step-up path) which keeps a per-user cache counter (`MFA_STEPUP_MAX_FAILURES`).

**Defect:** The primary login second factor is rate-limited **per IP only**. The in-code "138-day" comment assumes a single IP and no token re-minting — both false for a real attacker. Someone who already has the password (breach/phishing) mints fresh `mfa_token`s at 5/min and brute-forces TOTP from a distributed IP pool; with `valid_window=1` (~3 live codes/10⁶) the second factor falls well within a session window. The `mfa_token` is also reusable for its full 5-min TTL.

**Required change:**
- Apply the same **per-user (and per-`mfa_token` jti) attempt counter** used by `verify_mfa_code` to `MFAVerifyView`; lock the challenge after N failures.
- **Burn the `mfa_token`** after N failed attempts (bind attempts to its jti and reject further use), forcing a fresh password login.
- Keep the per-IP limiter as a secondary control.

**Acceptance criteria:** `test_mfa_login_locks_after_n_failures_per_user`; `test_mfa_token_burned_after_failures`; `test_valid_mfa_still_succeeds_within_limit`.
**Verify:** backend gauntlet.

---

### P1-2 · Option/future sizing ignores the contract multiplier — every risk ceiling is ~100× too loose for options
**Severity:** 🟠 High (money) · **Confidence:** High (verified)
**Locations:** `backend/apps/risk/sizing.py:32` (`contract_multiplier` defaults to `Decimal("1")`), used at `:79, :104`; `backend/apps/risk/integration.py:171-181` builds `SizingInputs` **without** setting `contract_multiplier`, even though the order already carries `asset_class=OPTION`/`FUTURE` and option details (`webhooks/tasks.py:247-259`).

**Defect:** An equity option controls 100 shares, but `compute_size` runs with multiplier=1 and `price` = per-share premium. So `raw_qty`, `max_qty_by_pos`, and the `leverage_cap` clamp all compute ~100× larger than intended for options — the risk ceilings never bind, and the alert's `requested_qty` passes through effectively unclamped. Futures have per-root multipliers with the same failure.

**Required change:**
- Populate `SizingInputs.contract_multiplier` from the order's asset class when building inputs in `apply_sizing`: 100 for equity options; a per-root lookup for futures (add a small `FUTURE_MULTIPLIERS` map with a conservative default and a `TODO` for completeness). Carry the multiplier onto the `Order` for auditability.
- Ensure notional/leverage math uses `price × qty × multiplier` consistently.

**Acceptance criteria:** `test_option_notional_uses_100x_multiplier` (property: option notional == qty × price × 100); `test_leverage_cap_binds_for_options`; `test_equity_sizing_unchanged` (multiplier=1 regression).
**Verify:** backend gauntlet.

---

### P1-3 · GDPR data-export download is a dead, unsigned link in the default self-hosted prod
**Severity:** 🟠 High (correctness + privacy) · **Confidence:** High (verified)
**Locations:** `backend/apps/users/tasks.py:28-31` (`signed_export_url()` → `export_storage().url(file_key)`); `backend/config/settings/base.py:734-740` (filesystem fallback `base_url="/media/exports/"`); `backend/config/settings/prod.py:146-155` (documents the filesystem fallback as the self-hosted default; the `/media/exports/` `base_url` literal itself is in `base.py:738`). **`MEDIA_URL`/`MEDIA_ROOT` are defined nowhere** (verified: `grep -rn MEDIA_URL\|MEDIA_ROOT backend/config` → none) and nothing serves `/media/` (no `static()` urlpattern, no nginx `location`; WhiteNoise serves only `STATIC_ROOT`).

**Defect:** A completed export emails/returns a `/media/exports/...` URL that 404s. Where `FileSystemStorage` is used, the advertised "24h signed URL" (`querystring_expire`) is a silent no-op — the URL, if ever served, would be unsigned and permanent. The GDPR export feature is non-functional in the default deploy.

**Required change:** Serve exports through an **authenticated Django view** that checks `job.user == request.user` **and** `not job.is_expired`, then streams the bytes (`FileResponse`) with `Content-Disposition: attachment`. Point `signed_export_url()` at that view's reverse URL for the filesystem backend; keep the true signed-URL path for S3/R2. Add the URL route. Do not rely on an unserved `/media/` path.

**Acceptance criteria:** `test_export_download_requires_owner` (owner 200, other user 404/403); `test_export_download_404_after_expiry`; `test_export_url_points_at_served_route_for_filesystem_backend`.
**Verify:** backend gauntlet + prod-import smoke.

---

### P1-4 · Long-lived refresh token stored in localStorage (XSS-exfiltratable)
**Severity:** 🟠 High (security) · **Confidence:** High (verified)
**Location:** `frontend/src/app/abstraction/stores/auth.store.ts:5, 11, 45, 112-127` — access + MFA tokens are correctly in-memory-only signals, but the **refresh** token is persisted to `localStorage` and reloaded on construction.

**Defect:** `localStorage` is readable by any JS on the origin. A single XSS (see P2-6, the `bypassSecurityTrustHtml` help sink, now reachable via public-repo PRs) hands an attacker the refresh token — indefinite access-token minting, i.e. persistent takeover of an account that places live trades.

**Required change (pick per the deployment model, document the decision as an ADR):**
- **Preferred:** backend issues the refresh token as an `HttpOnly; Secure; SameSite=Strict` cookie scoped to the refresh endpoint, with CSRF protection on that endpoint; the SPA never sees it. This touches `apps/users` token issuance + the frontend refresh interceptor (stop reading the token from the store; rely on the cookie). Single-origin self-hosting makes this clean.
- **Minimum if cookie is rejected:** move the refresh token to in-memory only (accept re-login on full page refresh) — still strictly better than `localStorage`.

**Acceptance criteria:** backend spec for cookie set/rotate/clear on login/refresh/logout; frontend refresh-interceptor spec updated; assert token no longer in `localStorage`. Update `refresh.interceptor.spec.ts` accordingly.
**Verify:** backend gauntlet + frontend gauntlet. Coordinate with P2-5..P2-8 (WS/refresh) since they share the flow.

---

### P1-5 · Ambiguous broker failure marks the order REJECTED and orphans a possibly-live order
**Severity:** 🟠 High (money) · **Confidence:** Medium-High (verified)
**Locations:** `backend/apps/webhooks/tasks.py:311-316` (`_reject` on `BrokerError`/`Exception`); `backend/apps/brokers/streams.py:64-88` (`catch_up_account` re-checks only `SUBMITTED/PARTIAL/PENDING_SUBMIT`); mitigation at `backend/apps/brokers/alpaca/adapter.py:261-273` (duplicate probe by `client_order_id`).

**Defect:** If `place_order` raises after a submit timeout **and** the duplicate probe also fails (network still down), the order is set `REJECTED` locally while potentially **live/resting at the broker**. The reconnect sweep won't re-examine a `REJECTED` order, so a working order (esp. an unfilled resting limit) becomes invisible to the platform and to daily-loss accounting, and can fill later untracked.

**Required change:**
- On *ambiguous* failure (timeout/unknown, not a definitive broker 4xx rejection), set a distinct non-terminal state `NEEDS_RECONCILE` rather than `REJECTED` (add to `Order.Status`, migration required).
- Extend `catch_up_account` (and the periodic reconcile) to re-resolve **any** order that has a `broker_order_id` **or** is in `NEEDS_RECONCILE`, regardless of local status, using the broker's order-lookup endpoint.

**Acceptance criteria:** `test_ambiguous_submit_marks_needs_reconcile_not_rejected`; `test_reconcile_resolves_needs_reconcile_order`; `test_definitive_broker_rejection_still_rejects`.
**Verify:** backend gauntlet incl. `-m pg`; `makemigrations --check`.

---

### P1-6 · Order `filled_qty` is accumulated locally instead of trusting the broker cumulative — first lost fill sticks it at PARTIAL forever
**Severity:** 🟠 High (ledger) · **Confidence:** Medium (verified) · **Depends on P0-2**
**Locations:** `backend/apps/orders/services.py:173` (`order.filled_qty = (order.filled_qty or 0) + fill.qty`), status derived at `:190-196`; broker cumulative available but discarded (`FillEvent.filled_qty`, `backend/apps/brokers/base.py:159`; mapped at `alpaca/mapping.py:203`).

**Defect:** Terminal order state is computed from a **local running sum**. If any fill is dropped (see P0-2) the sum stays short and the order never reaches `FILLED`; reconcile heals position qty but not order state. The event already carries the broker's authoritative cumulative `filled_qty`, which is thrown away.

**Required change:** When the event carries a broker cumulative, set `order.filled_qty = max(order.filled_qty, event.filled_qty)` and resolve `FILLED` vs `PARTIAL` against `order.qty` using the broker cumulative; keep the local sum only as a fallback when the cumulative is absent.

**Acceptance criteria:** `test_filled_qty_uses_broker_cumulative`; `test_dropped_intermediate_fill_still_reaches_filled_on_final_event`; `test_partial_then_full_sequence_correct`.
**Verify:** backend gauntlet incl. `-m pg`.

---

### P1-7 · `KILL_SWITCHES_ENABLED=false` silently drops user-global, daily-loss, and platform halts
**Severity:** 🟠 High (safety) · **Confidence:** High (verified)
**Location:** `backend/apps/risk/killswitch.py:74-80` — when `_enabled()` is false, `is_blocked` honors only an L0 strategy toggle and returns `None` for L1 (user-global), L2 (auto daily-loss), and L3 (platform) halts.

**Defect:** A single ops flag meant to disable the *engine* also disables the platform-wide **emergency stop** and the daily-loss breaker, with no signal. An operator flipping "kill switches" off to pause automation unknowingly voids their emergency halt.

**Required change:** Always honor active `TradingHalt` rows (they are explicit operator/state decisions). Let the flag gate only the **automatic tripping** (the `daily_loss_watcher` creating new L2 halts), never the *reading/enforcement* of existing halts. Reorder `is_blocked` so L3/L1/L2-existing checks run before the `_enabled()` short-circuit.

**Acceptance criteria:** `test_platform_halt_enforced_even_when_engine_disabled`; `test_user_halt_enforced_when_engine_disabled`; `test_flag_only_gates_auto_trip`.
**Verify:** backend gauntlet.

---

### P1-8 · `hard_stop_pct` is collected and validated but never enforced
**Severity:** 🟠 High (false protection) · **Confidence:** High (verified)
**Locations:** `backend/apps/risk/models.py:21` (`hard_stop_pct`); validated at `backend/apps/risk/serializers.py:45-47` (`soft_stop_pct < hard_stop_pct`); only `soft_stop_pct` is consumed (`backend/apps/risk/sizing.py:93`).

**Defect:** Users configure a hard stop expecting trading to **stop** at that drawdown; nothing reads it on the execution path. The soft stop only halves size. This is a silent no-op on a safety control.

**Required change:** In `compute_size`/`apply_sizing`, when `intraday_dd_pct >= hard_stop_pct`, **reject** the order (`HARD_STOP`) and trigger an L2 halt for the account (mirroring the daily-loss trip), so trading actually stops for the day. Emit the `RiskEvent` + metric.

**Acceptance criteria:** `test_hard_stop_rejects_and_halts_at_threshold`; `test_soft_stop_still_only_halves_below_hard`; `test_hard_stop_boundary`.
**Verify:** backend gauntlet.

---

### P1-9 · Audit scrubber uses exact key match; secret-ish keys pass through into the immutable log
**Severity:** 🟠 High (security/privacy) · **Confidence:** High (verified)
**Locations:** `backend/apps/audit/scrub.py:21-24, 44` (exact-match denylist: `authorization, sig, secret, password, token, api_key, dsn, key, code, mfa_code`); `backend/apps/strategies/views.py:265-269` (`StrategyDetailView.patch` emits `data_after={k: request.data.get(k) for k in request.data}` — every client key into the audit diff).

**Defect:** Substring variants (`api_secret`, `current_password`, `secret_encrypted`, `refresh`, `access`) are **not** redacted, unlike the GDPR export denylist which does substring matching (`gdpr.py:43-45`). Combined with the strategy-PATCH copying arbitrary body keys, a body like `{"name":"x","current_password":"…"}` persists unredacted into the **append-only, immutable** audit log — unfixable after the fact.

**Required change:** Make `scrub()` match on **substrings** (reuse the GDPR `SENSITIVE_FIELD_PARTS` approach; consolidate the two denylists into one shared constant). Independently, restrict `StrategyDetailView.patch` audit to a **known field allowlist** rather than echoing all request keys.

**Acceptance criteria:** `test_scrub_redacts_substring_keys` (`api_secret`, `current_password`, etc.); `test_strategy_patch_audit_only_allowlisted_fields`; parametrized test shared across scrub + gdpr denylists.
**Verify:** backend gauntlet.

---

### P1-10 · "Enable strategy" arms automated live execution with one tap, no confirmation
**Severity:** 🟠 High (trust/safety) · **Confidence:** High (verified)
**Locations:** `frontend/src/app/features/strategies/list/strategies-list.component.ts:77-84` (toggle button) and `:126-128` (`onToggle` → `facade.toggleEnabled` directly). Note `onDelete` (`:130`) *does* use a native `confirm()`, but its copy leaks dev jargon ("reversible by toggling `is_enabled` in admin") and the far more dangerous enable is unguarded — inverted risk priority.

**Defect:** Flipping the toggle **on** arms automated order execution immediately; user-uploaded strategies show an "untested" banner yet go live instantly with no confirmation.

**Required change:** Confirm on **enable** (disable can stay one-click) via the shared modal, with consequence copy: *"Enabling this strategy will execute live orders from its webhook alerts."* Rewrite the delete copy for end users and route it through the shared modal too (see P2 design cluster). Add `role="switch"` + `[attr.aria-checked]` while here (see P2-A11Y).

**Acceptance criteria:** karma: enable opens modal, `toggleEnabled` only fires on confirm; disable stays immediate; switch exposes `aria-checked`.
**Verify:** `ngc --noEmit -p tsconfig.app.json`, `pnpm test:ci`, axe gate.

---

## 6. Phase 2 — 🟡 P2 Medium

### 6a. Backend security & abuse-resistance

**P2-1 · TradingView IP allowlist bypassable via client `X-Forwarded-For`.** `backend/apps/webhooks/views.py:68-72` (`_client_ip` returns `XFF.split(",")[0]` — the client-settable left-most hop), enforced at `:106-109`. When operators enable `WEBHOOK_IP_ALLOWLIST`, an attacker sets `X-Forwarded-For: <allowlisted_ip>` to pass. **Fix:** derive the client IP from the right-most XFF entry after a configured `TRUSTED_PROXY_COUNT` (Railway/nginx), or use `REMOTE_ADDR`. **Test:** `test_xff_spoof_does_not_satisfy_allowlist`.

**P2-2 · Pre-auth per-user webhook rate limit lets anyone throttle a victim's alerts.** `backend/apps/webhooks/views.py:75-88` (`_rate_limited`, keyed only on path `user_id`), applied at `:101-103` **before** the `sig` check. Anyone who knows the (public) webhook URL can send 60+ unauth requests/min and 429 the victim's real TradingView alerts — a blocked exit/stop can mean an unbounded loss. **Fix:** rate-limit per source IP (correctly derived, P2-1) in addition to per-user, and/or only consume the budget on requests that fail the secret check so valid alerts are never starved. **Test:** `test_bad_sig_flood_does_not_starve_valid_alert`.

**P2-3 · Register / resend-verification / password-reset are per-email rate-limited only (email-bomb amplifier).** `backend/apps/users/views.py:162, 276-278, 513-515` use only `_email_keyer`, unlike `LoginView` (`:396-398`) which stacks per-email **and** per-IP. One IP can trigger unlimited verification/reset emails by cycling addresses. **Fix:** add a second `ratelimit(key="ip", rate=…)` to all three, mirroring login. **Test:** `test_reset_rate_limited_per_ip_across_emails`.

**P2-4 · Per-email login lockout/limit is a targeted DoS primitive.** `backend/apps/users/views.py:396-398` + `backend/apps/users/services.py:219-234`: an attacker submitting a victim's email 5×/min (throttle) or 10 bad attempts/15min (lockout, 423) can lock/throttle any account with only the address. **Fix:** treat per-IP as primary, per-email as secondary; consider IP-aware lockout or a CAPTCHA step. Document the tradeoff as an ADR. **Test:** `test_remote_attacker_cannot_lock_victim_from_one_ip_alone` (after mitigation).

**P2-5 · Webhook idempotency committed before durable enqueue; no requeue for stranded alerts.** `backend/apps/webhooks/views.py:181-187` (SETNX) then `:204-213` (create row + `process_alert.delay`). A crash between them makes a retry return `{"duplicate": true}` while the alert is never processed. **Fix:** make the committed `AlertMessage` the idempotency anchor (`unique(user, idempotency_key)`), set SETNX after commit, dispatch via `transaction.on_commit`, and add a periodic task re-dispatching `RECEIVED` alerts older than N seconds. **Test:** `test_crash_before_dispatch_is_reprocessed`; `test_stranded_received_alert_requeued`.

**P2-6 · GDPR export ZIPs never evicted and survive anonymization.** `backend/apps/users/gdpr.py:179-234` (`anonymize_user` deletes MFA/broker rows but not `DataExportJob` rows or their ZIPs) and no beat task evicts expired artifacts (`base.py:616-677`). A full personal-data export persists on disk past right-to-erasure. **Fix:** nightly task deleting `export_storage()` objects + `DataExportJob` rows past `expires_at`; purge a user's export jobs+files in `anonymize_user`. **Test:** `test_expired_exports_evicted`; `test_anonymize_purges_exports`.

**P2-7 · Audit `emit()` holds the global advisory lock for the whole enclosing transaction.** `backend/apps/audit/services.py:98-129` takes `pg_advisory_xact_lock` released only at top-level commit; when called inside a caller's `atomic()` it serializes all audit writes behind the slowest business txn. Correctness is fine; throughput is the risk as usage grows. **Fix:** scope the head-read lock to a short savepoint or use row-level `SELECT … FOR UPDATE` on the chain head, so contention lasts only for the emit. **Test:** `-m pg` concurrency test asserting two emits inside long outer txns don't serialize beyond the insert.

**P2-8 · Refresh rotation reads the family without a row lock (concurrent refresh self-revokes).** `backend/apps/users/services.py:139-179` does `get()` then compare-and-swap `current_jti` without `select_for_update`. Two near-simultaneous valid refreshes both rotate; the loser trips reuse-detection and revokes the whole family — a double-submitting client logs itself out everywhere. **Fix:** `select_for_update()` the family row inside a transaction for the CAS, or allow a one-step grace jti. **Test:** `-m pg` `test_concurrent_refresh_does_not_revoke_family`.

### 6b. Frontend lifecycle & correctness

**P2-9 · WebSocket subscriber refcount corrupted by reconnect → socket never torn down.** `frontend/src/app/core/services/ws.service.ts:44-45` (`connect()` does `this.refs += 1` unconditionally) and `:124-132` (reconnect calls `connect()`), compounded by `backtest.facade.ts:187` (`start()` → `ws.connect()`) vs `:191-194` (`stop()` never calls `disconnect()`). Every reconnect inflates `refs`, so `disconnect()` (closes only at `refs===0`) can never fire; the dashboard socket + 25s heartbeat leak and keep mutating the store after the user leaves. **Fix:** split a private `openSocket()` (no refs mutation) used by both `connect()` and the reconnect timer; only public `connect()` touches `refs`. Make `BacktestFacade.stop()` call `ws.disconnect()`. **Test:** spec asserting refs return to 0 after connect→reconnect→disconnect; backtest start/stop balanced.

**P2-10 · JWT access token passed in the WebSocket URL query string.** `frontend/src/app/core/services/ws.service.ts:56` (`…/ws/dashboard/?token=${…}`). URLs land in proxy/daphne access logs and history. **Fix:** carry the token via `Sec-WebSocket-Protocol` subprotocol, or issue a short-lived single-use WS ticket over HTTPS. Requires a small backend change to the Channels consumer auth (`apps/dashboard`). **Test:** consumer accepts subprotocol/ticket; rejects tokenless.

**P2-11 · WS reconnects forever with a stale token; logout doesn't tear the socket down.** `frontend/src/app/core/services/ws.service.ts:52-53, 124-132` (unbounded reconnect re-reading a possibly-expired token) and `auth.facade.ts:242-249` (`logout()` — the path the refresh-interceptor calls on failure — does not call `ws.forceDisconnect()`, unlike `signOut()` `:254-262`). **Fix:** on repeated auth-failure closes, trigger `refreshSession()` before retrying (or stop and surface a reconnect UI); add `ws.forceDisconnect()` to `logout()`. **Test:** spec for teardown-on-logout and refresh-on-auth-close.

**P2-12 · Gratuitous `bypassSecurityTrustHtml` on help content (only sanitizer-off HTML sink).** `frontend/src/app/features/help/help-article.component.ts:67` bound at `:28` (`[innerHTML]`). The styled tags (`h1/h2/p/ul/a/code`) all survive Angular's default sanitizer, so the bypass is pure risk — and on a public repo taking PRs, a malicious `assets/help/*.html` could run `<script>`/`<img onerror>` in an authed session (and exfiltrate the P1-4 token). **Fix:** bind the raw string to `[innerHTML]` (Angular sanitizes; styling preserved); if rich markup is truly needed, run through DOMPurify. **Test:** spec asserting an injected `<script>`/`onerror` is stripped.

**P2-13 · Zone change detection with data-heavy components not OnPush.** `frontend/src/main.ts:29` (no zoneless) and non-OnPush realtime/table components (`features/dashboard/dashboard.component.ts:29`, `features/orders/orders.component.ts:26`, `features/risk/…`, `features/strategies/…`, `features/settings/…`). Every WS frame/heartbeat/timer triggers a full-tree CD pass on the busiest screens. Since state is entirely signal-driven, **fix:** add `ChangeDetectionStrategy.OnPush` to the feature components (no template changes) and evaluate `provideExperimentalZonelessChangeDetection()`. **Test:** existing specs must stay green under OnPush; add a CD-count assertion where practical.

**P2-14 · Bootstrap blocks on an untimed network refresh (white-screen on slow backend).** `frontend/src/app/app.config.ts:42-47` (`APP_INITIALIZER` → `initAuth`) → `auth.facade.ts:302-306` → `:264-276` (`firstValueFrom` with no timeout). **Fix:** wrap the bootstrap refresh in a timeout and continue unauthenticated on failure; migrate deprecated `APP_INITIALIZER` → `provideAppInitializer` (Angular 19). **Test:** spec: slow/failed refresh resolves to login, not hang.

### 6c. Design, accessibility & UX

**P2-DESIGN-1 · Unify the three divergent halt UIs into one guarded modal.** Admin halt (`features/admin/halt-platform-modal.component.ts`) is excellent (typed phrase + MFA + shared focus-trapping `app-modal`); dashboard halt (`features/dashboard/dashboard.component.ts:195-231, confirmHalt:316`) is a hand-rolled `div` with no `role="dialog"`/focus trap/Escape and **hardcodes `flatten:true`** without saying so; risk halt (`features/risk/risk.component.ts:183`) is an inline form making flatten an opt-in checkbox. **Fix:** build one `HaltConfirmModal` on `app-modal` with an explicit flatten choice + consequence copy; reuse in dashboard, risk, and (with P0-4) brokers-flatten. Resolves TS-3, TS-4, A11Y-6. **Test:** karma + axe on the shared modal.

**P2-DESIGN-2 · Make forms perceivable to assistive tech.** Zero `aria-describedby` in the codebase — inputs set `aria-invalid` but the visible `<p role="alert">` error is never linked (`features/auth/register/register.component.ts:67-84`); risk errors aren't even `role="alert"` (`features/risk/risk.component.ts:83-85`); the strategy toggle is a plain `<button>` with no `role="switch"`/`aria-checked` (`strategies-list.component.ts:77-84`); broker-connect/orders-filter/MFA-remove fields lack `for`/`id`; radio/checkbox groups use a `<span>` pseudo-label not `<fieldset><legend>` (`risk.component.ts:101`, `backtest…:143`). **Fix:** give each error a stable `id` + wire `aria-describedby`; `for`/`id` on every field; `fieldset`/`legend` for groups; `role="switch"` + `aria-checked` on the toggle. **Verify:** axe gate + manual SR pass on register/risk/brokers.

**P2-DESIGN-3 · Add route-change focus management + announcement.** No `NavigationEnd` handler anywhere (`app.component.ts`, `shared/shell/shell.component.ts`); after nav, focus stays on the link and SR users aren't told the page changed (skip link exists but nothing resets focus). **Fix:** on `NavigationEnd`, move focus to the page `<h1>`/`<main>` and announce via an `aria-live` region. **Verify:** axe + manual keyboard/SR.

**P2-DESIGN-4 · Fix danger/success token contrast (AA failures).** Computed from `styles/tokens.css`: white on `success-500 #22c55e` = **2.28:1** (success toast, onboarding "Done" badge) and white on `danger-500 #ef4444` = **3.76:1** (danger button, error toast) both **fail** AA; `accent-500 #14b8a6` text on white = **2.49:1** (landing steps, "Getting started") fails; `slate-400 #94a3b8` completed-step = **2.56:1** fails. **Fix:** darken tokens (danger→~`#dc2626`, success→~`#16a34a`, accent for text emphasis→a darker shade or use `primary`), re-verify toast host + onboarding + button. **Verify:** contrast check on the changed pairs; axe gate.

**P2-DESIGN-5 · Adopt the shared kit + design tokens across feature screens.** 485 hardcoded Tailwind palette colors across 34 feature files while `styles/tokens.css` defines primary/danger/success/accent; the shared kit (`app-button`, `app-card`, `app-page-header`, `app-spinner`, `app-empty-state`) is barely used outside shell/landing. Root cause of most inconsistency, several a11y gaps, and the contrast failures (VH-1: page `<h1>`s omit `text-primary-900`). **Fix:** migrate one-off markup to the kit + token classes; add a lint/safelist rule against raw palette. This is a large, mechanical, high-value cleanup — do it screen-by-screen with the gauntlet green after each. **Verify:** grep shows raw-palette count trending to ~0 on touched screens; visual spot-check.

**P2-DESIGN-6 · Fix the disabled-submit trap on auth forms.** `features/auth/login/login.component.ts:54` and `register/register.component.ts:86` set `[disabled]="form.invalid || facade.status()==='loading'"` — the `form.invalid` half means the `markAllAsTouched()` in `onSubmit` is unreachable and Enter-submit is blocked — a user who tabs past a field sees a dead button with no reason. **Fix:** keep the button enabled, validate on submit, move focus to the first error; disable only while loading. **Test:** karma: invalid submit shows errors + focuses first invalid field.

**P2-DESIGN-7 · Complete missing loading/empty/error states + fix raw-JSON risk feed.** Loading states are uneven (positions has one at `dashboard.component.ts:121`; broker-status, fills, and risk events/sizing at `risk.component.ts:265,285` have none — slow loads flash a misleading "empty"). Risk events dump raw truncated JSON (`risk.component.ts:275`, `{{ e.details | json }}`). Error toasts auto-dismiss in 6s with no pause (`shared/ui/toast/toast.service.ts`), so a user can miss a trading error (WCAG 2.2.1). **Fix:** add loading states via `app-spinner`; render key risk-event fields with raw JSON behind an expander; make error toasts persist until dismissed / pause on hover. **Verify:** karma + axe.

**P2-DESIGN-8 · Standardize error/success/i18n handling.** Error display is inconsistent (login maps codes to i18n at `login.component.ts:19`; register prints raw `err.message` at `:31`; brokers/risk/backtest use allowlist+fallback; upload prints raw). Success feedback is done four ways despite a global `ToastService`. Hardcoded English leaks into an otherwise fully-i18n app (`strategies-upload.component.ts:192-194` 'Must end in .pine' / byte counts; both `confirm()` strings). **Fix:** standardize on allowlist+fallback (or a shared error pipe); route confirmations through the toast host; move leaked strings to translation keys and humanize byte sizes. Extract a shared currency/qty pipe to replace the per-screen `fmtMoney`/`fmtQty` (USD hardcoded at `dashboard.component.ts:292`). **Verify:** frontend gauntlet.

---

## 7. Phase 3 — 🟢 P3 Low (polish & defense-in-depth)

Each is a small, self-contained change; batch them into the `fix/review-p3-polish` PR with one test each where behavior changes.

| ID | Location | Issue | Fix |
|---|---|---|---|
| P3-1 | `backend/apps/risk/sizing.py:69-114` | Sizing math runs in `float`, `Decimal` only at the end — off-by-one lot risk at boundaries in an otherwise Decimal money path (worsens once P1-2 multipliers land) | Keep computation in `Decimal` with `quantize` for the lot floor, or document why float is acceptable |
| P3-2 | `backend/apps/webhooks/views.py:139-160` | Bad-`sig` request for a *known* (user,strategy) writes a `REJECTED` `AlertMessage` each time (DB write-amplification + latency timing oracle for valid pairs) | Rate-limit/aggregate bad-sig persistence (counter + first/last seen) and keep known-vs-unknown paths timing-symmetric |
| P3-3 | `backend/apps/risk/killswitch.py:216-238` + `tasks.py:41-47` | Daily-loss watcher does a synchronous `get_account()` per account serially on a 30s beat — a scaling landmine that can delay the breaker | Cache last-good equity snapshots (short TTL, shared with sizing read); parallelize + cap work per beat |
| P3-4 | `backend/apps/webhooks/views.py:163-165` (schema at `strategies/models.py:132`) | User-editable JSON Schema executed on the hot ingest path — pathological schema (deep nesting / unbounded `pattern`) can burn CPU (self-inflicted ReDoS) | Validate/limit schema complexity at save time (max depth; forbid unbounded `pattern`/`patternProperties`); optional wall-clock guard |
| P3-5 | `backend/config/urls.py:61-62` | `/api/schema/` + `/api/docs/` served unauthenticated in prod — full API surface disclosure | Gate behind `IsAdminAndMFAEnforced` (or `DEBUG`-only) in prod |
| P3-6 | `backend/config/settings/base.py:824-828` | `CSP_REPORT_ONLY` defaults `True` — the good `default-src 'none'` policy is never enforced | Set `CSP_REPORT_ONLY=false` in prod once P3-5 gates Swagger, or exempt only the docs route |
| P3-7 | `frontend/.../auth.facade.ts:146,173,233` | Post-login `next` redirect passed straight to `navigateByUrl` (router mitigates external origin, hence Low) | Accept `next` only if it starts with a single `/` (reject `//` and `scheme:`), else `/dashboard` |
| P3-8 | `frontend/.../settings/brokers/brokers.component.ts:359` | `window.location.href = res.value.authorize_url` — top-level nav to an unvalidated server URL (real off-origin sink if ever influenced) | Assert `https:` + host allowlist before assigning |
| P3-9 | `frontend/core/guards/guest.guard.ts:9` vs `auth.guard.ts:18` / `landing.guard.ts:12` | Guards use two different "authenticated" predicates — latent inconsistency | Add one `isEffectivelyAuthed` computed on the store; use in all four guards |
| P3-10 | `frontend/.../help/help-article.component.ts:54,65` | `route.paramMap.subscribe` + nested `http.get().subscribe` without `takeUntilDestroyed` — the one component departing from the codebase's leak-safe pattern | `toSignal`/`takeUntilDestroyed()`; reuse the promise-based HTTP pattern |
| P3-11 | `frontend/core/interceptors/refresh.interceptor.ts:13-14,58` | Module-global mutable refresh state + dead `!== null` filter with a misleading double-cast | Delete the filter; move in-flight coordination into an injectable service (logic itself is correct) |
| P3-12 | `frontend/core/interceptors/refresh.interceptor.ts:94`; `features/backtest/backtest-detail.component.ts:235,376-461` | `Observable<any>` on the retry path; untyped chart.js config | Type as `Observable<HttpEvent<unknown>>`; import chart.js types |
| P3-13 | `frontend/shared/ui/help-link.component.ts` | Inline "?" help target is 16×16px (below WCAG 2.5.8 ≥24×24) | Pad the hit area to ≥24px |
| P3-14 | Data tables (dashboard/orders/risk/backtest/admin) | `<th>` lacks `scope="col"`; filter/paginate changes results with no `aria-live` | Add `scope="col"`; announce "N results" politely after load |

---

## 8. What is strong — preserve these (do not regress)

The review found genuinely good engineering. Treat these as invariants when implementing the above:

- **Object-ownership / IDOR discipline is consistent** — every list/detail endpoint filters by `request.user`; admin endpoints are the only `.objects.all()` and are `IsAdminAndMFAEnforced`-gated. Keep it that way for any new endpoint (P1-3, P1-5).
- **Fill dedup + position math are correct** — `ingest_fill_event` is `@transaction.atomic` with `select_for_update`, `Fill` dedup is a real DB `unique_together (broker_account, broker_exec_id)`, and position math is Decimal with correct weighted-average + flip-through-zero. P0-2 and P1-6 must **not** weaken this.
- **The submit path already handles timeout-may-have-landed** (`retry=False` + `client_order_id` probe). P1-5 extends, does not replace, this.
- **Webhook secret comparison is correct** — constant-time `hmac.compare_digest`, non-ASCII guard, generic 401 for unknown configs, secret stripped before persistence.
- **The live-trading gate** (env flag AND DB override, read at call time, re-asserted at adapter + stream) and **credential hygiene** (Fernet at rest, redacting `__repr__`, `BrokerCallAudit` stores no bodies/keys) are solid.
- **Daily-loss now uses broker equity vs `last_equity`** — the old lifetime-P&L lockout blocker is genuinely fixed; P0-1/P1-8 build on it.
- **Audit hash-chain construction** (single timestamp, `DjangoJSONEncoder` normalization, genesis handling, Postgres append-only + linkage triggers, nightly verifier) is sound; P1-9/P2-7 touch scrubbing and locking, not the chain.
- **Frontend:** access + MFA tokens are in-memory-only (only refresh regresses — P1-4); the refresh-interceptor concurrency (leader/queue + 15s timeout) is correct and well-tested; `@for` uses `track` everywhere; runtime config carries no secrets. The **admin HALT-PLATFORM modal**, **terms-gate**, **`ModalComponent` focus trap**, and **`TotpInputComponent`** are exemplary — reuse them (P0-4, P2-DESIGN-1/2).
- **Honest UX** — TradeStation disabled-with-explanation, honest "enable 2FA" empty states, "untested strategy" banner. Preserve this candor.

---

## 9. Sequencing, effort & risk

| Phase | Items | Est. effort | Notes |
|---|---|---|---|
| P0 | 4 | 2–4 days | Do first. P0-2 blocks P1-6. P0-4 can share the modal with P2-DESIGN-1. Each flips a fail-open to fail-closed — gate for live/paper per §3.5. |
| P1 | 10 | 5–8 days | P1-4 (token) touches the same flow as P2-9..11 (WS/refresh) — sequence P1-4 first, then the WS items. P1-5/P1-6 need migrations. |
| P2 | 22 | 8–12 days | 6a backend + 6b frontend are independent and parallelizable. 6c design is the largest; P2-DESIGN-5 (kit/token migration) is mechanical but broad — land screen-by-screen. |
| P3 | 14 | 2–3 days | One PR, batched. |

**Migrations introduced:** P1-5 (`Order.Status.NEEDS_RECONCILE`), possibly P0-1 (default `RiskProfile` provisioning is data, not schema), P2-5 (`unique(user, idempotency_key)` on `AlertMessage`). Run `makemigrations --check` per §3.2 and keep migrations reversible.

**Cross-cutting reminders:** any new setting helper must be named-imported into `prod.py`/`dev.py` (star-import `_` drop); any new request/worker hook must be mirrored into `wsgi.py` + `asgi.py` + `worker_process_init`; new frontend `${VARS}` must be added to the nginx envsubst allowlist. See §3.3.

**Regression-test principle (the project's own lesson):** a clean bill of health can be produced by the defect itself. Every item above ships with an **end-to-end assertion that fails before the fix**, not a component self-report. Prefer `-m pg` tests for anything touching locks/transactions (P0-1, P0-2, P1-5, P1-6, P2-7, P2-8).

---

## 10. Traceability (review finding → plan item)

`EXEC-1→P0-1 · EXEC-3→P0-2 · INFRA-1→P0-3 · TS-1→P0-4 · INFRA-3→P1-1 · EXEC-2→P1-2 · INFRA-2→P1-3 · FE-1→P1-4 · EXEC-6→P1-5 · EXEC-8→P1-6 · EXEC-10→P1-7 · EXEC-7→P1-8 · INFRA-7→P1-9 · TS-2→P1-10 · EXEC-4→P2-1 · EXEC-5→P2-2 · INFRA-4→P2-3 · INFRA-8→P2-4 · EXEC-9→P2-5 · INFRA-5→P2-6 · INFRA-6→P2-7 · INFRA-12→P2-8 · FE-2→P2-9 · FE-3→P2-10 · FE-4→P2-11 · FE-5→P2-12 · FE-6→P2-13 · FE-7→P2-14 · TS-3/TS-4/A11Y-6→P2-DESIGN-1 · A11Y-1/2/3→P2-DESIGN-2 · A11Y-4→P2-DESIGN-3 · A11Y-5→P2-DESIGN-4 · CON-1/CON-2/VH-1→P2-DESIGN-5 · UX-1→P2-DESIGN-6 · ST-1/ST-2/ST-3→P2-DESIGN-7 · CON-3/CON-4/CON-5/ST-4→P2-DESIGN-8 · EXEC-11→P3-1 · EXEC-12/INFRA-9→P3-2 · EXEC-13→P3-3 · EXEC-14→P3-4 · INFRA-10→P3-5 · INFRA-11→P3-6 · FE-8→P3-7 · FE-10→P3-8 · FE-9→P3-9 · FE-11→P3-10 · FE-12→P3-11 · FE-13→P3-12 · A11Y-8→P3-13 · A11Y-9→P3-14 · TS-5→ folded into P2-DESIGN-1/2`

_End of plan._
