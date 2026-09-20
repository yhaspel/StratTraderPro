# MFA skew-diagnostics — execution report

Branch `fix/mfa-totp-skew-diagnostics` (base `1dcdd70` = `origin/main` at run start).
**Final status: BLOCKED before merge, PR #76 left OPEN — not deployed.** Phases 0–4 completed (branch landed,
invariant audit + full gauntlet + adversarial review all clean, docs committed, PR opened, CI run to
completion). Both `Backend — Lint & Test` and `Frontend — Build & Test` came back red, but in each case the
*only* failing step is a dependency-audit gate (`pip-audit` / `osv-scanner`) flagging advisories against
package versions this diff does not touch — confirmed root-caused entirely outside the diff (see Section B).
Per this prompt's own explicit rule ("Red outside the diff → leave open, report, skip Phases 5–6") the PR was
**not merged** and nothing was deployed. Phases 5 and 6's merge/deploy steps did not run; the operator step
below is therefore not yet actionable.

## OPERATOR — not yet actionable (PR not merged, nothing deployed)

*(This section describes what to do once the fix ships. It has NOT shipped — PR #76 is open, blocked on two
pre-existing CI gates unrelated to this diff. Do not act on the steps below until a maintainer either waives/
fixes those two gates on `main` in a separate PR, or explicitly overrides and merges #76 despite them. Kept
here, unmodified from the original prompt, so it's ready the moment the fix does land.)*

1. Sign in (Google or password), enter one code from Google Authenticator, note the on-screen error text.
2. **`MFA_CODE_CLOCK_SKEW`** ("…about N s behind/ahead…") → phone clock. Google Authenticator → ⋮ → Settings
   → Time correction for codes → Sync now; also enable automatic date & time on the phone. Sign in again;
   expect success. No reset needed. Close the incident.
3. **`MFA_CODE_INVALID`** → wrong secret. Retry with email + password instead of Google. If password login
   accepts the same code and Google does not, there are two User rows (the Google-linked one holds an old
   device) — open a follow-up to merge them and hand it back with both emails. If both reject, delete the
   StratTraderPro entry in the app, sign in with a backup code, Settings → Security → Disable, re-enrol, and
   delete nothing else.
4. Succeeds on the first try → intermittent skew already resolved itself; still run Sync now to be safe.
5. Either way, read the audit row: admin portal → Audit → `auth.mfa_challenge_fail` → the newest row's
   `reason` / `offset_steps` must agree with what the screen said. If they disagree, that is a bug — report it.

## Section A — Findings & fixes

**Invariant audit (read, not run) — PASS, no fix needed.** Read the diff of `mfa.py` and `views_m02.py`
directly (not the bundle's prose) and confirmed all four:
- (a) `verify_totp()` is byte-for-byte unchanged — the diff only adds `totp_skew_offset()` after it.
- (b) `totp_skew_offset`/`_totp_failure` are called only inside pre-existing `if not verify_totp(...)` /
  `if not ok_code` rejection branches, at all 4 call sites (`MFAEnrollConfirmView`, `MFAVerifyView` non-backup
  branch, `MFADisableView`, `MFABackupRegenerateView`).
- (c) every such branch still ends in `return fail(...)` with the same status codes as before (400/400/401/400).
- (d) no `issue_token_pair`/cookie/`verified = True` write is reachable after a miss — the `return` inside each
  `if not ...` block makes the success path (below, only reached when the check passes) unreachable.

**Adversarial review (fresh subagent, diff + repo access, no prior framing) — no invariant-breaking findings.**
All 6 brief items traced and confirmed safe with explicit reasoning (see full text in the PR body):
1. Never widens acceptance — confirmed via `verify_totp` diff + every call-site grep + the probe's explicit
   skip of the accepted window (`range(accepted+1, probe+1)`, matching pyotp's own `verify()` loop bounds).
2. Lockout/rate-limit/counters unchanged — line-by-line diff of all 4 call sites; no counter/cache line moved
   or gained a conditional.
3. No meaningful brute-force shortcut — TOTP steps are cryptographically independent HMAC outputs; matching
   step T±k reveals nothing about step T, and matching at all already implies knowledge of the secret.
4. Audit hash chain intact — `data_after` is an opaque per-call JSON blob pre-diff already; `reason`/
   `offset_steps` pass `scrub()`'s sensitive-key denylist untouched (they aren't secrets) and serialize fine.
5. No unhandled exception on odd input — `None`/non-digit/7-digit/spaced code all hit the same early-return
   guard as `verify_totp`; non-positive or huge `MFA_TOTP_SKEW_PROBE_STEPS` either short-circuits
   (`probe <= accepted`) or just costs CPU via a lazy `range()`, never crashes.
6. Backup-code miss never mislabeled — that branch hardcodes `MFA_CODE_INVALID` and never calls
   `_totp_failure`/`totp_skew_offset`.

**One minor finding — DISMISSED, not fixed.** No upper clamp on `MFA_TOTP_SKEW_PROBE_STEPS`: a badly
misconfigured (very large) value would make every *rejected* TOTP do a longer synchronous HMAC-probe loop.
Dismissed because: (a) it's an operator-set Django setting, not attacker-controlled input; (b) the
highest-traffic path (`MFAVerifyView`) is already IP-rate-limited (5/min); (c) the other three views require
authentication already, bounding any cost to an authenticated user's own request rate; (d) adding a clamp for
a hypothetical operator misconfiguration is speculative validation this project's conventions avoid (no
error-handling for scenarios that can't occur without an operator already having production settings write
access, at which point they have far more damaging options). No follow-up commit was needed — the branch
tip is unchanged from what landed at Phase 0.

## Section B — Autonomous decisions, deviations, deferred items

- **Not re-implemented from spec** — the branch and bundle-equivalent commits already existed locally
  (`fix/mfa-totp-skew-diagnostics`, 2 commits ahead of `1dcdd70`, exact file list and commit subjects matching
  the mission's SPEC verbatim), so Phase 0 was a checkout + verification, not a re-implementation.
- **No rebase needed** — `origin/main` was already at `1dcdd70` at run start; no divergence to resolve.
- **Stale `.git/index.lock` cleared** — dated ~a month old, no live git process held it (verified via `ps`
  and a successful concurrent `git status`); removed before `git checkout`.
- **Postgres + Redis brought up** (`docker compose up -d postgres redis`, ports 5434/6380) for the `-m pg`
  lane and the prod-settings smoke test; the project's `worker`/`beat`/`streams`/`worker-backtest` containers
  were separately crash-looping in the environment before this run started (pre-existing, unrelated to this
  branch — Celery workers aren't needed to run pytest) and were left alone.
- **Frontend dependency-audit gate (osv-scanner) — parked, not fixed. CI CONFIRMED RED, exactly as predicted.**
  `Frontend — Build & Test` job (run `35529126548`, job `106126475820`) failed at the "Dependency audit
  (osv-scanner, HIGH+ gate)" step in 20s — the step aborts the job before `Test (karma)`/`Build` even run, so
  CI never got to independently confirm the karma/build results this run proved locally. 16 un-waived HIGH+
  advisories against `pnpm-lock.yaml`. Confirmed out-of-diff-scope: `pnpm-lock.yaml` and `package.json` are
  byte-identical to `main` in this branch (`git diff --stat` empty), so osv-scanner's live-OSV-DB output is
  identical regardless of branch — this gate is equally red on `main` right now (`main`'s last CI run on the
  current HEAD `1dcdd70` was green 2026-08-04, 47 days of live-CVE-DB drift ago). Per the run's autonomous
  policy ("a new advisory on unchanged pins" is explicitly out-of-scope), no pins were bumped and no waivers
  were added.
- **Backend dependency-audit gate (pip-audit) — parked, not fixed. CI CONFIRMED RED, same pattern.**
  `Backend — Lint & Test` job (run `35529126548`, job `106126475872`) — every other step (ruff, bandit, the
  full pytest suite, the `-m pg` lane) **passed**, matching the local gauntlet exactly; only the "Dependency
  audit (pip-audit)" step failed, on 10 known vulnerabilities: 7 on `django==5.1.15` (PYSEC-2026-198/199/201/
  2090/2091/2092/3717), 2 on `djangorestframework==3.15.2` (PYSEC-2026-3827/3828), 1 on `weasyprint==68.1`
  (PYSEC-2026-3940). Confirmed out-of-diff-scope: `git diff --stat -- backend/requirements/` between `main`
  and this branch is empty — this diff touches zero dependency pins. Same 47-day live-CVE-drift explanation
  as the frontend gate. Per policy, not fixed here — a dependency-bump PR is a separate, out-of-scope piece of
  work (and `Django`/`DRF`/`weasyprint` version bumps are exactly the kind of change this diagnostics-only fix
  should not be bundled with).
- Because both required checks are red for reasons outside this diff, **the PR was left open and unmerged**
  per the mission's explicit Phase 4 fallback ("Red outside the diff → leave open, report, skip Phases 5–6").
  No `gh pr merge` was attempted. No deploy occurred. The two downstream jobs gated on
  `Backend — Lint & Test` (`E2E Smoke`, `Entrypoint — SERVICE_ROLE dispatch`, `Trivy — Docker Image Scan`) and
  on the frontend build (`A11y — axe-core`) never ran (shown as `skipping`) — this is a consequence of the two
  audit-gate failures, not an independent problem with this diff.
- **`plan-progress-tracker.md` left untouched** — Phase 02 (MFA & User Profile) is a fully "✅ Done" historical
  milestone record there with no open/in-progress row this fix should update; per the mission's instruction to
  touch it only if such a row exists, and per its known lag behind `PROGRESS.md` (which is canonical), it was
  not edited.
- **Follow-up issues (Out-of-scope section of the mission) — filed:**
  1. [#77](https://github.com/yhaspel/StratTraderPro/issues/77) — MFA verify per-IP rate limit inert in
     production (7 rapid probes all 401, never 429).
  2. [#78](https://github.com/yhaspel/StratTraderPro/issues/78) — the `/auth/refresh/` 401 that triggered the
     incident's re-login (two different failure-body sizes at 11:35:40Z vs 11:36:00Z).
- **Recommended next step (not taken here, out of scope):** open a separate dependency-bump PR covering
  Django (→5.2.17 or 6.0.8), DRF (→3.17.2), and WeasyPrint (→70.0) on `backend/requirements/`, plus a frontend
  waiver/bump pass for the 16 `osv-scanner` advisories (per the established `docs/security/dependency-
  waivers.md` pattern used on 2026-08-04 for the same class of issue) — once that lands and both gates are
  green on `main`, rebase/re-push this branch (or open a fresh PR from it) and it should merge cleanly, since
  every other required check already passed.

## Section C — Evidence

### Phase 1 gauntlet — backend (fork agent, from `backend/`)

| Command | Exit | Outcome |
|---|---|---|
| `ruff check .` | 0 | All checks passed |
| `bandit -r apps/ config/ -x tests -q --severity-level medium` | 0 | Clean (pre-existing informational-only `nosec` notices) |
| `python -m pytest -q` | 1 | 962 passed, 3 failed (WeasyPrint dyld gap, confirmed environmental — see below), 10 skipped |
| `pytest -v apps/users/test_mfa.py` | 0 | 51 passed, incl. all 7 new skew tests by name |
| `DATABASE_URL=postgres://stp_user:stp_local_pw@localhost:5434/strattraderpro pytest -m pg --ds=config.settings.test_pg` | 0 | 9 passed, 0 failed |
| `manage.py makemigrations --check --dry-run` | 0 | "No changes detected" |
| prod-settings import smoke (`DJANGO_SETTINGS_MODULE=config.settings.prod`, real Fernet key) | 0 | imports clean |
| Re-run of the 3 failures with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` | 0 | all 5 tests in `FullWalkForwardTests` pass — confirms the 3 failures were the known Mac-local `libgobject-2.0-0` dyld gap (CI installs native libs via apt; irrelevant there) |

### Phase 1 gauntlet — frontend (fork agent, from `frontend/`)

| Command | Exit | Outcome |
|---|---|---|
| `pnpm install --frozen-lockfile` | 0 | lockfile already up to date |
| `npx ngc --noEmit -p tsconfig.app.json` | 0 | silent, clean |
| `CHROME_BIN=".../Google Chrome" pnpm run test:ci` | 0 | 264/264 SUCCESS (run twice to confirm) |
| `npx ng build --configuration production` | 0 | clean build, 474.31 kB initial |
| `docker run ghcr.io/google/osv-scanner ... \| node scripts/audit-gate.mjs` | 1 | 16 un-waived HIGH+ — confirmed pre-existing on `main` (see Section B) |

### Repo guards (run directly, from repo root)

| Command | Exit | Outcome |
|---|---|---|
| `bash scripts/verify_entrypoint_dispatch.sh` | 0 | "entrypoint dispatch gauntlet: PASS" |
| `python3 scripts/check_envsubst_filter.py` | 0 | "envsubst filter in sync (6 vars)" |
| `python3 scripts/check_guides_catalog.py` | 0 | "guides catalog in sync (19 articles, 7 images)" |

### Phase 4 — PR + CI

- **PR:** [#76](https://github.com/yhaspel/StratTraderPro/pull/76) — `fix(mfa): report a rejected TOTP as
  clock skew vs. wrong secret, and audit the offset`. **State: OPEN, not merged.**
- **CI run:** [`35529126548`](https://github.com/yhaspel/StratTraderPro/actions/runs/35529126548)

| Check | Result | Note |
|---|---|---|
| Backend — Lint & Test | **fail** (pip-audit step only; ruff/bandit/pytest/pg lane all pass) | out-of-diff, see Section B |
| Frontend — Build & Test | **fail** (osv-scanner step only; job aborted before karma/build ran in CI) | out-of-diff, see Section B |
| A11y — axe-core | skipped (downstream of Frontend job) | — |
| E2E Smoke — docker-compose healthz | skipped (downstream of Backend job) | — |
| Entrypoint — SERVICE_ROLE dispatch | skipped (downstream of Backend job) | — |
| Trivy — Docker Image Scan | skipped (downstream of Backend job) | — |
| Guard — nginx envsubst filter in sync | pass | — |
| Guard — no legacy IBKR creds | pass | — |
| Guard — live trading stays disabled | pass | — |

### Phase 5–6 — not applicable (PR not merged)

- Squash-merge SHA: **N/A — not merged.**
- `/healthz` version before/after: **N/A — no deploy occurred.**
- `curl .../assets/i18n/en.json | grep -c MFA_CODE_CLOCK_SKEW`: **N/A — no deploy occurred.**
- Follow-up issue links: [#77](https://github.com/yhaspel/StratTraderPro/issues/77),
  [#78](https://github.com/yhaspel/StratTraderPro/issues/78) — both filed regardless, since they're
  independent of merge status.
- OPERATOR live-verification step: **not yet actionable** — see note at the top of this report.
