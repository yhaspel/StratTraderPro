# BUG-007 — "Frontend — Lint & Test" runs neither lint nor tests

| | |
|---|---|
| **Severity** | S2 — the entire frontend test suite is dead weight; no frontend regression can be caught by CI |
| **Status** | OPEN |
| **Area** | CI |
| **Found** | 2026-07-11, while adding a karma spec for the BUG-004 fix and checking it would actually run |

## Symptom

The CI job is **named** `Frontend — Lint & Test`. Its steps are:

1. checkout
2. Set up Node 20
3. Enable pnpm
4. Cache pnpm store
5. `cd frontend && pnpm install --frozen-lockfile`
6. `cd frontend && pnpm build`
7. Upload source maps to Sentry

There is **no lint step and no test step.** `pnpm test:ci`
(`ng test --no-watch --browsers=ChromeHeadless --code-coverage`) is defined in
`frontend/package.json` and never invoked.

## Impact

Every frontend spec in the repo has **never executed in CI**:

```
src/app/abstraction/stores/{auth,admin,strategies,backtest}.store.spec.ts
src/app/abstraction/facades/{admin,backtest,...}.facade.spec.ts
... and the rest
```

They compile (`tsc -p tsconfig.spec.json` passes), but nothing runs them. A green
build says nothing about frontend behaviour. This is the same theme as BUG-001 and
BUG-004: **a control that is present, reported healthy, and completely inert.**

It also means the karma spec added with the BUG-004 fix
(`config.service.spec.ts`, which pins the `${SENTRY_DSN}`-literal branch) does not
yet run in CI. BUG-004's *primary* guard is the static check
(`scripts/check_envsubst_filter.py`, wired into CI and verified), so BUG-004 is
genuinely covered — but the SPA-side defensive behaviour is not yet enforced.

`ng lint` is separately unusable: the Angular project has **no `lint` target**
configured (`ng lint` → *"Cannot find 'lint' target for the specified project"*),
so the job's "Lint" half was never real either.

## Why this wasn't fixed in the same commit as BUG-004

Turning the test step on is a one-line change, but it is **not** a safe one-liner:
these specs have never run in CI, so their current state is unknown — they may
have rotted. Enabling them could turn `main` red for reasons unrelated to BUG-004.
It deserves its own change, run first on a branch so the true state of the suite
is observed rather than assumed.

I could not run karma locally to find out: the sandbox has no Chrome and no root
to install one, and `node_modules` carries a darwin-arm64 esbuild binary
(installed on the developer's Mac), so `ng build`/`ng test` cannot execute on
Linux either.

## Fix

1. Add a test step to the frontend job:
   ```yaml
   - name: Test (karma, headless)
     run: cd frontend && pnpm test:ci
   ```
   GitHub's `ubuntu-latest` runners ship Chrome, so `ChromeHeadless` works.
2. Run it on a branch **first**. Expect failures; fix or quarantine them
   explicitly (do not blanket-skip).
3. Add a real `lint` target (`ng add angular-eslint`) and a lint step, or rename
   the job to what it actually does. A job named "Lint & Test" that does neither
   is worse than no job, because it manufactures false confidence.

## Follow-up

- [ ] Enable `pnpm test:ci` in CI (branch first, observe the true pass/fail state)
- [ ] Add an `eslint` target + lint step, or rename the job honestly
- [ ] Once green, confirm `config.service.spec.ts` (BUG-004 cover) runs
