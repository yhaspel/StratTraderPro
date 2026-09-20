> ## ⏳ ARCHIVED — IN PROGRESS 2026-09-20. Will be marked EXECUTED once the PR merges and the deploy is
> confirmed. Durable record: `project-plan/PROGRESS.md` and `MFA-SKEW-EXECUTION-REPORT.md`.

---

# ONE-SHOT PROMPT — Ship `fix/mfa-totp-skew-diagnostics` (land → gauntlet → PR → CI → merge → live verify)

> Paste everything below the line into Claude Code CLI (max effort), running from the repo root
> `~/Documents/Claude/Projects/StratTraderPro`. It is self-contained and designed to run end-to-end
> **without human input**: apply the delivered bundle → run every CI gate locally (including the two
> the sandbox could not) → adversarial review → push → PR → CI → squash-merge to `main` → confirm the
> auto-deploy → hand the operator the one live check only a human can perform. Operator decisions
> already made: **admin-merge the PR autonomously once CI is green**; on a hard blocker, **park it,
> document it, finish everything else best-effort**.
>
> Written 2026-09-20 from a live diagnosis (see §CONTEXT). This file ships **inside** the fix
> branch at `project-plan/ONE-SHOT-MFA-SKEW-DIAGNOSTICS.prompt.md`, so if you are reading it from
> the repo the branch is already applied — Phase 0 detects that and skips the bundle step. The
> bundle `fix-mfa-totp-skew-diagnostics.bundle` is only needed on a machine where the branch does
> not exist yet.

---

## MISSION

Land the one-commit branch `fix/mfa-totp-skew-diagnostics` (base `1dcdd70` = current `origin/main`)
on `main` of StratTraderPro (Django 5 + Angular 19 trading-bot monorepo), prove it with the full
gauntlet, and verify the production deploy picked it up. The change makes a rejected TOTP code
self-explanatory: `MFA_CODE_CLOCK_SKEW` ("your authenticator's clock is N s off — sync it") vs the
generic `MFA_CODE_INVALID`, and records `reason` + `offset_steps` on the `auth.mfa_challenge_fail`
audit row. **It must never widen acceptance** — that is the one invariant a reviewer must be unable
to break.

Precedence: **the code in the bundle > this prompt's summaries**. Read the diff yourself.

## CONTEXT — why this exists (do not re-derive; verify only what §PHASE 1 asks)

Live incident, 2026-09-20 (Railway backend HTTP log, UTC): `/api/v1/auth/refresh/` 401 at 11:35:40
forced a logout → Google re-sign-in → `/auth/oauth/exchange/` 200 (MFA challenge) → three
`POST /api/v1/auth/mfa/verify/` at 11:36:14 / :22 / :34, each **401 with an 82-byte body** — that
byte count is exactly `{"error":{"code":"MFA_CODE_INVALID","message":"Code is invalid or already
used."}}`. Same again at 11:46. Yet the same Google Authenticator entry (the user has exactly one)
had just been accepted by `/auth/mfa/enroll/confirm/` and `/auth/mfa/disable/`, which run the
identical `decrypt_secret` + `verify_totp` on the identical `MFADevice` row.

Ruled out against the live system, not by reading code: origin clock (Django's `Set-Cookie
expires` = wall time to the second), KEK/secret (nothing rewrites `secret_encrypted` after
enrolment), lock/rate-limit (different error codes; the per-IP limiter isn't even blocking — 7
rapid probes all 401, never 429), the 6-cell `TotpInputComponent` (shared with the enrol page),
Sentry (no MFA errors, only Celery `InterfaceError`s). What remains: the code was generated from
the right secret at the wrong time (phone clock drift — ±30 s window explains "works sometimes"),
or from the wrong secret (second `User` row behind the Google link). The backend collapsed both
into one error + one detail-free audit row. The bundle fixes *that*; the two candidate root causes
are settled by the operator step in §PHASE 6.

## WHAT "AUTONOMOUS" MEANS HERE (non-negotiable)

- **Never stop to ask the user anything.** Choose the safest reversible option, proceed, log it in
  the report (Section B "decided autonomously").
- **Hard blocker = park and continue.** If a gate cannot go green for a cause inside this diff, fix
  it; if the cause is outside the diff (a new advisory on unchanged pins, Actions infra), do NOT bump
  pins or weaken gates — leave the PR open, name the job + cause in Section B, finish the rest.
- **Bounded waits:** poll `gh pr checks` with a 60-minute deadline; on expiry treat as
  CI-cannot-green, never as a fix-forward loop.
- **Never widen TOTP acceptance.** Any change that makes `verify_totp` or the verify view accept a
  code outside `MFA_TOTP_VALID_WINDOW` is forbidden, including "to make a test pass".
- **Re-run / resume:** if a prior partial run left state (branch applied, PR open), verify each
  phase's end-state and continue from the first incomplete one. Merges must never run twice.
- **Keep a running report** `project-plan/MFA-SKEW-EXECUTION-REPORT.md`, updated per phase, so a
  crash mid-run leaves a usable trail. Final shape in §REPORT.
- Repo memory that applies (from earlier sessions — treat as facts):
  - `tsc --noEmit` does NOT catch Angular template errors; only `npx ngc --noEmit -p tsconfig.app.json`
    / `ng build` do.
  - CI = ruff + bandit (`bandit -r apps/ config/ -x tests -q --severity-level medium`) + pytest +
    pytest `-m pg` + pip-audit (backend); ngc + karma + `pnpm build` + osv-scanner (frontend);
    Playwright a11y; entrypoint-dispatch guard. `pytest` green alone is not green CI.
  - Use **pnpm**, never `npm install`, in `frontend/`.
  - `railway up` does NOT inject `RAILWAY_GIT_COMMIT_SHA`; only GitHub-triggered deploys do — a
    merge to `main` is one, so `/healthz` **should** report the merge SHA.
  - `project-plan/plan-progress-tracker.md` lags real state; PROGRESS.md is canonical.

## PHASE 0 — Land the branch

1. `git status` must be clean on `main`; `git fetch origin && git rev-parse origin/main` must be
   `1dcdd70`. If `origin/main` has moved, that is fine — record the SHA and expect a rebase in step 3.
2. If the branch `fix/mfa-totp-skew-diagnostics` already exists locally (`git branch --list`) and
   its tip's subject is the one named below, `git checkout` it and skip to step 4. Otherwise, if
   `fix-mfa-totp-skew-diagnostics.bundle` exists at the repo root:
   `git bundle verify` it, then
   `git fetch fix-mfa-totp-skew-diagnostics.bundle 'refs/heads/fix/mfa-totp-skew-diagnostics:refs/heads/fix/mfa-totp-skew-diagnostics'`
   and `git checkout fix/mfa-totp-skew-diagnostics`. Expect exactly one commit ahead of `1dcdd70`,
   subject `fix(mfa): report a rejected TOTP as clock skew vs. wrong secret, and audit the offset`,
   touching exactly: `CHANGELOG.md`, `backend/apps/users/mfa.py`, `backend/apps/users/test_mfa.py`,
   `backend/apps/users/views_m02.py`, `backend/config/settings/base.py`,
   `docs/runbooks/user-lost-mfa.md`, `frontend/src/assets/i18n/en.json`, plus this prompt at
   `project-plan/ONE-SHOT-MFA-SKEW-DIAGNOSTICS.prompt.md` (second commit).
3. If the bundle is **missing or fails to verify**: create the branch from `origin/main` and
   re-implement from §SPEC below, matching it exactly (same names, same error code, same audit
   fields, same setting). Record "re-implemented from spec" in Section B.
4. If `origin/main` moved past `1dcdd70`: `git rebase origin/main`; resolve conflicts (most likely
   `CHANGELOG.md` `[Unreleased]` — keep both entries, ours on top).
5. Delete the bundle file from the working tree (it must not be committed); if the OS blocks the
   delete, move it into `_to_delete/` (gitignored — if not, add it).

## SPEC (authoritative summary of the diff; re-implement from this only if Phase 0.3 applies)

- `backend/apps/users/mfa.py` — `totp_skew_offset(secret_b32, code) -> Optional[int]`, exported in
  `__all__`. Called ONLY after `verify_totp` rejected `code`. Normalises like `verify_totp` (strip,
  remove spaces, must be 6 digits else `None`). Reads `settings.MFA_TOTP_SKEW_PROBE_STEPS` (default
  10) and `settings.MFA_TOTP_VALID_WINDOW`; if probe ≤ window → `None`. Walks
  `k = window+1 … probe`, offsets `(-k, +k)` in that order, comparing
  `pyotp.TOTP(secret, interval=30, digits=6).at(timezone.now(), offset)` with
  `secrets.compare_digest`; returns the first matching offset, else `None`. Never returns 0/±1.
- `backend/config/settings/base.py` — `MFA_TOTP_SKEW_PROBE_STEPS = env.int(..., default=10)` right
  after `MFA_TOTP_VALID_WINDOW`, with a comment that it is diagnostic-only and never widens
  acceptance.
- `backend/apps/users/views_m02.py` — module helper
  `_totp_failure(secret, code) -> (error_code, message, audit_metadata)`:
  offset `None` → `("MFA_CODE_INVALID", "Code is invalid or already used.", {"reason": "no_match"})`;
  else → `("MFA_CODE_CLOCK_SKEW", "That code is valid for a time about {abs(offset)*30}s
  {behind|ahead of} the server, so your authenticator app's clock is off. Sync its time (Google
  Authenticator: Settings → Time correction for codes) and try again.", {"reason": "clock_skew",
  "offset_steps": offset})`. Used on the TOTP-miss path of `MFAEnrollConfirmView` (400),
  `MFAVerifyView` (401, TOTP branch only — backup-code misses stay `MFA_CODE_INVALID` with no
  `reason`), `MFADisableView` (400), `MFABackupCodesRegenerateView` (400). The metadata is merged
  into the existing `mfa_challenge_fail` `record_event(... metadata={"phase": ..., **diag})`. All
  counters (`MFA_VERIFICATIONS_TOTAL`, `MFA_CHALLENGE_FAILURES_TOTAL`), the per-user
  `mfa_login_fail_user:{pk}` cap, the per-jti burn and the `fail(...)` status codes are **unchanged**.
- `frontend/src/assets/i18n/en.json` — `mfa.error.MFA_CODE_CLOCK_SKEW` next to `MFA_CODE_INVALID`.
- `docs/runbooks/user-lost-mfa.md` — a "First: is the device actually lost, or are codes just being
  rejected?" section with a `reason`/`offset_steps` triage table; bump *Last reviewed*.
- `CHANGELOG.md` — `[Unreleased]` → "### Changed — MFA: a rejected TOTP now says *why*".
- Tests in `backend/apps/users/test_mfa.py` (7): probe reports `-4` for a stale code; `None` for a
  wrong secret; `None` for offsets −1/0/+1 (window skip); `None` when
  `MFA_TOTP_SKEW_PROBE_STEPS=1`; verify view with `.at(now, -4)` → 401 `MFA_CODE_CLOCK_SKEW`, no
  `access` in body, no `stp_refresh` cookie, audit `data_after.reason == "clock_skew"` and
  `offset_steps == -4`, `cache.get("mfa_login_fail_user:{pk}") == 1`; verify view with a code from a
  different secret → 401 `MFA_CODE_INVALID`, `reason == "no_match"`, no `offset_steps`, counter 1;
  enrol-confirm with `.at(now, 3)` → 400 `MFA_CODE_CLOCK_SKEW`, `mfa_enabled` still False,
  `offset_steps == 3`.

## PHASE 1 — Verify the invariant, then the full gauntlet (sandbox already did the backend half)

1. **Invariant audit first** (read, don't run): open the diff of `mfa.py` and `views_m02.py` and
   confirm (a) `verify_totp` is byte-identical to `main`, (b) `totp_skew_offset` is only ever called
   inside an `if not verify_totp(...)` / `if not ok_code` branch, (c) every such branch still ends in
   `return fail(...)`, (d) no `issue_token_pair` / cookie / `verified = True` write is reachable after
   a miss. If any of (a)–(d) fails, STOP this phase, fix it, record it as a Section-A finding.
2. Backend, in `backend/` with the repo venv (`.venv` / `uv`): `ruff check .`;
   `bandit -r apps/ config/ -x tests -q --severity-level medium`; `python -m pytest --tb=short -q`
   (expected ≥ 887 passed, 0 failed — sandbox result was 887 / 0 / 14 skipped);
   `python -m pytest -m pg --tb=short -q` (Postgres lane — needs the compose Postgres, `make up` or
   the documented `DATABASE_URL`); `python manage.py makemigrations --check --dry-run` (must be
   clean — this diff adds no model); prod-settings import smoke
   (`DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=x FERNET_KEK=$(python -c 'from
   cryptography.fernet import Fernet;print(Fernet.generate_key().decode())') DATABASE_URL=… python
   -c 'import django;django.setup()'`).
3. Frontend, in `frontend/`: `pnpm install --frozen-lockfile`; `npx ngc --noEmit -p
   tsconfig.app.json` (silent = pass); `pnpm run test:ci` (karma — expected 264+ SUCCESS; the only
   frontend change is one i18n string, so any failure is pre-existing or environmental — say which);
   `pnpm run build` / `npx ng build --configuration production`. **These three were NOT run in the
   sandbox** — this is the first time the frontend side is proven.
4. Repo guards CI also runs: `bash scripts/verify_entrypoint_dispatch.sh`,
   `python scripts/check_envsubst_filter.py`, `python scripts/check_guides_catalog.py` (check
   `ci.yml` for the exact invocations and any others) — run them.
5. Record every command + outcome in the report as you go.

## PHASE 2 — Adversarial review (subagent, fresh eyes)

Spawn a reviewer subagent with ONLY the diff and this brief: "Find any way this change (1) accepts a
TOTP outside ±MFA_TOTP_VALID_WINDOW, (2) changes lockout/rate-limit/burn behaviour, (3) leaks
something useful to a brute-forcer beyond 'your guess was a real code for step T±k' (state why that
is or isn't a shortcut to step T), (4) breaks the audit hash chain (`emit` / `data_after` shape),
(5) can raise on odd input (None code, non-digit, 7 digits, huge int in settings), (6) mis-labels a
backup-code miss." Fix real findings on the branch with a follow-up commit `fix(mfa): review
remediation — …`; record dismissed findings with the reason. If the reviewer proposes widening the
window "for UX", reject it explicitly in the report.

## PHASE 3 — Docs commit

One commit `docs(plan): MFA skew diagnostics — PROGRESS entry + archive one-shot` that:
- adds a dated **Last verified: 2026-09-20** paragraph at the top of `project-plan/PROGRESS.md`
  (canonical status file) summarising: incident, what was ruled out, what shipped, gauntlet numbers,
  and the deferred operator step from §PHASE 6;
- `git mv` this prompt from `project-plan/` to `project-plan/archived/ONE-SHOT-MFA-SKEW-DIAGNOSTICS.prompt.md` with a
  provenance header (`EXECUTED <date>` once Phase 5 completes — write "IN PROGRESS" now and amend in
  the final report commit), following the existing `project-plan/archived/` convention;
- adds `project-plan/MFA-SKEW-EXECUTION-REPORT.md` (the running report).
Do NOT edit `plan-progress-tracker.md` beyond a one-line pointer if it has an auth/MFA row.

## PHASE 4 — Push, PR, CI

1. `git push -u origin fix/mfa-totp-skew-diagnostics`.
2. `gh pr create --base main --title "fix(mfa): report a rejected TOTP as clock skew vs. wrong
   secret, and audit the offset" --body-file -` with a body that carries: the §CONTEXT incident
   timeline (UTC), the ruled-out list, the invariant ("never widens acceptance") and where the tests
   pin it, the gauntlet numbers from Phase 1, the reviewer's findings + dispositions, and the §PHASE 6
   operator step. Link the runbook section.
3. Poll `gh pr checks --watch` (60-min deadline). All required checks must be green: Backend — Lint &
   Test (incl. Postgres lane + pip-audit), Frontend — Build & Test (incl. osv-scanner), A11y, the
   guards. Red **inside** the diff → fix, push, re-poll. Red **outside** the diff → §AUTONOMOUS rule:
   leave open, report, skip Phases 5–6, still finish §REPORT.

## PHASE 5 — Merge and confirm the deploy

1. `gh pr merge --squash --admin --delete-branch` (operator pre-authorised). Record the squash SHA.
2. `git checkout main && git pull --ff-only`; confirm `git rev-parse HEAD` == squash SHA.
3. Railway auto-deploys `main` on GitHub push. Poll
   `https://backend-production-f3e8.up.railway.app/healthz` every 30 s, 15-min deadline, until
   `version` equals the squash SHA's short form (7 chars). If it never flips, report it — do NOT
   `railway up` (that would blank the SHA) and do NOT redeploy other services (`backend` is the only
   service that serves `/auth/mfa/*`; no env-var change is involved, so no cross-service redeploy is
   needed — see the FERNET_KEK memory: unchanged).
4. Confirm the frontend rebuilt too (it carries the i18n string): `curl -s
   https://strattraderpro.up.railway.app/assets/i18n/en.json | grep -c MFA_CODE_CLOCK_SKEW` → `1`.
   If `0`, the frontend service didn't redeploy from the same push — trigger its redeploy from the
   Railway UI **only** if the `railway` CLI is not authenticated; otherwise
   `railway redeploy --service frontend` and re-check. (The backend change is independently
   correct without it: the missing-key handler falls back to the server message.)
5. Tag nothing. This is a fix, not a milestone.

## PHASE 6 — The one step only the operator can do (write it into the report, prominently)

The fix makes the *next* rejected code diagnostic. The live root cause is settled by this
sequence, which requires the operator's phone and account — put it verbatim at the top of the
report under **"OPERATOR — do this once the deploy is confirmed"**:

1. Sign in (Google or password), enter one code from Google Authenticator, note the on-screen
   error text.
   - `MFA_CODE_CLOCK_SKEW` ("…about N s behind/ahead…") → phone clock. Google Authenticator → ⋮ →
     Settings → *Time correction for codes* → **Sync now**; also enable automatic date & time on the
     phone. Sign in again; expect success. No reset needed. Close the incident.
   - `MFA_CODE_INVALID` → wrong secret. Retry with **email + password** instead of Google. If
     password login accepts the same code and Google does not, there are two `User` rows (the
     Google-linked one holds an old device) — open a follow-up to merge them and hand it back to
     Claude with both emails. If both reject, delete the StratTraderPro entry in the app, sign in
     with a backup code, Settings → Security → Disable, re-enrol, and delete nothing else.
   - It succeeds on the first try → intermittent skew already resolved itself; still run **Sync
     now** to be safe.
2. Either way, read the audit row: admin portal → Audit → `auth.mfa_challenge_fail` → the newest
   row's `reason` / `offset_steps` must agree with what the screen said. If they disagree, that is
   a bug — report it.

## OUT OF SCOPE (record as follow-ups, do not fix here)

- The `/auth/mfa/verify/` per-IP `django_ratelimit` decorator is not blocking in prod (7 requests
  in 1 s → all 401, never 429): most likely `REMOTE_ADDR` is the proxy's address or `RATELIMIT_ENABLE`
  is off in prod. Open `gh issue create` titled "MFA verify per-IP rate limit inert in production"
  with the observation and the M16 H1 precedent (decorator ran before DRF auth → keyed on a
  constant). Do not touch it in this PR.
- The `/auth/refresh/` 401 that triggered the re-login (254-byte body at 11:35:40Z vs 73-byte at
  11:36:00Z — two different failure messages). Note it in the same issue or a second one.

## REPORT — `project-plan/MFA-SKEW-EXECUTION-REPORT.md` (final shape)

- **OPERATOR — do this once the deploy is confirmed** (Phase 6, verbatim, first).
- **Section A — Findings & fixes**: invariant audit result; reviewer findings with dispositions;
  anything fixed on the branch beyond the bundle.
- **Section B — Autonomous decisions, deviations, deferred items**: re-implemented-from-spec (if
  so), rebase conflicts, parked gates with job + cause, "not run because …", the two follow-up
  issues with links.
- **Section C — Evidence**: every gate command and its summary line; PR URL; CI run URL; squash
  SHA; `/healthz` version before/after with timestamps; the en.json grep result.
- Keep it factual; no claims without the command that produced them.

Amend the archived prompt's header to `EXECUTED <date>` in the same final commit as the report.
Land that docs-only commit the way recent `docs(plan):` commits landed (`1dcdd70`, `f060847` went
to `main` directly; branch protection on `main` is saved-not-enforced) — direct push is fine.
