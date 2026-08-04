> **⚙️ SPENT ONE-SHOT — completed; not a work item.**
> This is the agent prompt that drove the owner-only account cleanup on prod + local (2026-07-15):
> `yuval3000@gmail.com` is now the sole account (staff + superuser) in both. It surfaced the
> append-only-audit deletion blocker, fixed in migration `audit/0006` (PR #35). Moved to `archived/`
> on 2026-07-15 — historical record only, **do not re-run.**

---

# ONE-SHOT — Production + local account cleanup (owner-only, is_staff)

**For:** Claude Code (CLI), run from the StratTraderPro repo root on the owner's Mac,
with the Railway CLI installed + authenticated, Docker running (for the local step),
and network access to Railway.

**Safe to commit:** contains no secrets, project IDs, or hostnames — the Railway
project/environment are selected interactively via `railway link`.

---

## Goal
Make the OWNER the only account, on BOTH production and local:
- Keep exactly `yuval3000@gmail.com`; set `is_staff=true` **and** `is_superuser=true`.
- Delete every other account — specifically the `yuval3000+stp-mailtest@gmail.com`
  Gmail-alias test account ("Mail Flow Test", never logged in).

Current known state (verified 2026-07-15): production `users_user` has exactly those
two rows, both `is_staff=false`.

## Why the earlier attempt failed — read this first
The obvious command —

```
railway ssh --service backend python manage.py promote_user …
```

fails because **`promote_user` is not deployed to production.** It exists only in the
working tree (uncommitted: `backend/apps/users/management/commands/promote_user.py`).
The prod container runs the last *deployed* image, which has no such command →
`Unknown command: 'promote_user'`.

Therefore:
- **Production:** do the cleanup with an inline `manage.py shell` script (works against
  the deployed image as-is), OR deploy the command first (Part C).
- **Local:** the command *is* available (it's the working tree), so call it directly.

## Rules / safety
- **ORM only.** Delete via `QuerySet.delete()` — it cascades foreign keys, fires
  signals, and keeps the M10 audit hash-chain consistent. **Never** hand-run
  `DELETE FROM users_user`.
- **Never** use the Railway "Data" tab SQL box — it silently swallows write errors.
- **Enumerate first, then gate.** Read the full account list before mutating. If ANY
  account exists beyond the two expected emails above, **HALT and report** — delete nothing.
- Confirm the target: **production** (now the only Railway environment) for Part A;
  **local docker-compose** for Part B. Never cross them.
- Don't print secrets (DB URLs, keys) to logs.
- This is the owner's own single-tenant instance — the operation is sanctioned.

---

## PART 0 — Preconditions & connectivity
1. `cd` to the repo root. `git status` should show `promote_user.py` (untracked) and a
   modified `Makefile` — that confirms you have the tooling checked out.
2. Railway CLI: `railway --version`; `railway whoami`. If not logged in, ask the owner to
   run `railway login`, then continue.
3. Link the target: `railway link` → project **StratTraderPro**, environment
   **production**. Then `railway status` to confirm `Environment: production`.
4. Note the backend service name (usually `backend`) from `railway status` /
   `railway service`. Use it as `<BACKEND>` below.
5. **Read-only smoke test** — prove you can reach prod's DB through Django *before*
   changing anything:
   ```
   railway ssh --service <BACKEND> python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(sorted(g().objects.values_list('email', flat=True)))"
   ```
   - Expect: `['yuval3000+stp-mailtest@gmail.com', 'yuval3000@gmail.com']`.
   - If `railway ssh` errors (SSH not enabled, or won't accept a passed command), fall back to:
     `railway run python manage.py shell -c "<same one-liner>"` — runs locally with prod
     env injected; needs backend deps on this machine (the repo's `backend/.venv` on the
     owner's Mac, or an activated venv).
   - If neither works, **STOP and report** the exact errors. Do not fall back to raw SQL.

## PART A — Production cleanup
Run this inline ORM script in the **production** Django shell, via whichever method
passed the Part 0 smoke test. Write it to `/tmp/cleanup_owner.py`:

```python
from django.contrib.auth import get_user_model
from django.db import transaction

U = get_user_model()
KEEP = "yuval3000@gmail.com"
EXPECTED = {"yuval3000@gmail.com", "yuval3000+stp-mailtest@gmail.com"}

emails = sorted(U.objects.values_list("email", flat=True))
print("Accounts:", emails)

# HALT gates — refuse to touch anything unexpected.
assert any(e.lower() == KEEP for e in emails), f"Owner {KEEP} missing — HALT"
unexpected = [e for e in emails if e.lower() not in EXPECTED]
assert not unexpected, f"Unexpected account(s) — HALT, deleting nothing: {unexpected}"

with transaction.atomic():
    me = U.objects.get(email__iexact=KEEP)
    me.is_staff = True
    me.is_superuser = True
    me.save(update_fields=["is_staff", "is_superuser"])
    removed = U.objects.exclude(pk=me.pk).delete()

print("Removed:", removed)
print("Final:", list(U.objects.values_list("email", "is_staff", "is_superuser")))
```

Invoke it (pick the method whose smoke test worked):
- **SSH (preferred, matches the runbooks' "prod: Railway service shell"):**
  `railway ssh --service <BACKEND> python manage.py shell < /tmp/cleanup_owner.py`
  If your CLI won't pipe over ssh: run `railway ssh --service <BACKEND>`, then
  `python manage.py shell`, paste the script, and press Ctrl-D.
- **Local-with-prod-env:** `railway run python manage.py shell < /tmp/cleanup_owner.py`.

**Expected final line:** `Final: [('yuval3000@gmail.com', True, True)]`.
If an assertion trips, **STOP** and report the account list — delete nothing.

## PART B — Local cleanup
Local runs your *working-tree* code, so `promote_user` is available.
1. `docker compose up -d` and wait for `backend` to be healthy.
2. Preview (read-only):
   ```
   docker compose exec backend python manage.py promote_user yuval3000@gmail.com --staff --superuser --remove-others --dry-run
   ```
   - If this prints `Unknown command`, the container has stale code: rebuild with
     `docker compose up -d --build`, or run `/tmp/cleanup_owner.py` via
     `docker compose exec -T backend python manage.py shell < /tmp/cleanup_owner.py`.
3. If the preview lists only expected accounts, execute:
   ```
   docker compose exec backend python manage.py promote_user yuval3000@gmail.com --staff --superuser --remove-others --yes
   ```
4. Confirm `Accounts now: [('yuval3000@gmail.com', True, True)]`.

## PART C — (Optional) commit the tooling + tidy-ups
Not required for the cleanup, but the new command + tidy-ups are uncommitted. If the
owner wants them in the repo:
1. Run the local CI gauntlet (all must pass):
   ```
   cd backend && python -m pytest -q && ruff check . && bandit -r apps/ config/ -x tests -q --severity-level medium
   cd ../frontend && npx ngc --noEmit -p tsconfig.app.json && npm run build
   ```
2. Commit the set: `promote_user` command, `Makefile` (`prod-shell` / `promote-owner`),
   retirement of the AC-10-10 `/__debug__/boom/` endpoint (`config/urls.py`,
   `config/settings/base.py`, deleted `config/test_debug_error_endpoint.py`), and the
   removed `.env.staging.local`.
3. **Side effect:** pushing to `main` triggers a Railway production deploy. Only push
   when you mean to deploy. After deploy, `railway ssh --service <BACKEND> python
   manage.py promote_user …` works directly (no inline script needed).
   → If unsure, leave this to the owner and report that the changes are staged locally.

## Acceptance criteria
- Production `users_user`: one row — `yuval3000@gmail.com`, `is_staff=true`, `is_superuser=true`.
- Local `users_user`: same.
- Nothing deleted if any unexpected account was present (HALT respected).
- No raw SQL delete; Data tab not used.

## Report back
State: (1) which connection method worked for prod; (2) before/after account lists for
prod and local; (3) whether Part C was done or deferred; (4) anything that blocked you.
