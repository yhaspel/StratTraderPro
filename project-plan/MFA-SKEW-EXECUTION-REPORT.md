# MFA skew-diagnostics — execution report

Branch `fix/mfa-totp-skew-diagnostics` (base `1dcdd70` = `origin/main` at run start). This report is written
incrementally during the run per `ONE-SHOT-MFA-SKEW-DIAGNOSTICS.prompt.md`; Section C and the operator note
are completed as later phases finish.

## OPERATOR — do this once the deploy is confirmed (Phase 6)

*(Status: deploy not yet confirmed — this section will be filled in when Phase 5 completes. Do not act on it
until then; a placeholder is written here now so the structure is in place.)*

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
- **Frontend dependency-audit gate (osv-scanner) — parked, not fixed.** 16 un-waived HIGH+ advisories against
  `pnpm-lock.yaml`. Confirmed out-of-diff-scope: `pnpm-lock.yaml` and `package.json` are byte-identical to
  `main` in this branch, so osv-scanner's live-OSV-DB output is identical regardless of branch — this gate
  would be equally red on `main` right now. Per the run's autonomous policy ("a new advisory on unchanged
  pins" is explicitly out-of-scope), no pins were bumped and no waivers were added. This PR's frontend CI run
  is expected to show this same failure; it is not a regression introduced here.
- **`pip-audit` not run locally** — not installed in the local venv used for the gauntlet fork; this diff adds
  zero dependency changes so its result is unaffected. CI runs it independently and will be watched in Phase 4.
- **`plan-progress-tracker.md` left untouched** — Phase 02 (MFA & User Profile) is a fully "✅ Done" historical
  milestone record there with no open/in-progress row this fix should update; per the mission's instruction to
  touch it only if such a row exists, and per its known lag behind `PROGRESS.md` (which is canonical), it was
  not edited.
- **Follow-up issues (Out-of-scope section of the mission) — filed in Phase 4/6, links recorded here then:**
  1. MFA verify per-IP rate limit inert in production (7 rapid probes all 401, never 429).
  2. The `/auth/refresh/` 401 that triggered the incident's re-login (two different failure-body sizes at
     11:35:40Z vs 11:36:00Z).

## Section C — Evidence

*(Filled in as later phases complete — see individual command outputs already summarized in Section A above
for the Phase 1/2 gauntlet and review. PR URL, CI run URL, squash SHA, `/healthz` before/after, and the
`en.json` grep result are added once Phases 4–5 complete.)*

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

### Pending (Phases 4–6)

- PR URL: TBD
- CI run URL + final check statuses: TBD
- Squash-merge SHA: TBD
- `/healthz` version before/after (with timestamps): TBD
- `curl .../assets/i18n/en.json \| grep -c MFA_CODE_CLOCK_SKEW`: TBD
- Follow-up issue links: TBD
