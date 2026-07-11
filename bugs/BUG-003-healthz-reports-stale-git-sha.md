# BUG-003 — `/healthz` reports a stale commit SHA

| | |
|---|---|
| **Severity** | S3 — misleading deploy provenance; wrong Sentry `release` tagging |
| **Status** | OPEN |
| **Area** | Deploy / provenance |
| **Found** | 2026-07-11, while confirming the BUG-001 fix had rolled out |

## Symptom

After commit `dac9643` was pushed to `main` and Railway reported the deployment
as **Active / Deployment successful / Deployed via GitHub — branch `main`**, the
backend still reported the *previous* commit:

```
$ curl https://backend-production-f3e8.up.railway.app/healthz
{"status": "ok", "version": "2c1207b"}     # expected: dac9643
```

This is not a rollout failure — the new code was demonstrably running (traces
started flowing, which only the `dac9643` fix enables). Only the reported SHA is
wrong.

## Impact

1. `/healthz` cannot be trusted to tell you which commit is live — it actively
   misleads during incident triage, which is the exact moment you rely on it.
   It cost real time during the BUG-001 investigation: it looked like the deploy
   hadn't landed.
2. `sentry_sdk.init(release=GIT_SHA)` — Sentry release health is tagged with the
   **wrong commit**, so errors group against a stale release.
3. **Frontend sourcemaps never resolve.** Confirmed 2026-07-11 while fixing
   BUG-004: on the `frontend` service, `RELEASE="${{RAILWAY_GIT_COMMIT_SHA}}"`
   resolves to the **empty string** in *both* environments, so the SPA reports
   `release: ''`. CI uploads sourcemaps keyed to `${GITHUB_SHA}`
   (`sentry-cli sourcemaps upload --release "$GITHUB_SHA"`), and Sentry matches
   sourcemaps by release — with no release on the event, they can never match.

   So frontend stack traces stay minified, and the entire `SENTRY_AUTH_TOKEN` +
   sourcemap-upload setup (C2) currently buys nothing. This makes BUG-003 more
   than a cosmetic annoyance.

## Recommended fix (strengthened by the above)

Stop depending on `RAILWAY_GIT_COMMIT_SHA` entirely. Bake the SHA at **build**
time, which is deterministic and works for every service and every deploy method:

```dockerfile
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
```

…passed by the build, and used for the backend's `GIT_SHA` *and* the frontend's
`RELEASE`, so `/healthz`, Sentry release health, and sourcemap matching all agree
on one value.

## Key new evidence: staging is CORRECT, production is not

Later the same day, commit `3fe78bb` was pushed and deployed to both environments:

```
staging    /healthz -> {"status":"ok","version":"3fe78bb"}   # correct
production /healthz -> {"status":"ok","version":"2c1207b"}   # stale
```

Same code, same resolution logic, same deploy method (GitHub → Railway) — but only
production reports a stale SHA. That **rules out the code path** and points squarely
at production's environment: either a stale explicit `GIT_SHA` override on the
production backend service, or `RAILWAY_GIT_COMMIT_SHA` not being refreshed there.
Start by diffing the two services' resolved env.

## Root cause (suspected — needs confirmation)

`backend/config/settings/base.py` resolves the SHA as:

1. `git rev-parse --short HEAD` — fails inside the image (no `.git`)
2. `GIT_SHA` env var
3. `RAILWAY_GIT_COMMIT_SHA[:7]`
4. `"unknown"`

Since the value is a real, *previous* commit rather than `"unknown"`, step 2 or 3
returned a stale value. Most likely `RAILWAY_GIT_COMMIT_SHA` was not refreshed for
this deployment. There is a known related quirk on this project: **Railway CLI
(`railway up`) deploys do not inject `RAILWAY_GIT_COMMIT_SHA` at all**, so the
variable can be left holding whatever a previous deploy set.

## Next steps

- [ ] Inspect the backend service's resolved env in Railway: is `GIT_SHA`
      explicitly set (an override that has gone stale), and what is
      `RAILWAY_GIT_COMMIT_SHA` on the current deployment?
- [ ] If `GIT_SHA` is an explicit stale override → delete it.
- [ ] If `RAILWAY_GIT_COMMIT_SHA` is itself stale → stop depending on it. Bake the
      SHA at build time instead, e.g. a Docker `ARG GIT_SHA` passed by the build
      and written to `ENV GIT_SHA`, which is deterministic and survives any
      deploy method.
- [ ] Add a smoke assertion that `/healthz.version` matches the commit being
      deployed, so provenance drift fails loudly instead of silently.
