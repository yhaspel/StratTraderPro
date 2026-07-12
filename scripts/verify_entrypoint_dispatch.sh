#!/usr/bin/env bash
# M11 §7.0 / AC-11-14 — deps-free verification of the SERVICE_ROLE dispatcher.
# Mirrors backend/config/test_entrypoint_dispatch.py but needs no Python deps, so
# it runs in the local gauntlet and as a CI step before the image is built.
#
# It compares RESOLVED COMMAND STRINGS against the pinned literals in
# docker/entrypoint.expected — an exit-0 check alone proves nothing (BUG-009).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENTRY="$ROOT/docker/entrypoint.sh"
EXPECTED="$ROOT/docker/entrypoint.expected"

fail() { echo "FAIL: $1" >&2; exit 1; }

# 1) committed executable bit (the image CMD is exec-form).
mode="$(git -C "$ROOT" ls-files -s docker/entrypoint.sh 2>/dev/null | awk '{print $1}')"
if [ -n "$mode" ]; then
    [ "$mode" = "100755" ] || fail "entrypoint.sh committed mode is '$mode', want 100755"
else
    [ -x "$ENTRY" ] || fail "entrypoint.sh is not executable"
fi

# 2) exactly 7 data rows (skip comments/blanks); trailing newline required.
data="$(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$EXPECTED")"
n="$(printf '%s\n' "$data" | grep -c .)"
[ "$n" = "7" ] || fail "expected 7 pinned roles, got $n"
tail -c1 "$EXPECTED" | od -An -c | grep -q '\\n' || fail "entrypoint.expected must end with a newline"

# 3) every role resolves to its pinned literal (string equality).
printf '%s\n' "$data" | while IFS='|' read -r role expected; do
    actual="$(STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE="$role" DJANGO_SETTINGS_MODULE=config.settings.dev "$ENTRY")" \
        || fail "role '$role' exited non-zero"
    [ "$actual" = "$expected" ] || {
        echo "  want: $expected" >&2; echo "  got : $actual" >&2; fail "role '$role' command mismatch"; }
    echo "ok: $role"
done

# 4) unset / bogus / web-dev-misconfig must EXIT NON-ZERO and never resolve to web.
assert_nonzero() {
    local desc="$1"; shift
    if env "$@" "$ENTRY" >/dev/null 2>&1; then fail "$desc must exit non-zero"; fi
    echo "ok (exit!=0): $desc"
}
assert_nonzero "unset SERVICE_ROLE"                 STP_ENTRYPOINT_DRY_RUN=1
assert_nonzero "bogus SERVICE_ROLE"                 STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE=bogus
assert_nonzero "web-dev + prod settings"            STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE=web-dev DJANGO_SETTINGS_MODULE=config.settings.prod
assert_nonzero "web-dev + RAILWAY_ENVIRONMENT_NAME" STP_ENTRYPOINT_DRY_RUN=1 SERVICE_ROLE=web-dev DJANGO_SETTINGS_MODULE=config.settings.dev RAILWAY_ENVIRONMENT_NAME=production

echo "entrypoint dispatch gauntlet: PASS"
