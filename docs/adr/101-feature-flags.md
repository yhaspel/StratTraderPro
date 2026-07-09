# ADR-101 — DB-backed feature flags with Redis + process-local cache, fail-open to env

**Date:** 2026-07-10
**Status:** Accepted
**Milestone:** M10 — Admin Portal, Audit Log & Observability
**Reference:** `project-plan/10-admin-audit-observability.md` §6.4, §15; AC-10-5, AC-10-6;
`apps/admin_portal/flags.py`; `config/settings/base.py` (`FEATURE_FLAGS_REGISTRY`);
ADR-100 (the audit chain that records every flip); the master §15 rollback flags

## Context

Every milestone since M02 shipped its own env-var feature flag
(`MFA_ENABLED`, `WEBHOOK_V1_ENABLED`, `ENABLE_LIVE_TRADING`, `SIZING_V1_ENABLED`,
…). Flipping any of them meant editing a Railway env var and **redeploying** —
minutes of latency, and no in-app record of who flipped what or when. M10's admin
portal needs to toggle rollback flags **live** (§15), audited, without a deploy,
while keeping the existing env-var defaults as the source of truth and without
letting a runtime override *mask* a config change.

The tension is: a live DB override is the feature we want, but the env var must
stay authoritative for the flags that must **never** be flippable at runtime
(the security/safety gates), and a cache must never hide the true current state.

## Decision

### 1. A DB override layered over the env default, cached at two tiers

Resolution order for a mutable flag (`apps/admin_portal/flags.is_enabled(name)`):

1. **30 s process-local cache** — an in-process dict of `(override, expiry)`
   keyed by flag name, expiry compared against a monotonic clock. Caches **only
   the override state**, not the resolved boolean (see §3).
2. **60 s Redis cache** (Django cache backend, key `flag:<name>`), with a
   `"__none__"` sentinel meaning "no DB override exists" so a missing override is
   itself cacheable.
3. **DB row** — `FeatureFlag.objects.filter(name=name).values_list("enabled").first()`,
   `None` if absent.
4. **Live env setting** — `getattr(settings, name, registry_default)`, evaluated
   **at call time**.

`set_flag(name, enabled, *, actor, request, note)` is the single write path. It:
writes/updates the `FeatureFlag` row (`update_or_create`, recording `updated_by`
and `note`), sets the Redis key, **busts the process-local cache**, emits a
`flag.flipped` audit row via `emit()` (with before/after state — ADR-100), and
increments `feature_flag_flips_total{flag}`. Immutable flags raise `FlagImmutable`
→ the admin endpoint returns `400 FLAG_IMMUTABLE`; unknown flags → `404 FLAG_UNKNOWN`.

The `FeatureFlag` model (`admin_feature_flag` table) is intentionally thin:
`name` (unique), `enabled`, `updated_by` (FK, SET_NULL), `updated_at` (auto),
`note`. Absence of a row = no override = fall through to env.

### 2. One registry, three tiers of mutability

`settings.FEATURE_FLAGS_REGISTRY` (in `config/settings/base.py`) is the single
declaration — **18 flags + `ADMIN_PORTAL_ENABLED`**. Each entry carries its env
default, a description, and two booleans: `mutable` and `dangerous`. Three tiers:

- **Immutable (env-only, `mutable=False`)** — `MFA_ENABLED`,
  `KILL_SWITCHES_ENABLED`, `FILLS_INLINE`, `ADMIN_PORTAL_ENABLED`. These
  **short-circuit directly to the env setting** in `is_enabled()` and can never be
  flipped at runtime (`set_flag` raises `FlagImmutable`). They are the security /
  safety / self-referential gates: you must not be able to turn off MFA or the
  kill-switch engine, or disable the admin portal *through* the admin portal, from
  a DB row.
- **Dangerous (`dangerous=True`)** — `ENABLE_LIVE_TRADING`,
  `SENTIMENT_FAKE_SCORERS`, `SIZING_V1_ENABLED`. Mutable, but the admin **UI**
  forces a **typed-confirmation** before flipping. The server still MFA-gates every
  flip regardless of the UI; `dangerous` is a UI affordance layered on top of the
  server gate, not a substitute for it.
- **Ordinary (mutable, not dangerous)** — the rest (`GOOGLE_OAUTH_ENABLED`,
  `STRATEGIES_V1_ENABLED`, `WEBHOOK_V1_ENABLED`, `BROKER_*`, `ENABLE_REGIME_UI`,
  `SENTIMENT_*`, `BACKTEST_ENABLED`, …) — flippable live with MFA + audit.

### 3. Cache the override state ONLY — never the resolved value

This is the subtle one. The cache stores the **override state**
(`True`/`False`/`no-override`), **not** the resolved boolean. When there is no DB
override, `is_enabled()` resolves the no-override case from **live settings on
every call**. Consequence: changing the env var (a deploy, or `@override_settings`
in a test) is reflected **immediately** even for a flag that has recently been
read, because the cache only ever said "no override" — it never cached the
env-derived answer. If we cached the resolved boolean instead, an env change would
be masked for up to 60 s (or 30 s locally) after the last read, which is exactly
the kind of silent staleness that makes a rollback flag untrustworthy in an
incident.

### 4. Fail-open to the env default

Every cache/DB read is best-effort. A Redis outage or a DB error is caught,
logged, and treated as "no override" → the flag resolves to its **env default**.
The system never fails *closed* on a flag-store outage: if the override
infrastructure is down, behavior falls back to exactly what a fresh deploy with no
overrides would do. For the safety flags this is doubly safe — they never consult
the store at all (§2).

### 5. Why this lives in `apps/admin_portal`, not a new `apps/core`

The flag machinery is small (one model, one module) and its only non-settings
consumer is the admin portal that flips flags. Introducing an `apps/core`
just to house `flags.py` would create a new cross-cutting app that every other app
imports, inverting the dependency direction for no benefit — and there is **no
`apps/core` app** in this codebase, by deliberate omission. The registry itself
lives in `settings` (it is configuration); the resolve/flip logic lives with its
owner, the admin portal. Any app that needs to read a flag imports
`apps.admin_portal.flags.is_enabled` — a leaf import, not a framework.

## Consequences

- **Live, audited, deploy-free flag flips** for the ordinary and dangerous tiers,
  with `feature_flag_flips_total{flag}` on the dashboard and a `flag.flipped`
  chained audit row per flip (who/before/after/note).
- **Env stays authoritative and un-maskable.** The four safety flags are env-only;
  every other flag's *default* is the env, and an env change is never hidden by the
  cache because only the override state is cached.
- **Graceful under a store outage** — fail-open to env; the safety flags don't
  depend on the store at all.

**Honest limits:**

- **Up to ~60 s propagation for a flipped override across processes.** A flip busts
  the local cache in the flipping process and writes Redis; other gunicorn/worker
  processes pick it up when their 30 s local cache next expires and re-reads Redis.
  Acceptable for rollback flags; not a real-time kill switch (that is the L0–L3
  kill-switch engine, ADR-081, which is env-immutable and consulted per request).
- **Redis and the DB can momentarily disagree** after a flip if the DB write
  succeeds and the Redis set fails (or vice versa) — but the DB is authoritative
  and the local cache TTL bounds the window; the next resolve reconciles.

## Alternatives considered

1. **Pure env vars (status quo).** Rejected: every flip is a redeploy, and there's
   no in-app who/when record for a rollback action.
2. **DB-only, no cache.** Rejected: a DB round-trip on every flag read on the hot
   path (webhook ingest, order placement) is unacceptable; the caches exist to keep
   flag reads effectively free.
3. **Cache the resolved boolean.** Rejected: masks env/deploy changes for up to the
   TTL — the failure mode that makes a rollback flag lie to you during an incident.
   We cache override state only.
4. **A `django-waffle`-style third-party flag app.** Rejected for MVP: heavier
   model, its own admin, and its own semantics for "everyone/percent/user" we don't
   need — we need a boolean with an env default and an audit hook, which is ~200
   lines against our existing `emit()` and settings.
5. **A new `apps/core` to host flags.** Rejected: no such app exists and adding one
   inverts dependencies for a leaf utility; flags live with their owner.

## See also

- `backend/apps/admin_portal/flags.py` — `is_enabled` / `set_flag` / the caches
- `backend/apps/admin_portal/models.py` — `FeatureFlag`
- `backend/config/settings/base.py` — `FEATURE_FLAGS_REGISTRY` (the 18 + admin gate)
- ADR-100 — the `flag.flipped` audit event this emits
- ADR-102 — the observability topology (`feature_flag_flips_total` scrape)
- `docs/runbooks/platform-halt.md` — the admin-portal actions that read these gates
