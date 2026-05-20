#!/usr/bin/env bash
# Run from the repo root: bash _hotfix_push.sh
# Pushes ONLY the docker/backend.Dockerfile WSGI hotfix to origin/main.
# Sidelines:
#   - your uncommitted M04A IBKR WIP (stashed; restored at the end)
#   - the local-only `9ad27b2 m4 initial` commit (saved on a branch;
#     has a karma "~6.4.p0" typo that would break frontend pnpm install)
set -euo pipefail

cd "$(dirname "$0")"

echo "==> 1. Save the edited Dockerfile aside (so stash doesn't lose it)"
mkdir -p .hotfix-stage
cp docker/backend.Dockerfile .hotfix-stage/backend.Dockerfile.new

echo "==> 2. Clear any stale git index lock"
rm -f .git/index.lock || true

echo "==> 3. Park the local-only 'm4 initial' commit on a branch (don't lose it)"
git branch -f m4-initial-pause 9ad27b2 || true

echo "==> 4. Stash WIP (working tree + untracked screenshots/files)"
git stash push --include-untracked -m "M04A IBKR WIP + hotfix-pause"

echo "==> 5. Fetch & checkout a hotfix branch from origin/main"
git fetch origin
git checkout -B hotfix/wsgi-mode origin/main

echo "==> 6. Re-apply the Dockerfile change on the clean branch"
cp .hotfix-stage/backend.Dockerfile.new docker/backend.Dockerfile

echo "==> 7. Commit"
git add docker/backend.Dockerfile
git commit -m "fix(prod): switch backend to WSGI to bypass sentry-sdk 1.x ASGI bug

sentry-sdk 1.x DjangoIntegration installs SentryASGIMixin around the
Django ASGI app. allauth's sync AccountMiddleware then calls
response.headers.get(...) on what is actually an unawaited coroutine,
raising AttributeError on every request — gunicorn returns 500.

The pre-existing /metrics before_send Sentry filter (commit 5a26934)
only suppressed the *event*, not the 500. /healthz, /readyz, /metrics,
/api/v1/auth/login — all 500. The Railway-wide Postgres incident
(2026-05-20) brought the issue into focus when Postgres came back but
backend stayed broken.

Switch gunicorn from config.asgi:application + UvicornWorker to
config.wsgi:application + gthread workers (3 workers × 4 threads).
Sidesteps SentryASGIMixin entirely. No Channels in prod yet, so no
functional loss. When M04 ships WebSockets, upgrade sentry-sdk to
>=2.x (async-aware DjangoIntegration) and restore ASGI in the same
PR. Cross-ref Phase 10 §6.5 (/metrics outside Django) for the durable
allauth interaction fix."

echo "==> 8. Push hotfix branch"
git push -u origin hotfix/wsgi-mode

echo "==> 9. Fast-forward main onto the hotfix (drops the local-only m4-initial commit)"
git checkout main
git reset --hard origin/main
git merge --ff-only hotfix/wsgi-mode
git push origin main

echo "==> 10. Clean up staging dir"
rm -rf .hotfix-stage

echo
echo "==> Done. Railway will redeploy backend from main shortly."
echo "    To restore your M04A WIP after verification:"
echo "        git stash pop"
echo "    Your m4-initial commit is preserved on branch:"
echo "        m4-initial-pause   (fix the karma typo before reusing it)"
