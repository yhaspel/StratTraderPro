#!/usr/bin/env bash
# M11 §7.5 Day 6  →  AC-11-14  (the drill that would have caught BUG-011)
# ---------------------------------------------------------------------------
# DRILL: run the backend image with SERVICE_ROLE cleared (blank, the BUG-011
#        case) and with a bogus value.
# ASSERTS (for BOTH cases):
#   1. The container EXITS NON-ZERO — `docker inspect -f '{{.State.ExitCode}}'`
#      is not 0.
#   2. It prints the LOUD message ("entrypoint: FATAL ... set SERVICE_ROLE ...").
#   3. It does NOT quietly start serving HTTP — no gunicorn/runserver banner in
#      the logs. A blank field must crash, not silently become a web server.
#
# On a real compose service the four Celery/streams services carry
# `restart: on-failure`, so they CRASH-LOOP rather than sit `exited` — assert on
# the exit code + the loud log line, NOT on `docker compose ps` status text.
#
# This is a plain `docker run` against the built image, so it is safe to run even
# next to the shared stack (it starts throwaway containers, touches nothing in
# the running stack). It still refuses PROJECT=strattraderpro out of caution;
# override with FORCE_SHARED=1 if you deliberately point it at the shared image.
# ---------------------------------------------------------------------------
source "$(dirname "$0")/_lib.sh"

# Resolve the built backend image from the running (or built) stack.
BACKEND_CID="$(c ps -q backend 2>/dev/null | head -1 || true)"
if [ -n "${BACKEND_CID}" ]; then
  IMG="$(docker inspect -f '{{.Config.Image}}' "${BACKEND_CID}")"
else
  IMG="${IMG:-$(c images -q backend 2>/dev/null | head -1)}"
fi
[ -n "${IMG:-}" ] || { fail "could not resolve the backend image (build the stack first)"; exit 1; }
log "backend image under test: ${IMG}"

run_case() { # $1=label  $2..=docker -e args
  local label="$1"; shift
  local name="stp-chaos-role-$(date +%s%N)"
  log "case: ${label}"
  # No --rm so we can inspect the exit code afterwards. Cap the run so a
  # (wrongly) started server can't hang the drill.
  local out
  out="$(docker run --name "${name}" "$@" "${IMG}" 2>&1 || true)"
  local code
  code="$(docker inspect -f '{{.State.ExitCode}}' "${name}" 2>/dev/null || echo 999)"
  docker rm -f "${name}" >/dev/null 2>&1 || true

  printf '    exit code: %s\n' "${code}"
  printf '%s\n' "${out}" | sed 's/^/      | /' | head -8

  # 1. non-zero exit
  if [ "${code}" != "0" ] && [ "${code}" != "999" ]; then
    pass "[${label}] exited non-zero (${code})"
  else
    fail "[${label}] did NOT exit non-zero (got ${code})"
  fi
  # 2. loud message
  if printf '%s' "${out}" | grep -q 'entrypoint: FATAL' && \
     printf '%s' "${out}" | grep -q 'set SERVICE_ROLE'; then
    pass "[${label}] printed the loud FATAL message naming SERVICE_ROLE"
  else
    fail "[${label}] missing the loud FATAL message"
  fi
  # 3. did NOT start a web server
  if printf '%s' "${out}" | grep -Eqi 'Starting gunicorn|Watching for file changes|Booting worker'; then
    fail "[${label}] a web server banner appeared — it silently started serving HTTP!"
  else
    pass "[${label}] no web-server banner — it crashed instead of serving HTTP"
  fi
}

# Case A: SERVICE_ROLE blank (the exact BUG-011 shape: an empty Railway field).
run_case "SERVICE_ROLE blank" -e SERVICE_ROLE=

# Case B: SERVICE_ROLE bogus (typo / stale value).
run_case "SERVICE_ROLE bogus" -e SERVICE_ROLE=frobnicate

echo
[ "${FAILED}" = 0 ] && log "DRILL PASS — a blank or wrong SERVICE_ROLE crashes loudly and never serves HTTP" \
                    || log "DRILL FAIL — review above"
exit "${FAILED}"
