# BUG-003 — Frontend `release` is empty (was: "`/healthz` reports a stale commit SHA")

| | |
|---|---|
| **Severity** | S3 — frontend sourcemaps can never resolve, so the whole sourcemap setup buys nothing |
| **Status** | FIXED — pending live verification |
| **Area** | Deploy / provenance |
| **Found** | 2026-07-11 |

## ⚠️ The original report was wrong. Correcting the record.

This bug was originally filed as *"`/healthz` reports a stale commit SHA"*, based on
production returning `2c1207b` after `dac9643` had been deployed.

**That was a measurement error, not a bug.** The reading was taken **during a
rollout** — the request hit the old container before the new one took over. Once
both environments settled, they report the deployed commit correctly:

```
expected deployed commit: 6a842fe
backend-staging    -> {"status": "ok", "version": "6a842fe"}   ✅
backend-production -> {"status": "ok", "version": "6a842fe"}   ✅
```

`RAILWAY_GIT_COMMIT_SHA` **does** exist in the container environment, and
`/healthz` + `sentry_sdk.init(release=GIT_SHA)` resolve it correctly. There is
nothing to fix on the backend.

*(This is the second time a mid-rollout read produced a false conclusion — the
same thing initially made the OTel fix look like it hadn't worked. Lesson: after a
deploy, confirm the rollout has completed **before** trusting anything you measure.)*

## The real bug (what's left)

The frontend SPA reports **`release: ''`** in both environments:

```js
window.STP_CONFIG = { ..., sentryEnvironment: 'staging', release: '' };
```

### Root cause

Two different mechanisms, easy to conflate:

| Mechanism | Sees `RAILWAY_GIT_COMMIT_SHA`? |
|---|---|
| The **container environment** at runtime (what Django's `env()` and nginx's `envsubst` read) | ✅ **yes** — this is why `/healthz` works |
| Railway's **`${{...}}` variable-reference** templating (used in the service-variable UI) | ❌ **no** — resolves to the empty string |

The frontend's `RELEASE` was set to `"${{RAILWAY_GIT_COMMIT_SHA}}"`, i.e. via the
reference syntax — which silently resolved to `""`. Railway does not list
`RAILWAY_GIT_COMMIT_SHA` among the 8 variables it exposes to the reference system
(`RAILWAY_ENVIRONMENT_ID/NAME`, `RAILWAY_PRIVATE/PUBLIC_DOMAIN`,
`RAILWAY_PROJECT_ID/NAME`, `RAILWAY_SERVICE_ID/NAME`), even though it *is* present
in the container env.

### Why it matters

CI uploads frontend sourcemaps keyed to the commit:

```
npx @sentry/cli sourcemaps upload --release "${GITHUB_SHA}" dist
```

Sentry matches sourcemaps to events **by release**. With `release: ''` on every
event, they can never match — so frontend stack traces stay minified and the whole
`SENTRY_AUTH_TOKEN` + sourcemap-upload setup (C2) delivers nothing.

## Fix

Populate `RELEASE` from the container environment instead of the reference syntax.

The official nginx image's entrypoint runs the files in `/docker-entrypoint.d/` in
order, and — importantly — **`*.envsh` files are _sourced_** (so their `export`s
persist) while `*.sh` files run in a subshell. `20-envsubst-on-templates.sh` is
what performs the substitution, so a sourced script numbered below it can set
`RELEASE` before the template is rendered:

`docker/15-release-default.envsh` → `/docker-entrypoint.d/15-release-default.envsh`

```sh
# Default RELEASE to the platform's commit SHA when not explicitly provided.
if [ -z "${RELEASE:-}" ] && [ -n "${RAILWAY_GIT_COMMIT_SHA:-}" ]; then
  export RELEASE="$RAILWAY_GIT_COMMIT_SHA"
fi
```

This keeps the nginx template platform-agnostic (it still just emits `${RELEASE}`),
reads the SHA from the one place that actually has it, and leaves an explicitly-set
`RELEASE` untouched.

## Verification

- [ ] `GET /config.js` reports a non-empty `release` matching the deployed commit
- [ ] A frontend Sentry event carries that release
- [ ] Sourcemaps resolve (stack trace shows original TS, not minified output)

## Note on `GIT_SHA` resolution (unchanged, and fine)

`backend/config/settings/base.py` resolves in order: `git rev-parse` (fails in the
image — `.dockerignore` excludes `.git/`), then `GIT_SHA`, then
`RAILWAY_GIT_COMMIT_SHA[:7]`, then `"unknown"`. Step 3 is what fires in production,
and it works.
