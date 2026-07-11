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
3. Same `GIT_SHA` feeds the frontend `RELEASE` runtime var (see BUG-004).

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
