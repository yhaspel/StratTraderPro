# BUG-004 — nginx envsubst allowlist drops 4 of 5 runtime-config vars (frontend Sentry has never worked)

| | |
|---|---|
| **Severity** | S2 — a shipped feature is silently non-functional in production |
| **Status** | OPEN |
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

## Fix (proposed)

Widen the allowlist to every variable the template actually emits:

```dockerfile
ENV NGINX_ENVSUBST_FILTER='^(BACKEND_URL|GRAFANA_URL|SENTRY_DSN|SENTRY_ENVIRONMENT|RELEASE)$' \
```

and set those four variables on the Railway **frontend** service in both
environments. Note M12 additionally introduces `BETA_FEEDBACK_URL` and
`TRADESTATION_ENABLED`, so the filter should be widened to all seven at that
point — see `project-plan/12-beta-and-signoff.md`, which already sanctions this
fix and calls the current state a "latent M10 defect".

Defense in depth (already specified by M12): every runtime-config consumer should
treat a value that is empty **or starts with `${`** as unset.

## Tests to add with the fix

- A container/e2e assertion that `GET /config.js` contains **no** `${` substring.
- A frontend unit test that a `${`-prefixed DSN is treated as "Sentry disabled".

## Follow-up

- [ ] Widen `NGINX_ENVSUBST_FILTER` and fix the stale comment in
      `docker/nginx.conf.template` (which already documents the *intended* wider
      filter, so template and Dockerfile currently disagree).
- [ ] Set `GRAFANA_URL` / `SENTRY_DSN` / `SENTRY_ENVIRONMENT` / `RELEASE` on the
      Railway frontend service (staging + production).
- [ ] Re-verify frontend Sentry actually receives an event.
