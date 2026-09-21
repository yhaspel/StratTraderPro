#!/usr/bin/env bash
# Verify the live Claude scheduled-task prompt still matches the canonical repo copy.
#
# Why this exists: the `strattraderpro-silent-failure-audit` prompt lives outside git,
# in the Claude desktop app's Scheduled/ directory. On 2026-08-18 it was silently
# reverted to a ~2026-07-11 ancestor, reintroducing stale baselines that had already
# been fixed twice. Nothing detected it for ~5 weeks — the monitor's own definition
# had no monitor. See bugs/BUG-012.
#
# Usage: scripts/check_scheduled_task_sync.sh
# Exit 0 = in sync. Exit 1 = drift (prints a diff). Exit 2 = live file missing.

set -euo pipefail

REPO_COPY="$(dirname "$0")/../infra/scheduled-tasks/strattraderpro-silent-failure-audit.SKILL.md"
LIVE_COPY="$HOME/Documents/Claude/Scheduled/strattraderpro-silent-failure-audit/SKILL.md"

if [[ ! -f "$LIVE_COPY" ]]; then
  echo "SKIP: live task prompt not found at $LIVE_COPY"
  echo "      (expected on any machine that doesn't run the Claude desktop scheduler)"
  exit 2
fi

if cmp -s "$REPO_COPY" "$LIVE_COPY"; then
  echo "OK: scheduled-task prompt in sync ($(shasum -a 256 "$REPO_COPY" | cut -c1-12))"
  exit 0
fi

echo "DRIFT: live scheduled-task prompt differs from the canonical repo copy."
echo "  repo: $REPO_COPY"
echo "  live: $LIVE_COPY"
echo
diff -u "$REPO_COPY" "$LIVE_COPY" || true
echo
echo "If the LIVE copy is correct, copy it into the repo and commit."
echo "If the REPO copy is correct, restore it:  cp '$REPO_COPY' '$LIVE_COPY'"
exit 1
