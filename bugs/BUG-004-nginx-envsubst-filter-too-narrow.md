# BUG-004 — nginx envsubst allowlist drops 4 of 5 runtime-config vars (frontend Sentry has never worked)

| | |
|---|---|
| **Severity** | S2 — a shipped feature is silently non-functional in production |
| **Status** | FIXED (code) — pending live verification that frontend Sentry receives an event |
| **Area** | Frontend / Docker / runtime config |
| **Found** | 2026-07-11 (confirmed against the repo during M10 Section-B) |

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

## Follow-up

- [x] Widen `NGINX_ENVSUBST_FILTER`; fix the stale comment in the template
- [x] Add a CI guard so filter and template cannot drift apart again
- [x] Treat `${`-prefixed values as unset in the SPA
- [ ] Set `GRAFANA_URL` / `SENTRY_DSN` / `SENTRY_ENVIRONMENT` / `RELEASE` on the
      Railway **frontend** service (staging + production)
- [ ] Verify frontend Sentry actually receives an event — the only real proof
