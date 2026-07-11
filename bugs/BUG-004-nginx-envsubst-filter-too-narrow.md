# BUG-004 — nginx envsubst allowlist drops 4 of 5 runtime-config vars (frontend Sentry has never worked)

| | |
|---|---|
| **Severity** | S2 — a shipped feature is silently non-functional in production |
| **Status** | **FIXED & VERIFIED LIVE** (2026-07-11) — frontend Sentry now reports (`STRATTRADERPRO-2`) |
| **Area** | Frontend / Docker / runtime config |
| **Found** | 2026-07-11 (confirmed against the repo during M10 Section-B) |

## ⚠️ Correction to the original diagnosis (read this first)

The original write-up claimed the Railway-deployed SPA was being served
`sentryDsn: '${SENTRY_DSN}'`. **On Railway that was not what was happening.**

Inspecting the live `frontend` service revealed a **service-level
`NGINX_ENVSUBST_FILTER` variable**, which *overrides the Dockerfile `ENV`*, and it
already carried the wide filter:

```
NGINX_ENVSUBST_FILTER="BACKEND_URL|GRAFANA_URL|SENTRY_DSN|SENTRY_ENVIRONMENT|RELEASE"
SENTRY_DSN=""          <-- the actual cause on Railway
RELEASE=""
```

So on Railway the vars *were* substituted — into the **empty string**, because
`SENTRY_DSN` was never set (it couldn't be: no Sentry project existed until
2026-07-11). Frontend Sentry was still dead, just by a different mechanism:
**empty DSN**, not a literal placeholder.

The literal-`${...}` failure is real, but it applies to the **image default** —
docker-compose, local runs, and any new environment that lacks the service-level
override. Both mechanisms had the same outcome (a Sentry SDK that initialises and
reports nothing), and both are fixed here.

**Consequence worth keeping:** because a Railway *service variable* overrides the
Dockerfile, the CI guard protects the **image**, not Railway. Railway can still
drift on its own. See the follow-up below.

## Symptom

The SPA is served a runtime config in which four of five values are the **literal
template strings**, not their values. `GET /config.js` returns something like:

```js
window.STP_CONFIG = {
  backendUrl: 'https://backend-production-….up.railway.app',   // substituted
  grafanaUrl: '${GRAFANA_URL}',                                // literal!
  sentryDsn: '${SENTRY_DSN}',                                  // literal!
  sentryEnvironment: '${SENTRY_ENVIRONMENT}',                  // literal!
  release: '${RELEASE}'                                        // literal!
};
```

**Consequence: frontend Sentry has never reported a single event.** `Sentry.init()`
is called with `dsn: '${SENTRY_DSN}'`, which is not a valid DSN. Grafana deep
links and release tagging are likewise dead.

## Root cause

`docker/nginx.conf.template` emits five variables:

```
${BACKEND_URL} ${GRAFANA_URL} ${RELEASE} ${SENTRY_DSN} ${SENTRY_ENVIRONMENT}
```

but `docker/frontend.Dockerfile:23` restricts substitution to one:

```dockerfile
ENV NGINX_ENVSUBST_FILTER='^BACKEND_URL$' \
```

`NGINX_ENVSUBST_FILTER` is an **anchored allowlist**. Anything not matching it is
left untouched, so the raw `${...}` text is shipped to the browser. The filter
exists for a good reason — without it, envsubst would also clobber nginx's own
`$uri` / `$host` — but it was never widened when M10 added the four new vars.

## Why nothing caught it

- The karma specs stub `window.STP_CONFIG`, so they never exercise the served
  `/config.js`.
- Nothing asserts the served config is free of `${` placeholders.
- An invalid DSN makes the Sentry SDK a silent no-op rather than throwing.

Same family as BUG-001/BUG-002: **initialises fine, does nothing.**

## Fix (applied)

1. **Widened the allowlist** to every variable the template emits
   (`docker/frontend.Dockerfile`):

   ```dockerfile
   ENV NGINX_ENVSUBST_FILTER='^(BACKEND_URL|GRAFANA_URL|SENTRY_DSN|SENTRY_ENVIRONMENT|RELEASE)$'
   ```

2. **Static CI guard** — `scripts/check_envsubst_filter.py` cross-checks the filter
   against the `${VAR}`s in `docker/nginx.conf.template` and fails the build on drift
   in either direction. Wired in as the `Guard — nginx envsubst filter in sync` job.

   This is the load-bearing guard: it is static (milliseconds, no Docker) and it
   covers the **production artifact** — which the E2E smoke does not, because the
   smoke runs `ng serve` and never builds the nginx image. That gap is exactly why
   this shipped.

   Verified against the original filter: it fails, naming precisely
   `GRAFANA_URL, RELEASE, SENTRY_DSN, SENTRY_ENVIRONMENT`.

   *(The guard's own first draft was wrong — it flagged the example `${FOO}`
   placeholders inside the template's own comments. It now strips comment lines.
   Guards get tested against the real bug, not trusted.)*

3. **Defense in depth** — `frontend/src/app/core/runtime-config.ts` adds
   `runtimeValue()`, which treats a value that is empty **or** still starts with
   `${` as unset. Used by `ConfigService` and by `main.ts` (bootstrap runs before
   DI exists, hence a plain helper rather than the service). A future filter
   regression now degrades to "feature off" instead of "Sentry initialised with a
   junk DSN".

4. **Spec** — `config.service.spec.ts` pins three branches: value set, value unset,
   value still a `${...}` placeholder.

> ⚠️ That spec does **not yet run in CI** — see **BUG-007**: the `Frontend — Lint &
> Test` job runs neither lint nor tests, so *no* frontend spec has ever executed.
> BUG-004 is still genuinely guarded in CI, by the static check in (2).

M12 additionally introduces `BETA_FEEDBACK_URL` and `TRADESTATION_ENABLED`; the
guard will now *force* those into the filter when the template gains them, instead
of letting them silently ship as literals.

## Live verification (2026-07-11)

Set `SENTRY_DSN="${{shared.SENTRY_DSN}}"` on the Railway **frontend** service in
both environments and redeployed. The served config is now clean:

```js
// GET https://frontend-staging-9011.up.railway.app/config.js
window.STP_CONFIG = {
  backendUrl: 'https://backend-staging-4b6d.up.railway.app',
  grafanaUrl: 'https://yuval3000.grafana.net',
  sentryDsn: 'https://eb4bd…@o4511716412489728.ingest.us.sentry.io/4511716419305472',
  sentryEnvironment: 'staging',
  release: ''
};
```

No `${...}` placeholders, real DSN — same for production.

Then threw an **uncaught** error in the live SPA (so it goes through Sentry's
global handler, not an API call). Sentry received it:

> **`STRATTRADERPRO-2` — Error: "BUG-004 verification: frontend Sentry live check"** —
> Unhandled, 1 event, 1 user.

**That is the first frontend Sentry event this project has ever recorded.**

## Loose end found during verification: `release` is empty

`RELEASE="${{RAILWAY_GIT_COMMIT_SHA}}"` resolves to the **empty string** on the
frontend service, in both environments — so the SPA reports `release: ''`.

This matters beyond cosmetics: CI uploads frontend sourcemaps keyed to
`${GITHUB_SHA}` (`sentry-cli sourcemaps upload --release "$GITHUB_SHA"`). With no
release on the event, **Sentry can never match them**, so frontend stack traces
stay minified and the whole `SENTRY_AUTH_TOKEN`/sourcemap setup (C2) buys nothing.

This is the same root cause as **BUG-003** (Railway's git-SHA injection is
unreliable) and should be fixed there — bake the SHA at build time via a Docker
`ARG`/`ENV` rather than depending on `RAILWAY_GIT_COMMIT_SHA`.

## Follow-up

- [x] Widen `NGINX_ENVSUBST_FILTER`; fix the stale comment in the template
- [x] Add a CI guard so filter and template cannot drift apart again
- [x] Treat `${`-prefixed values as unset in the SPA
- [x] Set `SENTRY_DSN` on the Railway frontend service (staging + production)
- [x] Verify frontend Sentry actually receives an event ✅
- [ ] **Remove the service-level `NGINX_ENVSUBST_FILTER` override** from both
      frontend services once the fixed image is deployed, so the CI-guarded
      Dockerfile `ENV` is the single source of truth. While the override exists,
      the CI guard does not protect Railway.
- [ ] Fix `release: ''` (see BUG-003) so sourcemaps actually resolve.
