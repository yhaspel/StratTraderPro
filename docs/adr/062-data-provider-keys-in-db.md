# ADR-062 — Instance data-provider keys move to the database, staff-editable in Settings, env vars as fallback

**Date:** 2026-08-01
**Status:** Accepted
**Milestone:** post-M11 operability fix (no milestone of its own); unlocks M16 — Strategy Screener
**Reference:** ADR-061 (FMP/FRED as the vendors); `apps.regime.tasks.compute_features_daily`
(the pipeline that silently no-ops without keys); the 2026-07-29 bug-fix run's deploy
step B, which required setting `FMP_API_KEY`/`FRED_API_KEY` on three Railway services
by hand; M02's Fernet KEK pattern (`apps.users.mfa`), reused by brokers and webhooks.

## Context

Since M06, the FMP and FRED API keys existed **only as env vars** (`FMP_API_KEY`,
`FRED_API_KEY` in `config/settings/base.py`, empty by default). Nothing in the
product surfaced where to set them: not Settings, not the admin portal. The
consequences, observed live on 2026-07-29:

- The Market Regime card was empty forever because the nightly pipeline
  deliberately no-ops without both keys — and the only fix was a Railway
  console session touching **three** services (web, Celery worker, beat) plus a
  redeploy. Setting them on the web service alone is a trap the handoff doc had
  to warn about explicitly.
- The operator (a staff user of the product) went looking for the keys **in the
  UI** — under admin and Settings — and correctly concluded they didn't exist.
- The upcoming strategy screener (M16) gates on an FMP key being configured,
  which makes "is FMP configured?" a product-level question, not a deploy-time
  one.

Also relevant: these keys are **instance-scoped by nature** (decided 2026-08-01
with Yuval) — the regime pipeline computes one market-wide observation for the
whole deployment, and a self-hosted instance runs on one vendor subscription.
Per-user keys were considered and rejected (below).

## Decision

### 1. One `DataProviderKey` row per provider, Fernet-wrapped with the platform KEK

`apps/marketdata/models.py::DataProviderKey` — `provider` (unique; `FMP` |
`FRED`), `key_encrypted` (`BinaryField`, wrapped by the same `FERNET_KEK` used
for MFA/webhook/broker secrets via `apps.users.mfa._fernet`), a display-only
`key_hint` (last 4 chars, empty for short keys), `updated_by`/`updated_at`.
Plaintext never leaves `apps/marketdata/keys.py` (the brokers-services rule).

### 2. Resolution order: UI-stored key → env var → unconfigured

`apps.marketdata.keys.resolve_key(provider)` is the **single choke point**:

1. `DataProviderKey` row (set via the UI) — decrypted;
2. `settings.FMP_API_KEY` / `settings.FRED_API_KEY` (env) — unchanged semantics;
3. `""` — callers treat falsy as "not configured".

`FMPClient()`/`FREDClient()` default their key through `resolve_key`, so every
consumer — the regime pipeline's `_daily_source_configured()` gate,
`gather_daily_inputs`, `backfill_bars`, the M16 screener — inherits the rule
with no per-callsite changes. The DB read is defensive: on `DatabaseError`
(fresh install mid-migrate) it degrades to the env fallback instead of crashing
a worker boot.

**Why DB-over-env precedence:** a key saved in the UI is the operator's most
recent, most deliberate act; and the DB is shared by every service, which is
exactly what kills the "set it on all three services + redeploy" trap — a key
saved once takes effect on web, worker and beat immediately.

### 3. Staff-only writes, validated against the vendor before persisting

`/api/v1/marketdata/keys/` (GET status; MFA-enforced like the rest of the
trading surface) and `/api/v1/marketdata/keys/{provider}/` (PUT/DELETE,
`IsAdminAndMFAEnforced`). PUT re-uses the brokers AC-04-6 rule: the key is
tested live against the vendor (FMP `/quote`, FRED `series/observations`;
injectable HTTP, no live calls in CI) and **a bad key never creates a row**
(`INVALID_API_KEY` 400 / `PROVIDER_UNREACHABLE` 502; a 429 is accepted — being
rate-limited proves the key authenticated). Responses carry status + last-4
hint only — the key is write-only and never echoed. Set/remove emit audit
events (`marketdata.provider_key_set` / `…_removed`) with no key material.

### 4. Frontend: Settings → Data Providers

`/settings/data-providers` (reachable from the user menu, the regime card's
empty state, and the `market-regime-setup` guide): status per provider
(Configured / Configured via server environment / Not configured), staff-only
validate-&-save + remove, non-staff see status plus "ask your administrator".
The regime empty state and Admin → Health hints now point here first, env vars
second.

## Consequences

**Positive:**

- Pasting two keys into Settings lights up the regime pipeline with zero
  Railway changes and zero redeploys; the M16 screener gets a ready-made
  "is FMP configured?" signal (`resolve_key` / the status endpoint).
- Env-var deployments keep working untouched (local `.env`, Railway variables)
  — the change is purely additive for existing self-hosters.
- Key handling stays on the one platform KEK + write-only-serializer pattern;
  a KEK rotation covers these rows exactly like MFA/broker secrets.

**Negative / honest limits:**

- Two sources of truth exist by design; the UI mitigates by always naming the
  effective source (`ui` vs `env`). An operator who sets both must know the DB
  wins — the Settings page, the guide, and `base.py` comments all say so.
- Writes require a staff account with MFA. On an instance whose owner has not
  yet promoted themselves (`manage.py promote_user … --staff`), the page is
  read-only until they do — deliberate: instance-wide credentials are an
  admin act.
- The regime pipeline's "configured" check now costs one tiny indexed DB read
  in `/regime/model/` and Admin → Health. Negligible at this scale.

## Alternatives considered

1. **Per-user keys (each user brings their own).** Rejected 2026-08-01: the
   regime pipeline is instance-global — whose key would fund it? — and a
   self-hosted instance shares one subscription. Item-level user features
   (screener) still work: they use the instance key.
2. **Keep env-only and just document it better.** Rejected: leaves the
   three-services trap and the redeploy round-trip; the operator explicitly
   asked for keys settable in the UI.
3. **Store keys in the admin portal's `FeatureFlag`-style table, admin-portal
   URL space.** Rejected: flags are booleans with a registry contract; keys are
   secrets needing encryption + write-only handling, and the user's stated home
   for them is Settings. The admin portal keeps its read-only health signal.
4. **Railway API integration (write env vars from the app).** Rejected:
   platform-specific, needs a Railway token with project-write scope (a bigger
   secret than the ones being managed), still requires redeploys.

## See also

- ADR-061 — the vendors these keys unlock; its §4 vendor-change gate still governs new FMP endpoints (see M16's ADR-063)
- `backend/apps/marketdata/keys.py` — storage, resolution, validation
- `backend/apps/marketdata/views.py` / `urls.py` — the keys API
- `frontend/src/app/features/settings/data-providers/` — the Settings page
- `frontend/src/assets/guides/market-regime-setup.html` — the operator guide, updated
- `docs/runbooks/mfa-kek-rotation.md` — rotation covers these rows too
